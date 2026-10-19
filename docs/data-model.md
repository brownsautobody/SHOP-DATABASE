# Database design

**Status:** core tables are built (`db/models.py`). Tables for the later features are still on paper. Every schema
change is an Alembic migration (`migrations/versions/`), run by `python tools/migrate.py` after a backup copy.

Goal: one database that holds every job from the first estimate until it is closed, and that the future web app
(admin page + live production page) can grow on **without rebuilding what already exists**. Features that come later
(production board, who worked on the car, customer communication, parts receiving) only **add** tables; the core
tables built first never change shape.

## Technology
- **PostgreSQL** for the live web app (many people and screens at once). SQLite is fine for local testing - the
  same code runs on both.
- **SQLAlchemy** models + **Alembic** migrations (Python, like the parser). Every feature arrives as a numbered
  migration that creates its tables, so existing data is never rebuilt by hand.
- `estimate_parser/` never talks to the database. A separate `db/` package will have `save_parse(result)` that stores
  the dict `parse_pdf()` already returns (`estimate_parser/core.py`).

## Rules every table follows
1. Every row has `id`, `created_at`, `created_by`, `updated_at`, `updated_by`.
2. **Nothing important is overwritten or deleted.** A supplement is a new document, a stage move is a new row, a
   closed job gets `closed_at` instead of being deleted.
3. **Current state + history.** Live screens read one "current" field (`jobs.current_stage_id`) so they are fast;
   every change also writes a history row (`job_stage_events`) so the full timeline exists.
4. **One change log for everything** - `audit_log` (table, row id, field, old value, new value, user, time) is
   written by the app on every edit. "Who changed the promise date and when?" works for every table, including
   ones added later.
5. **Lists the shop may change live are tables, not code:** repair stages, employee roles, labor types, vendors.
   The admin page edits them.
6. Money is `numeric(10,2)` (Python `Decimal`); times are timezone-aware timestamps kept in UTC and shown in the
   shop's time zone. Printed text (dates, deductible) is typed in its column and kept as printed in the parse JSON.
7. Top-level tables carry `shop_id` (one shop today) so a second location never needs a redesign.
8. Each employee has their own login, so `created_by` / `moved_by` / `received_by` always names a person.

## Core tables (built first - saving parsed estimates)

| Table | Holds | Filled from parser |
|---|---|---|
| `shops` | shop name, address | - |
| `users` | employee name, login, role (admin, front office, body tech, painter, parts...), active | - |
| `customers` | name, phones, email - the same customer only when name (case/spacing ignored) AND phone (digits) match; never merged automatically | `header.customer`, phones |
| `vehicles` | VIN, year, make, model, full description - one row per VIN, shared by its jobs | `header.vehicle` |
| `insurance_companies` | name, matched with case/spacing ignored, stored as printed | `header.insurance` |
| `jobs` | the repair order - see below | `header`, `summary` |
| `estimate_documents` | one row per uploaded PDF, never overwritten - see below | `document`, `review` |
| `estimate_parses` | every reading of a document's PDF: parser version, parse JSON, review reasons, when; the document points at its current one | the whole result |
| `estimate_lines` | itemized rows: category (Part / Body Labor / Paint Labor / Sublet...), line #, operation, description, part #, part type, qty, hours, rate, amount, taxed | `charges` |
| `estimate_totals` | printed totals rows: label, hours, rate, amount, markup/discount | `totals` |
| `files` | any stored file linked to a job: estimate PDF, invoice, photo. File lives on disk / cloud storage; the row keeps path, type, size, uploaded by | uploaded PDF |
| `audit_log` | every edit (rule 4) | - |

**`jobs`** - `ro_number` (CCC prints it; Mitchell doesn't, so it is **typed in by hand**), customer, vehicle,
insurance company, `claim_no`, adjuster, estimator, loss date, deductible, `mileage_in`, `current_document_id`,
`current_stage_id`, key dates `dropped_off_at`, `promised_at`, `delivered_at`, `closed_at` (set by a person, see Closing a job).

**`estimate_documents`** - job, file, `format` (CCC ONE | Mitchell), `title_raw`, `stage` (preliminary | estimate |
to_repair | of_record | unknown), `supplement_no` (0 = original), `printed_at`, `supplement_amount`,
`needs_review` + `review_reasons` (from `review_flags()`), `parser_version`, the `job_numbers()` columns (body /
refinish / mechanical / other / total hours, labor $, parts $, tax $, grand total - lists and reports sum these in
SQL), and `current_parse_id` -> **`estimate_parses`**, which keeps every reading's full parse result as JSON
(printed history table included) so old documents can be re-read if the parser improves.

### How a supplement arrives
1. Upload a PDF -> `parse_pdf()`.
2. Find the job - automatic when sure, a person decides when not (`match_job()` in `db/matching.py`):
   1. same RO # -> that job, unless both estimates print a VIN and the VINs differ (-> a person);
   2. same claim # -> that job only if both print the same VIN; both printed and different -> not this job (one
      accident can bring two cars under one claim #), keep looking; either VIN missing -> a person;
   3. same VIN with an estimate printed within 90 days and no conflicting claim # -> that job;
   4. more than one candidate job at any step -> a person; 5. no match -> new job, Open;
   6. the matched job is closed -> a person (closed jobs are locked).
   "A person" = the upload waits in **`pending_uploads`** (stored file, parse JSON, reason `uncertain_match` |
   `closed_job` | `duplicate_ro`, candidate job ids, created by/at, resolved by/at, resolution + the job and document
   it became). The page shows the reason and candidate jobs with *Add to this job* / *Make a new job*; nothing is
   saved to a job until someone chooses, then it is saved exactly as an automatic match would be (`resolve_pending()`),
   and the choice is in `audit_log`. The job's RO# follows the newest document that prints one, unless a person
   typed it in.
3. Add a new `estimate_documents` row with its lines and totals. Nothing older is touched.
4. `jobs.current_document_id` points at the newest version, chosen by `version_key()` in
   `estimate_parser/core.py`: highest `supplement_no`, then stage rank (unknown < preliminary < estimate < to_repair
   < of_record), then `printed_at`. CCC and Mitchell totals are cumulative, so the newest document holds the whole
   job's numbers; older ones stay as history (what changed, profitability).
5. The job's fields follow its current version: RO #, claim #, adjuster, estimator, loss date, deductible, mileage
   in, customer, insurance company and vehicle - unless a person typed the field in by hand (logged as `manual`). A
   value the current version doesn't print keeps the job's. Every change goes through `set_field()` -> `audit_log`.

## Later features - tables they add

### Live production board (on hold)
A first version was built (commit 44a75d4: stages Blueprint / Body Work / Paint / Reassembly / Detail, one current tech
and estimator per job, stage history, Settings page) and then **removed** so the app could focus on the job list.
It can be brought back from git history. Tables it used:
- `production_stages` - name, display order, active.
- `job_stage_events` - job, from stage, to stage, moved by, moved at, note. Moving a job = new event row + update
  `jobs.current_stage_id`.
- `job_assignments` - job, employee, role (`tech` | `estimator`), assigned at/by, removed at.
- `time_entries` (optional, later) - employee clocks hours on a job: actual vs estimated hours from
  `estimate_lines`.

### Closing a job
Built (`db/closing.py`). A job is closed **for bookkeeping**: only after the file is audited, everything is closed
out, the shop is paid and the numbers are right for bookkeeping. Delivered does **not** mean closed. No payment records
in this app - bookkeeping handles payments.
- **Yes/No checklist per job**, answered by a person (never by an uploaded PDF, its name or contents):
  - `checklist_items` - name, display order (`position`), active, `required_to_close`. Rows, not code (a Settings
    page will edit them). A new database starts with *File audited*, *Everything closed out*, *Paid in full* and
    *Numbers OK for bookkeeping*, all required (`init_db()` adds them when the table is empty).
  - `job_checks` - job, item, yes/no, set by, set at (one row per job and item); every change also in `audit_log`.
- **Close** sets `jobs.closed_at` / `closed_by` (logged as `close`), only when every active required item is Yes.
- **Closed jobs are locked**: an upload matching one waits in `pending_uploads` (`closed_job`) and says the job is
  closed; checklist answers, the RO # and re-read numbers don't change. A person **Reopens** it with a required note
  (`audit_log.note`); the waiting upload can then be added. Reopening keeps the answers, but closing again needs every
  required item Yes again.

### Customer communication (front office)
- `communications` - job, customer, channel (call / text / email / in person), inbound or outbound, summary,
  staff member, time, optional attached file.

### Parts receiving
- `vendors` - name, phone, account #.
- `job_parts` - the parts expected on a job, created from the **Part** rows of an estimate document and linked back
  to that `estimate_lines` row. Status: needed / ordered / received / backordered / returned. A new supplement adds
  only the parts that are new (matched by part #), so check-ins already done are kept.
- `part_invoices` (vendor, invoice #, date, total, file) and `part_invoice_lines` (part #, description, qty, price).
- `part_receipts` - job part, qty received, received by, time, invoice line. Handles partial and split deliveries.
- The parts department **confirms the part # and price** of each part received (who and when are recorded). The
  estimate's printed part # and price stay as they are beside it; a mismatch is shown for a person to resolve,
  never corrected automatically.

### Knowledge base (first source built)
Reference knowledge kept apart from job data: CCC's documentation now; shop rules and context, shop policies and
references to other shop estimates later - each as its own source in the same tables. **Not shown to the shop's
users** - it is context for reading estimate PDFs correctly (labor hours by type, totals) and for answering technical
questions; looked up with `tools/kb_search.py`.
- `kb_sources` - name, kind (`web_docs` | `shop_policy` | `estimate_reference`), base URL, last synced.
- `kb_nodes` - the tree: category / section / article, `parent_id`, title, original URL, order, the page as HTML and as
  plain text (searchable), when the source last updated it. Gone from the source -> `active = false`, never deleted.
- `kb_revisions` - the previous title/body whenever the source changes a page.
- `kb_links` - every link and picture in a page; links to another page in the knowledge base point at its node, so
  "links from" and "linked from" both work.
- CCC: `kb/ccc_help.py` reads cccis.zendesk.com through Zendesk's public Help Center API (the web pages block
  automated visitors; robots.txt allows the API). 1 category, 17 sections, 555 articles. Pictures are kept as links.

## Build order
1. Core tables + save each parsed estimate (built).
2. Job list: every upload filed with its job, Open / Closed jobs; list with printed hours and dollars, search, date filter (built).
3. Bookkeeping export and financial / performance tracking, from `job_numbers()` (next).
4. Web login + admin page.
5. Live production page, closing a job, communication log, parts receiving (later).

Each step only adds tables; nothing built earlier changes shape.

## Rules the database enforces
- `files.sha256` unique: one row per PDF content (the same PDF uploaded again returns what it became).
- `jobs.ro_number` unique where not blank. Filing that would give two jobs the same RO # never crashes: the upload
  waits in `pending_uploads` with reason `duplicate_ro`.
- Re-reading a PDF (`reparse_document()`) adds an `estimate_parses` row instead of overwriting; lines and totals
  follow the current parse. On a closed job a re-read is history only.

## What the page shows today (per document)
- Labor by type: body, paint, mechanical, other - hours, rate, amount; total hours and amount
- Total parts (pre-tax)
- Other price breakdowns: materials, taxes, grand total, deductible, net, etc.
- A "Needs review" box when the parse doesn't match the estimate's own totals

# Database design

**Status:** core tables are built (`db/models.py`). Tables for the later features are still on paper. Until
Alembic migrations are added (before moving to PostgreSQL), missing tables are created at startup by `init_db()`.

Goal: one database that holds every job from the first estimate until it is archived, and that the future web app
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
   finished job gets `archived_at` instead of being deleted.
3. **Current state + history.** Live screens read one "current" field (`jobs.current_stage_id`) so they are fast;
   every change also writes a history row (`job_stage_events`) so the full timeline exists.
4. **One change log for everything** - `audit_log` (table, row id, field, old value, new value, user, time) is
   written by the app on every edit. "Who changed the promise date and when?" works for every table, including
   ones added later.
5. **Lists the shop may change live are tables, not code:** repair stages, employee roles, labor types, vendors.
   The admin page edits them.
6. Money is `numeric(10,2)`; times are timezone-aware timestamps.
7. Top-level tables carry `shop_id` (one shop today) so a second location never needs a redesign.
8. Each employee has their own login, so `created_by` / `moved_by` / `received_by` always names a person.

## Core tables (built first - saving parsed estimates)

| Table | Holds | Filled from parser |
|---|---|---|
| `shops` | shop name, address | - |
| `users` | employee name, login, role (admin, front office, body tech, painter, parts...), active | - |
| `customers` | name, phones, email | `header.customer`, phones |
| `vehicles` | VIN, year, make, model, full description, mileage | `header.vehicle` |
| `insurance_companies` | name | `header.insurance` |
| `jobs` | the repair order - see below | `header`, `summary` |
| `estimate_documents` | one row per uploaded PDF, never overwritten - see below | `document`, `review` |
| `estimate_lines` | itemized rows: category (Part / Body Labor / Paint Labor / Sublet...), line #, operation, description, part #, part type, qty, hours, rate, amount, taxed | `charges` |
| `estimate_totals` | printed totals rows: label, hours, rate, amount, markup/discount | `totals` |
| `files` | any stored file linked to a job: estimate PDF, invoice, photo. File lives on disk / cloud storage; the row keeps path, type, size, uploaded by | uploaded PDF |
| `audit_log` | every edit (rule 4) | - |

**`jobs`** - `ro_number` (CCC prints it; Mitchell doesn't, so it is **typed in by hand**), customer, vehicle,
insurance company, `claim_no`, adjuster, estimator, loss date, deductible, `current_document_id`,
`current_stage_id`, key dates `dropped_off_at`, `promised_at`, `delivered_at`, `archived_at`.

**`estimate_documents`** - job, file, `format` (CCC ONE | Mitchell), `title_raw`, `stage` (preliminary | estimate |
to_repair | of_record | unknown), `supplement_no` (0 = original), `printed_at`, `supplement_amount`,
`needs_review` + `review_reasons` (from `review_flags()`), `parser_version`, and the **full parse result as JSON**
(printed history table included) so old documents can be re-read if the parser improves.

### How a supplement arrives
1. Upload a PDF -> `parse_pdf()`.
2. Find the job: RO# first, then claim #, then VIN. None found -> new job.
3. Add a new `estimate_documents` row with its lines and totals. Nothing older is touched.
4. `jobs.current_document_id` points at the newest version, chosen by `version_key()` in
   `estimate_parser/core.py`: highest `supplement_no`, then stage rank (unknown < preliminary < estimate < to_repair
   < of_record), then `printed_at`. CCC and Mitchell totals are cumulative, so the newest document holds the whole
   job's numbers; older ones stay as history (what changed, profitability).

## Later features - tables they add

### Live production board (first part built - `db/production.py`, Active jobs page, Settings page)
- **Built:** `production_stages` - name, display order, active (edited on Settings). Starts with Blueprint,
  Body Work, Paint, Reassembly, Detail. A job with no stage yet is "Not started".
- **Built:** `job_stage_events` - job, from stage, to stage, moved by, moved at, note. Gives "dropped off Monday, in
  paint Wednesday" and time spent in each stage. Moving a job = new event row + update `jobs.current_stage_id`.
- **Built:** `job_assignments` - job, employee, role (`tech` | `estimator`), assigned at/by, removed at. One current
  tech and one current estimator per job; a change ends the old row, so hand-offs are kept. Employees are `users`
  rows (a placeholder login until real logins exist). `jobs.estimator` stays the name *printed on the estimate*.
- `time_entries` (optional, later) - employee clocks hours on a job: actual vs estimated hours from
  `estimate_lines`.

### Closing a job (planned)
- Delivered does **not** mean archived. Order: Delivered -> Final bill sent -> All payments received -> Archived.
- **Yes/No checklist per job**, confirmed by a person (never set by an uploaded PDF, its name or contents):
  - `checklist_items` - name, display order, active, `required_to_archive`. Edited on Settings, so new items need
    no code. Starts with *Final bill sent* and *All payments received*.
  - `job_checks` - job, item, yes/no, set by, set at; every change also in `audit_log`.
- Payments that arrive after the final bill need their own record (e.g. `payments`: job, payer insurance/customer,
  amount, date, method, recorded by); the estimate's printed "Received from / Balance due" rows are only what was
  printed at the time.
- Archive sets `jobs.archived_at` (logged as `archive`), only when every required checklist item is Yes; an
  archived-jobs list can un-archive.

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
2. Web login + admin page (employees and stages are on Settings; logins not yet).
3. Live production page (stage events, assignments - first part built; closing a job next).
4. Communication log.
5. Parts receiving.

Each step only adds tables; nothing built earlier changes shape.

## What the page shows today (per document)
- Labor by type: body, paint, mechanical, other - hours, rate, amount; total hours and amount
- Total parts (pre-tax)
- Other price breakdowns: materials, taxes, grand total, deductible, net, etc.
- A "Needs review" box when the parse doesn't match the estimate's own totals

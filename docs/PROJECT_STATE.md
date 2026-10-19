# Project state - Shop Database

The current picture of the project in one page: what works, how it fits together, what's next.
**Update this file in the same commit as any change to features, pages, tables, tools or plans** (a git hook checks).
Read this first instead of re-reading the code; open the files named here only when you need the detail.

Last updated: 2026-10-19 (branch `refactor-foundation`: the parser / database refactor, Steps 0-6, done)

## What it is
Brown's Body Shop's job database. Upload a CCC ONE or Mitchell estimate PDF -> it's read, checked against its own
printed totals, and filed with its job (every version kept). Goal: one source of truth for every job, later feeding
bookkeeping exports, production board, customer communication and parts receiving.
Stack: Python, pdfplumber, Flask (HTML built in Python, no templates), SQLAlchemy, SQLite (`data/shop.db`; PostgreSQL via
`DATABASE_URL`). Runs locally: `python app.py` -> http://127.0.0.1:5000.

## Phase status
| Phase | Status |
|---|---|
| 1. Estimate PDF parsing + display + "Needs review" checks | Built; tested on 54 real 2026 CCC estimates + Mitchell samples |
| 2. Core tables, save every upload to its job, job list, job page | Built |
| 2b. Open / Closed jobs; closing for bookkeeping with a required checklist, closed jobs locked | Built |
| 3. Bookkeeping export, financial / performance tracking (from `job_numbers()`) | **Next** |
| 4. Web login + admin page | Not started (`users` table exists, `user_id` is always None) |
| 5. Production board, communication log, parts receiving | Designed in `docs/data-model.md`; production board was built once (commit 44a75d4) then removed |

## Features (what a user can do today)
- **Upload estimate** (`/`): CCC ONE or Mitchell, estimate or supplement, max 25 MB. Unparseable PDFs show the reason.
- **Parsing** - only values the PDF prints, never calculated: customer (vehicle owner, not the insured on liability
  claims), phone (CCC; Mitchell only when printed in the Owner column - none of the samples do), vehicle
  (VIN/year/make/model/mileage), insurance, claim #, RO # as printed (CCC; Mitchell prints none - typed in by hand;
  Mitchell's Estimate ID is kept as `estimate_id`), adjuster, estimator, loss date, deductible; line items split into
  Part / Sublet / Other Charge and the labor types in `estimate_parser/labor.py` (Body, Paint, Mechanical, Structural,
  Frame, Electrical, Diagnostic, Glass, or a type the shop made up) as the estimate prints them; totals rows;
  supplement history; document type + print time. CCC is recognised by its own labels first ('Mitchell' can be a
  customer or street name). Amounts are exact `Decimal`s read from the printed text; every sum is in Decimal.
- **Needs review** flag when: labor hours by type or total don't match printed totals, parts/charges total doesn't
  match, history doesn't add up, document type unknown, or no print date (`review_flags()`).
- **Job matching - automatic when sure, a person decides when not** (`match_job()` in `db/matching.py`):
  1. same RO # -> that job, unless both print a VIN and they differ; 2. same claim # -> that job only when both print
  the same VIN (different VINs = another car on the claim, keep looking; a VIN missing = ask); 3. same VIN with an
  estimate printed within 90 days and no conflicting claim # -> that job; more than one candidate -> ask; no match ->
  new job; matched job closed -> ask. "Ask" holds the upload in `pending_uploads`: the **Waiting for a person** page
  (`/pending`, `/pending/<id>`) shows why, the upload and the candidate jobs with **Add to this job** / **Make a new
  job**. Nothing is filed until a person chooses; then it is saved exactly like an automatic match, and logged.
  A closed job can't be chosen until it is reopened. Same PDF uploaded twice = one copy (sha256), also while waiting.
- **Versions**: newest = highest supplement #, then stage (prelim < estimate < to repair < of record), then print time
  (`version_key()`).
- **Job fields - one rule** (`_follow_current()` in `db/save.py`): RO #, claim #, adjuster, estimator, loss date,
  deductible, mileage in, customer, insurance company and vehicle follow the job's current version, unless a person
  typed the field in by hand (`typed_by_hand()`: any field set with action `manual`). A value the current version
  doesn't print keeps the job's. Every change goes through `set_field()`.
- **Vehicles** are shared by every job on the same VIN (no VIN -> a new record); mileage is per job (`mileage_in`).
  **Customers** are the same only when name (case/spacing ignored) AND phone (digits) match - never on name alone;
  a missing phone means a new customer (a supplement of the same job with the same name keeps the job's customer).
  **Insurance companies** match by name, case/spacing ignored, stored as printed. Existing rows are never merged.
- **Jobs list** (`/jobs`): Open / Closed / All tabs; columns body / refinish / mech / other / total hours, labor $,
  parts $, tax $, grand total + totals row; search RO #, customer, VIN, claim #, insurance; date filter on estimate
  print date in the shop's time zone (range, This month / Last month / This year). Numbers come only from
  `job_numbers()`; hours by type are the estimate's printed labor totals rows (lines only when it prints none). The
  numbers are saved on each document when it is saved or re-read, and the list's search, filters, sort (newest
  print time first) and totals row run in SQL (`job_list_query()` in `app.py`).
- **Closing for bookkeeping** (`db/closing.py`): a Yes/No checklist per job (File audited, Everything closed out, Paid
  in full, Numbers OK for bookkeeping - rows in `checklist_items`, all required); **Close** only when every required
  item is Yes (sets `closed_at` / `closed_by`). A closed job is **locked** - new estimates for it wait for a person,
  its checklist, RO # and re-read numbers don't change - until a person **Reopens** it with a required note
  (`audit_log.note`). Reopening keeps the answers; closing again needs them all Yes again. No payments in this app.
- **Job page** (`/jobs/<id>`): header, Open/Closed status with the closing checklist and Close / Reopen, a tab per estimate version,
  needs-review reasons, hours and money as printed, job details (RO # editable), documents with PDF links.
- **Document names**: every stored PDF downloads as `LAST-RO-TYPE.pdf` (e.g. `BOATMAN-4403-PRELIM-SUPPLEMENT-1.pdf`);
  the uploaded name is kept too.
- **Rules the database enforces**: one `files` row per PDF content (unique sha256); one job per RO # (unique where
  not blank). Filing that would repeat an RO # goes to a person as `duplicate_ro` (`ro_conflict()` checks first; a
  person's choice that would repeat one keeps the upload waiting); typing an RO # another job has is refused.
- **Parse history**: every reading of a PDF is a row in `estimate_parses`; the document points at its current one
  (`current_parse_id`; `doc.parse` reads it) and its numbers, lines and totals follow it. `tools/reparse_documents.py`
  adds a reading for each document; on a **closed** job it is history only (numbers unchanged) and the tool prints
  what would change. It also prints every job field a re-read changes.
- **Change log**: every field change written to `audit_log` (create / update / manual / close / reopen / reparse) -
  not shown in the app yet.
- **Knowledge base** (no screen): CCC ONE help center copied locally (555 articles) for reading estimates correctly;
  `tools/kb_search.py <words>`, `--show <id>`, `--tree`.

## Tests and database changes
- **Run the tests:** `python -m pytest` (from WSL use `python.exe -m pytest`; packages live in the Windows Python).
  - `tests/test_parser_snapshots.py` parses every PDF in `samples/` and `data/test2026/files/` (68 today) and compares
    the full `parse_pdf()` result with `tests/snapshots/<sha256>.json`; a failure lists each value that changed.
    Accept changes with `python -m pytest --update-snapshots`. Snapshots hold customer data, so they're git-ignored.
    The Step 0 baseline is frozen in `data/snapshots-baseline-step0/` for comparing the whole refactor.
  - `tests/test_matching.py` - which job an upload is filed with, from small hand-made parses (no customer data),
    one case per rule where its two conditions disagree. `tests/test_pending.py` - the Waiting for a person pages.
  - `tests/test_jobs_list.py`, `tests/test_values.py` - the jobs list in SQL; printed text -> typed values.
  - `tests/test_job_fields.py` - vehicles by VIN, customers by name + phone, insurance by name, fields follow the
    current version unless typed by hand.
  - `tests/test_rules_db.py` - unique rules, duplicate RO #, parse history; `tests/test_reparse_tool.py` - the
    re-read tool on a sample PDF (closed job kept, reopened job follows).
  - `tests/test_closing.py` - the closing checklist, locked closed jobs, reopen with a note.
  - `tests/fakes.py` - hand-made estimates (`make()`) and `upload()` for tests.
  - `tests/test_parser_rules.py` - parser rules on hand-made inputs (format detection, RO #, labor types, printed
    hours, exact money, Mitchell owner phone).
  - `tests/test_migrations.py` - the migrations build exactly the tables in `db/models.py`.
  - `python tests/snapshot_report.py [folder] [--detail]` - which fields changed against the snapshots (or against
    `data/snapshots-baseline-step0`), grouped by field.
- **Schema changes are Alembic migrations** in `migrations/versions/` (0001 baseline = schema before Alembic,
  0002 `archived_at` -> `closed_at`, 0003 typed print time / loss date / deductible + saved job numbers,
  0004 `pending_uploads`, 0005 `jobs.mileage_in` copied from vehicles, `vehicles.mileage` dropped, 0006
  `estimate_parses` (each stored parse copied in as the first reading), unique sha256 and RO #, 0007 closing
  checklist tables, `jobs.closed_by`, `audit_log.note`). Update a database with `python tools/migrate.py`: it stamps a pre-Alembic
  database, then backs it up to `<data folder>/backups/<name>-YYYYMMDD-HHMM-before-<migration>.db` before each
  migration. A new database is created from the models and stamped; the app refuses to start on an out-of-date one.
  `tools/reparse_documents.py` also backs up first (`...-before-reparse.db`).

## Routes (`app.py`)
`/` upload · `/jobs` list (`?status=open|closed|all&q=&start=&end=`) · `/jobs/<id>` (`?v=<doc id>`) ·
POST `/jobs/<id>/ro`, `/jobs/<id>/check` (`item`, `value` yes|no), `/jobs/<id>/close`, `/jobs/<id>/reopen` (`note`) · `/pending` list, `/pending/<id>`, POST
`/pending/<id>/resolve` (`job_id` = a candidate job or `new`) · `/files/<id>` PDF download ·
`/documents/<id>`, `/closed`, `/archive` redirects for old links.

## Code map
- `estimate_parser/core.py` - `parse_pdf()`, format detection, `classify_document()`, `_checks()`, `review_flags()`,
  `version_key()`, `job_numbers()` + `NUMBER_FIELDS`, `doc_file_name()`, `PARSER_VERSION` (bump when parsing changes)
- `estimate_parser/ccc.py`, `mitchell.py` - one parser per format (header, items, totals, history)
- `estimate_parser/labor.py` - the one list of labor types and how each format prints them
- `estimate_parser/pdfutil.py` - PDF rows / number helpers (`num()`, `dec()` -> Decimal)
- `estimate_parser/render.py` - all HTML; job page = `JOB_SECTIONS` list (new feature = add a section function)
- `db/values.py` - printed text -> typed values (`printed_time()` shop time -> UTC, `printed_date()`,
  `printed_money()`), `SHOP_TZ` (America/Chicago; `SHOP_TIMEZONE` overrides), shop-day bounds
- `db/closing.py` - checklist, `close_job()`, `reopen_job()`, `DEFAULT_ITEMS`, `seed()`
- `db/matching.py` - `match_job()`: the matching rules, `REASONS` for a person
- `db/models.py` - tables (`UtcDateTime` column type: stored UTC, read back time-zone aware); `db/save.py` - `save_parse()` (-> `Saved`: document or pending), `resolve_pending()`, `reparse_document()`,
  `set_field()` (logs);
  `db/session.py` - engine, `init_db()` (new database: create + stamp; old schema: refuse); `db/migrate.py` -
  Alembic helpers, `backup()`; `migrations/` + `alembic.ini`
- `kb/ccc_help.py` + `tools/sync_ccc_kb.py` - knowledge base sync
- `tools/load_samples.py` (load `samples/` into a DB), `tools/reparse_documents.py` (re-read saved PDFs after a parser
  change, `--all`), `tools/reopen_jobs.py` (one-time: reopen jobs auto-filed as finished), `tools/migrate.py`

## Database (built tables)
shops, users, customers, vehicles (shared per VIN), insurance_companies, jobs (RO # unique when not blank;
`closed_at` = closed by a person;
`loss_date` date, `deductible` numeric, `mileage_in`), files (sha256 unique),
estimate_documents (`current_parse_id` -> estimate_parses, the history of every reading; `printed_at` UTC time; the `job_numbers()` columns body_hours ...
grand_total), pending_uploads (upload waiting for a person: file, parse, reason, candidates, resolution),
estimate_lines, estimate_totals, checklist_items, job_checks, audit_log (with `note`), kb_sources / kb_nodes /
kb_revisions / kb_links. Rules: nothing important overwritten or deleted; every change in `audit_log`; later
features only add tables. Full design and future tables: `docs/data-model.md`.

## Data on this machine (git-ignored, customer data)
- `data/shop.db` - real database: 2 jobs, 2 documents (parser 2026.10.14), knowledge base loaded.
- `data/test2026/shop.db` - test copy of 54 real 2026 CCC estimates / 41 jobs (all closed - they were filed as
  archived). Migrated to 0007; re-read with parser 2026.10.19b on 2026-10-19 (history only, nothing changed: closed).
  Backups before every migration and re-read in `data/test2026/backups/`.
- `data/test/` - older sample test copy (migrated to 0002). `samples/` - sample PDFs (7 CCC, 7 Mitchell).
- To use a test copy: `SHOP_DATA_DIR=data\test2026` (Windows `set SHOP_DATA_DIR=data\test2026`; from WSL also
  `WSLENV=SHOP_DATA_DIR`). Stored file paths are Windows paths, so run the tools with the Windows Python.

## Known gaps / to-dos
- No login; `created_by` / `user_id` always empty.
- No Settings page yet: checklist items are edited in the database.
- `data/test2026` (41) and `data/test` (15) jobs are all closed: they were filed as archived automatically before
  closing was a person's choice. `tools/reopen_jobs.py` reopens them (with a note) if their numbers should follow
  re-reads.
- SQLite has no exact decimal type: it keeps numeric columns as floating point, and SQLAlchemy rounds them back to
  2 places when reading (SQL sums too). Exact end to end on PostgreSQL. Python-side sums are always Decimal.
- Migration 0001 is SQLite-shaped (jobs <-> estimate_documents and shops <-> users point at each other); check it
  before the first PostgreSQL database.
- Leftover production-board tables (`production_stages`, `job_assignments`, `job_stage_events`) sit in `data/shop.db`
  and `data/test/`; migrations leave them alone.
- `Job.current_stage_id`, `dropped_off_at`, `promised_at`, `delivered_at` exist but nothing uses them.
- Line endings: files are CRLF (Windows). Git under WSL shows every line changed - use Windows git, or set
  `core.autocrlf=true` in the WSL git config before committing from WSL.
- Python packages are installed on Windows only, not in WSL.
- `data/test2026` holds one VIN on two vehicle rows (two jobs, from before vehicles were shared); new uploads use the
  oldest. A merge tool for customers / vehicles would come later - nothing merges automatically.
- Old branches `core-database`, `database-design`, `worktree-needs-review-flag` and a prunable worktree remain.

## Refactor results (2026-10-19, `data/test2026`, 54 real CCC estimates)
- Snapshot changes since the Step 0 baseline: 18 of 68 PDFs, only `header.loss_date` 'Days' -> '' (11, CCC blank
  loss date) and Mitchell `header.ro_number` -> `header.estimate_id` (7). No hours or dollars changed.
- Matching: replaying the 54 uploads in their original order gives the same 41 jobs with the old and new rules;
  nothing goes to Waiting for a person.
- `reparse_documents.py --all`: 54 re-read, 0 numbers changed. On a copy with the jobs reopened, job fields follow the
  current version on 5 jobs: 1 and 7 insurance name as printed now, 2 estimator / mileage / customer case / insurance
  filled, 7 customer CURRIE -> Curry (spelling on the newer estimate), 29 the longer printed customer name, and
  **job 6 customer IMO, STEVEN-AND-TRACY -> CHESSER, DON - worth a look** (the newest version names a different owner).

## Change history (newest first; add one line per commit)
- 2026-10-19 - Refactor Step 6: closing for bookkeeping - checklist (migration 0007), Close only when all required
  items are Yes, closed jobs locked, Reopen with a required note.
- 2026-10-19 - Refactor Step 5: migration 0006 - unique files.sha256 and jobs.ro_number, `estimate_parses` history;
  duplicate RO # -> a person; re-reads keep history and never change a closed job's numbers.
- 2026-10-19 - Refactor Step 4: vehicles shared per VIN, mileage on the job (migration 0005), customers by name AND
  phone, insurance by normalized name, every job field follows the current version unless typed by hand.
- 2026-10-19 - Refactor Step 3: matching rules (`db/matching.py`) - automatic when sure, otherwise
  `pending_uploads` (migration 0004) and the Waiting for a person pages.
- 2026-10-19 - Refactor Step 2: migration 0003 (printed_at UTC time, loss_date date, deductible numeric, job numbers
  saved per document); jobs list in SQL; shop time zone; CCC blank loss date no longer reads 'Days' (parser 2026.10.19b).
- 2026-10-19 - Refactor Step 1: parser 2026.10.19 - CCC detected before Mitchell, RO # kept as printed, one labor
  list (CCC glass = Glass Labor), job hours from printed labor rows, Decimal money, Mitchell owner phone.
- 2026-10-19 - Refactor Step 0: pytest snapshot + matching + migration tests, Alembic (0001 baseline, 0002 rename),
  `tools/migrate.py` with backups, backup before reparse.
- 2026-10-16 - Open / Closed jobs: Close / Reopen button, list tabs, `archived_at` -> `closed_at`; customer = vehicle
  owner (CCC); multi-line CCC notes; parser 2026.10.14; `tools/reopen_jobs.py`, `tools/reparse_documents.py`; added this file + CLAUDE.md + pre-commit check.
- d52e757 - Every stored document named LAST-RO-TYPE.pdf.
- 387be61 - Fixes from 54 real 2026 CCC estimates: open lines, blank header fields, job matching.
- 7bc114a / e672b19 - Job archive: job list with printed hours and dollars, one page per job.
- df04591 - Knowledge base: CCC help center copy.
- 34f938b - Archive / move back to active.
- 44a75d4 - Production board (stages, tech/estimator, settings) - later removed.
- 172dd17 / 109af75 - Parser keeps printed values only; `reparse_document`.

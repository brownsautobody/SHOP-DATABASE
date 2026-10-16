# Project state - Shop Database

The current picture of the project in one page: what works, how it fits together, what's next.
**Update this file in the same commit as any change to features, pages, tables, tools or plans** (a git hook checks).
Read this first instead of re-reading the code; open the files named here only when you need the detail.

Last updated: 2026-10-16

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
| 2b. Open / Closed jobs (close/reopen by a person) | Built |
| 3. Bookkeeping export, financial / performance tracking (from `job_numbers()`) | **Next** |
| 4. Web login + admin page | Not started (`users` table exists, `user_id` is always None) |
| 5. Production board, close-job checklist, communication log, parts receiving | Designed in `docs/data-model.md`; production board was built once (commit 44a75d4) then removed |

## Features (what a user can do today)
- **Upload estimate** (`/`): CCC ONE or Mitchell, estimate or supplement, max 25 MB. Unparseable PDFs show the reason.
- **Parsing** - only values the PDF prints, never calculated: customer (vehicle owner, not the insured on liability
  claims), phone, vehicle (VIN/year/make/model/mileage), insurance, claim #, RO # (CCC only), adjuster, estimator,
  loss date, deductible; line items split into Part / Body / Paint / Mechanical / Structural / Frame / Electrical /
  Diagnostic / Glass Labor / Sublet / Other Charge; totals rows; supplement history; document type + print time.
- **Needs review** flag when: labor hours by type or total don't match printed totals, parts/charges total doesn't
  match, history doesn't add up, document type unknown, or no print date (`review_flags()`).
- **Job matching** (`find_job()`): RO # -> claim # -> same VIN printed within 90 days with no conflicting claim #.
  Else a new job. Same PDF uploaded twice = one copy (sha256).
- **Versions**: newest = highest supplement #, then stage (prelim < estimate < to repair < of record), then print time
  (`version_key()`). Job's RO # and customer follow the newest version unless the RO # was typed by hand.
- **Jobs list** (`/jobs`): Open / Closed / All tabs; columns body / refinish / mech / other / total hours, labor $,
  parts $, tax $, grand total + totals row; search RO #, customer, VIN, claim #, insurance; date filter on estimate
  print date (range, This month / Last month / This year). Numbers come only from `job_numbers()`.
- **Job page** (`/jobs/<id>`): header, Open/Closed status with Close / Reopen button, a tab per estimate version,
  needs-review reasons, hours and money as printed, job details (RO # editable), documents with PDF links.
- **Document names**: every stored PDF downloads as `LAST-RO-TYPE.pdf` (e.g. `BOATMAN-4403-PRELIM-SUPPLEMENT-1.pdf`);
  the uploaded name is kept too.
- **Change log**: every field change written to `audit_log` (create / update / manual / close / reopen / reparse) -
  not shown in the app yet.
- **Knowledge base** (no screen): CCC ONE help center copied locally (555 articles) for reading estimates correctly;
  `tools/kb_search.py <words>`, `--show <id>`, `--tree`.

## Routes (`app.py`)
`/` upload · `/jobs` list (`?status=open|closed|all&q=&start=&end=`) · `/jobs/<id>` (`?v=<doc id>`) ·
POST `/jobs/<id>/ro`, `/jobs/<id>/close`, `/jobs/<id>/reopen` · `/files/<id>` PDF download ·
`/documents/<id>`, `/closed`, `/archive` redirects for old links.

## Code map
- `estimate_parser/core.py` - `parse_pdf()`, format detection, `classify_document()`, `_checks()`, `review_flags()`,
  `version_key()`, `job_numbers()` + `NUMBER_FIELDS`, `doc_file_name()`, `PARSER_VERSION` (bump when parsing changes)
- `estimate_parser/ccc.py`, `mitchell.py` - one parser per format (header, items, totals, history)
- `estimate_parser/pdfutil.py` - PDF rows / number helpers
- `estimate_parser/render.py` - all HTML; job page = `JOB_SECTIONS` list (new feature = add a section function)
- `db/models.py` - tables; `db/save.py` - `save_parse()`, `reparse_document()`, `find_job()`, `set_field()` (logs);
  `db/session.py` - engine, `init_db()` creates missing tables + small one-off column renames (no Alembic yet)
- `kb/ccc_help.py` + `tools/sync_ccc_kb.py` - knowledge base sync
- `tools/load_samples.py` (load `samples/` into a DB), `tools/reparse_documents.py` (re-read saved PDFs after a parser
  change, `--all`), `tools/reopen_jobs.py` (one-time: reopen jobs auto-filed as finished)

## Database (built tables)
shops, users, customers, vehicles, insurance_companies, jobs (`closed_at` = closed by a person), files,
estimate_documents (full parse JSON kept), estimate_lines, estimate_totals, audit_log, kb_sources / kb_nodes /
kb_revisions / kb_links. Rules: nothing important overwritten or deleted; every change in `audit_log`; later
features only add tables. Full design and future tables: `docs/data-model.md`.

## Data on this machine (git-ignored, customer data)
- `data/shop.db` - real database: 2 jobs, 2 documents (parser 2026.10.14), knowledge base loaded.
- `data/test2026/shop.db` - test copy of 54 real 2026 CCC estimates / 41 jobs, still on parser 2026.10.13b and the
  old `archived_at` column (renamed automatically on next start; run `tools/reparse_documents.py` to update parses).
- `data/test/` - older sample test copy. `samples/` - sample PDFs.

## Known gaps / to-dos
- No automated tests; checking is done by loading real PDFs and watching for "Needs review".
- No login; `created_by` / `user_id` always empty.
- Close job has no checklist yet (planned: Final bill sent / All payments received / Audits done gate it).
- Schema changes are hand-written in `init_db()`; add Alembic before PostgreSQL.
- Job list loads every job and filters in Python - fine at this size.
- `Job.current_stage_id`, `dropped_off_at`, `promised_at`, `delivered_at` exist but nothing uses them.
- README's test-database command is broken: `set SHOP_DATA_DIR=data<TAB>est` should be `data\test`.
- Line endings: files are CRLF (Windows). Git under WSL shows every line changed - use Windows git, or set
  `core.autocrlf=true` in the WSL git config before committing from WSL.
- Python packages are installed on Windows only, not in WSL.
- Old branches `core-database`, `database-design`, `worktree-needs-review-flag` and a prunable worktree remain.

## Change history (newest first; add one line per commit)
- 2026-10-16 - Open / Closed jobs: Close / Reopen button, list tabs, `archived_at` -> `closed_at`; customer = vehicle
  owner (CCC); multi-line CCC notes; parser 2026.10.14; `tools/reopen_jobs.py`, `tools/reparse_documents.py`; added this file + CLAUDE.md + pre-commit check.
- d52e757 - Every stored document named LAST-RO-TYPE.pdf.
- 387be61 - Fixes from 54 real 2026 CCC estimates: open lines, blank header fields, job matching.
- 7bc114a / e672b19 - Job archive: job list with printed hours and dollars, one page per job.
- df04591 - Knowledge base: CCC help center copy.
- 34f938b - Archive / move back to active.
- 44a75d4 - Production board (stages, tech/estimator, settings) - later removed.
- 172dd17 / 109af75 - Parser keeps printed values only; `reparse_document`.

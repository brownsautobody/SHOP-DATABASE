# Shop Database (shop-database-v1-app)

Brown's Body Shop's job database: reads CCC ONE / Mitchell estimates, saves every job and estimate version, and
grows into the production board, customer communication log and parts receiving (see `docs/data-model.md`).
Originally started as `parts-list-v1`.

## Project Prompt

Auto Body Shop Database System — Project Overview
Business Need

Build a centralized database system for [Shop Name] to manage all job information, documentation, and shop operations. Currently, job data is scattered across estimate PDFs, spreadsheets, and email. This system will become the single source of truth for all shop operations.

Long-Term Vision (Full System)

The completed system will:

Centralize all job data — estimates, labor, parts, status, documents (invoices, communications, photos)
Feed downstream tools that shop staff use daily:
Parts receiving document (updates inventory, links to jobs)
Production/shop board (shows job status in real-time)
Job tracking (open and closed jobs)
Customer communications and invoicing
Enable data-driven decisions — job profitability, turnaround time, parts costs, etc.
Phase 1: PDF Extraction & Data Display (THIS SPRINT)

Goal: Build a PDF ingestion tool that can reliably extract estimate data and display it in a structured format.

Scope:

Upload estimate PDF from CCC ONE or Mitchell (estimates and supplements)
Extract only what the estimate prints - the parser never calculates or fills in values:
Customer name and contact info
Vehicle info (year, make, model, VIN)
Insurance company, claim #, RO # (CCC prints it; Mitchell's is typed in by hand)
Labor line items (description, operation, labor type, hours) - labor dollars and rates come from the printed labor totals
Parts line items (description, part #, part type, quantity, price as printed)
Other charges and sublet (description, amount as printed)
Estimate totals as printed (labor by type, parts, materials, tax, grand total)
Display extracted data in a clean table format
Validate accuracy: compare what was read against the estimate's own printed totals and flag "Needs review" when they don't match

Deliverable:

Working tool that reliably parses estimate PDFs and displays results
Code is modular so the parser can be reused when building the database later

Success Criteria:

Correctly extracts 90%+ of data from a sample estimate PDF
Handles formatting variations in the estimate document
Easy to iterate on if extraction misses anything
Phase 2 & Beyond (Future)
Create database schema based on extracted data structure
Build REST API for job CRUD operations
Integrate PDF parser into job creation workflow
Add document storage (linking files to jobs)
Build production board and parts receiving tools
Add user permissions and audit logging
Technical Approach
Language: Python (for fast iteration)
PDF parsing: pdfplumber
Display: Flask upload page showing HTML tables (upload a PDF, see the itemized result)
Storage: Git repo, pushing incrementally
Next step: Once parsing is solid, create database schema to match this data structure

---

## Phase 1 status: built

Supports **CCC ONE** and **Mitchell** estimate/supplement PDFs (all pages read). Each charge is itemized as
Part, Body / Paint / Mechanical (and Structural, Frame...) Labor, Sublet or Other Charge. Every parse is checked against
the estimate's own totals (labor hours by type, parts/charges total, supplement history). If a check fails or the
document type / print time can't be read, the page shows a red "Needs review" box listing why.

## Phase 2 status: job list built (open and closed jobs)

The app's job for now: **a clean, organized record of every job and its estimate documents**, the base for
tracking financials and performance and for bookkeeping exports later.

A job is **Open** until a person closes it **for bookkeeping**: the job page's checklist (File audited, Everything
closed out, Paid in full, Numbers OK for bookkeeping) must all be Yes. A closed job is locked until someone reopens it
with a note - an uploaded PDF never closes or changes one. Every change is logged.

Every uploaded estimate is filed with its job when the match is sure - same RO #, or same claim # and VIN, or the same
VIN within 90 days - and waits on the **Waiting for a person** page when it isn't (VINs that disagree, several
possible jobs, a closed job, an RO # another job has). Nothing is filed until a person chooses. The job's RO# follows its newest document; a supplement becomes a new version of the same job
and the newest version becomes the job's current estimate. Uploading the same PDF twice keeps one copy.

Pages:
- **Upload estimate**
- **Jobs** - Open / Closed / All jobs, each with its current estimate's printed numbers: body / refinish / mechanical / total hours, labor $,
  parts $, tax $, grand total, plus a totals row. Search by RO #, customer, VIN, claim # or insurance; filter by the
  estimate's printed date (date range, or This month / Last month / This year).
- Every stored document is named **LAST-RO-TYPE.pdf** (e.g. `BOATMAN-4403-PRELIM-SUPPLEMENT-1.pdf`; no RO # yet:
  `LAST-TYPE.pdf`), from the job's customer and RO # and the document's title - `doc_file_name()` in
  `estimate_parser/core.py`. The name it was uploaded with is kept too.
- **One page per job** - labor hours and totals as printed, a tab per estimate version, job details (RO # editable),
  and its documents with their PDFs. The page is a list of sections (`JOB_SECTIONS` in `estimate_parser/render.py`) -
  a new feature adds a section.

The numbers in the list come from one function, `job_numbers()` in `estimate_parser/core.py` - the same numbers a
bookkeeping export will use. Every change is still recorded in `audit_log`; it just isn't shown.

To try things without touching the real data, load the sample PDFs into a separate test database:

```
set SHOP_DATA_DIR=data\test
python tools/load_samples.py
python app.py
```

The database is a SQLite file at `data/shop.db` and the PDFs are kept in `data/files/` - both ignored by git so
customer data stays local. Set `DATABASE_URL` to use PostgreSQL instead, or `SHOP_DATA_DIR` to keep the data
somewhere else.

### Run it

```
pip install -r requirements.txt
python tools/migrate.py   # update the database's tables (backs it up first)
python app.py             # then open http://127.0.0.1:5000 and upload a PDF
python -m pytest          # the tests (parser snapshots, matching, closing, ...)
```

Put test PDFs in `samples/` (ignored by git so customer data stays local).

### Layout

- `estimate_parser/ccc.py`, `mitchell.py` - one parser per format (header, line items, totals)
- `estimate_parser/core.py` - format detection, `parse_pdf()`, validation checks
- `estimate_parser/render.py` - HTML pages
- `db/models.py` - database tables; `db/save.py` - `save_parse()` and change logging; `db/session.py` - connection
- `tools/load_samples.py` - save every PDF in `samples/` into the database (for a test copy);
  `tools/reopen_jobs.py` - one-time: reopen every job (uploads used to mark jobs finished automatically)
- `tools/reparse_documents.py` - re-read saved estimates from their PDFs after the parser changes (`--all` for every one)
- `kb/ccc_help.py` - copies CCC's public help center (cccis.zendesk.com, through its public Help Center API) into the
  knowledge base; `tools/sync_ccc_kb.py` runs it. The knowledge base has no screen in the app - it is reference for
  reading estimates correctly (labor hours, totals) and for technical questions: `tools/kb_search.py labor hours`,
  `--show <id>` for one article, `--tree` for the whole tree
- `app.py` - the web app
- `docs/data-model.md` - database design for the web app (jobs, estimates, closing jobs, later: production board, customer
  communication, parts receiving) and the order to build it in

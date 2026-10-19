"""Re-read saved estimates from their stored PDFs after the parser changes:   python tools/reparse_documents.py [--all]
(default: only documents read by an older parser version; --all: every document). Backs the database up first.

Every new reading is added to the document's parse history (estimate_parses). Open jobs: the document's numbers,
lines and totals follow it, and so do the job's fields (fields typed in by hand are kept). Closed jobs: history
only - their numbers don't change; what would change is printed. Each change is logged."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from db import migrate  # noqa: E402
from db.models import EstimateDocument  # noqa: E402
from db.save import DuplicateRO, reparse_document  # noqa: E402
from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402
from estimate_parser.core import NUMBER_FIELDS, PARSER_VERSION, job_numbers, parse_pdf  # noqa: E402


def job_facts(job):
    """The job fields a re-read can change."""
    return {"RO #": job.ro_number, "claim #": job.claim_no, "adjuster": job.adjuster, "estimator": job.estimator,
            "loss date": job.loss_date, "deductible": job.deductible, "mileage in": job.mileage_in,
            "customer": job.customer.name if job.customer else "", "insurance": job.insurance.name if job.insurance else "",
            "VIN": job.vehicle.vin if job.vehicle else "", "current document": job.current_document_id}


def changed(before, after):
    return [f"{k} {before[k]} -> {after[k]}" for k in before if before[k] != after[k]]


if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    print("Backup:", migrate.backup(DATABASE_URL, "reparse") or "not SQLite - take a backup (pg_dump) first")
    counts = {"read": 0, "numbers": 0, "closed_would": 0, "jobs": 0, "duplicate_ro": 0}
    with init_db(make_engine())() as s:
        docs = select(EstimateDocument).order_by(EstimateDocument.job_id, EstimateDocument.id)
        if "--all" not in sys.argv:
            docs = docs.where(EstimateDocument.parser_version != PARSER_VERSION)
        by_job = {}
        for d in s.scalars(docs).all():
            by_job.setdefault(d.job, []).append(d)
        for job, job_docs in by_job.items():
            closed = job.closed_at is not None
            facts = job_facts(job)
            for d in job_docs:
                path = Path(d.file.path)
                result = parse_pdf(str(path if path.is_absolute() else ROOT / path), d.file.original_name)
                before = {k: getattr(d, k) for k in NUMBER_FIELDS} | {"review reasons": len(d.review_reasons or [])}
                after = job_numbers(result) | {"review reasons": len(result["review"])}
                try:
                    reparse_document(s, d, result, make_current=not closed)
                except DuplicateRO as e:
                    counts["duplicate_ro"] += 1
                    print(f"  job {job.id} doc {d.id}: NOT re-read - {e}")
                    continue
                counts["read"] += 1
                if diff := changed(before, after):
                    counts["closed_would" if closed else "numbers"] += 1
                    print(f"  job {job.id} doc {d.id} {d.display}"
                          f"{' [closed: history only - would change]' if closed else ''}: " + "; ".join(diff))
            if not closed:
                s.flush()
                s.refresh(job)
                if diff_job := changed(facts, job_facts(job)):
                    counts["jobs"] += 1
                    print(f"  job {job.id} fields: " + "; ".join(diff_job))
        s.commit()
    print(f"Re-read {counts['read']} document(s) with parser {PARSER_VERSION}: numbers changed on {counts['numbers']}; "
          f"on closed jobs {counts['closed_would']} would change (kept, history only); job fields changed on "
          f"{counts['jobs']} job(s); {counts['duplicate_ro']} not re-read (RO # already on another job).")

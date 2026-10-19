"""One-time update: reopen every closed job. Before jobs could be closed by hand, every upload was filed as finished
automatically, so none of those jobs was really closed out. Each one is logged.   python tools/reopen_jobs.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from db import migrate  # noqa: E402
from db.closing import reopen_job  # noqa: E402
from db.models import Job  # noqa: E402
from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    print("Backup:", migrate.backup(DATABASE_URL, "reopen") or "not SQLite - take a backup (pg_dump) first")
    with init_db(make_engine())() as s:
        jobs = s.scalars(select(Job).where(Job.closed_at.is_not(None))).all()
        for j in jobs:
            reopen_job(s, j, "One-time update: filed as finished automatically by an upload, never closed out")
        s.commit()
    print(f"Reopened {len(jobs)} job(s).")

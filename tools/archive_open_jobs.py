"""One-time update: file every job that is not yet archived (jobs saved before uploads went straight to the archive).
Their archive date is the day they were first saved. Each one is logged.   python tools/archive_open_jobs.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from db.models import Job  # noqa: E402
from db.save import audit  # noqa: E402
from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    with init_db(make_engine())() as s:
        jobs = s.scalars(select(Job).where(Job.archived_at.is_(None))).all()
        for j in jobs:
            j.archived_at = j.created_at
            audit(s, "jobs", j.id, "archive", "archived_at", None, j.archived_at.isoformat(), job_id=j.id)
        s.commit()
    print(f"Archived {len(jobs)} job(s).")

"""One-time update: reopen every closed job. Before jobs could be closed by hand, every upload was filed as finished
automatically, so none of those jobs was really closed out. Each one is logged.   python tools/reopen_jobs.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from db.models import Job  # noqa: E402
from db.save import set_field  # noqa: E402
from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    with init_db(make_engine())() as s:
        jobs = s.scalars(select(Job).where(Job.closed_at.is_not(None))).all()
        for j in jobs:
            set_field(s, j, "closed_at", None, job_id=j.id, action="reopen")
        s.commit()
    print(f"Reopened {len(jobs)} job(s).")

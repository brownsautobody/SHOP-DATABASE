"""tools/reparse_documents.py on a real sample PDF (skipped where samples/ is empty): a closed job's numbers never
change - the new reading goes to history only; once reopened, its numbers follow the new reading."""
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from db.models import Job, now
from db.save import save_parse
from db.session import init_db, make_engine
from estimate_parser.core import parse_pdf

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = next(iter(sorted((ROOT / "samples").glob("*.pdf"))), None)


def run_tool(data_dir):
    env = {**os.environ, "SHOP_DATA_DIR": str(data_dir)}
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "reparse_documents.py"), "--all"], env=env,
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.skipif(SAMPLE is None, reason="no sample PDFs on this machine")
def test_closed_job_numbers_are_kept(tmp_path):
    Session = init_db(make_engine(f"sqlite:///{tmp_path / 'shop.db'}"))
    with Session() as s:
        doc = save_parse(s, parse_pdf(str(SAMPLE), SAMPLE.name), SAMPLE.read_bytes(), tmp_path / "files").document
        doc.grand_total = Decimal("1.00")  # stands in for a number an older parser read differently
        doc.job.closed_at = now()
        s.commit()
        job_id = doc.job_id

    out = run_tool(tmp_path)
    assert "closed: history only - would change" in out and "grand_total 1.00 ->" in out
    assert (tmp_path / "backups").exists()
    with Session() as s:
        d = s.get(Job, job_id).current_document
        assert d.grand_total == Decimal("1.00") and len(d.parses) == 2 and d.current_parse_id == d.parses[0].id
        s.get(Job, job_id).closed_at = None
        s.commit()

    run_tool(tmp_path)
    with Session() as s:
        d = s.get(Job, job_id).current_document
        assert d.grand_total != Decimal("1.00") and len(d.parses) == 3 and d.current_parse_id == d.parses[-1].id

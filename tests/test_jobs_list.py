"""The jobs list: search, Open/Closed, date filter, order and totals - done in SQL from the saved job numbers."""
import re
from decimal import Decimal

import pytest

import app as webapp
from db.models import Job, now
from db.save import reparse_document
from db.session import init_db, make_engine
from fakes import VIN_A, VIN_B, make, upload

VIN_C = "3FA6P0H72HR123456"


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """Three jobs in a fresh database for the app: two open, one closed."""
    monkeypatch.setattr(webapp, "Session", init_db(make_engine(f"sqlite:///{tmp_path / 'list.db'}")))
    monkeypatch.setattr(webapp, "FILES_DIR", tmp_path / "files")
    with webapp.Session() as s:
        ids = {}
        # printed 2026-09-30 23:30 shop time = 2026-10-01 04:30 UTC: it belongs to September in the shop
        ids["a"] = upload(s, make(ro="5001", vin=VIN_A, customer="ADAMS, AL", insurance="Acme Ins",
                                  printed="2026-09-30T23:30:00", body_hours="4.5", grand_total="1000.10"),
                          webapp.FILES_DIR)[1]
        ids["b"] = upload(s, make(ro="5002", vin=VIN_B, customer="BAKER, BO", insurance="Zenith",
                                  printed="2026-10-01T08:00:00", body_hours="2.0", grand_total="500.20"),
                          webapp.FILES_DIR)[1]
        ids["c"] = upload(s, make(ro="5003", vin=VIN_C, customer="COLE, CY", claim="CL-9",
                                  printed="2026-08-15T09:00:00", body_hours="1.0", grand_total="0.10"),
                          webapp.FILES_DIR)[1]
        s.get(Job, ids["c"]).closed_at = now()
        s.commit()
    return ids


def listed(**args):
    html = webapp.app.test_client().get("/jobs", query_string=args).get_data(as_text=True)
    ros = re.findall(r"<a href='/jobs/\d+'>(\d+)</a>", html)
    foot = re.search(r"<tfoot>(.*?)</tfoot>", html, re.S)
    return ros, foot.group(1) if foot else ""


def test_open_closed_all(jobs):
    assert listed()[0] == ["5002", "5001"]  # open by default, newest printed first
    assert listed(status="closed")[0] == ["5003"]
    assert listed(status="all")[0] == ["5002", "5001", "5003"]


def test_search_ro_customer_vin_claim_insurance(jobs):
    assert listed(q="5001", status="all")[0] == ["5001"]
    assert listed(q="baker", status="all")[0] == ["5002"]
    assert listed(q=VIN_C.lower(), status="all")[0] == ["5003"]
    assert listed(q="cl-9", status="all")[0] == ["5003"]
    assert listed(q="zenith", status="all")[0] == ["5002"]
    assert listed(q="%", status="all")[0] == []  # typed text, not a wildcard


def test_date_filter_uses_the_shops_day(jobs):
    assert listed(start="2026-09-01", end="2026-09-30", status="all")[0] == ["5001"]
    assert listed(start="2026-10-01", end="2026-10-31", status="all")[0] == ["5002"]


def test_totals_row_sums_the_listed_jobs_exactly(jobs):
    _, foot = listed(status="all")
    assert "Total - 3 jobs" in foot and "1,500.40" in foot and "7.5" in foot
    _, foot = listed()
    assert "Total - 2 jobs" in foot and "1,500.30" in foot


def test_numbers_are_saved_on_the_document_and_follow_a_reread(jobs):
    with webapp.Session() as s:
        d = s.get(Job, jobs["a"]).current_document
        assert (d.body_hours, d.grand_total) == (Decimal("4.5"), Decimal("1000.10"))
        reparse_document(s, d, make(ro="5001", vin=VIN_A, printed="2026-09-30T23:30:00", body_hours="5.0",
                                    grand_total="1100.00"))
        s.commit()
        assert (d.body_hours, d.grand_total) == (Decimal("5.0"), Decimal("1100.00"))

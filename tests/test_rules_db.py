"""Rules the database enforces, the duplicate-RO path, and parse history."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import app as webapp
from db.models import EstimateParse, File, Job, PendingUpload, Shop, now
from db.save import DuplicateRO, reparse_document, resolve_pending, set_field
from db.session import init_db, make_engine
from fakes import VIN_A, VIN_B, make
from fakes import upload as _upload


@pytest.fixture
def s(tmp_path):
    with init_db(make_engine(f"sqlite:///{tmp_path / 'r.db'}"))() as s:
        s.files_dir = tmp_path / "files"
        yield s


def upload(s, **kw):
    return _upload(s, make(**kw), s.files_dir)


# ---------------------------------------------------------------- unique rules

def test_database_refuses_two_jobs_with_the_same_ro(s):
    shop = s.scalar(select(Shop.id))
    s.add_all([Job(shop_id=shop, ro_number="4401"), Job(shop_id=shop, ro_number="4401")])
    with pytest.raises(IntegrityError):
        s.flush()


def test_blank_ro_numbers_may_repeat(s):
    shop = s.scalar(select(Shop.id))
    s.add_all([Job(shop_id=shop, ro_number=""), Job(shop_id=shop, ro_number="")])
    s.flush()


def test_database_refuses_two_rows_for_one_pdf(s):
    shop = s.scalar(select(Shop.id))
    s.add_all([File(shop_id=shop, kind="estimate_pdf", path="a", sha256="x" * 64),
               File(shop_id=shop, kind="estimate_pdf", path="b", sha256="x" * 64)])
    with pytest.raises(IntegrityError):
        s.flush()


# ---------------------------------------------------------------- duplicate RO # goes to a person

def test_new_job_that_would_repeat_an_ro_waits_for_a_person(s):
    a = upload(s, ro="4401", vin=VIN_A, claim="CL-1")[1]
    b = upload(s, ro="", vin=VIN_B, claim="CL-2")[1]
    # job b's supplement now prints RO 4401: rule 1 finds job a by RO, VINs differ -> a person
    assert upload(s, ro="4401", vin=VIN_B, claim="CL-2", supplement_no=1)[0] == "person"
    p = s.scalar(select(PendingUpload))
    # choosing job b would give it RO 4401, which job a has: it keeps waiting, as a duplicate RO
    with pytest.raises(DuplicateRO):
        resolve_pending(s, p, b)
    assert p.reason == "duplicate_ro" and a in p.candidate_job_ids
    assert p.resolved_at is None and len(s.get(Job, b).documents) == 1


def test_a_new_job_cannot_take_an_ro_another_job_has(s):
    upload(s, ro="4401", vin=VIN_A)
    assert upload(s, ro="4401", vin=VIN_B)[0] == "person"  # same RO #, different VIN
    p = s.scalar(select(PendingUpload))
    with pytest.raises(DuplicateRO):
        resolve_pending(s, p, None)  # "Make a new job" would be a second job with RO 4401
    assert p.reason == "duplicate_ro" and s.scalar(select(func.count()).select_from(Job)) == 1


def test_a_reread_that_would_repeat_an_ro_changes_nothing(s):
    upload(s, ro="4401", vin=VIN_A)
    b = s.get(Job, upload(s, ro="", vin=VIN_B)[1])
    d = b.current_document
    with pytest.raises(DuplicateRO):
        reparse_document(s, d, make(ro="4401", vin=VIN_B))
    assert b.ro_number == "" and len(d.parses) == 1


def test_manual_ro_that_another_job_has_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "Session", init_db(make_engine(f"sqlite:///{tmp_path / 'w.db'}")))
    with webapp.Session() as s:
        a = _upload(s, make(ro="4401", vin=VIN_A), tmp_path / "f")[1]
        b = _upload(s, make(ro="4402", vin=VIN_B), tmp_path / "f")[1]
        s.commit()
    r = webapp.app.test_client().post(f"/jobs/{b}/ro", data={"ro": "4401"})
    assert "ro_taken=4401" in r.headers["Location"]
    with webapp.Session() as s:
        assert s.get(Job, b).ro_number == "4402"


# ---------------------------------------------------------------- parse history

def test_reread_adds_to_history_and_becomes_current(s):
    j = s.get(Job, upload(s, ro="1", vin=VIN_A, grand_total="100.00")[1])
    d = j.current_document
    first = d.current_parse_id
    p = reparse_document(s, d, make(ro="1", vin=VIN_A, grand_total="120.00"))
    assert d.current_parse_id == p.id != first
    assert [x.id for x in d.parses] == [first, p.id]
    assert d.parse["totals"][0]["amount"] == 120.0 and str(d.grand_total) == "120.00"
    assert s.get(EstimateParse, first).parse["totals"][0]["amount"] == 100.0  # kept as it was


def test_reread_of_a_closed_job_is_history_only(s):
    j = s.get(Job, upload(s, ro="1", vin=VIN_A, grand_total="100.00", adjuster="AMY")[1])
    d = j.current_document
    first = d.current_parse_id
    j.closed_at = now()
    p = reparse_document(s, d, make(ro="1", vin=VIN_A, grand_total="120.00", adjuster="BOB"), make_current=False)
    assert d.current_parse_id == first and str(d.grand_total) == "100.00" and j.adjuster == "AMY"
    assert [x.id for x in d.parses] == [first, p.id]


def test_saving_twice_keeps_one_file_row(s):
    upload(s, ro="1", vin=VIN_A)
    assert s.scalar(select(func.count()).select_from(File)) == 1


def test_a_known_file_row_is_reused_not_repeated(s):
    import hashlib
    shop = s.scalar(select(Shop.id))
    s.add(File(shop_id=shop, kind="estimate_pdf", path="x", sha256=hashlib.sha256(b"same pdf").hexdigest()))
    s.flush()
    from db.save import save_parse
    save_parse(s, make(ro="1", vin=VIN_A), b"same pdf", s.files_dir)
    assert s.scalar(select(func.count()).select_from(File)) == 1

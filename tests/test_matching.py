"""Which job an uploaded estimate is filed with. Small hand-made parses, no customer data.

upload() answers ("job", id) when the estimate was filed with a job, or ("person", reason) when it waits for a person
to choose. Each rule has a case where its two conditions disagree (same claim # but a different VIN, ...)."""
import pytest

from db.models import Job
from db.session import init_db, make_engine
from fakes import VIN_A, VIN_B, make
from fakes import upload as _upload


@pytest.fixture
def s(tmp_path):
    Session = init_db(make_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    with Session() as s:
        s.files_dir = tmp_path / "files"
        yield s


def upload(s, result):
    return _upload(s, result, s.files_dir)


def first(s, **kw):
    kind, job_id = upload(s, make(**kw))
    assert kind == "job"
    return job_id


# ---------------------------------------------------------------- rule 1: same RO #

def test_same_ro_same_vin_is_that_job(s):
    j = first(s, ro="4401", vin=VIN_A)
    assert upload(s, make(ro="4401", vin=VIN_A, supplement_no=1)) == ("job", j)


def test_same_ro_months_later_is_that_job(s):
    j = first(s, ro="4401", vin=VIN_A, printed="2026-01-05T10:00:00")
    assert upload(s, make(ro="4401", vin=VIN_A, printed="2026-09-01T10:00:00", supplement_no=1)) == ("job", j)


def test_same_ro_one_vin_missing_is_that_job(s):
    j = first(s, ro="4401", vin=VIN_A)
    assert upload(s, make(ro="4401", vin="", supplement_no=1)) == ("job", j)


def test_same_ro_different_vin_needs_a_person(s):
    first(s, ro="4401", vin=VIN_A)
    assert upload(s, make(ro="4401", vin=VIN_B))[0] == "person"


# ---------------------------------------------------------------- rule 2: same claim #

def test_same_claim_same_vin_is_that_job(s):
    j = first(s, claim="CL-1", vin=VIN_A)
    assert upload(s, make(claim="CL-1", vin=VIN_A, supplement_no=1)) == ("job", j)


def test_same_claim_same_vin_months_later_is_that_job(s):
    j = first(s, claim="CL-1", vin=VIN_A, printed="2026-01-05T10:00:00")
    assert upload(s, make(claim="CL-1", vin=VIN_A, printed="2026-09-01T10:00:00", supplement_no=1)) == ("job", j)


def test_same_claim_different_vin_is_a_new_job(s):
    j = first(s, claim="CL-1", vin=VIN_A)
    kind, j2 = upload(s, make(claim="CL-1", vin=VIN_B))
    assert kind == "job" and j2 != j


def test_same_claim_vin_missing_needs_a_person(s):
    first(s, claim="CL-1", vin=VIN_A)
    assert upload(s, make(claim="CL-1", vin=""))[0] == "person"


# ---------------------------------------------------------------- rule 3: same VIN within 90 days

def test_same_vin_within_90_days_is_that_job(s):
    j = first(s, vin=VIN_A, printed="2026-09-01T10:00:00")
    assert upload(s, make(vin=VIN_A, printed="2026-11-29T10:00:00", supplement_no=1)) == ("job", j)


def test_same_vin_after_90_days_is_a_new_job(s):
    j = first(s, vin=VIN_A, printed="2026-09-01T10:00:00")
    kind, j2 = upload(s, make(vin=VIN_A, printed="2026-12-01T10:00:00"))
    assert kind == "job" and j2 != j


def test_same_vin_within_90_days_claim_on_one_only_is_that_job(s):
    j = first(s, vin=VIN_A, claim="CL-1")
    assert upload(s, make(vin=VIN_A, supplement_no=1)) == ("job", j)


def test_same_vin_within_90_days_conflicting_claim_is_a_new_job(s):
    j = first(s, vin=VIN_A, claim="CL-1")
    kind, j2 = upload(s, make(vin=VIN_A, claim="CL-2"))
    assert kind == "job" and j2 != j


# ---------------------------------------------------------------- rule 4: more than one candidate

def test_two_candidate_jobs_need_a_person(s):
    a = first(s, vin=VIN_A, claim="CL-1")
    b = first(s, vin=VIN_A, claim="CL-2")
    assert a != b
    assert upload(s, make(vin=VIN_A))[0] == "person"


def test_two_jobs_with_the_same_claim_need_a_person(s):
    from db.models import PendingUpload
    from db.save import resolve_pending
    first(s, claim="CL-1", vin=VIN_A)
    assert upload(s, make(claim="CL-1", vin=""))[0] == "person"
    resolve_pending(s, s.query(PendingUpload).one(), None)  # a person made it a new job (no VIN to compare)
    assert upload(s, make(claim="CL-1", vin=VIN_A, supplement_no=1))[0] == "person"


# ---------------------------------------------------------------- rule 5: no match

def test_no_match_is_a_new_job(s):
    j = first(s, ro="4401", claim="CL-1", vin=VIN_A)
    kind, j2 = upload(s, make(ro="4402", claim="CL-2", vin=VIN_B))
    assert kind == "job" and j2 != j


# ---------------------------------------------------------------- rule 6: matched job is closed

def test_closed_job_needs_a_person(s):
    from db.models import now
    j = first(s, ro="4401", vin=VIN_A)
    s.get(Job, j).closed_at = now()
    s.flush()
    assert upload(s, make(ro="4401", vin=VIN_A, supplement_no=1)) == ("person", "closed_job")

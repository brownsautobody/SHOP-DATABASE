"""Which job an uploaded estimate is filed with. Small hand-made parses, no customer data.

upload() answers ("job", id) when the estimate was filed with a job, or ("person", reason) when it waits for a person
to choose. Each rule has a case where its two conditions disagree (same claim # but a different VIN, ...)."""
import itertools

import pytest

from db.models import Job
from db.save import save_parse
from db.session import init_db, make_engine

VIN_A = "1HGCM82633A004352"
VIN_B = "2T1BURHE0JC034461"
_n = itertools.count()


@pytest.fixture
def s(tmp_path):
    Session = init_db(make_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    with Session() as s:
        s.files_dir = tmp_path / "files"
        yield s


def make(ro="", claim="", vin="", printed="2026-09-01T10:00:00", customer="DOE, JANE", phone="", insurance="Acme Ins",
         supplement_no=0, stage="estimate", fmt="CCC ONE"):
    """A parse_pdf()-shaped result holding only what matching and saving read."""
    doc = {"title_raw": "Estimate", "display": "Estimate", "label": "Estimate", "stage": stage,
           "supplement_no": supplement_no, "printed_at": printed, "supplement_amount": None}
    header = {"ro_number": ro, "claim": claim, "customer": customer, "phone": phone, "insurance": insurance,
              "adjuster": "", "estimator": "", "loss_date": "", "deductible": "",
              "vehicle": {"year": "2020", "make": "Honda", "model": "Accord", "description": "2020 Honda Accord",
                          "vin": vin, "mileage": ""}}
    summary = {"document": doc, "history": None, "customer": customer, "ro_number": ro, "vehicle": "2020 Honda Accord",
               "vin": vin, "insurance": insurance, "claim": claim, "labor": [], "total_labor_hours": 0,
               "total_labor_amount": None, "parts_total": 0, "other_charges": [], "needs_review": False,
               "review_reasons": []}
    return {"filename": "test.pdf", "format": fmt, "pages": 1, "header": header, "document": doc, "history": None,
            "charges": [], "totals": [], "checks": [], "review": [], "summary": summary}


def upload(s, result):
    doc, _ = save_parse(s, result, f"fake pdf {next(_n)}".encode(), s.files_dir)
    s.flush()
    return "job", doc.job_id


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


@pytest.mark.xfail(strict=True, reason="Step 3: same RO # but a different VIN needs a person")
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


@pytest.mark.xfail(strict=True, reason="Step 3: one claim # can cover two cars - a different VIN is not this job")
def test_same_claim_different_vin_is_a_new_job(s):
    j = first(s, claim="CL-1", vin=VIN_A)
    kind, j2 = upload(s, make(claim="CL-1", vin=VIN_B))
    assert kind == "job" and j2 != j


@pytest.mark.xfail(strict=True, reason="Step 3: same claim # with a VIN missing needs a person")
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

@pytest.mark.xfail(strict=True, reason="Step 3: two candidate jobs need a person")
def test_two_candidate_jobs_need_a_person(s):
    a = first(s, vin=VIN_A, claim="CL-1")
    b = first(s, vin=VIN_A, claim="CL-2")
    assert a != b
    assert upload(s, make(vin=VIN_A))[0] == "person"


# ---------------------------------------------------------------- rule 5: no match

def test_no_match_is_a_new_job(s):
    j = first(s, ro="4401", claim="CL-1", vin=VIN_A)
    kind, j2 = upload(s, make(ro="4402", claim="CL-2", vin=VIN_B))
    assert kind == "job" and j2 != j


# ---------------------------------------------------------------- rule 6: matched job is closed

@pytest.mark.xfail(strict=True, reason="Step 3: an upload for a closed job needs a person")
def test_closed_job_needs_a_person(s):
    from db.models import now
    j = first(s, ro="4401", vin=VIN_A)
    s.get(Job, j).closed_at = now()
    s.flush()
    assert upload(s, make(ro="4401", vin=VIN_A, supplement_no=1)) == ("person", "closed_job")

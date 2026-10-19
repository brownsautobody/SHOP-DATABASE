"""Uploads the app is not sure about wait for a person: nothing is filed until someone chooses, then it is saved
exactly as an automatic match would be, and the choice is logged."""
import re

import pytest
from sqlalchemy import func, select

import app as webapp
from db.models import AuditLog, EstimateDocument, Job, PendingUpload, now
from db.save import resolve_pending, save_parse
from db.session import init_db, make_engine
from fakes import VIN_A, VIN_B, make


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "Session", init_db(make_engine(f"sqlite:///{tmp_path / 'pending.db'}")))
    monkeypatch.setattr(webapp, "FILES_DIR", tmp_path / "files")
    return webapp.app.test_client()


def _save(result, pdf):
    with webapp.Session() as s:
        saved = save_parse(s, result, pdf, webapp.FILES_DIR)
        s.commit()
        return (saved.document.job_id if saved.document else None), (saved.pending.id if saved.pending else None)


def _count(model):
    with webapp.Session() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_uncertain_upload_waits_and_nothing_is_filed(client):
    job_id, _ = _save(make(ro="4401", vin=VIN_A, customer="DOE, JANE"), b"one")
    _, pid = _save(make(ro="4401", vin=VIN_B, customer="ROE, RAY", supplement_no=1), b"two")
    assert pid and _count(EstimateDocument) == 1 and _count(Job) == 1
    html = client.get(f"/pending/{pid}").get_data(as_text=True)
    assert "Not sure which job" in html and "VINs differ" in html
    assert "DOE, JANE" in html and VIN_A in html and "ROE, RAY" in html  # the candidate job and this upload
    assert "Add to this job" in html and "Make a new job" in html
    assert "ROE, RAY" in client.get("/pending").get_data(as_text=True)


def test_same_pdf_again_returns_the_waiting_upload(client):
    _save(make(ro="4401", vin=VIN_A), b"one")
    _, pid = _save(make(ro="4401", vin=VIN_B), b"two")
    assert _save(make(ro="4401", vin=VIN_B), b"two") == (None, pid)
    assert _count(PendingUpload) == 1


def test_add_to_this_job(client):
    job_id, _ = _save(make(ro="4401", vin=VIN_A), b"one")
    _, pid = _save(make(ro="4401", vin=VIN_B, supplement_no=1), b"two")
    r = client.post(f"/pending/{pid}/resolve", data={"job_id": str(job_id)})
    assert r.status_code == 302 and f"/jobs/{job_id}" in r.headers["Location"]
    with webapp.Session() as s:
        job = s.get(Job, job_id)
        assert len(job.documents) == 2 and job.current_document.supplement_no == 1
        p = s.get(PendingUpload, pid)
        assert (p.resolution, p.resolution_job_id, p.document_id) == ("job", job_id, job.current_document_id)
        assert p.file.job_id == job_id
        assert s.scalar(select(AuditLog).where(AuditLog.table_name == "pending_uploads", AuditLog.action == "resolve"))
    assert "Nothing is waiting" in client.get("/pending").get_data(as_text=True)
    assert "Filed" in client.get(f"/pending/{pid}").get_data(as_text=True)


def test_make_a_new_job(client):
    # same claim # but no VIN on the new estimate: a person decides
    job_id, _ = _save(make(claim="CL-7", vin=VIN_A, ro="4402"), b"three")
    _, pid = _save(make(claim="CL-7", vin=""), b"four")
    r = client.post(f"/pending/{pid}/resolve", data={"job_id": "new"})
    new_id = int(re.search(r"/jobs/(\d+)", r.headers["Location"]).group(1))
    assert new_id != job_id and _count(Job) == 2
    with webapp.Session() as s:
        assert s.get(PendingUpload, pid).resolution == "new_job"
        assert s.get(Job, new_id).claim_no == "CL-7"


def test_closed_job_must_be_reopened_first(client):
    job_id, _ = _save(make(ro="4401", vin=VIN_A), b"one")
    with webapp.Session() as s:
        s.get(Job, job_id).closed_at = now()
        s.commit()
    _, pid = _save(make(ro="4401", vin=VIN_A, supplement_no=1), b"two")
    html = client.get(f"/pending/{pid}").get_data(as_text=True)
    assert "is closed" in html and "reopen the job first" in html and "Add to this job" not in html
    assert client.post(f"/pending/{pid}/resolve", data={"job_id": str(job_id)}).status_code == 409
    with webapp.Session() as s:
        assert len(s.get(Job, job_id).documents) == 1  # still locked
        with pytest.raises(ValueError):
            resolve_pending(s, s.get(PendingUpload, pid), job_id)


def test_only_a_candidate_job_can_be_chosen(client):
    _save(make(ro="4401", vin=VIN_A), b"one")
    other, _ = _save(make(ro="9999", vin="", claim="ZZ"), b"other")
    _, pid = _save(make(ro="4401", vin=VIN_B), b"two")
    assert client.post(f"/pending/{pid}/resolve", data={"job_id": str(other)}).status_code == 400

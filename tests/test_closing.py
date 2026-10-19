"""Closing a job for bookkeeping: a checklist a person answers, Close only when every required item is Yes, and a
closed job is locked until a person reopens it with a note."""
import re

import pytest
from sqlalchemy import select

import app as webapp
from db import closing
from db.models import AuditLog, ChecklistItem, Job, PendingUpload
from db.save import resolve_pending
from db.session import init_db, make_engine
from fakes import VIN_A, make
from fakes import upload as _upload


@pytest.fixture
def s(tmp_path):
    with init_db(make_engine(f"sqlite:///{tmp_path / 'c.db'}"))() as s:
        s.files_dir = tmp_path / "files"
        yield s


def new_job(s, **kw):
    return s.get(Job, _upload(s, make(ro="4401", vin=VIN_A, **kw), s.files_dir)[1])


def answer_all(s, job, value=True):
    for item, _ in closing.checklist(s, job):
        closing.set_check(s, job, item, value)


def test_the_default_checklist(s):
    items = s.scalars(select(ChecklistItem).order_by(ChecklistItem.position)).all()
    assert [i.name for i in items] == ["File audited", "Everything closed out", "Paid in full",
                                       "Numbers OK for bookkeeping"]
    assert all(i.required_to_close and i.active for i in items)


def test_close_only_when_every_required_item_is_yes(s):
    j = new_job(s)
    with pytest.raises(ValueError, match="Paid in full"):
        closing.close_job(s, j)
    answer_all(s, j)
    closing.set_check(s, j, closing.checklist(s, j)[2][0], False)  # Paid in full: No
    with pytest.raises(ValueError, match="still to do: Paid in full"):
        closing.close_job(s, j)
    closing.set_check(s, j, closing.checklist(s, j)[2][0], True)
    closing.close_job(s, j)
    assert j.closed_at is not None
    assert s.scalar(select(AuditLog).where(AuditLog.action == "close", AuditLog.field == "closed_at"))


def test_optional_and_retired_items_do_not_block_closing(s):
    s.add_all([ChecklistItem(name="Photos filed", position=9, required_to_close=False),
               ChecklistItem(name="Old rule", position=10, required_to_close=True, active=False)])
    s.flush()
    j = new_job(s)
    for item, _ in closing.checklist(s, j):
        if item.required_to_close:
            closing.set_check(s, j, item, True)
    assert "Old rule" not in [i.name for i, _ in closing.checklist(s, j)]
    closing.close_job(s, j)
    assert j.closed_at is not None


def test_each_answer_is_logged(s):
    j = new_job(s)
    item = closing.checklist(s, j)[0][0]
    closing.set_check(s, j, item, True)
    closing.set_check(s, j, item, False)
    logged = s.scalars(select(AuditLog).where(AuditLog.table_name == "job_checks")).all()
    assert [(a.old_value, a.new_value) for a in logged] == [(None, "True"), ("True", "False")]


def test_a_closed_job_is_locked(s):
    j = new_job(s)
    answer_all(s, j)
    closing.close_job(s, j)
    with pytest.raises(closing.JobClosed):
        closing.set_check(s, j, closing.checklist(s, j)[0][0], False)
    # a new estimate for it waits for a person, and can't be added until the job is reopened
    assert _upload(s, make(ro="4401", vin=VIN_A, supplement_no=1), s.files_dir) == ("person", "closed_job")
    p = s.scalar(select(PendingUpload))
    with pytest.raises(ValueError):
        resolve_pending(s, p, j.id)
    assert len(j.documents) == 1


def test_reopen_needs_a_note_and_keeps_the_answers(s):
    j = new_job(s)
    answer_all(s, j)
    closing.close_job(s, j)
    with pytest.raises(ValueError):
        closing.reopen_job(s, j, "  ")
    closing.reopen_job(s, j, "Supplement 2 arrived")
    assert j.closed_at is None
    assert s.scalar(select(AuditLog.note).where(AuditLog.action == "reopen", AuditLog.field == "closed_at")) == \
        "Supplement 2 arrived"
    assert all(c.value for _, c in closing.checklist(s, j))  # answers kept
    # the waiting upload can be added now
    _upload(s, make(ro="4401", vin=VIN_A, supplement_no=1), s.files_dir)


def test_closing_again_needs_every_item_yes_again(s):
    j = new_job(s)
    answer_all(s, j)
    closing.close_job(s, j)
    closing.reopen_job(s, j, "fix the parts total")
    closing.set_check(s, j, closing.checklist(s, j)[3][0], False)
    with pytest.raises(ValueError):
        closing.close_job(s, j)


# ---------------------------------------------------------------- the job page

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "Session", init_db(make_engine(f"sqlite:///{tmp_path / 'w.db'}")))
    monkeypatch.setattr(webapp, "FILES_DIR", tmp_path / "files")
    with webapp.Session() as s:
        job_id = _upload(s, make(ro="4401", vin=VIN_A), tmp_path / "files")[1]
        s.commit()
    return webapp.app.test_client(), job_id


def test_job_page_close_and_reopen(client):
    c, job_id = client
    page = c.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert "File audited" in page and "Still to do" in page and " disabled>Close job" in page
    r = c.post(f"/jobs/{job_id}/close")
    assert "Can" in c.get(r.headers["Location"]).get_data(as_text=True)  # refused, with what is still to do
    for item_id in map(int, re.findall(r"name='item' value='(\d+)'", page)):
        c.post(f"/jobs/{job_id}/check", data={"item": item_id, "value": "yes"})
    c.post(f"/jobs/{job_id}/close")
    page = c.get(f"/jobs/{job_id}").get_data(as_text=True)
    assert "chip done'>Closed" in page and "locked" in page and "Reopen job" in page
    assert "?msg=" in c.post(f"/jobs/{job_id}/ro", data={"ro": "9999"}).headers["Location"]  # locked
    c.post(f"/jobs/{job_id}/reopen", data={"note": ""})
    assert "chip done'>Closed" in c.get(f"/jobs/{job_id}").get_data(as_text=True)  # no note, still closed
    c.post(f"/jobs/{job_id}/reopen", data={"note": "customer came back"})
    assert "chip open'>Open" in c.get(f"/jobs/{job_id}").get_data(as_text=True)

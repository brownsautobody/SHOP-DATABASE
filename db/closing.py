"""Closing a job for bookkeeping. A job is closed only after the file is audited, everything is closed out, the shop is
paid and the numbers are right for bookkeeping - a person answers each checklist item. Payments themselves are
bookkeeping's, not this app's.

Closed jobs are locked: no checklist answers, RO # edits, re-read numbers or new estimates change them until a person
reopens the job (with a note). Reopening keeps the answers; closing again needs every required item Yes again."""
from sqlalchemy import func, select

from .models import ChecklistItem, JobCheck, now
from .save import set_field

# the checklist a new database starts with (the Settings page will edit it later; items are rows, not code)
DEFAULT_ITEMS = ["File audited", "Everything closed out", "Paid in full", "Numbers OK for bookkeeping"]


class JobClosed(ValueError):
    """The job is closed: reopen it first."""


def seed(s):
    """Add the default checklist to a database that has none."""
    if s.scalar(select(func.count()).select_from(ChecklistItem)) == 0:
        s.add_all(ChecklistItem(name=n, position=i, required_to_close=True) for i, n in enumerate(DEFAULT_ITEMS, 1))


def checklist(s, job):
    """[(item, its JobCheck or None)] for the active items, in order."""
    checks = {c.item_id: c for c in s.scalars(select(JobCheck).where(JobCheck.job_id == job.id))}
    items = s.scalars(select(ChecklistItem).where(ChecklistItem.active.is_(True)).order_by(ChecklistItem.position))
    return [(i, checks.get(i.id)) for i in items]


def still_to_do(s, job):
    """Names of the required items not answered Yes."""
    return [i.name for i, c in checklist(s, job) if i.required_to_close and not (c and c.value)]


def set_check(s, job, item, value, user_id=None):
    """A person answers one item Yes (True) or No (False). Logged."""
    if job.closed_at is not None:
        raise JobClosed("The job is closed - reopen it to change its checklist.")
    check = s.scalar(select(JobCheck).where(JobCheck.job_id == job.id, JobCheck.item_id == item.id))
    if check is None:
        check = JobCheck(job_id=job.id, item_id=item.id, value=None)
        s.add(check)
        s.flush()
    if set_field(s, check, "value", bool(value), user_id, job.id):
        check.set_by, check.set_at = user_id, now()
    return check


def close_job(s, job, user_id=None):
    """Close the job if every required item is Yes; otherwise ValueError naming what is still to do."""
    if job.closed_at is not None:
        return
    if todo := still_to_do(s, job):
        raise ValueError("Can't close yet - still to do: " + ", ".join(todo))
    set_field(s, job, "closed_at", now(), user_id, job.id, action="close")
    set_field(s, job, "closed_by", user_id, user_id, job.id, action="close")


def reopen_job(s, job, note, user_id=None):
    """Reopen a closed job; a note saying why is required (kept in the change log)."""
    note = (note or "").strip()
    if not note:
        raise ValueError("Say why the job is being reopened.")
    if job.closed_at is None:
        return
    set_field(s, job, "closed_at", None, user_id, job.id, action="reopen", note=note)
    set_field(s, job, "closed_by", None, user_id, job.id, action="reopen")

"""Production board: stages, stage moves, and who is assigned to a job. Every change is logged (rule 4)."""
import re

from sqlalchemy import func, select

from .models import JobAssignment, JobStageEvent, ProductionStage, Shop, User, now
from .save import audit, set_field

ROLES = ["tech", "estimator"]  # roles a job can have one current person in
EMPLOYEE_ROLES = ["tech", "estimator", "other"]


def _shop_id(s):
    return s.scalar(select(Shop.id).order_by(Shop.id).limit(1))


def stages(s, include_hidden=False):
    q = select(ProductionStage).order_by(ProductionStage.position, ProductionStage.id)
    return s.scalars(q if include_hidden else q.where(ProductionStage.active)).all()


def employees(s, role=None, include_inactive=False):
    q = select(User).order_by(User.name)
    if role:
        q = q.where(User.role == role)
    return s.scalars(q if include_inactive else q.where(User.active)).all()


def move_stage(s, job, stage_id, user_id=None, note=""):
    """Put a job in a stage (None = not started). Returns False if it was already there."""
    if job.current_stage_id == stage_id:
        return False
    s.add(JobStageEvent(job_id=job.id, from_stage_id=job.current_stage_id, to_stage_id=stage_id, moved_by=user_id, note=note))
    set_field(s, job, "current_stage_id", stage_id, user_id, job.id)
    return True


def assign(s, job, role, user_id, by=None):
    """Make user_id the job's current person in this role (None = nobody). The previous assignment is ended, not deleted."""
    cur = s.scalar(select(JobAssignment).where(JobAssignment.job_id == job.id, JobAssignment.role == role,
                                               JobAssignment.removed_at.is_(None)))
    if (cur.user_id if cur else None) == user_id:
        return False
    if cur:
        cur.removed_at = now()
    if user_id:
        s.add(JobAssignment(job_id=job.id, user_id=user_id, role=role, assigned_by=by))
    audit(s, "jobs", job.id, "assign", role, cur.user_id if cur else None, user_id, by, job.id)
    return True


def archive(s, job, by=None):
    """Move a job off the active list. Nothing is deleted; its stage and people stay as they were."""
    if job.archived_at is None:
        job.archived_at = now()
        job.updated_by = by
        audit(s, "jobs", job.id, "archive", "archived_at", None, job.archived_at.isoformat(), by, job.id)


def unarchive(s, job, by=None):
    if job.archived_at is not None:
        audit(s, "jobs", job.id, "unarchive", "archived_at", job.archived_at.isoformat(), None, by, job.id)
        job.archived_at = None
        job.updated_by = by


def current_assignments(s, job_ids):
    """{job_id: {role: User}} for the people on each job now."""
    out = {j: {} for j in job_ids}
    if job_ids:
        rows = s.scalars(select(JobAssignment).where(JobAssignment.job_id.in_(job_ids), JobAssignment.removed_at.is_(None)))
        for a in rows:
            out[a.job_id][a.role] = a.user
    return out


def stage_since(s, job_ids):
    """{job_id: when the job entered its current stage}."""
    if not job_ids:
        return {}
    q = select(JobStageEvent.job_id, func.max(JobStageEvent.moved_at)).where(JobStageEvent.job_id.in_(job_ids))
    return dict(s.execute(q.group_by(JobStageEvent.job_id)).all())


def stage_history(s, job_id):
    return s.scalars(select(JobStageEvent).where(JobStageEvent.job_id == job_id).order_by(JobStageEvent.id)).all()


# ------------------------------------------------------------------ settings page

def add_stage(s, name, by=None):
    pos = (s.scalar(select(func.max(ProductionStage.position))) or 0) + 1
    st = ProductionStage(shop_id=_shop_id(s), name=name, position=pos, created_by=by)
    s.add(st)
    s.flush()
    audit(s, "production_stages", st.id, "create", new=name, user_id=by)
    return st


def move_stage_order(s, stage, direction, by=None):
    """Swap a stage with its neighbour (direction -1 = up, +1 = down) among the visible stages."""
    order = list(stages(s))
    i = order.index(stage)
    j = i + direction
    if 0 <= j < len(order):
        for k, st in enumerate(order):  # renumber so positions are unique
            st.position = k
        other = order[j]
        stage.position, other.position = other.position, stage.position
        audit(s, "production_stages", stage.id, "update", "position", i, j, by)


def add_employee(s, name, role, by=None):
    base = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") or "employee"
    login, n = base, 1
    while s.scalar(select(User.id).where(User.login == login)):  # placeholder until logins exist
        n += 1
        login = f"{base}{n}"
    u = User(shop_id=_shop_id(s), name=name, login=login, role=role, created_by=by)
    s.add(u)
    s.flush()
    audit(s, "users", u.id, "create", new=f"{name} ({role})", user_id=by)
    return u

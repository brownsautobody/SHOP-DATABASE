"""Typed values and saved job numbers: estimate_documents.printed_at text -> UTC time, jobs.loss_date -> date,
jobs.deductible -> numeric; estimate_documents gets job_numbers() columns, filled from each stored parse.

The printed text stays in every document's stored parse. Downgrade: restore the backup tools/migrate.py made.

Revision ID: 0003
Revises: 0002
"""
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

from db.models import UtcDateTime
from estimate_parser.core import job_numbers

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

HOURS = ["body_hours", "refinish_hours", "mechanical_hours", "other_hours", "total_hours"]
MONEY = ["labor_amount", "parts", "tax", "grand_total"]
SHOP_TZ = ZoneInfo("America/Chicago")  # as db/values.py was when this migration was written


def _time(text):
    return datetime.fromisoformat(text).replace(tzinfo=SHOP_TZ).astimezone(timezone.utc) if text else None


def _date(text):
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", text or "")
    try:
        return date(int(m[3]), int(m[1]), int(m[2])) if m else None
    except ValueError:
        return None


def _money(text):
    m = re.search(r"-?\$?\s*(\d[\d,]*\.\d\d)", text or "")
    return Decimal(m[1].replace(",", "")) if m else None


def upgrade():
    with op.batch_alter_table("estimate_documents") as b:
        b.add_column(sa.Column("printed_at_new", sa.DateTime(timezone=True), nullable=True))
        for n in HOURS:
            b.add_column(sa.Column(n, sa.Numeric(8, 2), nullable=True))
        for n in MONEY:
            b.add_column(sa.Column(n, sa.Numeric(10, 2), nullable=True))
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("loss_date_new", sa.Date(), nullable=True))
        b.add_column(sa.Column("deductible_new", sa.Numeric(10, 2), nullable=True))

    conn = op.get_bind()
    docs = sa.table("estimate_documents", sa.column("id", sa.Integer), sa.column("printed_at", sa.String),
                    sa.column("parse", sa.JSON), sa.column("printed_at_new", UtcDateTime),
                    *(sa.column(n, sa.Numeric(8, 2)) for n in HOURS), *(sa.column(n, sa.Numeric(10, 2)) for n in MONEY))
    for doc_id, printed, parse in conn.execute(sa.select(docs.c.id, docs.c.printed_at, docs.c.parse)).all():
        conn.execute(docs.update().where(docs.c.id == doc_id).values(printed_at_new=_time(printed), **job_numbers(parse)))
    jobs = sa.table("jobs", sa.column("id", sa.Integer), sa.column("loss_date", sa.String),
                    sa.column("deductible", sa.String), sa.column("loss_date_new", sa.Date),
                    sa.column("deductible_new", sa.Numeric(10, 2)))
    for job_id, loss, ded in conn.execute(sa.select(jobs.c.id, jobs.c.loss_date, jobs.c.deductible)).all():
        conn.execute(jobs.update().where(jobs.c.id == job_id).values(loss_date_new=_date(loss), deductible_new=_money(ded)))

    with op.batch_alter_table("estimate_documents") as b:
        b.drop_column("printed_at")
        b.alter_column("printed_at_new", new_column_name="printed_at")
    op.create_index("ix_estimate_documents_printed_at", "estimate_documents", ["printed_at"])
    with op.batch_alter_table("jobs") as b:
        b.drop_column("loss_date")
        b.drop_column("deductible")
        b.alter_column("loss_date_new", new_column_name="loss_date")
        b.alter_column("deductible_new", new_column_name="deductible")


def downgrade():
    raise NotImplementedError("Restore the backup copy tools/migrate.py made before 0003.")

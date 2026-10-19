"""Rename jobs.archived_at to closed_at (was done by hand in init_db before migrations existed).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as b:
        b.alter_column("archived_at", new_column_name="closed_at")


def downgrade():
    with op.batch_alter_table("jobs") as b:
        b.alter_column("closed_at", new_column_name="archived_at")

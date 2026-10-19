"""Mileage belongs to the job, not the car: jobs.mileage_in (as printed), copied from each job's vehicle record;
vehicles.mileage is dropped after the copy (vehicles are now shared by every job on the same VIN).

Every vehicle row belonged to exactly one job when this was written, so the copy keeps every value. The printed
mileage also stays in each document's parse. Downgrade: restore the backup tools/migrate.py made.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    lost = conn.execute(sa.text(
        "SELECT count(*) FROM vehicles v WHERE coalesce(v.mileage, '') != '' "
        "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.vehicle_id = v.id)")).scalar()
    if lost:
        raise RuntimeError(f"{lost} vehicle(s) with a mileage belong to no job - the copy would lose them; stopping.")
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("mileage_in", sa.String(20), nullable=False, server_default=""))
    conn.execute(sa.text("UPDATE jobs SET mileage_in = coalesce((SELECT v.mileage FROM vehicles v "
                         "WHERE v.id = jobs.vehicle_id), '')"))
    with op.batch_alter_table("jobs") as b:
        b.alter_column("mileage_in", server_default=None)
    with op.batch_alter_table("vehicles") as b:
        b.drop_column("mileage")


def downgrade():
    raise NotImplementedError("Restore the backup copy tools/migrate.py made before 0005.")

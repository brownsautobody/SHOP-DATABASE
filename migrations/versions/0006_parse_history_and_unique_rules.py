"""Parse history and rules the database enforces.

- estimate_parses: every reading of an estimate PDF (document, parser version, parse JSON, review reasons, when).
  Each document's stored parse becomes its first row; estimate_documents.current_parse_id points at it and the
  parse column moves out of estimate_documents (the JSON is copied, not changed).
- files.sha256 unique (one row per PDF content); jobs.ro_number unique where not blank.
Stops without changing anything if existing rows already break a new unique rule - a person must decide.
Downgrade: restore the backup tools/migrate.py made.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    dup_files = conn.execute(sa.text("SELECT sha256 FROM files GROUP BY sha256 HAVING count(*) > 1")).fetchall()
    dup_ros = conn.execute(sa.text("SELECT ro_number, group_concat(id) FROM jobs WHERE ro_number != '' "
                                   "GROUP BY ro_number HAVING count(*) > 1")).fetchall()
    if dup_files or dup_ros:
        raise RuntimeError(f"Existing rows break the new unique rules - duplicate PDFs: {dup_files}; "
                           f"jobs sharing an RO #: {dup_ros}. Nothing was changed; a person must decide.")

    op.create_table(
        "estimate_parses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(length=20), nullable=False),
        sa.Column("parse", sa.JSON(), nullable=False),
        sa.Column("review_reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["estimate_documents.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_estimate_parses_document_id", "estimate_parses", ["document_id"])
    with op.batch_alter_table("estimate_documents") as b:
        b.add_column(sa.Column("current_parse_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_estimate_documents_current_parse", "estimate_parses", ["current_parse_id"], ["id"])

    # each document's stored parse becomes its first (and current) reading - the same JSON text, copied in SQL
    conn.execute(sa.text(
        "INSERT INTO estimate_parses (document_id, parser_version, parse, review_reasons, created_at, created_by) "
        "SELECT id, parser_version, parse, review_reasons, updated_at, updated_by FROM estimate_documents ORDER BY id"))
    conn.execute(sa.text("UPDATE estimate_documents SET current_parse_id = "
                         "(SELECT p.id FROM estimate_parses p WHERE p.document_id = estimate_documents.id)"))
    missing = conn.execute(sa.text("SELECT count(*) FROM estimate_documents WHERE current_parse_id IS NULL")).scalar()
    differ = conn.execute(sa.text("SELECT count(*) FROM estimate_documents d JOIN estimate_parses p "
                                  "ON p.id = d.current_parse_id WHERE p.parse != d.parse")).scalar()
    if missing or differ:
        raise RuntimeError(f"Parse copy check failed: {missing} without a parse, {differ} differ")
    with op.batch_alter_table("estimate_documents") as b:
        b.drop_column("parse")

    with op.batch_alter_table("files") as b:
        b.drop_index("ix_files_sha256")
        b.create_index("ix_files_sha256", ["sha256"], unique=True)
    op.create_index("uq_jobs_ro_number", "jobs", ["ro_number"], unique=True,
                    sqlite_where=sa.text("ro_number != ''"), postgresql_where=sa.text("ro_number != ''"))


def downgrade():
    raise NotImplementedError("Restore the backup copy tools/migrate.py made before 0006.")

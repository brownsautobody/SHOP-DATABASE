"""Alembic environment: the database comes from db/session.py; tables from db/models.py."""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, event, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.models import Base  # noqa: E402
from db.session import DATABASE_URL  # noqa: E402

config = context.config


def include_object(obj, name, type_, reflected, compare_to):
    # tables left over from removed features (e.g. the production board) are kept as they are, never dropped
    return not (type_ == "table" and reflected and compare_to is None)


def run():
    url = config.get_main_option("sqlalchemy.url") or DATABASE_URL
    # a plain engine: foreign keys stay off while SQLite copies a table to change it (render_as_batch), and are
    # checked once the migration is done
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":  # make SQLite DDL transactional: a failed migration leaves nothing behind
        @event.listens_for(engine, "connect")
        def _manual(dbapi_conn, _):
            dbapi_conn.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata, render_as_batch=True,
                          include_object=include_object, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        if conn.dialect.name == "sqlite":
            bad = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            if bad:
                raise RuntimeError(f"Foreign keys broken after migration: {bad[:10]}")


run()

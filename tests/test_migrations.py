"""The migrations build exactly the tables db/models.py describes, so every schema change comes with a migration."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from db import migrate
from db.models import Base
from db.session import make_engine


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(migrate.config(url), "head")
    with make_engine(url).connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert not diffs, "models and migrations differ - add a migration:\n" + "\n".join(map(str, diffs))

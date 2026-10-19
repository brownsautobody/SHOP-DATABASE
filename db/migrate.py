"""Schema migrations (Alembic) with a backup copy of the database before anything changes it."""
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "0001"  # the schema as it was before Alembic, with jobs.archived_at
RENAMED = "0002"  # jobs.archived_at renamed to closed_at (by hand, before migrations existed)


def config(url):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head(url):
    return ScriptDirectory.from_config(config(url)).get_current_head()


def current(engine):
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def sqlite_path(url):
    return Path(url[len("sqlite:///"):]) if url.startswith("sqlite:///") else None


def backup(url, reason):
    """Copy a SQLite database to <its folder>/backups/<name>-YYYYMMDD-HHMM-before-<reason>.db; returns the copy's path.
    PostgreSQL: returns None - take a pg_dump first."""
    src = sqlite_path(url)
    if src is None or not src.exists():
        return None
    dest = src.parent / "backups" / f"{src.stem}-{datetime.now():%Y%m%d-%H%M}-before-{reason}.db"
    dest.parent.mkdir(exist_ok=True)
    n = 1
    while dest.exists():  # never overwrite an earlier copy
        n += 1
        dest = dest.with_name(f"{src.stem}-{datetime.now():%Y%m%d-%H%M}-before-{reason}-{n}.db")
    with closing(sqlite3.connect(src)) as a, closing(sqlite3.connect(dest)) as b:
        a.backup(b)  # consistent copy even if the app has the file open
    return dest


def stamp(url, rev):
    command.stamp(config(url), rev)


def stamp_existing(engine, url):
    """A database made before Alembic: record which migration its tables already match. Returns that revision."""
    cols = {c["name"] for c in inspect(engine).get_columns("jobs")}
    rev = RENAMED if "closed_at" in cols else BASELINE
    stamp(url, rev)
    return rev


def upgrade(engine, url, log=print):
    """Bring a database up to the newest schema, one migration at a time, each after a fresh backup."""
    if current(engine) is None and "jobs" in inspect(engine).get_table_names():
        log(f"  no migration recorded - tables match {stamp_existing(engine, url)}; stamped")
    script = ScriptDirectory.from_config(config(url))
    while (rev := current(engine)) != script.get_current_head():
        nxt = next(s for s in script.walk_revisions() if s.down_revision == rev)
        copy = backup(url, nxt.revision)
        log(f"  backup: {copy}" if copy else "  not SQLite - take a backup (pg_dump) before migrating")
        command.upgrade(config(url), nxt.revision)
        log(f"  migrated to {nxt.revision}: {nxt.doc}")

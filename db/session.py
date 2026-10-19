"""Database connection. SQLite file by default; set DATABASE_URL for PostgreSQL."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker

from .models import Base, Shop

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SHOP_DATA_DIR", ROOT / "data"))
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'shop.db'}")


def make_engine(url=DATABASE_URL):
    if url.startswith("sqlite:///"):
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(conn, _):  # SQLite ignores foreign keys unless asked
            conn.execute("PRAGMA foreign_keys=ON")
    return engine


class NeedsMigration(RuntimeError):
    pass


def init_db(engine):
    """A new database gets every table and is stamped at the newest migration; an existing one must already be at
    the newest migration (python tools/migrate.py backs it up and updates it). Adds the one shop row. Returns a
    session factory."""
    from . import migrate
    url = engine.url.render_as_string(hide_password=False)
    if "jobs" not in inspect(engine).get_table_names():
        Base.metadata.create_all(engine)
        migrate.stamp(url, "head")
    elif migrate.current(engine) != migrate.head(url):
        raise NeedsMigration(f"The database ({url}) is on an older schema. Back it up and update it with: "
                             "python tools/migrate.py")
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as s:
        if s.scalar(select(Shop.id).limit(1)) is None:
            s.add(Shop(name="Brown's Body Shop"))
        from .closing import seed
        seed(s)  # the default closing checklist, if the database has none
        s.commit()
    return Session

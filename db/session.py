"""Database connection. SQLite file by default; set DATABASE_URL for PostgreSQL."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, select
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


def init_db(engine):
    """Create any missing tables and the one shop row. Returns a session factory."""
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as s:
        if s.scalar(select(Shop.id).limit(1)) is None:
            s.add(Shop(name="Brown's Body Shop"))
            s.commit()
    return Session

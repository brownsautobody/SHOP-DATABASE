"""Update the database to the newest schema:   python tools/migrate.py
Each migration runs after a fresh backup copy (<data folder>/backups/...-before-<migration>.db). A database made
before migrations existed is first stamped with the migration its tables already match."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import migrate  # noqa: E402
from db.session import DATABASE_URL, make_engine  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    engine = make_engine()
    migrate.upgrade(engine, DATABASE_URL)
    print("Up to date:", migrate.current(engine))

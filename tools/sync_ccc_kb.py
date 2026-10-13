"""Copy CCC's public help center into the knowledge base:  python tools/sync_ccc_kb.py
(uses the database chosen by SHOP_DATA_DIR / DATABASE_URL, like the app)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402
from kb.ccc_help import sync  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    Session = init_db(make_engine())
    with Session() as s:
        summary = sync(s)
        s.commit()
    print("Done:", summary)

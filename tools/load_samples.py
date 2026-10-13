"""Save every PDF in samples/ into the database - for a test copy:  set SHOP_DATA_DIR=data\\test, then run
python tools/load_samples.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.save import save_parse  # noqa: E402
from db.session import DATA_DIR, DATABASE_URL, init_db, make_engine  # noqa: E402
from estimate_parser.core import parse_pdf  # noqa: E402


def main():
    print("Database:", DATABASE_URL)
    Session = init_db(make_engine())
    with Session() as s:
        for f in sorted((ROOT / "samples").glob("**/*.pdf"), key=lambda p: p.name.lower()):
            data = f.read_bytes()
            try:
                doc, is_new = save_parse(s, parse_pdf(str(f), f.name), data, DATA_DIR / "files")
            except Exception as e:  # keep going; report the file
                s.rollback()
                print(f"  FAILED {f.name}: {e}")
                continue
            s.commit()
            print(f"  {'saved  ' if is_new else 'already'} {f.name} -> job {doc.job_id}")


if __name__ == "__main__":
    main()

"""Save every estimate PDF in a folder (default samples/, subfolders included) into the database - for a test copy:
set SHOP_DATA_DIR=data\\test, then run   python tools/load_samples.py [folder]
PDFs that are not CCC ONE / Mitchell estimates (scan reports, invoices...) are skipped."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.save import save_parse  # noqa: E402
from db.session import DATA_DIR, DATABASE_URL, init_db, make_engine  # noqa: E402
from estimate_parser.core import detect_format, parse_pdf  # noqa: E402
from estimate_parser.pdfutil import open_pages  # noqa: E402


def is_estimate(path):
    pdf, pages = open_pages(str(path))
    try:
        detect_format(pages)
        return True
    except ValueError:
        return False
    finally:
        pdf.close()


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples"
    print("Database:", DATABASE_URL, "| folder:", folder)
    skipped = 0
    Session = init_db(make_engine())
    with Session() as s:
        for f in sorted(folder.glob("**/*.pdf"), key=lambda p: str(p).lower()):
            if not is_estimate(f):
                skipped += 1
                continue
            data = f.read_bytes()
            try:
                doc, is_new = save_parse(s, parse_pdf(str(f), f.name), data, DATA_DIR / "files")
            except Exception as e:  # keep going; report the file
                s.rollback()
                print(f"  FAILED {f.name}: {e}")
                continue
            s.commit()
            print(f"  {'saved  ' if is_new else 'already'} {f.relative_to(folder)} -> job {doc.job_id}")
    print(f"Skipped {skipped} PDF(s) that are not estimates.")


if __name__ == "__main__":
    main()

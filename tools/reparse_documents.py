"""Re-read every saved estimate whose parse came from an older parser version, from its stored PDF. Job fields typed
in by hand are kept; each change is logged.   python tools/reparse_documents.py [--all]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from db.models import EstimateDocument  # noqa: E402
from db.save import reparse_document  # noqa: E402
from db.session import DATABASE_URL, init_db, make_engine  # noqa: E402
from estimate_parser.core import PARSER_VERSION, parse_pdf  # noqa: E402

if __name__ == "__main__":
    print("Database:", DATABASE_URL)
    with init_db(make_engine())() as s:
        docs = select(EstimateDocument)
        if "--all" not in sys.argv:
            docs = docs.where(EstimateDocument.parser_version != PARSER_VERSION)
        n = 0
        for d in s.scalars(docs).all():
            was = d.review_reasons or []
            reparse_document(s, d, parse_pdf(d.file.path, d.file.original_name))
            n += 1
            print(f"  job {d.job_id} {d.display}: review {len(was)} -> {len(d.review_reasons or [])}"
                  f"{'' if not d.review_reasons else ' (' + '; '.join(d.review_reasons) + ')'}")
        s.commit()
    print(f"Re-read {n} document(s) with parser {PARSER_VERSION}.")

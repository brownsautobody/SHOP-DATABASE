"""Summarize how the parser's output differs from the saved snapshots (or another snapshot folder):
    python tests/snapshot_report.py [snapshot folder] [--detail]
Changes are grouped by field (list positions shown as [*]) with how many PDFs each touches; --detail lists every
value per PDF."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from estimate_parser.core import jsonable, parse_pdf  # noqa: E402
from test_parser_snapshots import PDFS, SNAPSHOTS, diff  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(args[0]) if args else SNAPSHOTS
    by_field, per_pdf = defaultdict(set), {}
    for path, sha in PDFS:
        snap = folder / f"{sha}.json"
        if not snap.exists():
            print(f"no snapshot: {path.name}")
            continue
        changes = diff(json.loads(snap.read_text(encoding="utf-8")), jsonable(parse_pdf(str(path), path.name)))
        if changes:
            per_pdf[path.name] = changes
            for c in changes:
                by_field[re.sub(r"\[\d+\]", "[*]", c.split(":")[0])].add(path.name)
    print(f"{len(per_pdf)} of {len(PDFS)} PDFs changed")
    for field, pdfs in sorted(by_field.items(), key=lambda x: (-len(x[1]), x[0])):
        print(f"  {len(pdfs):3} PDF(s)  {field}")
    if "--detail" in sys.argv:
        for name, changes in per_pdf.items():
            print(f"\n{name}")
            for c in changes:
                print("   ", c)

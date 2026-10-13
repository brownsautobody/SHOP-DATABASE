"""Look things up in the knowledge base (not part of the shop's screens - reference for building and checking the
parser, and for technical questions).

  python tools/kb_search.py "labor hours"            articles whose title or text contain the words, with a snippet
  python tools/kb_search.py --show 1234              full text of one article (by its knowledge base id)
  python tools/kb_search.py --tree                   the tree: sections and their articles

Uses the database chosen by SHOP_DATA_DIR / DATABASE_URL, like the app."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import and_, select  # noqa: E402

from db.models import KbLink, KbNode  # noqa: E402
from db.session import init_db, make_engine  # noqa: E402


def _path(s, node):
    parts = []
    while node.parent_id:
        node = s.get(KbNode, node.parent_id)
        parts.insert(0, node.title)
    return " > ".join(parts)


def search(s, words, limit):
    """Every word must appear in the title or text; title matches first."""
    conds = [KbNode.title.ilike(f"%{w}%") | KbNode.body_text.ilike(f"%{w}%") for w in words]
    rows = s.scalars(select(KbNode).where(KbNode.kind == "article", KbNode.active, and_(*conds))).all()
    rows.sort(key=lambda n: (-sum(w.lower() in n.title.lower() for w in words), n.title))
    print(f"{len(rows)} article(s) match {' + '.join(words)!r}" + (f" - showing {limit}" if len(rows) > limit else ""))
    for n in rows[:limit]:
        text = n.body_text.replace("\n", " ")
        i = text.lower().find(words[0].lower())
        snippet = text[max(0, i - 100): i + 200] if i >= 0 else text[:300]
        print(f"\n[{n.id}] {n.title}\n    {_path(s, n)}\n    {n.url}\n    ...{snippet}...")


def show(s, node_id):
    n = s.get(KbNode, node_id)
    if n is None:
        sys.exit(f"No knowledge base entry {node_id}")
    print(f"[{n.id}] {n.title}\n{_path(s, n)}\n{n.url}\nUpdated by source: {n.source_updated_at}"
          f"{'' if n.active else '  (no longer on the source site)'}\n\n{n.body_text}")
    links = s.scalars(select(KbLink).where(KbLink.from_node_id == n.id, KbLink.kind == "article")).all()
    if links:
        print("\nLinks to other articles:")
        for ln in links:
            print(f"  [{ln.to_node_id or '-'}] {ln.text or ln.href}")


def tree(s):
    nodes = s.scalars(select(KbNode).where(KbNode.active)).all()
    kids = {}
    for n in sorted(nodes, key=lambda n: (n.kind == "article", n.position, n.title)):
        kids.setdefault(n.parent_id, []).append(n)

    def walk(parent, depth):
        for n in kids.get(parent, []):
            print("  " * depth + (f"[{n.id}] {n.title}" if n.kind == "article" else f"## {n.title}"))
            walk(n.id, depth + 1)
    walk(None, 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # CCC text uses (R), (TM) and other symbols
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*")
    ap.add_argument("--show", type=int, metavar="ID")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()
    with init_db(make_engine())() as s:
        if a.show:
            show(s, a.show)
        elif a.tree:
            tree(s)
        elif a.words:
            search(s, a.words, a.limit)
        else:
            ap.print_help()

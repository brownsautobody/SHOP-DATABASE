"""Copy CCC's public help center (cccis.zendesk.com) into the knowledge base.

The web pages block automated visitors, so this reads Zendesk's public Help Center API (allowed by the site's
robots.txt): categories -> sections (nested) -> articles. Nothing is deleted: a changed article keeps its old
version in kb_revisions, and one that disappears is marked inactive."""
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from sqlalchemy import select

from db.models import KbLink, KbNode, KbRevision, KbSource, Shop, now
from db.save import audit

NAME = "CCC ONE Help Center"
BASE = "https://cccis.zendesk.com"
API = BASE + "/api/v2/help_center/en-us/"
USER_AGENT = "Shop Database knowledge base sync (Brown's Body Shop)"
DELAY = 1.0  # seconds between requests
ARTICLE_LINK = re.compile(r"/hc/[^/]+/articles/(\d+)")


def _get_all(path, key, log=print):
    """Every item of a paginated API list."""
    url, items = API + path, []
    while url:
        log(f"  fetching {url}")
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}), timeout=60) as r:
            data = json.load(r)
        items += data[key]
        url = data.get("next_page")
        if url:
            time.sleep(DELAY)
    return items


class _Text(HTMLParser):
    """HTML -> readable text, collecting links and images on the way."""
    BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "ul", "ol", "section", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.links, self._a, self._skip = [], [], None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("td", "th"):
            self.out.append(" | ")
        if tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "text": []}
        elif tag == "img" and a.get("src"):
            self.links.append({"kind": "image", "href": a["src"], "text": a.get("alt") or ""})
            self.out.append(f"[picture{': ' + a['alt'] if a.get('alt') else ''}]")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
        elif tag in self.BLOCK or tag == "li":
            self.out.append("\n")
        if tag == "a" and self._a:
            self.links.append({"kind": "link", "href": self._a["href"], "text": " ".join(self._a["text"]).strip()})
            self._a = None

    def handle_data(self, data):
        if self._skip:
            return
        self.out.append(data)
        if self._a is not None:
            self._a["text"].append(data.strip())

    def text(self):
        t = re.sub(r"[ \t\xa0]+", " ", "".join(self.out))
        return re.sub(r"\n\s*\n+", "\n\n", "\n".join(line.strip() for line in t.splitlines())).strip()


def html_to_text(html):
    p = _Text()
    p.feed(html or "")
    p.close()
    return p.text(), p.links


def _sha(title, body):
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


def source(s):
    src = s.scalar(select(KbSource).where(KbSource.name == NAME))
    if src is None:
        shop_id = s.scalar(select(Shop.id).order_by(Shop.id).limit(1))
        src = KbSource(shop_id=shop_id, name=NAME, kind="web_docs", base_url=BASE + "/hc/en-us")
        s.add(src)
        s.flush()
    return src


def sync(s, log=print):
    """Fetch everything and bring the knowledge base up to date. Returns a summary dict. Caller commits."""
    src = source(s)
    log("Reading CCC help center...")
    cats = _get_all("categories.json?per_page=100", "categories", log)
    time.sleep(DELAY)
    secs = _get_all("sections.json?per_page=100", "sections", log)
    time.sleep(DELAY)
    arts = [a for a in _get_all("articles.json?per_page=100", "articles", log) if not a.get("draft")]

    existing = {(n.kind, n.external_id): n for n in s.scalars(select(KbNode).where(KbNode.source_id == src.id))}
    counts = {"new": 0, "changed": 0, "unchanged": 0, "removed": 0}
    seen, changed_nodes = set(), []

    def upsert(kind, item, body=""):
        key = (kind, str(item["id"]))
        seen.add(key)
        title = item.get("title") or item.get("name") or ""
        sha = _sha(title, body)
        node = existing.get(key)
        if node is None:
            node = KbNode(source_id=src.id, kind=kind, external_id=key[1])
            s.add(node)
            existing[key] = node
            counts["new"] += 1
        elif node.sha256 != sha:
            s.add(KbRevision(node_id=node.id, title=node.title, body_html=node.body_html, sha256=node.sha256,
                             source_updated_at=node.source_updated_at))
            counts["changed"] += 1
        else:
            counts["unchanged"] += 1
            node.active = True
            return node
        node.title, node.url, node.position = title, item.get("html_url", ""), item.get("position") or 0
        node.body_html, node.sha256, node.source_updated_at = body, sha, item.get("updated_at") or ""
        node.body_text, _ = html_to_text(body)
        node.fetched_at, node.active = now(), True
        changed_nodes.append(node)
        return node

    for c in cats:
        upsert("category", c)
    for sec in secs:
        upsert("section", sec)
    for a in arts:
        upsert("article", a, a.get("body") or "")
    s.flush()

    # parents: section -> parent section or category; article -> section
    for sec in secs:
        parent = existing.get(("section", str(sec["parent_section_id"]))) if sec.get("parent_section_id") \
            else existing.get(("category", str(sec["category_id"])))
        existing[("section", str(sec["id"]))].parent_id = parent.id if parent else None
    for a in arts:
        parent = existing.get(("section", str(a["section_id"])))
        existing[("article", str(a["id"]))].parent_id = parent.id if parent else None

    for key, node in existing.items():
        if key not in seen and node.active:
            node.active = False
            counts["removed"] += 1

    # links of new / changed articles (derived from the body, so they are rebuilt)
    for node in changed_nodes:
        for old in s.scalars(select(KbLink).where(KbLink.from_node_id == node.id)):
            s.delete(old)
        _, links = html_to_text(node.body_html)
        for ln in links:
            href = urljoin(node.url or BASE, ln["href"])
            m = ARTICLE_LINK.search(href)
            if ln["kind"] == "link" and (ln["href"].startswith("#") or (m and m.group(1) == node.external_id)):
                continue  # a jump to a heading on the same page, not a link to another page
            kind = "image" if ln["kind"] == "image" else "article" if m else "external"
            s.add(KbLink(from_node_id=node.id, kind=kind, text=ln["text"][:300], href=href[:1000]))
    s.flush()
    by_ext = {n.external_id: n.id for (k, _), n in existing.items() if k == "article"}
    for ln in s.scalars(select(KbLink).where(KbLink.kind == "article", KbLink.to_node_id.is_(None))):
        m = ARTICLE_LINK.search(ln.href)
        ln.to_node_id = by_ext.get(m.group(1)) if m else None

    src.last_synced_at = now()
    summary = {**counts, "categories": len(cats), "sections": len(secs), "articles": len(arts)}
    audit(s, "kb_sources", src.id, "sync", new=json.dumps(summary))
    return summary

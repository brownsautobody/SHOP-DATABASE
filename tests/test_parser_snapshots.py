"""Parse every estimate PDF and compare the full parse_pdf() result with its saved snapshot,
tests/snapshots/<sha256 of the PDF>.json. A parser change then shows up as a list of the values it changed.

PDFs: samples/ and, when present, the 2026 test set's stored files (data/test2026/files). Both hold customer data, so
they and the snapshots stay out of git. Accept new or changed snapshots:   pytest --update-snapshots"""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from estimate_parser.core import parse_pdf

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / "samples", ROOT / "data" / "test2026" / "files"]
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"


def _pdfs():
    """Every estimate PDF once (the same file can sit in both folders), by name."""
    seen = {}
    for folder in SOURCES:
        for p in sorted(folder.glob("**/*.pdf"), key=lambda p: str(p).lower()) if folder.exists() else []:
            seen.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), p)
    return sorted(((p, sha) for sha, p in seen.items()), key=lambda x: str(x[0]).lower())


def jsonable(result):
    """The parse as JSON would store it (Decimal -> number)."""
    return json.loads(json.dumps(result, default=lambda o: float(o) if isinstance(o, Decimal) else str(o)))


def diff(old, new, path=""):
    """Every value that differs, as 'path: old -> new' lines."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new), key=str):
            if k not in new:
                out.append(f"{path}.{k}: removed (was {old[k]!r})")
            elif k not in old:
                out.append(f"{path}.{k}: added {new[k]!r}")
            else:
                out += diff(old[k], new[k], f"{path}.{k}")
        return out
    if isinstance(old, list) and isinstance(new, list):
        out = [x for i, (a, b) in enumerate(zip(old, new)) for x in diff(a, b, f"{path}[{i}]")]
        out += [f"{path}[{i}]: removed (was {old[i]!r})" for i in range(len(new), len(old))]
        out += [f"{path}[{i}]: added {new[i]!r}" for i in range(len(old), len(new))]
        return out
    return [] if old == new else [f"{path}: {old!r} -> {new!r}"]


PDFS = _pdfs()


@pytest.mark.skipif(not PDFS, reason="no sample PDFs on this machine (samples/ is kept out of git)")
@pytest.mark.parametrize("path,sha", PDFS, ids=[p.name[:24] for p, _ in PDFS] or None)
def test_snapshot(path, sha, request):
    got = jsonable(parse_pdf(str(path), path.name))
    snap = SNAPSHOTS / f"{sha}.json"
    if request.config.getoption("--update-snapshots"):
        SNAPSHOTS.mkdir(exist_ok=True)
        snap.write_text(json.dumps(got, indent=1, sort_keys=True), encoding="utf-8")
        return
    if not snap.exists():
        pytest.fail(f"No snapshot for {path.name} yet - run pytest --update-snapshots")
    changes = diff(json.loads(snap.read_text(encoding="utf-8")), got)
    assert not changes, f"{path.name}: {len(changes)} value(s) changed\n" + "\n".join(changes)

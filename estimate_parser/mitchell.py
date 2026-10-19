"""Parser for Mitchell Cloud Estimating PDFs."""
import re
from decimal import Decimal

from .labor import MITCHELL_TYPES, category
from .pdfutil import dec, group_rows, is_num, money, num, page_text

STOP_ROW = re.compile(r"^(Parts Vendors|Recycled Part Vendors|Estimate Totals|Committed On|\*+ Judgment)")


def _header_cols(row):
    by = {}
    for w in row["words"]:
        by.setdefault(w["text"], []).append(w)
    if not all(k in by for k in ("Line", "Description", "Operation", "Qty", "Tax")):
        return None
    types = sorted(by["Type"], key=lambda w: w["x0"])
    tot = sorted(by["Total"], key=lambda w: w["x0"])
    return {
        "desc": by["Description"][0]["x0"] - 4,
        "op": by["Operation"][0]["x0"] - 4,
        "ltype": types[0]["x0"] - 4,
        "units": tot[0]["x0"] - 4,
        "ptype": types[-1]["x0"] - 4,
        "pnum": by["Number"][0]["x0"] - 4,
        "qty": by["Qty"][0]["x0"] - 4,
        "price": tot[-1]["x0"] - 4,
        "tax": by["Tax"][0]["x0"] - 4,
    }


def _band(x0, cols):
    order = ["desc", "op", "ltype", "units", "ptype", "pnum", "qty", "price", "tax"]
    band = "id"
    for name in order:
        if x0 >= cols[name]:
            band = name
    return band


def _parse_page(rows, cols, section):
    """Return (items, section) for the line-item table on one page."""
    anchors, others, sections = [], [], []
    for r in rows:
        if STOP_ROW.match(r["text"]):
            break
        ws = r["words"]
        num_w = next((w for w in ws if w["text"].isdigit() and 44 <= w["x0"] < 66), None)
        if num_w:
            supp = next((x for x in ws if re.match(r"^S\d+$", x["text"]) and x["x0"] < 44), None)
            opc = next((x for x in ws if 66 <= x["x0"] < cols["desc"]), None)
            anchors.append({"n": int(num_w["text"]), "y": num_w["top"], "supp": supp["text"] if supp else "",
                            "opcode": opc["text"] if opc else ""})
            used = {id(num_w)} | ({id(supp)} if supp else set()) | ({id(opc)} if opc else set())
        else:
            used = set()
            # heading rows sit flush left with nothing in the item columns
            if ws[0]["x0"] < 32 and not re.match(r"^S\d+$", ws[0]["text"]) and all(w["x0"] < cols["op"] for w in ws):
                sections.append({"y": r["top"], "text": r["text"]})
                continue
        for w in ws:
            if id(w) in used or (re.match(r"^S\d+$", w["text"]) and w["x0"] < 44):
                continue
            others.append(w)
    if not anchors:
        return [], section
    # pick up wrapped opcode cells like '63353' that sit on a row of their own (handled below by band)
    items = {a["n"]: {"anchor": a, "cells": {}, "section": None} for a in anchors}
    ordered = sorted(anchors, key=lambda a: a["y"])
    for w in others:
        best = min(ordered, key=lambda a: abs(w["top"] - a["y"]))
        band = _band(w["x0"], cols)
        if band == "id":
            continue
        items[best["n"]]["cells"].setdefault(band, []).append(w)
    # section for each item = last heading above it (or carried over from previous page)
    cur = section
    events = sorted([(s["y"], "s", s["text"]) for s in sections] + [(a["y"], "a", a["n"]) for a in ordered])
    for _, kind, val in events:
        if kind == "s":
            cur = val
        else:
            items[val]["section"] = cur
    return [items[a["n"]] for a in ordered], cur


def _cell(item, band, join=" "):
    ws = sorted(item["cells"].get(band, []), key=lambda w: (round(w["top"]), w["x0"]))
    return join.join(w["text"] for w in ws)


def _build(item):
    a = item["anchor"]
    desc = _cell(item, "desc")
    op = _cell(item, "op")
    ltype = _cell(item, "ltype").replace("*", "")
    units_raw = _cell(item, "units")
    ptype = _cell(item, "ptype")
    pnum = (_cell(item, "pnum", "") + " " + a["opcode"]).strip() if False else _cell(item, "pnum", "")
    qty = _cell(item, "qty")
    price = _cell(item, "price")
    tax = _cell(item, "tax")
    return {
        "line": a["n"], "supp": a["supp"], "opcode": a["opcode"], "section": item["section"] or "",
        "desc": desc, "op": op, "labor_type": ltype, "units_raw": units_raw, "part_type": ptype,
        "part_no": pnum, "qty": qty, "price_raw": price, "taxed": tax.lower().startswith("yes"),
    }


def parse_items(pages):
    items, cols, section = [], None, None
    for page in pages:
        text = page_text(page)
        if "Delta Report" in text[:200]:
            break
        rows = group_rows(page)
        start = None
        for i, r in enumerate(rows):
            c = _header_cols(r)
            if c:
                cols, start = c, i + 1
                break
        if start is None or not cols:
            continue
        parsed, section = _parse_page(rows[start:], cols, section)
        items += [_build(p) for p in parsed]
    return items


def expand(item):
    """Turn one Mitchell line into itemized charge rows."""
    out = []
    sec = item["section"].lower()
    base = {"line": item["line"], "section": item["section"], "op": item["op"], "desc": item["desc"],
            "part_no": item["part_no"], "flags": item["supp"]}
    desc = item["desc"]
    price_tok = item["price_raw"].split()[0] if item["price_raw"] else ""
    price = money(price_tok) if price_tok and is_num(price_tok) else None
    is_cost = "additional cost" in item["op"].lower() or sec.startswith("additional costs")
    units_tok = item["units_raw"].split()[0] if item["units_raw"] else ""
    units = num(units_tok.replace("*", "")) if units_tok and is_num(units_tok.replace("*", "")) else None
    units_inc = units_tok.upper().startswith("INC")
    ptype = item["part_type"]

    if not item["op"] and not item["labor_type"] and price is None and not ptype:
        return out  # free-text note line

    if price == 0 and units is not None and not is_cost:
        price = None  # labor-only operation that prints a $0.00 price column
    if price is not None:
        if is_cost:
            cat = "Other Charge"
        elif "sublet" in ptype.lower():
            cat = "Sublet"
        elif (ptype and ptype.lower() != "existing") or item["part_no"]:
            cat = "Part"
        else:
            cat = "Other Charge"
        qty = num(item["qty"]) if item["qty"] and is_num(item["qty"]) else None
        out.append({**base, "category": cat, "qty": qty, "part_type": ptype, "hours": None, "rate": None,
                    "amount": price, "taxed": item["taxed"]})
    elif item["qty"] and ptype.lower() != "existing":
        # part whose price is 'INC' (included)
        qty = num(item["qty"]) if item["qty"] and is_num(item["qty"]) else None
        out.append({**base, "category": "Part", "qty": qty, "part_type": ptype, "hours": None, "rate": None,
                    "amount": Decimal("0"), "taxed": item["taxed"], "note": "price included"})
    if units is not None and not units_inc and item["labor_type"]:
        cat = MITCHELL_TYPES.get(item["labor_type"].lower().split()[0], category(item["labor_type"]))
        if units != 0 or not out:
            out.append({**base, "category": cat, "qty": None, "part_type": "", "hours": units, "rate": None, "amount": None})
    return out


# ---------------------------------------------------------------- totals

def parse_totals(pages):
    rows, on = [], False
    for page in pages:
        for line in page_text(page).splitlines():
            line = line.strip()
            if line.startswith("Estimate Totals"):
                on = True
                continue
            if line.startswith("Less Original") and on:
                pass
            if not on:
                continue
            m = re.match(r"^(?P<l>[A-Za-z ]+Labor)\s+(?P<h>-?[\d.]+)\s*\$(?P<r>[\d,.]+)\s+\$(?P<a>[\d,.]+)$", line)
            if m:
                rows.append({"label": m["l"].replace("Refinish", "Paint"), "hours": dec(m["h"]),
                             "rate": dec(m["r"]), "amount": money(m["a"])})
                continue
            m = re.match(r"^(?P<l>Total Labor)\s+(?P<h>[\d.]+)\s+\$(?P<a>[\d,.]+)$", line)
            if m:
                rows.append({"label": "Total Labor", "hours": dec(m["h"]), "rate": None, "amount": money(m["a"])})
                continue
            m = re.match(r"^(?P<l>[A-Za-z][A-Za-z '\-]*?)(?: [\d.]+%)?\s+(?P<a>-?\$-?[\d,]+\.\d\d)\*?(?:\s+-?\$-?[\d,]+\.\d\d)?$", line)
            if m and not m["l"].startswith(("Committed", "Copyright")):
                label = m["l"]
                pct = re.search(r"([\d.]+%)", line)
                if pct and label.strip() == "Tax":
                    label = f"Tax ({pct.group(1)})"
                rows.append({"label": label, "hours": None, "rate": None, "amount": money(m["a"].replace("$", ""))})
            if line.startswith("Net Supplement Amount"):
                break
    # Mitchell repeats Taxable / Tax / Non-Taxable inside each block; record which block a row belongs to
    sec = "labor"
    for r in rows:
        if r["label"] == "Taxable Parts":
            sec = "parts"
        elif r["label"] in ("Paint Materials", "Shop Materials") and sec == "parts":
            sec = "costs"
        elif r["label"] == "Gross Total" and sec == "costs":
            sec = "gross"
        r["section"] = sec
    return rows


# ---------------------------------------------------------------- header

def _band_values(rows, labels, take=2):
    """labels: list of (name, first_word). Returns {name: text under it}."""
    for i, r in enumerate(rows):
        pos = []
        for name, first in labels:
            w = next((w for w in r["words"] if w["text"] == first), None)
            if not w:
                break
            pos.append((name, w["x0"]))
        else:
            out = {}
            for j, (name, x) in enumerate(pos):
                hi = pos[j + 1][1] - 2 if j + 1 < len(pos) else 9999
                vals = []
                for rr in rows[i + 1:i + 1 + take]:
                    vals += [w["text"] for w in rr["words"] if x - 2 <= w["x0"] < hi]
                out[name] = " ".join(vals)
            return out
    return {}


def parse_header(pages):
    rows = group_rows(pages[0])
    text = page_text(pages[0])
    h = {"document": "Mitchell Estimate"}
    m = re.search(r"\b(\d{2}-\d{9}-\d{2})\b", text)
    h["estimate_id"] = m.group(1) if m else ""  # Mitchell's Estimate ID (the claim # on these samples)
    h["ro_number"] = ""  # Mitchell prints no RO #; the shop types it in
    m = re.search(r"Quote ID\s*\n?(\d+)", text)
    third = "Insured" if any(w["text"] == "Insured" for r in rows for w in r["words"]) else "Claimant"
    o = _band_values(rows, [("owner", "Owner"), ("second", third), ("appraiser", "Appraiser")], take=1)
    h["customer"] = o.get("owner", "")
    h["estimator"] = o.get("appraiser", "")
    ins = _band_values(rows, [("company", "Insurance"), ("claim", "Claim"), ("adjuster", "Adjuster"), ("deductible", "Deductible")], take=2)
    h["insurance"] = ins.get("company", "")
    h["claim"] = ins.get("claim", "")
    h["adjuster"] = ins.get("adjuster", "")
    h["deductible"] = ins.get("deductible", "")
    dates = _band_values(rows, [("reported", "Reported"), ("loss", "Loss")], take=1)
    dm = re.search(r"\d\d/\d\d/\d{4}", dates.get("loss", ""))
    h["loss_date"] = dm.group(0) if dm else ""
    h["created"] = dates.get("reported", "")
    h["phone"] = _owner_phone(rows, third)
    veh = re.search(r"^((?:19|20)\d\d [A-Z][^\n]+)$", text, re.M)
    v = veh.group(1) if veh else ""
    ym = re.match(r"((?:19|20)\d\d)\s+(\S+)\s+(.*)", v)
    vin = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text)
    odo = re.search(r"Odometer.*?\n.*?\n?", text)
    om = re.search(r"Exterior Color License VIN Drivable\n.*?\b[A-HJ-NPR-Z0-9]{17}\b.*\nOdometer[^\n]*\n(\d[\d,]*)", text)
    h["vehicle"] = {
        "year": ym.group(1) if ym else "", "make": ym.group(2) if ym else "",
        "model": ym.group(3) if ym else v, "description": v,
        "vin": vin.group(1) if vin else "", "mileage": om.group(1) if om else "",
    }
    return h


def _owner_phone(rows, third):
    """The owner's phone, printed under the owner's name in the Owner column. Often not printed at all: the phone
    under the Appraiser column is the appraiser's, never the owner's."""
    for i, r in enumerate(rows):
        owner = next((w for w in r["words"] if w["text"] == "Owner"), None)
        nxt = next((w for w in r["words"] if w["text"] == third), None)
        if owner and nxt:
            for rr in rows[i + 1:i + 3]:
                col = " ".join(w["text"] for w in rr["words"] if owner["x0"] - 2 <= w["x0"] < nxt["x0"] - 2)
                m = re.search(r"\(\d{3}\) \d{3}-\d{4}", col)
                if m:
                    return m.group(0)
            return ""
    return ""


# ---------------------------------------------------------------- history

def _dollars(neg1, neg2, digits):
    v = dec(digits)
    return -v if (neg1 or neg2) else v


def parse_history(pages):
    """Original net total and each supplement's amount, exactly as printed on the totals page."""
    lines = [l.strip() for p in pages for l in page_text(p).splitlines()]
    total = original = None
    entries = []
    for l in lines:
        m = re.match(r"^Net Estimate Total\s+(-?)\$(-?)([\d,]+\.\d\d)$", l)
        if m and total is None:
            total = {"label": "Net Estimate Total", "amount": _dollars(m[1], m[2], m[3])}
        m = re.match(r"^Less Original Net Total\s+(-?)\$(-?)([\d,]+\.\d\d)$", l)
        if m and original is None:
            original = {"label": "Original estimate (Less Original Net Total)", "by": "", "amount": _dollars(m[1], m[2], m[3])}
        m = re.match(r"^(S\d+): (.+?)\s+(-?)\$(-?)([\d,]+\.\d\d)$", l)
        if m and not any(e["label"] == f"Supplement {m[1]}" for e in entries):
            entries.append({"label": f"Supplement {m[1]}", "by": m[2], "amount": _dollars(m[3], m[4], m[5])})
    if not original:
        return None
    return {"entries": [original] + entries, "total": total}

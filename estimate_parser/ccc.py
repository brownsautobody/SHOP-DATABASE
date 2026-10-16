"""Parser for CCC ONE estimates and supplements."""
import re

from .pdfutil import group_rows, is_num, num, page_text

OPS = {
    "Repl", "R&I", "Rpr", "O/H", "Blnd", "Refn", "Subl", "Sect", "D&R", "Algn",
    "Remove/Replace", "Remove/Install", "Repair", "Blend", "Refinish", "Overhaul",
}
PART_TYPE_PREFIX = re.compile(
    r"^(Non OEM CAPA|Non OEM NSF|Non OEM|Opt OEM|ALT OEM|OEM|RCY|LKQ|Recond|Reman|A/M|Used)\s+(?=\S)"
)
LABOR_TYPES = {
    "body": "Body", "mech": "Mechanical", "m": "Mechanical", "struc": "Structural", "s": "Structural",
    "frame": "Frame", "f": "Frame", "diag": "Diagnostic", "d": "Diagnostic", "elec": "Electrical",
    "e": "Electrical", "glass": "Body", "g": "Body",
}
OTHER_SECTIONS = {"MISCELLANEOUS OPERATIONS", "OTHER CHARGES"}
STOP_ROW = re.compile(r"^(NOTES\b|ESTIMATE TOTALS|Estimate Totals|T = Taxable|SUPPLEMENT SUMMARY|PARTS SUPPLIER LIST)")


def _header_cols(row):
    words = row["words"]
    by = {}
    for w in words:
        by.setdefault(w["text"], []).append(w)
    if not all(k in by for k in ("Line", "Description", "Qty", "Extended", "Labor", "Paint")):
        return None
    oper = (by.get("Oper") or by.get("Operation") or [None])[0]
    if oper is None:
        return None
    cols = {
        "oper_x0": oper["x0"],
        "qty_x0": by["Qty"][0]["x0"],
        "qty_x1": by["Qty"][0]["x1"],
        "price_x1": by["Extended"][0]["x1"],
        "labor_x0": by["Labor"][0]["x0"],
        "labor_x1": by["Labor"][0]["x1"],
        "paint_x1": by["Paint"][0]["x1"],
        "has_pn": "Number" in by,
    }
    cols["pn_x1"] = by["Number"][0]["x1"] + 14 if "Number" in by else None
    cols["text_end"] = cols["qty_x0"] - 4
    return cols


def _is_section(tokens):
    toks = [t for t in tokens if not re.match(r"^[ES]\d\d$", t)]
    return bool(toks) and all(
        re.match(r"^[A-Z&/,'\-]+$", t) or t in ("&",) for t in toks
    ) and any(len(t) >= 3 for t in toks)


def _parse_item(row, cols, line_no, section):
    words = row["words"][1:]
    tokens = [w["text"] for w in words]
    if _is_section(tokens):
        return {"section_only": " ".join(t for t in tokens if not re.match(r"^[ES]\d\d$", t))}

    flags, text_w, pn_w, other = [], [], [], []
    for w in words:
        x0 = w["x0"]
        if x0 < cols["oper_x0"] - 3:
            flags.append(w["text"])
        elif cols["pn_x1"] and cols["pn_x1"] - 30 <= w["x1"] <= cols["pn_x1"] + 6:
            pn_w.append(w["text"])
        elif x0 < cols["text_end"]:
            text_w.append(w["text"])
        else:
            other.append(w)

    item = {
        "line": line_no, "section": section, "flags": flags, "op": "", "desc": "",
        "part_no": " ".join(pn_w), "qty": None, "price": None, "labor": None, "paint": None,
        "part_type": "", "labor_type": "", "taxed": False, "notes": [],
    }
    op_flags = [f for f in flags if f in OPS]
    if op_flags:
        item["op"] = op_flags[0]
        flags = [f for f in flags if f not in OPS]
    elif text_w and text_w[0] in OPS:
        item["op"] = text_w.pop(0)
    item["desc"] = " ".join(text_w)

    cands = {"qty": cols["qty_x1"], "price": cols["price_x1"], "labor": cols["labor_x1"], "paint": cols["paint_x1"]}
    for w in other:
        t = w["text"]
        if is_num(t):
            col = min(cands, key=lambda c: abs(w["x1"] - cands[c]))
            if abs(w["x1"] - cands[col]) > 22:
                continue
            item[col] = num(t)
            if col == "price" and t.upper().endswith("T"):
                item["taxed"] = True
            if col == "labor" and re.search(r"[A-Za-z]$", t):
                item["labor_type"] = LABOR_TYPES.get(t[-1].lower(), "")
        elif t.lower().startswith("incl") and abs(w["x1"] - cols["labor_x1"]) < 25:
            item["labor"] = "Incl."
        elif t in ("T", "X"):
            item["taxed"] = t == "T"
        elif t in ("m", "s") and w["x1"] < cols["labor_x1"] - 8:
            pass  # lowercase after the price = MOTOR mechanical/structural *part* flag, not the labor type
        elif w["x0"] > cols["price_x1"] - 2 and w["x1"] < cols["labor_x1"] - 22:
            item["part_type"] = (item["part_type"] + " " + t).strip()
        elif w["x0"] >= cols["labor_x1"] - 2 and w["x1"] < cols["paint_x1"] - 15:
            item["labor_type"] = LABOR_TYPES.get(t.lower(), item["labor_type"] or t)

    m = PART_TYPE_PREFIX.match(item["desc"])
    if m:
        item["part_type"] = (item["part_type"] or m.group(1)).strip()
        item["desc"] = item["desc"][m.end():]
    item["flags"] = [f for f in flags if f not in ("#",)] + (["manual entry"] if "#" in flags else [])
    return item


def parse_items(pages):
    items, subtotals = [], []
    state = {"last": None, "cols": None, "section": None}
    for page in pages:
        rows = group_rows(page)
        if any(r["text"].startswith(("SUPPLEMENT SUMMARY", "PARTS SUPPLIER LIST")) for r in rows):
            return items, subtotals
        start = 0
        for i, r in enumerate(rows):
            c = _header_cols(r)
            if c:
                state["cols"], start = c, i + 1
                break
        cols = state["cols"]
        if not cols:
            continue
        started = False
        for r in rows[start:]:
            text = r["text"]
            if text.startswith("SUBTOTALS"):
                subtotals = [float(x.replace(",", "")) for x in re.findall(r"-?[\d,]+\.\d+", text)]
                break
            if STOP_ROW.match(text):
                if text.startswith(("SUPPLEMENT SUMMARY", "PARTS SUPPLIER LIST")):
                    return items, subtotals
                break
            first = r["words"][0]
            n = int(first["text"]) if first["text"].isdigit() and first["x0"] < 45 else None
            last = state["last"]
            # an "Open Line" (O column checked in CCC) prints 'open' where its line number goes; it is still a line
            is_open = n is None and started and first["text"].lower() == "open" and first["x0"] < 45
            if is_open:
                n = (last or 0) + 1
            if n is not None and ((last is None and n <= 5) or n == (last or 0) + 1):
                started = True
                state["last"] = n
                item = _parse_item(r, cols, n, state["section"])
                if "section_only" in item:
                    state["section"] = item["section_only"]
                    continue
                if is_open:
                    item["flags"].append("open line")
                items.append(item)
            elif started and items:
                cont = [w["text"] for w in r["words"] if w["x0"] >= cols["oper_x0"] - 3 and w["x0"] < cols["text_end"]]
                if cont and all(w["x0"] >= cols["oper_x0"] - 3 for w in r["words"] if w["x0"] < cols["text_end"]):
                    if text.startswith("Note:"):
                        items[-1]["notes"].append(text)
                    elif items[-1]["notes"]:  # a note's second line
                        items[-1]["notes"][-1] += " " + text
                    else:
                        items[-1]["desc"] = (items[-1]["desc"] + " " + " ".join(cont)).strip()
    return items, subtotals


def _labor_cat(labor_type):
    return f"{labor_type or 'Body'} Labor"


def expand(item):
    """Turn one estimate line into itemized charge rows (part / labor by type / paint / other)."""
    out = []
    base = {"line": item["line"], "section": item["section"] or "", "op": item["op"],
            "desc": item["desc"], "part_no": item["part_no"], "flags": ", ".join(item["flags"])}
    desc = item["desc"]
    if desc.startswith("**") or desc in ("-", "") and not item["price"]:
        return out
    sec = (item["section"] or "").upper()
    ptype = item["part_type"]
    if item["price"] is not None:
        is_other = sec in OTHER_SECTIONS or ptype.lower() == "other"
        is_sublet = "subl" in (item["op"] + " " + ptype).lower()
        cat = "Sublet" if is_sublet else "Other Charge" if is_other else "Part"
        out.append({**base, "category": cat, "qty": item["qty"], "part_type": ptype,
                    "unit_price": None, "hours": None, "rate": None, "amount": item["price"],
                    "taxed": item["taxed"]})
    labor = item["labor"]
    if isinstance(labor, float) and labor != 0:
        out.append({**base, "category": _labor_cat(item["labor_type"]), "qty": None, "part_type": "",
                    "hours": labor, "rate": None, "amount": None})
    if item["paint"]:
        out.append({**base, "category": "Paint Labor", "qty": None, "part_type": "",
                    "hours": item["paint"], "rate": None, "amount": None})
    if not out and isinstance(labor, float):
        out.append({**base, "category": _labor_cat(item["labor_type"]), "qty": None, "part_type": "",
                    "hours": labor, "rate": None, "amount": None})
    return out


# ---------------------------------------------------------------- totals

_AMT = r"\(?-?[\d,]+\.\d\d\)?"


def _amt(s):
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if "(" in s or "-" in s else v


def parse_totals(pages):
    rows, on = [], False
    for page in pages:
        for line in page_text(page).splitlines():
            line = line.strip()
            if re.match(r"^(ESTIMATE TOTALS|Estimate Totals)", line):
                on = True
            if line.startswith("SUPPLEMENT SUMMARY"):
                return rows
            if not on:
                continue
            m = re.match(rf"^(?P<l>[A-Za-z ]+?)\s+(?P<h>-?[\d.]+) hrs @ \$ ?(?P<r>[\d,.]+) /hr\s+(?P<a>{_AMT})$", line)
            if m:
                rows.append({"label": m["l"], "hours": float(m["h"]), "rate": float(m["r"].replace(",", "")), "amount": _amt(m["a"])})
                continue
            m = re.match(rf"^(?P<l>[A-Za-z ]+Tax)\s+\$ ?(?P<b>[\d,.]+) @ (?P<p>[\d.]+) ?%\s+(?P<a>{_AMT})$", line)
            if m:
                rows.append({"label": f"{m['l']} ({m['p']}%)", "hours": None, "rate": None, "amount": _amt(m["a"])})
                continue
            m = re.match(rf"^(?P<l>Labor, [A-Za-z]+)\s+(?P<r>[\d,.]+)\s+(?P<h>[\d.]+)\s+(?P<a>{_AMT})$", line)
            if m:
                lab = m["l"].split(", ")[1].replace("Refinish", "Paint")
                rows.append({"label": f"{lab} Labor", "hours": float(m["h"]), "rate": float(m["r"].replace(",", "")), "amount": _amt(m["a"])})
                continue
            m = re.match(rf"^(?P<l>[A-Za-z][A-Za-z ,./#$:()]*?)\s+(?:(?P<x>{_AMT})\s+)?(?P<a>{_AMT})$", line)
            if m and not m["l"].startswith(("T =", "Page")):
                rows.append({"label": m["l"].replace("Material, Paint", "Paint Materials").rstrip(" $:"), "hours": None, "rate": None,
                             "amount": _amt(m["a"]), "extra": _amt(m["x"]) if m["x"] else None})
    return rows


# ---------------------------------------------------------------- header

def _band_values(rows, label_words, take=2):
    """Find a row holding all label_words; return {label: text} taken from the rows beneath, by x band."""
    for i, r in enumerate(rows):
        toks = {w["text"]: w for w in r["words"]}
        if all(l in toks for l in label_words):
            xs = [toks[l]["x0"] for l in label_words]
            out = {}
            for j, l in enumerate(label_words):
                hi = xs[j + 1] - 2 if j + 1 < len(xs) else 9999
                same = [w["text"] for w in r["words"] if toks[l]["x1"] <= w["x0"] < hi and not w["text"].endswith(":")]
                vals = []
                for rr in rows[i + 1:i + 1 + take]:
                    vals += [w["text"] for w in rr["words"] if xs[j] - 2 <= w["x0"] < hi]
                out[l] = " ".join(same) if same else " ".join(v for v in vals if not v.endswith(":"))
            return out
    return {}


def parse_header(pages):
    rows = group_rows(pages[0])
    text = page_text(pages[0])
    h = {}  # after each label match spaces only, not line breaks: a blank field stays blank instead of reading the next line
    m = re.search(r"RO Number:[ \t]*(\S+)", text)
    h["ro_number"] = m.group(1) if m else ""
    m = re.search(r"^(Estimate|Preliminary[^\n]*|Supplement[^\n]*|Final[^\n]*)$", text, re.M)
    h["document"] = m.group(1).strip() if m else "Estimate"

    vals = _band_values(rows, ["Customer:", "Insurance:", "Adjuster:", "Estimator:"], take=1)
    if vals:
        h["customer"] = vals["Customer:"]
        h["insurance"] = vals["Insurance:"]
        h["adjuster"] = vals["Adjuster:"]
        h["estimator"] = re.sub(r"\s*Create Date:.*$", "", vals["Estimator:"]).strip()
        m = re.search(r"Claim:[ 	]*(\S+)", text)
        h["claim"] = m.group(1) if m else ""
        m = re.search(r"Deductible:[ 	]*([\d,.]+)", text)
        h["deductible"] = m.group(1) if m else ""
        m = re.search(r"Create Date:[ 	]*(\S+)", text)
        h["created"] = m.group(1) if m else ""
        h["phone"] = ""
    else:
        m = re.search(r"Insured:[ 	]*(.*?)\s+Policy #:", text)
        h["insured"] = m.group(1).strip() if m else ""
        cols = _band_values(rows, ["Owner:", "Inspection", "Insurance"], take=1)
        # the customer is the vehicle's owner; on a liability claim the insured is the other driver
        h["customer"] = cols.get("Owner:", "").strip() or h["insured"]
        m = re.search(r"Written By:[ \t]*(.+)", text)
        h["estimator"] = m.group(1).strip() if m else ""
        m = re.search(r"Adjuster:[ \t]*(.+)", text)
        h["adjuster"] = m.group(1).strip() if m else ""
        m = re.search(r"Claim #:[ \t]*(\S+)", text)
        h["claim"] = m.group(1) if m else ""
        h["insurance"] = cols.get("Insurance", "").title()
        m = re.search(r"Date of Loss:[ \t]*(\S+)", text)
        h["loss_date"] = m.group(1) if m else ""
        phones = re.findall(r"\(\d{3}\) \d{3}-\d{4}", text)
        h["phone"] = next((p for p in phones[1:] if p != phones[0]), "")
        h["deductible"] = ""
        h["created"] = ""

    m = re.search(r"^((?:19|20)\d\d [A-Z].+)$", text, re.M)
    veh = m.group(1) if m else ""
    ym = re.match(r"((?:19|20)\d\d)\s+(\S+)\s+(.*)", veh)
    h["vehicle"] = {
        "year": ym.group(1) if ym else "", "make": ym.group(2) if ym else "",
        "model": ym.group(3) if ym else veh, "description": veh,
    }
    m = re.search(r"VIN:[ \t]*([A-HJ-NPR-Z0-9]{17})", text)
    h["vehicle"]["vin"] = m.group(1) if m else ""
    m = re.search(r"Mileage In:[ \t]*([\d,]+)", text)
    h["vehicle"]["mileage"] = m.group(1) if m else ""
    return h


# ---------------------------------------------------------------- history

def parse_history(pages):
    """'CUMULATIVE EFFECTS OF SUPPLEMENT(S)' block, exactly as printed (only on 'with Summary' documents)."""
    lines = [l.strip() for p in pages for l in page_text(p).splitlines()]
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("CUMULATIVE EFFECTS"))
    except StopIteration:
        return None
    entries, total = [], None
    for l in lines[start + 1:]:
        m = re.match(r"^(Estimate|Supplement S\d+)\s+(-?[\d,]+\.\d\d)\s*(.*)$", l)
        if m:
            entries.append({"label": m.group(1), "by": m.group(3).strip(), "amount": float(m.group(2).replace(",", ""))})
            continue
        m = re.match(r"^(Job Total):\s*\$?\s*(-?[\d,]+\.\d\d)$", l)
        if m:
            total = {"label": m.group(1), "amount": float(m.group(2).replace(",", ""))}
            break
    return {"entries": entries, "total": total} if entries else None


def _hist_amt(s):
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if "(" in s or "-" in s else v


def parse_history_version_table(pages):
    """'Estimate Version Total $' table: Original / Supplement S01... rows printed near the totals (negatives in parentheses)."""
    lines = [l.strip() for p in pages for l in page_text(p).splitlines()]
    starts = [i for i, l in enumerate(lines) if l.startswith("Estimate Version Total")]
    entries = []
    for i in starts[:1]:
        for l in lines[i + 1:]:
            if re.match(r"^(Insurance Total|Customer Total|Balance due|Received)", l):
                break
            m = re.match(r"^(Original|Estimate|Supplement S?\d+)\s+(\(?-?[\d,]+\.\d\d\)?)\s*(.*)$", l)
            if m:
                entries.append({"label": m.group(1), "by": m.group(3).strip(), "amount": _hist_amt(m.group(2))})
    return {"entries": entries, "total": None} if entries else None


def parse_history_anywhere(pages):
    """Last resort: any 'Original' / 'Supplement Sxx' amount rows anywhere in the document."""
    entries, seen = [], set()
    for p in pages:
        for l in page_text(p).splitlines():
            m = re.match(r"^(Original|Supplement S?\d+)\s+(\(?-?[\d,]+\.\d\d\)?)\s*(.*)$", l.strip())
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                entries.append({"label": m.group(1), "by": m.group(3).strip(), "amount": _hist_amt(m.group(2))})
    return {"entries": entries, "total": None} if entries else None


def totals_extra_columns(pages):
    """Which column ('Discount' or 'Markup') an extra amount on a totals row sits under, judged by x position."""
    kinds = {}
    for page in pages:
        rows = group_rows(page)
        head = next((r for r in rows if {"Discount", "Markup"} <= {w["text"] for w in r["words"]}), None)
        if not head:
            continue
        cols = {w["text"]: w["x1"] for w in head["words"] if w["text"] in ("Discount", "Markup")}
        for r in rows:
            if r["top"] <= head["top"]:
                continue
            nums = [w for w in r["words"] if re.match(r"^\(?-?[\d,]+\.\d\d\)?$", w["text"])]
            label = " ".join(w["text"] for w in r["words"] if w["x0"] < (nums[0]["x0"] if nums else 0))
            if len(nums) == 2 and label:
                x = nums[0]["x1"]
                kinds[label.replace("Material, Paint", "Paint Materials")] = min(cols, key=lambda c: abs(cols[c] - x)).lower()
    return kinds

"""Format detection and the shared output shape for parsed estimates."""
import re
from datetime import datetime

from . import ccc, mitchell
from .pdfutil import open_pages, page_text

PARSER_VERSION = "2026.10.13"  # saved with each document; bump when parsing changes so old saves can be re-read
PRICED = {"Part", "Other Charge", "Sublet"}
LABOR_CATEGORIES = ["Body Labor", "Paint Labor", "Mechanical Labor", "Structural Labor",
                    "Frame Labor", "Electrical Labor", "Diagnostic Labor", "Glass Labor"]


def detect_format(pages):
    text = "\n".join(page_text(p) for p in pages[:2])
    if "Mitchell" in text:
        return "Mitchell"
    if "CCC ONE" in text or "Workfile ID" in text or "RO Number" in text:
        return "CCC ONE"
    raise ValueError("Unrecognized estimate format (expected CCC ONE or Mitchell).")


STAGE_RANK = {"unknown": 0, "preliminary": 1, "estimate": 2, "to_repair": 3, "of_record": 4}
STAGE_LABEL = {"unknown": "Unknown", "preliminary": "Preliminary", "estimate": "Estimate", "to_repair": "Estimate to repair",
               "of_record": "Of record"}


def classify_document(title, supplement_hint=None, context=""):
    """Work out stage + supplement number from a document title (never raises; unknown titles stay 'unknown')."""
    t = f"{title} {context}".lower()
    if "prelim" in t:
        stage = "preliminary"
    elif "of record" in t:
        stage = "of_record"
    elif "to repair" in t:
        stage = "to_repair"
    elif "estimate" in t or "supplement" in t:
        stage = "estimate"
    else:
        stage = "unknown"
    m = re.search(r"supplement(?:\s+of\s+record)?\s*#?\s*(\d+)", title.lower())
    if m:
        n = int(m.group(1))
    elif supplement_hint is not None:
        n = supplement_hint
    else:
        n = 1 if "supplement" in title.lower() else 0
    label = STAGE_LABEL[stage] + (f" - supplement {n}" if n else "")
    if stage == "estimate" and n:
        label = f"Supplement {n}"
    return {"title_raw": title, "stage": stage, "supplement_no": n, "label": label}


def _parse_dt(text, fmts):
    for f in fmts:
        try:
            return datetime.strptime(text, f).isoformat(timespec="seconds")
        except ValueError:
            pass
    return ""


def document_info(fmt, header, page1_text, all_text):
    """Type, version and print time of the document."""
    if fmt == "Mitchell":
        pm = re.search(r"Supplement (\d+) Printed (\d{1,2}/\d{1,2}/\d{4} \d\d:\d\d [AP]M)", all_text)
        tag = re.search(r"\bS(\d+)\b", page1_text)
        hint = int(pm.group(1)) if pm else int(tag.group(1)) if tag else 0
        title = f"Supplement {hint}" if hint else "Estimate"
        doc = classify_document(title, hint, context="of record" if "of record" in page1_text.lower() else "")
        pt = pm.group(2) if pm else ""
        if not pt:  # an original estimate prints 'Estimate Printed <time>' instead
            m = re.search(r"Estimate Printed (\d{1,2}/\d{1,2}/\d{4} \d\d:\d\d [AP]M)", all_text)
            pt = m.group(1) if m else ""
        doc["printed_at"] = _parse_dt(pt, ["%m/%d/%Y %I:%M %p"]) if pt else ""
        m = re.search(r"Net Supplement Amount\s+(-?)\$?(-?[\d,]+\.\d\d)", all_text)
    else:
        doc = classify_document(header.get("document", ""))
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d\d:\d\d [AP]M)", all_text)
        doc["printed_at"] = _parse_dt(m.group(1), ["%m/%d/%Y %I:%M:%S %p"]) if m else ""
        m = re.search(r"NET COST OF SUPPLEMENT\s+(-?)([\d,]+\.\d\d)", all_text)
    doc["supplement_amount"] = (-1 if m.group(1) else 1) * float(m.group(2).replace(",", "")) if m else None
    return doc


def _history_check(h, totals=()):
    """Add a sum check to the printed history. The printed total is one the PDF itself prints; nothing is estimated."""
    if not h:
        return None
    parts = round(sum(e["amount"] for e in h["entries"]), 2)
    h["sum"] = parts
    if not h["total"]:
        printed = [t for t in totals if t["label"] in ("Grand Total", "Net Total") and t["hours"] is None]
        match = next((t for t in printed if abs(t["amount"] - parts) <= 0.02), None) or (printed[0] if printed else None)
        h["total"] = {"label": match["label"], "amount": match["amount"]} if match else None
    h["ok"] = bool(h["total"]) and abs(parts - h["total"]["amount"]) <= 0.02
    return h


def _supplement_from_history(h):
    nums = [int(re.search(r"(\d+)$", e["label"]).group(1)) for e in (h or {}).get("entries", []) if "upplement" in e["label"]]
    return max(nums) if nums else 0


def version_key(doc):
    """Sort key: the highest value is the job's current document."""
    return (doc["supplement_no"], STAGE_RANK[doc["stage"]], doc["printed_at"] or "")


def _close(a, b, tol=0.06):
    return abs(a - b) <= tol


def _checks(fmt, charges, totals, subtotals):
    """Compare what we extracted line by line against the estimate's own totals."""
    by_label = {}
    for t in totals:
        by_label.setdefault(t["label"], t)
    checks = []

    def hours(cat):
        return round(sum(c["hours"] for c in charges if c["category"] == cat and c["hours"] is not None), 2)

    # CCC folds any labor type without its own totals row into Body Labor
    body_like = ["Body Labor"] + [c for c in LABOR_CATEGORIES[2:] if c not in by_label]
    if fmt != "CCC ONE":
        body_like = ["Body Labor"]
    for label, cats in (("Body Labor", body_like), ("Paint Labor", ["Paint Labor"]), ("Mechanical Labor", ["Mechanical Labor"])):
        exp = by_label.get(label, {}).get("hours")
        if exp is None:
            continue
        got = round(sum(hours(c) for c in cats), 2)
        checks.append({"name": f"{label} hours", "parsed": got, "expected": exp, "ok": _close(got, exp, 0.01)})

    # total hours: every labor line of any type vs the estimate's own total. Mitchell prints a Total Labor row; CCC
    # prints one row per labor type (Paint Supplies hours are materials, not labor - they can differ by the clear-coat cap)
    rows = [t for t in totals if t["hours"] is not None and t["label"].endswith(" Labor") and t["label"] != "Total Labor"]
    exp = by_label.get("Total Labor", {}).get("hours")
    if exp is None and rows:
        exp = round(sum(t["hours"] for t in rows), 2)
    if exp is not None:
        got = round(sum(c["hours"] for c in charges if c["hours"] is not None and c["category"].endswith(" Labor")), 2)
        checks.append({"name": "Total labor hours", "parsed": got, "expected": exp, "ok": _close(got, exp, 0.01)})

    price_total = round(sum(c["amount"] for c in charges if c["category"] in PRICED and c["amount"] is not None), 2)
    if fmt == "CCC ONE":
        exp = subtotals[0] if subtotals else by_label.get("Parts", {}).get("amount")
        p = by_label.get("Parts", {})
        if not subtotals and exp is not None:
            # printed Parts total = priced lines + markup (or - discount); sublet/misc is printed on its own row
            if p.get("extra") is not None and p.get("extra_kind") == "markup":
                exp = round(exp - p["extra"], 2)
            elif p.get("extra") is not None and p.get("extra_kind") == "discount":
                exp = round(exp + p["extra"], 2)
            # the sublet/misc row is labeled differently between CCC layouts
            exp = round(exp + sum(by_label.get(k, {}).get("amount", 0) for k in ("Sublet/Miscellaneous", "Miscellaneous")), 2)
        name = "Line price total"
    else:
        exp = None
        tp = by_label.get("Taxable Parts", {}).get("amount")
        if tp is not None:  # non-taxable parts (e.g. sublet, labor-only items) are printed in their own row
            tp += next((t["amount"] for t in totals if t["label"] == "Non-Taxable" and t.get("section") == "parts"), 0)
        cost = sum(t["amount"] for t in totals if t["label"] in ("Paint Materials", "Shop Materials", "Other Additional"))
        if tp is not None:
            exp = round(tp + cost, 2)
        name = "Parts + charges total"
    if exp is not None:
        checks.append({"name": name, "parsed": price_total, "expected": exp, "ok": _close(price_total, exp)})
    return checks


def review_flags(r):
    """Reasons a person should look at this parse; an empty list means it checks out."""
    reasons = []
    for c in r["checks"]:
        if not c["ok"]:
            reasons.append(f"{c['name']}: parsed {c['parsed']:,.2f}, estimate prints {c['expected']:,.2f}")
    if not r["checks"]:
        reasons.append("Couldn't find the estimate's printed totals to check against")
    h = r["history"]
    if h and not h["ok"]:
        if h["total"]:
            reasons.append(f"Document history adds up to ${h['sum']:,.2f} but the estimate prints ${h['total']['amount']:,.2f}")
        else:
            reasons.append("Document history has no printed total to check against")
    d = r["document"]
    if d["stage"] == "unknown":
        reasons.append(f"Couldn't tell what kind of document this is (title: '{d['title_raw']}')")
    if not d["printed_at"]:
        reasons.append("Couldn't find the print date")
    return reasons


def parse_pdf(src, filename=""):
    pdf, pages = open_pages(src)
    try:
        fmt = detect_format(pages)
        mod = ccc if fmt == "CCC ONE" else mitchell
        header = mod.parse_header(pages)
        if fmt == "CCC ONE":
            items, subtotals = ccc.parse_items(pages)
        else:
            items, subtotals = mitchell.parse_items(pages), []
        totals = mod.parse_totals(pages)
        if fmt == "CCC ONE":
            kinds = ccc.totals_extra_columns(pages)
            for t in totals:
                if t.get("extra") is not None:
                    t["extra_kind"] = kinds.get(t["label"], "")
        charges = [c for i in items for c in mod.expand(i)]
        n_pages = len(pages)
        history = mod.parse_history(pages)
        if not history and fmt == "CCC ONE":  # different layouts print the history in different places
            history = ccc.parse_history_version_table(pages) or ccc.parse_history_anywhere(pages)
        document = document_info(fmt, header, page_text(pages[0]), chr(10).join(page_text(p) for p in pages))
    finally:
        pdf.close()

    if document["supplement_amount"] is None and history:  # e.g. a $0.00 supplement prints no 'net cost' line
        cur = next((e for e in history["entries"] if re.search(rf"(?<!\d)0*{document['supplement_no']}$", e["label"]) and "upplement" in e["label"]), None)
        if cur and document["supplement_no"]:
            document["supplement_amount"] = cur["amount"]
    n = _supplement_from_history(history)
    if n > document["supplement_no"]:  # the title says 'Estimate' but the document carries supplement amounts
        document["supplement_no"] = n
        document["label"] += f" - includes supplement {n}"
    display = re.sub(r"\s+with summary$", "", document["title_raw"], flags=re.I).strip() or document["label"]
    if "includes supplement" in document["label"]:
        display += " - includes supplement " + str(document["supplement_no"])
    document["display"] = display
    result = {
        "filename": filename, "format": fmt, "pages": n_pages, "header": header, "document": document, "history": _history_check(history, totals),
        "charges": charges, "totals": totals, "checks": _checks(fmt, charges, totals, subtotals),
    }
    result["review"] = review_flags(result)
    result["summary"] = summarize(result)
    return result


# --------------------------------------------------------------- key-data summary

_DROP = {"Parts", "Taxable Parts", "Parts Total", "Parts Adjustments", "Taxable", "Non-Taxable", "Pre-Tax Discount",
         "Total Labor", "Labor Total", "Original", "Original Estimate", "Net Supplement", "Less Original Net Total",
         "Net Supplement Amount"}


def _short_model(model):
    """'Silverado LTZ 4 Door Crew Cab...' -> 'Silverado'; '1500 Silverado LTZ...' -> '1500 Silverado'; drops trim/engine/body."""
    parts = model.split()
    if not parts:
        return ""
    return " ".join(parts[:2]) if parts[0][0].isdigit() and len(parts) > 1 else parts[0]


NUMBER_FIELDS = ["body_hours", "refinish_hours", "mechanical_hours", "other_hours", "total_hours",
                 "labor_amount", "parts", "tax", "grand_total"]


def job_numbers(r):
    """The money and hours a job is tracked by, all as printed on the estimate (None when it doesn't print one).
    The one place lists, totals and exports read from - add a field here and every report can use it."""
    s = r["summary"]
    hours = {x["category"]: x["hours"] for x in s["labor"]}
    by = {}
    for t in r["totals"]:
        by.setdefault(t["label"], t)
    grand = (by.get("Grand Total") or by.get("Gross Total") or {}).get("amount")
    if r["format"] == "Mitchell":  # one 'Tax' row for the whole estimate (the others are per section)
        tax = by.get("Tax", {}).get("amount")
    else:  # CCC prints each tax on its own row (sales, county, municipal...)
        taxes = [t["amount"] for t in r["totals"] if "Tax" in t["label"] and t["hours"] is None]
        tax = round(sum(taxes), 2) if taxes else None
    return {"body_hours": hours.get("Body labor"), "refinish_hours": hours.get("Paint labor"),
            "mechanical_hours": hours.get("Mechanical labor"), "other_hours": hours.get("Other labor"),
            "total_hours": s["total_labor_hours"], "labor_amount": s["total_labor_amount"], "parts": s["parts_total"],
            "tax": tax, "grand_total": grand}


def summarize(r):
    """The handful of fields the shop needs from an estimate."""
    h, v = r["header"], r["header"]["vehicle"]
    charges, totals = r["charges"], r["totals"]
    ro = h.get("ro_number", "")
    rates = {t["label"]: t["rate"] for t in totals if t.get("rate")}

    groups = {"Body": ["Body Labor"], "Paint": ["Paint Labor"], "Mechanical": ["Mechanical Labor"]}
    # every other labor type - including ones the shop made up in CCC - so total hours never drop a line
    seen = {c["category"] for c in charges if c["hours"] is not None and c["category"].endswith(" Labor")}
    groups["Other"] = sorted((set(LABOR_CATEGORIES) | seen) - set(sum(groups.values(), [])))
    labor = []
    for name, cats in groups.items():
        rows = [c for c in charges if c["category"] in cats and c["hours"] is not None]
        hrs = round(sum(c["hours"] for c in rows), 2)
        rate = next((c["rate"] for c in rows if c.get("rate")), None) or next((rates[c] for c in cats if c in rates), None)
        # dollars come from the estimate's printed labor totals rows, never hours x rate
        printed = [t["amount"] for t in totals if t["label"] in cats and t["hours"] is not None and t["amount"] is not None]
        amt = round(sum(printed), 2) if printed else None
        labor.append({"category": f"{name} labor", "hours": hrs, "rate": rate, "amount": amt})

    by = {t["label"]: t["amount"] for t in totals}
    parts = by.get("Parts")
    if parts is None and "Taxable Parts" in by:  # Mitchell: taxable + non-taxable parts, before tax
        parts = round(by["Taxable Parts"] + next((t["amount"] for t in totals if t["label"] == "Non-Taxable" and t.get("section") == "parts"), 0), 2)
    if parts is None:
        parts = round(sum(c["amount"] for c in charges if c["category"] == "Part"), 2)

    labels = {t["label"] for t in totals}
    other_rows, tax_n = [], 0
    for t in totals:
        lab = t["label"]
        is_tax = lab.split(" ")[0] == "Tax" and r["format"] == "Mitchell"
        if is_tax:  # Mitchell prints tax for labor, parts, materials, then the grand total
            lab = {"labor": "Labor tax", "parts": "Parts tax", "costs": "Materials tax", "gross": "Total tax"}.get(t.get("section"), lab) + lab[3:]
        if lab in _DROP or lab in LABOR_CATEGORIES or t["hours"] is not None or not t["amount"]:
            continue
        other_rows.append({"label": lab, "amount": t["amount"]})
    for t in totals:
        if t.get("extra") is not None and t.get("extra_kind"):
            other_rows.insert(0, {"label": f"{t['label']} {t['extra_kind']} (included in {t['label'].lower()} total)", "amount": t["extra"]})
    seen, dedup = set(), []
    for o in other_rows:
        k = (o["label"], o["amount"])
        if k not in seen:
            seen.add(k)
            dedup.append(o)

    return {
        "document": r["document"],
        "history": r["history"],
        "customer": h.get("customer", ""),
        "ro_number": ro if ro.isdigit() and len(ro) == 4 else "",
        "vehicle": " ".join(x for x in (v.get("year"), v.get("make"), _short_model(v.get("model", ""))) if x),
        "vin": v.get("vin", ""),
        "insurance": h.get("insurance", ""),
        "claim": h.get("claim", ""),
        "labor": labor,
        "total_labor_hours": round(sum(x["hours"] for x in labor), 2),
        "total_labor_amount": round(sum(t["amount"] for t in totals if t["hours"] is not None and t["rate"] and t["label"].endswith("Labor")), 2) or None,
        "parts_total": parts,
        "other_charges": dedup,
        "needs_review": bool(r["review"]),
        "review_reasons": r["review"],
    }

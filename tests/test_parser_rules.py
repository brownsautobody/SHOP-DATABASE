"""Parser rules checked on small hand-made inputs (no customer data)."""
from decimal import Decimal

import pytest

from estimate_parser import ccc, core, mitchell
from estimate_parser.labor import category
from estimate_parser.pdfutil import num


class Page:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


# ---------------------------------------------------------------- format detection

def test_ccc_estimate_for_a_customer_named_mitchell_is_ccc():
    page = Page("Workfile ID: 1a2b3c4d\nCustomer: MITCHELL, JOHN\n1200 Mitchell St\nRO Number: 4401")
    assert core.detect_format([page]) == "CCC ONE"


def test_mitchell_estimate_is_mitchell():
    page = Page("Committed On Version Mitchell Cloud EstimatingTM Printed On\nCopyright 1994-2026 Mitchell International, Inc.")
    assert core.detect_format([page]) == "Mitchell"


def test_unknown_format_is_refused():
    with pytest.raises(ValueError):
        core.detect_format([Page("Invoice from Mitchell's Towing")])


# ---------------------------------------------------------------- RO #, labor, numbers

def _parse(fmt="CCC ONE", ro="", charges=(), totals=()):
    r = {"format": fmt, "header": {"ro_number": ro, "customer": "", "insurance": "", "claim": "",
                                   "vehicle": {"year": "", "make": "", "model": "", "vin": ""}},
         "document": {}, "history": None, "charges": list(charges), "totals": list(totals), "review": []}
    r["summary"] = core.summarize(r)
    return r


@pytest.mark.parametrize("printed,kept", [("4401", "4401"), ("10000", "10000"), (" 987 ", "987"), ("A-12", "A-12")])
def test_ro_number_is_kept_as_printed(printed, kept):
    assert _parse(ro=printed)["summary"]["ro_number"] == kept


def test_ccc_glass_labor_is_glass_labor():
    item = {"line": 1, "section": "", "op": "Repl", "desc": "Windshield", "part_no": "", "flags": [], "qty": None,
            "price": None, "labor": Decimal("2.0"), "paint": None, "part_type": "", "labor_type": ccc.CCC_TYPES["g"],
            "taxed": False}
    assert [c["category"] for c in ccc.expand(item)] == ["Glass Labor"]
    assert category("Frame") == "Frame Labor" and category("") == "Body Labor"


def _line(cat, hours):
    return {"category": cat, "hours": Decimal(hours), "amount": None, "rate": None}


def _row(label, hours, amount):
    return {"label": label, "hours": Decimal(hours), "rate": Decimal("60"), "amount": Decimal(amount)}


def test_ccc_check_folds_labor_types_without_their_own_row_into_body():
    charges = [_line("Body Labor", "3.0"), _line("Glass Labor", "1.5"), _line("Paint Labor", "2.0")]
    totals = [_row("Body Labor", "4.5", "270.00"), _row("Paint Labor", "2.0", "120.00")]
    checks = core._checks("CCC ONE", charges, totals, [])
    assert {c["name"]: c["ok"] for c in checks} == {"Body Labor hours": True, "Paint Labor hours": True,
                                                   "Total labor hours": True}


def test_job_hours_come_from_the_printed_labor_rows():
    # glass has no row of its own: CCC prints it inside Body Labor
    r = _parse(charges=[_line("Body Labor", "3.0"), _line("Glass Labor", "1.5"), _line("Paint Labor", "2.0")],
               totals=[_row("Body Labor", "4.5", "270.00"), _row("Paint Labor", "2.0", "120.00")])
    n = core.job_numbers(r)
    assert (n["body_hours"], n["refinish_hours"], n["other_hours"], n["total_hours"]) == (
        Decimal("4.5"), Decimal("2.0"), Decimal("0"), Decimal("6.5"))
    assert n["labor_amount"] == Decimal("390.00")


def test_hours_fall_back_to_lines_when_no_labor_rows_are_printed():
    r = _parse(charges=[_line("Body Labor", "3.0"), _line("Frame Labor", "1.0")])
    n = core.job_numbers(r)
    assert (n["body_hours"], n["other_hours"], n["total_hours"]) == (Decimal("3.0"), Decimal("1.0"), Decimal("4.0"))


# ---------------------------------------------------------------- exact money

def test_amounts_are_read_as_decimal():
    assert num("1,386.25") == Decimal("1386.25")
    assert num("(500.00)") == Decimal("-500.00")
    assert num("$5.10*") == Decimal("5.10")


def test_sums_from_stored_json_are_exact():
    # three taxes that float arithmetic adds to 0.30000000000000004
    r = {"format": "CCC ONE", "totals": [{"label": f"Tax {i}", "hours": None, "amount": 0.1} for i in range(3)],
         "summary": {"labor": [], "total_labor_hours": 0, "total_labor_amount": None, "parts_total": 0}}
    assert core.job_numbers(r)["tax"] == Decimal("0.3")


# ---------------------------------------------------------------- Mitchell owner phone

def _w(text, x0):
    return {"text": text, "x0": x0}


def _rows(*rows):
    return [{"words": [_w(t, x) for t, x in r]} for r in rows]


def test_mitchell_owner_phone_is_read_from_the_owner_column():
    rows = _rows([("Owner", 24), ("Insured", 212), ("Appraiser", 400)],
                 [("JANE", 24), ("DOE", 60), ("JANE", 212), ("DOE", 250), ("SAM", 400)],
                 [("(573)", 24), ("555-0101", 52), ("(Home)", 100)])
    assert mitchell._owner_phone(rows, "Insured") == "(573) 555-0101"


def test_mitchell_appraiser_phone_is_not_the_owner_phone():
    rows = _rows([("Owner", 24), ("Insured", 212), ("Appraiser", 400)],
                 [("JANE", 24), ("DOE", 60), ("SAM", 400)],
                 [("(440)", 400), ("620-3708", 430)])
    assert mitchell._owner_phone(rows, "Insured") == ""


class WordPage(Page):
    """A page from (text, x0, top) words, for the header parsers."""

    def __init__(self, words):
        self.words = [{"text": t, "x0": x, "x1": x + 6 * len(t), "top": top} for t, x, top in words]
        lines = {}
        for w in self.words:
            lines.setdefault(w["top"], []).append(w["text"])
        super().__init__("\n".join(" ".join(v) for _, v in sorted(lines.items())))

    def extract_words(self, **kw):
        return self.words


def test_mitchell_header_reads_the_owner_phone():
    page = WordPage([("Owner", 24, 180), ("Insured", 212, 180), ("Appraiser", 400, 180),
                     ("JANE", 24, 190), ("DOE", 60, 190), ("SAM", 400, 190),
                     ("(573)", 24, 200), ("555-0101", 60, 200), ("(440)", 400, 200), ("620-3708", 436, 200)])
    h = mitchell.parse_header([page])
    assert (h["customer"], h["phone"], h["ro_number"]) == ("JANE DOE", "(573) 555-0101", "")

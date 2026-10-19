"""Hand-made estimates for tests: parse_pdf()-shaped dicts holding only what saving and matching read."""
import itertools
from decimal import Decimal

from db.save import save_parse

VIN_A = "1HGCM82633A004352"
VIN_B = "2T1BURHE0JC034461"
_n = itertools.count()


def make(ro="", claim="", vin="", printed="2026-09-01T10:00:00", customer="DOE, JANE", phone="", insurance="Acme Ins",
         supplement_no=0, stage="estimate", fmt="CCC ONE", body_hours=None, grand_total=None, loss_date="",
         deductible="", mileage="", adjuster="", estimator=""):
    doc = {"title_raw": "Estimate", "display": "Estimate", "label": "Estimate", "stage": stage,
           "supplement_no": supplement_no, "printed_at": printed, "supplement_amount": None}
    header = {"ro_number": ro, "claim": claim, "customer": customer, "phone": phone, "insurance": insurance,
              "adjuster": adjuster, "estimator": estimator, "loss_date": loss_date, "deductible": deductible,
              "vehicle": {"year": "2020", "make": "Honda", "model": "Accord", "description": "2020 Honda Accord",
                          "vin": vin, "mileage": mileage}}
    labor = [{"category": "Body labor", "hours": Decimal(body_hours), "rate": None, "amount": None}] if body_hours else []
    totals = [{"label": "Grand Total", "hours": None, "rate": None, "amount": Decimal(grand_total)}] if grand_total else []
    summary = {"document": doc, "history": None, "customer": customer, "ro_number": ro, "vehicle": "2020 Honda Accord",
               "vin": vin, "insurance": insurance, "claim": claim, "labor": labor,
               "total_labor_hours": Decimal(body_hours or 0), "total_labor_amount": None, "parts_total": Decimal(0),
               "other_charges": [], "needs_review": False, "review_reasons": []}
    return {"filename": "test.pdf", "format": fmt, "pages": 1, "header": header, "document": doc, "history": None,
            "charges": [], "totals": totals, "checks": [], "review": [], "summary": summary}


def upload(s, result, files_dir):
    """('job', job id) when filed with a job; ('person', reason) when it waits for a person."""
    doc, _ = save_parse(s, result, f"fake pdf {next(_n)}".encode(), files_dir)
    s.flush()
    return "job", doc.job_id

"""Store a parse_pdf() result: find or create the job, keep the PDF, add a new estimate version."""
import hashlib
from pathlib import Path

from sqlalchemy import func, select

from estimate_parser.core import PARSER_VERSION, version_key
from .models import (AuditLog, Customer, EstimateDocument, EstimateLine, EstimateTotal, File, InsuranceCompany, Job,
                     Shop, Vehicle, now)

# job fields filled from the estimate; a value already on the job (e.g. typed in by hand) is never overwritten
_JOB_FIELDS = {"ro_number": ("summary", "ro_number"), "claim_no": ("summary", "claim"),
               "adjuster": ("header", "adjuster"), "estimator": ("header", "estimator"),
               "loss_date": ("header", "loss_date"), "deductible": ("header", "deductible")}


def audit(s, table, row_id, action, field="", old=None, new=None, user_id=None, job_id=None):
    s.add(AuditLog(table_name=table, row_id=row_id, action=action, field=field, user_id=user_id, job_id=job_id,
                   old_value=None if old is None else str(old), new_value=None if new is None else str(new)))


def set_field(s, obj, field, value, user_id=None, job_id=None):
    """Change one field and log it. Returns True if it changed."""
    old = getattr(obj, field)
    if old == value:
        return False
    setattr(obj, field, value)
    obj.updated_by = user_id
    audit(s, obj.__tablename__, obj.id, "update", field, old, value, user_id, job_id)
    return True


def _get_or_create(s, model, where, **values):
    row = s.scalar(select(model).where(*where).limit(1))
    if row is None:
        row = model(**values)
        s.add(row)
        s.flush()
    return row


def find_job(s, shop_id, ro, claim):
    """The job with the same RO#, then the same claim #. Every job is archived, so all jobs are searched. VIN is not
    used: the same car can come back later as a new job with a new RO# and claim."""
    jobs = select(Job).where(Job.shop_id == shop_id)
    for cond in ((Job.ro_number == ro) if ro else None, (Job.claim_no == claim) if claim else None):
        if cond is not None:
            job = s.scalar(jobs.where(cond).order_by(Job.id.desc()).limit(1))
            if job:
                return job
    return None


def _store_file(s, shop_id, pdf_bytes, filename, files_dir):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    path = Path(files_dir) / sha[:2] / f"{sha}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(pdf_bytes)
    f = File(shop_id=shop_id, kind="estimate_pdf", original_name=filename, path=str(path),
             content_type="application/pdf", size=len(pdf_bytes), sha256=sha)
    s.add(f)
    s.flush()
    return f


def save_parse(s, result, pdf_bytes, files_dir, user_id=None):
    """Save one parsed estimate. Returns (document, is_new); uploading the same PDF twice returns the first copy."""
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    dup = s.scalar(select(EstimateDocument).join(File, EstimateDocument.file_id == File.id).where(File.sha256 == sha).limit(1))
    if dup:
        return dup, False

    shop_id = s.scalar(select(Shop.id).order_by(Shop.id).limit(1))
    m, h, v = result["summary"], result["header"], result["header"]["vehicle"]
    job = find_job(s, shop_id, m["ro_number"], m["claim"])
    if job is None:
        name = m["customer"].strip()
        customer = _get_or_create(s, Customer, [Customer.shop_id == shop_id, func.lower(Customer.name) == name.lower()],
                                  shop_id=shop_id, name=name, phone=h.get("phone", ""), created_by=user_id) if name else None
        vehicle = Vehicle(shop_id=shop_id, vin=v.get("vin", ""), year=v.get("year", ""), make=v.get("make", ""),
                          model=v.get("model", ""), description=v.get("description", ""), mileage=v.get("mileage", ""),
                          created_by=user_id)
        s.add(vehicle)
        ins = m["insurance"].strip()
        insurance = _get_or_create(s, InsuranceCompany, [InsuranceCompany.shop_id == shop_id,
                                                          func.lower(InsuranceCompany.name) == ins.lower()],
                                   shop_id=shop_id, name=ins, created_by=user_id) if ins else None
        # filed straight into the archive: the app stores completed jobs and their estimates
        job = Job(shop_id=shop_id, customer=customer, vehicle=vehicle, insurance=insurance, created_by=user_id,
                  archived_at=now(), **{f: result[src].get(key) or "" for f, (src, key) in _JOB_FIELDS.items()})
        s.add(job)
        s.flush()
        audit(s, "jobs", job.id, "create", user_id=user_id, job_id=job.id)
    else:
        for f, (src, key) in _JOB_FIELDS.items():
            if not getattr(job, f) and result[src].get(key):
                set_field(s, job, f, result[src][key], user_id, job.id)

    d = result["document"]
    doc = EstimateDocument(
        job_id=job.id, file=_store_file(s, shop_id, pdf_bytes, result["filename"], files_dir), format=result["format"],
        title_raw=d["title_raw"], display=d["display"], stage=d["stage"], supplement_no=d["supplement_no"],
        printed_at=d["printed_at"], supplement_amount=d["supplement_amount"], needs_review=bool(result["review"]),
        review_reasons=result["review"], parser_version=PARSER_VERSION, parse=result, created_by=user_id,
        lines=_lines(result), totals=_totals(result))
    s.add(doc)
    s.flush()
    audit(s, "estimate_documents", doc.id, "create", new=doc.display, user_id=user_id, job_id=job.id)
    _set_current(s, job, user_id)
    return doc, True


def reparse_document(s, doc, result, user_id=None):
    """Replace a saved document's parse with a newer one of the same PDF. Job fields (e.g. a typed RO#) are kept."""
    job_id, d = doc.job_id, result["document"]
    old_version = doc.parser_version
    for field, value in (("display", d["display"]), ("stage", d["stage"]), ("supplement_no", d["supplement_no"]),
                         ("printed_at", d["printed_at"]), ("supplement_amount", d["supplement_amount"]),
                         ("needs_review", bool(result["review"])), ("review_reasons", result["review"]),
                         ("parser_version", PARSER_VERSION)):
        set_field(s, doc, field, value, user_id, job_id)
    doc.parse = result
    doc.lines = _lines(result)
    doc.totals = _totals(result)
    audit(s, "estimate_documents", doc.id, "reparse", "parse", old_version, PARSER_VERSION, user_id, job_id)
    s.flush()
    _set_current(s, doc.job, user_id)
    return doc


def _lines(result):
    return [EstimateLine(line_no=str(c.get("line") or ""), section=c.get("section") or "", operation=c.get("op") or "",
                         category=c["category"], description=c.get("desc") or "", part_no=c.get("part_no") or "",
                         part_type=c.get("part_type") or "", qty=c.get("qty"), hours=c.get("hours"), rate=c.get("rate"),
                         amount=c.get("amount"), taxed=c.get("taxed"), flags=str(c.get("flags") or ""))
            for c in result["charges"]]


def _totals(result):
    return [EstimateTotal(label=t["label"], section=t.get("section") or "", hours=t.get("hours"), rate=t.get("rate"),
                          amount=t.get("amount"), extra=t.get("extra"), extra_kind=t.get("extra_kind") or "")
            for t in result["totals"]]


def _set_current(s, job, user_id):
    """Point the job at its newest estimate version."""
    s.refresh(job, ["documents"])
    newest = max(job.documents, key=lambda x: version_key(
        {"supplement_no": x.supplement_no, "stage": x.stage, "printed_at": x.printed_at}))
    set_field(s, job, "current_document_id", newest.id, user_id, job.id)

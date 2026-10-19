"""Store a parse_pdf() result: find or create the job (or hold the upload for a person), keep the PDF, add a new
estimate version."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from estimate_parser.core import PARSER_VERSION, job_numbers, jsonable, version_key
from .matching import match_job
from .models import (AuditLog, Customer, EstimateDocument, EstimateLine, EstimateTotal, File, InsuranceCompany, Job,
                     PendingUpload, Shop, Vehicle, now)
from .values import printed_date, printed_money, printed_time

# job fields filled from the estimate (where in the parse, and how printed text becomes the column's value); a value
# already on the job (e.g. typed in by hand) is never overwritten
_JOB_FIELDS = {"ro_number": ("summary", "ro_number", str), "claim_no": ("summary", "claim", str),
               "adjuster": ("header", "adjuster", str), "estimator": ("header", "estimator", str),
               "loss_date": ("header", "loss_date", printed_date), "deductible": ("header", "deductible", printed_money)}


def _job_value(result, field):
    src, key, convert = _JOB_FIELDS[field]
    return convert(result[src].get(key) or "")


def audit(s, table, row_id, action, field="", old=None, new=None, user_id=None, job_id=None):
    s.add(AuditLog(table_name=table, row_id=row_id, action=action, field=field, user_id=user_id, job_id=job_id,
                   old_value=None if old is None else str(old), new_value=None if new is None else str(new)))


def set_field(s, obj, field, value, user_id=None, job_id=None, action="update"):
    """Change one field and log it. Returns True if it changed. action="manual" marks a value a person typed in."""
    old = getattr(obj, field)
    if old == value:
        return False
    setattr(obj, field, value)
    obj.updated_by = user_id
    audit(s, obj.__tablename__, obj.id, action, field, old, value, user_id, job_id)
    return True


def typed_by_hand(s, job, field):
    """True if a person has ever set this job field (logged with action 'manual'); estimates then never change it."""
    return s.scalar(select(AuditLog.id).where(AuditLog.table_name == "jobs", AuditLog.row_id == job.id,
                                              AuditLog.field == field, AuditLog.action == "manual").limit(1)) is not None


def _get_or_create(s, model, where, **values):
    row = s.scalar(select(model).where(*where).limit(1))
    if row is None:
        row = model(**values)
        s.add(row)
        s.flush()
    return row


def _customer(s, shop_id, name, phone="", user_id=None):
    name = name.strip()
    return _get_or_create(s, Customer, [Customer.shop_id == shop_id, func.lower(Customer.name) == name.lower()],
                          shop_id=shop_id, name=name, phone=phone, created_by=user_id) if name else None


def _store_file(s, shop_id, pdf_bytes, filename, files_dir):
    """The PDF on disk (one copy per content) and its files row."""
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


@dataclass
class Saved:
    """What happened to an upload: filed as `document`, or waiting for a person as `pending`. is_new False: this PDF
    was uploaded before and nothing new was saved."""
    document: EstimateDocument | None = None
    pending: PendingUpload | None = None
    is_new: bool = True


def save_parse(s, result, pdf_bytes, files_dir, user_id=None):
    """Save one parsed estimate: filed with its job when the match is sure, otherwise held in pending_uploads for a
    person (db/matching.py). Uploading the same PDF again returns what the first upload became."""
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    dup = s.scalar(select(EstimateDocument).join(File, EstimateDocument.file_id == File.id).where(File.sha256 == sha).limit(1))
    if dup:
        return Saved(document=dup, is_new=False)
    waiting = s.scalar(select(PendingUpload).join(File, PendingUpload.file_id == File.id)
                       .where(File.sha256 == sha, PendingUpload.resolved_at.is_(None)).limit(1))
    if waiting:
        return Saved(pending=waiting, is_new=False)

    shop_id = s.scalar(select(Shop.id).order_by(Shop.id).limit(1))
    m = result["summary"]
    match = match_job(s, shop_id, m["ro_number"], m["claim"], m["vin"], result["document"]["printed_at"])
    file = _store_file(s, shop_id, pdf_bytes, result["filename"], files_dir)
    if match.kind == "person":
        return Saved(pending=_hold(s, shop_id, result, file, match, user_id))
    return Saved(document=_file_with_job(s, match.job, result, file, user_id))


def _hold(s, shop_id, result, file, match, user_id):
    p = PendingUpload(shop_id=shop_id, file=file, parse=jsonable(result), parser_version=PARSER_VERSION,
                      reason=match.reason, detail=match.detail, candidate_job_ids=[j.id for j in match.candidates],
                      created_by=user_id)
    s.add(p)
    s.flush()
    audit(s, "pending_uploads", p.id, "create", "reason", None, match.reason, user_id)
    return p


def resolve_pending(s, pending, job_id=None, user_id=None):
    """A person's choice for a waiting upload: add it to job `job_id`, or (None) make a new job. Saved exactly as an
    automatic match would be. A closed job must be reopened first."""
    if pending.resolved_at is not None:
        raise ValueError("This upload was already filed.")
    job = None
    if job_id is not None:
        job = s.get(Job, job_id)
        if job is None:
            raise ValueError(f"No job {job_id}.")
        if job.closed_at is not None:
            raise ValueError("That job is closed - reopen it first.")
    doc = _file_with_job(s, job, pending.parse, pending.file, user_id)
    pending.resolved_at, pending.resolved_by = now(), user_id
    pending.resolution, pending.resolution_job_id, pending.document_id = ("job" if job else "new_job"), doc.job_id, doc.id
    audit(s, "pending_uploads", pending.id, "resolve", "resolution", None,
          f"{pending.resolution} {doc.job_id}", user_id, doc.job_id)
    return doc


def _file_with_job(s, job, result, file, user_id):
    """Add the estimate as a new version of `job` (None: a new job made from it)."""
    shop_id = file.shop_id
    m, h, v = result["summary"], result["header"], result["header"]["vehicle"]
    if job is None:
        customer = _customer(s, shop_id, m["customer"], h.get("phone", ""), user_id)
        vehicle = Vehicle(shop_id=shop_id, vin=v.get("vin", ""), year=v.get("year", ""), make=v.get("make", ""),
                          model=v.get("model", ""), description=v.get("description", ""), mileage=v.get("mileage", ""),
                          created_by=user_id)
        s.add(vehicle)
        ins = m["insurance"].strip()
        insurance = _get_or_create(s, InsuranceCompany, [InsuranceCompany.shop_id == shop_id,
                                                          func.lower(InsuranceCompany.name) == ins.lower()],
                                   shop_id=shop_id, name=ins, created_by=user_id) if ins else None
        job = Job(shop_id=shop_id, customer=customer, vehicle=vehicle, insurance=insurance, created_by=user_id,
                  **{f: _job_value(result, f) for f in _JOB_FIELDS})
        s.add(job)
        s.flush()
        audit(s, "jobs", job.id, "create", user_id=user_id, job_id=job.id)
    else:
        for f in _JOB_FIELDS:
            value = _job_value(result, f)
            if getattr(job, f) in ("", None) and value not in ("", None):
                set_field(s, job, f, value, user_id, job.id)

    d = result["document"]
    file.job_id = job.id
    doc = EstimateDocument(
        job_id=job.id, file=file, format=result["format"],
        title_raw=d["title_raw"], display=d["display"], stage=d["stage"], supplement_no=d["supplement_no"],
        printed_at=printed_time(d["printed_at"]), supplement_amount=d["supplement_amount"],
        needs_review=bool(result["review"]), review_reasons=result["review"], parser_version=PARSER_VERSION,
        parse=jsonable(result), created_by=user_id, lines=_lines(result), totals=_totals(result), **job_numbers(result))
    s.add(doc)
    s.flush()
    audit(s, "estimate_documents", doc.id, "create", new=doc.display, user_id=user_id, job_id=job.id)
    _set_current(s, job, user_id)
    return doc


def reparse_document(s, doc, result, user_id=None):
    """Replace a saved document's parse with a newer one of the same PDF. Job fields (e.g. a typed RO#) are kept."""
    job_id, d = doc.job_id, result["document"]
    old_version = doc.parser_version
    for field, value in (("display", d["display"]), ("stage", d["stage"]), ("supplement_no", d["supplement_no"]),
                         ("printed_at", printed_time(d["printed_at"])), ("supplement_amount", d["supplement_amount"]),
                         ("needs_review", bool(result["review"])), ("review_reasons", result["review"]),
                         ("parser_version", PARSER_VERSION), *job_numbers(result).items()):
        set_field(s, doc, field, value, user_id, job_id)
    doc.parse = jsonable(result)
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
    """Point the job at its newest estimate version. The job's RO# follows the newest version that prints one (the
    final bill can print a different RO# than the first estimate) unless a person typed the RO# in."""
    s.refresh(job, ["documents"])
    by_age = sorted(job.documents, key=lambda x: version_key(
        {"supplement_no": x.supplement_no, "stage": x.stage, "printed_at": x.printed_at}), reverse=True)
    set_field(s, job, "current_document_id", by_age[0].id, user_id, job.id)
    ro = next((d.parse["summary"]["ro_number"] for d in by_age if d.parse["summary"]["ro_number"]), "")
    if ro and ro != job.ro_number and not typed_by_hand(s, job, "ro_number"):
        set_field(s, job, "ro_number", ro, user_id, job.id)
    # the customer (vehicle owner) follows the newest version too, e.g. after a re-read corrects who the owner is
    name = by_age[0].parse["summary"]["customer"].strip()
    if name and (not job.customer or job.customer.name.lower() != name.lower()):
        set_field(s, job, "customer_id", _customer(s, job.shop_id, name, by_age[0].parse["header"].get("phone", ""), user_id).id,
                  user_id, job.id)
        s.refresh(job, ["customer"])

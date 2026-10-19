"""Store a parse_pdf() result: find or create the job (or hold the upload for a person), keep the PDF, add a new
estimate version."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from estimate_parser.core import PARSER_VERSION, job_numbers, jsonable, version_key
from .matching import DUPLICATE_RO, Match, match_job
from .models import (AuditLog, Customer, EstimateDocument, EstimateLine, EstimateParse, EstimateTotal, File,
                     InsuranceCompany, Job, PendingUpload, Shop, Vehicle, now)
from .values import printed_date, printed_money, printed_time

# job fields that follow the job's current estimate version (where in the parse, and how printed text becomes the
# column's value); customer, insurance company and vehicle follow it too (_follow_current)
_JOB_FIELDS = {"ro_number": ("summary", "ro_number", str.strip), "claim_no": ("summary", "claim", str.strip),
               "adjuster": ("header", "adjuster", str.strip), "estimator": ("header", "estimator", str.strip),
               "loss_date": ("header", "loss_date", printed_date), "deductible": ("header", "deductible", printed_money)}


def _job_value(result, field):
    src, key, convert = _JOB_FIELDS[field]
    return convert(result[src].get(key) or "")


def _mileage(result):
    return (result["header"]["vehicle"].get("mileage") or "").strip()


def audit(s, table, row_id, action, field="", old=None, new=None, user_id=None, job_id=None, note=""):
    s.add(AuditLog(table_name=table, row_id=row_id, action=action, field=field, user_id=user_id, job_id=job_id,
                   old_value=None if old is None else str(old), new_value=None if new is None else str(new), note=note))


def set_field(s, obj, field, value, user_id=None, job_id=None, action="update", note=""):
    """Change one field and log it. Returns True if it changed. action="manual" marks a value a person typed in."""
    old = getattr(obj, field)
    if old == value:
        return False
    setattr(obj, field, value)
    obj.updated_by = user_id
    audit(s, obj.__tablename__, obj.id, action, field, old, value, user_id, job_id, note)
    return True


def typed_by_hand(s, job, field):
    """True if a person has ever set this job field (logged with action 'manual'); estimates then never change it."""
    return s.scalar(select(AuditLog.id).where(AuditLog.table_name == "jobs", AuditLog.row_id == job.id,
                                              AuditLog.field == field, AuditLog.action == "manual").limit(1)) is not None


def same_name(a, b):
    """Names compared with case and spacing ignored."""
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()


def digits(phone):
    return "".join(ch for ch in phone or "" if ch.isdigit())


def _customer(s, shop_id, name, phone="", user_id=None):
    """The customer with this name AND phone (digits only); either missing a phone -> a new customer. Never matched on
    name alone: two different people can share a name. Existing customer rows are never merged or changed."""
    name = name.strip()
    if not name:
        return None
    if digits(phone):
        for c in s.scalars(select(Customer).where(Customer.shop_id == shop_id, Customer.phone != "").order_by(Customer.id)):
            if same_name(c.name, name) and digits(c.phone) == digits(phone):
                return c
    c = Customer(shop_id=shop_id, name=name, phone=phone, created_by=user_id)
    s.add(c)
    s.flush()
    return c


def _insurance(s, shop_id, name, user_id=None):
    """Insurance company by name, case and spacing ignored; a new one is stored as printed."""
    name = name.strip()
    if not name:
        return None
    for c in s.scalars(select(InsuranceCompany).where(InsuranceCompany.shop_id == shop_id).order_by(InsuranceCompany.id)):
        if same_name(c.name, name):
            return c
    c = InsuranceCompany(shop_id=shop_id, name=name, created_by=user_id)
    s.add(c)
    s.flush()
    return c


def _vehicle(s, shop_id, v, user_id=None):
    """The vehicle with this VIN (the oldest record, if an older database holds several); no VIN -> a new record."""
    vin = (v.get("vin") or "").strip()
    found = s.scalar(select(Vehicle).where(Vehicle.shop_id == shop_id, Vehicle.vin == vin).order_by(Vehicle.id).limit(1)) if vin else None
    if found:
        return found
    found = Vehicle(shop_id=shop_id, vin=vin, year=v.get("year", ""), make=v.get("make", ""), model=v.get("model", ""),
                    description=v.get("description", ""), created_by=user_id)
    s.add(found)
    s.flush()
    return found


def _store_file(s, shop_id, pdf_bytes, filename, files_dir):
    """The PDF on disk (one copy per content) and its files row."""
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    known = s.scalar(select(File).where(File.sha256 == sha))
    if known:
        return known
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
    if match.kind != "person" and (holder := ro_conflict(s, match.job, result)):
        match = Match("person", reason=DUPLICATE_RO, candidates=[j for j in (match.job, holder) if j],
                      detail=_duplicate_detail(result, holder))
    if match.kind == "person":
        return Saved(pending=_hold(s, shop_id, result, file, match, user_id))
    return Saved(document=_file_with_job(s, match.job, result, file, user_id))


class DuplicateRO(ValueError):
    """Filing would give two jobs the same RO #."""


def _duplicate_detail(result, holder):
    return (f"This estimate prints RO # {result['summary']['ro_number'].strip()}, which is already on job {holder.id}"
            f" ({holder.customer.name if holder.customer else 'no customer'}).")


def ro_conflict(s, job, result, replacing=None):
    """The other job that already has the RO # that filing `result` with `job` (None: a new job) would give it -
    or None. `replacing`: a document of the job whose parse `result` replaces (a re-read)."""
    if job is not None and typed_by_hand(s, job, "ro_number"):
        return None
    versions = [(version_key({"supplement_no": d.supplement_no, "stage": d.stage, "printed_at": d.printed_at}), d.parse)
                for d in (job.documents if job else []) if d is not replacing]
    d = result["document"]
    versions.append((version_key({"supplement_no": d["supplement_no"], "stage": d["stage"],
                                  "printed_at": printed_time(d["printed_at"])}), result))
    ro = max(versions, key=lambda v: v[0])[1]["summary"]["ro_number"].strip()
    if not ro or (job is not None and job.ro_number == ro):
        return None
    return s.scalar(select(Job).where(Job.ro_number == ro, Job.id != (job.id if job else -1)).limit(1))


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
    if holder := ro_conflict(s, job, pending.parse):
        # kept waiting, now as a duplicate RO #, with the job holding that RO # among the choices
        set_field(s, pending, "reason", DUPLICATE_RO, user_id)
        set_field(s, pending, "detail", _duplicate_detail(pending.parse, holder), user_id)
        if holder.id not in pending.candidate_job_ids:
            set_field(s, pending, "candidate_job_ids", [*pending.candidate_job_ids, holder.id], user_id)
        raise DuplicateRO(pending.detail)
    doc = _file_with_job(s, job, pending.parse, pending.file, user_id)
    pending.resolved_at, pending.resolved_by = now(), user_id
    pending.resolution, pending.resolution_job_id, pending.document_id = ("job" if job else "new_job"), doc.job_id, doc.id
    audit(s, "pending_uploads", pending.id, "resolve", "resolution", None,
          f"{pending.resolution} {doc.job_id}", user_id, doc.job_id)
    return doc


def _file_with_job(s, job, result, file, user_id):
    """Add the estimate as a new version of `job` (None: a new job made from it)."""
    if job is None:  # its fields are filled from this estimate by _follow_current, like any job's
        job = Job(shop_id=file.shop_id, created_by=user_id)
        s.add(job)
        s.flush()
        audit(s, "jobs", job.id, "create", user_id=user_id, job_id=job.id)

    d = result["document"]
    file.job_id = job.id
    doc = EstimateDocument(
        job_id=job.id, file=file, format=result["format"],
        title_raw=d["title_raw"], display=d["display"], stage=d["stage"], supplement_no=d["supplement_no"],
        printed_at=printed_time(d["printed_at"]), supplement_amount=d["supplement_amount"],
        needs_review=bool(result["review"]), review_reasons=result["review"], parser_version=PARSER_VERSION,
        created_by=user_id, lines=_lines(result), totals=_totals(result), **job_numbers(result))
    s.add(doc)
    s.flush()
    doc.current_parse = _add_parse(s, doc, result, user_id)
    s.flush()
    audit(s, "estimate_documents", doc.id, "create", new=doc.display, user_id=user_id, job_id=job.id)
    _follow_current(s, job, user_id)
    return doc


def _add_parse(s, doc, result, user_id):
    p = EstimateParse(document_id=doc.id, parser_version=PARSER_VERSION, parse=jsonable(result),
                      review_reasons=result["review"], created_by=user_id)
    s.add(p)
    s.flush()
    return p


def reparse_document(s, doc, result, user_id=None, make_current=True):
    """A newer reading of a saved document's PDF: always added to its parse history (estimate_parses). make_current:
    the document's fields, numbers, lines and totals follow it, and so does the job (typed-in fields are kept);
    False: kept in history only (e.g. a closed job, whose numbers don't change). Returns the new EstimateParse.
    Raises DuplicateRO (nothing changed) if it would give the job an RO # another job has."""
    job_id, d = doc.job_id, result["document"]
    if make_current and (holder := ro_conflict(s, doc.job, result, replacing=doc)):
        raise DuplicateRO(_duplicate_detail(result, holder))
    p = _add_parse(s, doc, result, user_id)
    audit(s, "estimate_parses", p.id, "create", "parser_version", doc.parser_version, PARSER_VERSION, user_id, job_id)
    if not make_current:
        return p
    for field, value in (("display", d["display"]), ("stage", d["stage"]), ("supplement_no", d["supplement_no"]),
                         ("printed_at", printed_time(d["printed_at"])), ("supplement_amount", d["supplement_amount"]),
                         ("needs_review", bool(result["review"])), ("review_reasons", result["review"]),
                         ("parser_version", PARSER_VERSION), ("current_parse_id", p.id), *job_numbers(result).items()):
        set_field(s, doc, field, value, user_id, job_id)
    s.flush()
    s.refresh(doc, ["current_parse"])
    doc.lines = _lines(result)
    doc.totals = _totals(result)
    s.flush()
    _follow_current(s, doc.job, user_id)
    return p


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


def _follow_current(s, job, user_id):
    """Point the job at its newest estimate version, and make the job's fields follow that version: RO #, claim #,
    adjuster, estimator, loss date, deductible, mileage in, customer, insurance company and vehicle - except a field a
    person typed in by hand. A value the current version doesn't print keeps what the job has. Every change is logged."""
    s.refresh(job, ["documents"])
    cur = max(job.documents, key=lambda x: version_key(
        {"supplement_no": x.supplement_no, "stage": x.stage, "printed_at": x.printed_at}))
    set_field(s, job, "current_document_id", cur.id, user_id, job.id)
    r, shop_id = cur.parse, job.shop_id

    def follow(field, value):
        if value in ("", None) or typed_by_hand(s, job, field):
            return
        if field == "ro_number" and value != job.ro_number and s.scalar(
                select(Job.id).where(Job.ro_number == value, Job.id != job.id).limit(1)):
            raise DuplicateRO(f"RO # {value} is already on another job.")  # callers check first (ro_conflict)
        set_field(s, job, field, value, user_id, job.id)

    for f in _JOB_FIELDS:
        follow(f, _job_value(r, f))
    follow("mileage_in", _mileage(r))
    name, phone = r["summary"]["customer"].strip(), (r["header"].get("phone") or "").strip()
    c = job.customer
    if name and not (c and same_name(c.name, name) and (not digits(phone) or digits(c.phone) == digits(phone))):
        follow("customer_id", _customer(s, shop_id, name, phone, user_id).id)
    ins = r["summary"]["insurance"].strip()
    if ins and not (job.insurance and same_name(job.insurance.name, ins)):
        follow("insurance_id", _insurance(s, shop_id, ins, user_id).id)
    v = r["header"]["vehicle"]
    if (v.get("vin") or "").strip() or job.vehicle_id is None:
        follow("vehicle_id", _vehicle(s, shop_id, v, user_id).id)
    s.flush()
    s.refresh(job, ["customer", "insurance", "vehicle"])

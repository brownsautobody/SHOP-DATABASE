"""Shop Database web app: python app.py, then open http://127.0.0.1:5000"""
import io
from datetime import date, timedelta

from flask import Flask, abort, redirect, request, send_file
from sqlalchemy import select

from db.models import EstimateDocument, File, Job, now
from db.save import save_parse, set_field
from db.session import DATA_DIR, init_db, make_engine
from estimate_parser.core import NUMBER_FIELDS, doc_file_name, doc_type_name, job_numbers, parse_pdf, version_key
from estimate_parser.render import job_page, jobs_list, upload_form

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
Session = init_db(make_engine())
FILES_DIR = DATA_DIR / "files"


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return upload_form()
    f = request.files.get("pdf")
    if not f or not f.filename:
        return upload_form("Choose a PDF file first."), 400
    data = f.read()
    try:
        result = parse_pdf(io.BytesIO(data), f.filename)
    except Exception as e:  # show the reason instead of a stack trace
        return upload_form(f"Could not parse {f.filename}: {e}"), 422
    with Session() as s:
        doc, is_new = save_parse(s, result, data, FILES_DIR)
        s.commit()
    return redirect(f"/jobs/{doc.job_id}?v={doc.id}&saved={'new' if is_new else 'dup'}")


def _vehicle(job):
    return job.current_document.parse["summary"]["vehicle"] if job.current_document else ""


def doc_names(job):
    """{document id: file name} for a job's documents, by the shop's naming convention (LAST-RO-TYPE.pdf). Documents
    with the same title are numbered oldest first by print date (...-ESTIMATE.pdf, then ...-ESTIMATE-2.pdf)."""
    customer = job.customer.name if job.customer else ""
    seen, names = {}, {}
    for d in sorted(job.documents, key=lambda d: (d.printed_at or "", d.id)):
        t = doc_type_name(d.stage, d.supplement_no)
        seen[t] = seen.get(t, 0) + 1
        names[d.id] = doc_file_name(customer, job.ro_number, t, seen[t])
    return names


def _periods(today):
    """Quick date ranges for the job list: (label, start, end) as ISO dates."""
    month = today.replace(day=1)
    last_end = month - timedelta(days=1)
    return [("This month", month.isoformat(), today.isoformat()),
            ("Last month", last_end.replace(day=1).isoformat(), last_end.isoformat()),
            ("This year", today.replace(month=1, day=1).isoformat(), today.isoformat())]


@app.route("/jobs")
def jobs():
    f = {k: request.args.get(k, "").strip() for k in ("q", "start", "end", "status")}
    if f["status"] not in ("open", "closed", "all"):
        f["status"] = "open"
    q = f["q"].lower()
    jobs = select(Job)
    if f["status"] != "all":
        jobs = jobs.where(Job.closed_at.is_(None) if f["status"] == "open" else Job.closed_at.is_not(None))
    rows = []
    with Session() as s:
        for j in s.scalars(jobs):
            d = j.current_document
            printed = (d.printed_at if d else "")[:10]  # the date the job's current estimate was printed
            if (f["start"] and printed < f["start"]) or (f["end"] and printed > f["end"]):
                continue
            row = {"id": j.id, "ro": j.ro_number, "customer": j.customer.name if j.customer else "", "vehicle": _vehicle(j),
                   "insurance": j.insurance.name if j.insurance else "", "claim": j.claim_no,
                   "vin": j.vehicle.vin if j.vehicle else "", "date": printed,
                   "needs_review": bool(d and d.needs_review), "closed": j.closed_at,
                   "numbers": job_numbers(d.parse) if d else dict.fromkeys(NUMBER_FIELDS)}
            if q and not any(q in str(row[k]).lower() for k in ("ro", "customer", "vin", "claim", "insurance")):
                continue
            rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    totals = {k: round(sum(r["numbers"][k] or 0 for r in rows), 2) for k in NUMBER_FIELDS}
    return jobs_list(rows, totals, f, _periods(date.today()))


@app.route("/closed")
@app.route("/archive")  # old link
def closed():
    return redirect("/jobs?status=closed")


@app.route("/jobs/<int:job_id>")
def job(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        info = {"id": j.id, "ro": j.ro_number, "customer": j.customer.name if j.customer else "", "vehicle": _vehicle(j),
                "vin": j.vehicle.vin if j.vehicle else "", "insurance": j.insurance.name if j.insurance else "",
                "claim": j.claim_no, "adjuster": j.adjuster, "estimator": j.estimator, "deductible": j.deductible,
                "loss_date": j.loss_date, "current_id": j.current_document_id, "closed": j.closed_at}
        docs = sorted(j.documents, key=lambda d: version_key(
            {"supplement_no": d.supplement_no, "stage": d.stage, "printed_at": d.printed_at}))
        names = doc_names(j)
        versions = [{"id": d.id, "display": d.display, "name": names[d.id], "printed": d.printed_at,
                     "amount": d.supplement_amount, "needs_review": d.needs_review, "uploaded": d.created_at,
                     "file_id": d.file_id, "uploaded_as": d.file.original_name if d.file else ""} for d in docs]
        want = request.args.get("v", type=int) or j.current_document_id
        shown = next((d for d in docs if d.id == want), docs[-1] if docs else None)
        note = {"new": f"Estimate saved to this job ({len(docs)} version{'s' if len(docs) != 1 else ''}).",
                "dup": "This PDF was already uploaded - nothing new was saved."}.get(request.args.get("saved"), "")
        return job_page({"job": info, "versions": versions, "note": note,
                         "shown": next((v for v in versions if shown and v["id"] == shown.id), None),
                         "summary": shown.parse["summary"] if shown else None})


@app.route("/jobs/<int:job_id>/ro", methods=["POST"])
def set_ro(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        set_field(s, j, "ro_number", request.form.get("ro", "").strip(), job_id=j.id, action="manual")
        s.commit()
    return redirect(f"/jobs/{job_id}")


@app.route("/jobs/<int:job_id>/close", methods=["POST"])
def close_job(job_id):
    """A person closes a job once every invoice is closed out, everything is paid and the shop's audits are done."""
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        if j.closed_at is None:
            set_field(s, j, "closed_at", now(), job_id=j.id, action="close")
            s.commit()
    return redirect(f"/jobs/{job_id}")


@app.route("/jobs/<int:job_id>/reopen", methods=["POST"])
def reopen_job(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        set_field(s, j, "closed_at", None, job_id=j.id, action="reopen")
        s.commit()
    return redirect(f"/jobs/{job_id}")


@app.route("/documents/<int:doc_id>")
def document(doc_id):
    """Old estimate links: an estimate is shown on its job's page now."""
    with Session() as s:
        d = s.get(EstimateDocument, doc_id) or abort(404)
        return redirect(f"/jobs/{d.job_id}?v={d.id}")


@app.route("/files/<int:file_id>")
def file(file_id):
    """A stored PDF, named by the shop's convention (the name it was uploaded with is kept in the database)."""
    with Session() as s:
        f = s.get(File, file_id) or abort(404)
        d = s.scalar(select(EstimateDocument).where(EstimateDocument.file_id == f.id).limit(1))
        name = doc_names(d.job)[d.id] if d else f.original_name
        return send_file(f.path, mimetype=f.content_type, download_name=name)


if __name__ == "__main__":
    app.run(debug=True)

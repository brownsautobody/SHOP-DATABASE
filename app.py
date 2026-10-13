"""Shop Database web app: python app.py, then open http://127.0.0.1:5000"""
import io

from flask import Flask, abort, redirect, request, send_file
from sqlalchemy import select

from db import production as prod
from db.models import AuditLog, EstimateDocument, File, Job, JobAssignment, ProductionStage, User
from db.save import save_parse, set_field
from db.session import DATA_DIR, init_db, make_engine
from estimate_parser.core import parse_pdf
from estimate_parser.render import archive_btn, archive_list, job_page, jobs_list, results, settings_page, upload_form

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
    return redirect(f"/documents/{doc.id}" + ("" if is_new else "?dup=1"))


def _vehicle(job):
    return job.current_document.parse["summary"]["vehicle"] if job.current_document else ""


def _options(s):
    """Dropdown choices: visible stages, active techs and estimators."""
    return {"stages": [(st.id, st.name) for st in prod.stages(s)],
            "techs": [(u.id, u.name) for u in prod.employees(s, "tech")],
            "estimators": [(u.id, u.name) for u in prod.employees(s, "estimator")]}


def _keep_current(options, key, item):
    """A job can still point at a hidden stage or an inactive employee - keep it in its dropdown."""
    if item is not None and item.id not in {k for k, _ in options[key]}:
        options[key].append((item.id, f"{item.name} (hidden)" if key == "stages" else f"{item.name} (inactive)"))


def _prod_row(j, people, since):
    return {"stage_id": j.current_stage_id, "tech_id": people.get("tech") and people["tech"].id,
            "est_id": people.get("estimator") and people["estimator"].id, "since": since}


@app.route("/jobs")
def jobs():
    tab = request.args.get("stage", "all")
    with Session() as s:
        rows = s.scalars(select(Job).where(Job.archived_at.is_(None)).order_by(Job.updated_at.desc())).all()
        ids = [j.id for j in rows]
        people, since = prod.current_assignments(s, ids), prod.stage_since(s, ids)
        opts = _options(s)
        for j in rows:
            _keep_current(opts, "stages", j.current_stage_id and s.get(ProductionStage, j.current_stage_id))
            for role, key in (("tech", "techs"), ("estimator", "estimators")):
                _keep_current(opts, key, people[j.id].get(role))
        counts = {}
        for j in rows:
            counts[j.current_stage_id] = counts.get(j.current_stage_id, 0) + 1
        tabs = [("All", "/jobs", len(rows), tab == "all"), ("Not started", "/jobs?stage=none", counts.get(None, 0), tab == "none")]
        tabs += [(name, f"/jobs?stage={sid}", counts.get(sid, 0), tab == str(sid)) for sid, name in _options(s)["stages"]]
        shown = [j for j in rows if tab == "all" or (tab == "none" and j.current_stage_id is None)
                 or str(j.current_stage_id) == tab]
        back = "/jobs" + (f"?stage={tab}" if tab != "all" else "")
        return jobs_list([{
            "id": j.id, "ro": j.ro_number, "customer": j.customer.name if j.customer else "", "vehicle": _vehicle(j),
            "insurance": j.insurance.name if j.insurance else "",
            "needs_review": bool(j.current_document and j.current_document.needs_review),
            **_prod_row(j, people[j.id], since.get(j.id))} for j in shown], opts, tabs, back)


@app.route("/jobs/<int:job_id>/production", methods=["POST"])
def set_production(job_id):
    """Save whichever of stage / tech / estimator was changed."""
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        value = lambda k: int(request.form[k]) if request.form[k] else None
        if "stage" in request.form:
            prod.move_stage(s, j, value("stage"))
        for role in prod.ROLES:
            if role in request.form:
                prod.assign(s, j, role, value(role))
        s.commit()
    back = request.form.get("next", "")
    return redirect(back if back.startswith("/jobs") else f"/jobs/{job_id}")


def _describe(a, names):
    """names: {'stage': {id: name}, 'user': {id: name}} for turning ids in the log into words."""
    if a.action == "create":
        return "Job created" if a.table_name == "jobs" else f"Estimate uploaded: {a.new_value}"
    if a.field == "current_document_id":
        return "Current estimate changed"
    if a.action in ("archive", "unarchive"):
        return "Job archived" if a.action == "archive" else "Job moved back to active"
    if a.field == "current_stage_id":
        n = names["stage"]
        return f"Stage: {n.get(int(a.old_value), '?') if a.old_value else 'Not started'} -> " \
               f"{n.get(int(a.new_value), '?') if a.new_value else 'Not started'}"
    if a.action == "assign":
        n = names["user"]
        return f"{a.field.capitalize()}: {n.get(int(a.old_value), '?') if a.old_value else '(none)'} -> " \
               f"{n.get(int(a.new_value), '?') if a.new_value else '(none)'}"
    return f"{a.field.replace('_', ' ')}: {a.old_value or '(blank)'} -> {a.new_value or '(blank)'}"


@app.route("/jobs/<int:job_id>")
def job(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        people = prod.current_assignments(s, [j.id])[j.id]
        info = {"id": j.id, "ro": j.ro_number, "customer": j.customer.name if j.customer else "", "vehicle": _vehicle(j),
                "vin": j.vehicle.vin if j.vehicle else "", "insurance": j.insurance.name if j.insurance else "",
                "claim": j.claim_no, "adjuster": j.adjuster, "estimator": j.estimator, "deductible": j.deductible,
                "loss_date": j.loss_date, "current_id": j.current_document_id, "archived_at": j.archived_at,
                **_prod_row(j, people, prod.stage_since(s, [j.id]).get(j.id))}
        versions = [{"id": d.id, "display": d.display, "printed": d.printed_at, "amount": d.supplement_amount,
                     "needs_review": d.needs_review, "uploaded": d.created_at, "file_id": d.file_id}
                    for d in sorted(j.documents, key=lambda d: d.id, reverse=True)]
        names = {"user": {u.id: u.name for u in s.scalars(select(User))},
                 "stage": {st.id: st.name for st in prod.stages(s, include_hidden=True)}}
        log = [{"at": a.at, "who": names["user"].get(a.user_id, ""), "what": _describe(a, names)}
               for a in s.scalars(select(AuditLog).where(AuditLog.job_id == j.id).order_by(AuditLog.id.desc()))]
        history, prev_at = [], None
        for e in prod.stage_history(s, j.id):
            history.append({"from": names["stage"].get(e.from_stage_id, "Not started"),
                            "to": names["stage"].get(e.to_stage_id, "Not started"), "at": e.moved_at,
                            "who": names["user"].get(e.moved_by, ""),
                            "days": "" if prev_at is None else round((e.moved_at - prev_at).total_seconds() / 86400, 1)})
            prev_at = e.moved_at
        opts = _options(s)
        _keep_current(opts, "stages", j.current_stage_id and s.get(ProductionStage, j.current_stage_id))
        for role, key in (("tech", "techs"), ("estimator", "estimators")):
            _keep_current(opts, key, people.get(role))
        return job_page(info, versions, log, opts, history)


@app.route("/jobs/<int:job_id>/archive", methods=["POST"])
def archive_job(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        prod.archive(s, j) if request.form.get("action") != "unarchive" else prod.unarchive(s, j)
        s.commit()
    back = request.form.get("next", "")
    return redirect(back if back.startswith(("/jobs", "/archive", "/documents")) else f"/jobs/{job_id}")


@app.route("/archive")
def archived():
    with Session() as s:
        rows = s.scalars(select(Job).where(Job.archived_at.is_not(None)).order_by(Job.archived_at.desc())).all()
        stage = {st.id: st.name for st in prod.stages(s, include_hidden=True)}
        return archive_list([{
            "id": j.id, "ro": j.ro_number, "customer": j.customer.name if j.customer else "", "vehicle": _vehicle(j),
            "insurance": j.insurance.name if j.insurance else "", "stage": stage.get(j.current_stage_id, "Not started"),
            "archived_at": j.archived_at} for j in rows])


@app.route("/settings")
def settings():
    with Session() as s:
        open_jobs = select(Job).where(Job.archived_at.is_(None))
        stage_jobs, user_jobs = {}, {}
        for j in s.scalars(open_jobs):
            stage_jobs[j.current_stage_id] = stage_jobs.get(j.current_stage_id, 0) + 1
        for a in s.scalars(select(JobAssignment).where(JobAssignment.removed_at.is_(None))):
            user_jobs[a.user_id] = user_jobs.get(a.user_id, 0) + 1
        st = sorted(prod.stages(s, include_hidden=True), key=lambda x: (not x.active, x.position, x.id))
        return settings_page(
            [{"id": x.id, "name": x.name, "active": x.active, "jobs": stage_jobs.get(x.id, 0)} for x in st],
            [{"id": u.id, "name": u.name, "role": u.role, "active": u.active, "jobs": user_jobs.get(u.id, 0)}
             for u in sorted(prod.employees(s, include_inactive=True), key=lambda u: (not u.active, u.name))],
            prod.EMPLOYEE_ROLES)


@app.route("/settings/stages", methods=["POST"])
def settings_stages():
    f = request.form
    with Session() as s:
        if f["action"] == "add" and f.get("name", "").strip():
            prod.add_stage(s, f["name"].strip())
        elif f["action"] != "add":
            st = s.get(ProductionStage, int(f["id"])) or abort(404)
            if f["action"] == "rename" and f.get("name", "").strip():
                set_field(s, st, "name", f["name"].strip())
            elif f["action"] in ("up", "down"):
                prod.move_stage_order(s, st, -1 if f["action"] == "up" else 1)
            elif f["action"] == "toggle":
                set_field(s, st, "active", not st.active)
        s.commit()
    return redirect("/settings")


@app.route("/settings/employees", methods=["POST"])
def settings_employees():
    f = request.form
    role = f.get("role") if f.get("role") in prod.EMPLOYEE_ROLES else "tech"
    with Session() as s:
        if f["action"] == "add" and f.get("name", "").strip():
            prod.add_employee(s, f["name"].strip(), role)
        elif f["action"] != "add":
            u = s.get(User, int(f["id"])) or abort(404)
            if f["action"] == "save" and f.get("name", "").strip():
                set_field(s, u, "name", f["name"].strip())
                set_field(s, u, "role", role)
            elif f["action"] == "toggle":
                set_field(s, u, "active", not u.active)
        s.commit()
    return redirect("/settings")


@app.route("/jobs/<int:job_id>/ro", methods=["POST"])
def set_ro(job_id):
    with Session() as s:
        j = s.get(Job, job_id) or abort(404)
        set_field(s, j, "ro_number", request.form.get("ro", "").strip(), job_id=j.id)
        s.commit()
    return redirect(f"/jobs/{job_id}")


@app.route("/documents/<int:doc_id>")
def document(doc_id):
    with Session() as s:
        d = s.get(EstimateDocument, doc_id) or abort(404)
        dup = "This PDF was already uploaded - showing the saved copy. " if request.args.get("dup") else "Saved to "
        archived = d.job.archived_at is not None
        note = (f"<div class='note row' style='justify-content:space-between'><span>{dup}"
                f"<a href='/jobs/{d.job_id}'>job {d.job.ro_number or '#' + str(d.job_id)}</a>"
                f" ({len(d.job.documents)} version{'s' if len(d.job.documents) != 1 else ''})"
                f"{' - archived' if archived else ''}.</span>{archive_btn(d.job_id, archived, f'/documents/{doc_id}')}</div>")
        return results(d.parse, note)


@app.route("/files/<int:file_id>")
def file(file_id):
    with Session() as s:
        f = s.get(File, file_id) or abort(404)
        return send_file(f.path, mimetype=f.content_type, download_name=f.original_name)


if __name__ == "__main__":
    app.run(debug=True)

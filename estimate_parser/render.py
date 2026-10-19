"""HTML rendering for parsed estimates and saved jobs."""
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

from db.values import SHOP_TZ

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#66707d;--line:#e2e6eb;--accent:#1f5fbf;--ok:#1a7f4b;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d222a;--ink:#e8ecf1;--mute:#98a2b0;--line:#2c333d;--accent:#7fb0ff;--ok:#5fd394;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px}
.sub{color:var(--mute);margin:0 0 16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px 22px}.grid div span{display:block;color:var(--mute);font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);font-size:14px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--bg);font-size:12px;color:var(--mute)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.wrap{overflow-x:auto}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;white-space:nowrap}
.ok{color:var(--ok)}.bad{color:var(--bad)}.sec{color:var(--mute);font-size:12px}
form.up{display:flex;gap:10px;align-items:center;flex-wrap:wrap}input[type=file]{flex:1;min-width:220px}
button.go{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 18px;font-size:15px;cursor:pointer}
.err,.review{background:var(--card);border:1px solid var(--bad);color:var(--bad);border-radius:10px;padding:12px 14px;margin:14px 0}
.review ul{margin:6px 0 0;padding-left:20px}
nav{display:flex;gap:18px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card)}
nav b{margin-right:auto}nav a{color:var(--accent);text-decoration:none}a{color:var(--accent)}
.flag{background:var(--bad);color:#fff}.note{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:0 0 14px}
form.ro{display:flex;gap:8px;align-items:center}form.ro input{width:90px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
button.small{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:5px 12px;cursor:pointer}
button.plain{background:none;border:1px solid var(--line);color:var(--ink);border-radius:6px;padding:4px 9px;cursor:pointer}
select,input.txt{padding:4px 6px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--ink);font:inherit;font-size:14px;max-width:100%}
table.jobs td{vertical-align:middle}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.tabs a{border:1px solid var(--line);background:var(--card);border-radius:99px;padding:3px 12px;text-decoration:none;color:var(--ink)}
.tabs a span{color:var(--mute);font-size:12px}.tabs a.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tabs a.on span{color:#fff}.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:0}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 22px}
.grid form.ro input{width:110px}.done{background:var(--ok);color:#fff}.open{border:1px solid var(--line)}tfoot th{background:var(--bg);color:var(--ink);font-size:13px}
"""


def _n(v, d=2, prefix=""):
    return "" if v is None else f"{prefix}{v:,.{d}f}"


NAV = "<nav><b>Shop Database</b><a href='/'>Upload estimate</a><a href='/jobs'>Jobs</a></nav>"


def page(body, title="Shop Database"):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{NAV}<main>{body}</main></body></html>")


def upload_form(error=""):
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    return page(
        "<h1>Upload estimate</h1><p class='sub'>Upload a CCC ONE or Mitchell estimate or supplement PDF. It is read and saved "
        "to its job (matched by RO #, then claim #) and filed with the jobs; a supplement becomes a new version of the same job.</p>"
        f"{err}<div class='card'><form class='up' method='post' action='/' enctype='multipart/form-data'>"
        "<input type='file' name='pdf' accept='application/pdf,.pdf' required>"
        "<button class='go' type='submit'>Save estimate</button></form></div>")


def _utc(d):
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dt(v):
    """ISO text or datetime -> '9/17/2026 1:20 PM'. Saved times are UTC and shown in the shop's time zone."""
    if not v:
        return ""
    d = v if isinstance(v, datetime) else datetime.fromisoformat(v)
    if isinstance(v, datetime):  # SQLite hands some saved times back without the zone - they are UTC
        d = _utc(d).astimezone(SHOP_TZ)
    return f"{d.month}/{d.day}/{d.year} {d.strftime('%I:%M %p').lstrip('0')}"


# ---------------------------------------------------------------- job list
# Columns come from core.job_numbers() - the same numbers a bookkeeping export will use.

LIST_COLUMNS = [("body_hours", "Body", 1), ("refinish_hours", "Refinish", 1), ("mechanical_hours", "Mech", 1),
                ("total_hours", "Total hrs", 1), ("labor_amount", "Labor $", 2), ("parts", "Parts $", 2),
                ("tax", "Tax $", 2), ("grand_total", "Grand total", 2)]


def jobs_list(jobs, totals, f, periods):
    """jobs: dicts id, ro, customer, vehicle, insurance, claim, date (estimate printed), needs_review, closed, numbers;
    totals: summed numbers; f: current filters q, start, end, status (open | closed | all);
    periods: quick date ranges (label, start, end)."""
    rows = "".join(
        f"<tr><td><a href='/jobs/{j['id']}'>{escape(j['ro']) or '&mdash;'}</a>"
        f"{' <span class=\"chip flag\">Needs review</span>' if j['needs_review'] else ''}"
        f"{' <span class=\"chip done\">Closed</span>' if j['closed'] else ''}</td>"
        f"<td>{escape(j['customer'])}</td><td>{escape(j['vehicle'])}</td><td>{escape(j['insurance'])}</td>"
        f"<td>{_d(j['date'])}</td>"
        + "".join(f"<td class='n'>{_n(j['numbers'][k], d)}</td>" for k, _, d in LIST_COLUMNS) + "</tr>" for j in jobs)
    foot = (f"<tr><th colspan='5'>Total - {len(jobs)} job{'s' if len(jobs) != 1 else ''}</th>"
            + "".join(f"<th class='n'>{_n(totals[k], d)}</th>" for k, _, d in LIST_COLUMNS) + "</tr>")
    head = ("<tr><th>RO #</th><th>Customer</th><th>Vehicle</th><th>Insurance</th><th>Estimate date</th>"
            + "".join(f"<th class='n'>{label}</th>" for _, label, _ in LIST_COLUMNS) + "</tr>")
    table = (f"<div class='wrap'><table class='jobs'><thead>{head}</thead><tbody>{rows}</tbody><tfoot>{foot}</tfoot>"
             "</table></div>") if jobs else "<p class='sub'>No jobs match.</p>"
    st = f"&status={f['status']}"
    status = "".join(f"<a class='tab{' on' if f['status'] == v else ''}' "
                     f"href='/jobs?status={v}&start={f['start']}&end={f['end']}&q={quote(f["q"])}'>{label}</a>"
                     for v, label in (("open", "Open"), ("closed", "Closed"), ("all", "All jobs")))
    quick = "".join(f"<a class='tab{' on' if (f['start'], f['end']) == (s, e) else ''}' "
                    f"href='/jobs?start={s}&end={e}&q={quote(f["q"])}{st}'>{escape(label)}</a>" for label, s, e in periods)
    quick += f"<a class='tab{' on' if not (f['start'] or f['end']) else ''}' href='/jobs?q={quote(f["q"])}{st}'>All dates</a>"
    form = ("<form method='get' action='/jobs' class='row' style='margin:0 0 10px'>"
            f"<input class='txt' name='q' value='{escape(f['q'])}' placeholder='RO #, customer, VIN, claim # or insurance' "
            "aria-label='Search' style='flex:1;min-width:220px'>"
            f"<label class='sec'>From <input class='txt' type='date' name='start' value='{f['start']}'></label>"
            f"<label class='sec'>To <input class='txt' type='date' name='end' value='{f['end']}'></label>"
            f"<input type='hidden' name='status' value='{f['status']}'><button class='small'>Show</button></form>")
    return page("<h1>Jobs</h1><p class='sub'>Every uploaded estimate is filed here with its job. A job is Closed once "
                "every invoice is closed out, everything is paid and the shop's audits are done. Hours and dollars are "
                "as printed on each job's current estimate; dates are the date that estimate was printed.</p>"
                f"{form}<div class='tabs'>{status}</div><div class='tabs'>{quick}</div>{table}", "Jobs")


def _d(v):
    """ISO text -> '9/17/2026' (date only)."""
    if not v:
        return ""
    d = datetime.fromisoformat(v)
    return f"{d.month}/{d.day}/{d.year}"


# ---------------------------------------------------------------- job page
# One page per job. It is a list of sections; each takes the same context dict and returns HTML (or "" to skip).
# A new feature adds one function to JOB_SECTIONS - nothing else on the page changes.
#
# ctx: job (dict, closed = when it was closed or None), versions (list of dicts: id, display, name, printed, amount, needs_review, uploaded, file_id, uploaded_as),
#      shown (the version dict being shown), summary (that version's parse summary), note (shown once after an upload)

LABOR_LABEL = {"Body labor": "Body", "Paint labor": "Refinish", "Mechanical labor": "Mechanical", "Other labor": "Other"}


def _job_header(ctx):
    j = ctx["job"]
    facts = " &middot; ".join(escape(x) for x in (f"RO {j['ro']}" if j["ro"] else "No RO #", j["insurance"],
                                                   f"Claim {j['claim']}" if j["claim"] else "") if x)
    note = f"<div class='note'>{escape(ctx['note'])}</div>" if ctx["note"] else ""
    return (f"<p><a href='/jobs'>&larr; Jobs</a></p><h1>{escape(j['customer']) or 'Job'} "
            f"<span class='sec'>{escape(j['vehicle'])}</span></h1><p class='sub'>{facts}</p>{note}")


def _job_versions(ctx):
    """Which estimate version the numbers below come from; the newest is the job's current one."""
    if not ctx["versions"]:
        return "<p class='sub'>No estimate saved for this job yet.</p>"
    j, shown = ctx["job"], ctx["shown"]
    tabs = "".join(
        f"<a class='tab{' on' if v['id'] == shown['id'] else ''}' href='/jobs/{j['id']}?v={v['id']}'>{escape(v['name'].removesuffix('.pdf'))}"
        f"{' <span>current</span>' if v['id'] == j['current_id'] else ''}</a>" for v in reversed(ctx["versions"]))
    pdf = f" &middot; <a href='/files/{shown['file_id']}'>Open {escape(shown['name'])}</a>" if shown["file_id"] else ""
    older = "" if shown["id"] == j["current_id"] else " &middot; <b>older version</b> - the current one is the newest"
    return (f"<div class='tabs'>{tabs}</div><p class='sec' style='margin:-4px 0 12px'>Printed {_dt(shown['printed']) or '?'}"
            f"{pdf}{older}</p>")


def _job_review(ctx):
    m = ctx["summary"]
    if not m or not m["needs_review"]:
        return ""
    items = "".join(f"<li>{escape(x)}</li>" for x in m["review_reasons"])
    return f"<div class='review'><strong>Needs review</strong> - the numbers below may be wrong<ul>{items}</ul></div>"


def _job_numbers(ctx):
    """Hours and money from the shown estimate - only what the estimate prints."""
    m = ctx["summary"]
    if not m:
        return ""
    lrows = "".join(
        f"<tr><td>{LABOR_LABEL.get(x['category'], escape(x['category']))}</td><td class='n'>{_n(x['hours'], 1)}</td>"
        f"<td class='n'>{_n(x['rate'], 2, '$')}</td><td class='n'>{_n(x['amount'], 2, '$')}</td></tr>"
        for x in m["labor"] if x["category"] != "Other labor" or x["hours"])
    lrows += (f"<tr><th>Total</th><th class='n'>{_n(m['total_labor_hours'], 1)}</th><th></th>"
              f"<th class='n'>{_n(m['total_labor_amount'], 2, '$')}</th></tr>")
    hours = ("<div><h2>Labor hours</h2><table><thead><tr><th>Type</th><th class='n'>Hours</th><th class='n'>Rate</th>"
             f"<th class='n'>Amount</th></tr></thead><tbody>{lrows}</tbody></table></div>")
    mrows = f"<tr><td>Parts</td><td class='n'>{_n(m['parts_total'], 2, '$')}</td></tr>" + "".join(
        f"<tr><td>{escape(o['label'])}</td><td class='n'>{_n(o['amount'], 2, '$')}</td></tr>" for o in m["other_charges"])
    money = f"<div><h2>Totals</h2><table><tbody>{mrows}</tbody></table></div>"
    return f"<div class='two'>{hours}{money}</div>"


def _job_details(ctx):
    j = ctx["job"]
    ro = (f"<form class='ro' method='post' action='/jobs/{j['id']}/ro'><input id='ro' name='ro' value='{escape(j['ro'])}' "
          f"maxlength='20' aria-label='RO #'><button class='small'>Save</button></form>")
    loss = j["loss_date"]
    fields = [("VIN", j["vin"]), ("Adjuster", j["adjuster"]), ("Estimator on estimate", j["estimator"]),
              ("Deductible", _n(j["deductible"], 2, "$")), ("Loss date", f"{loss.month}/{loss.day}/{loss.year}" if loss else "")]
    info = "".join(f"<div><span>{escape(k)}</span>{escape(str(v)) or '&mdash;'}</div>" for k, v in fields)
    return f"<h2>Job details</h2><div class='card'><div class='grid'><div><span>RO #</span>{ro}</div>{info}</div></div>"


def _job_documents(ctx):
    """Every document filed for the job, named LAST-RO-TYPE.pdf, with the name it was uploaded as."""
    if not ctx["versions"]:
        return ""
    rows = "".join(
        f"<tr><td><a href='/files/{v['file_id']}'>{escape(v['name'])}</a>"
        f"{' (current)' if v['id'] == ctx['job']['current_id'] else ''}"
        f"<div class='sec'>uploaded as {escape(v['uploaded_as'])}</div></td>"
        f"<td><a href='/jobs/{ctx['job']['id']}?v={v['id']}'>{escape(v['display'])}</a></td><td>{_dt(v['printed'])}</td>"
        f"<td class='n'>{_n(v['amount'], 2, '$')}</td><td>{_dt(v['uploaded'])}</td></tr>" for v in reversed(ctx["versions"]))
    return ("<h2>Documents</h2><div class='wrap'><table><thead><tr><th>File</th><th>Title on the document</th>"
            f"<th>Printed</th><th class='n'>Supplement amount</th><th>Uploaded</th></tr></thead><tbody>{rows}</tbody></table></div>")


def _job_status(ctx):
    """Open until a person closes the job: every invoice closed out, everything paid, the shop's audits done."""
    j = ctx["job"]
    if j["closed"]:
        return (f"<form class='row note' method='post' action='/jobs/{j['id']}/reopen'><span class='chip done'>Closed</span>"
                f"<span class='sec'>{_dt(j['closed'])}</span><button class='plain'>Reopen job</button></form>")
    return (f"<form class='row note' method='post' action='/jobs/{j['id']}/close'><span class='chip open'>Open</span>"
            "<span class='sec'>Close only when every invoice is closed out, everything is paid and the shop's audits "
            "are done.</span><button class='small'>Close job</button></form>")


JOB_SECTIONS = [_job_header, _job_status, _job_versions, _job_review, _job_numbers, _job_details, _job_documents]


def job_page(ctx):
    return page("".join(section(ctx) for section in JOB_SECTIONS), f"Job {ctx['job']['ro'] or ctx['job']['id']}")

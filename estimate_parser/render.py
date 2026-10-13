"""HTML rendering for parsed estimates and saved jobs."""
from datetime import datetime, timezone
from html import escape

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#66707d;--line:#e2e6eb;--accent:#1f5fbf;--ok:#1a7f4b;--bad:#b3261e;
--part:#e8f0fe;--body:#fdeedd;--paint:#f3e8fd;--mech:#e3f5ee;--other:#eef0f3}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d222a;--ink:#e8ecf1;--mute:#98a2b0;--line:#2c333d;--accent:#7fb0ff;--ok:#5fd394;--bad:#ff8a80;
--part:#1d2b45;--body:#43301c;--paint:#35244a;--mech:#1b3a2f;--other:#2a3038}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px}
.sub{color:var(--mute);margin:0 0 16px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px 22px}.grid div span{display:block;color:var(--mute);font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);font-size:14px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--bg);font-size:12px;color:var(--mute)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.wrap{overflow-x:auto}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;white-space:nowrap}
.Part{background:var(--part)}.Body{background:var(--body)}.Paint{background:var(--paint)}.Mechanical{background:var(--mech)}.Other{background:var(--other)}
.filters{margin:0 0 8px;display:flex;gap:6px;flex-wrap:wrap}.filters button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:99px;padding:3px 12px;cursor:pointer}
.filters button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
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
form.auto{display:flex;gap:4px;margin:0}select,input.txt{padding:4px 6px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--ink);font:inherit;font-size:14px;max-width:100%}
table.jobs td{vertical-align:middle}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 10px}
.tabs a{border:1px solid var(--line);background:var(--card);border-radius:99px;padding:3px 12px;text-decoration:none;color:var(--ink)}
.tabs a span{color:var(--mute);font-size:12px}.tabs a.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tabs a.on span{color:#fff}.row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:0}.off{opacity:.55}
.prod{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px 22px}.prod label{display:block;color:var(--mute);font-size:12px}
"""

JS = """
document.querySelectorAll('.filters button').forEach(function(b){b.onclick=function(){
 document.querySelectorAll('.filters button').forEach(function(x){x.classList.remove('on')});b.classList.add('on');
 var f=b.dataset.f;document.querySelectorAll('#charges tbody tr').forEach(function(r){r.style.display=(f==='all'||r.dataset.c===f)?'':'none'});};});
document.querySelectorAll('form.auto select').forEach(function(s){s.onchange=function(){s.form.submit()};});
"""


def _kind(cat):
    first = cat.split()[0]
    return first if first in ("Body", "Paint", "Mechanical") else "Part" if cat == "Part" else "Other"


def _n(v, d=2, prefix=""):
    return "" if v is None else f"{prefix}{v:,.{d}f}"


NAV = "<nav><b>Shop Database</b><a href='/'>Upload estimate</a><a href='/jobs'>Active jobs</a><a href='/archive'>Archive</a><a href='/settings'>Settings</a></nav>"


def page(body, title="Shop Database"):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{NAV}<main>{body}</main><script>{JS}</script></body></html>")


def upload_form(error=""):
    err = f"<div class='err'>{escape(error)}</div>" if error else ""
    return page(
        "<h1>Upload estimate</h1><p class='sub'>Upload a CCC ONE or Mitchell estimate or supplement PDF. It is read and saved "
        "to its job (matched by RO #, then claim #, then VIN); a supplement becomes a new version of the same job.</p>"
        f"{err}<div class='card'><form class='up' method='post' action='/' enctype='multipart/form-data'>"
        "<input type='file' name='pdf' accept='application/pdf,.pdf' required>"
        "<button class='go' type='submit'>Save estimate</button></form></div>")


def _utc(d):
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dt(v):
    """ISO text or datetime -> '9/17/2026 1:20 PM'."""
    if not v:
        return ""
    d = v if isinstance(v, datetime) else datetime.fromisoformat(v)
    if isinstance(v, datetime):  # saved times are UTC (SQLite hands them back without the zone); printed times are text
        d = _utc(d).astimezone()
    return f"{d.month}/{d.day}/{d.year} {d.strftime('%I:%M %p').lstrip('0')}"


def _select(job_id, field, value, options, blank, back):
    """A dropdown that saves one production field of a job as soon as it changes (button shown without JS)."""
    opts = f"<option value=''>{escape(blank)}</option>" + "".join(
        f"<option value='{k}'{' selected' if k == value else ''}>{escape(label)}</option>" for k, label in options)
    return (f"<form class='auto' method='post' action='/jobs/{job_id}/production'><input type='hidden' name='next' "
            f"value='{escape(back)}'><select name='{field}' aria-label='{field}'>{opts}</select>"
            "<noscript><button class='small'>Save</button></noscript></form>")


def production_fields(j, opts, back):
    """Stage, tech and estimator dropdowns. j: dict with id, stage_id, tech_id, est_id; opts: stages/techs/estimators."""
    return (_select(j["id"], "stage", j["stage_id"], opts["stages"], "Not started", back),
            _select(j["id"], "tech", j["tech_id"], opts["techs"], "No tech", back),
            _select(j["id"], "estimator", j["est_id"], opts["estimators"], "No estimator", back))


def _days(since):
    if not since:
        return ""
    d = (datetime.now(timezone.utc) - _utc(since)).days
    return "today" if d == 0 else f"{d} day{'s' if d != 1 else ''}"


def archive_btn(job_id, archived, back):
    action, label = ("unarchive", "Move back to active") if archived else ("archive", "Archive")
    return (f"<form method='post' action='/jobs/{job_id}/archive' class='row'><input type='hidden' name='action' "
            f"value='{action}'><input type='hidden' name='next' value='{escape(back)}'>"
            f"<button class='plain'>{label}</button></form>")


def archive_list(jobs):
    """Archived jobs. jobs: dicts with id, ro, customer, vehicle, insurance, stage, archived_at."""
    rows = "".join(
        f"<tr><td><a href='/jobs/{j['id']}'>{escape(j['ro']) or '&mdash;'}</a></td><td>{escape(j['customer'])}</td>"
        f"<td>{escape(j['vehicle'])}</td><td>{escape(j['insurance'])}</td><td>{escape(j['stage'])}</td>"
        f"<td>{_dt(j['archived_at'])}</td><td>{archive_btn(j['id'], True, '/archive')}</td></tr>" for j in jobs)
    table = ("<div class='wrap'><table class='jobs'><thead><tr><th>RO #</th><th>Customer</th><th>Vehicle</th>"
             "<th>Insurance</th><th>Last stage</th><th>Archived</th><th></th></tr></thead>"
             f"<tbody>{rows}</tbody></table></div>") if jobs else "<p class='sub'>No archived jobs.</p>"
    return page(f"<h1>Archive</h1><p class='sub'>{len(jobs)} archived job{'s' if len(jobs) != 1 else ''}. Nothing is "
                f"deleted - open a job to see all of it, or move it back to active.</p>{table}", "Archive")


def jobs_list(jobs, opts, tabs, back):
    """Active jobs. jobs: dicts with id, ro, customer, vehicle, insurance, needs_review, stage_id, tech_id,
    est_id, since; tabs: (label, url, count, on)."""
    nav = "".join(f"<a class='tab{' on' if on else ''}' href='{url}'>{escape(label)} <span>{n}</span></a>"
                  for label, url, n, on in tabs)
    rows = []
    for j in jobs:
        stage, tech, est = production_fields(j, opts, back)
        rows.append(
            f"<tr><td><a href='/jobs/{j['id']}'>{escape(j['ro']) or '&mdash;'}</a>"
            f"{' <span class=\"chip flag\">Needs review</span>' if j['needs_review'] else ''}</td><td>{escape(j['customer'])}</td>"
            f"<td>{escape(j['vehicle'])}</td><td>{escape(j['insurance'])}</td><td>{stage}</td><td>{tech}</td><td>{est}</td>"
            f"<td class='n'>{_days(j['since'])}</td></tr>")
    table = ("<div class='wrap'><table class='jobs'><thead><tr><th>RO #</th><th>Customer</th><th>Vehicle</th>"
             "<th>Insurance</th><th>Stage</th><th>Tech</th><th>Estimator</th><th class='n'>In stage</th>"
             f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
             ) if jobs else "<p class='sub'>No jobs here.</p>"
    return page(f"<h1>Active jobs</h1><p class='sub'>Change a job's stage, tech or estimator right in the table - it saves "
                f"as soon as you pick. Stages and employees are set up on <a href='/settings'>Settings</a>.</p>"
                f"<div class='tabs'>{nav}</div>{table}", "Active jobs")


def job_page(j, versions, log, opts, history):
    """j: job dict; versions: dicts with id, display, printed, amount, needs_review, uploaded, file_id; log: audit dicts;
    opts: dropdown choices; history: stage moves (from, to, at, who, days)."""
    stage, tech, est = production_fields(j, opts, f"/jobs/{j['id']}")
    prod = (f"<h2>Production</h2><div class='card'><div class='prod'><div><label>Stage</label>{stage}</div>"
            f"<div><label>Tech</label>{tech}</div><div><label>Estimator</label>{est}</div>"
            f"<div><label>In this stage</label>{_days(j['since']) or '&mdash;'}</div></div></div>")
    hrows = "".join(f"<tr><td>{escape(h['from'])} &rarr; {escape(h['to'])}</td><td>{_dt(h['at'])}</td>"
                    f"<td>{escape(h['who'])}</td><td class='n'>{h['days']}</td></tr>" for h in reversed(history))
    stage_hist = ("<h2>Stage history</h2><div class='wrap'><table><thead><tr><th>Move</th><th>When</th><th>Who</th>"
                  f"<th class='n'>Days in previous stage</th></tr></thead><tbody>{hrows}</tbody></table></div>") if history else ""
    fields = [("Customer", j["customer"]), ("Vehicle", j["vehicle"]), ("VIN", j["vin"]), ("Insurance", j["insurance"]),
              ("Claim #", j["claim"]), ("Adjuster", j["adjuster"]), ("Estimator on estimate", j["estimator"]),
              ("Deductible", j["deductible"]), ("Loss date", j["loss_date"])]
    info = "".join(f"<div><span>{escape(k)}</span>{escape(str(v)) or '&nbsp;'}</div>" for k, v in fields)
    ro = (f"<form class='ro' method='post' action='/jobs/{j['id']}/ro'><label for='ro'>RO #</label>"
          f"<input id='ro' name='ro' value='{escape(j['ro'])}' maxlength='20'><button class='small'>Save</button></form>")
    vrows = "".join(
        f"<tr><td><a href='/documents/{v['id']}'>{escape(v['display'])}</a>{' (current)' if v['id'] == j['current_id'] else ''}"
        f"{' <span class=\"chip flag\">Needs review</span>' if v['needs_review'] else ''}</td>"
        f"<td>{_dt(v['printed'])}</td><td class='n'>{_n(v['amount'], 2, '$')}</td><td>{_dt(v['uploaded'])}</td>"
        f"<td>{f'<a href=\"/files/{v['file_id']}\">PDF</a>' if v['file_id'] else ''}</td></tr>" for v in versions)
    lrows = "".join(
        f"<tr><td>{_dt(a['at'])}</td><td>{escape(a['who'])}</td><td>{escape(a['what'])}</td></tr>" for a in log)
    archived = j["archived_at"] is not None
    status = (f"<div class='note row'>Archived {_dt(j['archived_at'])} - this job is not on the active list."
              f"{archive_btn(j['id'], True, f'/jobs/{j['id']}')}</div>") if archived else ""
    top = f"<div class='card row' style='justify-content:space-between'>{ro}" + (
        "" if archived else archive_btn(j["id"], False, "/jobs")) + "</div>"
    back = "<a href='/archive'>&larr; Archive</a>" if archived else "<a href='/jobs'>&larr; Active jobs</a>"
    body = (f"<p>{back}</p><h1>{escape(j['customer']) or 'Job'} "
            f"<span class='sec'>{escape(j['vehicle'])}</span></h1>{status}{top}{prod}{stage_hist}"
            f"<h2>Job</h2><div class='card'><div class='grid'>{info}</div></div>"
            "<h2>Estimate versions</h2><div class='wrap'><table><thead><tr><th>Document</th><th>Printed</th>"
            f"<th class='n'>Supplement amount</th><th>Uploaded</th><th></th></tr></thead><tbody>{vrows}</tbody></table></div>"
            "<h2>Change log</h2><div class='wrap'><table><thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>"
            f"<tbody>{lrows}</tbody></table></div>")
    return page(body, f"Job {j['ro'] or j['id']}")


def _act(url, action, item_id, label, cls="plain"):
    return (f"<form method='post' action='{url}' class='row'><input type='hidden' name='action' value='{action}'>"
            f"<input type='hidden' name='id' value='{item_id}'><button class='{cls}'>{label}</button></form>")


def settings_page(stages, employees, roles):
    """stages: dicts id, name, active, jobs (count); employees: dicts id, name, role, active, jobs."""
    srows = []
    for i, st in enumerate(stages):
        u = "/settings/stages"
        srows.append(
            f"<tr class='{'' if st['active'] else 'off'}'><td><form method='post' action='{u}' class='row'>"
            f"<input type='hidden' name='action' value='rename'><input type='hidden' name='id' value='{st['id']}'>"
            f"<input class='txt' name='name' value='{escape(st['name'])}' maxlength='60' aria-label='Stage name'>"
            f"<button class='plain'>Rename</button></form></td><td class='n'>{st['jobs']}</td><td><div class='row'>"
            + (_act(u, "up", st['id'], "&uarr;") if st['active'] and i else "")
            + (_act(u, "down", st['id'], "&darr;") if st['active'] and i < len(stages) - 1 and stages[i + 1]['active'] else "")
            + _act(u, "toggle", st['id'], "Hide" if st['active'] else "Show again") + "</div></td></tr>")
    role_opts = lambda cur: "".join(f"<option{' selected' if r == cur else ''}>{r}</option>" for r in roles)
    erows = []
    for e in employees:
        u = "/settings/employees"
        erows.append(
            f"<tr class='{'' if e['active'] else 'off'}'><td><form method='post' action='{u}' class='row'>"
            f"<input type='hidden' name='action' value='save'><input type='hidden' name='id' value='{e['id']}'>"
            f"<input class='txt' name='name' value='{escape(e['name'])}' maxlength='120' aria-label='Name'>"
            f"<select name='role' aria-label='Role'>{role_opts(e['role'])}</select><button class='plain'>Save</button></form></td>"
            f"<td class='n'>{e['jobs']}</td><td>{_act(u, 'toggle', e['id'], 'Deactivate' if e['active'] else 'Reactivate')}</td></tr>")
    body = (
        "<h1>Settings</h1><p class='sub'>Changes are saved to the change log. Hidden stages and inactive employees stay on "
        "the history of jobs that used them.</p>"
        "<h2>Production stages</h2><div class='wrap'><table><thead><tr><th>Stage (in board order)</th>"
        f"<th class='n'>Active jobs</th><th></th></tr></thead><tbody>{''.join(srows)}</tbody></table></div>"
        "<div class='card' style='margin-top:8px'><form method='post' action='/settings/stages' class='row'>"
        "<input type='hidden' name='action' value='add'><input class='txt' name='name' placeholder='New stage name' "
        "maxlength='60' required aria-label='New stage name'><button class='small'>Add stage</button></form></div>"
        "<h2>Employees</h2><div class='wrap'><table><thead><tr><th>Name and role</th><th class='n'>Active jobs</th><th></th>"
        f"</tr></thead><tbody>{''.join(erows) or '<tr><td colspan=3>No employees yet.</td></tr>'}</tbody></table></div>"
        "<div class='card' style='margin-top:8px'><form method='post' action='/settings/employees' class='row'>"
        "<input type='hidden' name='action' value='add'><input class='txt' name='name' placeholder='Name' maxlength='120' "
        f"required aria-label='New employee name'><select name='role' aria-label='Role'>{role_opts('tech')}</select>"
        "<button class='small'>Add employee</button></form></div>")
    return page(body, "Settings")


def results(r, note=""):
    m = r["summary"]
    d = m["document"]
    fields = [("Customer", m["customer"]), ("RO #", m["ro_number"]), ("Vehicle", m["vehicle"]), ("VIN", m["vin"]),
              ("Insurance", m["insurance"]), ("Claim #", m["claim"])]
    info = "".join(f"<div><span>{escape(k)}</span>{escape(str(val)) or '&nbsp;'}</div>" for k, val in fields)

    lrows = "".join(
        f"<tr><td>{escape(x['category'])}</td><td class='n'>{_n(x['hours'], 1)}</td>"
        f"<td class='n'>{_n(x['rate'], 2, '$')}</td><td class='n'>{_n(x['amount'], 2, '$')}</td></tr>" for x in m["labor"])
    lrows += (f"<tr><th>Total labor</th><th class='n'>{_n(m['total_labor_hours'], 1)}</th><th></th>"
              f"<th class='n'>{_n(m['total_labor_amount'], 2, '$')}</th></tr>")
    labor = ("<h2>Labor</h2><div class='wrap'><table><thead><tr><th>Type</th><th class='n'>Hours</th>"
             f"<th class='n'>Rate</th><th class='n'>Amount</th></tr></thead><tbody>{lrows}</tbody></table></div>")

    parts = ("<h2>Parts</h2><div class='wrap'><table><tbody><tr><td>Total parts</td>"
             f"<td class='n'>{_n(m['parts_total'], 2, '$')}</td></tr></tbody></table></div>")

    orows = "".join(f"<tr><td>{escape(o['label'])}</td><td class='n'>{_n(o['amount'], 2, '$')}</td></tr>"
                    for o in m["other_charges"])
    other = ("<h2>Other price breakdowns</h2><div class='wrap'><table><tbody>" + orows + "</tbody></table></div>") if orows else ""

    hist = m["history"]
    if hist:
        hrows = "".join(f"<tr><td>{escape(e['label'])}</td><td>{escape(e['by'])}</td><td class='n'>{_n(e['amount'], 2, '$')}</td></tr>"
                        for e in hist["entries"])
        if hist["total"]:
            hrows += (f"<tr><th>{escape(hist['total']['label'])}</th><th></th>"
                      f"<th class='n'>{_n(hist['total']['amount'], 2, '$')}</th></tr>")
        history = ("<h2>Document history</h2><div class='wrap'><table><thead><tr><th>Document</th><th>By</th>"
                   f"<th class='n'>Amount</th></tr></thead><tbody>{hrows}</tbody></table></div>")
    else:
        history = ""

    review = ""
    if m["needs_review"]:
        items = "".join(f"<li>{escape(x)}</li>" for x in m["review_reasons"])
        review = f"<div class='review'><strong>Needs review</strong><ul>{items}</ul></div>"

    body = (f"{note or '<p><a href=\"/\">&larr; Upload another</a></p>'}<h1>{escape(d['display'])}</h1>"
            f"<p class='sub'>{escape(r['filename'] or '')}</p>{review}{history}"
            f"<h2>Job</h2><div class='card'><div class='grid'>{info}</div></div>{labor}{parts}{other}")
    return page(body, f"Parsed: {d['display']}")

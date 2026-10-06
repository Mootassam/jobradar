"""JobRadar - worldwide job search engine for personal use.

Run: python server.py  ->  http://127.0.0.1:5110
Local only (binds 127.0.0.1). Write requests must carry the X-JobRadar header, which a foreign website
cannot add without CORS approval - so other pages in your browser can't drive your local JobRadar."""
import csv
import io
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

import alerts
import applicant as profile
import app_paths
import cvcheck
import engine
import enrich
import extract
import geo
import matcher
import nightly
import outreach
import signals
import store
from sources import all_sources, ats

log = logging.getLogger("jobradar")
app = Flask(__name__, static_folder=app_paths.STATIC_DIR, template_folder=app_paths.TEMPLATE_DIR)
app.json.ensure_ascii = False
app.json.sort_keys = False
ASSET_V = app_paths.APP_VERSION + "-" + str(int(time.time()))
SECRET_KEYS = ("adzuna_app_key", "jooble_key", "usajobs_key", "imap_password", "careerjet_affid", "reliefweb_appname", "smtp_password")
STATUSES = ("new", "saved", "applied", "interview", "offer", "rejected")


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg, self.status = msg, status


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({"ok": False, "error": e.msg}), e.status


@app.errorhandler(Exception)
def _any_error(e):
    if hasattr(e, "code") and isinstance(getattr(e, "code"), int):
        return jsonify({"ok": False, "error": getattr(e, "description", str(e))}), e.code
    log.exception("error on %s", request.path)
    return jsonify({"ok": False, "error": "Internal error: %s" % str(e)[:200]}), 500


@app.before_request
def _guard():
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-JobRadar") != "1":
        abort(403)
    host = (request.host or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        abort(403)                   # blocks DNS-rebinding tricks


@app.after_request
def _headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if resp.mimetype == "text/html":
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                                                   "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def ok(**kw):
    kw.setdefault("ok", True)
    return jsonify(kw)


def public_settings():
    s = engine.settings()
    for k in SECRET_KEYS:
        if s.get(k):
            s[k] = "••••••••"
    return s


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    return render_template("index.html", v=ASSET_V)


@app.route("/api/meta")
def api_meta():
    st = engine.settings()
    return ok(version=app_paths.APP_VERSION, countries=geo.countries_list(),
              regions={cc: geo.regions_for(cc) for cc in geo.REGIONS},
              sources=[s.info(st) for s in all_sources()], settings=public_settings(), statuses=STATUSES)


@app.route("/api/stats")
def api_stats():
    s = store.stats()
    s["unread"] = store.q1("SELECT COUNT(*) AS n FROM notifications WHERE read = 0")["n"]
    s["active_runs"] = list(engine.RUNS.keys())
    n = store.q1("SELECT id, report, seen, finished_at FROM night_runs WHERE status = 'done' ORDER BY id DESC LIMIT 1")
    if n:
        rep = json.loads(n["report"] or "{}")
        s["night"] = {"id": n["id"], "headline": rep.get("headline", ""), "seen": n["seen"], "finished_at": n["finished_at"]}
    s["night_running"] = nightly.running()
    return ok(stats=s)


# ---------------------------------------------------------------- search runs

@app.route("/api/search", methods=["POST"])
def api_search():
    d = body()
    rid = engine.start_run(d, d.get("sources") or None)
    return ok(run_id=rid)


def run_out(r):
    d = dict(r)
    d["params"] = json.loads(d["params"])
    d["progress"] = json.loads(d["progress"] or "{}")
    d["active"] = d["id"] in engine.RUNS
    return d


@app.route("/api/runs")
def api_runs():
    rows = store.q("SELECT * FROM runs ORDER BY id DESC LIMIT 50")
    return ok(runs=[run_out(r) for r in rows])


@app.route("/api/runs/<int:rid>")
def api_run(rid):
    r = store.q1("SELECT * FROM runs WHERE id = ?", (rid,))
    if r is None:
        raise ApiError("Run not found", 404)
    return ok(run=run_out(r))


@app.route("/api/runs/<int:rid>", methods=["DELETE"])
def api_run_delete(rid):
    if rid in engine.RUNS:
        raise ApiError("Stop this search before deleting it.")
    return ok(count=store.delete_runs([rid]))


@app.route("/api/runs/delete", methods=["POST"])
def api_runs_delete():
    """Delete search history (the jobs found stay in All jobs). all=true -> every finished search."""
    d = body()
    ids = [r["id"] for r in store.q("SELECT id FROM runs")] if d.get("all") else [int(i) for i in d.get("ids") or []]
    active = [i for i in ids if i in engine.RUNS]
    return ok(count=store.delete_runs([i for i in ids if i not in engine.RUNS]), skipped_running=len(active))


@app.route("/api/runs/<int:rid>/stop", methods=["POST"])
def api_run_stop(rid):
    return ok(stopped=engine.stop_run(rid))


@app.route("/api/runs/<int:rid>/resume", methods=["POST"])
def api_run_resume(rid):
    if not engine.resume_run(rid):
        raise ApiError("This search can't be resumed (it already finished).")
    return ok(run_id=rid)


@app.route("/api/expand")
def api_expand():
    """Which extra terms a search will also cover (multilingual expansion) - shown under the search box."""
    from sources import Query
    q = Query(keywords=request.args.get("q", ""), country=request.args.get("country", ""))
    import synonyms
    return ok(extra=synonyms.expansion_summary(q.groups), sent=q.search_terms)


# ---------------------------------------------------------------- jobs

def job_filters(src):
    f = {k: src.get(k) for k in ("q", "country", "region", "city", "remote", "source", "status", "sort", "company_key")}
    f["contract"] = src.get("contract") or ""
    f["max_exp"] = int(src.get("max_exp") or 0)
    f["min_match"] = max(0, min(100, int(src.get("min_match") or 0)))
    for k in ("has_email", "has_phone", "has_salary", "include_worldwide", "show_hidden", "has_recruiter", "visa", "hide_closed"):
        f[k] = str(src.get(k, "")).lower() in ("1", "true", "yes", "on")
    f["days"] = int(src.get("days") or 0)
    f["run_id"] = int(src.get("run") or src.get("run_id") or 0)
    return f


@app.route("/api/jobs")
def api_jobs():
    page = max(1, int(request.args.get("page") or 1))
    per = max(10, min(200, int(request.args.get("per") or 50)))
    jobs, total = store.list_jobs(job_filters(request.args), page, per)
    return ok(jobs=jobs, total=total, page=page, pages=max(1, -(-total // per)))


@app.route("/api/jobs/<int:jid>", methods=["GET", "PATCH", "DELETE"])
def api_job(jid):
    if request.method == "DELETE":
        return ok(count=store.delete_jobs([jid]))
    if request.method == "PATCH":
        d = body()
        if "status" in d:
            if d["status"] not in STATUSES:
                raise ApiError("Unknown status")
            store.set_status([jid], status=d["status"])
        if "hidden" in d:
            store.set_status([jid], hidden=bool(d["hidden"]))
        if "notes" in d:
            store.run("UPDATE jobs SET notes = ? WHERE id = ?", (str(d["notes"])[:5000], jid))
    j = store.get_job(jid)
    if j is None:
        raise ApiError("Job not found", 404)
    if request.method == "GET" and not (j.get("match") or {}).get("parts"):
        r = matcher.rescore_one(jid)              # not scored yet (new job / new CV): score it now
        if r:
            j["match_score"], j["match"] = r
    return ok(job=j)


@app.route("/api/jobs/bulk", methods=["POST"])
def api_jobs_bulk():
    d = body()
    ids = [int(i) for i in (d.get("ids") or [])][:5000]
    if d.get("status") in STATUSES:
        store.set_status(ids, status=d["status"])
    if "hidden" in d:
        store.set_status(ids, hidden=bool(d["hidden"]))
    if d.get("delete"):
        return ok(count=store.delete_jobs(ids))
    return ok(count=len(ids))


@app.route("/api/jobs/delete-matching", methods=["POST"])
def api_jobs_delete_matching():
    """'Delete all' on a job list: every job matching the list's current filters (not just the visible page)."""
    ids = store.job_ids_matching(job_filters(body()))
    return ok(count=store.delete_jobs(ids))


EXPORT_COLS = [("Title", "title"), ("Company", "company"), ("Location", "location"), ("Country", "country"), ("Region", "region"),
               ("City", "city"), ("Remote", "remote"), ("Job type", "job_type"), ("Salary min", "salary_min"),
               ("Salary max", "salary_max"), ("Currency", "salary_currency"), ("Salary text", "salary_text"),
               ("Job emails", "emails"), ("Job phones", "phones"), ("Company emails", "c_emails"), ("Company phones", "c_phones"),
               ("Company website", "company_domain"), ("Posted", "posted_at"), ("Found", "first_seen"), ("Status", "status"),
               ("Sources", "sources"), ("Job URL", "url"), ("Apply URL", "apply_url"), ("Description", "description")]


@app.route("/api/export")
def api_export():
    fmt = request.args.get("format", "xlsx")
    f = job_filters(request.args)
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    rows, page = [], 1
    while True:
        chunk, total = store.list_jobs(f, page, 1000)
        rows += chunk
        if len(chunk) < 1000 or len(rows) >= 100000:
            break
        page += 1
    if ids:
        idset = set(ids)
        rows = [r for r in rows if r["id"] in idset]
    full = {r["id"]: dict(r) for r in store.q("SELECT id, description, company_domain FROM jobs WHERE id IN (%s)" % ",".join(str(r["id"]) for r in rows))} if rows else {}
    comps = {r["key"]: r["domain"] for r in store.q("SELECT key, domain FROM companies")}

    def val(r, k):
        if k == "description":
            return (full.get(r["id"]) or {"description": ""})["description"][:32000]
        if k == "company_domain":
            return (full.get(r["id"]) or {}).get("company_domain") or comps.get(r["company_key"], "")
        v = r.get(k)
        if isinstance(v, list):
            return ", ".join(v)
        if k in ("posted_at", "first_seen") and v:
            return time.strftime("%Y-%m-%d", time.localtime(v))
        if k == "remote":
            return "yes" if v else "no"
        return "" if v is None else v

    stamp = time.strftime("%Y%m%d-%H%M")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([c for c, _ in EXPORT_COLS])
        for r in rows:
            w.writerow([val(r, k) for _, k in EXPORT_COLS])
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="jobradar-%s.csv"' % stamp})
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook(write_only=False)
    ws = wb.active
    ws.title = "Jobs"
    ws.append([c for c, _ in EXPORT_COLS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([_xl_safe(val(r, k)) for _, k in EXPORT_COLS])
    widths = [40, 24, 28, 8, 16, 16, 8, 14, 11, 11, 9, 18, 30, 20, 30, 20, 22, 11, 11, 10, 20, 40, 40, 60]
    for i, wdt in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = wdt
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="jobradar-%s.xlsx" % stamp,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _xl_safe(v):
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch in "\t\n\r" or ord(ch) >= 32)
        if v[:1] in ("=", "+", "-", "@"):
            v = "'" + v                  # never let a scraped string become an Excel formula
    return v


# ---------------------------------------------------------------- companies & enrichment

@app.route("/api/companies")
def api_companies():
    page = max(1, int(request.args.get("page") or 1))
    rows, total = store.list_companies(request.args.get("q", ""), request.args.get("has_contact") in ("1", "true"), page, 50)
    return ok(companies=rows, total=total, page=page, pages=max(1, -(-total // 50)))


@app.route("/api/companies/<path:key>", methods=["GET", "PATCH"])
def api_company(key):
    if request.method == "PATCH":
        d = body()
        if "domain" in d:
            dom = extract.domain_of(str(d["domain"]).strip())
            store.run("UPDATE companies SET domain = ? WHERE key = ?", (dom, key))
        if "notes" in d:
            store.run("UPDATE companies SET notes = ? WHERE key = ?", (str(d["notes"])[:5000], key))
    c = enrich.dict_company(key)
    if c is None:
        raise ApiError("Company not found", 404)
    return ok(company=c)


@app.route("/api/companies/delete", methods=["POST"])
def api_companies_delete():
    """Delete companies + their contacts (and, by default, their jobs). keys=[...] or all=true (+ current filters)."""
    d = body()
    keys = store.company_keys_matching(str(d.get("q") or ""), bool(d.get("has_contact"))) if d.get("all") else d.get("keys") or []
    if not keys:
        raise ApiError("Select at least one company.")
    return ok(count=store.delete_companies(keys, with_jobs=d.get("with_jobs", True) is not False))


@app.route("/api/companies/<path:key>/enrich", methods=["POST"])
def api_company_enrich(key):
    c = enrich.enrich_company(key)
    if c is None:
        raise ApiError("Company not found", 404)
    return ok(company=c)


@app.route("/api/enrich/bulk", methods=["POST"])
def api_enrich_bulk():
    d = body()
    keys = d.get("keys") or []
    if d.get("all_missing"):
        keys = [r["key"] for r in store.q("SELECT key FROM companies WHERE enriched_at IS NULL ORDER BY key LIMIT 2000")]
    if d.get("from_jobs"):
        ids = [int(i) for i in d["from_jobs"]][:2000]
        keys = [r["company_key"] for r in store.q("SELECT DISTINCT company_key FROM jobs WHERE id IN (%s) AND company_key != ''" % ",".join(map(str, ids)))] if ids else []
    enrich.BULK.add(list(dict.fromkeys(keys)))
    return ok(queued=len(keys), status=enrich.BULK.status())


@app.route("/api/enrich/status")
def api_enrich_status():
    return ok(status=enrich.BULK.status())


@app.route("/api/enrich/cancel", methods=["POST"])
def api_enrich_cancel():
    enrich.BULK.cancel()
    return ok()


# ---------------------------------------------------------------- people (recruiter finder)

def people_filters(src):
    return {"q": src.get("q", ""), "role": src.get("role", ""), "company_key": src.get("company", ""),
            "country": src.get("country", ""), "has_email": str(src.get("has_email", "")).lower() in ("1", "true")}


@app.route("/api/people")
def api_people():
    page = max(1, int(request.args.get("page") or 1))
    rows, total = store.list_people(people_filters(request.args), page, 50)
    counts = {r["role"]: r["n"] for r in store.q("SELECT role, COUNT(*) AS n FROM people GROUP BY role")}
    return ok(people=rows, total=total, page=page, pages=max(1, -(-total // 50)), counts=counts)


@app.route("/api/people/<int:pid>", methods=["DELETE"])
def api_person_delete(pid):
    return ok(count=store.delete_people([pid]))


@app.route("/api/people/delete", methods=["POST"])
def api_people_delete():
    d = body()
    ids = store.people_ids_matching(people_filters(d)) if d.get("all") else d.get("ids") or []
    if not ids and not d.get("all"):
        raise ApiError("Select at least one person.")
    return ok(count=store.delete_people(ids))


@app.route("/api/export/people")
def api_export_people():
    rows, _ = store.list_people(people_filters(request.args), 1, 100000)
    cols = [("Name", "name"), ("Title", "title"), ("Role", "role"), ("Company", "company"), ("Website", "domain"),
            ("Email", "email"), ("Phone", "phone"), ("LinkedIn", "linkedin"), ("Found on", "source"), ("Source page", "url"),
            ("Open jobs", "jobs_count"), ("Relevance", "score")]
    stamp = time.strftime("%Y%m%d-%H%M")
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([c for c, _ in cols])
        for r in rows:
            w.writerow([_xl_safe(r.get(k, "")) for _, k in cols])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="recruiters-%s.csv"' % stamp})
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Recruiters"
    ws.append([c for c, _ in cols])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for r in rows:
        ws.append([_xl_safe(r.get(k, "")) for _, k in cols])
    for col, wdt in zip("ABCDEFGHIJKL", (24, 34, 12, 26, 22, 30, 18, 36, 14, 40, 10, 10)):
        ws.column_dimensions[col].width = wdt
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name="recruiters-%s.xlsx" % stamp,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- saved searches

@app.route("/api/searches", methods=["GET", "POST"])
def api_searches():
    if request.method == "POST":
        d = body()
        name = str(d.get("name") or "").strip()[:80]
        if not name:
            raise ApiError("Give the search a name")
        sid = store.run("INSERT INTO searches(name, params, every_hours, created_at) VALUES(?,?,?,?)",
                        (name, json.dumps(d.get("params") or {}), max(0, min(168, int(d.get("every_hours") or 0))), store.now()))
        return ok(id=sid)
    rows = [dict(r) for r in store.q("SELECT * FROM searches ORDER BY id DESC")]
    busy = engine.active_search_ids()
    for r in rows:
        r["params"] = json.loads(r["params"])
        r["running"] = r["id"] in busy
    return ok(searches=rows)


@app.route("/api/searches/<int:sid>", methods=["PUT", "DELETE"])
def api_search_edit(sid):
    if request.method == "DELETE":
        store.run("DELETE FROM searches WHERE id = ?", (sid,))
        return ok()
    d = body()
    if "every_hours" in d:
        store.run("UPDATE searches SET every_hours = ? WHERE id = ?", (max(0, min(168, int(d["every_hours"] or 0))), sid))
    if "name" in d and str(d["name"]).strip():
        store.run("UPDATE searches SET name = ? WHERE id = ?", (str(d["name"]).strip()[:80], sid))
    if "params" in d:
        store.run("UPDATE searches SET params = ? WHERE id = ?", (json.dumps(d["params"]), sid))
    return ok()


@app.route("/api/searches/delete-all", methods=["POST"])
def api_searches_delete_all():
    return ok(count=store.clear_table("searches"))


@app.route("/api/searches/<int:sid>/run", methods=["POST"])
def api_search_run(sid):
    s = store.q1("SELECT * FROM searches WHERE id = ?", (sid,))
    if s is None:
        raise ApiError("Search not found", 404)
    p = json.loads(s["params"])
    rid = engine.start_run(p, p.get("sources") or None, search_id=sid)
    return ok(run_id=rid)


@app.route("/api/searches/<int:sid>/seen", methods=["POST"])
def api_search_seen(sid):
    store.run("UPDATE searches SET unseen = 0 WHERE id = ?", (sid,))
    return ok()


# ---------------------------------------------------------------- sources, boards, settings

@app.route("/api/settings", methods=["PUT"])
def api_settings():
    d = body()
    for k, default in engine.DEFAULT_SETTINGS.items():
        if k not in d:
            continue
        v = d[k]
        if k in SECRET_KEYS and v == "••••••••":
            continue
        if isinstance(default, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ApiError("%s must be a number" % k)
        elif isinstance(default, list):
            v = [str(x).strip() for x in (v if isinstance(v, list) else str(v).splitlines()) if str(x).strip()][:500]
        else:
            v = str(v).strip()[:300]
        store.set_setting(k, v)
    return ok(settings=public_settings(), sources=[s.info(engine.settings()) for s in all_sources()])


@app.route("/api/sources/<sid>/test", methods=["POST"])
def api_source_test(sid):
    src = next((s for s in all_sources() if s.id == sid), None)
    if src is None:
        raise ApiError("Unknown source", 404)
    st = engine.settings()
    if not src.ready(st):
        raise ApiError("Missing settings: " + ", ".join(src.needs) if src.needs else "Add at least one website first")
    from sources import Ctx, Query
    stop = threading.Event()
    msgs = []
    ctx = Ctx(st, stop, msgs.append)
    t0 = time.time()
    n, sample = 0, None
    try:
        for raw in src.search(Query(keywords="engineer", max_per_source=20), ctx):
            n += 1
            sample = sample or raw.get("title")
            if n >= 5 or time.time() - t0 > 40:
                stop.set()
                break
    except Exception as e:
        raise ApiError("Test failed: %s" % str(e)[:200])
    return ok(count=n, sample=sample, seconds=round(time.time() - t0, 1))


@app.route("/api/boards", methods=["GET", "POST"])
def api_boards():
    if request.method == "POST":
        d = body()
        text = str(d.get("input") or "").strip()
        if not text:
            raise ApiError("Paste a careers page URL or provider:slug")
        added, found = 0, []
        for line in text.splitlines()[:300]:
            line = line.strip()
            if not line:
                continue
            if ":" in line and not line.startswith("http") and line.split(":")[0] in ats.PROVIDERS:
                prov, slug = line.split(":", 1)
                pairs = [(prov, slug.strip())]
            else:
                pairs = ats.detect(line)
            for prov, slug in pairs:
                found.append("%s:%s" % (prov, slug))
                added += 1 if store.add_board(prov, slug, discovered_from="manual") else 0
            if not pairs and line.startswith("http"):
                sites = engine.settings().get("crawl_sites") or []
                if line not in sites:
                    sites.append(line)
                    store.set_setting("crawl_sites", sites)
                found.append("crawler:" + line)
        return ok(added=added, found=found)
    where, args = ["1=1"], []
    if request.args.get("provider"):
        where.append("provider = ?")
        args.append(request.args["provider"])
    if request.args.get("status"):
        where.append("status = ?")
        args.append(request.args["status"])
    if request.args.get("q"):
        where.append("(slug LIKE ? OR company LIKE ?)")
        args += ["%" + request.args["q"] + "%"] * 2
    rows = store.q("SELECT id, provider, slug, company, status, jobs_count, last_fetch, last_error, discovered_from, created_at "
                   "FROM boards WHERE %s ORDER BY jobs_count DESC, id DESC LIMIT 500" % " AND ".join(where), args)
    summary = [dict(r) for r in store.q("SELECT provider, COUNT(*) AS n, SUM(status='ok') AS ok, SUM(jobs_count) AS jobs FROM boards GROUP BY provider")]
    return ok(boards=[dict(r) for r in rows], summary=summary,
              total=store.q1("SELECT COUNT(*) AS n FROM boards")["n"])


@app.route("/api/boards/<int:bid>", methods=["DELETE"])
def api_board_delete(bid):
    return ok(count=store.delete_boards([bid]))


@app.route("/api/boards/delete", methods=["POST"])
def api_boards_delete():
    """ids=[...] or all=true with the list filters (q, status)."""
    d = body()
    if d.get("all"):
        where, args = ["1=1"], []
        if d.get("status"):
            where.append("status = ?")
            args.append(d["status"])
        if d.get("q"):
            where.append("(slug LIKE ? OR company LIKE ?)")
            args += ["%" + str(d["q"]) + "%"] * 2
        ids = [r["id"] for r in store.q("SELECT id FROM boards WHERE %s" % " AND ".join(where), args)]
    else:
        ids = d.get("ids") or []
    return ok(count=store.delete_boards(ids))


@app.route("/api/boards/revive", methods=["POST"])
def api_boards_revive():
    store.run("UPDATE boards SET status = 'new', fails = 0 WHERE status = 'dead'")
    return ok()


# ---------------------------------------------------------------- applicant profile, CVs, autofill extension

@app.route("/api/profile", methods=["GET", "PUT"])
def api_profile():
    if request.method == "PUT":
        try:
            profile.save(body())
        except ValueError as e:
            raise ApiError(str(e))
        matcher.poke()
    return ok(profile=profile.get(), cvs=profile.cvs(), token=profile.token(),
              extension_dir=os.path.join(app_paths.BASE_DIR, "extension"))


@app.route("/api/profile/cv", methods=["POST"])
def api_profile_cv_upload():
    f = request.files.get("file")
    if f is None:
        raise ApiError("No file received")
    try:
        cid = profile.add_cv(f, request.form.get("label", ""))
    except ValueError as e:
        raise ApiError(str(e))
    matcher.poke()
    return ok(id=cid, cvs=profile.cvs())


@app.route("/api/profile/cv/<cid>", methods=["GET", "PUT", "DELETE"])
def api_profile_cv(cid):
    if request.method == "DELETE":
        profile.delete_cv(cid)
        matcher.poke()
        return ok(cvs=profile.cvs())
    if request.method == "PUT":
        d = body()
        profile.update_cv(cid, d.get("label"), bool(d.get("default")))
        return ok(cvs=profile.cvs())
    path, meta = profile.cv_path(cid)
    if not path:
        raise ApiError("CV not found", 404)
    return send_file(path, mimetype=meta["mime"], as_attachment=True, download_name=meta["name"])


@app.route("/api/profile/token", methods=["POST"])
def api_profile_token():
    return ok(token=profile.new_token())


def _ext_guard():
    if not profile.token_ok(request.headers.get("X-JobRadar-Token")):
        raise ApiError("Pairing code missing or wrong - copy it from JobRadar > My profile into the extension options.", 401)


@app.route("/ext/ping")
def ext_ping():
    _ext_guard()
    p = profile.get()
    return ok(app=app_paths.APP_NAME, name=" ".join(x for x in (p["first_name"], p["last_name"]) if x), cvs=len(profile.cvs()))


@app.route("/ext/profile")
def ext_profile():
    _ext_guard()
    data = profile.public_for_extension()
    data["profile"]["cover_letter"] = profile.fill_template(data["profile"]["cover_letter"], request.args.get("title", ""),
                                                            request.args.get("company", ""))
    data["suggested_cv"] = matcher.best_cv_for_url(request.args.get("url", "")) or ""     # the CV that fits this job best
    return ok(**data)


@app.route("/ext/cv/<cid>")
def ext_cv(cid):
    _ext_guard()
    path, meta = profile.cv_path(cid)
    if not path:
        raise ApiError("CV not found", 404)
    resp = send_file(path, mimetype=meta["mime"], as_attachment=False, download_name=meta["name"])
    resp.headers["X-File-Name"] = meta["name"].encode("ascii", "ignore").decode() or "cv"
    return resp


@app.route("/ext/applied", methods=["POST"])
def ext_applied():
    """The extension reports: 'I applied on this page'. Match the job in JobRadar (or create it) -> Applied."""
    _ext_guard()
    d = body()
    url = str(d.get("url") or "").strip()[:1000]
    if not url.startswith(("http://", "https://")):
        raise ApiError("Invalid page address")
    base = url.split("#")[0].split("?")[0].rstrip("/")
    row = store.q1("SELECT id FROM jobs WHERE url = ? OR apply_url = ? OR url LIKE ? OR apply_url LIKE ? ORDER BY id DESC LIMIT 1",
                   (url, url, base + "%", base + "%"))
    if row is None:
        title = str(d.get("title") or "").strip()[:200] or "Job application"
        job = engine.normalize({"title": title, "company": str(d.get("company") or "")[:120], "location": str(d.get("location") or "")[:120],
                                "url": url, "apply_url": url, "description": str(d.get("description") or "")[:20000]}, "manual")
        jid, _ = store.upsert_job(job, force=True)       # you applied: bring it back even if deleted before
        store.refresh_companies([store.company_key(job["company"])])
    else:
        jid = row["id"]
    cv = next((c for c in profile.cvs() if c["id"] == d.get("cv_id")), None)
    note = "Applied with JobRadar Autofill on %s%s." % (time.strftime("%Y-%m-%d %H:%M"), (" · CV: " + cv["label"]) if cv else "")
    store.run("UPDATE jobs SET status = 'applied', status_at = ?, hidden = 0, notes = TRIM(notes || char(10) || ?) WHERE id = ?",
              (store.now(), note, jid))
    return ok(job_id=jid, created=row is None)


@app.route("/autofill-test")
def autofill_test():
    """A harmless practice application form to try the extension on (nothing is sent anywhere)."""
    return render_template("autofill_test.html", v=ASSET_V)


# ---------------------------------------------------------------- CV checker + match score

def _cv_or_default(cid):
    cvs = profile.cvs()
    if not cvs:
        raise ApiError("Add your CV in My profile first", 404)
    cv = next((c for c in cvs if c["id"] == cid), None) or next((c for c in cvs if c.get("default")), cvs[0])
    path, _ = profile.cv_path(cv["id"])
    if not path:
        raise ApiError("CV file missing - upload it again", 404)
    return cv, path


@app.route("/api/cv/check")
def api_cv_check():
    cv, path = _cv_or_default(request.args.get("cv", ""))
    res = cvcheck.full_check(cv, path, profile.get(), force=request.args.get("force") == "1")
    return ok(result=res, cvs=profile.cvs())


@app.route("/api/match/status")
def api_match_status():
    m = matcher.me()
    return ok(state=matcher.STATE, ready=bool(m), dist=matcher.distribution(), alert_min=int(store.get_setting("match_alert_min", 75) or 0),
              me={"skills": m["skills"][:60], "years": m["years"], "languages": m["languages"], "education": m["education"],
                  "targets": m["targets"], "country": m["country"], "cvs": [{"id": c["id"], "label": c["label"], "skills": len(c["skills"])} for c in m["cvs"]]}
              if m else None)


@app.route("/api/match/gap")
def api_match_gap():
    return ok(gap=matcher.skill_gap())


@app.route("/api/match/rescore", methods=["POST"])
def api_match_rescore():
    store.run("UPDATE jobs SET match_ver = NULL")
    matcher.poke()
    return ok()


# ---------------------------------------------------------------- hiring signals + watchlist

@app.route("/api/signals")
def api_signals():
    m = matcher.me() or {}
    page = max(1, int(request.args.get("page") or 1))
    rows, total = signals.hot_companies(m.get("country", ""), m.get("families"), country=(request.args.get("country") or "").upper(),
                                        field_only=request.args.get("field") == "1", has_contact=request.args.get("contact") == "1",
                                        min_heat=int(request.args.get("min") or 1), q=request.args.get("q", ""),
                                        watched=request.args.get("watched") == "1", limit=40, offset=(page - 1) * 40)
    return ok(companies=rows, total=total, page=page, pages=max(1, -(-total // 40)),
              summary=signals.summary(m.get("country", ""), m.get("families")), my_country=m.get("country", ""))


@app.route("/api/companies/<path:key>/watch", methods=["POST"])
def api_company_watch(key):
    store.run("UPDATE companies SET watch = ? WHERE key = ?", (1 if body().get("watch") else 0, key))
    return ok()


# ---------------------------------------------------------------- spontaneous applications

@app.route("/api/outreach/candidates")
def api_outreach_candidates():
    rows, total = outreach.candidates(country=(request.args.get("country") or "").upper(), city=request.args.get("city", ""),
                                      q=request.args.get("q", ""), field_only=request.args.get("field") == "1",
                                      min_heat=int(request.args.get("min_heat") or 0), include_general=request.args.get("general", "1") == "1",
                                      limit=int(request.args.get("limit") or 100))
    return ok(companies=rows, total=total)


@app.route("/api/outreach/leadfinder")
def api_outreach_leadfinder():
    return ok(**outreach.leadfinder_search((request.args.get("country") or "").upper(), request.args.get("city", ""), request.args.get("q", ""),
                                            int(request.args.get("limit") or 200)))


@app.route("/api/outreach/leadfinder/import", methods=["POST"])
def api_outreach_leadfinder_import():
    d = body()
    n = outreach.import_leads(d.get("ids") or [])
    made = 0
    if d.get("draft"):
        path = outreach.leadfinder_db()
        keys = []
        if path and d.get("ids"):
            import sqlite3
            c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
            ids = [int(i) for i in d["ids"]][:2000]
            keys = [store.company_key(r[0]) for r in c.execute("SELECT name FROM leads WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)]
            c.close()
        made = outreach.create_drafts([{"key": k} for k in keys], d.get("lang", ""), d.get("cv_id", ""))
    return ok(imported=n, drafts=made)


@app.route("/api/outreach/drafts", methods=["POST"])
def api_outreach_drafts():
    d = body()
    made = outreach.create_drafts(d.get("items") or [], d.get("lang", ""), d.get("cv_id", ""))
    return ok(created=made)


@app.route("/api/outreach")
def api_outreach_list():
    page = max(1, int(request.args.get("page") or 1))
    rows, total, counts, kinds = outreach.listing(request.args.get("status", ""), request.args.get("q", ""), page, 50)
    return ok(items=rows, total=total, page=page, pages=max(1, -(-total // 50)), counts=counts, kinds=kinds, stats=outreach.stats())


@app.route("/api/outreach/<int:oid>", methods=["PUT", "DELETE"])
def api_outreach_item(oid):
    if request.method == "DELETE":
        outreach.bulk([oid], "delete")
        return ok()
    try:
        return ok(item=outreach.update(oid, body()))
    except ValueError as e:
        raise ApiError(str(e))


@app.route("/api/outreach/bulk", methods=["POST"])
def api_outreach_bulk():
    d = body()
    if d.get("action") not in ("approve", "cancel", "delete", "draft"):
        raise ApiError("Unknown action")
    return ok(count=outreach.bulk(d.get("ids") or [], d["action"]))


@app.route("/api/outreach/delete", methods=["POST"])
def api_outreach_delete():
    """ids=[...] or all=true for one tab: status 'active' (drafts/approved/failed) or 'done' (sent & replies)."""
    d = body()
    if d.get("all"):
        groups = {"active": ("draft", "queued", "failed", "cancelled"), "done": ("sent", "replied", "bounced")}
        st = groups.get(d.get("status"))
        if not st:
            raise ApiError("Choose which list to empty.")
        with store.tx() as c:
            n = c.execute("DELETE FROM outreach WHERE status IN (%s)" % ",".join("?" * len(st)), st).rowcount
            c.execute("UPDATE outreach SET parent_id = NULL WHERE parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM outreach)")
        return ok(count=n)
    ids = d.get("ids") or []
    if not ids:
        raise ApiError("Select at least one email.")
    return ok(count=outreach.bulk(ids, "delete"))


@app.route("/api/outreach/templates", methods=["GET", "PUT"])
def api_outreach_templates():
    if request.method == "PUT":
        return ok(templates=outreach.save_templates(body()))
    return ok(templates=outreach.templates(), defaults=outreach.DEFAULT_TEMPLATES,
              placeholders=["{greeting}", "{company}", "{my_name}", "{my_title}", "{my_title_a}", "{my_skills}", "{years}", "{my_phone}",
                            "{my_email}", "{my_linkedin}", "{city}"])


@app.route("/api/outreach/status")
def api_outreach_status():
    st = outreach.settings()
    return ok(sender=outreach.SENDER, stats=outreach.stats(), sent_today=outreach.sent_today(),
              config={k: st[k] for k in ("host", "port", "user", "daily", "gap", "window", "weekdays", "followup_days", "paused", "attach_cv")},
              has_password=bool(st["password"]), leadfinder=bool(outreach.leadfinder_db()), mailblaster=bool(outreach.mailblaster_db()))


@app.route("/api/outreach/test", methods=["POST"])
def api_outreach_test():
    try:
        outreach.test_smtp()
    except ValueError as e:
        raise ApiError(str(e))
    except Exception as e:
        raise ApiError("Login failed: %s" % str(e)[:200])
    return ok()


@app.route("/api/outreach/preview/<int:oid>")
def api_outreach_preview(oid):
    row = store.q1("SELECT * FROM outreach WHERE id = ?", (oid,))
    if row is None:
        raise ApiError("Not found", 404)
    st = outreach.settings()
    st["user"] = st["user"] or "you@example.com"
    msg, _ = outreach.build_message(dict(row), st)
    atts = [{"name": a.get_filename(), "size": len(a.get_payload(decode=True) or b"")} for a in msg.iter_attachments()]
    return ok(headers={k: msg[k] for k in ("From", "To", "Subject")}, body=row["body"], attachments=atts)


@app.route("/api/outreach/check-replies", methods=["POST"])
def api_outreach_check_replies():
    st = outreach.settings()
    if not (st["imap_user"] and st["imap_password"]):
        raise ApiError("Connect your mailbox first (Alerts & inbox or Outreach settings)")
    try:
        n = outreach.check_replies(st)
    except Exception as e:
        raise ApiError("Couldn't read your inbox: %s" % str(e)[:200])
    return ok(found=n)


@app.route("/api/outreach/mailblaster", methods=["POST"])
def api_outreach_mailblaster():
    d = body()
    try:
        return ok(**outreach.export_mailblaster([int(i) for i in d.get("ids") or []][:2000], d.get("group", "")))
    except ValueError as e:
        raise ApiError(str(e))


@app.route("/api/outreach/wake", methods=["POST"])
def api_outreach_wake():
    outreach.poke()
    return ok()


# ---------------------------------------------------------------- night deep scan

@app.route("/api/night")
def api_night():
    return ok(config=nightly.cfg(), running=nightly.running(), stages=nightly.STAGES, history=nightly.history(8),
              wake=nightly.wake_task_status())


@app.route("/api/night/run", methods=["POST"])
def api_night_run():
    return ok(run_id=nightly.start("manual"))


@app.route("/api/night/stop", methods=["POST"])
def api_night_stop():
    nightly.stop()
    return ok()


@app.route("/api/night/<int:nid>", methods=["DELETE"])
def api_night_delete(nid):
    if nightly.running() and nightly.STATE.get("run_id") == nid:
        raise ApiError("This scan is running - stop it first.")
    store.run("DELETE FROM night_runs WHERE id = ?", (nid,))
    return ok()


@app.route("/api/night/delete-all", methods=["POST"])
def api_night_delete_all():
    keep = nightly.STATE.get("run_id") if nightly.running() else 0
    with store.tx() as c:
        n = c.execute("DELETE FROM night_runs WHERE id != ?", (keep or 0,)).rowcount
    return ok(count=n)


@app.route("/api/night/seen", methods=["POST"])
def api_night_seen():
    store.run("UPDATE night_runs SET seen = 1")
    return ok()


@app.route("/api/night/wake", methods=["POST"])
def api_night_wake():
    try:
        if body().get("on"):
            nightly.install_wake_task()
        else:
            nightly.remove_wake_task()
    except ValueError as e:
        raise ApiError(str(e))
    return ok(wake=nightly.wake_task_status())


# ---------------------------------------------------------------- alerts, notifications, backup

@app.route("/api/alerts/import", methods=["POST"])
def api_alerts_import():
    started = alerts.run_import()
    return ok(started=started, state=alerts.STATE)


@app.route("/api/alerts/status")
def api_alerts_status():
    return ok(state=alerts.STATE)


@app.route("/api/notifications", methods=["DELETE"])
def api_notifications_clear():
    return ok(count=store.clear_table("notifications"))


@app.route("/api/notifications/<int:nid>", methods=["DELETE"])
def api_notification_delete(nid):
    store.run("DELETE FROM notifications WHERE id = ?", (nid,))
    return ok()


@app.route("/api/notifications", methods=["GET", "POST"])
def api_notifications():
    if request.method == "POST":
        store.run("UPDATE notifications SET read = 1")
        return ok()
    rows = store.q("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")
    return ok(notifications=[dict(r) for r in rows])


@app.route("/api/backup")
def api_backup():
    path = store.backup()
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/api/health")
@app.route("/api/ping")
def health():
    return ok(app=app_paths.APP_NAME, version=app_paths.APP_VERSION)


DATA_KINDS = {
    "jobs": "every job (the pipeline included)",
    "runs": "search history",
    "companies": "companies and the contacts found for them",
    "people": "recruiters and other people found",
    "searches": "saved searches / alerts",
    "outreach": "spontaneous applications (drafts, sent emails, replies)",
    "night": "night scan reports",
    "notifications": "notifications",
    "signals": "hiring-signal history",
    "cache": "downloaded page and career-board cache",
    "cvs": "CV files",
    "profile": "your profile details",
}


@app.route("/api/data/clear", methods=["POST"])
def api_data_clear():
    """Danger zone. what = one of DATA_KINDS or 'everything'; needs confirm='DELETE'."""
    d = body()
    if d.get("confirm") != "DELETE":
        raise ApiError("Type DELETE to confirm.")
    what = d.get("what")
    kinds = list(DATA_KINDS) if what == "everything" else [what]
    if any(k not in DATA_KINDS for k in kinds):
        raise ApiError("Unknown data type.")
    if engine.RUNS and any(k in ("jobs", "runs") for k in kinds):
        raise ApiError("A search is running - stop it first.")
    if nightly.running() and any(k in ("night", "jobs") for k in kinds):
        raise ApiError("The night scan is running - stop it first.")
    n = 0
    for k in kinds:
        if k == "jobs":
            n += store.delete_all_jobs()
        elif k == "runs":
            n += store.delete_runs([r["id"] for r in store.q("SELECT id FROM runs")])
        elif k == "companies":
            n += store.delete_companies([r["key"] for r in store.q("SELECT key FROM companies")], with_jobs=False)
        elif k == "people":
            n += store.clear_table("people")
        elif k == "searches":
            n += store.clear_table("searches")
        elif k == "outreach":
            n += store.clear_table("outreach")
        elif k == "night":
            n += store.clear_table("night_runs")
        elif k == "notifications":
            n += store.clear_table("notifications")
        elif k == "signals":
            n += store.clear_table("postings")
            store.run("UPDATE boards SET snapshots = 0, tracked_since = NULL")
            store.run("UPDATE companies SET watch = 0")
        elif k == "cache":
            n += store.clear_table("pages")
            store.run("UPDATE boards SET cache = NULL, last_fetch = NULL")
        elif k == "cvs":
            for c in profile.cvs():
                profile.delete_cv(c["id"])
                n += 1
        elif k == "profile":
            store.set_setting("profile", {})
            n += 1
    if "cvs" in kinds or "profile" in kinds:
        matcher.poke()
    return ok(count=n)


# ---------------------------------------------------------------- startup

def boot():
    try:
        if app_paths.migrate_legacy_data():
            log.info("imported data from the previous JobRadar folder")
    except Exception:
        log.exception("data migration")
    store.init()
    if not store.q1("SELECT 1 FROM boards LIMIT 1"):
        engine.seed_boards(os.path.join(app_paths.BASE_DIR, "seed_boards.json"))
    # A run still marked 'running' at startup was cut off (crash, shutdown, closed app): it can be resumed.
    store.run("UPDATE runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'", (store.now(),))


DEFAULT_PORT = 5110          # 5090 is ClientGuard's - every app of the family has its own port
PORT_FILE = os.path.join(app_paths.DATA_DIR, "port.txt")


def _port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _is_jobradar(port):
    """True only if the program answering on this port really is JobRadar (not ClientGuard or another app)."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == app_paths.APP_NAME
    except Exception:
        return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout) if sys.stdout else logging.NullHandler(),
                                  logging.FileHandler(os.path.join(app_paths.DATA_DIR, "jobradar.log"), encoding="utf-8")])
    background = "--background" in sys.argv          # started by the night-scan wake task: no browser, quiet exit if running
    want_browser = "--open" in sys.argv or os.environ.get("JOBRADAR_OPEN_BROWSER") == "1"
    fixed = os.environ.get("JOBRADAR_PORT")
    port = int(fixed or DEFAULT_PORT)
    candidates = [port]
    try:
        last = int(open(PORT_FILE, encoding="utf-8").read().strip())
        if not fixed and last != port:
            candidates.append(last)
    except (OSError, ValueError):
        pass
    for p in candidates:                              # second click on the icon: just show the open copy
        if not _port_free(p) and _is_jobradar(p):
            if not background:
                webbrowser.open("http://127.0.0.1:%d/" % p)
            return
    if not _port_free(port):
        if fixed:
            print("Port %d is used by another program." % port)
            return
        port = next((p for p in range(DEFAULT_PORT + 1, DEFAULT_PORT + 60) if _port_free(p)), port)
    try:
        with open(PORT_FILE, "w", encoding="utf-8") as f:
            f.write(str(port))
    except OSError:
        pass
    boot()
    engine.start_scheduler()
    engine.backfill_insights()
    matcher.start()
    outreach.start()
    nightly.start_scheduler()
    resumed = engine.auto_resume()
    if resumed:
        log.info("resumed interrupted searches: %s", resumed)
    try:
        store.backup()
    except Exception:
        pass
    url = "http://127.0.0.1:%d/" % port
    print("\n  JobRadar %s  ->  %s\n  Data: %s\n" % (app_paths.APP_VERSION, url, app_paths.DATA_DIR))
    if want_browser and not background:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    from waitress import serve
    serve(app, host="127.0.0.1", port=port, threads=24, channel_timeout=120, ident="JobRadar")


if __name__ == "__main__":
    main()
else:
    boot()          # imported (tests): ready to use without the startup checks

"""Night deep scan - JobRadar works while you sleep.

Every night at your chosen time (or as soon as JobRadar runs again if the PC was off - "catch-up"), it runs:
  1. every saved search (or your target role if you have none)
  2. a full refresh of every company career board (feeds hiring signals + watched companies)
  3. imports your job-alert emails
  4. finds recruiters & contacts for the best new companies
  5. checks that the jobs in your pipeline are still open
  6. scores every job against your CV
  7. checks replies to your spontaneous applications
  8. backs up your database
and leaves a morning report: new jobs, top matches, companies heating up, new recruiters, replies.
While it runs, Windows is asked not to fall asleep. Optionally a Windows scheduled task wakes the PC and starts
JobRadar at night (you enable it with one click; it can be removed the same way)."""
import concurrent.futures as cf
import ctypes
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta

import app_paths
import geo
import store

log = logging.getLogger("jobradar.night")
TASK_NAME = "JobRadar Night Scan"
STAGES = [("searches", "Run saved searches"), ("boards", "Refresh company career boards"), ("alerts", "Import job-alert emails"),
          ("enrich", "Find recruiters for top companies"), ("links", "Check pipeline jobs are still open"), ("matches", "Score jobs against your CV"),
          ("replies", "Check replies to your applications"), ("backup", "Back up your data")]
STATE = {"running": False, "run_id": None, "stage": "", "stop": threading.Event()}
_lock = threading.Lock()


def cfg():
    import engine
    s = engine.settings()
    tasks = s.get("night_tasks") or [k for k, _ in STAGES]
    return {"enabled": int(s.get("night_enabled") or 0), "time": s.get("night_time") or "02:00", "catchup": int(s.get("night_catchup") or 0),
            "tasks": [t for t in tasks if t in dict(STAGES)], "enrich_max": max(0, min(300, int(s.get("night_enrich_max") or 40))),
            "keep_awake": int(s.get("night_keep_awake") if s.get("night_keep_awake") is not None else 1)}


# ---------------------------------------------------------------- keep Windows awake while scanning

def _keep_awake(on):
    if os.name != "nt":
        return
    try:
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_AWAYMODE_REQUIRED = 0x80000000, 0x00000001, 0x00000040
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED if on else ES_CONTINUOUS
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


# ---------------------------------------------------------------- the run

def running():
    return STATE["running"]


def start(trigger="manual"):
    with _lock:
        if STATE["running"]:
            return STATE["run_id"]
        STATE["stop"] = threading.Event()
        c = cfg()
        stages = [{"id": k, "name": n, "status": "queued" if k in c["tasks"] else "skipped", "message": "", "count": 0} for k, n in STAGES]
        rid = store.run("INSERT INTO night_runs(started_at, trigger, stages) VALUES(?,?,?)", (store.now(), trigger, json.dumps(stages)))
        STATE.update(running=True, run_id=rid, stage="")
    threading.Thread(target=_run, args=(rid, stages, c), daemon=True, name="night").start()
    return rid


def stop():
    STATE["stop"].set()
    import engine
    for r in list(engine.RUNS.values()):
        if getattr(r, "night", False):
            r.stop.set()


def _save(rid, stages, status=None, report=None):
    sets, args = ["stages = ?"], [json.dumps(stages)]
    if status:
        sets.append("status = ?")
        args.append(status)
        if status != "running":
            sets.append("finished_at = ?")
            args.append(store.now())
    if report is not None:
        sets.append("report = ?")
        args.append(json.dumps(report, ensure_ascii=False))
    store.run("UPDATE night_runs SET %s WHERE id = ?" % ", ".join(sets), args + [rid])


def _run(rid, stages, c):
    t0 = store.now()
    if c["keep_awake"]:
        _keep_awake(True)
    try:
        for st in stages:
            if st["status"] == "skipped":
                continue
            if STATE["stop"].is_set():
                st["status"] = "stopped"
                continue
            STATE["stage"] = st["id"]
            st.update(status="running", started=store.now())
            _save(rid, stages)

            def report(msg, count=None):
                st["message"] = msg
                if count is not None:
                    st["count"] = count
                _save(rid, stages)
            try:
                RUNNERS[st["id"]](report, c)
                st["status"] = "stopped" if STATE["stop"].is_set() else "done"
            except Exception as e:
                log.exception("night stage %s", st["id"])
                st.update(status="error", message=str(e)[:200])
            st["finished"] = store.now()
            _save(rid, stages)
        rep = morning_report(t0)
        status = "stopped" if STATE["stop"].is_set() else "done"
        _save(rid, stages, status, rep)
        if status == "done":
            store.notify(rep["headline"], "#/night")
    except Exception:
        log.exception("night run")
        _save(rid, stages, "error")
    finally:
        _keep_awake(False)
        STATE.update(running=False, stage="")


# ---------------------------------------------------------------- stages

def _wait_run(rid, report, label):
    import engine
    while rid in engine.RUNS:
        if STATE["stop"].is_set():
            engine.stop_run(rid)
        r = store.q1("SELECT found, new FROM runs WHERE id = ?", (rid,))
        report("%s · %d matches, %d new" % (label, r["found"], r["new"]))
        time.sleep(3)
    r = store.q1("SELECT found, new FROM runs WHERE id = ?", (rid,))
    return (r["found"], r["new"]) if r else (0, 0)


def stage_searches(report, c):
    import applicant
    import engine
    searches = [dict(r) for r in store.q("SELECT * FROM searches ORDER BY id")]
    jobs = []
    for s in searches:
        jobs.append((s["name"], json.loads(s["params"] or "{}"), s["id"]))
    if not jobs:
        p = applicant.get()
        target = (p.get("target_titles") or p.get("current_title") or "").strip()
        if target:
            import cvcheck
            jobs.append(("Your target role: " + target, {"keywords": target, "country": cvcheck.geo_code(p.get("country", "")),
                                                          "multilingual": True, "max_per_source": 1000}, None))
    if not jobs:
        report("No saved searches and no target role in your profile - nothing to search", 0)
        return
    total_new = 0
    for i, (name, params, sid) in enumerate(jobs):
        if STATE["stop"].is_set():
            break
        waited = 0
        while sid and sid in engine.active_search_ids() and waited < 3600:
            time.sleep(5)                         # this saved search is already running (scheduler / you): let it finish
            waited += 5
        rid = engine.start_run(params, params.get("sources") or None, search_id=sid)
        r = engine.RUNS.get(rid)
        if r is not None:
            r.night = True
        found, new = _wait_run(rid, lambda m, n=name, k=i: report("%d/%d · %s · %s" % (k + 1, len(jobs), n, m)), name)
        total_new += new
        if sid:
            store.run("UPDATE searches SET last_run = ? WHERE id = ?", (store.now(), sid))
    report("%d search%s · %d new jobs" % (len(jobs), "es" if len(jobs) != 1 else "", total_new), total_new)


def stage_boards(report, c):
    import engine
    from sources import ats
    st = engine.settings()
    boards = [dict(b) for b in store.q("SELECT id, provider, slug, company, fails FROM boards WHERE status != 'dead' ORDER BY jobs_count DESC")]
    workers = max(2, min(12, int(st.get("board_workers") or 8)))
    done = errors = postings = 0
    stop = STATE["stop"]
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(ats.load_board, b, stop, 18 * 3600): b for b in boards}
        for fut in cf.as_completed(futs):
            if stop.is_set():
                for f in futs:
                    f.cancel()
                break
            done += 1
            try:
                jobs, _ = fut.result()
                postings += len(jobs)
            except Exception:
                errors += 1
            if done % 5 == 0 or done == len(boards):
                report("%d/%d companies · %d open jobs%s" % (done, len(boards), postings, (" · %d unreachable" % errors) if errors else ""), done)


def stage_alerts(report, c):
    import alerts
    import engine
    st = engine.settings()
    if not (st.get("imap_user") and st.get("imap_password")):
        report("No mailbox connected (Alerts & inbox) - skipped", 0)
        return
    if alerts.run_import():
        while alerts.STATE["running"]:
            report(alerts.STATE.get("message") or "Reading alert emails…")
            time.sleep(2)
    report(alerts.STATE.get("error") or alerts.STATE.get("message") or "Done", alerts.STATE.get("new", 0))


def stage_enrich(report, c):
    import enrich
    import signals
    import matcher
    limit = c["enrich_max"]
    if not limit:
        report("Disabled", 0)
        return
    m = matcher.me()
    keys = [r["company_key"] for r in store.q(
        "SELECT j.company_key, MAX(COALESCE(j.match_score, 0)) AS best FROM jobs j JOIN companies c ON c.key = j.company_key "
        "WHERE c.enriched_at IS NULL AND j.company_key != '' AND j.hidden = 0 GROUP BY j.company_key ORDER BY best DESC, MAX(j.first_seen) DESC LIMIT ?",
        (limit,))]
    if len(keys) < limit:
        sig = signals.compute((m or {}).get("country", ""), (m or {}).get("families"))
        hot = [k for k, s in sorted(sig.items(), key=lambda x: -x[1]["heat"]) if s["heat"] >= 25]
        todo = {r["key"] for r in store.q("SELECT key FROM companies WHERE enriched_at IS NULL")}
        keys += [k for k in hot if k in todo and k not in keys][: limit - len(keys)]
    people0 = store.q1("SELECT COUNT(*) AS n FROM people")["n"]
    for i, k in enumerate(keys):
        if STATE["stop"].is_set():
            break
        report("%d/%d · %s" % (i + 1, len(keys), k), i)
        try:
            enrich.enrich_company(k, STATE["stop"])
        except Exception as e:
            log.info("enrich %s: %s", k, e)
    found = store.q1("SELECT COUNT(*) AS n FROM people")["n"] - people0
    report("%d companies scanned · %d new people found" % (len(keys), max(0, found)), max(0, found))


CLOSED_TEXT = ("no longer accepting applications", "this job is no longer available", "position has been filled", "job has expired",
               "offre n'est plus disponible", "offre expirée", "cette offre a expiré", "annonce n'est plus", "stelle ist nicht mehr",
               "nicht mehr verfügbar", "ya no está disponible", "job not found", "posting has closed", "this position is closed")


def stage_links(report, c):
    from net import FetchError, fetch
    rows = store.q("SELECT id, url, sources FROM jobs WHERE status IN ('saved','applied') AND closed_at IS NULL AND url != '' "
                   "ORDER BY status_at DESC LIMIT 200")
    closed = checked = 0
    for r in rows:
        if STATE["stop"].is_set():
            break
        src = r["sources"] or ""
        if "-alert" in src or any(x in (r["url"] or "") for x in ("linkedin.", "indeed.", "glassdoor.")):
            continue                          # never visit those sites automatically
        checked += 1
        gone = False
        try:
            resp = fetch(r["url"], expect="response", timeout=20, retries=1, check_robots=True)
            low = resp.text[:200000].lower() if "html" in (resp.headers.get("content-type") or "") else ""
            gone = any(t in low for t in CLOSED_TEXT)
        except FetchError as e:
            gone = e.status in (404, 410)
        except Exception:
            gone = False
        if gone:
            closed += 1
            store.run("UPDATE jobs SET closed_at = ?, notes = TRIM(notes || char(10) || ?) WHERE id = ?",
                      (store.now(), "Job closed (checked by the night scan on %s)." % time.strftime("%Y-%m-%d"), r["id"]))
        report("%d checked · %d closed" % (checked, closed), closed)
    report("%d checked · %d closed" % (checked, closed), closed)


def stage_matches(report, c):
    import matcher
    if not matcher.me():
        report("Add a CV in My profile to get match scores", 0)
        return
    matcher._run_once()
    d = matcher.distribution()
    report("%d jobs scored · %d top matches (75%%+)" % (d["scored"], d["top"]), d["top"])


def stage_replies(report, c):
    import outreach
    st = outreach.settings()
    if not (st["imap_user"] and st["imap_password"]):
        report("No mailbox connected - skipped", 0)
        return
    n = outreach.check_replies(st)
    outreach.make_followups(st)
    report("%d new repl%s" % (n, "ies" if n != 1 else "y"), n)


def stage_backup(report, c):
    path = store.backup()
    report("Saved " + os.path.basename(path), 1)


RUNNERS = {"searches": stage_searches, "boards": stage_boards, "alerts": stage_alerts, "enrich": stage_enrich, "links": stage_links,
           "matches": stage_matches, "replies": stage_replies, "backup": stage_backup}


# ---------------------------------------------------------------- morning report

def morning_report(since):
    import matcher
    import signals
    alert_min = int(store.get_setting("match_alert_min", 75) or 75)
    new_jobs = store.q1("SELECT COUNT(*) AS n FROM jobs WHERE first_seen >= ?", (since,))["n"]
    top = [dict(r) for r in store.q("SELECT id, title, company, country, city, match_score FROM jobs WHERE first_seen >= ? AND match_score >= ? "
                                    "AND hidden = 0 ORDER BY match_score DESC LIMIT 10", (since, alert_min))]
    top_n = store.q1("SELECT COUNT(*) AS n FROM jobs WHERE first_seen >= ? AND match_score >= ? AND hidden = 0", (since, alert_min))["n"]
    m = matcher.me() or {}
    hot, _ = signals.hot_companies(m.get("country", ""), m.get("families"), min_heat=30, limit=5)
    people = store.q1("SELECT COUNT(*) AS n FROM people WHERE found_at >= ?", (since,))["n"]
    replies = [dict(r) for r in store.q("SELECT company, reply_kind FROM outreach WHERE reply_at >= ? ORDER BY reply_at DESC LIMIT 10", (since - 86400,))]
    closed = store.q1("SELECT COUNT(*) AS n FROM jobs WHERE closed_at >= ?", (since,))["n"]
    followups = store.q1("SELECT COUNT(*) AS n FROM outreach WHERE kind = 'followup' AND status = 'draft'")["n"]
    parts = ["%d new jobs" % new_jobs]
    if top_n:
        parts.append("%d top matches" % top_n)
    if hot:
        parts.append("%d compan%s heating up" % (len(hot), "ies" if len(hot) != 1 else "y"))
    if replies:
        parts.append("%d repl%s" % (len(replies), "ies" if len(replies) != 1 else "y"))
    for c in top:
        c["flag"] = geo.flag(c["country"])
    return {"headline": "☀️ Good morning - " + " · ".join(parts), "new_jobs": new_jobs, "top_matches": top, "top_count": top_n,
            "alert_min": alert_min, "hot": [{"key": h["key"], "name": h["name"], "heat": h["heat"], "reasons": [r[1] for r in h["signal"]["reasons"][:2]]} for h in hot],
            "people": people, "replies": replies, "closed": closed, "followups": followups}


def history(limit=10):
    rows = store.q("SELECT * FROM night_runs ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["stages"] = json.loads(d["stages"] or "[]")
        d["report"] = json.loads(d["report"] or "{}")
        out.append(d)
    return out


# ---------------------------------------------------------------- scheduler

def _due(c, now=None):
    now = now or datetime.now()
    last = store.q1("SELECT MAX(started_at) AS t FROM night_runs WHERE trigger != 'manual'")["t"] or 0
    try:
        hh, mm = [int(x) for x in c["time"].split(":")]
    except ValueError:
        hh, mm = 2, 0
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    in_window = now - slot < timedelta(hours=4)
    if in_window and last < slot.timestamp() - 60:
        return "schedule"
    last_any = store.q1("SELECT MAX(started_at) AS t FROM night_runs WHERE status = 'done'")["t"] or 0
    if c["catchup"] and last < slot.timestamp() - 60 and time.time() - last_any > 20 * 3600 and last_any:
        return "catch-up"                      # the PC was off at night: run now, once
    return None


def _loop():
    time.sleep(90)
    while True:
        try:
            c = cfg()
            if c["enabled"] and not STATE["running"]:
                why = _due(c)
                if why:
                    log.info("night scan starting (%s)", why)
                    start(why)
        except Exception:
            log.exception("night scheduler")
        time.sleep(60)


def start_scheduler():
    threading.Thread(target=_loop, daemon=True, name="night-scheduler").start()


# ---------------------------------------------------------------- Windows: wake the PC + start JobRadar at night

def _pythonw():
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.exists(w) else exe


def wake_task_status():
    if os.name != "nt":
        return {"supported": False}
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"supported": True, "installed": r.returncode == 0}
    except Exception as e:
        return {"supported": True, "installed": False, "error": str(e)[:120]}


def install_wake_task():
    """Create a Windows scheduled task: wake the PC 10 minutes before the night scan and start JobRadar (hidden)."""
    if os.name != "nt":
        raise ValueError("Only available on Windows")
    c = cfg()
    try:
        hh, mm = [int(x) for x in c["time"].split(":")]
    except ValueError:
        hh, mm = 2, 0
    at = (datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0) - timedelta(minutes=10))
    start_boundary = at.strftime("%Y-%m-%dT%H:%M:%S")
    server = os.path.join(app_paths.BASE_DIR, "server.py")
    xml = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Wakes the PC and starts JobRadar for its night deep scan (created from JobRadar &gt; Night scan).</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>%s</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Enabled>true</Enabled><AllowStartOnDemand>true</AllowStartOnDemand>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
  </Settings>
  <Actions Context="Author"><Exec><Command>%s</Command><Arguments>"%s" --background</Arguments><WorkingDirectory>%s</WorkingDirectory></Exec></Actions>
</Task>""" % (start_boundary, _xml(_pythonw()), _xml(server), _xml(app_paths.BASE_DIR))
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    with open(path, "w", encoding="utf-16") as f:
        f.write(xml)
    try:
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    finally:
        os.remove(path)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout or "schtasks failed").strip()[:300])
    return True


def remove_wake_task():
    if os.name != "nt":
        return False
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

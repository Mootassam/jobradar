"""Search engine: runs all sources in parallel, normalizes, filters, de-duplicates, stores, reports live progress,
and runs saved searches on schedule."""
import html
import json
import re
import logging
import threading
import time
import traceback

import extract
import geo
import insights
import recruiters
import net
import synonyms
import store
from sources import Ctx, Query, all_sources, ats

log = logging.getLogger("jobradar.engine")

DEFAULT_SETTINGS = {
    "board_cache_hours": 6, "board_workers": 8, "crawl_pages": 40, "crawl_sites": [],
    "adzuna_app_id": "", "adzuna_app_key": "", "jooble_key": "", "usajobs_key": "", "usajobs_email": "",
    "careerjet_affid": "", "reliefweb_appname": "", "auto_resume": 1,
    "disabled_sources": [], "imap_host": "imap.gmail.com", "imap_user": "", "imap_password": "", "imap_folder": "INBOX",
    "imap_days": 14,
    # CV match
    "match_alert_min": 75,
    # spontaneous applications (sending from your own mailbox)
    "smtp_host": "", "smtp_port": 465, "smtp_user": "", "smtp_password": "", "outreach_daily_limit": 15, "outreach_gap_min": 4,
    "outreach_window": "09:00-18:00", "outreach_weekdays": 1, "outreach_followup_days": 7, "outreach_paused": 0, "outreach_attach_cv": 1,
    "leadfinder_db": "", "mailblaster_db": "",
    # night deep scan
    "night_enabled": 1, "night_time": "02:00", "night_catchup": 1, "night_keep_awake": 1, "night_enrich_max": 40,
    "night_tasks": ["searches", "boards", "alerts", "enrich", "links", "matches", "replies", "backup"],
}

EU = set(geo.AREA_COUNTRIES["eu"]) | {"GB", "CH", "NO", "IS", "UA", "RS", "BA", "AL", "MK", "ME", "MD", "XK", "BY"}
AMERICAS = {"US", "CA", "MX", "BR", "AR", "CO", "CL", "PE", "UY", "EC", "BO", "PY", "VE", "CR", "PA", "GT", "HN", "SV", "NI", "DO", "PR", "CU", "JM"}
LATAM = AMERICAS - {"US", "CA"}
APAC = {"AU", "NZ", "SG", "JP", "KR", "CN", "HK", "TW", "IN", "ID", "MY", "TH", "VN", "PH", "PK", "BD", "LK", "NP"}
MENA = {"AE", "SA", "QA", "KW", "BH", "OM", "JO", "LB", "EG", "MA", "DZ", "TN", "LY", "IL", "TR", "IQ", "IR"}
AREA_SETS = {"eu": EU, "europe": EU, "emea": EU | MENA | {"ZA", "NG", "KE", "GH", "RW", "ET", "UG", "SN", "TZ"},
             "americas": AMERICAS, "latam": LATAM, "north america": {"US", "CA", "MX"}, "apac": APAC}


def settings():
    s = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        v = store.get_setting(k)
        if v is not None:
            s[k] = v
    return s


# ---------------------------------------------------------------- normalize

def _clean_tags(tags):
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    out = []
    for t in tags or []:
        t = str(t).strip()
        if t and len(t) < 40 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return out[:12]


def normalize(raw, source_id):
    title = extract.html_to_text(raw.get("title") or "", 300).replace("\n", " ").strip()
    if not title:
        return None
    desc = raw.get("description") or extract.html_to_text(raw.get("description_html") or "")
    if raw.get("mojibake"):
        desc, title = extract.fix_mojibake(desc), extract.fix_mojibake(title)
    company = (extract.fix_mojibake(raw.get("company") or "") if raw.get("mojibake") else (raw.get("company") or ""))
    company = html.unescape(html.unescape(company)).strip()[:200]
    hint = geo.resolve_country(raw.get("country_hint") or "")
    loc_text = (raw.get("location") or "").strip()
    loc = geo.parse_location(loc_text, hint)
    if raw.get("region") and not loc["region"]:
        loc["region"] = raw["region"]
    clist = raw.get("country_list") or []
    if clist:
        codes = [geo.resolve_country(c) for c in clist]
        codes = [c for c in codes if c]
        if len(codes) == 1:
            loc["country"] = codes[0]
        loc["worldwide"] = False
        loc["countries"] = codes
    remote = bool(raw.get("remote")) or loc["remote"]
    smin, smax, cur = raw.get("salary_min"), raw.get("salary_max"), raw.get("salary_currency") or ""
    stext = raw.get("salary_text") or ""
    try:
        smin = float(smin) if smin not in (None, "", 0, "0") else None
        smax = float(smax) if smax not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        smin = smax = None
    if smin is None and smax is None:
        pmin, pmax, pcur, ptext = extract.parse_salary(stext, False) if stext else extract.parse_salary(desc[:6000], True)
        if pmin:
            smin, smax, cur = pmin, pmax, cur or pcur
            stext = stext or ptext
    emails = extract.find_emails(desc)
    for e in raw.get("emails") or []:
        if e and e.lower() not in emails:
            emails.append(e.lower())
    phones = extract.find_phones((raw.get("phones_raw") or "") + "\n" + desc[:20000], loc["country"])
    url = raw.get("url") or raw.get("apply_url") or ""
    apply_url = raw.get("apply_url") or url
    return {
        "title": title, "company": company, "location": loc_text or ("Remote" if remote else ""),
        "country": loc["country"], "region": loc["region"], "city": loc["city"], "remote": remote,
        "worldwide": loc["worldwide"] or (remote and not loc["country"] and not loc.get("countries") and not loc["areas"]),
        "areas": loc["areas"], "countries": loc.get("countries") or [],
        "job_type": (raw.get("job_type") or "").strip()[:80], "salary_min": smin, "salary_max": smax,
        "salary_currency": cur, "salary_text": stext[:120], "description": desc, "url": url, "apply_url": apply_url,
        "posted_at": extract.to_ts(raw.get("posted_at")), "tags": _clean_tags(raw.get("tags")),
        "emails": emails, "phones": phones, "sources": [source_id],
        "insights": insights.analyze(title, desc),
        "contacts": recruiters.people_from_text(desc[:20000], url, company, from_job=True, region=loc["country"])[:5],
        "company_domain": extract.company_domain(apply_url if source_id not in ("remotive", "remoteok", "jobicy", "himalayas", "arbeitnow", "workingnomads", "weworkremotely") else "", emails),
    }


# ---------------------------------------------------------------- matching

_ARABIC = re.compile(r"[؀-ۿ]")
_TERM_RX = {}


def _has_term(hay, term):
    """Accent/case-insensitive match at a word start ("hr" must not match inside "three"; "develop" still matches
    "developer"). Arabic terms match anywhere, because Arabic attaches prefixes like ال to the word."""
    t = synonyms.fold(term)
    if not t:
        return True
    if _ARABIC.search(t):
        return t in hay
    rx = _TERM_RX.get(t)
    if rx is None:
        rx = _TERM_RX[t] = re.compile(r"(?<![a-z0-9])" + re.escape(t))
    return bool(rx.search(hay))


def _contains_all(text, words):
    return all(_has_term(text, w) for w in words)


def matches(j, q, skip_keywords=False):
    """j = normalized job. skip_keywords: the source already searched the keywords server-side."""
    groups = q.match_groups
    if groups and not skip_keywords:
        hay = synonyms.fold(" ".join([j["title"], " ".join(j.get("tags") or []), j.get("company", "")]))
        if q.match_description:
            hay += " " + synonyms.fold((j.get("description") or "")[:6000])
        if not any(_contains_all(hay, g) for g in groups):
            return False
    if q.remote == "remote" and not j["remote"]:
        return False
    if q.remote == "onsite" and j["remote"]:
        return False
    if q.country:
        # Strict by default: the job must be located in the country. Multi-country postings count when the
        # country is one of their real locations; remote "open to X" eligibility is opt-in (include_worldwide).
        ok = j["country"] == q.country or (q.country in (j.get("countries") or []) and not j["remote"])
        if not ok and j["remote"] and q.include_worldwide and q.country in (j.get("countries") or []):
            ok = True
        if not ok and j["remote"] and q.include_worldwide:
            if j.get("worldwide"):
                ok = True
            elif any(q.country in AREA_SETS.get(a, set()) for a in j.get("areas") or []):
                ok = True
        if not ok:
            return False
    if q.region:
        rq = q.region.lower()
        if rq not in (j.get("region") or "").lower() and rq not in (j.get("location") or "").lower():
            return False
    if q.city:
        cq = q.city.lower()
        if cq not in (j.get("city") or "").lower() and cq not in (j.get("location") or "").lower():
            return False
    if q.days and j.get("posted_at") and j["posted_at"] < time.time() - q.days * 86400:
        return False
    if q.job_type and q.job_type.lower() not in (j.get("job_type") or "").lower() and q.job_type.lower() not in (j.get("title") or "").lower():
        return False
    return True


# ---------------------------------------------------------------- runs

RUNS = {}          # run_id -> Runner
_runs_lock = threading.Lock()


class Runner:
    """One search run. Progress (per source, plus a checkpoint of finished company boards) is written to the
    database continuously, so a run cut off by a crash, a shutdown or a closed app can resume where it stopped."""

    def __init__(self, run_id, query, source_ids, search_id=None, resume_state=None):
        self.run_id = run_id
        self.q = query
        self.search_id = search_id
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.found = 0
        self.new = 0
        self.company_keys = set()
        srcs = {s.id: s for s in all_sources()}
        self.sources = [srcs[i] for i in source_ids if i in srcs]
        self.progress = {s.id: {"name": s.name, "status": "queued", "found": 0, "scanned": 0, "message": "", "error": ""} for s in self.sources}
        if resume_state:
            for sid, old in resume_state.items():
                if sid in self.progress and isinstance(old, dict):
                    self.progress[sid].update(old)
                    if old.get("status") != "done":
                        self.progress[sid].update(status="queued", error="")
            row = store.q1("SELECT COUNT(*) AS n, COALESCE(SUM(is_new), 0) AS nn FROM run_jobs WHERE run_id = ?", (run_id,))
            self.found, self.new = row["n"], row["nn"]
        self._last_save = 0

    def _save(self, force=False):
        if not force and time.time() - self._last_save < 0.8:
            return
        self._last_save = time.time()
        with self.lock:
            prog = json.dumps(self.progress)
            found, new = self.found, self.new
        note = "Internet connection lost - waiting for it to come back, the search will continue automatically." \
            if net.OFFLINE["since"] else ""
        store.run("UPDATE runs SET progress = ?, found = ?, new = ?, note = ? WHERE id = ?", (prog, found, new, note, self.run_id))

    def _run_source(self, src, st):
        p = self.progress[src.id]
        if p.get("status") == "done":
            return                                    # finished before the interruption
        p["status"] = "running"
        started = time.time()

        def report(msg):
            p["message"] = msg
            self._save()

        def early_match(raw):
            n = normalize(raw, src.id)
            return bool(n) and matches(n, self.q)

        ctx = Ctx(st, self.stop, report, match=early_match if src.kind == "ats" else None)
        # checkpoint: company boards already processed in this run are skipped after a resume
        ctx.checkpoint = set(p.get("checkpoint") or [])

        def board_done(bid):
            with self.lock:
                p.setdefault("checkpoint", []).append(bid)
            self._save()
        ctx.board_done = board_done
        try:
            for raw in src.search(self.q, ctx):
                if self.stop.is_set():
                    break
                p["scanned"] += 1
                job = normalize(raw, src.id)
                if not job:
                    continue
                if src.kind != "ats":
                    ats.discover(" ".join((job["url"], job["apply_url"], job["description"][:8000])), source=src.id)
                if not matches(job, self.q, skip_keywords=src.server_search):
                    continue
                jid, is_new = store.upsert_job(job)
                if jid is None:          # the user deleted this job - don't bring it back
                    continue
                store.run("INSERT OR IGNORE INTO run_jobs(run_id, job_id, is_new) VALUES(?,?,?)", (self.run_id, jid, 1 if is_new else 0))
                with self.lock:
                    self.found += 1
                    self.new += 1 if is_new else 0
                    if job["company"]:
                        self.company_keys.add(store.company_key(job["company"]))
                p["found"] += 1
                self._save()
                if p["found"] >= self.q.max_per_source * (3 if src.kind == "ats" else 1):
                    p["message"] = (p["message"] + " · limit reached").strip(" ·")
                    break
            p["status"] = "stopped" if self.stop.is_set() else "done"
        except Exception as e:
            p["status"] = "error"
            p["error"] = str(e)[:300]
            log.warning("source %s failed: %s", src.id, traceback.format_exc(limit=3))
        p["seconds"] = round(time.time() - started, 1)
        self._save(force=True)

    def run(self):
        st = settings()
        threads = [threading.Thread(target=self._run_source, args=(s, st), daemon=True, name="src-" + s.id) for s in self.sources]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        try:
            store.refresh_companies(self.company_keys)
        except Exception:
            log.exception("refresh companies")
        status = "stopped" if self.stop.is_set() else ("error" if all(p["status"] == "error" for p in self.progress.values()) and self.progress else "done")
        self._save(force=True)
        store.run("UPDATE runs SET status = ?, finished_at = ? WHERE id = ?", (status, store.now(), self.run_id))
        if self.search_id:
            s = store.q1("SELECT name FROM searches WHERE id = ?", (self.search_id,))
            store.run("UPDATE searches SET last_run = ?, last_new = ?, unseen = unseen + ? WHERE id = ?",
                      (store.now(), self.new, self.new, self.search_id))
            if self.new and s:
                store.notify("%d new job%s for “%s”" % (self.new, "s" if self.new != 1 else "", s["name"]), "#/jobs?run=%d" % self.run_id)
        with _runs_lock:
            RUNS.pop(self.run_id, None)
        try:
            import matcher
            matcher.poke()                    # score the new jobs against the CV
        except Exception:
            pass


def start_run(params, source_ids=None, search_id=None):
    q = Query(**{k: params.get(k) for k in QUERY_KEYS if k in params})
    st = settings()
    available = [s for s in all_sources() if s.ready(st)]
    ids = [i for i in (source_ids or [s.id for s in available if s.id not in (st.get("disabled_sources") or [])])
           if i in {s.id for s in available}]
    rid = store.run("INSERT INTO runs(search_id, params, progress, started_at) VALUES(?,?,?,?)",
                    (search_id, json.dumps(dict(q.to_dict(), sources=ids)), "{}", store.now()))
    r = Runner(rid, q, ids, search_id)
    with _runs_lock:
        RUNS[rid] = r
    r._save(force=True)
    threading.Thread(target=r.run, daemon=True, name="run-%d" % rid).start()
    return rid


def stop_run(rid):
    r = RUNS.get(rid)
    if r:
        r.stop.set()
        return True
    return False


QUERY_KEYS = ("keywords", "country", "region", "city", "remote", "days", "job_type", "max_per_source", "match_description",
              "include_worldwide", "multilingual")


def resume_run(rid):
    """Continue a stopped or interrupted run: finished sources and finished company boards are skipped."""
    with _runs_lock:
        if rid in RUNS:
            return True
    row = store.q1("SELECT * FROM runs WHERE id = ?", (rid,))
    if row is None or row["status"] not in ("stopped", "interrupted", "error"):
        return False
    params = json.loads(row["params"] or "{}")
    progress = json.loads(row["progress"] or "{}")
    q = Query(**{k: params[k] for k in QUERY_KEYS if k in params})
    ids = params.get("sources") or list(progress.keys())
    r = Runner(rid, q, ids, row["search_id"], resume_state=progress)
    with _runs_lock:
        RUNS[rid] = r
    store.run("UPDATE runs SET status = 'running', finished_at = NULL, note = '' WHERE id = ?", (rid,))
    r._save(force=True)
    threading.Thread(target=r.run, daemon=True, name="run-%d" % rid).start()
    return True


def auto_resume(max_age_hours=48, limit=3):
    """At startup: resume searches that were cut off by a crash / shutdown (not the ones you stopped yourself)."""
    if not int(settings().get("auto_resume") or 0):
        return []
    rows = store.q("SELECT id FROM runs WHERE status = 'interrupted' AND started_at >= ? ORDER BY id DESC LIMIT ?",
                   (store.now() - max_age_hours * 3600, limit))
    return [r["id"] for r in rows if resume_run(r["id"])]


def active_search_ids():
    with _runs_lock:
        return {r.search_id for r in RUNS.values() if r.search_id}


# ---------------------------------------------------------------- scheduler

def _scheduler():
    time.sleep(20)
    while True:
        try:
            busy = active_search_ids()
            for s in store.q("SELECT * FROM searches WHERE every_hours > 0"):
                due = not s["last_run"] or store.now() - s["last_run"] >= s["every_hours"] * 3600
                if due and s["id"] not in busy:
                    p = json.loads(s["params"])
                    start_run(p, p.get("sources") or None, search_id=s["id"])
                    store.run("UPDATE searches SET last_run = ? WHERE id = ?", (store.now(), s["id"]))
        except Exception:
            log.exception("scheduler")
        time.sleep(60)


def start_scheduler():
    threading.Thread(target=_scheduler, daemon=True, name="scheduler").start()


def seed_boards(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for provider, slugs in data.items():
        for s in slugs:
            n += 1 if store.add_board(provider, s, discovered_from="seed") else 0
    return n


# ---------------------------------------------------------------- backfill (jobs saved before insights existed)

def backfill_insights(batch=300):
    """Analyse older jobs in the background: insights + contact persons named in the job text."""
    def work():
        while True:
            rows = store.q("SELECT id, title, company, description, url, country FROM jobs WHERE insights = '{}' LIMIT ?", (batch,))
            if not rows:
                return
            for r in rows:
                ins = insights.analyze(r["title"], r["description"]) or {"_": 1}
                contacts = recruiters.people_from_text((r["description"] or "")[:20000], r["url"], r["company"], from_job=True,
                                                       region=r["country"])[:5]
                store.run("UPDATE jobs SET insights = ?, contacts = ? WHERE id = ?",
                          (json.dumps(ins, ensure_ascii=False), json.dumps(contacts, ensure_ascii=False), r["id"]))
                if contacts:
                    store.save_people(store.company_key(r["company"]), contacts, r["id"])
            time.sleep(0.2)
    threading.Thread(target=work, daemon=True, name="backfill").start()

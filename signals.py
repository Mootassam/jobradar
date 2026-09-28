"""Hiring signals - companies that are about to hire, often before the jobs reach the big job boards.

Every time a company career board is downloaded, each of its postings is recorded (first seen / last seen / gone).
Comparing those snapshots over days shows:
  - a hiring surge (many new postings, open jobs growing fast)
  - expansion into a new country (first job ever in a country - especially yours)
  - a new team / department starting
  - recruiters being hired (the company is building a recruiting team = more hiring ahead)
  - new postings in your own field
Companies found only on job boards (e.g. national boards) contribute through the posting dates of their jobs.
Watched companies notify you as soon as they post something new."""
import hashlib
import json
import time

import geo
import store
import synonyms

_RECRUITER_CONCEPTS = None
_CACHE = {"at": 0, "key": None, "data": None}


def _pkey(j):
    base = j.get("url") or ("%s|%s" % (j.get("title"), j.get("location")))
    return hashlib.sha1(str(base).encode()).hexdigest()[:20]


_ANON = ("entreprise anonyme", "anonyme", "anonymous", "confidential", "confidentiel", "confidentielle", "societe confidentielle",
         "company confidential", "undisclosed", "non communique", "client confidentiel", "vertraulich")


def is_anonymous(key):
    """Job-board posts that hide the employer ("Entreprise Anonyme") are not one company."""
    k = synonyms.fold(key or "")
    return not k or any(k == a or k.startswith(a + " ") for a in _ANON)


def record_board(board, jobs, company=""):
    """Snapshot one freshly-downloaded board. Called by the ATS source (not for cached reads)."""
    bid = board["id"]
    now = store.now()
    row = store.q1("SELECT tracked_since, snapshots FROM boards WHERE id = ?", (bid,))
    first_time = not row or not row["tracked_since"]
    ckey = store.company_key(company or (jobs[0].get("company") if jobs else "") or board.get("company") or board.get("slug", ""))
    current = {}
    for j in jobs:
        loc = geo.parse_location(j.get("location") or "", geo.resolve_country(j.get("country_hint") or ""))
        current[_pkey(j)] = (str(j.get("title") or "")[:200], loc["country"] or "", ((j.get("tags") or [""])[0] or "")[:80])
    new_titles = []
    with store.tx() as c:
        known = {r["pkey"]: r for r in c.execute("SELECT pkey, gone_at FROM postings WHERE board_id = ?", (bid,))}
        for pk, (title, country, dept) in current.items():
            if pk in known:
                c.execute("UPDATE postings SET last_seen = ?, gone_at = NULL, company_key = ? WHERE board_id = ? AND pkey = ?", (now, ckey, bid, pk))
            else:
                c.execute("INSERT INTO postings(board_id, pkey, company_key, title, country, dept, first_seen, last_seen, baseline) VALUES(?,?,?,?,?,?,?,?,?)",
                          (bid, pk, ckey, title, country, dept, now, now, 1 if first_time else 0))
                if not first_time:
                    new_titles.append(title)
        gone = [pk for pk, r in known.items() if pk not in current and r["gone_at"] is None]
        for pk in gone:
            c.execute("UPDATE postings SET gone_at = ? WHERE board_id = ? AND pkey = ?", (now, bid, pk))
        c.execute("UPDATE boards SET tracked_since = COALESCE(tracked_since, ?), snapshots = snapshots + 1 WHERE id = ?", (now, bid))
    if new_titles and ckey:
        w = store.q1("SELECT name, watch FROM companies WHERE key = ?", (ckey,))
        if w and w["watch"]:
            store.notify("⭐ %s posted %d new job%s: %s" % (w["name"], len(new_titles), "s" if len(new_titles) > 1 else "",
                                                          ", ".join(new_titles[:3])[:200]), "#/signals?company=" + ckey)
    _CACHE["at"] = 0
    return len(new_titles)


def _recruiter_title(title):
    t = synonyms.fold(title)
    return any(w in t for w in ("recruit", "talent acquisition", "sourcer", "recrut", "charge de recrutement", "people partner",
                                "hr business partner", "personalreferent"))


def compute(my_country="", my_families=None, days=14):
    """Signals for every tracked company -> {company_key: {...}} (cached 5 min)."""
    key = (my_country, tuple(my_families or []), days)
    if _CACHE["data"] is not None and _CACHE["key"] == key and time.time() - _CACHE["at"] < 300:
        return _CACHE["data"]
    now = store.now()
    since = now - days * 86400
    month = now - 30 * 86400
    import cvcheck
    import matcher
    fams = set(my_families or []) - matcher.GENERIC_FAMILIES     # "assistant" alone doesn't make a job "in your field"
    out = {}
    rows = store.q("SELECT p.company_key, p.title, p.country, p.dept, p.first_seen, p.gone_at, p.baseline, b.tracked_since "
                   "FROM postings p JOIN boards b ON b.id = p.board_id WHERE p.company_key != ''")
    by = {}
    for r in rows:
        by.setdefault(r["company_key"], []).append(r)
    for ck, ps in by.items():
        if is_anonymous(ck):
            continue
        tracked = min((p["tracked_since"] or now) for p in ps)
        age_days = (now - tracked) / 86400
        open_now = [p for p in ps if p["gone_at"] is None]
        fresh = [p for p in ps if not p["baseline"] and p["first_seen"] >= since]
        fresh30 = [p for p in ps if not p["baseline"] and p["first_seen"] >= month]
        open_before = [p for p in ps if p["first_seen"] <= month and (p["gone_at"] is None or p["gone_at"] > month)]
        countries_old = {p["country"] for p in ps if p["country"] and (p["baseline"] or p["first_seen"] < month)}
        new_countries = sorted({p["country"] for p in fresh30 if p["country"] and p["country"] not in countries_old})
        depts_old = {p["dept"] for p in ps if p["dept"] and (p["baseline"] or p["first_seen"] < month)}
        new_depts = sorted({p["dept"] for p in fresh30 if p["dept"] and p["dept"] not in depts_old})[:4]
        s = {"open": len(open_now), "new": len(fresh), "new30": len(fresh30), "tracked_days": round(age_days, 1),
             "new_countries": new_countries if age_days >= 5 else [], "new_depts": new_depts if age_days >= 5 else [],
             "growth": None, "recruiters": sum(1 for p in open_now if _recruiter_title(p["title"])),
             "in_my_country": sum(1 for p in fresh30 if my_country and p["country"] == my_country),
             "my_field": 0, "titles": [p["title"] for p in sorted(fresh, key=lambda x: -x["first_seen"])][:6]}
        if age_days >= 21 and open_before:
            s["growth"] = round((len(open_now) - len(open_before)) / max(1, len(open_before)), 2)
        if fams:
            s["my_field"] = sum(1 for p in fresh30 if set(cvcheck.job_families(p["title"])) & fams)
        out[ck] = s
    # companies known only from job boards: fresh postings by posting date
    rows = store.q("SELECT company_key, COUNT(*) AS n, SUM(posted_at >= ?) AS n14, SUM(posted_at >= ? AND country = ?) AS mine, "
                   "group_concat(title, '||') AS titles FROM jobs WHERE company_key != '' AND posted_at >= ? AND sources NOT LIKE '%companies%' "
                   "GROUP BY company_key", (since, month, my_country or "--", month))
    for r in rows:
        if is_anonymous(r["company_key"]):
            continue
        s = out.setdefault(r["company_key"], {"open": 0, "new": 0, "new30": 0, "tracked_days": 0, "new_countries": [], "new_depts": [],
                                               "growth": None, "recruiters": 0, "in_my_country": 0, "my_field": 0, "titles": []})
        titles = [t for t in (r["titles"] or "").split("||") if t]
        s["new"] = max(s["new"], r["n14"] or 0)
        s["new30"] = max(s["new30"], r["n"] or 0)
        s["in_my_country"] = max(s["in_my_country"], r["mine"] or 0)
        s["recruiters"] = max(s["recruiters"], sum(1 for t in titles if _recruiter_title(t)))
        if fams:
            s["my_field"] = max(s["my_field"], sum(1 for t in titles if set(cvcheck.job_families(t)) & fams))
        s["titles"] = s["titles"] or titles[:6]
    for ck, s in out.items():
        s["heat"], s["reasons"] = _heat(s, my_country)
    _CACHE.update(at=time.time(), key=key, data=out)
    return out


def _heat(s, my_country):
    heat, reasons = 0, []
    if s["new"]:
        heat += min(40, 6 * s["new"])
        reasons.append(("surge" if s["new"] >= 5 else "new", "%d new job%s in 14 days" % (s["new"], "s" if s["new"] > 1 else "")))
    if s["growth"] is not None and s["growth"] >= 0.25 and s["open"] >= 4:
        heat += min(25, int(s["growth"] * 30))
        reasons.append(("growth", "Open jobs up %d%% in a month" % round(s["growth"] * 100)))
    if s["new_countries"]:
        heat += 15
        reasons.append(("country", "First jobs in " + ", ".join(geo.country_name(c) for c in s["new_countries"][:3])))
    if my_country and s["in_my_country"]:
        heat += 15
        reasons.append(("mine", "%d new in %s" % (s["in_my_country"], geo.country_name(my_country))))
    if s["recruiters"]:
        heat += 10
        reasons.append(("recruiters", "Hiring recruiters - more hiring ahead"))
    if s["new_depts"]:
        heat += 6
        reasons.append(("team", "New team: " + ", ".join(s["new_depts"][:2])))
    if s["my_field"]:
        heat += 10
        reasons.append(("field", "%d in your field" % s["my_field"]))
    return min(100, heat), reasons


def hot_companies(my_country="", my_families=None, country="", field_only=False, has_contact=False, min_heat=1, q="", watched=False,
                  limit=60, offset=0):
    sig = compute(my_country, my_families)
    keys = [k for k, s in sig.items() if s["heat"] >= min_heat and (not field_only or s["my_field"])] if not watched else list(sig.keys())
    if not keys and not watched:
        return [], 0
    comp = {}
    wh = "" if not watched else " OR c.watch = 1"
    for i in range(0, max(1, len(keys)), 900):
        chunk = keys[i:i + 900]
        ph = ",".join("?" * len(chunk)) if chunk else "''"
        for r in store.q("SELECT c.key, c.name, c.domain, c.emails, c.watch, c.enriched_at, c.logo, c.description, "
                         "(SELECT COUNT(*) FROM people p WHERE p.company_key = c.key) AS people, "
                         "(SELECT COUNT(*) FROM people p WHERE p.company_key = c.key AND p.role = 'hr') AS hr, "
                         "(SELECT group_concat(DISTINCT j.country) FROM jobs j WHERE j.company_key = c.key AND j.country != '') AS countries, "
                         "(SELECT COUNT(*) FROM jobs j WHERE j.company_key = c.key AND j.hidden = 0) AS jobs, "
                         "(SELECT MAX(j.match_score) FROM jobs j WHERE j.company_key = c.key) AS best_match, "
                         "(SELECT MAX(o.sent_at) FROM outreach o WHERE o.company_key = c.key AND o.status IN ('sent','replied')) AS contacted "
                         "FROM companies c WHERE c.key IN (%s)%s" % (ph, wh), chunk):
            comp[r["key"]] = dict(r)
    out = []
    for k, c in comp.items():
        s = sig.get(k) or {"heat": 0, "reasons": [], "open": 0, "new": 0, "titles": [], "new_countries": [], "growth": None}
        if watched and not c["watch"]:
            continue
        cc = [x for x in (c["countries"] or "").split(",") if x]
        if country and country not in cc and country not in s.get("new_countries", []) and not (country == my_country and s.get("in_my_country")):
            continue
        emails = json.loads(c["emails"] or "[]")
        if has_contact and not emails and not c["people"]:
            continue
        if q and synonyms.fold(q) not in synonyms.fold(c["name"] + " " + (c["domain"] or "")):
            continue
        out.append(dict(c, emails=emails[:3], countries=cc[:8], signal=s, heat=s["heat"]))
    out.sort(key=lambda x: (-x["heat"], -(x["signal"].get("new") or 0), x["name"]))
    return out[offset:offset + limit], len(out)


def summary(my_country="", my_families=None):
    sig = compute(my_country, my_families)
    tracked = store.q1("SELECT COUNT(*) AS n, MIN(tracked_since) AS since, SUM(snapshots) AS snaps FROM boards WHERE tracked_since IS NOT NULL")
    return {"companies": len(sig), "hot": sum(1 for s in sig.values() if s["heat"] >= 40),
            "warm": sum(1 for s in sig.values() if 15 <= s["heat"] < 40),
            "new_country": sum(1 for s in sig.values() if s["new_countries"]),
            "tracked_boards": tracked["n"] or 0, "tracking_since": tracked["since"], "snapshots": tracked["snaps"] or 0,
            "watched": store.q1("SELECT COUNT(*) AS n FROM companies WHERE watch = 1")["n"]}

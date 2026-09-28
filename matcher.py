"""CV <-> job match score (0-100), best-CV picker, skill-gap report and top-match alerts.

The score explains itself - every job gets a breakdown:
  skills 45  (required skills count fully, nice-to-have ones less; related skills give partial credit)
  role   25  (same job family in any language - "comptable" = "accountant" - or overlapping title words)
  experience 12, languages 8 (incl. the language the post is written in), education 5, location 5
A background worker keeps every stored job scored: new jobs, and all jobs again whenever the profile or a CV
changes (tracked by a profile fingerprint)."""
import hashlib
import json
import logging
import re
import threading
import time

import applicant
import cvcheck
import skills
import store
import synonyms

log = logging.getLogger("jobradar.match")
WEIGHTS = {"skills": 45, "role": 25, "experience": 12, "languages": 8, "education": 5, "location": 5}
EDU_LEVEL = {"PhD / Doctorate": 5, "Master's": 4, "Bachelor's": 3, "Associate / BTS": 2, "High school": 1}
LANG_CODE = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "ar": "Arabic"}
_TITLE_STOP = set("senior junior sr jr lead principal staff head chief intern stagiaire trainee h/f f/h m/w/d w/m/d m/f/d f/m/x "
                  "remote hybrid full time part time the of and for de du des la le et en a au im in mit der die das y el los".split())
# Generic job words (engineer, manager, assistant...) - on their own they don't make two jobs the same profession.
GENERIC_FAMILIES = {36, 42, 65, 66, 67, 68, 72}
# Neighbouring professions (indexes into synonyms.CONCEPTS): an accountant fits an auditor job partly, not a nurse job.
FAMILY_GROUPS = [{0, 1, 2, 3, 4}, {10, 11, 12, 13, 22}, {14, 15, 16}, {17, 18, 19, 20, 21}, {23, 24}, {25, 26}, {27, 28, 29},
                 {30, 31, 32}, {33, 34, 35}, {37, 38, 39, 46}, {40, 41, 43, 44, 45}, {8, 9}, {5, 6, 7}, {47, 48, 49, 50, 51, 52},
                 {53, 54, 55, 56, 57}, {58, 59}, {60, 61, 62}]


def _related(a, b):
    return any(a & g and b & g for g in FAMILY_GROUPS)
STATE = {"running": False, "done": 0, "total": 0, "version": "", "last": 0, "error": ""}
_lock = threading.Lock()
_wake = threading.Event()


# ---------------------------------------------------------------- my profile (from all CVs + profile form)

def me(force=False):
    """Everything the matcher knows about the user. Returns None when there's nothing to match with yet."""
    p = applicant.get()
    cvs = applicant.cvs()
    per_cv = []
    for cv in cvs:
        path, _ = applicant.cv_path(cv["id"])
        if not path:
            continue
        try:
            d = cvcheck.parse_cv(cv, path, p, force)
        except Exception:
            log.exception("parse cv %s", cv["id"])
            continue
        a = d["a"]
        per_cv.append({"id": cv["id"], "label": cv["label"], "default": cv.get("default"), "skills": a["skills"],
                       "months": a["months"], "languages": a["languages"], "education": a["education"], "families": a["families"]})
    extra = []
    for s in str(p.get("skills_extra") or "").split(","):
        s = s.strip()
        canon = skills._ALIAS.get(synonyms.fold(s)) if s else None
        if canon:
            extra.append(canon)
    targets = ", ".join(x for x in (p.get("target_titles"), p.get("current_title")) if x)
    fam = cvcheck.job_families(targets) if targets else []
    if not per_cv and not extra and not fam:
        return None
    all_skills = list(dict.fromkeys([s for c in per_cv for s in c["skills"]] + extra))
    langs = {}
    for c in per_cv:
        for k, v in c["languages"].items():
            langs[k] = max(langs.get(k, 0), v)
    for k, v in cvcheck.languages_spoken(p.get("languages") or "", p.get("languages") or "").items():
        langs[k] = max(langs.get(k, 0), v)
    try:
        years = float(str(p.get("years_experience") or "").replace(",", ".").split()[0])
    except (ValueError, IndexError):
        years = max([c["months"] for c in per_cv] or [0]) / 12.0
    edu = max([c["education"] for c in per_cv] + [cvcheck.education_level(p.get("education_degree") or "")] + [0])
    families = list(dict.fromkeys(fam + [f for c in per_cv for f in c["families"]]))
    title_words = _title_words(targets) or set()
    for c in per_cv:
        c["skills"] = list(dict.fromkeys(c["skills"] + extra))
    return {"skills": all_skills, "years": round(years, 1), "languages": langs, "education": edu, "families": families,
            "title_words": sorted(title_words), "targets": targets, "country": cvcheck.geo_code(p.get("country", "")),
            "city": synonyms.fold(p.get("city") or ""), "relocate": p.get("willing_to_relocate") or "",
            "sponsorship": p.get("requires_sponsorship") or "", "cvs": per_cv}


def fingerprint(m):
    if not m:
        return ""
    return hashlib.md5(json.dumps(m, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12] + "-v5"


def _title_words(text):
    return {w for w in re.findall(r"[\w+#.]+", synonyms.fold(text or "")) if len(w) > 1 and w not in _TITLE_STOP}


# ---------------------------------------------------------------- scoring

def _skill_part(req, nice, have):
    if not req and not nice:
        return None, [], [], [], []
    full, partial = skills.closure(have)
    wsum = got = 0.0
    matched, part, miss_r, miss_n = [], [], [], []
    if not [x for x in req + nice if skills.kind(x) != "soft"]:
        return None, [x for x in req + nice if x in have], [], [], []     # only soft skills listed: says nothing about fit
    for s, factor, miss in [(x, 1.0, miss_r) for x in req] + [(x, 0.4, miss_n) for x in nice]:
        w = skills.weight(s) * factor
        soft = skills.kind(s) == "soft"
        c = 1.0 if s in full else (0.6 if soft else partial.get(s, 0))   # soft skills: benefit of the doubt, CVs rarely list them
        wsum += w
        got += w * c
        if c == 1:
            matched.append(s)
        elif soft:
            continue
        elif c > 0:
            part.append(s)
        else:
            miss.append(s)
    ratio = (got + 0.25) / (wsum + 0.5)          # light smoothing: one-skill posts don't swing 0 <-> 100
    return ratio, matched, part, miss_r, miss_n


def score_job(j, m, cache_skills=None):
    """j: dict with title, description, insights, country, city, remote, location. m: me(). -> (score, detail)."""
    title = j.get("title") or ""
    desc = j.get("description") or ""
    ins = j.get("insights") or {}
    if isinstance(ins, str):
        try:
            ins = json.loads(ins)
        except ValueError:
            ins = {}
    if cache_skills:
        req, nice = cache_skills
    else:
        req, nice = skills.job_skills(title + "\n" + desc)
    parts, notes = {}, []
    # role
    jf = set(cvcheck.job_families(title))
    mine = set(m["families"])
    spec_job, spec_me = jf - GENERIC_FAMILIES, mine - GENERIC_FAMILIES
    tw = _title_words(title)
    overlap = len(tw & set(m["title_words"]))
    if spec_job & spec_me:
        role = 1.0
    elif spec_job and _related(spec_job, spec_me):
        role = 0.7                                          # a neighbouring profession (accountant -> auditor)
    elif spec_job:
        role = 0.4 if overlap else 0.0                     # a different profession ("Assistant dentaire" for an accountant)
        if not role:
            notes.append("Different job family")
    elif jf & mine:
        role = 0.3                                          # only a generic word in common ("Assistant ...", "Manager ...")
    else:
        role = min(1.0, 0.35 + 0.3 * overlap) if overlap else 0.0
        if not role and any(s in skills.find(title) for s in m["skills"]):
            role = 0.55                                     # "Python Developer" for someone who knows Python
        if not role:
            role = 0.3                                      # title of unknown family: neutral-low
    parts["role"] = role
    # skills - per CV, keep the best
    best = None
    for cv in m["cvs"] or [{"id": "", "label": "", "skills": m["skills"]}]:
        r = _skill_part(req, nice, cv["skills"])
        if best is None or (r[0] or 0) > (best[1][0] or 0):
            best = (cv, r)
    cv, (ratio, matched, part, miss_r, miss_n) = best
    # experience
    need = ins.get("experience_years")
    sen = ins.get("seniority") or ""
    yrs = m["years"]
    if need is None:
        exp = 0.85
        if sen in ("Senior", "Lead", "Director", "Manager") and yrs < 3:
            exp = 0.35
            notes.append("%s role" % sen)
        elif sen in ("Intern", "Junior") and yrs > 8:
            exp = 0.7
    elif yrs >= need:
        exp = 1.0 if not (sen in ("Intern", "Junior") and yrs > need + 8) else 0.7
    else:
        exp = max(0.0, 1 - (need - yrs) * 0.22)
        notes.append("Asks %d+ years, you have %s" % (need, _yrs(yrs)))
    parts["experience"] = exp
    # languages (asked + the language the post is written in)
    asked = list(ins.get("languages") or [])
    written = LANG_CODE.get(cvcheck.detect_language(desc[:4000])) if desc else None
    if written and written != "English" and written not in asked:
        asked.append(written)
    if asked:
        vals = []
        for L in asked:
            lvl = m["languages"].get(L, 0)
            if not lvl and L == "English" and m["languages"]:
                lvl = 2                                     # almost everyone who lists languages reads English
            vals.append(1.0 if lvl >= 3 else 0.6 if lvl == 2 else 0.3 if lvl == 1 else 0.0)
            if lvl == 0:
                notes.append("%s needed" % L)
        lang = sum(vals) / len(vals)
    else:
        lang = 1.0
    parts["languages"] = lang
    # education
    need_edu = EDU_LEVEL.get(ins.get("education") or "", 0)
    have_edu = m["education"]
    edu = 1.0 if not need_edu or have_edu >= need_edu or not have_edu else (0.6 if have_edu == need_edu - 1 else 0.3)
    parts["education"] = edu
    # location
    if j.get("remote"):
        loc = 1.0
    elif not j.get("country") or not m["country"]:
        loc = 0.7
    elif j["country"] == m["country"]:
        loc = 1.0 if (not m["city"] or m["city"] in synonyms.fold((j.get("city") or "") + " " + (j.get("location") or ""))) else 0.85
    else:
        vis = "Visa sponsorship" in (ins.get("benefits") or []) or "Relocation" in (ins.get("benefits") or [])
        loc = 0.75 if vis else (0.55 if m["relocate"] == "yes" else 0.3)
        if m["sponsorship"] == "yes" and not vis:
            loc = min(loc, 0.25)
            notes.append("Abroad - no visa support mentioned")
    parts["location"] = loc
    # combine: skills + job family make the core fit; experience, languages, education and location adjust it
    # (a job that simply has "no conflict" on those must not look like a match)
    weights = dict(WEIGHTS)
    if ratio is None:                                        # post lists no recognizable hard skills: the job family decides
        weights["role"] += weights.pop("skills")
        core = role
    else:
        parts["skills"] = ratio
        core = (WEIGHTS["skills"] * ratio + WEIGHTS["role"] * role) / (WEIGHTS["skills"] + WEIGHTS["role"])
    mods = sum(WEIGHTS[k] * parts[k] for k in ("experience", "languages", "education", "location")) / \
        sum(WEIGHTS[k] for k in ("experience", "languages", "education", "location"))
    total = 100 * core * (0.6 + 0.4 * mods)
    if lang < 0.35:
        total = min(total, 55)
    if need is not None and need - yrs >= 4:
        total = min(total, 60)
    if role == 0 and ratio is not None and ratio < 0.3:
        total = min(total, 35)
    if ratio is None:
        total = min(total, 85 if role == 1.0 else 45)       # the post lists no skills: we can't be sure
        notes.append("Few details in the post")
    score = int(round(max(0, min(100, total))))
    detail = {"score": score, "parts": {k: round(v * 100) for k, v in parts.items()}, "weights": weights,
              "have": matched[:15], "partial": part[:10], "missing": miss_r[:12], "missing_nice": miss_n[:10],
              "req": req[:25], "nice": nice[:15], "notes": notes[:5], "cv": cv.get("id", ""), "cv_label": cv.get("label", "")}
    return score, detail


def _yrs(y):
    return ("%g" % y) if y else "0"


# ---------------------------------------------------------------- background scoring

def _worker():
    time.sleep(8)
    while True:
        try:
            _run_once()
        except Exception as e:
            STATE["error"] = str(e)[:200]
            log.exception("match worker")
        STATE["running"] = False
        _wake.wait(timeout=45)
        _wake.clear()


def _run_once(batch=150):
    m = me()
    if not m:
        STATE.update(version="", total=0, done=0)
        return
    ver = fingerprint(m)
    STATE["version"] = ver
    remaining = store.q1("SELECT COUNT(*) AS n FROM jobs WHERE match_ver IS NULL OR match_ver != ?", (ver,))["n"]
    if not remaining:
        return
    STATE.update(running=True, total=remaining, done=0, error="")
    alert_min = int(store.get_setting("match_alert_min", 75) or 0)
    fresh_hits = []
    while True:
        rows = store.q("SELECT id, title, description, insights, country, city, remote, location, first_seen, match_alerted FROM jobs "
                       "WHERE match_ver IS NULL OR match_ver != ? ORDER BY first_seen DESC LIMIT ?", (ver, batch))
        if not rows:
            break
        out = []
        for r in rows:
            j = dict(r)
            try:
                s, d = score_job(j, m)
            except Exception:
                log.exception("score job %s", r["id"])
                s, d = 0, {"error": True}
            out.append((s, json.dumps(d, ensure_ascii=False), ver, r["id"]))
            if alert_min and s >= alert_min and not r["match_alerted"] and r["first_seen"] >= time.time() - 2 * 86400:
                fresh_hits.append(r["id"])
        with store.tx() as c:
            c.executemany("UPDATE jobs SET match_score = ?, match = ?, match_ver = ? WHERE id = ?", out)
        STATE["done"] += len(rows)
        time.sleep(0.05)
    if fresh_hits:
        with store.tx() as c:
            c.executemany("UPDATE jobs SET match_alerted = 1 WHERE id = ?", [(i,) for i in fresh_hits])
        store.notify("🎯 %d new job%s match your CV at %d%%+" % (len(fresh_hits), "s" if len(fresh_hits) > 1 else "", alert_min),
                     "#/jobs?sort=match&min_match=%d" % alert_min)
    STATE["last"] = int(time.time())


def start():
    threading.Thread(target=_worker, daemon=True, name="matcher").start()


def poke():
    """Profile / CV / new jobs changed: rescore soon."""
    _wake.set()


def rescore_one(jid):
    m = me()
    if not m:
        return None
    r = store.q1("SELECT id, title, description, insights, country, city, remote, location FROM jobs WHERE id = ?", (jid,))
    if r is None:
        return None
    s, d = score_job(dict(r), m)
    store.run("UPDATE jobs SET match_score = ?, match = ?, match_ver = ? WHERE id = ?", (s, json.dumps(d, ensure_ascii=False), fingerprint(m), jid))
    return s, d


# ---------------------------------------------------------------- reports

def skill_gap(limit=12):
    """Skills most often missing in the jobs that fit you - and how many good jobs each one would unlock."""
    rows = store.q("SELECT match_score, match FROM jobs WHERE hidden = 0 AND match_score >= 35 AND match_ver IS NOT NULL "
                   "ORDER BY match_score DESC LIMIT 3000")
    miss, unlock, nice = {}, {}, {}
    n = 0
    for r in rows:
        try:
            d = json.loads(r["match"] or "{}")
        except ValueError:
            continue
        if (d.get("parts") or {}).get("role", 0) < 100 and r["match_score"] < 60:
            continue                                   # only jobs in your field count
        n += 1
        for s in d.get("missing") or []:
            miss[s] = miss.get(s, 0) + 1
            if 50 <= r["match_score"] < 75 and len(d.get("missing") or []) <= 2:
                unlock[s] = unlock.get(s, 0) + 1
        for s in d.get("missing_nice") or []:
            nice[s] = nice.get(s, 0) + 1
    ranked = sorted(((s, c) for s, c in miss.items() if c >= 2 or len(miss) < 6), key=lambda x: (-x[1], x[0]))[:limit]
    return {"jobs": n, "skills": [{"skill": s, "jobs": c, "share": round(100 * c / n) if n else 0, "unlocks": unlock.get(s, 0),
                                   "kind": skills.kind(s)} for s, c in ranked],
            "nice": [{"skill": s, "jobs": c} for s, c in sorted(nice.items(), key=lambda x: -x[1])[:10]]}


def distribution():
    r = store.q1("SELECT COUNT(*) AS scored, SUM(match_score >= 75) AS top, SUM(match_score >= 60 AND match_score < 75) AS good, "
                 "SUM(match_score >= 40 AND match_score < 60) AS fair, SUM(match_score < 40) AS low FROM jobs WHERE hidden = 0 AND match_ver IS NOT NULL")
    return {k: (r[k] or 0) for k in r.keys()}


def best_cv_for_url(url):
    """The CV that fits a job page best (used by the autofill extension)."""
    if not url:
        return None
    base = url.split("#")[0].split("?")[0].rstrip("/")
    row = store.q1("SELECT id, match FROM jobs WHERE url = ? OR apply_url = ? OR url LIKE ? OR apply_url LIKE ? ORDER BY id DESC LIMIT 1",
                   (url, url, base + "%", base + "%"))
    if not row:
        return None
    try:
        d = json.loads(row["match"] or "{}")
    except ValueError:
        return None
    return d.get("cv") or None

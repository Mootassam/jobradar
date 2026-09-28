"""Company career boards hosted on applicant-tracking systems (public, documented job-board APIs):
Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Personio.

The registry of company boards lives in the `boards` table. It starts with a verified seed list and
grows by itself: every job URL / description that links to a board we don't know is registered
(`discover()`), and you can add any careers page URL (`detect()`)."""
import concurrent.futures as cf
import logging
import re

from bs4 import BeautifulSoup

import extract
import store
from net import FetchError, fetch
from . import Source

PROVIDERS = ("greenhouse", "lever", "ashby", "recruitee", "smartrecruiters", "personio")

DISCOVERY = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]{2,60})", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]{2,60})", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_.-]{2,60})", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.%-]{2,60})", re.I)),
    ("recruitee", re.compile(r"\b([a-z0-9-]{2,60})\.recruitee\.com", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]{2,60})", re.I)),
    ("personio", re.compile(r"\b([a-z0-9-]{2,60})\.jobs\.personio\.(?:de|com)", re.I)),
]
SKIP_SLUGS = {"embed", "api", "www", "jobs", "v1", "o", "careers", "job", "apply", "static", "assets", "app", "blog", "help"}


def discover(text, source=""):
    """Register every ATS board referenced in text. Returns number of new boards."""
    if not text:
        return 0
    added = 0
    for provider, rx in DISCOVERY:
        for m in rx.finditer(text):
            slug = m.group(1).strip(".").lower() if provider != "smartrecruiters" else m.group(1)
            if slug.lower() in SKIP_SLUGS or len(slug) < 2:
                continue
            if store.add_board(provider, slug, discovered_from=source):
                added += 1
    return added


def detect(url_or_text):
    """Find the ATS board behind a careers URL (follows the page once if needed). Returns [(provider, slug)]."""
    found = []
    for provider, rx in DISCOVERY:
        for m in rx.finditer(url_or_text):
            found.append((provider, m.group(1)))
    if found or not url_or_text.startswith("http"):
        return list(dict.fromkeys(found))
    try:
        html = fetch(url_or_text, expect="text", check_robots=True, timeout=20)
    except FetchError:
        return []
    for provider, rx in DISCOVERY:
        for m in rx.finditer(html):
            if m.group(1).lower() not in SKIP_SLUGS:
                found.append((provider, m.group(1)))
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- per-provider fetchers -> list of raw jobs

def _t(html):
    return extract.html_to_text(html, limit=25000)


def fetch_greenhouse(slug, stop):
    d = fetch("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug, params={"content": "true"}, stop=stop, timeout=40)
    out, company = [], ""
    for j in d.get("jobs", []):
        company = company or j.get("company_name") or ""
        offices = ", ".join(o.get("name", "") for o in (j.get("offices") or [])[:3])
        out.append({"title": j.get("title"), "company": j.get("company_name") or slug, "location": (j.get("location") or {}).get("name") or offices,
                    "description": _t(j.get("content")), "url": j.get("absolute_url"), "apply_url": j.get("absolute_url"),
                    "posted_at": j.get("first_published") or j.get("updated_at"),
                    "tags": [x.get("name") for x in (j.get("departments") or []) if x.get("name")][:3]})
    return out, company


def fetch_lever(slug, stop):
    try:
        d = fetch("https://api.lever.co/v0/postings/%s" % slug, params={"mode": "json"}, stop=stop, timeout=40)
    except FetchError as e:
        if e.status != 404:
            raise
        d = fetch("https://api.eu.lever.co/v0/postings/%s" % slug, params={"mode": "json"}, stop=stop, timeout=40)
    out = []
    for j in d if isinstance(d, list) else []:
        cat = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            parts.append("%s\n%s" % (lst.get("text", ""), _t(lst.get("content", ""))))
        parts.append(j.get("additionalPlain") or "")
        out.append({"title": j.get("text"), "company": slug.replace("-", " ").title(), "location": cat.get("location") or "",
                    "country_hint": j.get("country") or "", "remote": (j.get("workplaceType") == "remote"),
                    "description": "\n\n".join(p for p in parts if p).strip(), "url": j.get("hostedUrl"),
                    "apply_url": j.get("applyUrl") or j.get("hostedUrl"), "posted_at": j.get("createdAt"),
                    "job_type": cat.get("commitment") or "", "tags": [x for x in (cat.get("team"), cat.get("department")) if x]})
    return out, ""


def fetch_ashby(slug, stop):
    d = fetch("https://api.ashbyhq.com/posting-api/job-board/%s" % slug, params={"includeCompensation": "true"}, stop=stop, timeout=40)
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        locs = [j.get("location") or ""] + [s.get("location", "") for s in (j.get("secondaryLocations") or [])[:4]]
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append({"title": (j.get("title") or "").strip(), "company": slug.replace("-", " ").title(),
                    "location": " | ".join(l for l in locs if l), "country_hint": addr.get("addressCountry") or "",
                    "remote": bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
                    "description": j.get("descriptionPlain") or _t(j.get("descriptionHtml")), "url": j.get("jobUrl"),
                    "apply_url": j.get("applyUrl") or j.get("jobUrl"), "posted_at": j.get("publishedAt"),
                    "job_type": j.get("employmentType") or "", "salary_text": comp,
                    "tags": [x for x in (j.get("department"), j.get("team")) if x]})
    return out, ""


def fetch_recruitee(slug, stop):
    d = fetch("https://%s.recruitee.com/api/offers/" % slug, stop=stop, timeout=40)
    out, company = [], ""
    for j in d.get("offers", []):
        company = company or j.get("company_name") or ""
        loc = ", ".join(x for x in (j.get("city"), j.get("state_name"), j.get("country")) if x)
        sal = j.get("salary") or {}
        out.append({"title": j.get("title"), "company": j.get("company_name") or slug, "location": loc or ("Remote" if j.get("remote") else ""),
                    "country_hint": j.get("country_code") or "", "remote": bool(j.get("remote")),
                    "description": _t((j.get("description") or "") + "\n" + (j.get("requirements") or "")),
                    "url": j.get("careers_url"), "apply_url": j.get("careers_apply_url") or j.get("careers_url"),
                    "posted_at": j.get("published_at"), "job_type": (j.get("employment_type_code") or "").replace("_", " "),
                    "salary_min": sal.get("min"), "salary_max": sal.get("max"), "salary_currency": sal.get("currency") or "",
                    "tags": [j.get("department")] if j.get("department") else []})
    return out, company


def fetch_smartrecruiters(slug, stop):
    out, company, offset = [], "", 0
    while offset < 1000:
        d = fetch("https://api.smartrecruiters.com/v1/companies/%s/postings" % slug, params={"limit": 100, "offset": offset}, stop=stop, timeout=40)
        rows = d.get("content") or []
        for j in rows:
            loc = j.get("location") or {}
            company = company or (j.get("company") or {}).get("name") or ""
            out.append({"title": j.get("name"), "company": (j.get("company") or {}).get("name") or slug,
                        "location": ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x),
                        "country_hint": (loc.get("country") or "").upper(), "remote": bool(loc.get("remote")),
                        "description": "", "detail_ref": j.get("ref"),
                        "url": "https://jobs.smartrecruiters.com/%s/%s" % (slug, j.get("id")),
                        "apply_url": "https://jobs.smartrecruiters.com/%s/%s" % (slug, j.get("id")),
                        "posted_at": j.get("releasedDate"), "job_type": (j.get("typeOfEmployment") or {}).get("label") or "",
                        "tags": [x.get("label") for x in (j.get("function"), j.get("department")) if isinstance(x, dict) and x.get("label")]})
        offset += 100
        if len(rows) < 100:
            break
    return out, company


def smartrecruiters_detail(ref, stop):
    d = fetch(ref, stop=stop, timeout=30)
    secs = ((d.get("jobAd") or {}).get("sections") or {})
    parts = [_t((secs.get(k) or {}).get("text")) for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")]
    return "\n\n".join(p for p in parts if p)


def fetch_personio(slug, stop):
    xml = fetch("https://%s.jobs.personio.de/xml" % slug, expect="text", stop=stop, timeout=40)
    soup = BeautifulSoup(xml, "xml")
    out, company = [], ""
    for p in soup.find_all("position"):
        def tx(name):
            t = p.find(name)
            return t.text.strip() if t else ""
        company = company or tx("subcompany")
        desc = "\n\n".join("%s\n%s" % (d.find("name").text if d.find("name") else "", _t(d.find("value").text if d.find("value") else ""))
                           for d in p.find_all("jobDescription"))
        pid = tx("id")
        out.append({"title": tx("name"), "company": tx("subcompany") or slug, "location": tx("office"), "description": desc,
                    "url": "https://%s.jobs.personio.de/job/%s" % (slug, pid), "apply_url": "https://%s.jobs.personio.de/job/%s" % (slug, pid),
                    "posted_at": tx("createdAt"), "job_type": " ".join(x for x in (tx("employmentType"), tx("schedule")) if x),
                    "tags": [tx("department")] if tx("department") else []})
    return out, company


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby, "recruitee": fetch_recruitee,
            "smartrecruiters": fetch_smartrecruiters, "personio": fetch_personio}


def load_board(board, stop, max_age):
    """Jobs of one board, from cache when fresh."""
    cached = store.board_cache_get(board["id"], max_age)
    if cached is not None:
        row = store.q1("SELECT tracked_since FROM boards WHERE id = ?", (board["id"],))
        if row is not None and not row["tracked_since"]:
            try:                            # never snapshotted yet: start tracking from the cached list (baseline)
                import signals
                signals.record_board(board, cached, board.get("company") or "")
            except Exception:
                logging.getLogger("jobradar.signals").exception("baseline board %s", board.get("id"))
        return cached, True
    try:
        jobs, company = FETCHERS[board["provider"]](board["slug"], stop)
    except FetchError as e:
        store.board_fail(board["id"], e, dead=e.status in (404, 410) or (board["fails"] >= 3 and e.status and e.status < 500))
        raise
    if company:
        for j in jobs:
            j["company"] = company if j.get("company", "").lower() in ("", board["slug"].lower(), board["slug"].replace("-", " ").lower()) else j["company"]
    store.board_cache_put(board["id"], jobs, company)
    try:
        import signals                      # hiring signals: snapshot what this company has open today
        signals.record_board(board, jobs, company)
    except Exception:
        logging.getLogger("jobradar.signals").exception("snapshot board %s", board.get("id"))
    return jobs, False


class CompanyBoards(Source):
    id, name, kind = "companies", "Company career pages", "ats"
    homepage = ""
    about = ("Scans every registered company career board (Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters, Personio) "
             "in parallel. The list grows automatically as new companies are discovered.")
    coverage = "Worldwide · direct from employers"

    def search(self, q, ctx):
        boards = [dict(b) for b in store.q("SELECT id, provider, slug, company, fails FROM boards WHERE status != 'dead' ORDER BY jobs_count DESC")]
        skipped = len([b for b in boards if b["id"] in ctx.checkpoint])
        boards = [b for b in boards if b["id"] not in ctx.checkpoint]      # resume: skip boards already done
        if not boards:
            return
        max_age = int(ctx.settings.get("board_cache_hours") or 6) * 3600
        workers = max(2, min(16, int(ctx.settings.get("board_workers") or 8)))
        done = errors = matched = 0
        scanned = 0
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(load_board, b, ctx.stop, max_age): b for b in boards}
            for fut in cf.as_completed(futs):
                if ctx.stopped:
                    for f in futs:
                        f.cancel()
                    return
                b = futs[fut]
                done += 1
                try:
                    jobs, _ = fut.result()
                except Exception:
                    errors += 1
                    jobs = []
                scanned += len(jobs)
                detail_budget = 30
                for j in jobs:
                    j = dict(j)
                    j["_board"] = "%s:%s" % (b["provider"], b["slug"])
                    if ctx.match and not ctx.match(j):
                        continue
                    if b["provider"] == "smartrecruiters" and not j.get("description") and j.get("detail_ref") and detail_budget > 0:
                        detail_budget -= 1
                        try:
                            j["description"] = smartrecruiters_detail(j["detail_ref"], ctx.stop)
                        except Exception:
                            pass
                    matched += 1
                    yield j
                if ctx.board_done and not ctx.stopped:
                    ctx.board_done(b["id"])
                ctx.report("%d/%d companies · %d jobs scanned · %d match%s%s" % (
                    done + skipped, len(boards) + skipped, scanned, matched, (" · %d errors" % errors) if errors else "",
                    (" · resumed" if skipped else "")))

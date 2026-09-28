"""Public job boards with free, documented APIs/feeds (no key needed)."""
import re

from bs4 import BeautifulSoup

import geo
from net import fetch
from . import Source

JOBICY_GEO = {"US": "usa", "GB": "uk", "CA": "canada", "DE": "germany", "FR": "france", "ES": "spain", "NL": "netherlands",
              "PL": "poland", "PT": "portugal", "IT": "italy", "IE": "ireland", "SE": "sweden", "AU": "australia",
              "IN": "india", "BR": "brazil", "MX": "mexico", "AR": "argentina", "PH": "philippines", "ZA": "south-africa",
              "BE": "belgium", "CH": "switzerland", "AT": "austria", "DK": "denmark", "FI": "finland", "NO": "norway",
              "RO": "romania", "CZ": "czechia", "GR": "greece", "IL": "israel", "JP": "japan", "SG": "singapore",
              "AE": "uae", "NZ": "new-zealand", "CO": "colombia", "CL": "chile", "UA": "ukraine", "TR": "turkiye"}


class Remotive(Source):
    id, name, homepage = "remotive", "Remotive", "https://remotive.com"
    about = "Hand-picked remote jobs in tech, marketing, sales, support and more."
    coverage = "Remote · worldwide"
    server_search = True

    def search(self, q, ctx):
        n = 0
        for term in q.search_terms:
            data = fetch("https://remotive.com/api/remote-jobs", params={"search": term} if term else {}, stop=ctx.stop)
            for j in data.get("jobs", []):
                n += 1
                yield {"title": j.get("title"), "company": j.get("company_name"), "location": j.get("candidate_required_location") or "Remote",
                       "remote": True, "description_html": j.get("description"), "url": j.get("url"), "apply_url": j.get("url"),
                       "posted_at": j.get("publication_date"), "job_type": (j.get("job_type") or "").replace("_", " "),
                       "salary_text": j.get("salary") or "", "tags": j.get("tags") or [], "category": j.get("category")}
            ctx.report("%d jobs" % n)


class RemoteOK(Source):
    id, name, homepage = "remoteok", "Remote OK", "https://remoteok.com"
    about = "One of the largest remote job boards."
    coverage = "Remote · worldwide"

    def search(self, q, ctx):
        tags = []
        for g in q.groups:
            tags += [w for w in g if len(w) > 1]
        urls = ["https://remoteok.com/api"] + ["https://remoteok.com/api?tag=%s" % re.sub(r"[^a-z0-9+#-]", "", t) for t in dict.fromkeys(tags)][:6]
        seen = set()
        for u in urls:
            if ctx.stopped:
                return
            data = fetch(u, stop=ctx.stop)
            for j in data if isinstance(data, list) else []:
                if not isinstance(j, dict) or not j.get("position") or j.get("id") in seen:
                    continue
                seen.add(j.get("id"))
                smin, smax = j.get("salary_min") or None, j.get("salary_max") or None
                yield {"title": j.get("position"), "company": j.get("company"), "location": j.get("location") or "Remote",
                       "remote": True, "description_html": j.get("description"), "url": j.get("url"),
                       "apply_url": j.get("apply_url") or j.get("url"), "posted_at": j.get("date") or j.get("epoch"),
                       "salary_min": smin, "salary_max": smax, "salary_currency": "USD" if smin else "", "tags": j.get("tags") or [],
                       "mojibake": True}
            ctx.report("%d jobs" % len(seen))


class Jobicy(Source):
    id, name, homepage = "jobicy", "Jobicy", "https://jobicy.com"
    about = "Remote jobs with country (geo) filtering."
    coverage = "Remote · 35+ countries"
    server_search = True

    def search(self, q, ctx):
        params_list = []
        geo_slug = JOBICY_GEO.get(q.country, "")
        for term in q.search_terms[:5]:
            p = {"count": 100}
            if geo_slug:
                p["geo"] = geo_slug
            if term:
                p["tag"] = term
            params_list.append(p)
        seen = set()
        for p in params_list:
            if ctx.stopped:
                return
            try:
                data = fetch("https://jobicy.com/api/v2/remote-jobs", params=p, stop=ctx.stop)
            except Exception:
                if "geo" in p:          # unknown geo slug -> retry without it
                    p.pop("geo")
                    data = fetch("https://jobicy.com/api/v2/remote-jobs", params=p, stop=ctx.stop)
                else:
                    raise
            for j in data.get("jobs", []) or []:
                if j.get("id") in seen:
                    continue
                seen.add(j.get("id"))
                smin, smax = j.get("annualSalaryMin"), j.get("annualSalaryMax")
                yield {"title": j.get("jobTitle"), "company": j.get("companyName"), "location": j.get("jobGeo") or "Remote",
                       "remote": True, "description_html": j.get("jobDescription"), "url": j.get("url"), "apply_url": j.get("url"),
                       "posted_at": j.get("pubDate"), "job_type": ", ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else j.get("jobType"),
                       "salary_min": smin, "salary_max": smax, "salary_currency": j.get("salaryCurrency") or "",
                       "tags": (j.get("jobIndustry") or []) if isinstance(j.get("jobIndustry"), list) else []}
            ctx.report("%d jobs" % len(seen))


class Himalayas(Source):
    id, name, homepage = "himalayas", "Himalayas", "https://himalayas.app"
    about = "Large remote job marketplace (~100k jobs) with salaries and location restrictions."
    coverage = "Remote · worldwide"
    server_search = True

    def search(self, q, ctx):
        n, seen = 0, set()
        per_term = max(1, q.max_per_source // 20 // max(1, len(q.search_terms)))
        for term in q.search_terms:
            for page in range(1, min(per_term, 25) + 1):
                if ctx.stopped:
                    return
                if term:
                    data = fetch("https://himalayas.app/jobs/api/search", params={"q": term, "page": page}, stop=ctx.stop)
                else:
                    data = fetch("https://himalayas.app/jobs/api", params={"limit": 20, "offset": (page - 1) * 20}, stop=ctx.stop)
                jobs = data.get("jobs") or []
                if not jobs:
                    break
                for j in jobs:
                    key = j.get("guid") or j.get("applicationLink")
                    if key in seen:
                        continue
                    seen.add(key)
                    n += 1
                    locs = j.get("locationRestrictions") or []
                    yield {"title": j.get("title"), "company": j.get("companyName"),
                           "location": ", ".join(locs) if locs else "Remote (Worldwide)", "remote": True,
                           "description_html": j.get("description") or j.get("excerpt"), "url": j.get("applicationLink") or j.get("guid"),
                           "apply_url": j.get("applicationLink"), "posted_at": j.get("pubDate"), "job_type": j.get("employmentType") or "",
                           "salary_min": j.get("minSalary"), "salary_max": j.get("maxSalary"), "salary_currency": j.get("currency") or "",
                           "tags": (j.get("categories") or [])[:8], "country_list": locs}
                ctx.report("%d jobs" % n)
                if len(jobs) < 20:
                    break


class Arbeitnow(Source):
    id, name, homepage = "arbeitnow", "Arbeitnow", "https://www.arbeitnow.com"
    about = "Jobs in Germany and Europe, many with visa sponsorship, plus remote roles."
    coverage = "Europe (mainly Germany) · remote"

    def search(self, q, ctx):
        pages = max(1, min(8, q.max_per_source // 300 + 1))
        n = 0
        for page in range(1, pages + 1):
            if ctx.stopped:
                return
            data = fetch("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, stop=ctx.stop)
            rows = data.get("data") or []
            for j in rows:
                n += 1
                yield {"title": j.get("title"), "company": j.get("company_name"), "location": j.get("location") or "",
                       "country_hint": "DE" if not j.get("remote") else "", "remote": bool(j.get("remote")),
                       "description_html": j.get("description"), "url": j.get("url"), "apply_url": j.get("url"),
                       "posted_at": j.get("created_at"), "job_type": ", ".join(j.get("job_types") or []), "tags": j.get("tags") or []}
            ctx.report("%d jobs scanned" % n)
            if not (data.get("links") or {}).get("next"):
                break


class WorkingNomads(Source):
    id, name, homepage = "workingnomads", "Working Nomads", "https://www.workingnomads.com"
    about = "Curated remote jobs."
    coverage = "Remote · worldwide"

    def search(self, q, ctx):
        data = fetch("https://www.workingnomads.com/api/exposed_jobs/", stop=ctx.stop)
        n = 0
        for j in data if isinstance(data, list) else []:
            n += 1
            tags = j.get("tags") or ""
            yield {"title": j.get("title"), "company": j.get("company_name"), "location": j.get("location") or "Remote",
                   "remote": True, "description_html": j.get("description"), "url": j.get("url"), "apply_url": j.get("url"),
                   "posted_at": j.get("pub_date"), "tags": [t.strip() for t in tags.split(",")] if isinstance(tags, str) else tags}
        ctx.report("%d jobs" % n)


class WeWorkRemotely(Source):
    id, name, homepage = "weworkremotely", "We Work Remotely", "https://weworkremotely.com"
    about = "Well-known remote job board (RSS feed)."
    coverage = "Remote · worldwide"

    def search(self, q, ctx):
        xml = fetch("https://weworkremotely.com/remote-jobs.rss", expect="text", stop=ctx.stop)
        soup = BeautifulSoup(xml, "xml")
        n = 0
        for it in soup.find_all("item"):
            raw_title = (it.title.text if it.title else "").strip()
            company, _, title = raw_title.partition(": ")
            if not title:
                title, company = raw_title, ""
            region = it.find("region")
            n += 1
            yield {"title": title, "company": company, "location": (region.text if region else "") or "Remote", "remote": True,
                   "description_html": it.description.text if it.description else "", "url": it.link.text if it.link else "",
                   "apply_url": it.link.text if it.link else "", "posted_at": it.pubDate.text if it.pubDate else None,
                   "job_type": (it.find("type").text if it.find("type") else ""),
                   "tags": [it.category.text] if it.category else []}
        ctx.report("%d jobs" % n)

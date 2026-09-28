"""National job boards that publish schema.org JobPosting data and allow crawling of their listing and job
pages in robots.txt. JobRadar uses each site's own search, reads the structured job data from each job page,
caches every job page (downloaded once, reused for 7 days), waits between requests and never bypasses
bot protection. Sites that block bots (Cloudflare challenges) or disallow listings are intentionally absent."""
import json
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

import extract
import store
from net import Blocked, FetchError, fetch
from . import Source

SITES = [
    {"id": "keejob", "name": "Keejob", "country": "TN", "base": "https://www.keejob.com",
     "search": "https://www.keejob.com/offres-emploi/?keywords={q}&page={page}", "link": r"/offres-emploi/\d+/[^\"'#?]*", "per_page": 15},
    {"id": "jobberman", "name": "Jobberman", "country": "NG", "base": "https://www.jobberman.com",
     "search": "https://www.jobberman.com/jobs?q={q}&page={page}", "link": r"https://www\.jobberman\.com/listings/[a-z0-9-]+", "per_page": 16},
    {"id": "brightermonday", "name": "BrighterMonday Kenya", "country": "KE", "base": "https://www.brightermonday.co.ke",
     "search": "https://www.brightermonday.co.ke/jobs?q={q}&page={page}", "link": r"https://www\.brightermonday\.co\.ke/listings/[a-z0-9-]+", "per_page": 16},
]
CACHE_SECONDS = 7 * 86400


def _cached(url):
    r = store.q1("SELECT data, fetched_at FROM pages WHERE url = ?", (url,))
    if r and store.now() - r["fetched_at"] < CACHE_SECONDS:
        return json.loads(r["data"])
    return None


def _cache(url, data):
    store.run("INSERT INTO pages(url, fetched_at, data) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET fetched_at = excluded.fetched_at, "
              "data = excluded.data", (url, store.now(), json.dumps(data, ensure_ascii=False)))


def job_page(url, site, stop, fallback_title=""):
    """Structured job from one job page (cached)."""
    hit = _cached(url)
    if hit is not None:
        return hit
    html = fetch(url, expect="text", check_robots=True, stop=stop, timeout=25, retries=1)
    jobs = extract.jsonld_jobpostings(html, url)
    if jobs:
        j = jobs[0]
        if not j.get("company"):
            m = re.search(r'"hiringOrganization"\s*:\s*"([^"]+)"', html)
            j["company"] = m.group(1) if m else ""
    else:
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        j = {"title": (h1.get_text(" ", strip=True) if h1 else fallback_title), "company": "", "location": "",
             "description_html": str(soup.find("main") or soup.body or "")[:60000], "url": url}
    j["url"] = url
    j["apply_url"] = url
    j["country_hint"] = j.get("country_hint") or site["country"]
    j["description"] = extract.html_to_text(j.pop("description_html", "") or "")
    _cache(url, j)
    return j


class NationalBoards(Source):
    id, name, kind = "national", "National job boards", "board"
    about = ("Country job sites with structured job data and crawler-friendly rules: " +
             ", ".join("%s (%s)" % (s["name"], s["country"]) for s in SITES) +
             ". Uses each site's own search; every job page is cached so repeat searches are fast.")
    coverage = "Tunisia · Nigeria · Kenya (more coming)"
    server_search = True

    def search(self, q, ctx):
        sites = [s for s in SITES if not q.country or s["country"] == q.country]
        if not sites:
            ctx.report("no national board for this country yet")
            return
        total = 0
        for site in sites:
            if ctx.stopped:
                return
            budget = q.max_per_source if q.country else min(q.max_per_source, 60)
            max_pages = max(1, min(80, -(-budget // site["per_page"])))
            found = 0
            for term in q.search_terms[:5]:
                seen = set()
                for page in range(1, max_pages + 1):
                    if ctx.stopped or found >= budget:
                        break
                    url = site["search"].format(q=quote_plus(term), page=page)
                    try:
                        html = fetch(url, expect="text", check_robots=True, stop=ctx.stop, timeout=25)
                    except Blocked:
                        ctx.report("%s: robots.txt disallows search - skipped" % site["name"])
                        break
                    links = []
                    soup = BeautifulSoup(html, "lxml")
                    for a in soup.find_all("a", href=True):
                        href = urljoin(site["base"], a["href"]).split("#")[0]
                        if re.search(site["link"], href) and href not in seen:
                            seen.add(href)
                            links.append((href, a.get_text(" ", strip=True)))
                    if not links:
                        break
                    for href, text in links:
                        if ctx.stopped or found >= budget:
                            break
                        try:
                            j = job_page(href, site, ctx.stop, text)
                        except (Blocked, FetchError):
                            continue
                        found += 1
                        total += 1
                        yield dict(j)
                    ctx.report("%s: %d jobs (page %d)" % (site["name"], found, page))
        ctx.report("%d jobs from %d site(s)" % (total, len(sites)))

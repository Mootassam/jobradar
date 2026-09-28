"""Career-site crawler: visits the careers pages you add (any company website), follows job links on the
same site, and reads the schema.org JobPosting data that sites publish for Google Jobs.
Respects robots.txt, stays on the same domain, polite delays, page budget per site."""
import re
from collections import deque
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

import extract
import store
from net import Blocked, FetchError, fetch
from . import Source, ats

JOB_LINK_HINT = re.compile(r"job|career|position|opening|vacanc|stellen|emploi|offre|empleo|lavoro|vaga|werken|role|opportunit|join", re.I)
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp4|mp3|css|js|ico)(\?|$)", re.I)


def crawl_site(start, max_pages, stop, report=None):
    """Yield raw jobs found on one site."""
    host = urlparse(start).netloc.lower()
    queue, seen = deque([start]), {start}
    pages = 0
    while queue and pages < max_pages:
        if stop is not None and stop.is_set():
            return
        url = queue.popleft()
        try:
            r = fetch(url, expect="response", check_robots=True, stop=stop, timeout=20, retries=1)
        except (Blocked, FetchError):
            continue
        pages += 1
        if "html" not in (r.headers.get("content-type") or ""):
            continue
        html = r.text
        ats.discover(html, source=start)
        for j in extract.jsonld_jobpostings(html, url):
            j["url"] = j.get("url") or url
            j["apply_url"] = j.get("url")
            yield j
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = urldefrag(urljoin(url, a["href"]))[0]
            p = urlparse(href)
            if p.scheme not in ("http", "https") or p.netloc.lower() != host or href in seen or SKIP_EXT.search(href):
                continue
            if JOB_LINK_HINT.search(href) or JOB_LINK_HINT.search(a.get_text(" ", strip=True)[:80]):
                seen.add(href)
                queue.append(href)
        if report:
            report("%s: %d pages" % (host, pages))


class CareerSites(Source):
    id, name, kind = "sites", "Company websites (crawler)", "crawler"
    about = ("Crawls the careers pages you add in Sources and extracts every job they publish "
             "(schema.org JobPosting). Also discovers the company's ATS board automatically.")
    coverage = "Any website you add"

    def ready(self, settings):
        return bool(settings.get("crawl_sites"))

    def search(self, q, ctx):
        sites = [s.strip() for s in (ctx.settings.get("crawl_sites") or []) if s.strip().startswith("http")]
        per_site = int(ctx.settings.get("crawl_pages") or 40)
        n = 0
        for i, site in enumerate(sites):
            if ctx.stopped:
                return
            for j in crawl_site(site, per_site, ctx.stop):
                n += 1
                yield j
            ctx.report("%d/%d sites · %d jobs" % (i + 1, len(sites), n))
        store.refresh_companies()

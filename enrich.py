"""Company intelligence from the company's own public website.

Visits the most informative pages first (team / leadership / imprint / contact / about / careers - in several
languages), up to MAX_PAGES, respecting robots.txt and staying on the company's domain. Produces:
  - company profile: title, description, logo, address, founded, employees, socials
  - contact channels: emails (classified recruiting / general / personal), phones
  - people: recruiters, HR, leadership and hiring managers the company publishes (see recruiters.py)"""
import json
import queue
import re
import threading
from urllib.parse import urljoin, urlparse

import dns.resolver
from bs4 import BeautifulSoup

import extract
import geo
import recruiters
import store
from net import Blocked, FetchError, fetch

MAX_PAGES = 18
# Higher = visit earlier. Matched against the URL path and the link text.
PAGE_PRIORITY = [
    (100, r"team|equipe|équipe|notre-equipe|our-people|people|leadership|management|direction|fuehrung|führung|founders|"
          r"about-us/team|who-we-are|wer-wir-sind|quienes-somos|chi-siamo|staff|board|executive"),
    (90, r"impressum|imprint|legal-notice|legal|mentions-legales|mentions-légales|aviso-legal|note-legali"),
    (80, r"contact|kontakt|contacto|contatti|nous-contacter|get-in-touch|reach-us"),
    (70, r"career|careers|jobs|karriere|carriere|carrieres|recrutement|join-us|join|work-with-us|empleo|lavora|stellen"),
    (60, r"about|a-propos|qui-sommes|ueber-uns|uber-uns|about-us|company|entreprise|unternehmen|empresa|azienda"),
    (30, r"press|presse|news|media"),
]
_PRIO = [(s, re.compile(rx, re.I)) for s, rx in PAGE_PRIORITY]
COMMON_PATHS = ("/team", "/about", "/about-us", "/contact", "/impressum", "/imprint", "/careers", "/jobs", "/leadership",
                "/our-team", "/equipe", "/mentions-legales", "/kontakt", "/ueber-uns", "/company", "/legal")
SKIP = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|mp4|mp3|css|js|ico)(\?|$)|/(wp-admin|login|signin|cart|checkout|account)\b", re.I)
SOCIAL = re.compile(r"https?://(?:[a-z]+\.)?(linkedin\.com/company/[^\s\"'?#<]+|twitter\.com/[A-Za-z0-9_]+|x\.com/[A-Za-z0-9_]+|"
                    r"facebook\.com/[^\s\"'?#<]+|instagram\.com/[A-Za-z0-9_.]+|github\.com/[A-Za-z0-9_-]+|youtube\.com/[^\s\"'?#<]+|"
                    r"tiktok\.com/@[A-Za-z0-9_.]+)", re.I)
SOCIAL_SKIP = ("sharer", "share?", "intent/", "/plugins", "/dialog", "/hashtag", "/login", "/signup", "/policies")


def has_mx(domain):
    try:
        return bool(dns.resolver.resolve(domain, "MX", lifetime=5))
    except Exception:
        return False


def guess_domain(name):
    """Try name.com / .io / ... and accept only if the homepage title mentions the company."""
    key = store.company_key(name).replace(" ", "")
    first = geo.norm(name).split(" ")[0] if name else ""
    if len(key) < 3:
        return ""
    for tld in (".com", ".io", ".co", ".ai", ".app", ".tech", ".net"):
        dom = key + tld
        try:
            html = fetch("https://" + dom, expect="text", timeout=10, retries=0, check_robots=False)
        except FetchError:
            continue
        title = BeautifulSoup(html[:30000], "lxml").title
        t = geo.norm(title.text if title else "")
        if first and len(first) >= 3 and first in t:
            return dom
    return ""


def priority(url, text=""):
    path = urlparse(url).path or "/"
    best = 0
    for score, rx in _PRIO:
        if rx.search(path) or (text and rx.search(text)):
            best = max(best, score)
    return best - path.count("/")          # shallower pages first on ties


def _profile(soup, url):
    """Company profile from the home page: meta tags + schema.org Organization."""
    p = {}
    t = soup.find("title")
    if t:
        p["title"] = t.get_text(" ", strip=True)[:200]
    for sel, key in (('meta[name="description"]', "description"), ('meta[property="og:description"]', "description"),
                     ('meta[property="og:image"]', "logo")):
        m = soup.select_one(sel)
        if m and m.get("content") and not p.get(key):
            p[key] = urljoin(url, m["content"]) if key == "logo" else m["content"].strip()[:600]
    icon = soup.select_one('link[rel~="icon"], link[rel="apple-touch-icon"]')
    if icon and icon.get("href") and not p.get("logo"):
        p["logo"] = urljoin(url, icon["href"])
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads((tag.string or tag.get_text() or "").strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
                continue
            if not isinstance(n, dict):
                continue
            if "@graph" in n:
                stack.extend(n["@graph"] if isinstance(n["@graph"], list) else [n["@graph"]])
            types = n.get("@type") if isinstance(n.get("@type"), list) else [n.get("@type")]
            if not any(x in ("Organization", "Corporation", "LocalBusiness", "Company", "EmploymentAgency", "ProfessionalService") for x in types):
                continue
            if n.get("description") and not p.get("description"):
                p["description"] = str(n["description"])[:600]
            logo = n.get("logo")
            if isinstance(logo, dict):
                logo = logo.get("url")
            if logo and isinstance(logo, str):
                p["logo"] = urljoin(url, logo)
            addr = n.get("address")
            if isinstance(addr, list):
                addr = addr[0] if addr else None
            if isinstance(addr, dict):
                country = addr.get("addressCountry")
                country = country.get("name") if isinstance(country, dict) else country
                p["address"] = ", ".join(str(x) for x in (addr.get("streetAddress"), addr.get("postalCode"), addr.get("addressLocality"),
                                                          addr.get("addressRegion"), country) if x)[:250]
            elif isinstance(addr, str):
                p["address"] = addr[:250]
            if n.get("foundingDate"):
                p["founded"] = str(n["foundingDate"])[:20]
            emp = n.get("numberOfEmployees")
            if isinstance(emp, dict):
                emp = emp.get("value") or "-".join(str(x) for x in (emp.get("minValue"), emp.get("maxValue")) if x)
            if emp:
                p["employees"] = str(emp)[:30]
            for k in ("email", "telephone"):
                if n.get(k):
                    p.setdefault("_" + k, []).append(str(n[k]).replace("mailto:", "").replace("tel:", ""))
    return p


def enrich_company(key, stop=None):
    c = store.q1("SELECT * FROM companies WHERE key = ?", (key,))
    if c is None:
        return None
    domain = c["domain"]
    if not domain:
        for r in store.q("SELECT emails, apply_url FROM jobs WHERE company_key = ? LIMIT 50", (key,)):
            domain = extract.company_domain(r["apply_url"], json.loads(r["emails"] or "[]"))
            if domain:
                break
    if domain and any(b in domain for b in extract.JOB_BOARD_DOMAINS):
        domain = ""                      # a job board is never the company's own website
    if not domain:
        domain = guess_domain(c["name"])
    if not domain:
        store.run("UPDATE companies SET domain = '', enrich_status = ?, enriched_at = ? WHERE key = ?", ("no website found - set it manually", store.now(), key))
        return dict_company(key)

    countries = [r["country"] for r in store.q("SELECT country FROM jobs WHERE company_key = ? AND country != '' LIMIT 30", (key,))]
    region = max(set(countries), key=countries.count) if countries else ""
    base = "https://" + domain
    frontier = {base: 1000}
    for p in COMMON_PATHS:
        frontier.setdefault(base + p, priority(base + p) - 5)     # guesses rank just below real links
    seen, pages = set(), []
    emails, phones, socials, people = [], [], [], []
    profile = {}
    host = domain
    while frontier and len(pages) < MAX_PAGES:
        if stop is not None and stop.is_set():
            break
        url = max(frontier, key=frontier.get)
        frontier.pop(url)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = fetch(url, expect="response", check_robots=True, timeout=15, retries=1)
        except (Blocked, FetchError):
            continue
        if "html" not in (r.headers.get("content-type") or ""):
            continue
        final_host = urlparse(r.url).netloc.lower().replace("www.", "")
        if final_host and domain not in final_host and final_host not in domain:
            continue                                 # redirected to another site
        if url == base:
            host = final_host or domain
        html = r.text
        pages.append(r.url)
        soup = BeautifulSoup(html, "lxml")
        if url == base:
            profile = _profile(soup, r.url)
        for a in soup.select('a[href^="mailto:"]'):
            e = a["href"][7:].split("?")[0].strip().lower()
            if e and "@" in e and e not in emails and not any(b in e for b in extract.BAD_EMAIL_PARTS):
                emails.append(e)
        for a in soup.select('a[href^="tel:"]'):
            for ph in extract.find_phones(a["href"][4:], region):
                if ph not in phones:
                    phones.append(ph)
        text = soup.get_text("\n")
        for e in extract.find_emails(text):
            if e not in emails:
                emails.append(e)
        for ph in extract.find_phones(text[:40000], region):
            if ph not in phones:
                phones.append(ph)
        for m in SOCIAL.finditer(html):
            s = "https://" + m.group(1).rstrip("/\\")
            if s not in socials and not any(x in s for x in SOCIAL_SKIP):
                socials.append(s)
        people += recruiters.people_from_html(html, r.url, c["name"], region)
        # queue more same-site pages, most informative first
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"]).split("#")[0].rstrip("/")
            ph = urlparse(href)
            if ph.scheme not in ("http", "https") or ph.netloc.lower().replace("www.", "") != host or SKIP.search(href):
                continue
            if href in seen or href + "/" in seen:
                continue
            score = priority(href, a.get_text(" ", strip=True)[:60])
            if score > 0 and score > frontier.get(href, -999):
                frontier[href] = score

    for e in profile.pop("_email", []):
        if e.lower() not in emails:
            emails.append(e.lower())
    for t in profile.pop("_telephone", []):
        for ph in extract.find_phones(t, region):
            if ph not in phones:
                phones.append(ph)
    # company-domain emails first; recruiting inboxes on top
    emails = sorted(set(emails), key=lambda e: (0 if e.endswith("@" + domain) or e.endswith("." + domain) else 1,
                                               {"recruiting": 0, "personal": 1, "general": 2, "other": 3}[recruiters.email_type(e)], e))[:30]
    types = {e: recruiters.email_type(e) for e in emails}
    people = recruiters.merge(people)
    # attach published personal emails to the right people (only exact matches)
    for p in people:
        if not p.get("email"):
            p["email"] = next((e for e in emails if types[e] == "personal" and recruiters.email_belongs_to(e, p["name"])), "")
    # A fresh scan replaces what we previously read from the website; contacts named in job posts stay.
    store.run("DELETE FROM people WHERE company_key = ? AND source != 'job post'", (key,))
    store.save_people(key, people)
    status = "ok" if (emails or phones or people) else ("no contacts found" if pages else "website unreachable")
    if people:
        status += " · %d people" % len(people)
    if emails and not has_mx(domain):
        status += " · domain has no MX"
    store.run("UPDATE companies SET domain = ?, emails = ?, phones = ?, socials = ?, pages = ?, enriched_at = ?, enrich_status = ?, "
              "title = ?, description = ?, logo = ?, address = ?, founded = ?, employees = ?, email_types = ? WHERE key = ?",
              (domain, json.dumps(emails), json.dumps(phones[:12]), json.dumps(socials[:12]), json.dumps(pages), store.now(), status,
               profile.get("title", ""), profile.get("description", ""), profile.get("logo", ""), profile.get("address", ""),
               profile.get("founded", ""), profile.get("employees", ""), json.dumps(types), key))
    return dict_company(key)


def dict_company(key):
    c = store.dict_row(store.q1("SELECT * FROM companies WHERE key = ?", (key,)), store.COMPANY_JSON)
    if c is not None:
        c["people"] = store.company_people(key)
    return c


# ---------------------------------------------------------------- background bulk enrichment

class _Bulk:
    def __init__(self):
        self.q = queue.Queue()
        self.total = 0
        self.done = 0
        self.current = ""
        self.stop = threading.Event()
        self.threads = []
        self.lock = threading.Lock()
        self.workers = 3            # different companies = different sites, so a few in parallel is still polite

    def add(self, keys):
        with self.lock:
            for k in keys:
                self.q.put(k)
                self.total += 1
            self.threads = [t for t in self.threads if t.is_alive()]
            if not self.threads:
                self.stop.clear()
            while len(self.threads) < self.workers:
                t = threading.Thread(target=self._work, daemon=True, name="enrich")
                t.start()
                self.threads.append(t)

    def _work(self):
        while not self.stop.is_set():
            try:
                k = self.q.get(timeout=2)
            except queue.Empty:
                break
            self.current = k
            try:
                enrich_company(k, self.stop)
            except Exception:
                pass
            with self.lock:
                self.done += 1
        with self.lock:
            if self.q.empty() and all(not t.is_alive() or t is threading.current_thread() for t in self.threads):
                self.total = self.done = 0
                self.current = ""

    def status(self):
        return {"total": self.total, "done": self.done, "current": self.current,
                "running": any(t.is_alive() for t in self.threads)}

    def cancel(self):
        self.stop.set()
        with self.q.mutex:
            self.q.queue.clear()


BULK = _Bulk()

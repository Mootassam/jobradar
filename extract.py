"""Turning raw job data into clean fields: HTML -> text, emails, phone numbers, salaries,
schema.org JobPosting (JSON-LD) parsing, company domains."""
import html as htmllib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import phonenumbers
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- text

def html_to_text(value, limit=60000):
    if not value:
        return ""
    s = str(value)
    if "&lt;" in s and "<" not in s[:200]:
        s = htmllib.unescape(s)          # Greenhouse double-encodes its HTML
    if "<" not in s:
        return _tidy(htmllib.unescape(s))[:limit]
    soup = BeautifulSoup(s, "lxml")
    for t in soup(["script", "style", "noscript", "iframe", "svg"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("\n• ")
    for blk in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "section"]):
        blk.insert_after("\n")
    return _tidy(soup.get_text())[:limit]


def _tidy(s):
    s = s.replace("\xa0", " ").replace("​", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fix_mojibake(s):
    """RemoteOK sometimes double-encodes UTF-8 ("weâ\x80\x99re")."""
    if s and ("â\x80" in s or "Ã" in s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


# ---------------------------------------------------------------- contacts

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])")
OBFUSCATED_RE = re.compile(r"([A-Za-z0-9._%+-]{1,64})\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9-]+)\s*[\[(]\s*dot\s*[\])]\s*([A-Za-z]{2,24})", re.I)
BAD_EMAIL_PARTS = ("example.", "domain.com", "email.com", "yourname", "sentry.", "wixpress", "@2x", ".png", ".jpg", ".jpeg",
                   ".gif", ".svg", ".webp", "noreply", "no-reply", "donotreply", "do-not-reply", "u003e", "@sentry")


def find_emails(text):
    if not text:
        return []
    found = []
    for m in EMAIL_RE.finditer(text):
        found.append(m.group(1))
    for m in OBFUSCATED_RE.finditer(text):
        found.append("%s@%s.%s" % m.groups())
    out = []
    for e in found:
        e = e.strip(".").lower()
        if any(b in e for b in BAD_EMAIL_PARTS) or len(e) > 120:
            continue
        if e not in out:
            out.append(e)
    return out[:20]


def find_phones(text, region=""):
    """International-format phones anywhere + local-format phones for the job's country."""
    if not text:
        return []
    regions = [region.upper()] if region and len(region) == 2 else []
    regions.append(None)
    out = []
    for reg in regions:
        try:
            matcher = phonenumbers.PhoneNumberMatcher(text, reg or "ZZ", leniency=phonenumbers.Leniency.VALID, max_tries=200)
            for m in matcher:
                num = phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                digits = re.sub(r"\D", "", num)
                if len(digits) < 8 or len(set(digits)) < 4:
                    continue
                if num not in out:
                    out.append(num)
        except Exception:
            continue
    return out[:10]


# ---------------------------------------------------------------- salary

CURRENCY_SIGNS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY", "₺": "TRY", "₦": "NGN", "R$": "BRL", "CHF": "CHF",
                  "AED": "AED", "SAR": "SAR", "MAD": "MAD", "CAD": "CAD", "AUD": "AUD", "USD": "USD", "EUR": "EUR", "GBP": "GBP"}
_SAL_RE = re.compile(r"(R\$|CHF|AED|SAR|MAD|CAD|AUD|USD|EUR|GBP|[$€£₹¥₺₦])\s?(\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?)\s?([kK])?"
                     r"(?:\s?(?:-|–|to)\s?(?:R\$|CHF|AED|SAR|MAD|CAD|AUD|USD|EUR|GBP|[$€£₹¥₺₦])?\s?(\d{1,3}(?:[,.\s]\d{3})*(?:\.\d+)?)\s?([kK])?)?")


def _num(s, k):
    s2 = re.sub(r"[,\s]", "", s)
    # "120.000" / "1.200.000" use dots as thousands separators
    if s2.count(".") > 1 or (s2.count(".") == 1 and len(s2.split(".")[1]) == 3):
        s2 = s2.replace(".", "")
    v = float(s2)
    return v * 1000 if k else v


# "2 500 € brut", "1 800 - 2 200 DT", "45k€" - currency written after the amount (FR / Maghreb / much of Europe)
_SUFFIX_CUR = {"€": "EUR", "eur": "EUR", "euros": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "dt": "TND", "tnd": "TND", "dinars": "TND",
               "dh": "MAD", "mad": "MAD", "dirhams": "MAD", "da": "DZD", "dzd": "DZD", "aed": "AED", "sar": "SAR", "chf": "CHF"}
_SAL_SUFFIX_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ .,  ]\d{3})*(?:[.,]\d{1,2})?)\s?([kK])?\s?"
                            r"(?:(?:-|–|à|to|bis)\s?(\d{1,3}(?:[ .,  ]\d{3})*(?:[.,]\d{1,2})?)\s?([kK])?\s?)?"
                            r"(€|\$|£|eur\b|euros\b|usd\b|dt\b|tnd\b|dinars\b|dh\b|mad\b|dirhams\b|da\b|dzd\b|aed\b|sar\b|chf\b)", re.I)


def _parse_suffix_salary(text, require_context):
    for m in _SAL_SUFFIX_RE.finditer(text):
        if require_context and not m.group(3) and not _SAL_CONTEXT.search(text[max(0, m.start() - 60): m.end() + 40]):
            continue
        try:
            lo = _num(m.group(1).replace(" ", " ").replace(" ", " "), m.group(2))
            hi = _num(m.group(3).replace(" ", " ").replace(" ", " "), m.group(4) or m.group(2)) if m.group(3) else None
        except ValueError:
            continue
        if lo < 100 and not m.group(2):
            continue
        return lo, hi, _SUFFIX_CUR.get(m.group(5).lower(), ""), m.group(0).strip()
    return None, None, "", ""


_SAL_CONTEXT = re.compile(r"salar|compensation|\bpay\b|base pay|wage|remunera|rémunéra|salaire|gehalt|vergütung|sueldo|retribuci|"
                          r"stipendio|ote\b|per (?:year|annum|month|hour)|/\s?(?:yr|year|month|mo|hour|hr)\b|annual|brut|gross|راتب", re.I)


def parse_salary(text, require_context=False):
    """'$120k – $150k' -> (120000, 150000, 'USD', '$120k – $150k'). Returns (None, None, '', '') if nothing.
    require_context=True (free description text): only accept an amount that is clearly pay - a salary word nearby,
    or a range - so "€800 learning budget" is never shown as the salary."""
    if not text:
        return None, None, "", ""
    text = str(text)
    m = None
    for cand in _SAL_RE.finditer(text):
        if not require_context or cand.group(4) or _SAL_CONTEXT.search(text[max(0, cand.start() - 60): cand.end() + 40]):
            m = cand
            break
    if not m:
        return _parse_suffix_salary(text, require_context)
    try:
        lo = _num(m.group(2), m.group(3))
        hi = _num(m.group(4), m.group(5) or m.group(3)) if m.group(4) else None
    except ValueError:
        return None, None, "", ""
    if lo < 100 and not m.group(3):        # "$25" is usually an hourly rate or noise
        return None, None, "", m.group(0).strip()
    return lo, hi, CURRENCY_SIGNS.get(m.group(1), ""), m.group(0).strip()


# ---------------------------------------------------------------- dates

def to_ts(value):
    """ISO string / epoch seconds / epoch ms -> unix seconds (int) or None."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        v = float(value)
        if v > 1e12:
            v /= 1000
        return int(v) if v > 0 else None
    s = str(value).strip().replace("Z", "+00:00").replace(" UTC", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S%z", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- domains

# Stems (no TLD) so every country domain of a job site is excluded too (arbeitnow.ch, indeed.fr, ...)
JOB_BOARD_DOMAINS = ("greenhouse.", "lever.co", "ashbyhq.", "recruitee.", "smartrecruiters.", "workable.", "personio.",
                     "remotive.", "remoteok.", "jobicy.", "himalayas.", "arbeitnow.", "workingnomads.", "weworkremotely.",
                     "linkedin.", "indeed.", "glassdoor.", "adzuna.", "jooble.", "usajobs.", "bamboohr.", "myworkdayjobs.",
                     "icims.", "taleo.", "jobvite.", "breezy.hr", "teamtailor.", "join.com", "google.", "bit.ly", "t.co",
                     "ziprecruiter.", "monster.", "stepstone.", "welcometothejungle.", "wellfound.", "angel.co", "dice.com",
                     "careerbuilder.", "simplyhired.", "totaljobs.", "reed.co.uk", "seek.com", "naukri.", "bayt.", "rekrute.",
                     "keejob.", "jobberman.", "brightermonday.", "tanitjobs.", "optioncarriere.", "careerjet.", "emploitic.",
                     "reliefweb.", "wuzzuf.", "emploi.ma", "emploi.tn", "emploi.dz", "hellowork.", "apec.fr", "cadremploi.",
                     "francetravail.", "pole-emploi.", "infojobs.", "xing.", "kununu.", "jobteaser.", "indeed.", "jobrapido.",
                     "talent.com", "neuvoo.", "jora.", "glints.", "jobstreet.", "naukrigulf.", "gulftalent.", "drjobpro.",
                     "akhtaboot.", "tanqeeb.", "forasna.", "jobzella.", "fuzu.", "myjobmag.", "ngcareers.", "pnet.", "careers24.",
                     "workday.com", "successfactors.", "oraclecloud.com", "smartrecruiters.", "recruitee.", "jazzhr.", "zohorecruit.")
FREE_MAIL = ("gmail.com", "yahoo.", "hotmail.", "outlook.", "live.com", "icloud.com", "aol.com", "proton", "gmx.", "mail.ru", "yandex.")


def domain_of(url):
    try:
        host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def company_domain(apply_url="", emails=()):
    """A likely company website domain, skipping job boards and free-mail providers."""
    for e in emails or ():
        d = e.split("@")[-1]
        if not any(f in d for f in FREE_MAIL) and not any(b in d for b in JOB_BOARD_DOMAINS):
            return d
    d = domain_of(apply_url or "")
    if d and not any(b in d for b in JOB_BOARD_DOMAINS):
        return root_site(d)
    return ""


_SUB_PREFIX = re.compile(r"^(careers?|jobs?|join|work|apply|hiring|talent|karriere|carrieres?|emplois?|recrutement|stellen)\.", re.I)


def root_site(domain):
    """careers.airbnb.com -> airbnb.com (team/imprint pages live on the main site)."""
    return _SUB_PREFIX.sub("", domain) if domain.count(".") >= 2 else domain


# ---------------------------------------------------------------- schema.org JobPosting

def jsonld_jobpostings(html_text, page_url=""):
    """All JobPosting objects embedded in a page (JSON-LD), normalized to our job dict shape."""
    soup = BeautifulSoup(html_text, "lxml")
    out = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            if "@graph" in node:
                stack.extend(node["@graph"] if isinstance(node["@graph"], list) else [node["@graph"]])
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" in types:
                out.append(_jobposting(node, page_url))
    return out


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _jobposting(n, page_url):
    org = _first(n.get("hiringOrganization")) or {}
    if isinstance(org, str):
        org = {"name": org}
    locs = n.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    loc_parts = []
    country = ""
    for l in locs:
        addr = (l or {}).get("address") if isinstance(l, dict) else None
        if isinstance(addr, dict):
            bits = [addr.get("addressLocality"), addr.get("addressRegion"), _country_val(addr.get("addressCountry"))]
            loc_parts.append(", ".join(b for b in bits if b))
            country = country or _country_val(addr.get("addressCountry"))
        elif isinstance(addr, str):
            loc_parts.append(addr)
    remote = str(n.get("jobLocationType", "")).upper() == "TELECOMMUTE"
    sal = n.get("baseSalary") or {}
    smin = smax = None
    cur = ""
    if isinstance(sal, dict):
        cur = sal.get("currency", "") or ""
        val = sal.get("value") or {}
        if isinstance(val, dict):
            smin, smax = _float(val.get("minValue") or val.get("value")), _float(val.get("maxValue"))
        else:
            smin = _float(val)
    return {
        "title": htmllib.unescape(str(n.get("title") or "")).strip(),
        "company": str(org.get("name") or "").strip(),
        "company_url": org.get("sameAs") or org.get("url") or "",
        "location": " | ".join(loc_parts) or ("Remote" if remote else ""),
        "country_hint": country,
        "remote": remote,
        "description_html": n.get("description") or "",
        "url": n.get("url") or page_url,
        "posted_at": to_ts(n.get("datePosted")),
        "job_type": ", ".join(n.get("employmentType")) if isinstance(n.get("employmentType"), list) else (n.get("employmentType") or ""),
        "salary_min": smin, "salary_max": smax, "salary_currency": cur,
    }


def _country_val(v):
    if isinstance(v, dict):
        return v.get("name") or v.get("@id") or ""
    return v or ""


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

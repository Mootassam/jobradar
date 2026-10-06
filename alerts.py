"""Import jobs from job-alert emails in your own mailbox (LinkedIn, Indeed, Glassdoor, and others).
You set up free job alerts on those sites; JobRadar reads the alert emails (read-only IMAP) and turns every
job in them into a row - the legal way to get their jobs, with no scraping and no risk to your accounts."""
import email
import email.utils
import imaplib
import re
import threading
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

import engine
import store

PATTERNS = [
    ("linkedin", re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I), "https://www.linkedin.com/jobs/view/%s/"),
    ("indeed", re.compile(r"indeed\.[a-z.]+/(?:rc/clk|viewjob|pagead/clk|m/viewjob)[^\"'\s>]*?jk=([a-f0-9]{8,20})", re.I), "https://www.indeed.com/viewjob?jk=%s"),
    ("glassdoor", re.compile(r"glassdoor\.[a-z.]+/(?:partner/jobListing\.htm|job-listing/[^\"'\s>]*?)[^\"'\s>]*?(?:jobListingId|jl)=(\d+)", re.I), "https://www.glassdoor.com/job-listing/?jl=%s"),
]
SENDERS = ("linkedin.com", "indeed.com", "indeed.", "glassdoor.com", "glassdoor.")
STATE = {"running": False, "message": "", "imported": 0, "new": 0, "emails": 0, "error": ""}


def _decode(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _html_of(msg):
    html = text = ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue
        s = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if ctype == "text/html" and not html:
            html = s
        elif ctype == "text/plain" and not text:
            text = s
    return html, text


def parse_alert(html, sent_ts=None):
    """Jobs inside one alert email."""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for site, rx, canon in PATTERNS:
            m = rx.search(href)
            if not m:
                continue
            jid = m.group(1)
            if (site, jid) in seen:
                continue
            title = a.get_text(" ", strip=True)
            block = a.find_parent(["td", "table", "div"]) or a.parent
            lines = [l.strip() for l in block.get_text("\n").split("\n") if l.strip()] if block else []
            if not title or len(title) < 4 or title.lower() in ("view job", "apply", "see job", "voir l'offre", "apply now"):
                title = next((l for l in lines if len(l) > 4 and not l.lower().startswith(("view", "apply", "http"))), "")
            if not title:
                continue
            company, location = "", ""
            rest = [l for l in lines if l != title][:4]
            for l in rest:
                if "·" in l or " - " in l:
                    parts = [p.strip() for p in re.split(r"·| - ", l) if p.strip()]
                    company = company or (parts[0] if parts else "")
                    location = location or (parts[1] if len(parts) > 1 else "")
                elif not company and len(l) < 60:
                    company = l
                elif not location and len(l) < 80:
                    location = l
            seen.add((site, jid))
            out.append({"title": title[:200], "company": company[:120], "location": location[:120], "url": canon % jid,
                        "apply_url": canon % jid, "posted_at": sent_ts, "site": site})
    return out


def run_import():
    if STATE["running"]:
        return False
    st = engine.settings()
    if not (st.get("imap_user") and st.get("imap_password")):
        STATE.update(error="Add your email and app password first", running=False)
        return False
    STATE.update(running=True, message="Connecting…", imported=0, new=0, emails=0, error="")
    threading.Thread(target=_import, args=(st,), daemon=True, name="alerts").start()
    return True


def _import(st):
    try:
        M = imaplib.IMAP4_SSL(st.get("imap_host") or "imap.gmail.com", 993, timeout=30)
        M.login(st["imap_user"], st["imap_password"])
        M.select(st.get("imap_folder") or "INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=int(st.get("imap_days") or 14))).strftime("%d-%b-%Y")
        ids = set()
        for sender in ("linkedin.com", "indeed.com", "glassdoor.com"):
            typ, data = M.search(None, '(SINCE %s FROM "%s")' % (since, sender))
            if typ == "OK" and data and data[0]:
                ids.update(data[0].split())
        STATE["message"] = "Reading %d emails…" % len(ids)
        for i, mid in enumerate(sorted(ids)):
            typ, data = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1])
            sender = _decode(msg.get("From")).lower()
            if not any(s in sender for s in SENDERS):
                continue
            try:
                sent = int(email.utils.parsedate_to_datetime(msg.get("Date")).timestamp())
            except Exception:
                sent = None
            html, _ = _html_of(msg)
            if not html:
                continue
            STATE["emails"] += 1
            for raw in parse_alert(html, sent):
                job = engine.normalize(raw, raw["site"] + "-alert")
                if not job:
                    continue
                jid, is_new = store.upsert_job(job)
                if jid is None:          # deleted by the user earlier
                    continue
                STATE["imported"] += 1
                STATE["new"] += 1 if is_new else 0
            STATE["message"] = "%d/%d emails · %d jobs" % (i + 1, len(ids), STATE["imported"])
        M.logout()
        store.refresh_companies()
        STATE["message"] = "Done: %d jobs from %d alert emails (%d new)" % (STATE["imported"], STATE["emails"], STATE["new"])
        if STATE["new"]:
            store.notify("%d new jobs imported from your job-alert emails" % STATE["new"], "#/jobs?source=alert")
    except imaplib.IMAP4.error as e:
        STATE["error"] = "Login failed - for Gmail use an App Password (not your normal password). %s" % str(e)[:120]
    except Exception as e:
        STATE["error"] = str(e)[:200]
    finally:
        STATE["running"] = False

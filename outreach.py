"""Spontaneous applications - reach the hidden job market.

1. Finder: companies in your country / field that publish a real contact (an HR person, a jobs@ inbox, or a general
   address), ranked by hiring signals, your match with their jobs and the quality of the contact. Companies from
   your Lead Finder database can be added too.
2. Drafts: a personal email per company from your template (EN / FR picked from the company's country), with your
   best CV attached. You review and approve every email - nothing is sent without your approval.
3. Sender: your own mailbox (SMTP), a small daily limit, random gaps between emails, office hours only, never the same
   company twice. Stops by itself on login errors or repeated failures.
4. Follow-up drafts after N days without an answer; replies, interview invitations, rejections and bounces are
   detected in your inbox (read-only) and shown here."""
import email
import email.utils
import imaplib
import json
import logging
import mimetypes
import os
import random
import re
import smtplib
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage

import applicant
import extract
import geo
import recruiters
import skills
import store
import synonyms

log = logging.getLogger("jobradar.outreach")
FR_COUNTRIES = {"TN", "MA", "DZ", "FR", "BE", "LU", "SN", "CI", "CM", "MC", "CD", "BJ", "BF", "ML", "NE", "TG", "GA", "MG", "HT"}
SENDER = {"state": "idle", "message": "", "last_sent": 0, "sent_today": 0, "last_check": 0, "replies": 0}
_wake = threading.Event()

DEFAULT_TEMPLATES = {
    "en": {
        "subject": "Spontaneous application - {my_title}",
        "body": "{greeting}\n\nI'm {my_name}, {my_title_a} with {years} of experience in {my_skills}. I follow {company} with interest and "
                "I'd love to contribute to your team.\n\nEven if you have no open position right now, I'd be glad to be considered for "
                "current or upcoming opportunities. My CV is attached.\n\nWould you have 15 minutes for a short call in the coming days?\n\n"
                "Best regards,\n{my_name}\n{my_phone}\n{my_linkedin}",
    },
    "fr": {
        "subject": "Candidature spontanée - {my_title}",
        "body": "{greeting}\n\nJe m'appelle {my_name}, {my_title_a} avec {years} d'expérience en {my_skills}. Je suis avec intérêt "
                "l'activité de {company} et je serais ravi(e) de rejoindre votre équipe.\n\nMême si aucun poste n'est ouvert actuellement, je "
                "vous serais reconnaissant(e) de considérer ma candidature pour vos besoins actuels ou à venir. Vous trouverez mon CV en pièce jointe."
                "\n\nSeriez-vous disponible pour un court échange dans les prochains jours ?\n\nBien cordialement,\n{my_name}\n{my_phone}\n{my_linkedin}",
    },
}
FOLLOWUP = {
    "en": "{greeting}\n\nI'm following up on my application sent on {sent_date}. I'm still very interested in joining {company} and I'd be "
          "happy to share more about my experience.\n\nThank you for your time,\n{my_name}\n{my_phone}",
    "fr": "{greeting}\n\nJe me permets de revenir vers vous au sujet de ma candidature envoyée le {sent_date}. Je reste très motivé(e) à "
          "l'idée de rejoindre {company} et je serais heureux(se) d'échanger avec vous.\n\nMerci pour votre temps,\n{my_name}\n{my_phone}",
}
REPLY_KINDS = [
    ("auto", r"out of office|automatic reply|auto-reply|autoreply|absent du bureau|réponse automatique|abwesenheit|fuera de la oficina|"
             r"je suis absent|currently away|on leave until"),
    ("rejection", r"unfortunately|not moving forward|not be moving forward|other candidates|no suitable|not able to offer|regret to|"
                  r"malheureusement|ne pas donner suite|pas de suite favorable|ne correspond pas|pas retenue?|leider|lamentablemente|"
                  r"no position available|no openings|aucun poste"),
    ("interview", r"interview|entretien|call with|a call|appel|meet you|rencontrer|available for|disponible pour|disponibilités|"
                  r"schedule|planifier|rendez-vous|vorstellungsgespräch|entrevista|next step|prochaine étape|test technique|technical test"),
]


def settings():
    import engine
    s = engine.settings()
    host = s.get("smtp_host") or ("smtp.gmail.com" if "gmail" in (s.get("imap_host") or "gmail") else "")
    return {"host": host, "port": int(s.get("smtp_port") or 465), "user": s.get("smtp_user") or s.get("imap_user") or "",
            "password": s.get("smtp_password") or s.get("imap_password") or "", "daily": max(1, min(50, int(s.get("outreach_daily_limit") or 15))),
            "gap": max(1, int(s.get("outreach_gap_min") or 4)), "window": s.get("outreach_window") or "09:00-18:00",
            "weekdays": int(s.get("outreach_weekdays") if s.get("outreach_weekdays") is not None else 1),
            "followup_days": int(s.get("outreach_followup_days") or 0), "paused": int(s.get("outreach_paused") or 0),
            "attach_cv": int(s.get("outreach_attach_cv") if s.get("outreach_attach_cv") is not None else 1),
            "imap_host": s.get("imap_host") or "imap.gmail.com", "imap_user": s.get("imap_user") or "", "imap_password": s.get("imap_password") or ""}


def templates():
    t = store.get_setting("outreach_templates", {}) or {}
    out = {}
    for lang, d in DEFAULT_TEMPLATES.items():
        out[lang] = {"subject": (t.get(lang) or {}).get("subject") or d["subject"], "body": (t.get(lang) or {}).get("body") or d["body"]}
    return out


def save_templates(data):
    cur = templates()
    for lang in ("en", "fr"):
        d = data.get(lang) or {}
        for k in ("subject", "body"):
            if isinstance(d.get(k), str) and d[k].strip():
                cur[lang][k] = d[k][: 300 if k == "subject" else 6000]
    store.set_setting("outreach_templates", cur)
    return cur


# ---------------------------------------------------------------- contacts & candidates

FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.fr", "hotmail.com", "hotmail.fr", "outlook.com", "outlook.fr", "live.com",
             "live.fr", "msn.com", "icloud.com", "me.com", "aol.com", "gmx.de", "gmx.net", "gmx.fr", "web.de", "yandex.com", "yandex.ru",
             "mail.ru", "protonmail.com", "proton.me", "orange.fr", "free.fr", "laposte.net", "sfr.fr", "wanadoo.fr", "topnet.tn",
             "planet.tn", "gnet.tn", "menara.ma", "zoho.com"}


def _domain_of_email(e):
    return e.split("@")[-1].lower().strip() if "@" in e else ""


def _org_domain(email_addr, company_domain=""):
    """The organisation's domain for de-duplication - never a free-mail provider like gmail.com."""
    d = (company_domain or "").lower() or _domain_of_email(email_addr)
    return "" if d in FREE_MAIL else d


_NOT_FOR_APPLICATIONS = re.compile(r"^(legal|privacy|abuse|security|press|presse|media|medias|dpo|gdpr|rgpd|no-?reply|donotreply|do-not-reply|"
                                   r"billing|invoices?|factur\w*|webmaster|postmaster|hostmaster|unsubscribe|bounce|mailer|newsletter|"
                                   r"compliance|ethics|investors?|ir|partners?|affiliates?)[@.+_-]", re.I)


def best_contact(ckey, emails, types, domain):
    """Pick who to write to: a named HR person with an email > recruiting inbox > a leader (small company) > general inbox.
    Addresses that are never read for applications (legal@, privacy@, press@, noreply@...) are skipped."""
    emails = [e for e in emails if not _NOT_FOR_APPLICATIONS.match(e)]
    people = store.q("SELECT name, title, role, email FROM people WHERE company_key = ? AND email != '' ORDER BY "
                     "CASE role WHEN 'hr' THEN 0 WHEN 'leader' THEN 1 WHEN 'manager' THEN 2 ELSE 3 END, score DESC", (ckey,))
    for p in people:
        if p["role"] == "hr":
            return {"email": p["email"], "name": p["name"], "title": p["title"], "quality": "HR person"}
    rec = [e for e in emails if types.get(e) == "recruiting"]
    if rec:
        return {"email": rec[0], "name": "", "title": "", "quality": "Recruiting inbox"}
    for p in people:
        if p["role"] in ("leader", "manager"):
            return {"email": p["email"], "name": p["name"], "title": p["title"], "quality": "Manager" if p["role"] == "manager" else "Leadership"}
    own = [e for e in emails if domain and _domain_of_email(e).endswith(domain)] or emails
    gen = [e for e in own if types.get(e, recruiters.email_type(e)) in ("general", "other")]
    if gen:
        return {"email": gen[0], "name": "", "title": "", "quality": "General inbox"}
    if own:
        return {"email": own[0], "name": "", "title": "", "quality": "Company email"}
    return None


def contacted_domains(days=180):
    since = store.now() - days * 86400
    rows = store.q("SELECT DISTINCT domain, company_key FROM outreach WHERE status IN ('queued','sent','replied','bounced') OR "
                   "(status = 'draft') OR (sent_at >= ?)", (since,))
    return {r["domain"] for r in rows if r["domain"]}, {r["company_key"] for r in rows if r["company_key"]}


def candidates(country="", city="", q="", field_only=False, min_heat=0, include_general=True, limit=100):
    """Companies worth a spontaneous application (from JobRadar's own database)."""
    import matcher
    import signals
    m = matcher.me()
    fams = m["families"] if m else []
    my_country = (m or {}).get("country", "")
    sig = signals.compute(my_country, fams)
    doms, keys = contacted_domains()
    where, args = ["(c.emails != '[]' OR EXISTS(SELECT 1 FROM people p WHERE p.company_key = c.key AND p.email != ''))"], []
    if country:
        where.append("(c.country = ? OR EXISTS(SELECT 1 FROM jobs j WHERE j.company_key = c.key AND j.country = ?))")
        args += [country, country]
    if city:
        where.append("(c.address LIKE ? OR EXISTS(SELECT 1 FROM jobs j WHERE j.company_key = c.key AND (j.city LIKE ? OR j.location LIKE ?)))")
        args += ["%" + city + "%"] * 3
    if q:
        where.append("(c.name LIKE ? OR c.description LIKE ? OR c.category LIKE ? OR EXISTS(SELECT 1 FROM jobs j WHERE j.company_key = c.key AND j.title LIKE ?))")
        args += ["%" + q + "%"] * 4
    rows = store.q("SELECT c.*, (SELECT COUNT(*) FROM jobs j WHERE j.company_key = c.key AND j.hidden = 0) AS jobs, "
                   "(SELECT MAX(j.match_score) FROM jobs j WHERE j.company_key = c.key) AS best_match, "
                   "(SELECT COUNT(*) FROM jobs j WHERE j.company_key = c.key AND j.status IN ('applied','interview','offer')) AS applied "
                   "FROM companies c WHERE %s LIMIT 5000" % " AND ".join(where), args)
    out = []
    for r in rows:
        c = store.dict_row(r, store.COMPANY_JSON)
        if c["key"] in keys or (c["domain"] and c["domain"] in doms) or signals.is_anonymous(c["key"]):
            continue
        if any(b in (c["domain"] or "") for b in extract.JOB_BOARD_DOMAINS):
            continue
        contact = best_contact(c["key"], c["emails"] or [], c.get("email_types") or {}, c["domain"])
        if not contact:
            continue
        if not include_general and contact["quality"] in ("General inbox", "Company email"):
            continue
        s = sig.get(c["key"]) or {"heat": 0, "reasons": [], "my_field": 0}
        if min_heat and s["heat"] < min_heat:
            continue
        in_field = bool(s.get("my_field")) or (c["best_match"] or 0) >= 55
        if field_only and not in_field:
            continue
        rank = s["heat"] + (c["best_match"] or 0) * 0.6 + {"HR person": 30, "Recruiting inbox": 24, "Manager": 16, "Leadership": 12}.get(contact["quality"], 5)
        reasons = [x[1] for x in s["reasons"][:3]]
        if (c["best_match"] or 0) >= 55:
            reasons.append("Their jobs match you %d%%" % c["best_match"])
        if c["applied"]:
            reasons.append("You already applied to a job there")
        out.append({"key": c["key"], "name": c["name"], "domain": c["domain"], "country": c.get("country") or "", "logo": c.get("logo") or "",
                    "description": (c.get("description") or "")[:200], "jobs": c["jobs"], "best_match": c["best_match"], "heat": s["heat"],
                    "contact": contact, "reasons": reasons, "rank": round(rank, 1), "source": c.get("source") or "jobradar"})
    out.sort(key=lambda x: -x["rank"])
    return out[:limit], len(out)


# ---------------------------------------------------------------- Lead Finder integration (read-only)

def leadfinder_db():
    custom = store.get_setting("leadfinder_db", "")
    cands = [custom] if custom else []
    cands += [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Lead Finder", "leads.db"), r"D:\lead-finder\leads.db"]
    found = [p for p in cands if p and os.path.isfile(p)]
    return max(found, key=os.path.getmtime) if found else ""


def leadfinder_search(country="", city="", q="", limit=200):
    path = leadfinder_db()
    if not path:
        return {"found": False, "leads": []}
    c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    where, args = ["email != ''", "(mx_ok IS NULL OR mx_ok != 0)"], []
    if country:
        where.append("country_code = ?")
        args.append(country.upper())
    if city:
        where.append("city LIKE ?")
        args.append("%" + city + "%")
    if q:
        where.append("(name LIKE ? OR category LIKE ? OR niche LIKE ? OR description LIKE ?)")
        args += ["%" + q + "%"] * 4
    try:
        rows = c.execute("SELECT id, name, category, niche, city, country_code, website, domain, email, emails, phone, description "
                         "FROM leads WHERE %s ORDER BY score DESC, id DESC LIMIT ?" % " AND ".join(where), args + [limit]).fetchall()
        total = c.execute("SELECT COUNT(*) FROM leads WHERE %s" % " AND ".join(where), args).fetchone()[0]
    except sqlite3.Error as e:
        return {"found": True, "error": str(e), "leads": []}
    finally:
        c.close()
    doms, keys = contacted_domains()
    known = {r["key"] for r in store.q("SELECT key FROM companies")}
    leads = []
    for r in rows:
        d = dict(r)
        ck = store.company_key(d["name"])
        dom = (d["domain"] or extract.domain_of(d["website"] or "") or "").lower()
        d["key"] = ck
        d["contacted"] = ck in keys or (dom and dom in doms)
        d["in_jobradar"] = ck in known
        d["domain"] = dom
        leads.append(d)
    return {"found": True, "path": path, "total": total, "leads": leads}


def import_leads(ids):
    """Copy Lead Finder companies into JobRadar's companies (so they can get drafts, signals, contacts)."""
    path = leadfinder_db()
    if not path or not ids:
        return 0
    c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    ids = [int(i) for i in ids][:2000]
    rows = c.execute("SELECT * FROM leads WHERE id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
    c.close()
    n = 0
    with store.tx() as t:
        for r in rows:
            ck = store.company_key(r["name"])
            if not ck:
                continue
            emails = []
            try:
                emails = json.loads(r["emails"] or "[]")
            except ValueError:
                pass
            if r["email"] and r["email"] not in emails:
                emails.insert(0, r["email"])
            emails = [e.lower() for e in emails if e][:10]
            types = {e: recruiters.email_type(e) for e in emails}
            dom = (r["domain"] or extract.domain_of(r["website"] or "") or "").lower()
            phones = [r["phone"]] if r["phone"] else []
            ex = t.execute("SELECT key, emails FROM companies WHERE key = ?", (ck,)).fetchone()
            if ex:
                old = json.loads(ex["emails"] or "[]")
                merged = old + [e for e in emails if e not in old]
                t.execute("UPDATE companies SET emails = ?, email_types = ?, domain = CASE WHEN domain = '' THEN ? ELSE domain END, "
                          "country = CASE WHEN country = '' THEN ? ELSE country END, category = CASE WHEN category = '' THEN ? ELSE category END WHERE key = ?",
                          (json.dumps(merged[:30]), json.dumps({e: recruiters.email_type(e) for e in merged[:30]}), dom, r["country_code"] or "",
                           r["category"] or r["niche"] or "", ck))
            else:
                t.execute("INSERT INTO companies(key, name, domain, emails, phones, email_types, description, address, source, country, category) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (ck, r["name"][:200], dom, json.dumps(emails), json.dumps(phones), json.dumps(types), (r["description"] or "")[:600],
                           ", ".join(x for x in (r["address"], r["city"]) if x)[:250], "leadfinder", r["country_code"] or "", r["category"] or r["niche"] or ""))
            n += 1
    return n


# ---------------------------------------------------------------- drafts

def _lang_for(country, forced=""):
    if forced in ("en", "fr"):
        return forced
    return "fr" if (country or "").upper() in FR_COUNTRIES else "en"


def _vars(company, contact, lang, cv_skills=None, sent_date=""):
    import matcher
    p = applicant.get()
    m = matcher.me() or {}
    name = " ".join(x for x in (p["first_name"], p["last_name"]) if x) or "…"
    title = (p.get("target_titles") or p.get("current_title") or "").split(",")[0].strip() or ("professionnel(le)" if lang == "fr" else "professional")
    top = [skills.label(s, lang) for s in (cv_skills or m.get("skills") or []) if skills.kind(s) != "soft"][:3]
    et = " et " if lang == "fr" else " and "
    skills_txt = (", ".join(top[:-1]) + et + top[-1]) if len(top) > 1 else (top[0] if top else title)
    yrs = int(m.get("years") or 0)                      # 6.1 -> "6 ans"
    years = ("%d an%s" % (yrs, "s" if yrs >= 2 else "")) if lang == "fr" else ("%d year%s" % (yrs, "s" if yrs != 1 else ""))
    if not yrs:
        years = "une première expérience" if lang == "fr" else "hands-on experience"
    first = (contact.get("name") or "").split(" ")[0] if contact.get("name") else ""
    if lang == "fr":
        greeting = ("Bonjour %s," % first) if first else "Madame, Monsieur,"
        title_a = title
    else:
        greeting = ("Dear %s," % first) if first else "Dear Hiring Team,"
        title_a = ("an " if title[:1].lower() in "aeiou" else "a ") + title
    return {"{company}": company, "{greeting}": greeting, "{my_name}": name, "{my_title}": title, "{my_title_a}": title_a,
            "{my_skills}": skills_txt, "{years}": years, "{my_phone}": p.get("phone") or "", "{my_email}": p.get("email") or "",
            "{my_linkedin}": p.get("linkedin") or "", "{city}": p.get("city") or "", "{first_name}": first, "{sent_date}": sent_date}


def _fill(text, v):
    for k, val in v.items():
        text = text.replace(k, val)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def create_drafts(items, lang="", cv_id=""):
    """items: [{key} | {company, email, name}] -> number of drafts created."""
    import matcher
    tpl = templates()
    m = matcher.me() or {}
    doms, keys = contacted_domains()
    made = 0
    for it in items[:500]:
        ck = it.get("key") or store.company_key(it.get("company") or "")
        c = store.dict_row(store.q1("SELECT * FROM companies WHERE key = ?", (ck,)), store.COMPANY_JSON) if ck else None
        company = (c or {}).get("name") or it.get("company") or ""
        domain = (c or {}).get("domain") or ""
        if it.get("email"):
            contact = {"email": it["email"].strip().lower(), "name": it.get("name") or "", "title": it.get("title") or "", "quality": "Chosen"}
        elif c:
            contact = best_contact(ck, c.get("emails") or [], c.get("email_types") or {}, domain)
        else:
            contact = None
        if not contact or not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", contact["email"], re.I):
            continue
        domain = _org_domain(contact["email"], domain)
        if ck in keys or (domain and domain in doms):
            continue
        country = (c or {}).get("country") or ""
        if not country and ck:
            r = store.q1("SELECT country, COUNT(*) AS n FROM jobs WHERE company_key = ? AND country != '' GROUP BY country ORDER BY n DESC LIMIT 1", (ck,))
            country = r["country"] if r else ""
        L = _lang_for(country or m.get("country"), lang or it.get("lang", ""))
        best_cv = cv_id or _best_cv_for_company(ck) or next((x["id"] for x in applicant.cvs() if x.get("default")), "")
        cv_sk = next((x["skills"] for x in (m.get("cvs") or []) if x["id"] == best_cv), None)
        v = _vars(company, contact, L, cv_sk)
        store.run("INSERT INTO outreach(company_key, company, domain, country, to_email, to_name, to_title, lang, subject, body, cv_id, status, "
                  "source, reason, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ck, company[:200], domain, country, contact["email"], contact.get("name", "")[:80], contact.get("title", "")[:120], L,
                   _fill(tpl[L]["subject"], v)[:300], _fill(tpl[L]["body"], v), best_cv, "draft", (c or {}).get("source") or "jobradar",
                   (contact.get("quality") or "")[:40], store.now()))
        if domain:
            doms.add(domain)
        keys.add(ck)
        made += 1
    return made


def _best_cv_for_company(ck):
    if not ck:
        return ""
    r = store.q1("SELECT match FROM jobs WHERE company_key = ? AND match_score IS NOT NULL ORDER BY match_score DESC LIMIT 1", (ck,))
    if not r:
        return ""
    try:
        return json.loads(r["match"] or "{}").get("cv") or ""
    except ValueError:
        return ""


def update(oid, data):
    row = store.q1("SELECT * FROM outreach WHERE id = ?", (oid,))
    if row is None:
        raise ValueError("Not found")
    upd = {}
    for k, n in (("subject", 300), ("body", 8000), ("to_email", 200), ("to_name", 80), ("cv_id", 40), ("lang", 2)):
        if k in data and row["status"] in ("draft", "failed"):
            upd[k] = str(data[k] or "").strip()[:n]
    if "to_email" in upd and not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", upd["to_email"], re.I):
        raise ValueError("That email address doesn't look right")
    if data.get("status") in ("queued", "draft", "cancelled"):
        if data["status"] == "queued" and row["status"] not in ("draft", "failed"):
            raise ValueError("Only drafts can be approved")
        if data["status"] == "queued" and "{" in (upd.get("body") or row["body"]) and re.search(r"\{[a-z_]+\}", upd.get("body") or row["body"]):
            raise ValueError("The email still contains a {placeholder} - edit it first")
        upd["status"] = data["status"]
        if data["status"] == "queued":
            upd["queued_at"] = store.now()
            upd["error"] = ""
    if upd:
        store.run("UPDATE outreach SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in upd), list(upd.values()) + [oid])
    if upd.get("status") == "queued":
        _wake.set()
    return dict(store.q1("SELECT * FROM outreach WHERE id = ?", (oid,)))


def bulk(ids, action):
    ids = [int(i) for i in ids][:1000]
    n = 0
    for i in ids:
        try:
            if action == "approve":
                update(i, {"status": "queued"})
            elif action == "cancel":
                r = store.q1("SELECT status FROM outreach WHERE id = ?", (i,))
                if r and r["status"] in ("draft", "queued", "failed"):
                    store.run("UPDATE outreach SET status = 'cancelled' WHERE id = ?", (i,))
            elif action == "delete":           # any status: drafts, approved, sent history
                with store.tx() as c:
                    c.execute("UPDATE outreach SET parent_id = NULL WHERE parent_id = ?", (i,))
                    if not c.execute("DELETE FROM outreach WHERE id = ?", (i,)).rowcount:
                        continue
            elif action == "draft":
                store.run("UPDATE outreach SET status = 'draft' WHERE id = ? AND status IN ('queued','cancelled','failed')", (i,))
            n += 1
        except ValueError:
            continue
    return n


def listing(status="", q="", page=1, per=50):
    where, args = ["1=1"], []
    if status == "active":
        where.append("status IN ('draft','queued','failed')")
    elif status == "done":
        where.append("status IN ('sent','replied','bounced')")
    elif status:
        where.append("status = ?")
        args.append(status)
    if q:
        where.append("(company LIKE ? OR to_email LIKE ? OR to_name LIKE ?)")
        args += ["%" + q + "%"] * 3
    w = " AND ".join(where)
    total = store.q1("SELECT COUNT(*) AS n FROM outreach WHERE %s" % w, args)["n"]
    rows = store.q("SELECT * FROM outreach WHERE %s ORDER BY CASE status WHEN 'replied' THEN 0 WHEN 'failed' THEN 1 WHEN 'draft' THEN 2 "
                   "WHEN 'queued' THEN 3 ELSE 4 END, COALESCE(reply_at, sent_at, queued_at, created_at) DESC LIMIT ? OFFSET ?" % w,
                   args + [per, (page - 1) * per])
    counts = {r["status"]: r["n"] for r in store.q("SELECT status, COUNT(*) AS n FROM outreach GROUP BY status")}
    kinds = {r["reply_kind"]: r["n"] for r in store.q("SELECT reply_kind, COUNT(*) AS n FROM outreach WHERE status = 'replied' GROUP BY reply_kind")}
    return [dict(r) for r in rows], total, counts, kinds


# ---------------------------------------------------------------- sending

def _in_window(st, now=None):
    now = now or datetime.now()
    if st["weekdays"] and now.weekday() >= 5:
        return False
    try:
        a, b = st["window"].split("-")
        h0, m0 = [int(x) for x in a.strip().split(":")]
        h1, m1 = [int(x) for x in b.strip().split(":")]
    except ValueError:
        return True
    cur = now.hour * 60 + now.minute
    return h0 * 60 + m0 <= cur < h1 * 60 + m1


def sent_today():
    start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    return store.q1("SELECT COUNT(*) AS n FROM outreach WHERE sent_at >= ? AND status IN ('sent','replied','bounced')", (start,))["n"]


def build_message(row, st):
    p = applicant.get()
    msg = EmailMessage()
    from_name = " ".join(x for x in (p["first_name"], p["last_name"]) if x)
    msg["From"] = email.utils.formataddr((from_name, st["user"])) if from_name else st["user"]
    msg["To"] = email.utils.formataddr((row["to_name"], row["to_email"])) if row["to_name"] else row["to_email"]
    msg["Subject"] = row["subject"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    mid = email.utils.make_msgid(domain=(st["user"].split("@")[-1] or "jobradar.local"))
    msg["Message-ID"] = mid
    if row["kind"] == "followup" and row["parent_id"]:
        par = store.q1("SELECT message_id FROM outreach WHERE id = ?", (row["parent_id"],))
        if par and par["message_id"]:
            msg["In-Reply-To"] = par["message_id"]
            msg["References"] = par["message_id"]
    msg.set_content(row["body"])
    if st["attach_cv"] and row["cv_id"] and row["kind"] == "first":
        path, meta = applicant.cv_path(row["cv_id"])
        if path:
            ctype = meta.get("mime") or mimetypes.guess_type(path)[0] or "application/octet-stream"
            main, sub = ctype.split("/", 1)
            fname = meta.get("name") or os.path.basename(path)
            with open(path, "rb") as f:
                msg.add_attachment(f.read(), maintype=main, subtype=sub, filename=fname)
    return msg, mid


def _smtp(st):
    if st["port"] == 465:
        s = smtplib.SMTP_SSL(st["host"], 465, timeout=40)
    else:
        s = smtplib.SMTP(st["host"], st["port"], timeout=40)
        s.ehlo()
        s.starttls()
        s.ehlo()
    s.login(st["user"], st["password"])
    return s


def test_smtp():
    st = settings()
    if not (st["host"] and st["user"] and st["password"]):
        raise ValueError("Add your email address and app password first")
    s = _smtp(st)
    s.noop()
    s.quit()
    return True


def send_one(row, st):
    import enrich
    dom = _domain_of_email(row["to_email"])
    if not enrich.has_mx(dom):
        store.run("UPDATE outreach SET status = 'failed', error = ? WHERE id = ?", ("The domain %s has no mail server" % dom, row["id"]))
        return False
    dup = store.q1("SELECT id FROM outreach WHERE id != ? AND status IN ('sent','replied','bounced') AND kind = 'first' AND (to_email = ? OR (domain = ? AND domain != '')) "
                   "AND ? = 'first'", (row["id"], row["to_email"], row["domain"], row["kind"]))
    if dup:
        store.run("UPDATE outreach SET status = 'cancelled', error = 'Already contacted this company' WHERE id = ?", (row["id"],))
        return False
    msg, mid = build_message(row, st)
    s = _smtp(st)
    try:
        s.send_message(msg)
    finally:
        try:
            s.quit()
        except Exception:
            pass
    store.run("UPDATE outreach SET status = 'sent', sent_at = ?, message_id = ?, error = '' WHERE id = ?", (store.now(), mid, row["id"]))
    return True


def _sender_loop():
    time.sleep(15)
    fails = 0
    last_followups = last_replies = 0
    while True:
        try:
            st = settings()
            SENDER["sent_today"] = sent_today()
            queued = store.q1("SELECT COUNT(*) AS n FROM outreach WHERE status = 'queued'")["n"]
            if time.time() - last_followups > 3600:
                last_followups = time.time()
                make_followups(st)
            if time.time() - last_replies > 900 and st["imap_user"] and st["imap_password"]:
                last_replies = time.time()
                try:
                    check_replies(st)
                except Exception as e:
                    log.warning("reply check: %s", e)
            if not queued:
                SENDER.update(state="idle", message="Nothing waiting to be sent")
            elif st["paused"]:
                SENDER.update(state="paused", message="Sending is paused")
            elif not (st["host"] and st["user"] and st["password"]):
                SENDER.update(state="setup", message="Add your email account in Outreach > Settings to start sending")
            elif not _in_window(st):
                SENDER.update(state="waiting", message="Outside your sending hours (%s%s)" % (st["window"], ", weekdays" if st["weekdays"] else ""))
            elif SENDER["sent_today"] >= st["daily"]:
                SENDER.update(state="waiting", message="Daily limit reached (%d) - continues tomorrow" % st["daily"])
            elif time.time() - SENDER["last_sent"] < SENDER.get("next_gap", st["gap"] * 60):
                left = int(SENDER.get("next_gap", st["gap"] * 60) - (time.time() - SENDER["last_sent"]))
                SENDER.update(state="waiting", message="Next email in %d min %02d s" % (left // 60, left % 60))
            else:
                row = store.q1("SELECT * FROM outreach WHERE status = 'queued' ORDER BY queued_at, id LIMIT 1")
                if row:
                    SENDER.update(state="sending", message="Sending to %s…" % row["company"])
                    try:
                        if send_one(dict(row), st):
                            fails = 0
                            SENDER["last_sent"] = time.time()
                            SENDER["next_gap"] = st["gap"] * 60 * random.uniform(1.0, 2.0)
                    except smtplib.SMTPAuthenticationError as e:
                        store.set_setting("outreach_paused", 1)
                        store.notify("✉️ Sending paused: your email login was refused. Check the app password in Outreach > Settings.", "#/outreach?tab=settings")
                        SENDER.update(state="error", message="Login refused: %s" % str(e)[:120])
                    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError, smtplib.SMTPSenderRefused) as e:
                        fails += 1
                        store.run("UPDATE outreach SET status = 'failed', error = ? WHERE id = ?", (str(e)[:250], row["id"]))
                    except Exception as e:
                        fails += 1
                        store.run("UPDATE outreach SET status = 'failed', error = ? WHERE id = ?", (str(e)[:250], row["id"]))
                    if fails >= 3:
                        store.set_setting("outreach_paused", 1)
                        store.notify("✉️ Sending paused after 3 failures in a row - check Outreach.", "#/outreach")
                        fails = 0
        except Exception:
            log.exception("sender loop")
        _wake.wait(timeout=30)
        _wake.clear()


def start():
    threading.Thread(target=_sender_loop, daemon=True, name="outreach").start()


def poke():
    _wake.set()


# ---------------------------------------------------------------- follow-ups

def make_followups(st=None):
    st = st or settings()
    days = st["followup_days"]
    if not days:
        return 0
    rows = store.q("SELECT o.* FROM outreach o WHERE o.status = 'sent' AND o.kind = 'first' AND o.sent_at <= ? AND o.sent_at >= ? "
                   "AND NOT EXISTS(SELECT 1 FROM outreach f WHERE f.parent_id = o.id)", (store.now() - days * 86400, store.now() - 60 * 86400))
    n = 0
    for r in rows:
        v = _vars(r["company"], {"name": r["to_name"]}, r["lang"], sent_date=time.strftime("%d/%m/%Y", time.localtime(r["sent_at"])))
        subj = r["subject"] if r["subject"].lower().startswith("re:") else "Re: " + r["subject"]
        store.run("INSERT INTO outreach(company_key, company, domain, country, to_email, to_name, to_title, lang, subject, body, cv_id, kind, "
                  "parent_id, status, source, reason, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (r["company_key"], r["company"], r["domain"], r["country"], r["to_email"], r["to_name"], r["to_title"], r["lang"], subj,
                   _fill(FOLLOWUP.get(r["lang"], FOLLOWUP["en"]), v), r["cv_id"], "followup", r["id"], "draft", r["source"], "Follow-up", store.now()))
        n += 1
    if n:
        store.notify("✉️ %d follow-up%s ready to review (no answer after %d days)" % (n, "s" if n > 1 else "", days), "#/outreach?tab=queue")
    return n


# ---------------------------------------------------------------- replies (read-only IMAP)

def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _body_text(msg):
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() in ("text/plain", "text/html") and not part.get_filename():
            try:
                t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if part.get_content_type() == "text/html":
                t = extract.html_to_text(t, 5000)
            return t
    return ""


def classify_reply(text):
    head = synonyms.fold(text[:3000])
    for kind, rx in REPLY_KINDS:
        if re.search(rx, head, re.I):
            return kind
    return "other"


def check_replies(st=None):
    st = st or settings()
    sent = store.q("SELECT id, to_email, domain, message_id, sent_at, company, status FROM outreach WHERE status IN ('sent','replied') AND sent_at >= ?",
                   (store.now() - 90 * 86400,))
    if not sent:
        return 0
    by_mid = {r["message_id"]: r for r in sent if r["message_id"]}
    by_dom = {}
    for r in sent:
        if r["domain"] and r["domain"] not in FREE_MAIL:
            by_dom.setdefault(r["domain"], []).append(r)
    by_addr = {r["to_email"].lower(): r for r in sent}
    since = datetime.fromtimestamp(min(r["sent_at"] for r in sent)) - timedelta(days=1)
    M = imaplib.IMAP4_SSL(st["imap_host"], 993, timeout=30)
    found = 0
    try:
        M.login(st["imap_user"], st["imap_password"])
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "(SINCE %s)" % since.strftime("%d-%b-%Y"))
        ids = (data[0].split() if typ == "OK" and data and data[0] else [])[-800:]
        for mid in ids:
            typ, d = M.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT IN-REPLY-TO REFERENCES DATE)])")
            if typ != "OK" or not d or not isinstance(d[0], tuple):
                continue
            h = email.message_from_bytes(d[0][1])
            frm = email.utils.parseaddr(_dec(h.get("From")))[1].lower()
            refs = (h.get("In-Reply-To") or "") + " " + (h.get("References") or "")
            try:
                when = int(email.utils.parsedate_to_datetime(h.get("Date")).timestamp())
            except Exception:
                when = store.now()
            target = next((by_mid[x] for x in re.findall(r"<[^>]+>", refs) if x in by_mid), None)
            bounce = bool(re.search(r"mailer-daemon|postmaster|mail delivery", frm + " " + _dec(h.get("Subject")), re.I))
            if target is None and not bounce and frm in by_addr and when >= by_addr[frm]["sent_at"]:
                target = by_addr[frm]
            if target is None and not bounce:
                dom = frm.split("@")[-1]
                cands = by_dom.get(dom) or [v for k, v in by_dom.items() if dom.endswith("." + k)]
                target = next((c for c in (cands or []) if when >= c["sent_at"]), None)
            if bounce:
                typ, d2 = M.fetch(mid, "(BODY.PEEK[TEXT]<0.6000>)")
                body = d2[0][1].decode("utf-8", "replace").lower() if typ == "OK" and d2 and isinstance(d2[0], tuple) else ""
                hit = next((r for a, r in by_addr.items() if a in body and when >= r["sent_at"]), None)
                if hit and hit["status"] == "sent":
                    store.run("UPDATE outreach SET status = 'bounced', reply_at = ?, reply_kind = 'bounce', reply_snippet = ? WHERE id = ?",
                              (when, "The address doesn't exist or refused the email.", hit["id"]))
                    found += 1
                continue
            if target is None or target["status"] == "replied" or when < target["sent_at"]:
                continue
            typ, d2 = M.fetch(mid, "(BODY.PEEK[])")
            text = ""
            if typ == "OK" and d2 and isinstance(d2[0], tuple):
                text = _body_text(email.message_from_bytes(d2[0][1]))
            text = re.split(r"\n(?:on .{5,80} wrote:|le .{5,80} a écrit|-----original message|from: )", text, flags=re.I)[0]
            kind = classify_reply(_dec(h.get("Subject")) + "\n" + text)
            store.run("UPDATE outreach SET status = 'replied', reply_at = ?, reply_from = ?, reply_kind = ?, reply_snippet = ? WHERE id = ?",
                      (when, frm, kind, re.sub(r"\s+", " ", text).strip()[:400], target["id"]))
            store.run("UPDATE outreach SET status = 'cancelled', error = 'They replied' WHERE parent_id = ? AND status IN ('draft','queued')", (target["id"],))
            target = dict(target, status="replied")
            found += 1
            label = {"interview": "🎉 Interview invitation", "rejection": "Reply (not this time)", "auto": "Auto-reply"}.get(kind, "📬 Reply")
            store.notify("%s from %s" % (label, target["company"]), "#/outreach?tab=sent")
    finally:
        try:
            M.logout()
        except Exception:
            pass
    SENDER["last_check"] = int(time.time())
    SENDER["replies"] = found
    return found


# ---------------------------------------------------------------- MailBlaster export (alternative channel)

def mailblaster_db():
    custom = store.get_setting("mailblaster_db", "")
    cands = [custom] if custom else []
    cands += [os.path.join(os.environ.get("LOCALAPPDATA", ""), "MailBlaster", "mailblaster.db"), r"D:\mailblaster\mailblaster.db"]
    found = [p for p in cands if p and os.path.isfile(p)]
    return max(found, key=os.path.getmtime) if found else ""


def export_mailblaster(ids, group=""):
    path = mailblaster_db()
    if not path:
        raise ValueError("MailBlaster database not found")
    rows = [dict(r) for r in store.q("SELECT * FROM outreach WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)] if ids else []
    group = group or "JobRadar applications " + time.strftime("%Y-%m-%d")
    c = sqlite3.connect(path, timeout=30)
    added = updated = 0
    try:
        lcols = {r[1] for r in c.execute("PRAGMA table_info(lists)")}
        row = c.execute("SELECT id FROM lists WHERE name = ?", (group,)).fetchone()
        if row:
            gid = row[0]
        elif "color" in lcols:
            gid = c.execute("INSERT INTO lists(name, color, created_at) VALUES(?,?,?)", (group, "#0ea5e9", time.time())).lastrowid
        else:
            gid = c.execute("INSERT INTO lists(name, created_at) VALUES(?,?)", (group, time.time())).lastrowid
        for r in rows:
            first, _, last = (r["to_name"] or "").partition(" ")
            data = {"company": r["company"], "website": r["domain"], "country": r["country"], "source": "JobRadar"}
            ex = c.execute("SELECT id FROM contacts WHERE email = ?", (r["to_email"],)).fetchone()
            if ex:
                cid = ex[0]
                updated += 1
            else:
                cid = c.execute("INSERT INTO contacts(email, first_name, last_name, data, status, created_at) VALUES(?,?,?,?,?,?)",
                                (r["to_email"], first, last, json.dumps(data), "active", time.time())).lastrowid
                added += 1
            c.execute("INSERT OR IGNORE INTO list_members(list_id, contact_id) VALUES(?,?)", (gid, cid))
        c.commit()
    finally:
        c.close()
    return {"group": group, "added": added, "updated": updated}


def stats():
    since = store.now() - 30 * 86400
    r = store.q1("SELECT SUM(status IN ('sent','replied','bounced')) AS sent, SUM(status = 'replied') AS replied, "
                 "SUM(status = 'replied' AND reply_kind = 'interview') AS interviews, SUM(status = 'bounced') AS bounced, "
                 "SUM(status = 'draft') AS drafts, SUM(status = 'queued') AS queued FROM outreach WHERE created_at >= ? OR status IN ('draft','queued')", (since,))
    d = {k: (r[k] or 0) for k in r.keys()}
    real = d["sent"] - d["bounced"]
    d["reply_rate"] = round(100 * d["replied"] / real) if real > 0 else 0
    return d

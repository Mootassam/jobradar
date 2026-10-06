"""SQLite storage: jobs (+ FTS5 full-text index), companies, runs, saved searches, ATS boards, settings."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import zlib

import app_paths
import geo

_local = threading.local()
_db_path = app_paths.DB_PATH
_write_lock = threading.RLock()     # serialize writers across the crawler threads

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    company_key TEXT NOT NULL DEFAULT '',
    company_domain TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    remote INTEGER NOT NULL DEFAULT 0,
    worldwide INTEGER NOT NULL DEFAULT 0,
    job_type TEXT NOT NULL DEFAULT '',
    salary_min REAL, salary_max REAL,
    salary_currency TEXT NOT NULL DEFAULT '',
    salary_text TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    apply_url TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '[]',
    emails TEXT NOT NULL DEFAULT '[]',
    phones TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    posted_at INTEGER,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',      -- new | saved | applied | interview | offer | rejected
    hidden INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    status_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_jobs_seen ON jobs(first_seen DESC);
CREATE INDEX IF NOT EXISTS ix_jobs_posted ON jobs(posted_at DESC);
CREATE INDEX IF NOT EXISTS ix_jobs_country ON jobs(country, region);
CREATE INDEX IF NOT EXISTS ix_jobs_company ON jobs(company_key);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);

CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    title, company, location, description, tags, content='jobs', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS jobs_ai AFTER INSERT ON jobs BEGIN
    INSERT INTO jobs_fts(rowid, title, company, location, description, tags) VALUES (new.id, new.title, new.company, new.location, new.description, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS jobs_ad AFTER DELETE ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location, description, tags) VALUES('delete', old.id, old.title, old.company, old.location, old.description, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS jobs_au AFTER UPDATE OF title, company, location, description, tags ON jobs BEGIN
    INSERT INTO jobs_fts(jobs_fts, rowid, title, company, location, description, tags) VALUES('delete', old.id, old.title, old.company, old.location, old.description, old.tags);
    INSERT INTO jobs_fts(rowid, title, company, location, description, tags) VALUES (new.id, new.title, new.company, new.location, new.description, new.tags);
END;

CREATE TABLE IF NOT EXISTS companies (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    emails TEXT NOT NULL DEFAULT '[]',
    phones TEXT NOT NULL DEFAULT '[]',
    socials TEXT NOT NULL DEFAULT '[]',
    pages TEXT NOT NULL DEFAULT '[]',
    enriched_at INTEGER,
    enrich_status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    search_id INTEGER,
    params TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',  -- running | done | stopped | error
    progress TEXT NOT NULL DEFAULT '{}',
    found INTEGER NOT NULL DEFAULT 0,
    new INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS run_jobs (run_id INTEGER NOT NULL, job_id INTEGER NOT NULL, is_new INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, job_id)) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    params TEXT NOT NULL,
    every_hours INTEGER NOT NULL DEFAULT 0,  -- 0 = manual only
    last_run INTEGER,
    last_new INTEGER NOT NULL DEFAULT 0,
    unseen INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS boards (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    slug TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',      -- new | ok | empty | dead
    jobs_count INTEGER NOT NULL DEFAULT 0,
    last_fetch INTEGER,
    last_error TEXT NOT NULL DEFAULT '',
    fails INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT NOT NULL DEFAULT '',
    cache BLOB,
    created_at INTEGER NOT NULL,
    UNIQUE(provider, slug)
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    company_key TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'other',       -- hr | leader | manager | other
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    linkedin TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',           -- job post | team page | structured data | page text | contact link
    url TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    job_id INTEGER,
    found_at INTEGER NOT NULL,
    UNIQUE(company_key, name_key)
);
CREATE INDEX IF NOT EXISTS ix_people_company ON people(company_key, score DESC);
CREATE INDEX IF NOT EXISTS ix_people_role ON people(role);

CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, fetched_at INTEGER NOT NULL, data TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, link TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, read INTEGER NOT NULL DEFAULT 0
);

-- Hiring signals: every posting seen on each company career board, over time (first / last seen, gone).
CREATE TABLE IF NOT EXISTS postings (
    board_id INTEGER NOT NULL,
    pkey TEXT NOT NULL,
    company_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    dept TEXT NOT NULL DEFAULT '',
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    gone_at INTEGER,
    baseline INTEGER NOT NULL DEFAULT 0,       -- 1 = already open when we started tracking this board (not "new")
    PRIMARY KEY (board_id, pkey)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_postings_company ON postings(company_key, first_seen);

-- Spontaneous applications (and their follow-ups)
CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY,
    company_key TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    to_email TEXT NOT NULL,
    to_name TEXT NOT NULL DEFAULT '',
    to_title TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT 'en',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    cv_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'first',           -- first | followup
    parent_id INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',         -- draft | queued | sent | failed | replied | bounced | cancelled
    source TEXT NOT NULL DEFAULT 'jobradar',      -- jobradar | leadfinder | manual
    reason TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    queued_at INTEGER,
    sent_at INTEGER,
    message_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    reply_at INTEGER,
    reply_from TEXT NOT NULL DEFAULT '',
    reply_snippet TEXT NOT NULL DEFAULT '',
    reply_kind TEXT NOT NULL DEFAULT ''           -- interview | rejection | auto | other
);
CREATE INDEX IF NOT EXISTS ix_outreach_status ON outreach(status, queued_at);
CREATE INDEX IF NOT EXISTS ix_outreach_domain ON outreach(domain);

-- jobs the user deleted: a later search must not bring them back
CREATE TABLE IF NOT EXISTS deleted_jobs (uid TEXT PRIMARY KEY, at INTEGER NOT NULL) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS night_runs (
    id INTEGER PRIMARY KEY, started_at INTEGER NOT NULL, finished_at INTEGER, status TEXT NOT NULL DEFAULT 'running',
    trigger TEXT NOT NULL DEFAULT 'schedule', stages TEXT NOT NULL DEFAULT '[]', report TEXT NOT NULL DEFAULT '{}', seen INTEGER NOT NULL DEFAULT 0
);
"""


def now():
    return int(time.time())


def set_db_path(path):
    global _db_path
    c = getattr(_local, "c", None)
    if c:
        c.close()
        _local.c = None
    _db_path = path


def conn():
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "p", None) != _db_path:
        c = sqlite3.connect(_db_path, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c, _local.p = c, _db_path
    return c


MIGRATIONS = {
    "jobs": [("insights", "TEXT NOT NULL DEFAULT '{}'"), ("contacts", "TEXT NOT NULL DEFAULT '[]'"),
             ("match_score", "INTEGER"), ("match", "TEXT NOT NULL DEFAULT '{}'"), ("match_ver", "TEXT"),
             ("match_alerted", "INTEGER NOT NULL DEFAULT 0"), ("closed_at", "INTEGER")],
    "boards": [("tracked_since", "INTEGER"), ("snapshots", "INTEGER NOT NULL DEFAULT 0")],
    "runs": [("note", "TEXT NOT NULL DEFAULT ''")],
    "companies": [("title", "TEXT NOT NULL DEFAULT ''"), ("description", "TEXT NOT NULL DEFAULT ''"), ("logo", "TEXT NOT NULL DEFAULT ''"),
                  ("address", "TEXT NOT NULL DEFAULT ''"), ("founded", "TEXT NOT NULL DEFAULT ''"), ("employees", "TEXT NOT NULL DEFAULT ''"),
                  ("email_types", "TEXT NOT NULL DEFAULT '{}'"), ("watch", "INTEGER NOT NULL DEFAULT 0"),
                  ("source", "TEXT NOT NULL DEFAULT ''"), ("country", "TEXT NOT NULL DEFAULT ''"), ("category", "TEXT NOT NULL DEFAULT ''")],
}


def init():
    conn().executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn().execute("PRAGMA table_info(%s)" % table)}
        for name, ddl in cols:
            if name not in have:
                conn().execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
    conn().execute("CREATE INDEX IF NOT EXISTS ix_jobs_match ON jobs(match_score DESC)")


def q(sql, a=()):
    return conn().execute(sql, a).fetchall()


def q1(sql, a=()):
    return conn().execute(sql, a).fetchone()


def run(sql, a=()):
    with _write_lock:
        return conn().execute(sql, a).lastrowid


class tx:
    def __enter__(self):
        _write_lock.acquire()
        self.c = conn()
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, et, e, tb):
        try:
            self.c.execute("COMMIT" if et is None else "ROLLBACK")
        finally:
            _write_lock.release()
        return False


JSON_FIELDS = ("sources", "emails", "phones", "tags", "insights", "contacts", "match")
COMPANY_JSON = ("emails", "phones", "socials", "pages", "email_types")


def dict_row(r, json_fields=JSON_FIELDS):
    if r is None:
        return None
    d = dict(r)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except ValueError:
                d[f] = {} if f in ("insights", "email_types", "match") else []
    return d


# ---------------------------------------------------------------- settings

def get_setting(key, default=None):
    r = q1("SELECT value FROM settings WHERE key = ?", (key,))
    if r is None:
        return default
    try:
        return json.loads(r["value"])
    except ValueError:
        return r["value"]


def set_setting(key, value):
    run("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)))


# ---------------------------------------------------------------- jobs

def company_key(name):
    k = geo.norm(name)
    for suffix in (" inc", " llc", " ltd", " limited", " gmbh", " sa", " sas", " bv", " ag", " plc", " corp",
                   " corporation", " co", " srl", " ab", " oy", " as", " pty ltd", " pvt ltd", " sarl"):
        if k.endswith(suffix):
            k = k[: -len(suffix)].strip()
    return k


def job_uid(title, company, country, location):
    base = "|".join((geo.norm(title)[:120], company_key(company), country or geo.norm(location)[:40]))
    return hashlib.sha1(base.encode()).hexdigest()


def _merge_list(a, b, limit=30):
    out = list(a or [])
    for x in b or []:
        if x and x not in out:
            out.append(x)
    return out[:limit]


def upsert_job(j, force=False):
    """Insert or merge one normalized job. Returns (job_id, is_new); (None, False) for a job the user deleted."""
    uid = job_uid(j["title"], j.get("company", ""), j.get("country", ""), j.get("location", ""))
    ts = now()
    with tx() as c:
        row = c.execute("SELECT * FROM jobs WHERE uid = ?", (uid,)).fetchone()
        if row is None and c.execute("SELECT 1 FROM deleted_jobs WHERE uid = ?", (uid,)).fetchone():
            if not force:
                return None, False
            c.execute("DELETE FROM deleted_jobs WHERE uid = ?", (uid,))
        if row is None:
            cur = c.execute(
                "INSERT INTO jobs(uid, title, company, company_key, company_domain, location, country, region, city, remote, "
                "worldwide, job_type, salary_min, salary_max, salary_currency, salary_text, description, url, apply_url, sources, "
                "emails, phones, tags, posted_at, first_seen, last_seen, insights, contacts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uid, j["title"][:300], j.get("company", "")[:200], company_key(j.get("company", "")), j.get("company_domain", ""),
                 j.get("location", "")[:300], j.get("country", ""), j.get("region", "")[:80], j.get("city", "")[:80],
                 1 if j.get("remote") else 0, 1 if j.get("worldwide") else 0, j.get("job_type", "")[:80],
                 j.get("salary_min"), j.get("salary_max"), j.get("salary_currency", ""), j.get("salary_text", "")[:120],
                 j.get("description", ""), j.get("url", ""), j.get("apply_url", ""), json.dumps(j.get("sources", [])),
                 json.dumps(j.get("emails", [])), json.dumps(j.get("phones", [])), json.dumps(j.get("tags", [])[:15]),
                 j.get("posted_at"), ts, ts, json.dumps(j.get("insights") or {}, ensure_ascii=False),
                 json.dumps(j.get("contacts") or [], ensure_ascii=False)))
            jid, is_new = cur.lastrowid, True
        else:
            jid, is_new = _merge_job(c, row, j, ts), False
    if j.get("contacts"):
        save_people(company_key(j.get("company", "")), j["contacts"], jid)
    return jid, is_new


def _merge_job(c, row, j, ts):
    """Merge a re-found job into its existing row (richer description wins, lists are unioned). Returns id."""
    d = dict_row(row)
    upd = {"last_seen": ts,
           "sources": json.dumps(_merge_list(d["sources"], j.get("sources"))),
           "emails": json.dumps(_merge_list(d["emails"], j.get("emails"), 20)),
           "phones": json.dumps(_merge_list(d["phones"], j.get("phones"), 10)),
           "tags": json.dumps(_merge_list(d["tags"], j.get("tags"), 15))}
    if len(j.get("description", "")) > len(d["description"]) + 40:
        upd["description"] = j["description"]
        if j.get("insights"):
            upd["insights"] = json.dumps(j["insights"], ensure_ascii=False)
    elif not d.get("insights") and j.get("insights"):
        upd["insights"] = json.dumps(j["insights"], ensure_ascii=False)
    if j.get("contacts"):
        upd["contacts"] = json.dumps(_merge_list(d.get("contacts") or [], j["contacts"], 10), ensure_ascii=False)
    for f in ("company_domain", "region", "city", "job_type", "salary_currency", "salary_text", "apply_url", "url"):
        if not d.get(f) and j.get(f):
            upd[f] = j[f]
    for f in ("salary_min", "salary_max", "posted_at"):
        if d.get(f) is None and j.get(f) is not None:
            upd[f] = j[f]
    if j.get("posted_at") and d.get("posted_at") and j["posted_at"] < d["posted_at"]:
        upd["posted_at"] = j["posted_at"]
    cols = ", ".join("%s = ?" % k for k in upd)
    c.execute("UPDATE jobs SET %s WHERE id = ?" % cols, list(upd.values()) + [d["id"]])
    return d["id"]


# ---------------------------------------------------------------- people (recruiter finder)

def _name_key(name):
    return geo.norm(name)


def save_people(ckey, people, job_id=None):
    """Upsert people for a company; richer data and higher scores win."""
    if not ckey or not people:
        return 0
    ts = now()
    n = 0
    with tx() as c:
        for p in people:
            nk = _name_key(p.get("name", ""))
            if not nk:
                continue
            row = c.execute("SELECT * FROM people WHERE company_key = ? AND name_key = ?", (ckey, nk)).fetchone()
            if row is None:
                c.execute("INSERT INTO people(company_key, name, name_key, title, role, email, phone, linkedin, source, url, score, job_id, found_at) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (ckey, p["name"][:80], nk, (p.get("title") or "")[:120], p.get("role") or "other", (p.get("email") or "")[:120],
                           (p.get("phone") or "")[:40], (p.get("linkedin") or "")[:200], (p.get("source") or "")[:40],
                           (p.get("url") or "")[:300], int(p.get("score") or 0), job_id, ts))
                n += 1
                continue
            upd = {}
            for f in ("title", "email", "phone", "linkedin"):
                if not row[f] and p.get(f):
                    upd[f] = p[f]
            if int(p.get("score") or 0) > row["score"]:
                upd.update(score=int(p["score"]), role=p.get("role") or row["role"], source=p.get("source") or row["source"],
                           url=p.get("url") or row["url"])
            if job_id and not row["job_id"]:
                upd["job_id"] = job_id
            if upd:
                c.execute("UPDATE people SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in upd), list(upd.values()) + [row["id"]])
    return n


def company_people(ckey, limit=50):
    return [dict(r) for r in q("SELECT * FROM people WHERE company_key = ? ORDER BY score DESC, name LIMIT ?", (ckey, limit))]


def list_people(f, page=1, per=50):
    where, args = ["1=1"], []
    if f.get("q"):
        where.append("(p.name LIKE ? OR p.title LIKE ? OR c.name LIKE ? OR p.email LIKE ?)")
        args += ["%" + f["q"] + "%"] * 4
    if f.get("role"):
        where.append("p.role = ?")
        args.append(f["role"])
    if f.get("has_email"):
        where.append("p.email != ''")
    if f.get("company_key"):
        where.append("p.company_key = ?")
        args.append(f["company_key"])
    if f.get("country"):
        where.append("EXISTS(SELECT 1 FROM jobs j WHERE j.company_key = p.company_key AND j.country = ?)")
        args.append(f["country"].upper())
    w = " AND ".join(where)
    base = "FROM people p LEFT JOIN companies c ON c.key = p.company_key WHERE %s" % w
    total = q1("SELECT COUNT(*) AS n " + base, args)["n"]
    rows = q("SELECT p.*, c.name AS company, c.domain AS domain, "
             "(SELECT COUNT(*) FROM jobs j WHERE j.company_key = p.company_key AND j.hidden = 0) AS jobs_count " + base +
             " ORDER BY p.score DESC, p.found_at DESC LIMIT ? OFFSET ?", args + [per, (page - 1) * per])
    return [dict(r) for r in rows], total


def get_job(jid):
    j = dict_row(q1("SELECT * FROM jobs WHERE id = ?", (jid,)))
    if j:
        comp = q1("SELECT * FROM companies WHERE key = ?", (j["company_key"],))
        j["company_info"] = dict_row(comp, COMPANY_JSON) if comp else None
        j["people"] = company_people(j["company_key"], 30) if j["company_key"] else []
        if not j.get("insights") and j.get("description"):
            import insights as _ins            # jobs stored before insights existed
            j["insights"] = _ins.analyze(j["title"], j["description"])
        j["flag"] = geo.flag(j["country"])
        j["country_name"] = geo.country_name(j["country"])
    return j


def fts_query(text, multilingual=True):
    """User text -> safe FTS5 query. 'react, vue' = OR; words inside = AND; prefix match on the last word.
    multilingual: each group also matches its translations ("accountant" -> comptable, Buchhalter, محاسب...)."""
    import synonyms
    base = []
    for part in str(text).split(","):
        words = [w for w in re.findall(r"[\w+#.]+", part.lower()) if w.strip(".")]
        if words:
            base.append(words)
    alts = synonyms.expand_groups(base, 25) if multilingual else base
    groups = []
    for alt in alts[:80]:
        terms = []
        for k, term in enumerate(alt):
            toks = [t for t in re.findall(r"[\w+#.]+", term) if t.strip(".")]
            if not toks:
                continue
            if len(toks) > 1:
                terms.append('"%s"' % " ".join(t.replace('"', "") for t in toks))          # phrase
            else:
                terms.append('"%s"%s' % (toks[0].replace('"', "").strip("."), "*" if k == len(alt) - 1 else ""))
        if terms:
            groups.append("(" + " AND ".join(terms) + ")")
    return " OR ".join(dict.fromkeys(groups))


SORTS = {
    "newest": "COALESCE(j.posted_at, j.first_seen) DESC",
    "found": "j.first_seen DESC",
    "salary": "COALESCE(j.salary_max, j.salary_min, 0) DESC",
    "company": "j.company_key ASC",
    "match": "COALESCE(j.match_score, -1) DESC, COALESCE(j.posted_at, j.first_seen) DESC",
}


def _job_where(f):
    """(join, where_sql, args) for the job filters shared by the list, export and delete."""
    where, args = ["1=1"], []
    join = ""
    if f.get("q"):
        fq = fts_query(f["q"])
        if fq:
            join = "JOIN jobs_fts ON jobs_fts.rowid = j.id"
            where.append("jobs_fts MATCH ?")
            args.append(fq)
    if f.get("run_id"):
        where.append("j.id IN (SELECT job_id FROM run_jobs WHERE run_id = ?)")
        args.append(int(f["run_id"]))
    if f.get("country"):
        if f.get("include_worldwide"):
            where.append("(j.country = ? OR j.worldwide = 1)")
        else:
            where.append("j.country = ?")
        args.append(f["country"].upper())
    if f.get("region"):
        where.append("(j.region LIKE ? OR j.location LIKE ?)")
        args += ["%" + f["region"] + "%"] * 2
    if f.get("city"):
        where.append("(j.city LIKE ? OR j.location LIKE ?)")
        args += ["%" + f["city"] + "%"] * 2
    if f.get("remote") == "remote":
        where.append("j.remote = 1")
    elif f.get("remote") == "onsite":
        where.append("j.remote = 0")
    if f.get("has_email"):
        where.append("(j.emails != '[]' OR EXISTS(SELECT 1 FROM companies c WHERE c.key = j.company_key AND c.emails != '[]'))")
    if f.get("has_phone"):
        where.append("(j.phones != '[]' OR EXISTS(SELECT 1 FROM companies c WHERE c.key = j.company_key AND c.phones != '[]'))")
    if f.get("has_salary"):
        where.append("(j.salary_min IS NOT NULL OR j.salary_text != '')")
    if f.get("source"):
        where.append("j.sources LIKE ?")
        args.append('%' + f["source"] + '%')
    if f.get("status"):
        if f["status"] == "pipeline":
            where.append("j.status IN ('saved','applied','interview','offer')")
        else:
            where.append("j.status = ?")
            args.append(f["status"])
    if f.get("days"):
        where.append("COALESCE(j.posted_at, j.first_seen) >= ?")
        args.append(now() - int(f["days"]) * 86400)
    if f.get("company_key"):
        where.append("j.company_key = ?")
        args.append(f["company_key"])
    if f.get("has_recruiter"):
        where.append("EXISTS(SELECT 1 FROM people p WHERE p.company_key = j.company_key)")
    if f.get("visa"):
        where.append("(j.insights LIKE '%Visa sponsorship%' OR j.insights LIKE '%Relocation%')")
    if f.get("contract"):
        where.append("j.insights LIKE ?")
        args.append('%' + f["contract"] + '%')
    if f.get("max_exp") not in (None, "", 0):
        where.append("(json_extract(j.insights, '$.experience_years') IS NULL OR json_extract(j.insights, '$.experience_years') <= ?)")
        args.append(int(f["max_exp"]))
    if f.get("min_match"):
        where.append("j.match_score >= ?")
        args.append(int(f["min_match"]))
    if f.get("hide_closed"):
        where.append("j.closed_at IS NULL")
    if not f.get("show_hidden"):
        where.append("j.hidden = 0")
    return join, " AND ".join(where), args


def job_ids_matching(f):
    join, sql_where, args = _job_where(f)
    return [r["id"] for r in q("SELECT j.id FROM jobs j %s WHERE %s" % (join, sql_where), args)]


def list_jobs(f, page=1, per=50):
    join, sql_where, args = _job_where(f)
    total = q1("SELECT COUNT(*) AS n FROM jobs j %s WHERE %s" % (join, sql_where), args)["n"]
    order = SORTS.get(f.get("sort") or "newest", SORTS["newest"])
    rows = q("SELECT j.id, j.title, j.company, j.company_key, j.location, j.country, j.region, j.city, j.remote, j.worldwide, "
             "j.job_type, j.salary_min, j.salary_max, j.salary_currency, j.salary_text, j.sources, j.emails, j.phones, j.tags, "
             "j.posted_at, j.first_seen, j.status, j.url, j.apply_url, j.insights, j.match_score, j.closed_at, "
             "(SELECT c.emails FROM companies c WHERE c.key = j.company_key) AS c_emails, "
             "(SELECT c.phones FROM companies c WHERE c.key = j.company_key) AS c_phones, "
             "(SELECT COUNT(*) FROM people p WHERE p.company_key = j.company_key) AS people_count "
             "FROM jobs j %s WHERE %s ORDER BY %s LIMIT ? OFFSET ?" % (join, sql_where, order),
             args + [per, (page - 1) * per])
    out = []
    for r in rows:
        d = dict_row(r, JSON_FIELDS + ("c_emails", "c_phones"))
        d["c_emails"] = d.get("c_emails") or []
        d["c_phones"] = d.get("c_phones") or []
        d["flag"] = geo.flag(d["country"])
        out.append(d)
    return out, total


def set_status(ids, status=None, hidden=None):
    ts = now()
    with tx() as c:
        for i in ids:
            if status is not None:
                c.execute("UPDATE jobs SET status = ?, status_at = ? WHERE id = ?", (status, ts, i))
            if hidden is not None:
                c.execute("UPDATE jobs SET hidden = ? WHERE id = ?", (1 if hidden else 0, i))


# ---------------------------------------------------------------- companies

def refresh_companies(keys=None):
    """Make sure every company that has jobs has a companies row (with a guessed domain)."""
    sql = ("SELECT company_key, MAX(company) AS name, MAX(company_domain) AS domain FROM jobs "
           "WHERE company_key != '' %s GROUP BY company_key")
    args = []
    if keys:
        keys = list(keys)[:5000]
        sql = sql % ("AND company_key IN (%s)" % ",".join("?" * len(keys)))
        args = keys
    else:
        sql = sql % ""
    rows = q(sql, args)
    with tx() as c:
        for r in rows:
            c.execute("INSERT INTO companies(key, name, domain) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                      "domain = CASE WHEN companies.domain = '' THEN excluded.domain ELSE companies.domain END",
                      (r["company_key"], r["name"], r["domain"] or ""))


def list_companies(qtext="", has_contact=False, page=1, per=50):
    where, args = ["1=1"], []
    if qtext:
        where.append("(c.name LIKE ? OR c.domain LIKE ?)")
        args += ["%" + qtext + "%"] * 2
    if has_contact:
        where.append("(c.emails != '[]' OR c.phones != '[]')")
    w = " AND ".join(where)
    total = q1("SELECT COUNT(*) AS n FROM companies c WHERE %s" % w, args)["n"]
    rows = q("SELECT c.*, (SELECT COUNT(*) FROM jobs j WHERE j.company_key = c.key AND j.hidden = 0) AS jobs_count, "
             "(SELECT MAX(COALESCE(j.posted_at, j.first_seen)) FROM jobs j WHERE j.company_key = c.key) AS last_job, "
             "(SELECT group_concat(DISTINCT j.country) FROM jobs j WHERE j.company_key = c.key AND j.country != '') AS countries, "
             "(SELECT COUNT(*) FROM people p WHERE p.company_key = c.key) AS people_count, "
             "(SELECT COUNT(*) FROM people p WHERE p.company_key = c.key AND p.role = 'hr') AS hr_count "
             "FROM companies c WHERE %s ORDER BY jobs_count DESC, c.name LIMIT ? OFFSET ?" % w, args + [per, (page - 1) * per])
    return [dict_row(r, COMPANY_JSON) for r in rows], total


# ---------------------------------------------------------------- boards (ATS company registry)

def add_board(provider, slug, company="", discovered_from=""):
    slug = slug.strip()
    if not slug:
        return False
    try:
        run("INSERT INTO boards(provider, slug, company, discovered_from, created_at) VALUES(?,?,?,?,?)",
            (provider, slug, company, discovered_from[:200], now()))
        return True
    except sqlite3.IntegrityError:
        return False


def board_cache_get(bid, max_age):
    r = q1("SELECT cache, last_fetch FROM boards WHERE id = ?", (bid,))
    if r and r["cache"] and r["last_fetch"] and now() - r["last_fetch"] < max_age:
        try:
            return json.loads(zlib.decompress(r["cache"]).decode())
        except Exception:
            return None
    return None


def board_cache_put(bid, jobs, company=""):
    blob = zlib.compress(json.dumps(jobs, ensure_ascii=False).encode(), 6)
    run("UPDATE boards SET cache = ?, last_fetch = ?, jobs_count = ?, status = ?, last_error = '', fails = 0, "
        "company = CASE WHEN company = '' THEN ? ELSE company END WHERE id = ?",
        (blob, now(), len(jobs), "ok" if jobs else "empty", company, bid))


def board_fail(bid, err, dead=False):
    run("UPDATE boards SET last_error = ?, fails = fails + 1, last_fetch = ?, status = CASE WHEN ? THEN 'dead' ELSE status END "
        "WHERE id = ?", (str(err)[:200], now(), 1 if dead else 0, bid))



# ---------------------------------------------------------------- deleting

def _chunks(ids, n=400):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def delete_jobs(ids, remember=True):
    """Delete jobs (and their search-run links). remember=True keeps them from coming back in later searches."""
    ids = [int(i) for i in ids or []]
    n, ts = 0, now()
    with tx() as c:
        for ch in _chunks(ids):
            ph = ",".join("?" * len(ch))
            if remember:
                c.execute("INSERT OR IGNORE INTO deleted_jobs(uid, at) SELECT uid, ? FROM jobs WHERE id IN (%s)" % ph, [ts] + ch)
            c.execute("DELETE FROM run_jobs WHERE job_id IN (%s)" % ph, ch)
            c.execute("UPDATE people SET job_id = NULL WHERE job_id IN (%s)" % ph, ch)
            n += c.execute("DELETE FROM jobs WHERE id IN (%s)" % ph, ch).rowcount
    return n


def delete_all_jobs():
    """Fresh start: every job, run link and the 'deleted' memory (so new searches find everything again)."""
    with tx() as c:
        n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        c.execute("DELETE FROM jobs")
        c.execute("DELETE FROM run_jobs")
        c.execute("DELETE FROM deleted_jobs")
        c.execute("UPDATE people SET job_id = NULL")
    conn().execute("INSERT INTO jobs_fts(jobs_fts) VALUES('rebuild')")
    return n


def delete_runs(ids):
    ids = [int(i) for i in ids or []]
    n = 0
    with tx() as c:
        for ch in _chunks(ids):
            ph = ",".join("?" * len(ch))
            c.execute("DELETE FROM run_jobs WHERE run_id IN (%s)" % ph, ch)
            n += c.execute("DELETE FROM runs WHERE id IN (%s)" % ph, ch).rowcount
    return n


def delete_companies(keys, with_jobs=True):
    """Delete companies with the contacts found for them; with_jobs also deletes (and forgets) their jobs."""
    keys = [str(k) for k in keys or [] if k]
    n = 0
    if with_jobs:
        jids = []
        for ch in _chunks(keys):
            jids += [r["id"] for r in q("SELECT id FROM jobs WHERE company_key IN (%s)" % ",".join("?" * len(ch)), ch)]
        delete_jobs(jids)
    with tx() as c:
        for ch in _chunks(keys):
            ph = ",".join("?" * len(ch))
            c.execute("DELETE FROM people WHERE company_key IN (%s)" % ph, ch)
            n += c.execute("DELETE FROM companies WHERE key IN (%s)" % ph, ch).rowcount
    return n


def company_keys_matching(qtext="", has_contact=False):
    where, args = ["1=1"], []
    if qtext:
        where.append("(c.name LIKE ? OR c.domain LIKE ?)")
        args += ["%" + qtext + "%"] * 2
    if has_contact:
        where.append("(c.emails != '[]' OR c.phones != '[]')")
    return [r["key"] for r in q("SELECT c.key FROM companies c WHERE %s" % " AND ".join(where), args)]


def people_ids_matching(f):
    rows, total = list_people(f, 1, 1)
    if not total:
        return []
    rows, _ = list_people(f, 1, total)
    return [r["id"] for r in rows]


def delete_people(ids):
    ids = [int(i) for i in ids or []]
    n = 0
    with tx() as c:
        for ch in _chunks(ids):
            n += c.execute("DELETE FROM people WHERE id IN (%s)" % ",".join("?" * len(ch)), ch).rowcount
    return n


def delete_boards(ids):
    ids = [int(i) for i in ids or []]
    n = 0
    with tx() as c:
        for ch in _chunks(ids):
            ph = ",".join("?" * len(ch))
            c.execute("DELETE FROM postings WHERE board_id IN (%s)" % ph, ch)
            n += c.execute("DELETE FROM boards WHERE id IN (%s)" % ph, ch).rowcount
    return n


def clear_table(table):
    """Wipe one whole table (danger zone)."""
    assert table in ("searches", "notifications", "night_runs", "postings", "pages", "outreach", "people", "deleted_jobs")
    with tx() as c:
        return c.execute("DELETE FROM %s" % table).rowcount

# ---------------------------------------------------------------- misc

def notify(text, link=""):
    run("INSERT INTO notifications(text, link, created_at) VALUES(?,?,?)", (text[:300], link, now()))


def stats():
    r = q1("SELECT COUNT(*) AS jobs, SUM(first_seen >= ?) AS today, SUM(emails != '[]') AS with_email, "
           "SUM(phones != '[]') AS with_phone, COUNT(DISTINCT company_key) AS companies, COUNT(DISTINCT country) AS countries, "
           "SUM(status IN ('saved','applied','interview','offer')) AS pipeline, SUM(remote) AS remote FROM jobs WHERE hidden = 0",
           (now() - 86400,))
    d = dict(r)
    d = {k: (v or 0) for k, v in d.items()}
    d["by_country"] = [dict(x) for x in q(
        "SELECT country, COUNT(*) AS n FROM jobs WHERE hidden = 0 AND country != '' GROUP BY country ORDER BY n DESC LIMIT 12")]
    for x in d["by_country"]:
        x["flag"] = geo.flag(x["country"])
        x["name"] = geo.country_name(x["country"])
    d["by_source"] = []
    counts = {}
    for row in q("SELECT sources FROM jobs WHERE hidden = 0 AND first_seen >= ?", (now() - 30 * 86400,)):
        for s in json.loads(row["sources"] or "[]"):
            counts[s] = counts.get(s, 0) + 1
    d["by_source"] = sorted(({"source": k, "n": v} for k, v in counts.items()), key=lambda x: -x["n"])
    d["top_companies"] = [dict(x) for x in q(
        "SELECT MAX(company) AS company, company_key, COUNT(*) AS n FROM jobs WHERE hidden = 0 AND company_key != '' "
        "GROUP BY company_key ORDER BY n DESC LIMIT 10")]
    d["people"] = q1("SELECT COUNT(*) AS n FROM people")["n"]
    d["hr_people"] = q1("SELECT COUNT(*) AS n FROM people WHERE role = 'hr'")["n"]
    d["boards"] = dict(q1("SELECT COUNT(*) AS total, SUM(status='ok') AS ok, SUM(status='dead') AS dead FROM boards"))
    d["pipeline_by"] = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}
    return d


def backup(keep=10):
    name = time.strftime("jobradar-%Y%m%d-%H%M%S.db")
    path = os.path.join(app_paths.BACKUP_DIR, name)
    dst = sqlite3.connect(path)
    try:
        conn().backup(dst)
    finally:
        dst.close()
    files = sorted(f for f in os.listdir(app_paths.BACKUP_DIR) if f.startswith("jobradar-"))
    for old in files[:-keep]:
        try:
            os.remove(os.path.join(app_paths.BACKUP_DIR, old))
        except OSError:
            pass
    return path

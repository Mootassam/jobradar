"""JobRadar tests - no network (sources and fetch are faked).   python -m unittest discover -s tests -v"""
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-test-")
os.environ["JOBRADAR_DATA"] = TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alerts  # noqa: E402
import engine  # noqa: E402
import enrich  # noqa: E402
import extract  # noqa: E402
import geo  # noqa: E402
import server  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
from sources import Query, Source, ats  # noqa: E402

H = {"X-JobRadar": "1"}


class FakeSource(Source):
    id, name, kind = "fake", "Fake board", "board"
    JOBS = [
        {"title": "Senior Python Developer", "company": "Acme GmbH", "location": "Berlin, Germany", "description_html":
            "<p>Great team. Apply: <a href='mailto:jobs@acme.de'>jobs@acme.de</a> or call +49 30 12345678. Salary €70,000 - €90,000.</p>",
         "url": "https://acme.de/jobs/1", "posted_at": "2026-09-20T10:00:00Z", "tags": ["python", "django"]},
        {"title": "Registered Nurse", "company": "Care Inc", "location": "Austin, TX", "description": "Nights. Call (512) 555-0199.",
         "url": "https://care.example.org/rn", "posted_at": time.time() - 3600, "country_hint": "US"},
        {"title": "Python Engineer (Remote)", "company": "Globex", "location": "Worldwide", "remote": True,
         "description": "Fully remote. See https://boards.greenhouse.io/globexcorp for more roles.", "url": "https://globex.io/j/9"},
        {"title": "Data Analyst", "company": "Initech", "location": "Remote - EMEA", "remote": True, "description": "SQL", "url": "https://initech.com/j"},
        {"title": "=HYPERLINK(\"http://evil\")", "company": "Evil", "location": "London, UK", "description": "", "url": "https://evil.example/j"},
    ]

    def search(self, q, ctx):
        for j in self.JOBS:
            yield dict(j)
        ctx.report("%d jobs" % len(self.JOBS))


class FakeSource2(FakeSource):
    id, name = "fake2", "Fake board 2"
    JOBS = [{"title": "Senior Python Developer", "company": "ACME gmbh", "location": "Berlin", "country_hint": "DE",
             "description": "Short. hr@acme.de", "url": "https://other.example/acme-1"}]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.set_db_path(os.path.join(TMP, "t-%s.db" % cls.__name__))
        store.init()
        cls._orig = sources.all_sources
        fake = lambda: [FakeSource(), FakeSource2()]  # noqa: E731
        sources.all_sources = fake
        engine.all_sources = fake
        server.all_sources = fake
        cls.c = server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        sources.all_sources = engine.all_sources = server.all_sources = cls._orig

    def wait_run(self, rid, timeout=20):
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = store.q1("SELECT * FROM runs WHERE id = ?", (rid,))
            if r["status"] != "running":
                return r
            time.sleep(0.1)
        self.fail("run did not finish")


class TestGeo(unittest.TestCase):
    def test_locations(self):
        cases = {"Austin, TX": ("US", "Texas"), "München, Deutschland": ("DE", "Bavaria"), "London, UK": ("GB", "England"),
                 "Toronto, ON, Canada": ("CA", "Ontario"), "Casablanca, Morocco": ("MA", "Casablanca-Settat"),
                 "Remote (US)": ("US", ""), "Dubai": ("AE", "Dubai"), "Sydney NSW": ("AU", "New South Wales")}
        for text, (cc, region) in cases.items():
            p = geo.parse_location(text)
            self.assertEqual(p["country"], cc, text)
            if region:
                self.assertEqual(p["region"], region, text)
        w = geo.parse_location("Anywhere in the world")
        self.assertTrue(w["worldwide"] and w["remote"])
        self.assertIn("emea", geo.parse_location("Remote - EMEA")["areas"])

    def test_resolve_and_flags(self):
        self.assertEqual(geo.resolve_country("usa"), "US")
        self.assertEqual(geo.resolve_country("DEU"), "DE")
        self.assertEqual(geo.resolve_country("Maroc"), "MA")
        self.assertEqual(geo.flag("FR"), "🇫🇷")
        self.assertGreater(len(geo.countries_list()), 190)


class TestExtract(unittest.TestCase):
    def test_contacts(self):
        self.assertEqual(extract.find_emails("Mail hr@acme.com, logo@2x.png, noreply@x.com, a [at] b [dot] io"), ["hr@acme.com", "a@b.io"])
        ph = extract.find_phones("Call +1 (415) 555-0132 or 020 7946 0958. Order 123456.", "GB")
        self.assertIn("+44 20 7946 0958", ph)
        self.assertTrue(any(p.startswith("+1") for p in ph))

    def test_salary(self):
        self.assertEqual(extract.parse_salary("$120k - $150k")[:3], (120000, 150000, "USD"))
        self.assertEqual(extract.parse_salary("€70.000 – €90.000")[:3], (70000, 90000, "EUR"))
        self.assertEqual(extract.parse_salary("no salary")[0], None)

    def test_html_and_dates(self):
        self.assertIn("• one", extract.html_to_text("<ul><li>one</li><li>two</li></ul>"))
        self.assertEqual(extract.html_to_text("&lt;p&gt;Hi&lt;/p&gt;"), "Hi")
        self.assertEqual(extract.to_ts("2026-01-01T00:00:00Z"), 1767225600)
        self.assertEqual(extract.to_ts(1767225600000), 1767225600)

    def test_jsonld(self):
        html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"JobPosting","title":"Chef",
        "hiringOrganization":{"@type":"Organization","name":"Bistro"},"jobLocation":{"address":{"addressLocality":"Lyon","addressCountry":"FR"}},
        "datePosted":"2026-09-01","baseSalary":{"currency":"EUR","value":{"minValue":2500,"maxValue":3000}}}]}</script>"""
        jobs = extract.jsonld_jobpostings(html, "https://bistro.fr/jobs")
        self.assertEqual(jobs[0]["title"], "Chef")
        self.assertEqual(jobs[0]["company"], "Bistro")
        self.assertEqual(jobs[0]["country_hint"], "FR")
        self.assertEqual(jobs[0]["salary_max"], 3000)


class TestMatching(unittest.TestCase):
    def job(self, **kw):
        base = {"title": "Python Developer", "company": "X", "location": "Berlin, Germany", "url": "u"}
        base.update(kw)
        return engine.normalize(base, "t")

    def test_keywords_or_and(self):
        j = self.job()
        self.assertTrue(engine.matches(j, Query(keywords="python developer")))
        self.assertTrue(engine.matches(j, Query(keywords="nurse, python")))
        self.assertFalse(engine.matches(j, Query(keywords="nurse")))
        self.assertTrue(engine.matches(j, Query(keywords="nurse"), skip_keywords=True))

    def test_location_rules(self):
        de = self.job()
        self.assertTrue(engine.matches(de, Query(country="DE")))
        self.assertFalse(engine.matches(de, Query(country="FR")))
        self.assertTrue(engine.matches(de, Query(country="DE", region="bavaria")) is False)
        # strict by default: remote-worldwide / regional-remote jobs are NOT "in Tunisia"
        ww = self.job(location="Worldwide", remote=True)
        self.assertFalse(engine.matches(ww, Query(country="TN")))
        self.assertTrue(engine.matches(ww, Query(country="TN", include_worldwide=True)))
        emea = self.job(location="Remote - EMEA", remote=True)
        self.assertFalse(engine.matches(emea, Query(country="FR")))
        self.assertTrue(engine.matches(emea, Query(country="FR", include_worldwide=True)))
        self.assertFalse(engine.matches(emea, Query(country="US", include_worldwide=True)))
        # remote job open to a list of countries (Himalayas-style) is opt-in; a job located in Tunisia always matches
        opento = engine.normalize({"title": "Dev", "location": "Remote", "remote": True, "country_list": ["Tunisia", "France"]}, "t")
        self.assertFalse(engine.matches(opento, Query(country="TN")))
        self.assertTrue(engine.matches(opento, Query(country="TN", include_worldwide=True)))
        tunis = self.job(location="Sfax")
        self.assertEqual(tunis["country"], "TN")
        self.assertTrue(engine.matches(tunis, Query(country="TN")))
        self.assertFalse(engine.matches(tunis, Query(country="US")))
        # multi-country on-site posting (ReliefWeb style) counts for each real country
        multi = engine.normalize({"title": "Officer", "location": "Tunis, Libya", "country_list": ["Tunisia", "Libya"]}, "t")
        self.assertTrue(engine.matches(multi, Query(country="LY")))
        self.assertFalse(engine.matches(de, Query(remote="remote")))


class TestEngineAndApi(Base):
    def test_full_run_dedupe_contacts_and_discovery(self):
        r = self.c.post("/api/search", json={"keywords": "", "max_per_source": 100}, headers=H)
        rid = r.get_json()["run_id"]
        run = self.wait_run(rid)
        self.assertEqual(run["status"], "done")
        # 5 + 1 raw jobs, the Acme job is found by both sources -> 5 rows
        self.assertEqual(store.q1("SELECT COUNT(*) n FROM jobs")["n"], 5)
        acme = store.dict_row(store.q1("SELECT * FROM jobs WHERE company_key = 'acme'"))
        self.assertEqual(sorted(acme["sources"]), ["fake", "fake2"])
        self.assertIn("jobs@acme.de", acme["emails"])
        self.assertIn("hr@acme.de", acme["emails"])
        self.assertIn("+49 30 12345678", acme["phones"])
        self.assertEqual(acme["salary_min"], 70000)
        self.assertEqual(acme["country"], "DE")
        rn = store.dict_row(store.q1("SELECT * FROM jobs WHERE title = 'Registered Nurse'"))
        self.assertEqual((rn["country"], rn["region"]), ("US", "Texas"))
        self.assertTrue(rn["phones"])
        # ATS board referenced in a description was discovered
        self.assertIsNotNone(store.q1("SELECT 1 FROM boards WHERE provider = 'greenhouse' AND slug = 'globexcorp'"))
        prog = json.loads(run["progress"])
        self.assertEqual(prog["fake"]["status"], "done")

    def test_filters_status_bulk_and_fts(self):
        rid = self.c.post("/api/search", json={"keywords": "python", "max_per_source": 100}, headers=H).get_json()["run_id"]
        self.wait_run(rid)
        res = self.c.get("/api/jobs?run=%d" % rid).get_json()
        titles = {j["title"] for j in res["jobs"]}
        self.assertIn("Python Engineer (Remote)", titles)
        self.assertNotIn("Registered Nurse", titles)
        self.assertEqual(self.c.get("/api/jobs?q=django").get_json()["total"], 1)
        self.assertGreaterEqual(self.c.get("/api/jobs?has_email=1").get_json()["total"], 1)
        de = self.c.get("/api/jobs?country=DE").get_json()
        self.assertTrue(all(j["country"] == "DE" for j in de["jobs"]))
        jid = res["jobs"][0]["id"]
        self.assertEqual(self.c.patch("/api/jobs/%d" % jid, json={"status": "applied"}, headers=H).get_json()["job"]["status"], "applied")
        self.assertEqual(self.c.patch("/api/jobs/%d" % jid, json={"status": "bogus"}, headers=H).status_code, 400)
        self.c.post("/api/jobs/bulk", json={"ids": [jid], "hidden": True}, headers=H)
        self.assertNotIn(jid, [j["id"] for j in self.c.get("/api/jobs").get_json()["jobs"]])

    def test_export_xlsx_csv_escapes_formulas(self):
        rid = self.c.post("/api/search", json={"keywords": ""}, headers=H).get_json()["run_id"]
        self.wait_run(rid)
        r = self.c.get("/api/export?format=xlsx")
        self.assertTrue(r.data.startswith(b"PK"))
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(r.data)).active
        titles = [c.value for c in ws["A"]]
        self.assertTrue(any(str(t).startswith("'=HYPERLINK") for t in titles))
        csv_text = self.c.get("/api/export?format=csv").get_data(as_text=True)
        self.assertIn("Company emails", csv_text)

    def test_guard_requires_header_and_local_host(self):
        self.assertEqual(self.c.post("/api/search", json={}).status_code, 403)
        self.assertEqual(self.c.get("/api/meta", headers={"Host": "evil.com"}).status_code, 403)
        self.assertEqual(self.c.get("/api/meta").status_code, 200)

    def test_saved_searches_and_boards(self):
        store.run("DELETE FROM jobs")        # so the run finds "new" jobs
        sid = self.c.post("/api/searches", json={"name": "Py", "params": {"keywords": "python"}, "every_hours": 6}, headers=H).get_json()["id"]
        rid = self.c.post("/api/searches/%d/run" % sid, headers=H).get_json()["run_id"]
        self.wait_run(rid)
        time.sleep(0.2)
        s = [x for x in self.c.get("/api/searches").get_json()["searches"] if x["id"] == sid][0]
        self.assertGreater(s["unseen"], 0)
        self.assertTrue(self.c.get("/api/notifications").get_json()["notifications"])
        r = self.c.post("/api/boards", json={"input": "lever:acmeco\nhttps://jobs.ashbyhq.com/someco"}, headers=H).get_json()
        self.assertEqual(r["added"], 2)
        self.assertIn("ashby:someco", r["found"])
        self.assertEqual(self.c.post("/api/boards", json={"input": "lever:acmeco"}, headers=H).get_json()["added"], 0)

    def test_settings_masks_secrets(self):
        self.c.put("/api/settings", json={"jooble_key": "SECRET123", "board_workers": "6"}, headers=H)
        meta = self.c.get("/api/meta").get_json()
        self.assertEqual(meta["settings"]["jooble_key"], "••••••••")
        self.assertEqual(meta["settings"]["board_workers"], 6)
        self.c.put("/api/settings", json={"jooble_key": "••••••••"}, headers=H)
        self.assertEqual(engine.settings()["jooble_key"], "SECRET123")
        self.assertEqual(self.c.put("/api/settings", json={"board_workers": "x"}, headers=H).status_code, 400)


class TestAtsAndEnrich(Base):
    def test_board_cache_and_dead(self):
        store.add_board("greenhouse", "zzco")
        b = dict(store.q1("SELECT * FROM boards WHERE slug = 'zzco'"))
        calls = []
        orig = ats.FETCHERS["greenhouse"]
        ats.FETCHERS["greenhouse"] = lambda slug, stop: (calls.append(slug) or [{"title": "T", "company": "zzco", "location": "Paris"}], "ZZ Co")
        try:
            jobs, cached = ats.load_board(b, None, 3600)
            self.assertFalse(cached)
            self.assertEqual(jobs[0]["company"], "ZZ Co")
            jobs, cached = ats.load_board(dict(store.q1("SELECT * FROM boards WHERE slug='zzco'")), None, 3600)
            self.assertTrue(cached)
            self.assertEqual(len(calls), 1)
        finally:
            ats.FETCHERS["greenhouse"] = orig
        from net import FetchError

        def boom(slug, stop):
            raise FetchError("HTTP 404", 404)
        ats.FETCHERS["lever"] = boom
        store.add_board("lever", "gone")
        with self.assertRaises(FetchError):
            ats.load_board(dict(store.q1("SELECT * FROM boards WHERE slug='gone'")), None, 0)
        self.assertEqual(store.q1("SELECT status FROM boards WHERE slug='gone'")["status"], "dead")
        ats.FETCHERS["lever"] = ats.fetch_lever

    def test_enrich_company(self):
        store.upsert_job(engine.normalize({"title": "Cook", "company": "Bistro Lune", "location": "Lyon, France",
                                           "url": "https://bistrolune.fr/jobs/1", "apply_url": "https://bistrolune.fr/jobs/1"}, "t"))
        store.refresh_companies()

        class R:
            def __init__(self, url, text):
                self.url, self.text, self.headers = url, text, {"content-type": "text/html"}
        pages = {
            "https://bistrolune.fr": '<a href="/contact">Contact</a><a href="https://www.linkedin.com/company/bistro-lune">in</a>',
            "https://bistrolune.fr/contact": '<a href="mailto:hello@bistrolune.fr">mail</a> Tél : +33 4 78 12 34 56',
        }

        def fake_fetch(url, **kw):
            if url.rstrip("/") in pages:
                return R(url, pages[url.rstrip("/")])
            from net import FetchError
            raise FetchError("404", 404)
        orig, orig_mx = enrich.fetch, enrich.has_mx
        enrich.fetch, enrich.has_mx = fake_fetch, lambda d: True
        try:
            c = enrich.enrich_company(store.company_key("Bistro Lune"))
        finally:
            enrich.fetch, enrich.has_mx = orig, orig_mx
        self.assertEqual(c["domain"], "bistrolune.fr")
        self.assertIn("hello@bistrolune.fr", c["emails"])
        self.assertIn("+33 4 78 12 34 56", c["phones"])
        self.assertTrue(any("linkedin.com/company/bistro-lune" in s for s in c["socials"]))
        self.assertTrue(c["enrich_status"].startswith("ok"))


class TestAlerts(unittest.TestCase):
    def test_linkedin_like_email(self):
        html = """<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trk=eml">Product Designer</a>
        <p>Spotify · Stockholm, Sweden</p></td></tr>
        <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/?x=1">View job</a><div>Growth Marketer</div><div>Canva · Remote</div></td></tr>
        <tr><td><a href="https://www.indeed.com/rc/clk?jk=abcdef123456&from=ja">Barista</a><span>Blue Bottle - Oakland, CA</span></td></tr></table>"""
        jobs = alerts.parse_alert(html, 1767225600)
        by = {j["url"]: j for j in jobs}
        a = by["https://www.linkedin.com/jobs/view/4012345678/"]
        self.assertEqual((a["title"], a["company"], a["location"]), ("Product Designer", "Spotify", "Stockholm, Sweden"))
        self.assertEqual(by["https://www.linkedin.com/jobs/view/4099999999/"]["title"], "Growth Marketer")
        self.assertEqual(by["https://www.indeed.com/viewjob?jk=abcdef123456"]["company"], "Blue Bottle")


if __name__ == "__main__":
    unittest.main(verbosity=2)

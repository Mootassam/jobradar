"""Multilingual search, resumable runs and offline tolerance (no real network)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-res-")
os.environ.setdefault("JOBRADAR_DATA", TMP)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
import net  # noqa: E402
import requests  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402
import synonyms  # noqa: E402
from sources import Ctx, Query, Source, ats  # noqa: E402

CALLS = {"a": 0, "b": 0}


class SrcA(Source):
    id, name = "srca", "Source A"

    def search(self, q, ctx):
        CALLS["a"] += 1
        yield {"title": "Comptable confirmé", "company": "Alpha", "location": "Tunis", "url": "https://a/1"}


class SrcB(Source):
    id, name = "srcb", "Source B"

    def search(self, q, ctx):
        CALLS["b"] += 1
        yield {"title": "Accountant", "company": "Beta", "location": "Sfax, Tunisia", "url": "https://b/1"}
        yield {"title": "Driver", "company": "Beta", "location": "Sfax, Tunisia", "url": "https://b/2"}


class TestMultilingual(unittest.TestCase):
    def test_expansion_and_terms(self):
        extra = synonyms.expansion_summary([["accountant"]])
        for w in ("comptable", "buchhalter", "contador", "محاسب"):
            self.assertIn(w, extra)
        self.assertEqual(Query(keywords="accountant", country="TN").search_terms, ["accountant", "comptable", "محاسب"])
        self.assertEqual(Query(keywords="project manager", country="FR").search_terms, ["project manager", "chef de projet"])
        self.assertEqual(Query(keywords="nurse", country="US").search_terms, ["nurse"])
        self.assertEqual(Query(keywords="accountant", country="TN", multilingual=False).search_terms, ["accountant"])

    def test_matching(self):
        q = Query(keywords="accountant")
        job = lambda t: engine.normalize({"title": t, "company": "X", "location": "Tunis", "url": "u"}, "t")  # noqa: E731
        for t in ("Comptable confirmé", "Responsable Comptabilité", "محاسب رئيسي", "Buchhalter (m/w/d)", "Senior Accountant"):
            self.assertTrue(engine.matches(job(t), q), t)
        self.assertFalse(engine.matches(job("Sales Manager"), q))
        self.assertFalse(engine.matches(job("Comptable"), Query(keywords="accountant", multilingual=False)))
        self.assertFalse(engine.matches(job("Three Rivers Driver"), Query(keywords="hr")))
        self.assertTrue(engine.matches(job("Responsable RH"), Query(keywords="hr")))
        self.assertTrue(engine.matches(job("Python Developer"), Query(keywords="develop")))       # prefix still works


class TestResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.set_db_path(os.path.join(TMP, "res.db"))
        store.init()
        cls._orig = sources.all_sources
        engine.all_sources = lambda: [SrcA(), SrcB()]

    @classmethod
    def tearDownClass(cls):
        engine.all_sources = cls._orig

    def wait(self, rid):
        for _ in range(200):
            if store.q1("SELECT status FROM runs WHERE id = ?", (rid,))["status"] != "running":
                return
            time.sleep(0.05)
        self.fail("run did not finish")

    def test_resume_skips_finished_sources(self):
        # a run that was cut off: source A finished (1 match saved), source B was still running
        params = {"keywords": "accountant", "country": "TN", "sources": ["srca", "srcb"]}
        progress = {"srca": {"name": "Source A", "status": "done", "found": 1, "scanned": 1, "message": "1 jobs", "error": ""},
                    "srcb": {"name": "Source B", "status": "running", "found": 0, "scanned": 0, "message": "", "error": ""}}
        rid = store.run("INSERT INTO runs(params, progress, status, found, started_at) VALUES(?,?,?,?,?)",
                        (json.dumps(params), json.dumps(progress), "interrupted", 1, store.now()))
        jid, _ = store.upsert_job(engine.normalize({"title": "Comptable confirmé", "company": "Alpha", "location": "Tunis", "url": "https://a/1"}, "srca"))
        store.run("INSERT INTO run_jobs(run_id, job_id, is_new) VALUES(?,?,1)", (rid, jid))
        CALLS.update(a=0, b=0)
        self.assertTrue(engine.resume_run(rid))
        self.wait(rid)
        row = store.q1("SELECT * FROM runs WHERE id = ?", (rid,))
        self.assertEqual(row["status"], "done")
        self.assertEqual(CALLS["a"], 0)             # finished source not re-run
        self.assertEqual(CALLS["b"], 1)
        self.assertEqual(row["found"], 2)           # 1 before the interruption + "Accountant" (Driver filtered)
        self.assertFalse(engine.resume_run(rid))    # finished runs can't be resumed

    def test_auto_resume_only_interrupted(self):
        mk = lambda st: store.run("INSERT INTO runs(params, progress, status, started_at) VALUES(?,?,?,?)",  # noqa: E731
                                  (json.dumps({"keywords": "x", "sources": ["srca"]}), "{}", st, store.now()))
        a, b = mk("interrupted"), mk("stopped")
        resumed = engine.auto_resume()
        self.assertIn(a, resumed)
        self.assertNotIn(b, resumed)
        self.wait(a)

    def test_board_checkpoint(self):
        store.add_board("greenhouse", "cp-one")
        store.add_board("greenhouse", "cp-two")
        ids = {r["slug"]: r["id"] for r in store.q("SELECT id, slug FROM boards WHERE slug LIKE 'cp-%'")}
        fetched = []
        orig = ats.FETCHERS["greenhouse"]
        ats.FETCHERS["greenhouse"] = lambda slug, stop: (fetched.append(slug) or [{"title": "Accountant", "company": slug, "location": "Paris"}], slug)
        try:
            ctx = Ctx({}, threading.Event(), lambda m: None)
            ctx.checkpoint = {ids["cp-one"]}
            done = []
            ctx.board_done = done.append
            got = list(ats.CompanyBoards().search(Query(keywords="accountant"), ctx))
        finally:
            ats.FETCHERS["greenhouse"] = orig
        self.assertNotIn("cp-one", fetched)
        self.assertIn("cp-two", fetched)
        self.assertIn(ids["cp-two"], done)
        self.assertTrue(any(j["company"] == "cp-two" for j in got))


class TestOffline(unittest.TestCase):
    def test_fetch_waits_for_internet_instead_of_failing(self):
        state = {"calls": 0, "online_checks": 0}

        class Resp:
            status_code = 200
            headers = {}

            def json(self):
                return {"ok": True}

        def fake_request(*a, **k):
            state["calls"] += 1
            if state["calls"] == 1:
                raise requests.ConnectionError("network down")
            return Resp()

        def fake_online():
            state["online_checks"] += 1
            return state["online_checks"] >= 3        # offline for two checks, then back

        orig_online, orig_every = net.online, net.WAIT_EVERY
        net.online, net.WAIT_EVERY = fake_online, 0.01
        sess = net.session()
        orig_req = sess.request
        sess.request = fake_request
        try:
            out = net.fetch("https://example.test/api", retries=0)      # no retries allowed - must still succeed
        finally:
            net.online, net.WAIT_EVERY = orig_online, orig_every
            sess.request = orig_req
        self.assertEqual(out, {"ok": True})
        self.assertIsNone(net.OFFLINE["since"])

    def test_stop_while_offline(self):
        orig_online, orig_every = net.online, net.WAIT_EVERY
        net.online, net.WAIT_EVERY = (lambda: False), 0.01
        stop = threading.Event()
        threading.Timer(0.1, stop.set).start()
        try:
            self.assertFalse(net.wait_online(stop))
        finally:
            net.online, net.WAIT_EVERY = orig_online, orig_every
            net.OFFLINE["since"] = None


if __name__ == "__main__":
    unittest.main(verbosity=2)

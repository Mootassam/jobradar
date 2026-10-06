"""Every delete / delete-all action, the 'deleted jobs stay deleted' rule and the danger zone."""
import io
import os
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-del-")
os.environ.setdefault("JOBRADAR_DATA", TMP)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402

H = {"X-JobRadar": "1"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def job(title, company="Acme", location="Tunis, Tunisia", src="srca"):
    return engine.normalize({"title": title, "company": company, "location": location,
                             "url": "https://example.com/" + title.replace(" ", "-")}, src)


class TestDelete(unittest.TestCase):
    def setUp(self):
        store.set_db_path(os.path.join(TMP, "del-%s.db" % self._testMethodName))
        store.init()
        self.c = server.app.test_client()

    def post(self, url, data=None):
        r = self.c.post(url, json=data or {}, headers=H)
        return r.status_code, r.get_json()

    def delete(self, url, data=None):
        r = self.c.delete(url, json=data or {}, headers=H)
        return r.status_code, r.get_json()

    def count(self, table, where="1=1"):
        return store.q1("SELECT COUNT(*) AS n FROM %s WHERE %s" % (table, where))["n"]

    # ---------------------------------------------------------------- jobs
    def test_delete_one_job_and_it_never_comes_back(self):
        jid, new = store.upsert_job(job("Comptable"))
        self.assertTrue(new)
        code, r = self.delete("/api/jobs/%d" % jid)
        self.assertEqual((code, r["count"]), (200, 1))
        self.assertEqual(self.count("jobs"), 0)
        again, new = store.upsert_job(job("Comptable"))          # a later search finds it again
        self.assertIsNone(again)
        self.assertFalse(new)
        self.assertEqual(self.count("jobs"), 0)
        forced, _ = store.upsert_job(job("Comptable"), force=True)   # you applied to it via the extension
        self.assertIsNotNone(forced)

    def test_bulk_delete_and_run_links(self):
        rid = store.run("INSERT INTO runs(params, started_at, status) VALUES('{}', 1, 'done')")
        ids = [store.upsert_job(job("Job %d" % i))[0] for i in range(5)]
        for i in ids:
            store.run("INSERT INTO run_jobs(run_id, job_id) VALUES(?,?)", (rid, i))
        code, r = self.post("/api/jobs/bulk", {"ids": ids[:3], "delete": True})
        self.assertEqual(r["count"], 3)
        self.assertEqual(self.count("jobs"), 2)
        self.assertEqual(self.count("run_jobs"), 2)

    def test_delete_all_matching_filters(self):
        for i in range(4):
            store.upsert_job(job("Dev %d" % i, location="Paris, France"))
        for i in range(3):
            store.upsert_job(job("Nurse %d" % i, location="Tunis, Tunisia"))
        code, r = self.post("/api/jobs/delete-matching", {"country": "FR"})
        self.assertEqual(r["count"], 4)
        self.assertEqual(self.count("jobs"), 3)
        jid = store.q1("SELECT id FROM jobs")["id"]
        store.set_status([jid], status="saved")
        code, r = self.post("/api/jobs/delete-matching", {"status": "saved"})   # a pipeline column
        self.assertEqual((r["count"], self.count("jobs")), (1, 2))
        code, r = self.post("/api/jobs/delete-matching", {})                      # everything shown
        self.assertEqual(self.count("jobs"), 0)
        self.assertEqual(self.c.get("/api/jobs").get_json()["total"], 0)

    def test_fulltext_search_still_works_after_deletes(self):
        a = store.upsert_job(job("Pastry chef"))[0]
        store.upsert_job(job("Pastry baker"))
        store.delete_jobs([a])
        res = self.c.get("/api/jobs?q=pastry").get_json()
        self.assertEqual([j["title"] for j in res["jobs"]], ["Pastry baker"])
        store.delete_all_jobs()
        self.assertEqual(self.c.get("/api/jobs?q=pastry").get_json()["total"], 0)
        self.assertIsNotNone(store.upsert_job(job("Pastry chef"))[0])          # fresh start forgets deletions

    # ---------------------------------------------------------------- search history
    def test_delete_runs_one_and_all_but_not_running(self):
        r1 = store.run("INSERT INTO runs(params, started_at, status) VALUES('{}', 1, 'done')")
        r2 = store.run("INSERT INTO runs(params, started_at, status) VALUES('{}', 2, 'done')")
        r3 = store.run("INSERT INTO runs(params, started_at, status) VALUES('{}', 3, 'running')")
        self.assertEqual(self.delete("/api/runs/%d" % r1)[1]["count"], 1)
        engine.RUNS[r3] = object()
        try:
            self.assertEqual(self.delete("/api/runs/%d" % r3)[0], 400)
            code, r = self.post("/api/runs/delete", {"all": True})
            self.assertEqual((r["count"], r["skipped_running"]), (1, 1))
        finally:
            engine.RUNS.pop(r3, None)
        self.assertEqual([x["id"] for x in store.q("SELECT id FROM runs")], [r3])
        self.assertTrue(r2)

    # ---------------------------------------------------------------- companies + people
    def test_delete_companies_with_and_without_jobs(self):
        store.upsert_job(job("A1", company="Alpha"))
        store.upsert_job(job("B1", company="Beta"))
        store.upsert_job(job("G1", company="Gamma"))
        store.refresh_companies()
        store.save_people("alpha", [{"name": "Sarah Ben Ali", "title": "HR Manager", "role": "hr"}])
        code, r = self.post("/api/companies/delete", {"keys": ["alpha"]})
        self.assertEqual(r["count"], 1)
        self.assertEqual(self.count("jobs", "company_key='alpha'"), 0)
        self.assertEqual(self.count("people"), 0)
        code, r = self.post("/api/companies/delete", {"keys": ["beta"], "with_jobs": False})
        self.assertEqual(self.count("jobs", "company_key='beta'"), 1)
        code, r = self.post("/api/companies/delete", {"all": True, "q": "gam"})
        self.assertEqual((r["count"], self.count("companies")), (1, 0))
        self.assertEqual(self.post("/api/companies/delete", {})[0], 400)

    def test_delete_people_one_filtered_all(self):
        store.upsert_job(job("X", company="Delta"))
        store.refresh_companies()
        store.save_people("delta", [{"name": "Amira Trabelsi", "title": "Talent Acquisition", "role": "hr"},
                                    {"name": "Karim Haddad", "title": "CEO", "role": "leader"},
                                    {"name": "Lina Mansour", "title": "Recruiter", "role": "hr"}])
        pid = store.q1("SELECT id FROM people WHERE name LIKE 'Karim%'")["id"]
        self.assertEqual(self.delete("/api/people/%d" % pid)[1]["count"], 1)
        code, r = self.post("/api/people/delete", {"all": True, "role": "hr", "q": "Amira"})
        self.assertEqual(r["count"], 1)
        code, r = self.post("/api/people/delete", {"all": True})
        self.assertEqual((r["count"], self.count("people")), (1, 0))

    # ---------------------------------------------------------------- saved searches, boards, outreach, night, notifications
    def test_saved_searches_delete_all(self):
        for i in range(3):
            self.post("/api/searches", {"name": "S%d" % i, "params": {"keywords": "x"}})
        sid = store.q1("SELECT id FROM searches")["id"]
        self.assertEqual(self.delete("/api/searches/%d" % sid)[0], 200)
        self.assertEqual(self.post("/api/searches/delete-all")[1]["count"], 2)
        self.assertEqual(self.count("searches"), 0)

    def test_boards_delete_selected_filtered_all(self):
        for slug in ("a1", "a2", "dead1", "dead2"):
            store.add_board("greenhouse", slug)
        store.run("UPDATE boards SET status='dead' WHERE slug LIKE 'dead%'")
        bid = store.q1("SELECT id FROM boards WHERE slug='a1'")["id"]
        store.run("INSERT INTO postings(board_id, pkey, first_seen, last_seen) VALUES(?, 'p', 1, 1)", (bid,))
        self.assertEqual(self.delete("/api/boards/%d" % bid)[1]["count"], 1)
        self.assertEqual(self.count("postings"), 0)
        self.assertEqual(self.post("/api/boards/delete", {"all": True, "status": "dead"})[1]["count"], 2)
        self.assertEqual(self.post("/api/boards/delete", {"all": True})[1]["count"], 1)

    def test_outreach_delete_any_status_and_all(self):
        mk = lambda st: store.run("INSERT INTO outreach(to_email, status, created_at) VALUES('a@b.co', ?, 1)", (st,))  # noqa: E731
        d, q, sent, rep = mk("draft"), mk("queued"), mk("sent"), mk("replied")
        self.assertEqual(self.delete("/api/outreach/%d" % sent)[0], 200)
        self.assertEqual(self.count("outreach", "id=%d" % sent), 0)          # sent history can be deleted now
        self.assertEqual(self.post("/api/outreach/delete", {"ids": [q]})[1]["count"], 1)
        self.assertEqual(self.post("/api/outreach/delete", {"all": True, "status": "active"})[1]["count"], 1)
        self.assertEqual(self.post("/api/outreach/delete", {"all": True, "status": "done"})[1]["count"], 1)
        self.assertEqual(self.post("/api/outreach/delete", {"all": True, "status": "x"})[0], 400)
        self.assertTrue(d and rep)

    def test_night_reports_and_notifications(self):
        n1 = store.run("INSERT INTO night_runs(started_at, status) VALUES(1, 'done')")
        store.run("INSERT INTO night_runs(started_at, status) VALUES(2, 'done')")
        self.assertEqual(self.delete("/api/night/%d" % n1)[0], 200)
        self.assertEqual(self.post("/api/night/delete-all")[1]["count"], 1)
        store.notify("hello")
        store.notify("world")
        n = store.q1("SELECT id FROM notifications")["id"]
        self.assertEqual(self.delete("/api/notifications/%d" % n)[0], 200)
        self.assertEqual(self.delete("/api/notifications")[1]["count"], 1)

    # ---------------------------------------------------------------- danger zone
    def test_danger_zone(self):
        self.assertEqual(self.post("/api/data/clear", {"what": "jobs", "confirm": "no"})[0], 400)
        self.assertEqual(self.post("/api/data/clear", {"what": "nope", "confirm": "DELETE"})[0], 400)
        r = self.c.post("/api/profile/cv", data={"file": (io.BytesIO(PDF), "cv.pdf")}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.c.put("/api/profile", json={"first_name": "Amira"}, headers=H)
        store.upsert_job(job("Chef"))
        store.refresh_companies()
        store.notify("x")
        self.post("/api/searches", {"name": "S", "params": {}})
        store.add_board("lever", "acme")
        for what in ("cvs", "profile", "notifications"):
            self.assertEqual(self.post("/api/data/clear", {"what": what, "confirm": "DELETE"})[0], 200, what)
        self.assertEqual(self.c.get("/api/profile").get_json()["cvs"], [])
        self.assertEqual(self.c.get("/api/profile").get_json()["profile"]["first_name"], "")
        code, r = self.post("/api/data/clear", {"what": "everything", "confirm": "DELETE"})
        self.assertEqual(code, 200)
        for t in ("jobs", "companies", "searches", "notifications", "runs", "people", "outreach", "night_runs"):
            self.assertEqual(self.count(t), 0, t)
        self.assertEqual(self.count("boards"), 1)                    # sources are kept
        self.assertEqual(self.c.get("/api/stats").status_code, 200)

    def test_ping_identifies_jobradar(self):
        self.assertEqual(self.c.get("/api/ping").get_json()["app"], "JobRadar")


if __name__ == "__main__":
    unittest.main()

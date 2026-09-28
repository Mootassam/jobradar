"""v4: skills taxonomy, ATS CV checker, CV <-> job match, hiring signals, spontaneous applications, night deep scan."""
import json
import os
import sys
import tempfile
import time
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-v4-")
os.environ.setdefault("JOBRADAR_DATA", TMP)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import applicant  # noqa: E402
import cv_samples  # noqa: E402
import cvcheck  # noqa: E402
import engine  # noqa: E402
import matcher  # noqa: E402
import nightly  # noqa: E402
import outreach  # noqa: E402
import server  # noqa: E402
import signals  # noqa: E402
import skills  # noqa: E402
import store  # noqa: E402

H = {"X-JobRadar": "1"}


def add_cv(path, cid="cvmain", label="Main CV"):
    import shutil
    dst = os.path.join(applicant.CV_DIR, cid + os.path.splitext(path)[1])
    shutil.copy(path, dst)
    items = [c for c in (store.get_setting("cv_files", []) or []) if c["id"] != cid]
    items.append({"id": cid, "name": os.path.basename(path), "label": label, "file": os.path.basename(dst), "size": os.path.getsize(dst),
                  "mime": "application/pdf", "uploaded_at": int(time.time())})
    store.set_setting("cv_files", items)
    store.set_setting("cv_default", items[0]["id"])


def job(title, desc, country="TN", company="Stram", url=None, **kw):
    raw = dict({"title": title, "company": company, "location": {"TN": "Tunis, Tunisia", "DE": "Berlin, Germany", "US": "Austin, TX"}.get(country, country),
                "description": desc, "url": url or "https://example.org/%s/%s" % (company, abs(hash(title)))}, **kw)
    jid, _ = store.upsert_job(engine.normalize(raw, "national"))
    return jid


class TestSkills(unittest.TestCase):
    def test_multilingual_and_exact_rules(self):
        self.assertEqual(set(skills.find("Maîtrise d'Excel, Sage 100 et comptabilité générale")), {"Excel", "Sage", "Accounting"})
        self.assertIn("Accounting", skills.find("خبرة في المحاسبة"))
        self.assertEqual(skills.find("We excel at EXCELLENT products. Go to our site."), [])
        self.assertEqual(skills.find("Tableau de bord, budget de 800€, formation continue, réseau de distribution"), [])
        self.assertIn("Go", skills.find("Stack: Python, Go and PostgreSQL"))
        self.assertIn("Go", skills.find("6+ years of experience with Go, Kubernetes and PostgreSQL"))
        self.assertNotIn("R", skills.find("Our R&D team in Tunis. Go to our website"))

    def test_required_vs_nice(self):
        req, nice = skills.job_skills("Requirements:\n- Python and PostgreSQL\nNice to have:\n- Kubernetes\n- AWS")
        self.assertEqual(set(req), {"Python", "PostgreSQL"})
        self.assertEqual(set(nice), {"Kubernetes", "AWS"})
        req, nice = skills.job_skills("Maîtrise de Sage. La connaissance de SAP serait un plus.")
        self.assertEqual((req, nice), (["Sage"], ["SAP"]))

    def test_related_skills_give_partial_credit(self):
        full, partial = skills.closure(["PostgreSQL"])
        self.assertEqual(partial.get("SQL"), 0.7)


class TestCvCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.s = cv_samples.all_samples(cls.dir)

    def run_check(self, key):
        p = self.s[key]
        text, facts = cvcheck.read(p)
        a = cvcheck.analyze(text, facts, os.path.basename(p), os.path.getsize(p), {"country": "Tunisia", "city": "Tunis"})
        score, checks, cats = cvcheck.check(text, facts, a)
        return score, {c["id"]: c["status"] for c in checks}, a, facts

    def test_good_cv(self):
        score, st, a, facts = self.run_check("good")
        self.assertGreaterEqual(score, 85)
        self.assertEqual(a["email"], "amira.trabelsi@example.com")
        self.assertEqual(a["phone"], "+216 20 123 456")
        self.assertTrue(a["linkedin"])
        self.assertEqual(a["sections"][:3], ["summary", "experience", "education"])
        self.assertEqual(a["months"] // 12, (cvcheck.date.today().year * 12 + cvcheck.date.today().month - (2022 * 12 + 3) + 1 + 18) // 12)
        self.assertEqual(a["languages"]["Arabic"], 5)
        self.assertEqual(a["education"], 4)
        self.assertIn("Accounting", a["skills"])
        self.assertEqual(st["columns"], "ok")

    def test_layout_problems_are_found(self):
        score_good = self.run_check("good")[0]
        score, st, a, facts = self.run_check("columns")
        self.assertTrue(facts["columns"])
        self.assertEqual(st["columns"], "warn")
        self.assertEqual(st["tables"], "warn")
        self.assertEqual(st["filename"], "warn")         # "cv.pdf"
        self.assertEqual(a["phone"], "")                   # dates like 2022 - 2024 are never a phone number
        self.assertLess(score, score_good)

    def test_scanned_cv_fails(self):
        score, st, a, facts = self.run_check("scan")
        self.assertTrue(facts["scanned"])
        self.assertEqual(st["text"], "fail")
        self.assertLessEqual(score, 25)

    def test_docx_contact_in_header(self):
        score, st, a, facts = self.run_check("docx")
        self.assertEqual(facts["format"], "docx")
        self.assertEqual(st["header"], "warn")
        self.assertEqual(st["tables"], "warn")


class TestMatchSignalsOutreachNight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.set_db_path(os.path.join(TMP, "v4.db"))
        store.init()
        cls.c = server.app.test_client()
        d = tempfile.mkdtemp()
        add_cv(cv_samples.make_pdf(os.path.join(d, "Amira_Trabelsi_CV.pdf")))
        applicant.save({"first_name": "Amira", "last_name": "Trabelsi", "email": "amira@example.com", "phone": "+216 20 123 456",
                        "country": "Tunisia", "city": "Tunis", "target_titles": "comptable, accountant"})
        cls.acc = job("Comptable confirmé(e)", "Profil recherché :\n- 3 ans d'expérience en comptabilité générale\n- Maîtrise de Sage et Excel\n"
                      "- Fiscalité (TVA)\nLa connaissance de SAP serait un plus.", company="Stram SA")
        cls.dev = job("Senior Backend Engineer", "Requirements:\n- 6+ years of experience with Go, Kubernetes and PostgreSQL\n- AWS", country="US", company="Acme Cloud")
        cls.dent = job("Assistant(e) dentaire", "Accueil des patients, gestion des rendez-vous, stérilisation.", company="Cabinet Dr X")
        cls.de = job("Buchhalter (m/w/d)", "Ihr Profil:\n- Abgeschlossene Ausbildung in der Buchhaltung\n- Sehr gute Deutschkenntnisse\n- DATEV und Excel\n"
                     "Wir bieten ein tolles Team und flexible Arbeitszeiten in unserem Unternehmen mit der Möglichkeit zur Weiterbildung.",
                     country="DE", company="Muster GmbH")
        store.refresh_companies()
        matcher._run_once()

    def score(self, jid):
        r = store.q1("SELECT match_score, match FROM jobs WHERE id = ?", (jid,))
        return r["match_score"], json.loads(r["match"])

    # ---- match
    def test_match_ranks_the_right_jobs(self):
        acc, d = self.score(self.acc)
        dev, dd = self.score(self.dev)
        dent, _ = self.score(self.dent)
        self.assertGreaterEqual(acc, 80)
        self.assertIn("Sage", d["have"])
        self.assertEqual(d["missing"], [])
        self.assertLess(dev, 40)
        self.assertIn("Go", dd["missing"])
        self.assertLess(dent, 60)                          # "assistant" alone is not the same profession
        self.assertEqual(d["cv"], "cvmain")

    def test_language_of_the_post_counts(self):
        s, d = self.score(self.de)
        self.assertIn("German needed", d["notes"])
        self.assertLessEqual(s, 55)

    def test_profile_change_rescores(self):
        v1 = store.q1("SELECT match_ver FROM jobs WHERE id = ?", (self.acc,))["match_ver"]
        applicant.save({"skills_extra": "Odoo, Power BI"})
        self.assertIn("Odoo", matcher.me()["skills"])
        matcher._run_once()
        self.assertNotEqual(store.q1("SELECT match_ver FROM jobs WHERE id = ?", (self.acc,))["match_ver"], v1)
        applicant.save({"skills_extra": ""})
        matcher._run_once()

    def test_match_api_sort_filter_and_gap(self):
        r = self.c.get("/api/jobs?sort=match&min_match=70").get_json()
        self.assertEqual(r["jobs"][0]["id"], self.acc)
        self.assertTrue(all(j["match_score"] >= 70 for j in r["jobs"]))
        st = self.c.get("/api/match/status").get_json()
        self.assertTrue(st["ready"])
        self.assertGreaterEqual(st["dist"]["top"], 1)
        self.assertIn("gap", self.c.get("/api/match/gap").get_json())
        j = self.c.get("/api/jobs/%d" % self.acc).get_json()["job"]
        self.assertIn("parts", j["match"])

    def test_cv_check_api(self):
        r = self.c.get("/api/cv/check").get_json()["result"]
        self.assertGreaterEqual(r["score"], 80)
        self.assertIn("Accounting", r["profile"]["skills"])
        self.assertTrue(r["ats_text"].startswith("Amira Trabelsi"))

    def test_extension_gets_best_cv(self):
        url = store.q1("SELECT url FROM jobs WHERE id = ?", (self.acc,))["url"]
        r = self.c.get("/ext/profile?url=" + url, headers={"X-JobRadar-Token": applicant.token()}).get_json()
        self.assertEqual(r["suggested_cv"], "cvmain")

    # ---- hiring signals
    def test_signals_from_board_snapshots(self):
        store.add_board("greenhouse", "sigco", "SigCo")
        b = dict(store.q1("SELECT * FROM boards WHERE slug = 'sigco'"))
        base = [{"title": "Engineer %d" % i, "company": "SigCo", "location": "Berlin, Germany", "url": "https://x/%d" % i} for i in range(3)]
        signals.record_board(b, base, "SigCo")
        self.assertEqual(signals.compute("TN", [])["sigco"]["new"], 0)            # first snapshot = baseline, nothing is "new"
        store.run("UPDATE boards SET tracked_since = ? WHERE id = ?", (store.now() - 10 * 86400, b["id"]))
        store.run("UPDATE postings SET first_seen = ? WHERE board_id = ?", (store.now() - 10 * 86400, b["id"]))
        store.run("UPDATE companies SET watch = 1 WHERE key = 'sigco'") if store.q1("SELECT 1 FROM companies WHERE key='sigco'") else \
            store.run("INSERT INTO companies(key, name, watch) VALUES('sigco', 'SigCo', 1)")
        more = base + [{"title": "Comptable", "company": "SigCo", "location": "Tunis, Tunisia", "url": "https://x/tn%d" % i} for i in range(5)]
        n0 = store.q1("SELECT COUNT(*) AS n FROM notifications")["n"]
        self.assertEqual(signals.record_board(b, more, "SigCo"), 5)
        s = signals.compute("TN", matcher.me()["families"])["sigco"]
        self.assertEqual(s["new"], 5)
        self.assertIn("TN", s["new_countries"])
        self.assertEqual(s["in_my_country"], 5)
        self.assertEqual(s["my_field"], 5)
        self.assertGreaterEqual(s["heat"], 60)
        self.assertGreater(store.q1("SELECT COUNT(*) AS n FROM notifications")["n"], n0)   # watched company posted -> notified
        signals.record_board(b, more[3:], "SigCo")                                          # 3 postings closed
        self.assertEqual(store.q1("SELECT COUNT(*) AS n FROM postings WHERE board_id = ? AND gone_at IS NOT NULL", (b["id"],))["n"], 3)
        r = self.c.get("/api/signals?country=TN").get_json()
        self.assertTrue(any(c["key"] == "sigco" for c in r["companies"]))

    # ---- spontaneous applications
    def test_outreach_flow(self):
        store.run("UPDATE companies SET emails = ?, email_types = ?, domain = 'stram.tn', country = 'TN' WHERE key = ?",
                  (json.dumps(["contact@stram.tn", "rh@stram.tn"]), json.dumps({"contact@stram.tn": "general", "rh@stram.tn": "recruiting"}), "stram"))
        store.run("INSERT OR IGNORE INTO companies(key, name, domain, emails, email_types, country) VALUES('gmailco', 'Gmail Co', '', ?, '{}', 'TN')",
                  (json.dumps(["boss.gmailco@gmail.com"]),))
        store.run("INSERT OR IGNORE INTO companies(key, name, domain, emails, email_types, country) VALUES('gmailco2', 'Other Co', '', ?, '{}', 'TN')",
                  (json.dumps(["owner.other@gmail.com"]),))
        cands, n = outreach.candidates(country="TN")
        stram = next(c for c in cands if c["key"] == "stram")
        self.assertEqual(stram["contact"]["email"], "rh@stram.tn")       # the recruiting inbox beats contact@
        made = self.c.post("/api/outreach/drafts", json={"items": [{"key": "stram"}, {"key": "gmailco"}, {"key": "gmailco2"}]}, headers=H).get_json()["created"]
        self.assertEqual(made, 3)                                          # two gmail.com companies are NOT the same company
        self.assertEqual(self.c.post("/api/outreach/drafts", json={"items": [{"key": "stram"}]}, headers=H).get_json()["created"], 0)
        d = store.q1("SELECT * FROM outreach WHERE company_key = 'stram'")
        self.assertEqual(d["lang"], "fr")
        self.assertIn("Stram SA", d["body"])
        self.assertIn("Madame, Monsieur", d["body"])
        self.assertNotRegex(d["body"], r"\{[a-z_]+\}")
        self.assertEqual(d["cv_id"], "cvmain")
        bad = self.c.put("/api/outreach/%d" % d["id"], json={"body": "Hello {company_x}", "status": "queued"}, headers=H)
        self.assertEqual(bad.status_code, 400)
        ok = self.c.put("/api/outreach/%d" % d["id"], json={"body": d["body"], "status": "queued"}, headers=H).get_json()
        self.assertEqual(ok["item"]["status"], "queued")
        pv = self.c.get("/api/outreach/preview/%d" % d["id"]).get_json()
        self.assertEqual(pv["attachments"][0]["name"], "Amira_Trabelsi_CV.pdf")
        # send with a fake SMTP server
        sent = []

        class FakeSMTP:
            def send_message(self, msg):
                sent.append(msg)

            def quit(self):
                pass
        orig_smtp, orig_mx = outreach._smtp, outreach.enrich_has_mx if hasattr(outreach, "enrich_has_mx") else None
        import enrich
        orig_has_mx = enrich.has_mx
        outreach._smtp = lambda st: FakeSMTP()
        enrich.has_mx = lambda dom: True
        try:
            row = dict(store.q1("SELECT * FROM outreach WHERE id = ?", (d["id"],)))
            st = outreach.settings()
            st.update(user="amira@example.com", attach_cv=1)
            self.assertTrue(outreach.send_one(row, st))
            self.assertEqual(sent[0]["To"], "rh@stram.tn")
            self.assertEqual(len(list(sent[0].iter_attachments())), 1)
            # the same company is never written to twice
            store.run("INSERT INTO outreach(company_key, company, domain, to_email, status, created_at, kind) VALUES('x', 'Stram again', 'stram.tn', 'ceo@stram.tn', 'queued', ?, 'first')", (store.now(),))
            again = dict(store.q1("SELECT * FROM outreach WHERE to_email = 'ceo@stram.tn'"))
            self.assertFalse(outreach.send_one(again, st))
            self.assertEqual(store.q1("SELECT status FROM outreach WHERE id = ?", (again["id"],))["status"], "cancelled")
        finally:
            outreach._smtp = orig_smtp
            enrich.has_mx = orig_has_mx
        # follow-up draft after N days without answer
        store.run("UPDATE outreach SET sent_at = ? WHERE id = ?", (store.now() - 8 * 86400, d["id"]))
        st = outreach.settings()
        st["followup_days"] = 7
        self.assertEqual(outreach.make_followups(st), 1)
        f = store.q1("SELECT * FROM outreach WHERE parent_id = ?", (d["id"],))
        self.assertEqual((f["kind"], f["status"]), ("followup", "draft"))
        self.assertTrue(f["subject"].startswith("Re: "))
        self.assertEqual(outreach.make_followups(st), 0)

    def test_contact_choice_and_french_wording(self):
        self.assertIsNone(outreach.best_contact("nobody", ["legal@supabase.com", "privacy@supabase.com"], {}, "supabase.com"))
        self.assertEqual(outreach.best_contact("nobody", ["legal@a.com", "hello@a.com"], {}, "a.com")["email"], "hello@a.com")
        v = outreach._vars("Stram", {}, "fr")
        self.assertRegex(v["{years}"], r"^\d+ ans?$")                  # "6 ans", never "6.1 ans"
        self.assertIn("comptabilité", v["{my_skills}"])
        self.assertNotIn("Accounting", v["{my_skills}"])
        self.assertTrue(signals.is_anonymous("entreprise anonyme"))
        self.assertFalse(signals.is_anonymous("stram"))

    def test_reply_classifier(self):
        self.assertEqual(outreach.classify_reply("Bonjour, seriez-vous disponible pour un entretien jeudi ?"), "interview")
        self.assertEqual(outreach.classify_reply("Unfortunately we decided not to move forward."), "rejection")
        self.assertEqual(outreach.classify_reply("Je suis absent du bureau jusqu'au 12. Réponse automatique."), "auto")

    def test_sending_window(self):
        from datetime import datetime
        st = {"weekdays": 1, "window": "09:00-18:00"}
        self.assertTrue(outreach._in_window(st, datetime(2026, 9, 29, 10, 0)))       # Tuesday
        self.assertFalse(outreach._in_window(st, datetime(2026, 9, 29, 20, 0)))
        self.assertFalse(outreach._in_window(st, datetime(2026, 10, 3, 10, 0)))      # Saturday

    # ---- night scan
    def test_night_run_and_report(self):
        calls = []
        saved = dict(nightly.RUNNERS)
        for k in saved:
            nightly.RUNNERS[k] = (lambda name: (lambda report, c: (calls.append(name), report("ok", 1))))(k)
        try:
            rid = nightly.start("manual")
            for _ in range(100):
                if not nightly.running():
                    break
                time.sleep(0.05)
        finally:
            nightly.RUNNERS.update(saved)
        run = nightly.history(1)[0]
        self.assertEqual(run["id"], rid)
        self.assertEqual(run["status"], "done")
        self.assertEqual(len(calls), len(nightly.STAGES))
        self.assertIn("Good morning", run["report"]["headline"])
        r = self.c.get("/api/night").get_json()
        self.assertEqual(r["history"][0]["id"], rid)
        s = self.c.get("/api/stats").get_json()["stats"]
        self.assertEqual(s["night"]["id"], rid)

    def test_night_schedule_and_catchup(self):
        from datetime import datetime
        store.run("DELETE FROM night_runs")
        c = {"time": "02:00", "catchup": 1}
        self.assertEqual(nightly._due(c, datetime(2026, 9, 29, 2, 5)), "schedule")
        self.assertIsNone(nightly._due(c, datetime(2026, 9, 29, 9, 0)))              # no run ever: no surprise daytime scan
        store.run("INSERT INTO night_runs(started_at, finished_at, status, trigger) VALUES(?,?,?,?)",
                  (int(datetime(2026, 9, 27, 2, 0).timestamp()), int(datetime(2026, 9, 27, 3, 0).timestamp()), "done", "schedule"))
        self.assertEqual(nightly._due(c, datetime(2026, 9, 29, 9, 0)), "catch-up")    # PC was off last night
        store.run("INSERT INTO night_runs(started_at, status, trigger) VALUES(?,?,?)", (int(datetime(2026, 9, 29, 2, 0).timestamp()), "done", "schedule"))
        self.assertIsNone(nightly._due(c, datetime(2026, 9, 29, 3, 0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

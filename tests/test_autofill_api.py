"""Applicant profile, CV versions and the extension endpoints (pairing-code protected)."""
import io
import os
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-af-")
os.environ.setdefault("JOBRADAR_DATA", TMP)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import applicant  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402

H = {"X-JobRadar": "1"}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class TestAutofillApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.set_db_path(os.path.join(TMP, "af.db"))
        store.init()
        cls.c = server.app.test_client()

    def ext(self, method, url, **kw):
        headers = dict(kw.pop("headers", {}), **{"X-JobRadar-Token": applicant.token(), "X-JobRadar": "1"})
        return self.c.open(url, method=method, headers=headers, **kw)

    def test_profile_roundtrip_and_validation(self):
        r = self.c.put("/api/profile", json={"first_name": "Amira", "last_name": "Trabelsi", "email": "amira@example.com",
                                             "linkedin": "linkedin.com/in/amira", "authorized_to_work": "yes",
                                             "cover_letter": "Dear {company}, I apply for {job_title}. {my_name}"}, headers=H)
        p = r.get_json()["profile"]
        self.assertEqual(p["linkedin"], "https://linkedin.com/in/amira")
        self.assertTrue(r.get_json()["token"].startswith("JR-"))
        self.assertEqual(self.c.put("/api/profile", json={"email": "not-an-email"}, headers=H).status_code, 400)
        self.assertEqual(self.c.put("/api/profile", json={"authorized_to_work": "maybe"}, headers=H).status_code, 400)
        self.assertEqual(self.c.put("/api/profile", json={"first_name": "x"}).status_code, 403)     # UI header required

    def test_cv_upload_validation_download_delete(self):
        up = lambda data, name: self.c.post("/api/profile/cv", data={"file": (io.BytesIO(data), name)}, headers=H,  # noqa: E731
                                            content_type="multipart/form-data")
        self.assertEqual(up(b"not a pdf", "cv.pdf").status_code, 400)
        self.assertEqual(up(b"MZ\x90", "cv.exe").status_code, 400)
        r = up(PDF, "Amira CV.pdf")
        self.assertEqual(r.status_code, 200)
        cid = r.get_json()["id"]
        cvs = r.get_json()["cvs"]
        self.assertTrue(any(c["id"] == cid and c["label"] == "Amira CV" for c in cvs))
        self.assertEqual(self.c.get("/api/profile/cv/" + cid).data, PDF)
        cid2 = up(PDF, "French CV.pdf").get_json()["id"]
        self.c.put("/api/profile/cv/" + cid2, json={"default": True}, headers=H)
        self.assertTrue(next(c for c in applicant.cvs() if c["id"] == cid2)["default"])
        self.c.delete("/api/profile/cv/" + cid2, headers=H)
        self.assertTrue(next(c for c in applicant.cvs() if c["id"] == cid)["default"])   # default falls back

    def test_extension_requires_pairing_code(self):
        self.assertEqual(self.c.get("/ext/profile").status_code, 401)
        self.assertEqual(self.c.get("/ext/profile", headers={"X-JobRadar-Token": "JR-wrong"}).status_code, 401)
        self.c.put("/api/profile", json={"first_name": "Amira", "last_name": "Trabelsi",
                                         "cover_letter": "Dear {company}, I apply for {job_title}. {my_name}"}, headers=H)
        r = self.ext("GET", "/ext/profile?title=Junior%20Accountant&company=Acme")
        prof = r.get_json()["profile"]
        self.assertEqual(prof["full_name"], "Amira Trabelsi")
        self.assertEqual(prof["cover_letter"], "Dear Acme, I apply for Junior Accountant. Amira Trabelsi")
        old = applicant.token()
        self.c.post("/api/profile/token", headers=H)
        self.assertEqual(self.c.get("/ext/ping", headers={"X-JobRadar-Token": old}).status_code, 401)   # old code revoked
        self.assertEqual(self.ext("GET", "/ext/ping").status_code, 200)

    def test_mark_applied_matches_or_creates(self):
        jid, _ = store.upsert_job(engine.normalize({"title": "Comptable", "company": "Stram", "location": "Tunis",
                                                    "url": "https://www.keejob.com/offres-emploi/1/comptable/"}, "national"))
        r = self.ext("POST", "/ext/applied", json={"url": "https://www.keejob.com/offres-emploi/1/comptable/?utm=x", "title": "x"})
        self.assertEqual(r.get_json()["job_id"], jid)
        self.assertFalse(r.get_json()["created"])
        row = store.q1("SELECT status, notes FROM jobs WHERE id = ?", (jid,))
        self.assertEqual(row["status"], "applied")
        self.assertIn("Applied with JobRadar Autofill", row["notes"])
        r = self.ext("POST", "/ext/applied", json={"url": "https://careers.newco.io/apply/77", "title": "Data Analyst", "company": "NewCo"})
        self.assertTrue(r.get_json()["created"])
        new = store.q1("SELECT title, company, status FROM jobs WHERE id = ?", (r.get_json()["job_id"],))
        self.assertEqual((new["title"], new["company"], new["status"]), ("Data Analyst", "NewCo", "applied"))
        self.assertEqual(self.ext("POST", "/ext/applied", json={"url": "javascript:alert(1)"}).status_code, 400)

    def test_practice_form_page(self):
        r = self.c.get("/autofill-test")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"application_form", r.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Recruiter finder, email intelligence, job insights and deep company enrichment (no network)."""
import os
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="jobradar-rec-")
os.environ.setdefault("JOBRADAR_DATA", TMP)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine  # noqa: E402
import enrich  # noqa: E402
import insights  # noqa: E402
import recruiters as R  # noqa: E402
import store  # noqa: E402

TEAM_PAGE = """<html><body><h1>Meet our team</h1>
<div class="grid">
  <div class="card"><img src="a.jpg"><h3>Sarah Johnson</h3><p>Head of Talent Acquisition</p>
     <a href="mailto:sarah.johnson@acme.io">Email</a> <a href="https://www.linkedin.com/in/sarahjohnson/">LinkedIn</a></div>
  <div class="card"><h3>Marc Dupont</h3><p>CEO &amp; Co-Founder</p></div>
  <div class="card"><h3>Lina Ben Salah</h3><span>Senior Backend Engineer</span></div>
  <div class="card"><h3>Read More</h3><p>About our values</p></div>
  <div class="card"><h3>Customer Success</h3><p>Head of Support team</p></div>
</div>
<footer><a href="mailto:jobs@acme.io">jobs@acme.io</a> <a href="mailto:info@acme.io">Contact us</a></footer></body></html>"""

IMPRESSUM = """<html><body><h1>Impressum</h1><p>Acme GmbH<br>Musterstraße 1, 10115 Berlin</p>
<p>Geschäftsführer: Max Mustermann, Erika Musterfrau</p><p>Vertreten durch: Jonas Weber</p>
<p>Telefon: +49 30 1234567 E-Mail: kontakt@acme.de</p></body></html>"""

MENTIONS = """<html><body><h2>Mentions légales</h2><p>Directeur de la publication : Karim Haddad</p>
<p>Gérante : Sophie Martin</p></body></html>"""

JSONLD = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Globex",
"description":"We build rockets.","foundingDate":"2012","numberOfEmployees":{"@type":"QuantitativeValue","value":250},
"address":{"@type":"PostalAddress","streetAddress":"1 Main St","addressLocality":"Austin","addressCountry":"US"},
"founder":[{"@type":"Person","name":"Hank Scorpio","jobTitle":"Founder & CEO","sameAs":["https://www.linkedin.com/in/hankscorpio"]}],
"employee":{"@type":"Person","name":"Laura Chen","jobTitle":"Recruiting Lead","email":"mailto:laura.chen@globex.com"}}</script>
</head><body><h1>Globex</h1></body></html>"""

JOB_TEXT = """We are hiring a Warehouse Supervisor in Sfax.
Your contact: Amira Trabelsi, HR Manager
Email: amira.trabelsi@stram.tn - Tel: +216 71 234 567
Apply before 30/11/2026."""


class TestPeople(unittest.TestCase):
    def names(self, people):
        return {p["name"]: p for p in people}

    def test_team_cards(self):
        ppl = self.names(R.people_from_html(TEAM_PAGE, "https://acme.io/team", "Acme"))
        self.assertIn("Sarah Johnson", ppl)
        s = ppl["Sarah Johnson"]
        self.assertEqual((s["role"], s["email"]), ("hr", "sarah.johnson@acme.io"))
        self.assertTrue(s["linkedin"].startswith("https://www.linkedin.com/in/sarahjohnson"))
        self.assertEqual(ppl["Marc Dupont"]["role"], "leader")
        self.assertNotIn("Read More", ppl)
        self.assertNotIn("Customer Success", ppl)
        ranked = R.people_from_html(TEAM_PAGE, "", "Acme")
        self.assertEqual(ranked[0]["name"], "Sarah Johnson")          # HR ranks first

    def test_impressum_and_mentions(self):
        ppl = self.names(R.people_from_html(IMPRESSUM, "https://acme.de/impressum", "Acme GmbH"))
        self.assertIn("Max Mustermann", ppl)
        self.assertIn("Jonas Weber", ppl)
        self.assertEqual(ppl["Max Mustermann"]["role"], "leader")
        fr = self.names(R.people_from_html(MENTIONS, "", "X"))
        self.assertIn("Karim Haddad", fr)
        self.assertIn("Sophie Martin", fr)

    def test_jsonld_people(self):
        ppl = self.names(R.people_from_html(JSONLD, "", "Globex"))
        self.assertEqual(ppl["Laura Chen"]["email"], "laura.chen@globex.com")
        self.assertEqual(ppl["Laura Chen"]["role"], "hr")
        self.assertIn("linkedin.com/in/hankscorpio", ppl["Hank Scorpio"]["linkedin"])

    def test_job_post_contact(self):
        ppl = R.people_from_text(JOB_TEXT, "u", "STRAM", from_job=True, region="TN")
        self.assertEqual(ppl[0]["name"], "Amira Trabelsi")
        self.assertEqual(ppl[0]["title"], "HR Manager")
        self.assertEqual(ppl[0]["email"], "amira.trabelsi@stram.tn")
        self.assertGreater(ppl[0]["score"], 130)

    def test_names_and_emails(self):
        self.assertEqual(R.clean_name("Dr. Jean-Luc Picard"), "Jean-Luc Picard")
        self.assertEqual(R.clean_name("Ludwig van Beethoven"), "Ludwig van Beethoven")
        for bad in ("Our Team", "Privacy Policy", "New York", "Learn More", "Hello", "ACME GMBH", "The Best Company Ever In Town"):
            self.assertEqual(R.clean_name(bad), "", bad)
        self.assertEqual(R.email_type("jobs@acme.io"), "recruiting")
        self.assertEqual(R.email_type("rh@stram.tn"), "recruiting")
        self.assertEqual(R.email_type("bewerbung@firma.de"), "recruiting")
        self.assertEqual(R.email_type("info@acme.io"), "general")
        self.assertEqual(R.email_type("sarah.johnson@acme.io"), "personal")
        self.assertTrue(R.email_belongs_to("sarah.johnson@acme.io", "Sarah Johnson"))
        self.assertTrue(R.email_belongs_to("sjohnson@acme.io", "Sarah Johnson"))
        self.assertFalse(R.email_belongs_to("info@acme.io", "Sarah Johnson"))
        # regressions from the live run on keejob pages
        for bad in ("Directeur Général", "Technicien Infrastructure Cybersécurité", "Espace Recruteur", "Debt Recovery Advisor",
                    "Entreprise Anonyme", "Audit Interne Groupe", "Responsable Achats"):
            self.assertEqual(R.clean_name(bad), "", bad)
        self.assertEqual(R.clean_name("Amira Trabelsi", strict=True), "Amira Trabelsi")
        self.assertEqual(R.clean_name("Quantum Leap", strict=True), "")
        self.assertEqual(R.email_type("inforecruteur@keejob.com"), "recruiting")
        self.assertEqual(R.email_type("contact@stram.tn"), "general")
        self.assertEqual(R.email_type("zzqx@acme.io"), "other")
        import extract
        self.assertEqual(extract.company_domain("https://www.keejob.com/offres-emploi/1/x/"), "")
        self.assertEqual(extract.company_domain("https://www.jobberman.com/listings/x"), "")
        self.assertEqual(extract.company_domain("https://careers.acme.io/jobs/1"), "acme.io")
        self.assertEqual(extract.company_domain("https://www.acme.co.uk/careers"), "acme.co.uk")
        self.assertEqual(R.classify_title("Chargée de recrutement"), "hr")
        self.assertEqual(R.classify_title("Personalreferentin"), "hr")
        self.assertEqual(R.classify_title("Directeur Général"), "leader")
        self.assertEqual(R.classify_title("Engineering Manager"), "manager")


class TestInsights(unittest.TestCase):
    def test_multilingual(self):
        d = ("Poste en CDI. Vous justifiez d'au moins 3 ans d'expérience. Diplôme d'ingénieur ou Bac+5. "
             "Maîtrise du français et de l'anglais courant. Compétences: Excel, SAP, Power BI. Tickets restaurant, mutuelle. "
             "Date limite: 15/12/2026")
        i = insights.analyze("Contrôleur de gestion confirmé", d)
        self.assertEqual(i["experience_years"], 3)
        self.assertEqual(i["education"], "Master's")
        self.assertEqual(set(i["languages"]), {"French", "English"})
        self.assertIn("SAP", i["skills"])
        self.assertIn("power bi", i["skills"])
        self.assertIn("Permanent (CDI)", i["contract"])
        self.assertEqual(i["seniority"], "Senior")
        self.assertIn("Meal vouchers", i["benefits"])
        self.assertIn("deadline", i)
        de = insights.analyze("Werkstudent Marketing", "Mindestens 2 Jahre Erfahrung, fließend Deutsch und Englisch, Teilzeit, visa sponsorship")
        self.assertEqual(de["experience_years"], 2)
        self.assertIn("Visa sponsorship", de["benefits"])
        self.assertIn("Part-time", de["contract"])

    def test_normalize_attaches_insights_and_contacts(self):
        j = engine.normalize({"title": "Warehouse Supervisor", "company": "STRAM", "location": "Sfax", "description": JOB_TEXT, "url": "u"}, "t")
        self.assertEqual(j["contacts"][0]["name"], "Amira Trabelsi")
        self.assertIn("deadline", j["insights"])


class TestDeepEnrich(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        store.set_db_path(os.path.join(TMP, "rec.db"))
        store.init()

    def test_enrich_builds_profile_people_and_email_types(self):
        store.upsert_job(engine.normalize({"title": "Backend Engineer", "company": "Acme", "location": "Berlin",
                                           "url": "https://acme.io/jobs/1", "apply_url": "https://acme.io/jobs/1"}, "t"))
        store.refresh_companies()

        class Resp:
            def __init__(self, url, text):
                self.url, self.text, self.headers = url, text, {"content-type": "text/html; charset=utf-8"}
        home = JSONLD.replace("Globex", "Acme") .replace("<h1>Acme</h1>", '<h1>Acme</h1><a href="/team">Our team</a><a href="/impressum">Impressum</a>')
        site = {"https://acme.io": home, "https://acme.io/team": TEAM_PAGE, "https://acme.io/impressum": IMPRESSUM}
        visited = []

        def fake_fetch(url, **kw):
            visited.append(url)
            u = url.rstrip("/")
            if u in site:
                return Resp(u, site[u])
            from net import FetchError
            raise FetchError("404", 404)
        orig, orig_mx = enrich.fetch, enrich.has_mx
        enrich.fetch, enrich.has_mx = fake_fetch, lambda d: True
        try:
            c = enrich.enrich_company(store.company_key("Acme"))
        finally:
            enrich.fetch, enrich.has_mx = orig, orig_mx
        self.assertEqual(visited[0], "https://acme.io")
        self.assertIn("https://acme.io/team", visited[:3])            # team page crawled before guesses
        self.assertEqual(c["founded"], "2012")
        self.assertEqual(c["employees"], "250")
        self.assertIn("Austin", c["address"])
        self.assertEqual(c["email_types"]["jobs@acme.io"], "recruiting")
        self.assertEqual(c["emails"][0], "jobs@acme.io")               # recruiting inbox listed first
        names = [p["name"] for p in c["people"]]
        self.assertIn("Sarah Johnson", names)
        self.assertIn("Max Mustermann", names)
        self.assertEqual(c["people"][0]["role"], "hr")
        # people are visible on the job and in the directory
        job = store.get_job(store.q1("SELECT id FROM jobs")["id"])
        self.assertTrue(any(p["name"] == "Sarah Johnson" for p in job["people"]))
        rows, total = store.list_people({"role": "hr"})
        self.assertTrue(any(r["name"] == "Laura Chen" or r["name"] == "Sarah Johnson" for r in rows))
        jobs, _ = store.list_jobs({"has_recruiter": True})
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

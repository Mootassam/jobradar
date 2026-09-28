"""Structured insights pulled out of a job's title + description (multilingual: EN / FR / DE / ES / IT / AR)."""
import re
from datetime import datetime

SKILLS = """python|java|javascript|typescript|c++|c#|.net|go|golang|rust|php|ruby|kotlin|swift|scala|r|matlab|sql|nosql|postgresql|mysql|
mongodb|redis|elasticsearch|oracle|sap|salesforce|excel|power bi|tableau|looker|react|angular|vue|next.js|node.js|django|flask|fastapi|
spring|laravel|symfony|rails|html|css|figma|photoshop|illustrator|indesign|autocad|solidworks|revit|aws|azure|gcp|google cloud|docker|
kubernetes|terraform|ansible|linux|git|jenkins|ci/cd|devops|machine learning|deep learning|ai|llm|nlp|computer vision|data science|
data analysis|statistics|pandas|spark|hadoop|kafka|airflow|dbt|snowflake|etl|seo|sem|google ads|facebook ads|social media|content marketing|
copywriting|crm|hubspot|zoho|erp|odoo|quickbooks|accounting|bookkeeping|payroll|ifrs|audit|tax|financial analysis|budgeting|
project management|agile|scrum|jira|pmp|prince2|lean|six sigma|supply chain|logistics|procurement|negotiation|b2b sales|customer service|
call center|telemarketing|cold calling|nursing|patient care|first aid|pharmacy|laboratory|teaching|training|recruitment|onboarding|
microsoft office|powerpoint|outlook|google workspace|cybersecurity|networking|cisco|itil|helpdesk|embedded|plc|electrical|
mechanical|civil engineering|hvac|welding|forklift|driving licence|driver's license|permis b|translation|interpretation|
video editing|premiere pro|after effects|3d|blender|unity|unreal|shopify|wordpress|magento|woocommerce|ux|ui|product management""".replace("\n", "")
_SKILL_LIST = [s.strip() for s in SKILLS.split("|") if s.strip()]
_SKILL_RX = [(s, re.compile(r"(?<![\w+#.])" + re.escape(s) + r"(?![\w+#])", re.I)) for s in _SKILL_LIST]
# "Go" and "R" only count inside a list of technologies ("Python, Go, Rust" / "SQL and R"), never in "Go to" / "R&D".
_LIST_ONLY = {k: re.compile(r"(?:[,/(|•]\s*|\band\s+|\bor\s+|\bet\s+)" + v + r"(?=\s*[,/)|•]|\s+(?:and|or|et)\b|\s*\.?\s*$)", re.M)
              for k, v in (("go", "Go"), ("r", "R"))}
# Short names that are also ordinary words/letters: only count them in their real spelling.
_CASE_SENSITIVE = {"r": "R", "go": "Go", "ai": "AI", "ui": "UI", "ux": "UX", "3d": "3D", "sap": "SAP", "git": "Git", "lean": "Lean"}

LANGS = {
    "English": r"english|anglais|englisch|inglés|ingles|inglese|الإنجليزية|الانجليزية",
    "French": r"french|français|francais|französisch|francés|frances|francese|الفرنسية",
    "German": r"german|allemand|deutsch|alemán|aleman|tedesco|الألمانية",
    "Arabic": r"arabic|arabe|arabisch|árabe|arabo|العربية",
    "Spanish": r"spanish|espagnol|spanisch|español|espanol|spagnolo|الإسبانية",
    "Italian": r"italian|italien|italienisch|italiano|الإيطالية",
    "Portuguese": r"portuguese|portugais|portugiesisch|portugués|portoghese",
    "Dutch": r"dutch|néerlandais|niederländisch|holandés|olandese",
    "Chinese": r"chinese|mandarin|chinois|chinesisch|chino|cinese",
    "Turkish": r"turkish|turc|türkisch|turco",
    "Russian": r"russian|russe|russisch|ruso|russo",
    "Japanese": r"japanese|japonais|japanisch|japonés|giapponese",
    "Hindi": r"hindi",
}
_LANG_RX = {k: re.compile(r"\b(?:%s)\b" % v, re.I) for k, v in LANGS.items()}
_LANG_CONTEXT = re.compile(r"language|langue|sprache|idioma|lingua|fluent|courant|fließend|bilingual|bilingue|native|maîtrise|"
                           r"proficien|written|spoken|oral|écrit|niveau|level|c1|c2|b2|اللغة|لغة", re.I)

EDU = [("PhD / Doctorate", r"\b(ph\.?d|doctorate|doctorat|promotion|doctorado|dottorato)\b"),
       ("Master's", r"\b(master'?s?|msc|m\.sc|mba|bac\s*\+\s*5|ingénieur d'état|diplôme d'ingénieur|mastère|máster|laurea magistrale)\b"),
       ("Bachelor's", r"\b(bachelor'?s?|bsc|b\.sc|licence|bac\s*\+\s*3|grado|laurea|undergraduate degree|university degree)\b"),
       ("Associate / BTS", r"\b(bac\s*\+\s*2|bts|dut|associate degree|technicien supérieur)\b"),
       ("High school", r"\b(high school|baccalauréat|baccalaureat|abitur|bachillerato)\b")]
_EDU_RX = [(k, re.compile(v, re.I)) for k, v in EDU]

CONTRACTS = [("Permanent (CDI)", r"\bcdi\b|permanent|unbefristet|indefinido|tempo indeterminato"),
             ("Fixed-term (CDD)", r"\bcdd\b|fixed[- ]term|befristet|temporal|tempo determinato"),
             ("Freelance / Contract", r"freelance|contractor|independent contractor|\bcontract\b|auto-entrepreneur|freiberuf"),
             ("Internship", r"intern(ship)?\b|stage\b|stagiaire|praktikum|praktikant|prácticas|pasantía|tirocinio|stagista"),
             ("Apprenticeship", r"apprentic|alternance|ausbildung|duales studium|apprendistato"),
             ("Part-time", r"part[- ]time|temps partiel|teilzeit|media jornada|tiempo parcial|part time"),
             ("Full-time", r"full[- ]time|temps plein|vollzeit|jornada completa|tempo pieno")]
_CONTRACT_RX = [(k, re.compile(v, re.I)) for k, v in CONTRACTS]

SENIORITY = [("Intern", r"\bintern\b|stagiaire|praktikant|trainee|\bstage\b"), ("Junior", r"\bjunior\b|\bjr\.?\b|entry[- ]level|graduate|débutant"),
             ("Senior", r"\bsenior\b|\bsr\.?\b|confirmé|expérimenté"), ("Lead", r"\blead\b|principal|staff engineer|architect"),
             ("Manager", r"\bmanager\b|responsable|leiter|\bhead of\b|chef de"), ("Director", r"director|directeur|directrice|\bvp\b|vice president|chief")]
_SEN_RX = [(k, re.compile(v, re.I)) for k, v in SENIORITY]

BENEFITS = [("Visa sponsorship", r"visa sponsor|sponsor(ship)? (a |your )?visa|work permit support|visa support|parrainage de visa|visum"),
            ("Relocation", r"relocation|relocation package|déménagement pris en charge|umzugshilfe|reubicación"),
            ("Remote / hybrid", r"remote|hybrid|télétravail|home ?office|teletrabajo|smart working"),
            ("Health insurance", r"health insurance|medical insurance|mutuelle|krankenversicherung|seguro médico|assurance maladie"),
            ("Bonus", r"\bbonus|prime|commission|variable pay|13th month|13ème mois|13\. monatsgehalt"),
            ("Equity / stock options", r"equity|stock options|esop|bspce|aktienoptionen"),
            ("Training", r"training budget|learning budget|formation|weiterbildung|certification"),
            ("Meal vouchers", r"meal voucher|tickets? restaurant|essenszuschuss|cheques? repas"),
            ("Company car", r"company car|voiture de fonction|dienstwagen|coche de empresa"),
            ("Flexible hours", r"flexible hours|flexible working|horaires flexibles|gleitzeit|flexibilidad horaria"),
            ("Paid leave+", r"unlimited (pto|vacation)|30 days|25 days of (paid )?(leave|vacation)|congés payés")]
_BEN_RX = [(k, re.compile(v, re.I)) for k, v in BENEFITS]

_EXP_RX = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to|à|a|bis)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?|ans?|années?|jahre?n?|años|anni)"
                     r"(?:[^.\n]{0,60}?)?(?=[^.\n]{0,60}(?:experience|expérience|erfahrung|experiencia|esperienza|professional))", re.I)
_EXP_RX2 = re.compile(r"(?:experience|expérience|erfahrung|experiencia|esperienza)[^.\n]{0,40}?(\d{1,2})\s*(?:\+)?\s*(?:(?:-|–|to|à|bis)\s*(\d{1,2}))?\s*"
                      r"(?:years?|yrs?|ans?|années?|jahre?n?|años|anni)", re.I)
_DEADLINE_RX = re.compile(r"(?:deadline|apply (?:by|before)|closing date|applications? close|date limite|avant le|bewerbungsfrist|fecha límite|"
                          r"scadenza)[^\d\n]{0,25}(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-zéû]+\s+\d{4})", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
_MONTHS.update({m: i + 1 for i, m in enumerate("janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split())})


def _deadline(text):
    m = _DEADLINE_RX.search(text)
    if not m:
        return None
    s = m.group(1)
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            pass
    parts = s.split()
    if len(parts) == 3 and parts[1].lower() in _MONTHS:
        try:
            return int(datetime(int(parts[2]), _MONTHS[parts[1].lower()], int(parts[0])).timestamp())
        except ValueError:
            return None
    return None


def analyze(title, description):
    title = title or ""
    text = description or ""
    both = title + "\n" + text
    out = {}
    exp = []
    for rx in (_EXP_RX, _EXP_RX2):
        for m in rx.finditer(text[:20000]):
            lo = int(m.group(1))
            if 0 < lo <= 25:
                exp.append(lo)
    if exp:
        out["experience_years"] = min(exp)
    edu = [k for k, rx in _EDU_RX if rx.search(text)]
    if edu:
        out["education"] = edu[0]
    langs = []
    for k, rx in _LANG_RX.items():
        for m in rx.finditer(text[:20000]):
            ctx = text[max(0, m.start() - 80): m.end() + 80]
            if _LANG_CONTEXT.search(ctx):
                langs.append(k)
                break
    if langs:
        out["languages"] = langs
    skills = []
    low = both[:25000]
    for s, rx in _SKILL_RX:
        exact = _CASE_SENSITIVE.get(s)
        if s in _LIST_ONLY:
            if _LIST_ONLY[s].search(low):
                skills.append(exact)
            continue
        if exact:
            if re.search(r"(?<![\w+#.])" + re.escape(exact) + r"(?![\w+#])", low):
                skills.append(exact)
        elif rx.search(low):
            skills.append(s)
    if skills:
        out["skills"] = skills[:25]
    contracts = [k for k, rx in _CONTRACT_RX if rx.search(both[:15000])]
    if contracts:
        out["contract"] = contracts[:3]
    sen = [k for k, rx in _SEN_RX if rx.search(title)]
    if sen:
        out["seniority"] = sen[-1] if "Intern" not in sen else "Intern"
    elif out.get("experience_years") is not None:
        y = out["experience_years"]
        out["seniority"] = "Junior" if y <= 2 else "Mid-level" if y <= 5 else "Senior"
    ben = [k for k, rx in _BEN_RX if rx.search(text[:20000])]
    if ben:
        out["benefits"] = ben
    dl = _deadline(text[:20000])
    if dl:
        out["deadline"] = dl
    return out

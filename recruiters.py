"""Recruiter finder: people and contact channels that a company PUBLISHES itself - on its website (team, about,
leadership, imprint/legal, contact, careers pages) or inside its job posts.

Extraction methods (combined, de-duplicated, ranked):
  1. schema.org Person / Organization.founder / employee / contactPoint in JSON-LD
  2. team "cards": a name next to a job title in the same small block (with its mailto / tel / LinkedIn link)
  3. labelled lines: "Geschäftsführer: Max Muster", "Contact person: Jane Doe, HR Manager", "Gérant : ..."
  4. "Jane Doe, Talent Acquisition Manager" lines and mailto links whose text is a person's name
Nothing is guessed: no invented email addresses, no LinkedIn scraping (only profile links the site shows)."""
import json
import re

from bs4 import BeautifulSoup

import extract

# ---------------------------------------------------------------- roles (EN / FR / DE / ES / IT / AR)
HR_TERMS = ("recruit", "talent acquisition", "talent partner", "talent manager", "talent lead", "sourcer", "human resources",
            "hr manager", "hr business", "hr generalist", "hr director", "hr specialist", "hr officer", "hr lead", "head of hr",
            "hrbp", "people partner", "people operations", "people & culture", "people and culture", "head of people",
            "chief people", "vp people", "chro", "hiring", "ressources humaines", "responsable rh", "chargé rh", "chargée rh",
            "directeur rh", "directrice rh", "drh", "recrutement", "recruteur", "recruteuse", "talent", "personalreferent",
            "personalleiter", "personalleitung", "personalabteilung", "personalwesen", "personalmanager", "recruiterin",
            "recursos humanos", "reclutamiento", "reclutador", "reclutadora", "selección de personal", "risorse umane",
            "selezione del personale", "ansprechpartner", "contact person", "personne à contacter", "الموارد البشرية", "التوظيف", "مسؤول التوظيف")
LEADER_TERMS = ("ceo", "founder", "co-founder", "cofounder", "managing director", "geschäftsführer", "geschäftsführerin",
                "geschaeftsfuehrer", "gérant", "gérante", "gerant", "président", "presidente", "president", "owner", "inhaber",
                "inhaberin", "directeur général", "directrice générale", "director general", "directora general", "fundador",
                "fundadora", "fondateur", "fondatrice", "general manager", "country manager", "managing partner", "المدير العام",
                "المؤسس", "vertreten durch", "represented by", "directeur de la publication", "responsable de la publication")
MANAGER_TERMS = ("head of", "director", "manager", "team lead", "tech lead", "engineering lead", "lead ", "vp ", "vice president",
                 "cto", "coo", "cfo", "cmo", "cpo", "cio", "chief", "directeur", "directrice", "responsable", "leiter", "leiterin",
                 "jefe", "jefa", "direttore", "responsabile", "supervisor", "principal", "partner")

ROLE_SCORE = {"hr": 100, "leader": 70, "manager": 60, "other": 25}
ROLE_LABEL = {"hr": "HR / Recruiting", "leader": "Leadership", "manager": "Hiring manager", "other": "Team"}


def _terms_rx(terms):
    # Whole-word matching: "cto" must not fire inside "Contacto" or "October". Stems like "recruit" keep a free tail.
    stems = ("recruit", "recrut", "talent", "personal", "hiring")
    parts = []
    for w in terms:
        w = w.strip()
        tail = r"\w*" if any(w.startswith(s) for s in stems) else ""
        parts.append(r"(?<!\w)" + re.escape(w) + tail + r"(?!\w)")
    return re.compile("|".join(parts), re.I)


_HR_RX = _terms_rx(HR_TERMS + ("hr", "rh"))
_LEADER_RX = _terms_rx(LEADER_TERMS)
_MANAGER_RX = _terms_rx(MANAGER_TERMS)


def classify_title(title):
    t = title or ""
    if _HR_RX.search(t):
        return "hr"
    if _LEADER_RX.search(t):
        return "leader"
    if _MANAGER_RX.search(t):
        return "manager"
    return "other"


def looks_like_title(text):
    """A short job title, not a sentence that happens to contain 'manager'."""
    if not text or len(text) > 60 or len(text.split()) > 7 or text.rstrip().endswith((".", ":", ";")):
        return False
    low = " %s " % text.lower()
    if any(w in low for w in (" we ", " you ", " our ", " the ", " vous ", " nous ", " est ", " sont ", " wir ", " ist ", " aura ",
                               " cherche ", " recrute ", " is ", " are ", " will ", " pour ", " avec ")):
        return False
    return classify_title(text) != "other"


# ---------------------------------------------------------------- names
_PARTICLES = {"de", "da", "di", "du", "del", "della", "der", "den", "van", "von", "le", "la", "el", "al", "bin", "ben", "ibn", "y", "zu", "ter", "dos", "das"}
_NOT_NAME = set("""our the team contact about us privacy policy read more learn join home careers career jobs job apply now sign log in terms
cookie cookies services service products product solutions news blog company get started free trial view all open positions customer
support head office management board leadership meet founders human resources sales marketing engineering design finance operations
success managing director chief officer executive group partner partners street avenue road rue strasse straße monday tuesday
wednesday thursday friday saturday sunday january february march april may june july august september october november december
email phone mail call follow linkedin twitter facebook instagram youtube address location locations imprint impressum legal notice
data protection copyright rights reserved menu search download request demo book pricing features resources events press partner
customers case studies who we are what we do how it works why investors culture values mission vision benefits perks faq help center
technology platform product manager director engineer developer designer analyst consultant specialist coordinator assistant intern
new york san francisco london paris berlin tunis dubai casablanca""".split())
NAME_TOKEN = r"(?:[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ'’]+(?:-[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ'’]+)?|[A-ZÀ-ÖØ-Ý]\.)"
NAME_RE = re.compile(r"^\s*(%s(?:\s+(?:%s|%s)){1,3})\s*$" % (NAME_TOKEN, NAME_TOKEN, "|".join(sorted(_PARTICLES))))
NAME_IN_TEXT = r"(%s(?:\s+(?:%s|%s)){1,3})" % (NAME_TOKEN, NAME_TOKEN, "|".join(sorted(_PARTICLES)))


FIRST_NAMES = set("""
james john robert michael william david richard joseph thomas charles christopher daniel matthew anthony mark donald steven paul andrew
joshua kenneth kevin brian george timothy ronald edward jason jeffrey ryan jacob gary nicholas eric jonathan stephen larry justin scott
brandon benjamin samuel gregory alexander frank patrick raymond jack dennis jerry tyler aaron jose adam nathan henry douglas zachary peter
kyle noah ethan jeremy walter christian keith roger terry austin sean gerald carl harold dylan arthur lawrence jordan jesse bryan billy
bruce gabriel joe logan alan juan albert willie elijah wayne randy vincent mason roy ralph bobby russell bradley philip eugene liam oliver
lucas leo max felix oscar hugo louis jules arthur theo tom nathan enzo mathis clement antoine nicolas julien sebastien guillaume pierre
jean marc laurent olivier philippe francois michel alain christophe frederic stephane thierry vincent yves eric herve bruno didier
mary patricia jennifer linda elizabeth barbara susan jessica sarah karen lisa nancy betty margaret sandra ashley kimberly emily donna
michelle carol amanda dorothy melissa deborah stephanie rebecca sharon laura cynthia kathleen amy angela shirley anna brenda pamela emma
nicole helen samantha katherine christine debra rachel carolyn janet catherine maria heather diane ruth julie olivia joyce virginia
victoria kelly lauren christina joan evelyn judith megan andrea cheryl hannah jacqueline martha gloria teresa ann sara madison frances
kathryn janice jean abigail alice judy sophia grace denise amber doris marilyn danielle beverly isabella theresa diana natalie brittany
charlotte marie kayla alexis lori julia chloe camille lea manon ines jade louise alice lina sarah clara zoe juliette anais pauline
marine lucie mathilde elodie aurelie celine sandrine nathalie isabelle sophie valerie veronique sylvie catherine christine
mohamed mohammed muhammad ahmed ahmad ali omar youssef yousef hassan hussein ibrahim mahmoud mustafa khaled khalid karim kareem said
sami samir walid amine amin mehdi hamza anis aymen ayman bilel bilal nabil rami ramzi slim sofiane sofien tarek tarik wassim yassine
yasine zied hatem hedi hichem hicham jamel kamel lotfi mourad moez mounir nizar radhi riadh ridha rached slah taieb faouzi fethi habib
hamdi imed issam jalel lassaad mehrez mongi naceur noureddine oussama rafik skander wael yosri zouhair ayoub adel aziz badr driss hamid
hakim idriss ismail jawad jalal khalil larbi mouad nouredine rachid redouane saad soufiane tawfik younes zakaria abdel abdelaziz
abdelkader abdellah abdallah abderrahmane abdessamad othmane marwan fares firas malek majd nour ranim
fatma fatima khadija aicha aisha amina amira asma hajer hiba ines imen imane leila leïla lina mariem maryam meriem mouna nadia nawel
nesrine olfa rim rania salma sana sarra sirine sonia souad wafa yasmine yasmina zeineb zainab zahra hanen hela houda ibtissem
jihen kaouther khouloud manel molka nada najwa oumaima rahma rym safa samia sameh sawsen siwar sabrine hind hanane loubna naima
karima latifa malika nabila nora rachida saida samira siham zineb ghita hafsa kenza salima widad
jose juan carlos luis miguel javier francisco antonio manuel pedro alejandro diego pablo sergio jorge alberto fernando rafael raul
andres ricardo enrique eduardo roberto santiago mateo sofia valentina camila lucia martina paula elena carmen ana isabel laura
marco luca giuseppe giovanni francesco andrea matteo alessandro lorenzo stefano paolo roberto giulia chiara francesca alessia
hans peter klaus wolfgang jurgen jörg jens uwe stefan andreas thomas michael frank sven lars jan tobias florian sebastian lukas
anna lena lea hannah mia emma sophie katharina julia laura sabine petra monika ursula claudia susanne andrea nicole stefanie
raj rahul amit vikram arjun rohan sanjay suresh ramesh anil sunil vijay ajay deepak manish priya neha pooja anjali divya kavya
wei li wang zhang liu chen yang huang zhao wu zhou xu sun ma zhu hu guo lin he gao luo
aleksandr alexander dmitri ivan sergei andrei vladimir olga natalia irina svetlana tatiana ekaterina anastasia
kwame kofi chinedu emeka oluwaseun tunde ade ngozi chioma amaka wanjiru achieng otieno kamau njeri
""".split())

JOB_WORDS = set("""advisor adviser technicien technician technicienne infrastructure securite sécurité cybersecurite cybersécurité audit
interne interne groupe group entreprise anonyme agent assistant assistante commercial commerciale comptable ingenieur ingénieur
developpeur développeur developer consultant consultante analyst analyste specialist spécialiste officer supervisor superviseur
operator opérateur operateur chauffeur vendeur vendeuse caissier caissière stagiaire service services client clients recovery debt
sales support center centre office bureau espace space portal connexion login formation training emploi emplois offre offres jobs
recrutement recruteur recruteuse recruitment responsable directeur directrice general général générale manager gestionnaire chef
coordinator coordinateur coordinatrice charge chargé chargée administratif administrative financier financière technique technical
marketing digital projet project produit product qualite qualité logistique logistics achat achats production maintenance
electricien électricien mecanicien mécanicien infirmier infirmière medecin médecin pharmacien pharmacienne juridique legal
ressources humaines human resources partner partenaire senior junior confirmé confirme stage alternance cdi cdd sivp karama
engineering design finance operations accounting accountant engineer designer architect lead head chief executive president
founder fondateur team equipe équipe company société societe sarl suarl gmbh inc ltd llc group holding international tunisie
tunisia morocco maroc algerie france germany""".split())


def clean_name(text, company="", strict=False):
    """A plausible person name or ''. strict=True also requires a known first name (for weak patterns)."""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", str(text)).strip(" ,;:-–|•·")
    t = re.sub(r"^(?:mr|mrs|ms|mme|m|dr|prof|herr|frau|sr|sra)\.?\s+", "", t, flags=re.I)
    if len(t) < 5 or len(t) > 42 or not NAME_RE.match(t):
        return ""
    words = [w.lower().strip(".") for w in t.split()]
    if any(w in _NOT_NAME for w in words) or sum(1 for w in words if w not in _PARTICLES) < 2:
        return ""
    folded = [extract_ascii(w) for w in words]
    if any(w in JOB_WORDS or f in JOB_WORDS for w, f in zip(words, folded)) or classify_title(t) != "other":
        return ""                         # "Directeur Général", "Technicien Infrastructure" are titles, not people
    if strict and not any(f.replace("-", "") in FIRST_NAMES or f.split("-")[0] in FIRST_NAMES for f in folded[:2]):
        return ""
    if company and t.lower() == company.lower():
        return ""
    return t


# ---------------------------------------------------------------- emails
RECRUIT_LOCAL = re.compile(r"^(jobs?|careers?|recruit\w*|recrutement\w*|rh|hr|talents?|people|hiring|apply|applications?|bewerbung\w*|"
                           r"karriere|emplois?|empleos?|candidatures?|cv|staffing|joinus|join|stage|stages|internships?|work|vacanc\w*)"
                           r"([._-].*)?$", re.I)
GENERAL_LOCAL = re.compile(r"^(info|contact|hello|hi|office|admin|support|sales|service|mail|team|press|media|enquiries|inquiries|kontakt|"
                           r"bonjour|accueil|secretariat|reception|welcome|general|marketing|billing|accounts?|finance|legal|privacy|dpo)"
                           r"([._-].*)?$", re.I)


RECRUIT_ANYWHERE = re.compile(r"recrut|recruit|career|carriere|carrière|karriere|bewerb|emploi|empleo|talent|hiring|staffing", re.I)


def email_type(email):
    local = email.split("@")[0].lower()
    if RECRUIT_LOCAL.match(local) or RECRUIT_ANYWHERE.search(local):
        return "recruiting"
    if GENERAL_LOCAL.match(local):
        return "general"
    parts = [p for p in re.split(r"[._-]+", extract_ascii(local)) if p]
    if len(parts) >= 2 and all(p.isalpha() for p in parts[:2]) and (parts[0] in FIRST_NAMES or len(parts[0]) == 1 or parts[1] in FIRST_NAMES):
        return "personal"
    if extract_ascii(local).isalpha() and any(local.startswith(n) and len(local) - len(n) >= 3 for n in FIRST_NAMES if len(n) >= 4):
        return "personal"                 # "sarahjohnson@"
    return "other"


def email_belongs_to(email, name):
    """True if the email's local part clearly refers to this person (jane.doe@, jdoe@, doe@...)."""
    local = re.sub(r"[^a-z]", "", email.split("@")[0].lower())
    parts = [re.sub(r"[^a-z]", "", extract_ascii(p).lower()) for p in name.split() if p.lower() not in _PARTICLES]
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) < 2 or len(local) < 3:
        return False
    first, last = parts[0], parts[-1]
    return last in local and (first in local or local.startswith(first[0]))


def extract_ascii(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


# ---------------------------------------------------------------- people extraction
LABEL_RE = re.compile(
    r"(?P<label>Geschäftsführer(?:in)?|Geschaeftsfuehrer(?:in)?|Managing Directors?|Vertreten durch|Represented by|CEO|Founder|"
    r"Co-?Founder|Gérante?|Directeur de (?:la )?publication|Responsable de (?:la )?publication|Président(?:e)?|Inhaber(?:in)?|"
    r"Ansprechpartner(?:in)?|Ihr(?:e)? Ansprechpartner(?:in)?|Contact person|Contact|Your contact|Votre contact|Personne à contacter|"
    r"Persona de contacto|Contacto|Referente|Recruiter|Recruiting contact|HR contact|Hiring manager)"
    r"\s*(?:\([^)]{0,30}\))?\s*[:\-–]\s*" + NAME_IN_TEXT, re.I | re.U)
NAME_COMMA_TITLE = re.compile(NAME_IN_TEXT + r"\s*(?:,|–|-|\||/|\()\s*(?P<title>[^\n,|()]{3,80})")


def _person(name, title, email="", phone="", linkedin="", source="", url="", from_job=False):
    role = classify_title(title)
    score = ROLE_SCORE[role] + (40 if from_job else 0) + (15 if email else 0) + (5 if phone else 0) + (5 if linkedin else 0)
    return {"name": name, "title": (title or "").strip()[:120], "role": role, "email": email, "phone": phone,
            "linkedin": linkedin, "source": source, "url": url, "score": score}


def people_from_text(text, url="", company="", from_job=False, region=""):
    """Labelled lines and 'Name, Title' patterns in plain text (job descriptions, imprint pages)."""
    out = []
    if not text:
        return out
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        window = " ".join(lines[i:i + 3])[:400]
        for m in LABEL_RE.finditer(line if len(line) < 300 else line[:300]):
            label = m.group("label")
            weak = label.lower() in ("contact", "contacto", "referente", "recruiter")     # generic labels need a real first name
            name = clean_name(m.group(2), company, strict=weak)
            if not name:
                continue
            after = line[m.end():].strip(" ,;:-–|")
            title = after if looks_like_title(after) else (label if classify_title(label) != "other" else "Contact person")
            emails = extract.find_emails(window)
            email = next((e for e in emails if email_belongs_to(e, name)), emails[0] if emails and from_job else "")
            phones = extract.find_phones(window, region)
            out.append(_person(name, title, email, phones[0] if phones and from_job else "", "", "job post" if from_job else "page text", url, from_job))
        for m in NAME_COMMA_TITLE.finditer(line[:300]):
            name = clean_name(m.group(1), company, strict=True)
            title = m.group("title").strip()
            if name and looks_like_title(title):
                emails = extract.find_emails(window)
                email = next((e for e in emails if email_belongs_to(e, name)), "")
                out.append(_person(name, title, email, "", "", "job post" if from_job else "page text", url, from_job))
    return merge(out)


def _jsonld_people(soup, url, company):
    out = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads((tag.string or tag.get_text() or "").strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
                continue
            if not isinstance(n, dict):
                continue
            for k in ("@graph", "founder", "founders", "employee", "employees", "member", "members", "author", "contactPoint", "itemListElement", "item"):
                v = n.get(k)
                if isinstance(v, (list, dict)):
                    stack.extend(v if isinstance(v, list) else [v])
            t = n.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Person" in types:
                name = clean_name(n.get("name") or " ".join(x for x in (n.get("givenName"), n.get("familyName")) if x), company)
                if name:
                    same = n.get("sameAs") or []
                    same = same if isinstance(same, list) else [same]
                    li = next((s for s in same if isinstance(s, str) and "linkedin.com/in/" in s), "")
                    out.append(_person(name, n.get("jobTitle") or "", (n.get("email") or "").replace("mailto:", "").lower(),
                                       n.get("telephone") or "", li, "structured data", url))
    return out


TEAM_URL = re.compile(r"team|equipe|people|leadership|management|about|a-propos|ueber-uns|impressum|imprint|legal|mentions|contact|"
                      r"kontakt|who-we-are|founders|direction|board", re.I)


CHROME_RX = re.compile(r"(^|[\s_-])(nav|navbar|menu|megamenu|footer|header|breadcrumb|cookie|consent|sidebar|dropdown|language|lang-switch|"
                       r"skip-link|social-links|site-map|sitemap)([\s_-]|$)", re.I)


def _card_people(soup, url, company, region):
    """Name + title in the same small block (team pages, contact pages)."""
    team_page = bool(TEAM_URL.search(url or "")) or not url
    out = []
    seen = set()
    for el in soup.find_all(["h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "span", "div", "li", "a", "figcaption", "dt", "td"]):
        own = el.get_text(" ", strip=True)
        if not own or len(own) > 42 or el.find(["div", "p", "li", "ul", "table"]):
            continue
        name = clean_name(own, company, strict=not team_page)
        if not name or name in seen:
            continue
        # The person's own card = the first ancestor that holds anything besides the name.
        box = el
        for _ in range(4):
            if box.parent is None:
                break
            box = box.parent
            if len(box.get_text(" ", strip=True)) > len(own) + 3:
                break
        if len(box.get_text(" ", strip=True)) > len(own) + 250:
            continue                      # that's a page section, not one person's card
        # The title must sit right next to the name (the 3 lines after it or the 2 before it), never elsewhere in the block.
        strings = [t.strip() for t in box.stripped_strings if t.strip()]
        idx = strings.index(own) if own in strings else next((i for i, s in enumerate(strings) if own in s), 0)
        near = strings[idx + 1: idx + 4] + list(reversed(strings[max(0, idx - 2): idx]))
        title = next((t for t in near if looks_like_title(t) and not clean_name(t, company)), "")
        email = ""
        for a in box.select('a[href^="mailto:"]'):
            email = a["href"][7:].split("?")[0].strip().lower()
            break
        phone = ""
        for a in box.select('a[href^="tel:"]'):
            ph = extract.find_phones(a["href"][4:], region)
            phone = ph[0] if ph else ""
            break
        li = ""
        for a in box.select('a[href*="linkedin.com/in/"]'):
            li = a["href"].split("?")[0]
            break
        if not title and not (email and email_belongs_to(email, name)) and not li:
            continue                      # a lonely capitalised phrase is not enough evidence
        # Person evidence: a real first name, a portrait, or personal contact links. Menu items ("Gift Cards",
        # "Brand Assets") have none of these.
        first_ok = any(part in FIRST_NAMES for w in name.split()[:2] for part in extract_ascii(w).lower().split("-"))
        if not (first_ok or box.find("img") or li or (email and email_belongs_to(email, name))):
            continue
        seen.add(name)
        out.append(_person(name, title, email if (not email or email_belongs_to(email, name) or title) else "", phone, li, "team page", url))
    return out


def _mailto_people(soup, url, company):
    out = []
    for a in soup.select('a[href^="mailto:"]'):
        name = clean_name(a.get_text(" ", strip=True), company)
        email = a["href"][7:].split("?")[0].strip().lower()
        if name and "@" in email:
            out.append(_person(name, "", email, "", "", "contact link", url))
    return out


def people_from_html(html, url="", company="", region=""):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg"]):
        if t.name == "script" and "ld+json" in (t.get("type") or ""):
            continue
        t.decompose()
    people = _jsonld_people(soup, url, company)
    full_text = soup.get_text("\n")            # labelled lines (imprint / legal credits) often live in the footer
    # Navigation, headers, footers, cookie banners and breadcrumbs never contain team members.
    for t in soup.find_all(["nav", "header", "footer", "aside", "form", "select", "button"]):
        t.decompose()
    for t in soup.find_all(attrs={"class": CHROME_RX}) + soup.find_all(attrs={"id": CHROME_RX}):
        if t.parent is not None:
            t.decompose()
    people += _card_people(soup, url, company, region) + _mailto_people(soup, url, company)
    people += people_from_text(full_text, url, company, False, region)
    return merge(people)


def merge(people):
    """De-duplicate by name, keeping the richest data and best score."""
    by = {}
    for p in people:
        k = extract_ascii(p["name"]).lower()
        cur = by.get(k)
        if cur is None:
            by[k] = dict(p)
            continue
        for f in ("title", "email", "phone", "linkedin"):
            if not cur.get(f) and p.get(f):
                cur[f] = p[f]
        if p["score"] > cur["score"]:
            cur["score"], cur["role"], cur["source"], cur["url"] = p["score"], p["role"], p["source"], p["url"] or cur["url"]
        if cur.get("title") and classify_title(cur["title"]) != "other":
            cur["role"] = classify_title(cur["title"])
    return sorted(by.values(), key=lambda p: -p["score"])

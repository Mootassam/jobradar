"""Multilingual job-term expansion: one search covers EN / FR / DE / ES / IT / PT / NL / AR.

Each concept lists equivalent job words/titles per language (first word of each language = the preferred search
term in that language). A search word or phrase belonging to a concept expands to every variant, so "accountant"
also matches "comptable", "Buchhalter", "contador", "محاسب"... Matching is accent- and case-insensitive."""
import itertools
import re
import unicodedata

LANGS = ("en", "fr", "de", "es", "it", "pt", "nl", "ar")


def C(en, fr="", de="", es="", it="", pt="", nl="", ar=""):
    """A concept; each argument is a '|'-separated list of variants, preferred first."""
    return {k: [x.strip() for x in v.split("|") if x.strip()] for k, v in zip(LANGS, (en, fr, de, es, it, pt, nl, ar)) if v}


CONCEPTS = [
    # --- finance / admin
    C("accountant|accounting", "comptable|comptabilité", "buchhalter|buchhalterin|buchhaltung", "contador|contadora|contabilidad",
      "contabile|contabilità", "contabilista|contador", "boekhouder", "محاسب|محاسبة"),
    C("auditor|audit", "auditeur|auditrice", "wirtschaftsprüfer|revisor", "auditor|auditora", "revisore", "auditor|auditoria", "auditor",
      "مدقق|مراجع حسابات"),
    C("financial analyst", "analyste financier", "finanzanalyst", "analista financiero", "analista finanziario", "analista financeiro",
      "financieel analist", "محلل مالي"),
    C("financial controller|controller", "contrôleur de gestion|controleur de gestion", "controller|controlling",
      "controller financiero|controlador de gestión", "controller|controllo di gestione", "controller", "controller", "مراقب مالي"),
    C("payroll", "gestionnaire de paie|paie", "lohnbuchhaltung|entgeltabrechnung", "nóminas", "paghe|addetto paghe",
      "folha de pagamento", "salarisadministratie", "الرواتب"),
    C("administrative assistant|office assistant", "assistant administratif|assistante administrative",
      "bürokaufmann|bürokauffrau|sachbearbeiter", "asistente administrativo|auxiliar administrativo", "assistente amministrativo",
      "assistente administrativo", "administratief medewerker", "مساعد إداري"),
    C("secretary", "secrétaire", "sekretär|sekretärin", "secretaria|secretario", "segretaria|segretario", "secretária", "secretaresse",
      "سكرتير|سكرتيرة"),
    C("receptionist", "réceptionniste|hôtesse d'accueil", "empfangsmitarbeiter|rezeptionist", "recepcionista", "receptionist|addetto reception",
      "recepcionista", "receptioniste", "موظف استقبال"),
    C("human resources|hr", "ressources humaines|rh", "personalwesen|personalabteilung", "recursos humanos", "risorse umane",
      "recursos humanos", "personeelszaken|hr", "الموارد البشرية"),
    C("recruiter|talent acquisition", "chargé de recrutement|recruteur|chargée de recrutement", "recruiter|personalvermittler",
      "reclutador|técnico de selección", "recruiter|selezionatore", "recrutador", "recruiter", "مسؤول توظيف"),
    # --- tech
    C("developer|software engineer|programmer|software developer", "développeur|developpeur|ingénieur logiciel",
      "entwickler|softwareentwickler|programmierer", "desarrollador|programador", "sviluppatore|programmatore",
      "desenvolvedor|programador", "ontwikkelaar|softwareontwikkelaar", "مطور|مبرمج|مهندس برمجيات"),
    C("frontend|front-end|front end"),
    C("backend|back-end|back end"),
    C("full stack|fullstack|full-stack"),
    C("data analyst", "analyste de données|data analyst", "datenanalyst", "analista de datos", "analista dati", "analista de dados",
      "data-analist", "محلل بيانات"),
    C("data scientist", "data scientist|scientifique des données", "data scientist|datenwissenschaftler", "científico de datos",
      "data scientist", "cientista de dados", "data scientist", "عالم بيانات"),
    C("data engineer", "ingénieur data|ingénieur données", "data engineer|dateningenieur", "ingeniero de datos", "data engineer",
      "engenheiro de dados", "data engineer", "مهندس بيانات"),
    C("system administrator|sysadmin", "administrateur système|administrateur systèmes", "systemadministrator",
      "administrador de sistemas", "amministratore di sistema", "administrador de sistemas", "systeembeheerder", "مسؤول أنظمة"),
    C("network engineer", "ingénieur réseau", "netzwerkingenieur|netzwerktechniker", "ingeniero de redes", "ingegnere di rete",
      "engenheiro de redes", "netwerkengineer", "مهندس شبكات"),
    C("cybersecurity|cyber security|information security", "cybersécurité|sécurité informatique", "it-sicherheit|cybersicherheit",
      "ciberseguridad", "sicurezza informatica", "segurança da informação|cibersegurança", "cybersecurity", "الأمن السيبراني"),
    C("devops|site reliability|sre"),
    C("it support|helpdesk|help desk", "technicien support|support informatique", "it-support|helpdesk", "soporte técnico",
      "supporto it|helpdesk", "suporte técnico", "servicedesk", "دعم فني"),
    C("qa|quality assurance|tester|qa engineer", "testeur|ingénieur qa", "softwaretester|tester", "tester|analista de pruebas",
      "tester", "testador", "tester", "مختبر برمجيات"),
    C("ux designer|ui designer|product designer", "designer ux|designer ui", "ux designer", "diseñador ux", "ux designer",
      "designer ux", "ux designer", "مصمم واجهات"),
    C("graphic designer", "graphiste|infographiste", "grafikdesigner", "diseñador gráfico", "grafico|graphic designer",
      "designer gráfico", "grafisch ontwerper", "مصمم جرافيك"),
    C("project manager", "chef de projet", "projektleiter|projektmanager", "jefe de proyecto|gerente de proyecto",
      "project manager|capo progetto", "gerente de projeto|gestor de projetos", "projectleider|projectmanager", "مدير مشروع|مدير مشاريع"),
    C("product manager|product owner", "chef de produit|product owner", "produktmanager", "gerente de producto|product manager",
      "product manager", "gerente de produto", "productmanager", "مدير منتج"),
    # --- sales / marketing / customer
    C("sales|salesperson|sales representative|sales executive", "commercial|commerciale|vendeur|vendeuse",
      "vertrieb|verkäufer|verkauf|vertriebsmitarbeiter", "comercial|vendedor|vendedora", "commerciale|venditore",
      "vendedor|comercial", "verkoper|sales", "مبيعات|مندوب مبيعات|بائع"),
    C("account manager", "chargé de clientèle|chargée de clientèle|chargé d'affaires", "kundenbetreuer|account manager",
      "gestor de cuentas|ejecutivo de cuentas", "account manager", "gerente de contas", "accountmanager", "مدير حسابات"),
    C("business developer|business development", "développeur commercial|business developer|développement commercial",
      "geschäftsentwicklung|business developer", "desarrollo de negocio", "sviluppo commerciale|business developer",
      "desenvolvimento de negócios", "business developer", "تطوير الأعمال"),
    C("marketing", "marketing|mercatique", "marketing", "marketing|mercadotecnia", "marketing", "marketing", "marketing", "تسويق"),
    C("digital marketing", "marketing digital|marketing numérique", "online-marketing|digitales marketing", "marketing digital",
      "marketing digitale", "marketing digital", "online marketing", "التسويق الرقمي"),
    C("community manager|social media manager", "community manager|gestionnaire de communauté", "social media manager",
      "community manager", "social media manager", "social media", "social media manager", "مدير مجتمع|مسؤول وسائل التواصل"),
    C("customer service|customer support", "service client|relation client|conseiller client", "kundenservice|kundendienst",
      "atención al cliente", "servizio clienti|assistenza clienti", "atendimento ao cliente", "klantenservice", "خدمة العملاء"),
    C("call center|call centre|contact center", "téléconseiller|centre d'appels|téléconseillère|centre d'appel", "callcenter|call-center",
      "teleoperador|centro de llamadas", "operatore call center", "operador de telemarketing|call center", "callcenter", "مركز اتصال"),
    C("cashier", "caissier|caissière", "kassierer|kassiererin", "cajero|cajera", "cassiere", "operador de caixa", "kassamedewerker",
      "أمين صندوق"),
    # --- engineering / industry
    C("engineer", "ingénieur", "ingenieur", "ingeniero", "ingegnere", "engenheiro", "ingenieur", "مهندس"),
    C("civil engineer", "ingénieur génie civil|ingénieur civil", "bauingenieur", "ingeniero civil", "ingegnere civile",
      "engenheiro civil", "civiel ingenieur", "مهندس مدني"),
    C("mechanical engineer", "ingénieur mécanique", "maschinenbauingenieur", "ingeniero mecánico", "ingegnere meccanico",
      "engenheiro mecânico", "werktuigbouwkundig ingenieur", "مهندس ميكانيكي"),
    C("electrical engineer", "ingénieur électrique|ingénieur électricien", "elektroingenieur", "ingeniero eléctrico",
      "ingegnere elettrico", "engenheiro eletricista", "elektrotechnisch ingenieur", "مهندس كهربائي"),
    C("electrician", "électricien|electricien", "elektriker", "electricista", "elettricista", "eletricista", "elektricien", "كهربائي"),
    C("mechanic", "mécanicien|mecanicien", "mechaniker|kfz-mechatroniker", "mecánico", "meccanico", "mecânico", "monteur", "ميكانيكي"),
    C("technician", "technicien|technicienne", "techniker", "técnico", "tecnico", "técnico", "technicus", "فني|تقني"),
    C("maintenance technician|maintenance", "technicien de maintenance|maintenance", "instandhaltung|servicetechniker",
      "técnico de mantenimiento|mantenimiento", "manutentore|manutenzione", "técnico de manutenção|manutenção", "onderhoudsmonteur",
      "فني صيانة|صيانة"),
    C("welder", "soudeur", "schweißer", "soldador", "saldatore", "soldador", "lasser", "لحام"),
    C("plumber", "plombier", "klempner|installateur", "fontanero", "idraulico", "encanador", "loodgieter", "سباك"),
    C("quality control|quality inspector", "contrôle qualité|contrôleur qualité", "qualitätskontrolle|qualitätsprüfer",
      "control de calidad", "controllo qualità", "controle de qualidade", "kwaliteitscontrole", "مراقبة الجودة"),
    C("production operator|machine operator", "opérateur de production|opérateur machine", "produktionsmitarbeiter|maschinenbediener",
      "operario de producción", "operatore di produzione", "operador de produção", "productiemedewerker", "عامل إنتاج"),
    C("logistics", "logistique", "logistik", "logística", "logistica", "logística", "logistiek", "لوجستيك|لوجستيات"),
    C("warehouse worker|warehouse", "magasinier|préparateur de commandes|entrepôt", "lagerist|lagermitarbeiter",
      "mozo de almacén|almacén", "magazziniere", "armazém|operador de armazém", "magazijnmedewerker", "أمين مخزن|مخزن"),
    C("driver|delivery driver", "chauffeur|livreur", "fahrer|kraftfahrer", "conductor|chofer|repartidor", "autista", "motorista",
      "chauffeur", "سائق"),
    C("procurement|purchasing|buyer", "acheteur|achats", "einkäufer|einkauf", "compras|comprador", "acquisti|buyer",
      "compras|comprador", "inkoper", "مشتريات"),
    C("supply chain", "supply chain|chaîne d'approvisionnement", "lieferkette|supply chain", "cadena de suministro", "supply chain",
      "cadeia de suprimentos", "supply chain", "سلسلة التوريد"),
    # --- health / care / education
    C("nurse|nursing", "infirmier|infirmière", "pflegefachkraft|krankenpfleger|krankenschwester|pflegekraft", "enfermero|enfermera",
      "infermiere", "enfermeiro", "verpleegkundige", "ممرض|ممرضة"),
    C("doctor|physician", "médecin", "arzt|ärztin", "médico", "medico", "médico", "huisarts", "طبيب"),
    C("pharmacist", "pharmacien|pharmacienne", "apotheker", "farmacéutico", "farmacista", "farmacêutico", "apotheker", "صيدلي"),
    C("caregiver|care assistant", "aide-soignant|aide soignant|aide-soignante", "pflegehelfer|betreuer", "cuidador|auxiliar de enfermería",
      "badante|oss", "cuidador", "verzorgende", "مقدم رعاية"),
    C("dentist", "dentiste", "zahnarzt", "dentista", "dentista", "dentista", "tandarts", "طبيب أسنان"),
    C("teacher", "enseignant|professeur", "lehrer|lehrerin", "profesor|profesora|docente", "insegnante|docente", "professor",
      "leraar|docent", "معلم|مدرس|أستاذ"),
    C("trainer", "formateur|formatrice", "trainer|ausbilder", "formador", "formatore", "formador", "trainer", "مدرب"),
    # --- hospitality / trades
    C("cook|chef", "cuisinier|cuisinière|chef", "koch|köchin", "cocinero|cocinera", "cuoco", "cozinheiro", "kok", "طباخ|طاه"),
    C("waiter|waitress", "serveur|serveuse", "kellner|kellnerin", "camarero|camarera", "cameriere", "garçom", "ober", "نادل"),
    C("hotel", "hôtellerie|hôtel", "hotellerie|hotel", "hotelería|hotel", "alberghiero|hotel", "hotelaria", "hotel", "فندق|فندقة"),
    C("cleaner", "agent d'entretien|agent de nettoyage", "reinigungskraft", "limpiador|limpiadora", "addetto pulizie", "faxineiro",
      "schoonmaker", "عامل نظافة"),
    C("security guard", "agent de sécurité", "sicherheitsmitarbeiter", "vigilante de seguridad|vigilante", "guardia di sicurezza",
      "vigilante", "beveiliger", "حارس أمن"),
    # --- management / general
    C("manager", "responsable|manager|gestionnaire", "leiter|leiterin|manager", "gerente|responsable", "responsabile|manager",
      "gerente|gestor", "manager|leidinggevende", "مدير|مسؤول"),
    C("director", "directeur|directrice", "direktor|direktorin", "director|directora", "direttore|direttrice", "diretor|diretora",
      "directeur", "مدير عام"),
    C("assistant", "assistant|assistante", "assistent|assistentin", "asistente", "assistente", "assistente", "assistent", "مساعد"),
    C("consultant", "consultant|consultante", "berater|beraterin", "consultor|consultora", "consulente", "consultor", "adviseur|consultant",
      "مستشار"),
    C("lawyer|legal counsel", "juriste|avocat", "jurist|rechtsanwalt", "abogado", "avvocato", "advogado", "advocaat|jurist",
      "محامي|مستشار قانوني"),
    C("architect", "architecte", "architekt", "arquitecto", "architetto", "arquiteto", "architect", "مهندس معماري"),
    C("translator", "traducteur|traductrice", "übersetzer", "traductor", "traduttore", "tradutor", "vertaler", "مترجم"),
    C("intern|internship", "stagiaire|stage", "praktikant|praktikum", "becario|prácticas", "tirocinante|stage|tirocinio",
      "estagiário|estágio", "stagiair|stage", "متدرب"),
]

# Languages spoken per country - used to pick which translations to send to server-side search APIs.
COUNTRY_LANGS = {
    "FR": ["fr"], "BE": ["fr", "nl"], "CH": ["de", "fr", "it"], "LU": ["fr", "de"], "MA": ["fr", "ar"], "TN": ["fr", "ar"],
    "DZ": ["fr", "ar"], "DE": ["de"], "AT": ["de"], "ES": ["es"], "MX": ["es"], "AR": ["es"], "CO": ["es"], "CL": ["es"],
    "PE": ["es"], "IT": ["it"], "PT": ["pt"], "BR": ["pt"], "NL": ["nl"], "AE": ["ar"], "SA": ["ar"], "QA": ["ar"], "KW": ["ar"],
    "EG": ["ar"], "JO": ["ar"], "LB": ["ar", "fr"], "OM": ["ar"], "BH": ["ar"], "CA": ["fr"], "SN": ["fr"], "CI": ["fr"],
    "CM": ["fr"], "UY": ["es"], "EC": ["es"], "VE": ["es"], "CR": ["es"], "PA": ["es"], "DO": ["es"], "GT": ["es"],
}


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.replace("-", " ")).strip()


_INDEX = {}      # folded variant -> concept index
for _i, _c in enumerate(CONCEPTS):
    for _lang, _vs in _c.items():
        for _v in _vs:
            _INDEX.setdefault(fold(_v), _i)
_MAX_PHRASE = max(len(fold(v).split()) for c in CONCEPTS for vs in c.values() for v in vs)


def concept_of(text):
    return _INDEX.get(fold(text))


def variants(text):
    """All equivalent terms for a word/phrase (itself first), or [text] if unknown."""
    i = concept_of(text)
    if i is None:
        return [text]
    allv = [v for vs in CONCEPTS[i].values() for v in vs]
    return list(dict.fromkeys([text] + [v for v in allv if fold(v) != fold(text)]))


def preferred(text, lang):
    """The preferred word for this concept in a language (or None)."""
    i = concept_of(text)
    if i is None:
        return None
    vs = CONCEPTS[i].get(lang)
    return vs[0] if vs else None


def _segment(words):
    """Split a keyword group into the longest known phrases: ['senior','data','analyst'] -> ['senior', 'data analyst']."""
    out, i = [], 0
    while i < len(words):
        for size in range(min(_MAX_PHRASE, len(words) - i), 0, -1):
            chunk = " ".join(words[i:i + size])
            if size == 1 or fold(chunk) in _INDEX:
                out.append(chunk)
                i += size
                break
    return out


def expand_group(words, limit=60):
    """One AND-group of words -> alternative AND-groups (each a list of words/phrases), original first."""
    options = [variants(p) for p in _segment(words)]
    return [list(c) for c in itertools.islice(itertools.product(*options), limit)]


def expand_groups(groups, limit_per_group=60):
    out, seen = [], set()
    for g in groups:
        for alt in expand_group(g, limit_per_group):
            key = tuple(fold(x) for x in alt)
            if key not in seen:
                seen.add(key)
                out.append(alt)
    return out


def server_terms(groups, country="", max_terms=4):
    """Phrases for APIs with server-side search: each original phrase, then the same phrase in the chosen country's
    languages (TN -> French + Arabic), using each concept's preferred word in that language."""
    terms = [" ".join(g) for g in groups]
    for lang in COUNTRY_LANGS.get((country or "").upper(), []):
        for g in groups:
            parts = _segment(g)
            translated = [preferred(p, lang) or p for p in parts]
            if translated != parts:
                phrase = " ".join(translated)
                if fold(phrase) not in {fold(x) for x in terms}:
                    terms.append(phrase)
    return terms[:max_terms]


def expansion_summary(groups, max_items=14):
    """Human-readable list of extra terms that will also be searched (for the UI)."""
    extra = []
    for g in groups:
        for p in _segment(g):
            for v in variants(p)[1:]:
                if v not in extra:
                    extra.append(v)
    return extra[:max_items]

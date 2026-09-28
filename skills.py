"""Multilingual skill taxonomy - shared by the CV checker, the CV <-> job match score and hiring signals.

Every skill has one canonical name plus its spellings in EN / FR / DE / ES / IT / AR ("Excel" = "MS Excel" =
"tableur Excel"; "Accounting" = "comptabilité" = "Buchhaltung" = "محاسبة"). find() returns canonical names, so a
French CV and an English job post are compared on the same terms. Related skills give partial credit
(PostgreSQL -> SQL, React -> JavaScript), so "knows PostgreSQL" still counts for a job that asks for "SQL"."""
import re

import synonyms

# kind: tech | tool | domain | cert | soft   (soft skills weigh less in the match score)
_RAW = [
    # ---------------------------------------------------------------- programming & software
    ("Python", "python|python3", "tech"), ("Java", "java|java ee|j2ee", "tech"), ("JavaScript", "javascript|js|ecmascript|es6", "tech"),
    ("TypeScript", "typescript", "tech"), ("C++", "c++|cpp", "tech"), ("C#", "c#|csharp|c sharp", "tech"), (".NET", ".net|dotnet|asp.net|.net core", "tech"),
    ("Go", "golang", "tech"), ("Rust", "rust lang|rustlang", "tech"), ("PHP", "php", "tech"), ("Ruby", "ruby", "tech"), ("Kotlin", "kotlin", "tech"),
    ("Swift", "swift|swiftui", "tech"), ("Scala", "scala", "tech"), ("R", "", "tech"), ("MATLAB", "matlab", "tech"), ("C", "", "tech"),
    ("Dart", "dart", "tech"), ("Perl", "perl", "tech"), ("Bash", "bash|shell scripting|shell script", "tech"), ("PowerShell", "powershell", "tech"),
    ("VBA", "vba|excel macros|macros excel|visual basic", "tech"), ("COBOL", "cobol", "tech"), ("ABAP", "abap", "tech"),
    ("SQL", "sql|t-sql|tsql|pl/sql|plsql", "tech"), ("NoSQL", "nosql", "tech"), ("PostgreSQL", "postgresql|postgres", "tech"),
    ("MySQL", "mysql|mariadb", "tech"), ("SQL Server", "sql server|mssql|ms sql", "tech"), ("Oracle DB", "oracle database|oracle db|oracle 1[0-9]c?", "tech"),
    ("MongoDB", "mongodb|mongo db", "tech"), ("Redis", "redis", "tech"), ("Elasticsearch", "elasticsearch|elastic search|elk", "tech"),
    ("SQLite", "sqlite", "tech"), ("Firebase", "firebase|firestore", "tech"), ("GraphQL", "graphql", "tech"), ("REST API", "rest api|restful|rest apis|api rest|web services|web service", "tech"),
    ("HTML", "html|html5", "tech"), ("CSS", "css|css3|sass|scss|less", "tech"), ("Tailwind", "tailwind|tailwindcss", "tech"), ("Bootstrap", "bootstrap", "tech"),
    ("React", "react|react.js|reactjs", "tech"), ("React Native", "react native", "tech"), ("Angular", "angular|angularjs", "tech"), ("Vue.js", "vue|vue.js|vuejs|nuxt", "tech"),
    ("Next.js", "next.js|nextjs", "tech"), ("Svelte", "svelte", "tech"), ("jQuery", "jquery", "tech"), ("Node.js", "node.js|nodejs|node js|express.js|expressjs", "tech"),
    ("NestJS", "nestjs|nest.js", "tech"), ("Django", "django", "tech"), ("Flask", "flask", "tech"), ("FastAPI", "fastapi", "tech"),
    ("Spring", "spring boot|springboot|spring framework|spring mvc", "tech"), ("Laravel", "laravel", "tech"), ("Symfony", "symfony", "tech"),
    ("Ruby on Rails", "ruby on rails|rails", "tech"), ("Flutter", "flutter", "tech"), ("Android", "android|android studio", "tech"), ("iOS", "ios|xcode", "tech"),
    ("Unity", "unity3d|unity 3d|unity engine", "tech"), ("Unreal Engine", "unreal engine|unreal", "tech"), ("WordPress", "wordpress", "tool"),
    ("Shopify", "shopify", "tool"), ("Magento", "magento|adobe commerce", "tool"), ("WooCommerce", "woocommerce", "tool"), ("Drupal", "drupal", "tool"),
    ("Git", "git|github|gitlab|bitbucket", "tool"), ("Docker", "docker|docker compose", "tech"), ("Kubernetes", "kubernetes|k8s|openshift", "tech"),
    ("Terraform", "terraform", "tech"), ("Ansible", "ansible", "tech"), ("Jenkins", "jenkins", "tool"), ("CI/CD", "ci/cd|ci cd|continuous integration|intégration continue|github actions|gitlab ci", "tech"),
    ("Linux", "linux|ubuntu|debian|centos|red hat|redhat|unix", "tech"), ("Windows Server", "windows server|active directory|ad ds", "tech"),
    ("AWS", "aws|amazon web services|ec2|s3|lambda", "tech"), ("Azure", "azure|microsoft azure", "tech"), ("Google Cloud", "gcp|google cloud|bigquery", "tech"),
    ("Microservices", "microservices|micro services|micro-services|microservice", "tech"), ("Testing", "unit testing|unit tests|tests unitaires|jest|pytest|junit|selenium|cypress|test automation|automatisation des tests", "tech"),
    ("QA", "quality assurance|qa testing|software testing|test manuel|manual testing|istqb", "domain"),
    ("Cybersecurity", "cybersecurity|cyber security|information security|sécurité informatique|cybersécurité|pentest|penetration testing|soc analyst|siem|iso 27001", "domain"),
    ("Networking", "network administration|administration réseau|administration réseaux|réseaux informatiques|tcp/ip|lan/wan|vpn|firewall|pare-feu|routage", "domain"),
    ("Cisco", "cisco|ccna|ccnp", "cert"), ("ITIL", "itil", "cert"), ("Help desk", "help desk|helpdesk|service desk|support informatique|it support|support technique", "domain"),
    ("Embedded systems", "embedded|systèmes embarqués|embarqué|firmware|microcontroller|microcontrôleur|stm32|arduino|rtos", "domain"),
    ("PLC", "plc|automate programmable|automates programmables|siemens s7|tia portal|scada", "tech"),
    ("Machine learning", "machine learning|apprentissage automatique|ml engineer|scikit-learn|sklearn|xgboost", "domain"),
    ("Deep learning", "deep learning|apprentissage profond|neural networks|réseaux de neurones|tensorflow|pytorch|keras", "domain"),
    ("NLP", "nlp|natural language processing|traitement du langage", "domain"), ("Computer vision", "computer vision|vision par ordinateur|opencv", "domain"),
    ("Generative AI", "generative ai|genai|llm|llms|large language models|prompt engineering|rag|langchain|openai api|chatgpt api", "domain"),
    ("Data analysis", "data analysis|analyse de données|analyse des données|datenanalyse|análisis de datos|تحليل البيانات", "domain"),
    ("Statistics", "statistics|statistiques|statistik|estadística|الإحصاء", "domain"),
    ("Pandas", "pandas|numpy", "tech"), ("Spark", "spark|pyspark|databricks", "tech"), ("Hadoop", "hadoop|hive", "tech"), ("Kafka", "kafka", "tech"),
    ("Airflow", "airflow", "tech"), ("dbt", "dbt", "tech"), ("Snowflake", "snowflake", "tech"), ("ETL", "etl|elt|data pipelines|pipelines de données|talend|informatica|ssis", "domain"),
    ("Data warehouse", "data warehouse|entrepôt de données|datawarehouse", "domain"),
    ("Power BI", "power bi|powerbi|dax", "tool"), ("Tableau", "tableau software|tableau desktop|tableau", "tool"), ("Looker", "looker|looker studio|google data studio", "tool"),
    ("Qlik", "qlik|qlikview|qlik sense", "tool"), ("Google Analytics", "google analytics|ga4", "tool"),
    # ---------------------------------------------------------------- office & business tools
    ("Excel", "excel|ms excel|microsoft excel|tableur|tableaux croisés dynamiques|pivot tables|vlookup|recherchev", "tool"),
    ("Word", "ms word|microsoft word|word processing|traitement de texte", "tool"), ("PowerPoint", "powerpoint|ms powerpoint", "tool"),
    ("Outlook", "outlook", "tool"), ("MS Office", "ms office|microsoft office|office 365|microsoft 365|pack office|suite office|bureautique", "tool"),
    ("Google Workspace", "google workspace|g suite|gsuite|google sheets|google docs", "tool"), ("Access", "ms access|microsoft access", "tool"),
    ("SAP", "sap|sap fi|sap co|sap mm|sap sd|sap hana|s/4hana|s4hana", "tool"), ("Oracle ERP", "oracle erp|oracle financials|oracle ebs|jd edwards", "tool"),
    ("Odoo", "odoo|openerp", "tool"), ("Sage", "sage|sage 100|sage 1000|ciel compta", "tool"), ("QuickBooks", "quickbooks", "tool"), ("Xero", "xero", "tool"),
    ("ERP", "erp|progiciel de gestion", "tool"), ("CRM", "crm|customer relationship management|gestion de la relation client", "tool"),
    ("Salesforce", "salesforce|sfdc", "tool"), ("HubSpot", "hubspot", "tool"), ("Zoho", "zoho", "tool"), ("Jira", "jira|confluence", "tool"),
    ("Trello", "trello|asana|monday.com|notion", "tool"), ("MS Project", "ms project|microsoft project|primavera", "tool"),
    # ---------------------------------------------------------------- design & media
    ("Figma", "figma", "tool"), ("Adobe XD", "adobe xd", "tool"), ("Sketch", "sketch app", "tool"), ("Photoshop", "photoshop", "tool"),
    ("Illustrator", "illustrator", "tool"), ("InDesign", "indesign", "tool"), ("Premiere Pro", "premiere pro|adobe premiere", "tool"),
    ("After Effects", "after effects", "tool"), ("Final Cut", "final cut", "tool"), ("Canva", "canva", "tool"), ("Blender", "blender", "tool"),
    ("3D modeling", "3d modeling|modélisation 3d|3ds max|maya|cinema 4d|3d modelling", "domain"),
    ("UX design", "ux design|user experience|expérience utilisateur|ux research|ux/ui|ui/ux|ux ui|ui ux|wireframes|wireframing|prototyping|maquettage", "domain"),
    ("UI design", "ui design|user interface design|interface utilisateur", "domain"), ("Graphic design", "graphic design|design graphique|infographie|infographiste|grafikdesign|diseño gráfico", "domain"),
    ("Video editing", "video editing|montage vidéo|videoschnitt|edición de video|montaggio video", "domain"), ("Photography", "photography|photographie", "domain"),
    # ---------------------------------------------------------------- engineering
    ("AutoCAD", "autocad", "tool"), ("SolidWorks", "solidworks", "tool"), ("CATIA", "catia", "tool"), ("Revit", "revit|bim", "tool"),
    ("ArcGIS", "arcgis|qgis|gis|sig", "tool"), ("ANSYS", "ansys|abaqus|finite element|éléments finis", "tool"),
    ("Mechanical engineering", "mechanical engineering|génie mécanique|maschinenbau|ingeniería mecánica", "domain"),
    ("Electrical engineering", "electrical engineering|génie électrique|électrotechnique|elektrotechnik|ingeniería eléctrica", "domain"),
    ("Civil engineering", "civil engineering|génie civil|bauingenieurwesen|ingeniería civil", "domain"),
    ("HVAC", "hvac|climatisation|génie climatique|chauffage ventilation", "domain"), ("Maintenance", "maintenance industrielle|preventive maintenance|maintenance préventive|gmao|cmms", "domain"),
    ("Quality management", "quality management|gestion de la qualité|iso 9001|quality control|contrôle qualité|haccp|qhse|quality assurance engineer", "domain"),
    ("Lean", "lean manufacturing|kaizen|5s", "domain"), ("Six Sigma", "six sigma|6 sigma|dmaic", "cert"),
    ("Production", "production planning|planification de la production|ordonnancement|mrp", "domain"),
    ("Welding", "welding|soudure|soudage|schweißen", "domain"), ("Electrician", "électricien|electrician|câblage|wiring|habilitation électrique", "domain"),
    # ---------------------------------------------------------------- finance & accounting
    ("Accounting", "accounting|comptabilité|comptabilite|buchhaltung|contabilidad|contabilità|محاسبة", "domain"),
    ("Bookkeeping", "bookkeeping|tenue de comptabilité|saisie comptable|tenue des comptes", "domain"),
    ("Financial reporting", "financial reporting|reporting financier|états financiers|financial statements|clôture|month-end close|closing", "domain"),
    ("IFRS", "ifrs|ias|us gaap|gaap|normes comptables", "domain"), ("Audit", "audit|auditing|commissariat aux comptes|revisión|prüfung", "domain"),
    ("Tax", "tax|taxation|fiscalité|fiscal|déclarations fiscales|tva|vat|steuer|impuestos|الضرائب", "domain"),
    ("Payroll", "payroll|paie|gestion de la paie|lohnabrechnung|nómina|الرواتب", "domain"),
    ("Budgeting", "budgeting|contrôle budgétaire|forecasting|budgétisation|budget planning|élaboration du budget", "domain"),
    ("Financial analysis", "financial analysis|analyse financière|finanzanalyse|análisis financiero|financial modeling|modélisation financière", "domain"),
    ("Management control", "contrôle de gestion|management control|controlling|cost accounting|comptabilité analytique", "domain"),
    ("Treasury", "treasury|trésorerie|cash management|gestion de trésorerie", "domain"), ("Banking", "banking|banque|credit analysis|analyse crédit", "domain"),
    ("Accounts payable", "accounts payable|comptabilité fournisseurs|comptes fournisseurs", "domain"),
    ("Accounts receivable", "accounts receivable|comptabilité clients|recouvrement|credit collection", "domain"),
    ("ACCA", "acca|cpa|cma|cfa|dcg|dscg|expert comptable|expert-comptable", "cert"),
    # ---------------------------------------------------------------- marketing & sales
    ("Digital marketing", "digital marketing|marketing digital|marketing numérique|online marketing|webmarketing|web marketing", "domain"),
    ("SEO", "seo|search engine optimization|référencement naturel|référencement", "domain"), ("SEM", "google ads|adwords|référencement payant|ppc|sem/seo|seo/sem", "domain"),
    ("Social media", "social media|réseaux sociaux|community management|community manager|social media marketing|médias sociaux", "domain"),
    ("Meta Ads", "facebook ads|meta ads|instagram ads|meta business", "tool"), ("Email marketing", "email marketing|emailing|mailchimp|newsletter", "domain"),
    ("Content marketing", "content marketing|content creation|création de contenu|copywriting|rédaction web|rédactionnel", "domain"),
    ("Market research", "market research|étude de marché|études de marché|marktforschung", "domain"), ("Branding", "branding|brand management|gestion de marque", "domain"),
    ("B2B sales", "b2b sales|vente b2b|business development|développement commercial|prospection|new business", "domain"),
    ("B2C sales", "b2c|retail sales|vente en magasin|vente au détail", "domain"),
    ("Negotiation", "negotiation|négociation|verhandlung|negociación|التفاوض", "domain"),
    ("Key account management", "key account management|grands comptes|key accounts|account management|gestion de comptes", "domain"),
    ("Customer service", "customer service|service client|relation client|kundenservice|atención al cliente|customer support|support client|خدمة العملاء", "domain"),
    ("Call center", "call center|centre d'appels|centre d'appel|téléconseiller|teleconseiller|telemarketing|télévente|teleoperador", "domain"),
    ("E-commerce", "e-commerce|ecommerce|commerce électronique|online store|marketplace", "domain"),
    ("Product management", "product management|gestion de produit|product owner|product manager", "domain"),
    # ---------------------------------------------------------------- management, HR, admin, logistics
    ("Project management", "project management|gestion de projet|gestion de projets|projektmanagement|gestión de proyectos|إدارة المشاريع", "domain"),
    ("Agile", "agile|agilité|scrum|kanban|sprint", "domain"), ("PMP", "pmp|prince2|capm", "cert"),
    ("Recruitment", "recruitment|recrutement|sourcing|talent acquisition|personalbeschaffung|reclutamiento|التوظيف", "domain"),
    ("HR administration", "hr administration|administration du personnel|gestion administrative du personnel|gestion rh|hris|sirh", "domain"),
    ("Training", "training delivery|formateur|formatrice|trainer|onboarding|learning and development|l&d|ingénierie de formation|animation de formations", "domain"),
    ("Labor law", "labor law|labour law|droit du travail|droit social|arbeitsrecht|derecho laboral", "domain"),
    ("Supply chain", "supply chain|chaîne d'approvisionnement|chaine logistique|lieferkette|cadena de suministro", "domain"),
    ("Logistics", "logistics|logistique|logistik|logística|freight|fret|import export|incoterms|douane|customs clearance|transit", "domain"),
    ("Procurement", "procurement|purchasing|achats|approvisionnement|einkauf|compras|sourcing fournisseurs", "domain"),
    ("Inventory management", "inventory management|gestion des stocks|gestion de stock|lagerverwaltung|warehouse|entrepôt|magasinier|wms", "domain"),
    ("Administration", "office administration|administrative tasks|tâches administratives|gestion administrative|secrétariat|secretarial|classement|archivage", "domain"),
    ("Legal", "affaires juridiques|juriste|contract law|droit des affaires|droit des contrats|corporate law|compliance|conformité réglementaire", "domain"),
    ("Translation", "translation|traduction|übersetzung|traducción|الترجمة|interpreting", "domain"),
    ("Teaching", "teaching|enseignement|pédagogie|lehre|enseñanza|التدريس|tutoring", "domain"),
    # ---------------------------------------------------------------- health, hospitality, trades
    ("Nursing", "nursing|soins infirmiers|infirmier|infirmière|pflege|enfermería|التمريض", "domain"), ("Patient care", "patient care|prise en charge des patients|soins aux patients", "domain"),
    ("First aid", "first aid|premiers secours|sst|psc1|erste hilfe|primeros auxilios", "cert"), ("Pharmacy", "pharmacy|pharmacie|pharmazie|farmacia|صيدلة", "domain"),
    ("Laboratory", "laboratory|laboratoire|laboratorio|مختبر|analyses médicales|lab technician", "domain"), ("Medical coding", "medical coding|codage médical|icd-10", "domain"),
    ("Hospitality", "hospitality|hôtellerie|hotellerie|front office|réception hôtel|gastgewerbe", "domain"), ("Cooking", "cooking|cuisine|chef de partie|pâtisserie|culinary", "domain"),
    ("Driving licence", "driving licence|driving license|driver's license|permis b|permis de conduire|führerschein|carnet de conducir|رخصة سياقة|رخصة قيادة", "cert"),
    ("Forklift", "forklift|chariot élévateur|caces|gabelstapler", "cert"),
    # ---------------------------------------------------------------- soft skills (low weight)
    ("Communication", "communication skills|communication|compétences en communication|kommunikationsfähigkeit|التواصل", "soft"),
    ("Teamwork", "teamwork|team player|esprit d'équipe|travail en équipe|teamfähigkeit|trabajo en equipo|العمل الجماعي", "soft"),
    ("Leadership", "leadership|management d'équipe|team management|encadrement|gestion d'équipe|führung", "soft"),
    ("Problem solving", "problem solving|problem-solving|résolution de problèmes|esprit d'analyse|analytical skills|analytical thinking", "soft"),
    ("Autonomy", "autonomy|autonomie|autonome|self-motivated|self starter|selbstständig", "soft"),
    ("Organization", "organizational skills|sens de l'organisation|rigueur|rigoureux|rigoureuse|attention to detail|sens du détail", "soft"),
    ("Time management", "time management|gestion du temps|gestion des priorités|prioritization", "soft"),
    ("Adaptability", "adaptability|adaptabilité|flexibilité|flexibility", "soft"),
]

# Knowing the key implies (partially) knowing the value - partial credit in the match score.
RELATED = {
    "PostgreSQL": ["SQL"], "MySQL": ["SQL"], "SQL Server": ["SQL"], "Oracle DB": ["SQL"], "SQLite": ["SQL"], "MongoDB": ["NoSQL"],
    "Redis": ["NoSQL"], "React": ["JavaScript"], "Angular": ["TypeScript", "JavaScript"], "Vue.js": ["JavaScript"], "Next.js": ["React", "JavaScript"],
    "Node.js": ["JavaScript"], "NestJS": ["Node.js", "TypeScript"], "TypeScript": ["JavaScript"], "React Native": ["React", "JavaScript"],
    "Django": ["Python"], "Flask": ["Python"], "FastAPI": ["Python"], "Pandas": ["Python", "Data analysis"], "Spark": ["Python"],
    "Spring": ["Java"], "Laravel": ["PHP"], "Symfony": ["PHP"], "Ruby on Rails": ["Ruby"], "Flutter": ["Dart"], ".NET": ["C#"],
    "Kubernetes": ["Docker"], "Power BI": ["Data analysis", "Excel"], "Tableau": ["Data analysis"], "Looker": ["Data analysis"], "Qlik": ["Data analysis"],
    "Machine learning": ["Python", "Statistics"], "Deep learning": ["Machine learning"], "NLP": ["Machine learning"], "Computer vision": ["Machine learning"],
    "Bookkeeping": ["Accounting"], "Financial reporting": ["Accounting"], "IFRS": ["Accounting"], "Accounts payable": ["Accounting"],
    "Accounts receivable": ["Accounting"], "Management control": ["Budgeting", "Accounting"], "Sage": ["Accounting"], "QuickBooks": ["Accounting"],
    "Xero": ["Accounting"], "SAP": ["ERP"], "Odoo": ["ERP"], "Oracle ERP": ["ERP"], "Salesforce": ["CRM"], "HubSpot": ["CRM"], "Zoho": ["CRM"],
    "SEM": ["Digital marketing"], "SEO": ["Digital marketing"], "Social media": ["Digital marketing"], "Meta Ads": ["Digital marketing"],
    "Email marketing": ["Digital marketing"], "Key account management": ["B2B sales"], "Call center": ["Customer service"],
    "Agile": ["Project management"], "PMP": ["Project management"], "MS Project": ["Project management"], "Jira": ["Agile"],
    "Excel": ["MS Office"], "Word": ["MS Office"], "PowerPoint": ["MS Office"], "Outlook": ["MS Office"], "Access": ["MS Office"],
    "Revit": ["AutoCAD"], "SolidWorks": ["Mechanical engineering"], "CATIA": ["Mechanical engineering"], "Cisco": ["Networking"],
    "Six Sigma": ["Lean", "Quality management"], "Illustrator": ["Graphic design"], "Photoshop": ["Graphic design"], "InDesign": ["Graphic design"],
    "Figma": ["UI design", "UX design"], "Premiere Pro": ["Video editing"], "After Effects": ["Video editing"], "Inventory management": ["Logistics"],
    "Procurement": ["Supply chain"], "Logistics": ["Supply chain"], "Recruitment": ["HR administration"], "ACCA": ["Accounting"],
}

SKILLS = {}                       # canonical -> {"kind", "aliases"}
_ALIAS = {}                       # folded alias -> canonical
for _name, _aliases, _kind in _RAW:
    SKILLS[_name] = {"kind": _kind, "aliases": [a for a in _aliases.split("|") if a]}
    for _a in SKILLS[_name]["aliases"]:
        _ALIAS.setdefault(synonyms.fold(_a), _name)

# Short names that are also ordinary words or letters: exact spelling + a list context only.
_EXACT = {"Go": r"Go(?:lang)?", "R": r"R", "C": r"C", "Rust": r"Rust", "Swift": r"Swift", "Sketch": r"Sketch", "Access": r"MS Access|Access",
          "Unity": r"Unity", "Spring": r"Spring(?: Boot)?", "Lean": r"Lean", "Word": r"MS Word|Microsoft Word|Word", "Tableau": r"Tableau(?! de\b| des\b| d')",
          "Sage": r"Sage", "Excel": r"Excel|EXCEL", "Git": r"Git|GitHub|GitLab|git", "Audit": r"[Aa]udit(?:s|ing)?"}
_LIST_CTX = (r"(?:(?<=[,/(|•;:])\s*|(?<=\band )|(?<=\bor )|(?<=\bet )|(?<=\bund )|(?<=\by )|(?<=^)|(?<=\n)|(?<=- )|"
             r"(?<=\bwith )|(?<=\busing )|(?<=\bin )|(?<=\ben )|(?<=\bavec )|(?<=\bmit )|(?<=\bcon ))")
_LIST_ONLY = {"Go", "R", "C", "Rust", "Swift", "Sketch", "Access", "Unity", "Word", "Spring"}
_EXACT_RX = {k: re.compile((_LIST_CTX if k in _LIST_ONLY else r"(?<![\w+#.])") + r"(?:%s)(?![\w+#]|\.(?:js|net)\b)" % v + (
    r"(?=\s*[,/)|•;.]|\s+(?:and|or|et|und|y)\b|\s*$)" if k in _LIST_ONLY else ""), re.M) for k, v in _EXACT.items()}
_ARABIC = re.compile(r"[؀-ۿ]")


def _build():
    latin, arabic = [], []
    for a, name in _ALIAS.items():
        if name in _EXACT and a == synonyms.fold(name):
            continue                      # the bare ambiguous word is handled by the exact-spelling rule
        (arabic if _ARABIC.search(a) else latin).append(a)
    latin.sort(key=len, reverse=True)
    arabic.sort(key=len, reverse=True)
    parts = [re.escape(a).replace(r"\ ", r"[\s/]?") for a in latin]
    lat = re.compile(r"(?<![\w+#])(" + "|".join(parts) + r")(?![\w+#])")
    ara = re.compile("(" + "|".join(re.escape(a) for a in arabic) + ")") if arabic else None
    return lat, ara


_LAT_RX, _AR_RX = _build()
_KEY = {}
for _a, _n in _ALIAS.items():
    _KEY[re.sub(r"[\s\-/]", "", _a)] = _n


def _fold_lines(text):
    """fold() line by line - keeps the line structure (needed to find sentences and section headings)."""
    return "\n".join(synonyms.fold(line) for line in str(text or "").split("\n"))


def _canon(matched):
    return _ALIAS.get(matched) or _KEY.get(re.sub(r"[\s\-/]", "", matched))


def find(text, with_spans=False):
    """Canonical skills mentioned in a text -> list (or {skill: [(start, end), ...]} with spans on the folded text)."""
    raw = str(text or "")[:60000]
    low = _fold_lines(raw)
    found = {}
    for m in _LAT_RX.finditer(low):
        name = _canon(m.group(1))
        if name:
            found.setdefault(name, []).append(m.span())
    if _AR_RX is not None:
        for m in _AR_RX.finditer(low):
            name = _canon(m.group(1))
            if name:
                found.setdefault(name, []).append(m.span())
    for name, rx in _EXACT_RX.items():
        if name in found:
            continue
        m = rx.search(raw)
        if m:
            found.setdefault(name, []).append((-1, -1))
    if with_spans:
        return found
    return list(found)


def kind(name):
    return (SKILLS.get(name) or {}).get("kind", "domain")


def weight(name):
    return 0.35 if kind(name) == "soft" else 1.0


def closure(have):
    """Skills fully known + skills partially implied by them (e.g. PostgreSQL -> SQL at 0.7)."""
    full = set(have)
    partial = {}
    for s in have:
        for r in RELATED.get(s, []):
            if r not in full:
                partial[r] = max(partial.get(r, 0), 0.7)
    # the reverse direction gives a little: knowing SQL helps a PostgreSQL job
    for s, rel in RELATED.items():
        if s not in full and any(r in full for r in rel):
            partial[s] = max(partial.get(s, 0), 0.4)
    return full, partial


# ---------------------------------------------------------------- required vs. nice-to-have (job posts)

_NICE = re.compile(r"nice to have|nice-to-have|a plus|is a plus|would be a plus|bonus|preferred|desirable|ideally|advantage|"
                   r"un plus|serait un plus|est un plus|souhaité|souhaitée|souhaitable|apprécié|appréciée|atout|idéalement|"
                   r"wünschenswert|von vorteil|idealerweise|plus$|deseable|valorable|se valorará|gradito|preferibile|"
                   r"optional|optionnel", re.I)
_REQ = re.compile(r"required|requirement|must have|must-have|mandatory|essential|you have|you bring|you will need|qualifications|"
                  r"requis|requise|exigé|exigée|obligatoire|indispensable|impératif|maîtrise|vous maîtrisez|profil recherché|"
                  r"erforderlich|voraussetzung|zwingend|sie bringen mit|dein profil|ihr profil|requisitos|imprescindible|"
                  r"requisiti|richiesto|necessario", re.I)


def job_skills(text):
    """Skills of a job post split into required / nice-to-have, from the sentence (or section) each one appears in."""
    raw = str(text or "")[:60000]
    low = _fold_lines(raw)
    spans = find(raw, with_spans=True)
    required, nice = [], []
    # nearest section heading before a position (lines that look like a heading)
    heads = [(m.start(), m.group(0)) for m in re.finditer(r"(?m)^[^\n]{2,70}$", low)
             if m.group(0).rstrip().endswith(":") or _NICE.search(m.group(0)) or _REQ.search(m.group(0))]
    for name, poss in spans.items():
        verdict = None
        for (a, b) in poss:
            if a < 0:
                continue
            ls = max(low.rfind("\n", 0, a), low.rfind(". ", 0, a)) + 1
            le_candidates = [x for x in (low.find("\n", b), low.find(". ", b)) if x != -1]
            le = min(le_candidates) if le_candidates else len(low)
            sentence = low[ls:le]
            if _NICE.search(sentence):
                verdict = verdict or "nice"
                continue
            head = next((hd for pos, hd in reversed(heads) if pos < a and a - pos < 2500), "")
            if _NICE.search(head):
                verdict = verdict or "nice"
            else:
                verdict = "required"
                break
        (nice if verdict == "nice" else required).append(name)
    return required, nice


# French names for skills whose canonical name is an English word (tools and languages keep their name).
LABELS_FR = {
    "Accounting": "comptabilité", "Bookkeeping": "tenue de comptabilité", "Financial reporting": "reporting financier", "Audit": "audit",
    "Tax": "fiscalité", "Payroll": "paie", "Budgeting": "contrôle budgétaire", "Financial analysis": "analyse financière",
    "Management control": "contrôle de gestion", "Treasury": "trésorerie", "Banking": "banque", "Accounts payable": "comptabilité fournisseurs",
    "Accounts receivable": "recouvrement clients", "Digital marketing": "marketing digital", "Social media": "réseaux sociaux",
    "Email marketing": "emailing", "Content marketing": "création de contenu", "Market research": "études de marché", "Branding": "gestion de marque",
    "B2B sales": "développement commercial B2B", "B2C sales": "vente", "Negotiation": "négociation", "Key account management": "gestion grands comptes",
    "Customer service": "relation client", "Call center": "centre d'appels", "Product management": "gestion de produit",
    "Project management": "gestion de projet", "Recruitment": "recrutement", "HR administration": "administration du personnel",
    "Training": "formation", "Labor law": "droit du travail", "Supply chain": "supply chain", "Logistics": "logistique", "Procurement": "achats",
    "Inventory management": "gestion des stocks", "Administration": "gestion administrative", "Legal": "juridique", "Translation": "traduction",
    "Teaching": "enseignement", "Nursing": "soins infirmiers", "Patient care": "prise en charge des patients", "Pharmacy": "pharmacie",
    "Laboratory": "laboratoire", "Hospitality": "hôtellerie", "Cooking": "cuisine", "Data analysis": "analyse de données", "Statistics": "statistiques",
    "Machine learning": "machine learning", "Networking": "réseaux informatiques", "Cybersecurity": "cybersécurité", "Help desk": "support informatique",
    "Embedded systems": "systèmes embarqués", "Quality management": "gestion de la qualité", "Maintenance": "maintenance industrielle",
    "Production": "planification de la production", "Mechanical engineering": "génie mécanique", "Electrical engineering": "génie électrique",
    "Civil engineering": "génie civil", "Graphic design": "design graphique", "Video editing": "montage vidéo", "Photography": "photographie",
    "UX design": "UX design", "UI design": "UI design", "3D modeling": "modélisation 3D", "E-commerce": "e-commerce", "Testing": "tests logiciels",
}


def label(name, lang="en"):
    if lang == "fr":
        return LABELS_FR.get(name, name)
    return name[0].lower() + name[1:] if kind(name) == "domain" and not name.isupper() and name not in ("UX design", "UI design") else name

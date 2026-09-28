"""Location intelligence: every country, main regions/states, big cities, and a parser that turns
free text ("Austin, TX", "Remote - EMEA", "München, Deutschland", "Worldwide") into
{country, region, city, remote, worldwide}."""
import re
import unicodedata

# ISO 3166-1 alpha-2 : English name | extra aliases (native names, ISO3, common short forms)
_COUNTRIES = """
AF:Afghanistan|AD:Andorra|AE:United Arab Emirates;UAE;Emirates;Dubai;Abu Dhabi|AG:Antigua and Barbuda|AL:Albania|AM:Armenia|AO:Angola|
AR:Argentina|AT:Austria;Österreich;Oesterreich|AU:Australia|AZ:Azerbaijan|BA:Bosnia and Herzegovina;Bosnia|BB:Barbados|BD:Bangladesh|
BE:Belgium;Belgique;België|BF:Burkina Faso|BG:Bulgaria|BH:Bahrain|BI:Burundi|BJ:Benin|BN:Brunei|BO:Bolivia|BR:Brazil;Brasil|BS:Bahamas|
BT:Bhutan|BW:Botswana|BY:Belarus|BZ:Belize|CA:Canada|CD:Democratic Republic of the Congo;DR Congo;DRC|CF:Central African Republic|
CG:Republic of the Congo;Congo|CH:Switzerland;Schweiz;Suisse;Svizzera|CI:Ivory Coast;Côte d'Ivoire;Cote d'Ivoire|CL:Chile|CM:Cameroon|
CN:China;PRC|CO:Colombia|CR:Costa Rica|CU:Cuba|CV:Cape Verde;Cabo Verde|CY:Cyprus|CZ:Czech Republic;Czechia;Česko|DE:Germany;Deutschland|
DJ:Djibouti|DK:Denmark;Danmark|DM:Dominica|DO:Dominican Republic|DZ:Algeria;Algérie|EC:Ecuador|EE:Estonia|EG:Egypt|ER:Eritrea|
ES:Spain;España|ET:Ethiopia|FI:Finland;Suomi|FJ:Fiji|FR:France|GA:Gabon|GB:United Kingdom;UK;Great Britain;Britain;England;Scotland;Wales;Northern Ireland|
GD:Grenada|GE:Georgia (country);Sakartvelo|GH:Ghana|GM:Gambia|GN:Guinea|GQ:Equatorial Guinea|GR:Greece;Hellas|GT:Guatemala|GW:Guinea-Bissau|
GY:Guyana|HK:Hong Kong|HN:Honduras|HR:Croatia;Hrvatska|HT:Haiti|HU:Hungary;Magyarország|ID:Indonesia|IE:Ireland;Éire|IL:Israel|IN:India|
IQ:Iraq|IR:Iran|IS:Iceland|IT:Italy;Italia|JM:Jamaica|JO:Jordan|JP:Japan|KE:Kenya|KG:Kyrgyzstan|KH:Cambodia|KM:Comoros|KN:Saint Kitts and Nevis|
KR:South Korea;Korea;Republic of Korea|KW:Kuwait|KZ:Kazakhstan|LA:Laos|LB:Lebanon|LC:Saint Lucia|LI:Liechtenstein|LK:Sri Lanka|LR:Liberia|
LS:Lesotho|LT:Lithuania|LU:Luxembourg|LV:Latvia|LY:Libya|MA:Morocco;Maroc;Marruecos|MC:Monaco|MD:Moldova|ME:Montenegro|MG:Madagascar|
MK:North Macedonia;Macedonia|ML:Mali|MM:Myanmar;Burma|MN:Mongolia|MO:Macau;Macao|MR:Mauritania|MT:Malta|MU:Mauritius|MV:Maldives|MW:Malawi|
MX:Mexico;México|MY:Malaysia|MZ:Mozambique|NA:Namibia|NE:Niger|NG:Nigeria|NI:Nicaragua|NL:Netherlands;Nederland;Holland;The Netherlands|
NO:Norway;Norge|NP:Nepal|NZ:New Zealand;Aotearoa|OM:Oman|PA:Panama|PE:Peru;Perú|PG:Papua New Guinea|PH:Philippines|PK:Pakistan|PL:Poland;Polska|
PR:Puerto Rico|PS:Palestine|PT:Portugal|PY:Paraguay|QA:Qatar|RO:Romania;România|RS:Serbia;Srbija|RU:Russia;Russian Federation|RW:Rwanda|
SA:Saudi Arabia;KSA|SB:Solomon Islands|SC:Seychelles|SD:Sudan|SE:Sweden;Sverige|SG:Singapore|SI:Slovenia;Slovenija|SK:Slovakia;Slovensko|
SL:Sierra Leone|SM:San Marino|SN:Senegal;Sénégal|SO:Somalia|SR:Suriname|SS:South Sudan|SV:El Salvador|SY:Syria|SZ:Eswatini;Swaziland|
TD:Chad|TG:Togo|TH:Thailand|TJ:Tajikistan|TL:Timor-Leste;East Timor|TM:Turkmenistan|TN:Tunisia;Tunisie|TR:Turkey;Türkiye;Turkiye|
TT:Trinidad and Tobago|TW:Taiwan|TZ:Tanzania|UA:Ukraine;Україна|UG:Uganda|US:United States;USA;U.S.;US;United States of America;America|
UY:Uruguay|UZ:Uzbekistan|VA:Vatican City|VC:Saint Vincent and the Grenadines|VE:Venezuela|VN:Vietnam;Viet Nam|YE:Yemen|ZA:South Africa|
ZM:Zambia|ZW:Zimbabwe|XK:Kosovo|CW:Curaçao|GI:Gibraltar|IM:Isle of Man|JE:Jersey|GG:Guernsey|RE:Réunion|GP:Guadeloupe|MQ:Martinique
"""

COUNTRIES = {}   # code -> name
ALIASES = {}     # normalized alias -> code


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


for chunk in _COUNTRIES.replace("\n", "").split("|"):
    chunk = chunk.strip()
    if not chunk:
        continue
    code, names = chunk.split(":", 1)
    parts = [p.strip() for p in names.split(";") if p.strip()]
    COUNTRIES[code] = parts[0].replace(" (country)", "")
    for p in parts:
        ALIASES[norm(p.replace(" (country)", ""))] = code

# "US"/"UK" as bare tokens are handled separately (they are also ordinary words).
for amb in ("us", "america", "georgia", "jersey", "guinea", "congo", "korea", "chad", "niger", "jordan"):
    ALIASES.pop(amb, None)

# ISO3 codes commonly seen in job feeds
ISO3 = {"USA": "US", "GBR": "GB", "DEU": "DE", "FRA": "FR", "ESP": "ES", "ITA": "IT", "NLD": "NL", "CAN": "CA",
        "AUS": "AU", "IND": "IN", "BRA": "BR", "MEX": "MX", "IRL": "IE", "POL": "PL", "PRT": "PT", "CHE": "CH",
        "AUT": "AT", "BEL": "BE", "SWE": "SE", "NOR": "NO", "DNK": "DK", "FIN": "FI", "SGP": "SG", "JPN": "JP",
        "ARE": "AE", "SAU": "SA", "MAR": "MA", "EGY": "EG", "ZAF": "ZA", "NGA": "NG", "KEN": "KE", "ISR": "IL",
        "TUR": "TR", "ARG": "AR", "COL": "CO", "CHL": "CL", "PHL": "PH", "IDN": "ID", "MYS": "MY", "NZL": "NZ",
        "ROU": "RO", "CZE": "CZ", "HUN": "HU", "GRC": "GR", "UKR": "UA", "PAK": "PK", "VNM": "VN", "THA": "TH"}

# Regions (states/provinces) - name/abbr -> (country, canonical region name)
_REGIONS = {
    "US": "AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|FL:Florida|GA:Georgia|"
          "HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|"
          "MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|"
          "NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|"
          "OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|"
          "VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia",
    "CA": "AB:Alberta|BC:British Columbia|MB:Manitoba|NB:New Brunswick|NL:Newfoundland and Labrador|NS:Nova Scotia|"
          "NT:Northwest Territories|NU:Nunavut|ON:Ontario|PE:Prince Edward Island|QC:Quebec|SK:Saskatchewan|YT:Yukon",
    "AU": "NSW:New South Wales|VIC:Victoria|QLD:Queensland|WA:Western Australia|SA:South Australia|TAS:Tasmania|"
          "ACT:Australian Capital Territory|NT:Northern Territory",
    "IN": "MH:Maharashtra|KA:Karnataka|TN:Tamil Nadu|TG:Telangana|DL:Delhi|UP:Uttar Pradesh|GJ:Gujarat|WB:West Bengal|"
          "RJ:Rajasthan|KL:Kerala|HR:Haryana|PB:Punjab|AP:Andhra Pradesh|MP:Madhya Pradesh|OR:Odisha|BR:Bihar",
    "DE": "BW:Baden-Württemberg|BY:Bavaria|BE:Berlin|BB:Brandenburg|HB:Bremen|HH:Hamburg|HE:Hesse|NI:Lower Saxony|"
          "MV:Mecklenburg-Vorpommern|NW:North Rhine-Westphalia|RP:Rhineland-Palatinate|SL:Saarland|SN:Saxony|"
          "ST:Saxony-Anhalt|SH:Schleswig-Holstein|TH:Thuringia",
    "GB": "ENG:England|SCT:Scotland|WLS:Wales|NIR:Northern Ireland",
    "BR": "SP:São Paulo|RJ:Rio de Janeiro|MG:Minas Gerais|RS:Rio Grande do Sul|PR:Paraná|SC:Santa Catarina|BA:Bahia|DF:Distrito Federal",
    "ES": "MD:Madrid|CT:Catalonia|AN:Andalusia|VC:Valencia|PV:Basque Country|GA:Galicia",
    "FR": "IDF:Île-de-France|ARA:Auvergne-Rhône-Alpes|PAC:Provence-Alpes-Côte d'Azur|OCC:Occitanie|NAQ:Nouvelle-Aquitaine|HDF:Hauts-de-France|GES:Grand Est|BRE:Bretagne|PDL:Pays de la Loire|NOR:Normandie",
    "MA": "CS:Casablanca-Settat|RSK:Rabat-Salé-Kénitra|TTA:Tanger-Tétouan-Al Hoceïma|MS:Marrakech-Safi|FM:Fès-Meknès|SM:Souss-Massa|OR:Oriental",
    "AE": "DU:Dubai|AZ:Abu Dhabi|SH:Sharjah|AJ:Ajman",
    "MX": "CMX:Mexico City|JAL:Jalisco|NLE:Nuevo León|MEX:State of Mexico",
    "IT": "LOM:Lombardy|LAZ:Lazio|PIE:Piedmont|VEN:Veneto|EMR:Emilia-Romagna|TOS:Tuscany|CAM:Campania",
    "NL": "NH:North Holland|ZH:South Holland|UT:Utrecht|NB:North Brabant|GE:Gelderland",
}
REGIONS = {}         # country -> [(abbr, name)]
REGION_NAMES = {}    # normalized name -> (country, name)
REGION_ABBR = {}     # country -> {ABBR: name}
for cc, spec in _REGIONS.items():
    REGIONS[cc] = []
    REGION_ABBR[cc] = {}
    for part in spec.split("|"):
        abbr, name = part.split(":", 1)
        REGIONS[cc].append((abbr, name))
        REGION_ABBR[cc][abbr] = name
        REGION_NAMES.setdefault(norm(name), (cc, name))
# Ambiguous region names that are also countries/cities elsewhere
for amb in ("georgia", "victoria", "punjab", "madrid", "berlin", "hamburg", "bremen", "dubai", "abu dhabi", "utrecht", "valencia", "galicia"):
    REGION_NAMES.pop(amb, None)

# Big job-market cities -> (country, region)
_CITIES = """
new york:US:New York|nyc:US:New York|brooklyn:US:New York|san francisco:US:California|sf bay area:US:California|bay area:US:California|
los angeles:US:California|san diego:US:California|san jose:US:California|palo alto:US:California|mountain view:US:California|
sunnyvale:US:California|menlo park:US:California|oakland:US:California|seattle:US:Washington|redmond:US:Washington|bellevue:US:Washington|
austin:US:Texas|dallas:US:Texas|houston:US:Texas|chicago:US:Illinois|boston:US:Massachusetts|cambridge ma:US:Massachusetts|
denver:US:Colorado|boulder:US:Colorado|atlanta:US:Georgia|miami:US:Florida|orlando:US:Florida|tampa:US:Florida|phoenix:US:Arizona|
washington dc:US:District of Columbia|philadelphia:US:Pennsylvania|pittsburgh:US:Pennsylvania|portland:US:Oregon|salt lake city:US:Utah|
minneapolis:US:Minnesota|detroit:US:Michigan|nashville:US:Tennessee|raleigh:US:North Carolina|charlotte:US:North Carolina|
las vegas:US:Nevada|columbus:US:Ohio|toronto:CA:Ontario|ottawa:CA:Ontario|vancouver:CA:British Columbia|montreal:CA:Quebec|
calgary:CA:Alberta|london:GB:England|manchester:GB:England|birmingham:GB:England|edinburgh:GB:Scotland|glasgow:GB:Scotland|
bristol:GB:England|leeds:GB:England|cambridge:GB:England|oxford:GB:England|belfast:GB:Northern Ireland|cardiff:GB:Wales|
dublin:IE:|cork:IE:|berlin:DE:Berlin|munich:DE:Bavaria|munchen:DE:Bavaria|hamburg:DE:Hamburg|frankfurt:DE:Hesse|cologne:DE:North Rhine-Westphalia|
koln:DE:North Rhine-Westphalia|dusseldorf:DE:North Rhine-Westphalia|stuttgart:DE:Baden-Württemberg|leipzig:DE:Saxony|paris:FR:Île-de-France|
lyon:FR:Auvergne-Rhône-Alpes|marseille:FR:Provence-Alpes-Côte d'Azur|toulouse:FR:Occitanie|bordeaux:FR:Nouvelle-Aquitaine|lille:FR:Hauts-de-France|
nantes:FR:Pays de la Loire|madrid:ES:Madrid|barcelona:ES:Catalonia|valencia:ES:Valencia|seville:ES:Andalusia|malaga:ES:Andalusia|
lisbon:PT:|lisboa:PT:|porto:PT:|amsterdam:NL:North Holland|rotterdam:NL:South Holland|the hague:NL:South Holland|eindhoven:NL:North Brabant|
brussels:BE:|antwerp:BE:|zurich:CH:|geneva:CH:|basel:CH:|vienna:AT:|wien:AT:|milan:IT:Lombardy|milano:IT:Lombardy|rome:IT:Lazio|roma:IT:Lazio|
turin:IT:Piedmont|stockholm:SE:|gothenburg:SE:|copenhagen:DK:|oslo:NO:|helsinki:FI:|warsaw:PL:|krakow:PL:|wroclaw:PL:|prague:CZ:|
budapest:HU:|bucharest:RO:|athens:GR:|istanbul:TR:|ankara:TR:|kyiv:UA:|tallinn:EE:|riga:LV:|vilnius:LT:|sofia:BG:|belgrade:RS:|zagreb:HR:|
tel aviv:IL:|jerusalem:IL:|dubai:AE:Dubai|abu dhabi:AE:Abu Dhabi|sharjah:AE:Sharjah|riyadh:SA:|jeddah:SA:|doha:QA:|kuwait city:KW:|manama:BH:|
muscat:OM:|amman:JO:|beirut:LB:|cairo:EG:|alexandria:EG:|casablanca:MA:Casablanca-Settat|rabat:MA:Rabat-Salé-Kénitra|marrakech:MA:Marrakech-Safi|
tangier:MA:Tanger-Tétouan-Al Hoceïma|tanger:MA:Tanger-Tétouan-Al Hoceïma|fes:MA:Fès-Meknès|agadir:MA:Souss-Massa|tunis:TN:|algiers:DZ:|
lagos:NG:|abuja:NG:|nairobi:KE:|accra:GH:|johannesburg:ZA:|cape town:ZA:|durban:ZA:|kigali:RW:|addis ababa:ET:|kampala:UG:|dakar:SN:|
bangalore:IN:Karnataka|bengaluru:IN:Karnataka|mumbai:IN:Maharashtra|pune:IN:Maharashtra|hyderabad:IN:Telangana|chennai:IN:Tamil Nadu|
new delhi:IN:Delhi|delhi:IN:Delhi|gurgaon:IN:Haryana|gurugram:IN:Haryana|noida:IN:Uttar Pradesh|kolkata:IN:West Bengal|ahmedabad:IN:Gujarat|
karachi:PK:|lahore:PK:|islamabad:PK:|dhaka:BD:|colombo:LK:|singapore:SG:|kuala lumpur:MY:|jakarta:ID:|bangkok:TH:|manila:PH:|
ho chi minh city:VN:|hanoi:VN:|hong kong:HK:|shanghai:CN:|beijing:CN:|shenzhen:CN:|taipei:TW:|seoul:KR:|tokyo:JP:|osaka:JP:|
sydney:AU:New South Wales|melbourne:AU:Victoria|brisbane:AU:Queensland|perth:AU:Western Australia|adelaide:AU:South Australia|
canberra:AU:Australian Capital Territory|auckland:NZ:|wellington:NZ:|sao paulo:BR:São Paulo|rio de janeiro:BR:Rio de Janeiro|
belo horizonte:BR:Minas Gerais|mexico city:MX:Mexico City|ciudad de mexico:MX:Mexico City|guadalajara:MX:Jalisco|monterrey:MX:Nuevo León|
bogota:CO:|medellin:CO:|buenos aires:AR:|santiago:CL:|lima:PE:|montevideo:UY:|quito:EC:|san jose cr:CR:|panama city:PA:|
sfax:TN:|sousse:TN:|ariana:TN:|ben arous:TN:|nabeul:TN:|monastir:TN:|bizerte:TN:|kairouan:TN:|gabes:TN:|la marsa:TN:|manouba:TN:|
hammamet:TN:|mahdia:TN:|el omrane:TN:|lac 1:TN:|lac 2:TN:|charguia:TN:|
meknes:MA:Fès-Meknès|oujda:MA:Oriental|kenitra:MA:Rabat-Salé-Kénitra|tetouan:MA:Tanger-Tétouan-Al Hoceïma|el jadida:MA:Casablanca-Settat|
mohammedia:MA:Casablanca-Settat|sale:MA:Rabat-Salé-Kénitra|
oran:DZ:|constantine:DZ:|annaba:DZ:|setif:DZ:|blida:DZ:|giza:EG:|new cairo:EG:|sheikh zayed:EG:|6th of october:EG:|mansoura:EG:|
tripoli:LY:|benghazi:LY:|khartoum:SD:|nouakchott:MR:|abidjan:CI:|douala:CM:|yaounde:CM:|kinshasa:CD:|lusaka:ZM:|harare:ZW:|
dar es salaam:TZ:|mombasa:KE:|kisumu:KE:|port harcourt:NG:|ibadan:NG:|kano:NG:|kumasi:GH:|luanda:AO:|maputo:MZ:|gaborone:BW:|
windhoek:NA:|pretoria:ZA:|port louis:MU:|antananarivo:MG:|bamako:ML:|ouagadougou:BF:|lome:TG:|cotonou:BJ:|niamey:NE:|conakry:GN:|
freetown:SL:|monrovia:LR:|banjul:GM:|mogadishu:SO:|djibouti city:DJ:|asmara:ER:|juba:SS:|kigali city:RW:|bujumbura:BI:|lilongwe:MW:|
baghdad:IQ:|erbil:IQ:|basra:IQ:|tehran:IR:|damascus:SY:|sanaa:YE:|ramallah:PS:|gaza:PS:|abu dhabi city:AE:Abu Dhabi|al ain:AE:Abu Dhabi|
dammam:SA:|khobar:SA:|al khobar:SA:|mecca:SA:|medina:SA:|lusail:QA:|salmiya:KW:
"""
CITIES = {}
for chunk in _CITIES.replace("\n", "").split("|"):
    chunk = chunk.strip()
    if chunk:
        name, cc, region = chunk.split(":", 2)
        CITIES[norm(name)] = (cc, region)

REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere", "worldwide", "distributed", "telecommute", "home based", "home office",
                "homeoffice", "teletravail", "remoto", "fernarbeit", "mobiles arbeiten")
WORLDWIDE_WORDS = ("worldwide", "anywhere", "global", "earth", "all countries", "international")
AREA_COUNTRIES = {
    "eu": ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"],
    "europe": None, "emea": None, "latam": None, "apac": None, "americas": None, "north america": ["US", "CA", "MX"],
}


def flag(code):
    if not code or len(code) != 2:
        return "🌍"
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code.upper())


def country_name(code):
    return COUNTRIES.get((code or "").upper(), "")


def resolve_country(text):
    """Country code from a name, alias, ISO2 or ISO3 - or ''."""
    if not text:
        return ""
    t = str(text).strip()
    if len(t) == 2 and t.upper() in COUNTRIES:
        return t.upper()
    if len(t) == 3 and t.upper() in ISO3:
        return ISO3[t.upper()]
    return ALIASES.get(norm(t), "")


def parse_location(text, hint_country=""):
    """Best-effort structured location. Never raises."""
    out = {"country": "", "region": "", "city": "", "remote": False, "worldwide": False, "areas": []}
    if not text:
        if hint_country:
            out["country"] = hint_country
        return out
    raw = str(text)
    n = norm(raw)
    if any(w in n for w in REMOTE_WORDS):
        out["remote"] = True
    if any(w in n for w in WORLDWIDE_WORDS):
        out["worldwide"] = True
    for area in AREA_COUNTRIES:
        if re.search(r"\b%s\b" % re.escape(area), n):
            out["areas"].append(area)

    # 1) country names/aliases anywhere (longest first)
    padded = " %s " % n
    best = None
    for alias, cc in ALIASES.items():
        if len(alias) >= 4 and (" %s " % alias) in padded:
            if best is None or len(alias) > len(best[0]):
                best = (alias, cc)
    if best:
        out["country"] = best[1]

    # 2) comma parts: "City, ST" / "City, Region, Country"
    parts = [p.strip() for p in re.split(r"[,;/|•·\n]| - |\(|\)", raw) if p.strip()]
    for p in parts:
        pu = p.strip().upper()
        if pu in ("US", "USA", "U.S.", "U.S.A.") and not out["country"]:
            out["country"] = "US"
        elif pu in ("UK", "GB") and not out["country"]:
            out["country"] = "GB"
        elif len(pu) == 3 and pu in ISO3 and not out["country"]:
            out["country"] = ISO3[pu]

    for p in parts:
        pn = norm(p)
        pu = p.strip().upper()
        if pn in CITIES:
            cc, region = CITIES[pn]
            if not out["country"] or out["country"] == cc:
                out["country"] = cc
                out["city"] = out["city"] or p.strip()
                out["region"] = out["region"] or region
        if pn in REGION_NAMES:
            cc, region = REGION_NAMES[pn]
            if not out["country"] or out["country"] == cc:
                out["country"] = out["country"] or cc
                out["region"] = out["region"] or region
        if len(pu) in (2, 3) and pu.isalpha():
            for cc in ([out["country"]] if out["country"] else ["US", "CA", "AU"]):
                if cc in REGION_ABBR and pu in REGION_ABBR[cc] and parts.index(p) > 0:
                    out["country"] = cc
                    out["region"] = out["region"] or REGION_ABBR[cc][pu]
                    break

    # 3) no separators ("Sydney NSW", "Remote Berlin"): scan 1-3 word windows for known cities
    if not out["city"]:
        words = n.split()
        for size in (3, 2, 1):
            hit = None
            for i in range(len(words) - size + 1):
                cand = " ".join(words[i:i + size])
                if cand in CITIES and (not out["country"] or CITIES[cand][0] == out["country"]):
                    hit = cand
                    break
            if hit:
                cc, region = CITIES[hit]
                out["country"], out["city"] = cc, hit.title()
                out["region"] = out["region"] or region
                break

    if not out["city"] and parts:
        first = parts[0].strip()
        fn = norm(first)
        if fn and fn not in ALIASES and fn not in REGION_NAMES and not any(w in fn for w in REMOTE_WORDS) and len(first) <= 40:
            out["city"] = first
    if not out["country"] and hint_country:
        out["country"] = hint_country
    if out["worldwide"]:
        out["remote"] = True
    return out


def countries_list():
    return sorted(({"code": c, "name": n, "flag": flag(c)} for c, n in COUNTRIES.items()), key=lambda x: x["name"])


def regions_for(code):
    return [name for _, name in REGIONS.get((code or "").upper(), [])]

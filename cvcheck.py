"""CV reader + ATS checker.

Reads a CV the way applicant-tracking systems do (plain text in file order) and inspects the layout for things
that break them: multiple columns, tables, text boxes, contact details in the page header, scanned pages, broken
font encodings, icons instead of text. Then checks the content (contact, sections, dates, bullets, numbers,
length, personal data) and compares the CV's skills with what the job market asks for the user's target job.

Everything runs locally; the CV never leaves this computer."""
import contextlib
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import date

import extract
import insights
import skills
import store
import synonyms

# ---------------------------------------------------------------- text extraction + layout facts

def _pdf(path):
    import pymupdf
    facts = {"format": "pdf", "pages": 0, "columns": False, "tables": 0, "images": 0, "photo": False, "scanned": False,
             "garbled": 0.0, "fonts": [], "body_size": 0, "icon_fonts": False, "hidden_links": [], "encrypted": False,
             "header_text": "", "text_boxes": 0}
    doc = pymupdf.open(path)
    if doc.needs_pass:
        facts["encrypted"] = True
        return "", facts
    facts["pages"] = doc.page_count
    texts, sizes, fonts = [], {}, {}
    left_chars = right_chars = total_chars = 0
    header_parts = []
    for pno, page in enumerate(doc):
        if pno >= 6:
            break
        W, H = page.rect.width or 595, page.rect.height or 842
        texts.append(page.get_text("text"))                      # content-stream order = what simple parsers read
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") == 1:
                x0, y0, x1, y1 = b["bbox"]
                w, hgt = x1 - x0, y1 - y0
                facts["images"] += 1
                if pno == 0 and y0 < H * 0.4 and 40 < w < 260 and 40 < hgt < 300 and 0.55 < (w / max(hgt, 1)) < 1.5:
                    facts["photo"] = True
                continue
            for line in b.get("lines", []):
                lx0, ly0, lx1, ly1 = line["bbox"]
                t = "".join(s.get("text", "") for s in line.get("spans", []))
                n = len(t.strip())
                if not n:
                    continue
                total_chars += n
                if lx1 <= W * 0.5 and lx0 < W * 0.3:
                    left_chars += n if lx1 - lx0 < W * 0.45 else 0
                if lx0 >= W * 0.3:
                    right_chars += n
                if ly1 < H * 0.07 or ly0 > H * 0.94:
                    header_parts.append(t)
                for s in line.get("spans", []):
                    st = s.get("text", "").strip()
                    if not st:
                        continue
                    sz = round(s.get("size", 0))
                    sizes[sz] = sizes.get(sz, 0) + len(st)
                    fn = (s.get("font") or "").split("+")[-1]
                    fonts[fn] = fonts.get(fn, 0) + len(st)
                    if re.search(r"awesome|icon|symbol|wingding|dingbat|material", fn, re.I):
                        facts["icon_fonts"] = True
        try:
            with contextlib.redirect_stdout(io.StringIO()):          # pymupdf prints an advert for an optional package
                found = page.find_tables().tables
            for t in found:
                if t.row_count >= 2 and t.col_count >= 2:
                    facts["tables"] += 1
        except Exception:
            pass
        try:
            for ln in page.get_links():
                uri = ln.get("uri") or ""
                if uri.startswith("http"):
                    facts["hidden_links"].append(uri)
        except Exception:
            pass
    text = "\n".join(texts)
    if total_chars:
        facts["columns"] = right_chars / total_chars >= 0.25 and left_chars / total_chars >= 0.12
    facts["scanned"] = len(text.strip()) < 150 and facts["images"] > 0
    bad = len(re.findall(r"[\ufffd\ue000-\uf8ff]|\(cid:\d+\)", text))
    facts["garbled"] = round(bad / max(1, len(text)), 4)
    facts["fonts"] = [f for f, _ in sorted(fonts.items(), key=lambda x: -x[1])][:8]
    facts["body_size"] = max(sizes, key=sizes.get) if sizes else 0
    facts["header_text"] = "\n".join(header_parts)[:600]
    return text, facts


def _docx(path):
    import docx
    from docx.oxml.ns import qn
    facts = {"format": "docx", "pages": 0, "columns": False, "tables": 0, "images": 0, "photo": False, "scanned": False,
             "garbled": 0.0, "fonts": [], "body_size": 0, "icon_fonts": False, "hidden_links": [], "encrypted": False,
             "header_text": "", "text_boxes": 0}
    d = docx.Document(path)
    parts = []
    body = d.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            parts.append("".join(t.text or "" for t in child.iter(qn("w:t"))))
        elif child.tag == qn("w:tbl"):
            facts["tables"] += 1
            for row in child.iter(qn("w:tr")):
                cells = ["".join(t.text or "" for t in c.iter(qn("w:t"))) for c in row.iter(qn("w:tc"))]
                parts.append("  ".join(x for x in cells if x))
    boxes = list(body.iter(qn("w:txbxContent")))
    box_text = []
    for bx in boxes:
        box_text.append(" ".join(t.text or "" for t in bx.iter(qn("w:t"))))
    facts["text_boxes"] = len([b for b in box_text if len(b.strip()) > 20])
    header = []
    for sec in d.sections:
        for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            try:
                header += [p.text for p in part.paragraphs if p.text.strip()]
                for t in part.tables:
                    for row in t.rows:
                        header += [c.text for c in row.cells if c.text.strip()]
            except Exception:
                pass
        cols = sec._sectPr.find(qn("w:cols"))
        if cols is not None and int(cols.get(qn("w:num")) or 1) > 1:
            facts["columns"] = True
    facts["header_text"] = "\n".join(header)[:600]
    facts["images"] = len(d.inline_shapes) + len(list(body.iter(qn("wp:anchor"))))
    fonts, sizes = {}, {}
    for p in d.paragraphs:
        for r in p.runs:
            n = len(r.text.strip())
            if not n:
                continue
            if r.font.name:
                fonts[r.font.name] = fonts.get(r.font.name, 0) + n
            if r.font.size:
                sz = round(r.font.size.pt)
                sizes[sz] = sizes.get(sz, 0) + n
    facts["fonts"] = [f for f, _ in sorted(fonts.items(), key=lambda x: -x[1])][:8]
    facts["body_size"] = max(sizes, key=sizes.get) if sizes else 0
    for rel in d.part.rels.values():
        if "hyperlink" in rel.reltype and rel.is_external:
            facts["hidden_links"].append(rel.target_ref)
    text = "\n".join(parts)
    if facts["text_boxes"]:
        text += "\n" + "\n".join(box_text)          # most ATS skip these; we still read them to judge the content
    facts["pages"] = max(1, round(len(text.split()) / 480 + 0.4))
    return text, facts


def _odt(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:(p|h)>|<text:line-break/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html as _h
    text = _h.unescape(text)
    return text, {"format": "odt", "pages": max(1, round(len(text.split()) / 480 + 0.4)), "tables": xml.count("<table:table ")}


def _rtf(path):
    raw = open(path, "rb").read().decode("latin-1", "replace")
    raw = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), raw)
    raw = re.sub(r"\{\\\*[^{}]*\}", "", raw)
    raw = re.sub(r"\\par[d]?\b|\\line\b", "\n", raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", raw)
    return raw, {"format": "rtf", "pages": max(1, round(len(raw.split()) / 480 + 0.4))}


def _txt(path):
    data = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return text, {"format": "txt", "pages": max(1, round(len(text.split()) / 480 + 0.4))}


def _doc(path):
    data = open(path, "rb").read()
    chunks = re.findall(rb"(?:[\x20-\x7e\xa0-\xff]\x00){4,}", data)
    text = "\n".join(c.decode("utf-16le", "ignore") for c in chunks)
    if len(text) < 200:
        text = "\n".join(c.decode("cp1252", "ignore") for c in re.findall(rb"[\x20-\x7e\xa0-\xff]{6,}", data))
    return text, {"format": "doc", "pages": max(1, round(len(text.split()) / 480 + 0.4))}


READERS = {".pdf": _pdf, ".docx": _docx, ".odt": _odt, ".rtf": _rtf, ".txt": _txt, ".doc": _doc}
BASE_FACTS = {"pages": 1, "columns": False, "tables": 0, "images": 0, "photo": False, "scanned": False, "garbled": 0.0, "fonts": [],
              "body_size": 0, "icon_fonts": False, "hidden_links": [], "encrypted": False, "header_text": "", "text_boxes": 0}


def read(path):
    ext = os.path.splitext(path)[1].lower()
    fn = READERS.get(ext)
    if fn is None:
        raise ValueError("Unsupported file type")
    try:
        text, facts = fn(path)
    except Exception as e:
        text, facts = "", {"format": ext.strip("."), "error": str(e)[:200]}
    out = dict(BASE_FACTS)
    out.update(facts)
    text = re.sub(r"[ \t\u00a0]+", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text, out


# ---------------------------------------------------------------- content analysis

SECTIONS = {
    "summary": r"summary|profile|professional summary|about me|objective|career objective|profil|profil professionnel|résumé|a propos|à propos|"
               r"objectif|kurzprofil|profil|zusammenfassung|perfil|resumen|sobre mí|profilo|sommario|نبذة|الملخص|الهدف",
    "experience": r"experience|work experience|professional experience|employment history|work history|career history|expérience|expériences|"
                  r"expérience professionnelle|expériences professionnelles|parcours professionnel|berufserfahrung|berufliche erfahrung|"
                  r"werdegang|experiencia|experiencia laboral|experiencia profesional|esperienza|esperienze professionali|الخبرة|الخبرات|الخبرة المهنية",
    "education": r"education|academic background|qualifications|formation|formations|études|cursus|parcours académique|diplômes|"
                 r"ausbildung|bildung|studium|educación|formación|formación académica|istruzione|formazione|التعليم|المؤهلات|التكوين",
    "skills": r"skills|technical skills|key skills|core competencies|competencies|expertise|compétences|compétences techniques|savoir-faire|"
              r"kenntnisse|fähigkeiten|kompetenzen|habilidades|competencias|conocimientos|competenze|المهارات|الكفاءات",
    "languages": r"languages|language skills|langues|langues étrangères|sprachen|sprachkenntnisse|idiomas|lingue|اللغات",
    "certifications": r"certifications|certificates|certificats|certifications et formations|zertifikate|certificaciones|certificazioni|الشهادات",
    "projects": r"projects|projets|projekte|proyectos|progetti|المشاريع|academic projects|projets académiques",
    "interests": r"interests|hobbies|centres d'intérêt|centres d’intérêt|loisirs|interessen|hobbys|intereses|interessi|الهوايات",
    "volunteering": r"volunteering|volunteer|bénévolat|vie associative|ehrenamt|voluntariado|volontariato|التطوع",
}
_SEC_RX = {k: re.compile(r"^\W{0,4}(?:%s)\W{0,4}$" % v, re.I) for k, v in SECTIONS.items()}

_MONTHS = ("jan|january|janvier|januar|enero|gennaio|feb|february|février|fevrier|februar|febrero|febbraio|mar|march|mars|märz|marzo|"
           "apr|april|avril|abril|aprile|may|mai|mayo|maggio|jun|june|juin|juni|junio|giugno|jul|july|juillet|juli|julio|luglio|"
           "aug|august|août|aout|agosto|sep|sept|september|septembre|septiembre|settembre|oct|october|octobre|oktober|octubre|ottobre|"
           "nov|november|novembre|noviembre|dec|december|décembre|decembre|dezember|diciembre|dicembre")
_NOW = r"present|current|now|today|ongoing|présent|actuel|actuellement|aujourd'hui|aujourd’hui|à ce jour|en cours|heute|aktuell|bis heute|actualidad|presente|oggi|حاليا|الآن"
_D = r"(?:(?:%s)\.?\s+\d{4}|\d{1,2}[/.\-]\d{4}|\d{4})" % _MONTHS
_RANGE = re.compile(r"(%s)\s*(?:-|–|—|to|à|au|bis|a|al|->|→)\s*(%s|%s)" % (_D, _D, _NOW), re.I)
_ACTION = set("""achieved built created delivered designed developed drove grew implemented improved increased launched led managed
negotiated optimized organized reduced resolved saved streamlined supervised trained won coordinated analyzed automated handled
prepared maintained established generated conducted produced monitored reconciled supported planned executed
réalisé réalisée conçu conçue développé développée géré gérée piloté pilotée mis en place encadré encadrée optimisé optimisée
augmenté réduit amélioré améliorée assuré assurée coordonné coordonnée négocié analysé automatisé préparé participé contribué
élaboré suivi rédigé organisé déployé lancé créé animé formé traité
entwickelt geleitet verantwortet gesteigert reduziert optimiert eingeführt betreut koordiniert
desarrollé gestioné lideré implementé coordiné diseñé""".split())
_PERSONAL = [("date of birth", r"date of birth|date de naissance|né le|née le|geburtsdatum|fecha de nacimiento|تاريخ الميلاد|\bdob\b"),
             ("age", r"\b\d{2}\s*(?:ans|years old|jahre alt|años)\b"),
             ("marital status", r"marital status|situation familiale|célibataire|marié|mariée|married|single|ledig|verheiratet|soltero|casado|أعزب|متزوج"),
             ("nationality", r"nationality|nationalité|staatsangehörigkeit|nacionalidad|الجنسية"),
             ("ID number", r"\bcin\b|carte d'identité|passport n|n° de passeport|social security|sécurité sociale")]
_LANG_LEVEL = re.compile(r"native|mother tongue|maternelle|langue maternelle|muttersprache|nativo|madrelingua|اللغة الأم|"
                         r"fluent|bilingual|bilingue|courant|fließend|fluido|c2|c1|b2|b1|a2|a1|advanced|avancé|intermediate|"
                         r"intermédiaire|professional working|notions|basic|débutant|scolaire|conversational", re.I)
_LEVEL_SCORE = [(r"native|mother tongue|maternelle|muttersprache|nativo|madrelingua|اللغة الأم|bilingual|bilingue|c2", 5),
                (r"fluent|courant|fließend|fluido|c1|advanced|avancé|professional working", 4), (r"b2|intermediate|intermédiaire", 3),
                (r"b1|conversational", 2), (r"a2|a1|notions|basic|débutant|scolaire", 1)]
_STOP = {"en": " the and with for of to in on as experience ", "fr": " le la les et des pour avec dans en du expérience ",
         "de": " der die das und mit für von bei erfahrung ", "es": " el la los las y con para de en experiencia ",
         "ar": " في من على إلى مع عن "}
GENERIC_NAMES = re.compile(r"^(cv|resume|résumé|curriculum|curriculum vitae|document|untitled|sans titre|scan|img|image|file|new|nouveau|mon cv|my cv)"
                           r"[\s_\-\d()]*$", re.I)


def _year_month(s):
    s = s.strip().lower()
    if re.fullmatch(_NOW, s, re.I):
        t = date.today()
        return t.year, t.month, True
    y = re.search(r"\d{4}", s)
    if not y:
        return None
    year = int(y.group(0))
    m = re.match(r"(\d{1,2})[/.\-]\d{4}", s)
    if m:
        return year, max(1, min(12, int(m.group(1)))), False
    for i, grp in enumerate(("jan", "feb|fév|fev", "mar|mär", "apr|avr|abr", "may|mai|mag", "jun|juin|giu", "jul|juil|lug", "aug|ao|ago",
                             "sep|set", "oct|okt|ott", "nov", "dec|déc|dez|dic")):
        if re.match(r"(?:%s)" % grp, s):
            return year, i + 1, False
    return year, 0, False


def date_ranges(text):
    out = []
    for m in _RANGE.finditer(text):
        a, b = _year_month(m.group(1)), _year_month(m.group(2))
        if not a or not b:
            continue
        y0, m0, _ = a
        y1, m1, now = b
        if not (1960 <= y0 <= date.today().year + 1 and 1960 <= y1 <= date.today().year + 1):
            continue
        start = y0 * 12 + (m0 or 1) - 1
        end = y1 * 12 + (m1 or 12) - 1
        if end < start or end - start > 45 * 12:
            continue
        style = "month-name" if re.match(r"[a-zé]", m.group(1).strip(), re.I) else ("mm/yyyy" if re.match(r"\d{1,2}[/.\-]", m.group(1).strip()) else "yyyy")
        out.append({"start": start, "end": end, "now": now, "style": style, "text": m.group(0), "pos": m.start()})
    return out


def total_months(ranges):
    iv = sorted((r["start"], r["end"]) for r in ranges)
    total, cur = 0, None
    for s, e in iv:
        if cur is None:
            cur = [s, e]
        elif s <= cur[1] + 1:
            cur[1] = max(cur[1], e)
        else:
            total += cur[1] - cur[0] + 1
            cur = [s, e]
    if cur:
        total += cur[1] - cur[0] + 1
    return total


def sections(text):
    """[(name, line_index)] for section headings found in order."""
    found = []
    for i, line in enumerate(text.split("\n")):
        t = line.strip().strip(":").strip()
        if not t or len(t) > 45:
            continue
        for name, rx in _SEC_RX.items():
            if rx.match(t) and name not in [f[0] for f in found]:
                found.append((name, i))
                break
    return found


def section_text(text, found, name):
    lines = text.split("\n")
    for k, (n, idx) in enumerate(found):
        if n == name:
            end = found[k + 1][1] if k + 1 < len(found) else len(lines)
            return "\n".join(lines[idx + 1:end])
    return ""


def detect_language(text):
    low = " " + synonyms.fold(text[:6000]) + " "
    scores = {}
    for lang, words in _STOP.items():
        scores[lang] = sum(low.count(" %s " % w) for w in words.split())
    best = max(scores, key=scores.get)
    return best if scores[best] >= 5 else ""


def languages_spoken(text, lang_section=""):
    src = lang_section or text
    out = {}
    for name, rx in insights._LANG_RX.items():
        for m in rx.finditer(src):
            ctx = src[max(0, m.start() - 10): m.end() + 60]
            if not lang_section and not _LANG_LEVEL.search(ctx):
                continue
            lvl = 3
            for pat, sc in _LEVEL_SCORE:
                if re.search(pat, ctx, re.I):
                    lvl = sc
                    break
            out[name] = max(out.get(name, 0), lvl)
            break
    return out


def education_level(text):
    order = {"PhD / Doctorate": 5, "Master's": 4, "Bachelor's": 3, "Associate / BTS": 2, "High school": 1}
    best = 0
    for k, rx in insights._EDU_RX:
        if rx.search(text):
            best = max(best, order[k])
    return best


_FAMILY_RX = None


def job_families(text):
    """Job families (synonym concepts) the CV mentions - e.g. accountant, developer - in any language."""
    global _FAMILY_RX
    if _FAMILY_RX is None:
        pats = sorted(synonyms._INDEX.keys(), key=len, reverse=True)
        pats = [p for p in pats if len(p) >= 3]
        _FAMILY_RX = re.compile(r"(?<![\w])(" + "|".join(re.escape(p) for p in pats) + r")(?![\w])")
    low = synonyms.fold(text)
    fams = []
    for m in _FAMILY_RX.finditer(low):
        i = synonyms._INDEX.get(m.group(1))
        if i is not None and i not in fams:
            fams.append(i)
    return fams


def analyze(text, facts, file_name="", size=0, profile=None):
    """Everything we know about a CV: profile data for matching + ATS facts."""
    profile = profile or {}
    found = sections(text)
    exp_text = section_text(text, found, "experience")
    edu_text = section_text(text, found, "education")
    ranges = date_ranges(exp_text or text)
    if not exp_text and edu_text:
        edu_ranges = {r["text"] for r in date_ranges(edu_text)}
        ranges = [r for r in ranges if r["text"] not in edu_ranges]
    months = total_months(ranges)
    top = text[: max(400, len(text) // 4)]
    emails = [e.lower() for e in _EMAIL_RX.findall(text)]
    region = geo_code(profile.get("country", ""))
    phones = cv_phones(text, region)
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    bullets = [l for l in lines if re.match(r"^[•\-\*▪►✓●◦–·]\s*\w|^\d+[.)]\s+\w", l)]
    bullet_bodies = [re.sub(r"^[•\-\*▪►✓●◦–·\d.)]+\s*", "", b) for b in bullets]
    action = [b for b in bullet_bodies if synonyms.fold(b.split(" ")[0] if b else "").strip(",.") in {synonyms.fold(w) for w in _ACTION}]
    numbers = [b for b in bullet_bodies if re.search(r"\d+\s*%|\d{2,}|[€$£]\s?\d|\d\s?(k|m|dt|tnd|eur|usd)\b", b, re.I)]
    words = len(text.split())
    have = skills.find(text)
    extra = [s.strip() for s in str(profile.get("skills_extra") or "").split(",") if s.strip()]
    for s in extra:
        canon = skills._ALIAS.get(synonyms.fold(s)) or (s if s in skills.SKILLS else None)
        if canon and canon not in have:
            have.append(canon)
    langs = languages_spoken(text, section_text(text, found, "languages"))
    return {
        "words": words, "pages": facts.get("pages") or 1, "language": detect_language(text),
        "sections": [f[0] for f in found],
        "email": emails[0] if emails else "", "email_top": bool(emails and emails[0] in top.lower()),
        "phone": phones[0] if phones else "", "linkedin": bool(re.search(r"linkedin\.com/in/[\w\-%]+", text, re.I)),
        "linkedin_link_only": (not re.search(r"linkedin\.com/in/", text, re.I)) and any("linkedin.com/in/" in u for u in facts.get("hidden_links") or []),
        "city": bool(profile.get("city") and synonyms.fold(profile["city"]) in synonyms.fold(text)),
        "ranges": len(ranges), "date_styles": sorted({r["style"] for r in ranges}), "months": months,
        "reverse_chrono": _is_reverse(ranges), "bullets": len(bullets), "action_bullets": len(action), "number_bullets": len(numbers),
        "personal": [label for label, rx in _PERSONAL if re.search(rx, text, re.I)],
        "skills": have, "languages": langs, "education": education_level(edu_text or text),
        "families": job_families(" ".join(lines[:12]) + "\n" + exp_text[:6000] + "\n" + str(profile.get("current_title") or "")
                                 + "\n" + str(profile.get("target_titles") or "")),
        "contact_in_header": bool(re.search(r"@|\+?\d[\d\s().-]{7,}", facts.get("header_text") or "")) and not (emails and emails[0] in
                                                                                                                   (text[:1500].lower())),
        "file_generic": bool(GENERIC_NAMES.match(os.path.splitext(file_name or "")[0].strip())), "size": size,
    }


_EMAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_CANDIDATE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s.\-]?)?\(?\d{1,4}\)?(?:[\s.\-]?\d{2,4}){2,5}")
_PHONE_LABEL = re.compile(r"tel|tél|phone|mobile|gsm|portable|handy|telefon|teléfono|cell|whatsapp|☎|📞|هاتف|جوال", re.I)
_YEARS = re.compile(r"(?:19|20)\d{2}\s*[-–/]\s*(?:19|20)\d{2}|\d{1,2}/(?:19|20)\d{2}")


def cv_phones(text, region=""):
    """Phone numbers in a CV: international format, or on a line labelled phone/tel/mobile. Date ranges never count."""
    out = []
    for line in text.split("\n")[:80]:
        for m in _PHONE_CANDIDATE.finditer(line):
            cand = m.group(0).strip()
            digits = re.sub(r"\D", "", cand)
            if len(digits) < 8 or len(digits) > 15 or _YEARS.search(cand):
                continue
            if not (cand.startswith(("+", "00")) or _PHONE_LABEL.search(line) or re.fullmatch(r"0\d([\s.]?\d{2}){4}|\d{2}[\s.]\d{3}[\s.]\d{3}", cand)):
                continue
            for ph in extract.find_phones(cand, region):
                if ph not in out:
                    out.append(ph)
    return out


def _is_reverse(ranges):
    ends = [r["end"] for r in sorted(ranges, key=lambda r: r["pos"])]
    if len(ends) < 3:
        return True
    ok = sum(1 for a, b in zip(ends, ends[1:]) if a >= b)
    return ok >= (len(ends) - 1) * 0.6


def geo_code(country):
    import geo
    return geo.resolve_country(country or "") or ""


# ---------------------------------------------------------------- market keywords (what jobs for the target role ask)

def market_skills(targets, country="", limit_jobs=400):
    """Most requested skills in stored jobs for the target role(s): [(skill, share_of_jobs)]."""
    targets = [t.strip() for t in str(targets or "").split(",") if t.strip()]
    if not targets:
        return [], 0
    fq = store.fts_query(", ".join(targets))
    if not fq:
        return [], 0
    args = [fq]
    where = ""
    if country:
        where = "AND (j.country = ? OR j.worldwide = 1)"
        args.append(country)
    rows = store.q("SELECT j.title, j.description FROM jobs j JOIN jobs_fts ON jobs_fts.rowid = j.id WHERE jobs_fts MATCH ? %s "
                   "ORDER BY j.first_seen DESC LIMIT %d" % (where, limit_jobs), args)
    if len(rows) < 10 and country:
        rows = store.q("SELECT j.title, j.description FROM jobs j JOIN jobs_fts ON jobs_fts.rowid = j.id WHERE jobs_fts MATCH ? "
                       "ORDER BY j.first_seen DESC LIMIT %d" % limit_jobs, [fq])
    counts = {}
    for r in rows:
        for s in set(skills.find((r["title"] or "") + "\n" + (r["description"] or "")[:15000])):
            counts[s] = counts.get(s, 0) + 1
    n = len(rows)
    ranked = sorted(((s, c / n) for s, c in counts.items() if n and c / n >= 0.06 and skills.kind(s) != "soft"), key=lambda x: -x[1])
    return ranked[:30], n


# ---------------------------------------------------------------- the checks

def _chk(out, cid, cat, status, title, detail, fix, got, mx):
    out.append({"id": cid, "cat": cat, "status": status, "title": title, "detail": detail, "fix": fix, "points": round(got, 1), "max": mx})


def check(text, facts, a, market=None, market_n=0):
    """ATS + recruiter checks -> (score 0-100, checks, categories)."""
    C = []
    fmt = facts.get("format")
    readable = len(text) >= 300 and not facts.get("encrypted") and not facts.get("scanned") and facts.get("garbled", 0) < 0.03
    # --- 1. can robots read it (35)
    if facts.get("encrypted"):
        _chk(C, "encrypted", "read", "fail", "The PDF is password-protected", "ATS software can't open protected files - your CV is rejected unread.",
             "Save the PDF again without a password.", 0, 12)
    elif facts.get("scanned") or len(text) < 300:
        _chk(C, "text", "read", "fail", "No readable text", "This file looks like a scan or an image: robots see an empty page.",
             "Export your CV from Word / Google Docs / Canva as a text PDF (not a photo or scan).", 0, 12)
    else:
        _chk(C, "text", "read", "ok", "Text is readable", "Robots can extract %d words." % a["words"], "", 12, 12)
    if facts.get("garbled", 0) >= 0.01:
        _chk(C, "garbled", "read", "fail" if facts["garbled"] >= 0.03 else "warn", "Some characters come out broken",
             "%.1f%% of the characters can't be decoded (special font encoding)." % (facts["garbled"] * 100),
             "Use a standard font (Arial, Calibri, Garamond, Helvetica) and export again.", 0 if facts["garbled"] >= 0.03 else 2, 5)
    else:
        _chk(C, "garbled", "read", "ok", "Fonts decode cleanly", "No broken characters found.", "", 5, 5)
    if facts.get("columns"):
        _chk(C, "columns", "read", "warn", "Two-column layout", "Many ATS read across both columns line by line, mixing your sidebar into your experience.",
             "Use one column. Put skills and languages under your experience instead of in a sidebar.", 1, 6)
    else:
        _chk(C, "columns", "read", "ok", "Single-column layout", "Your content is read in the right order.", "", 6, 6)
    if facts.get("tables"):
        _chk(C, "tables", "read", "warn", "%d table(s) used for layout" % facts["tables"], "Tables are often flattened or skipped by ATS parsers.",
             "Replace tables with plain lines (\"Company - Title - 2021-2023\").", 1.5, 4)
    else:
        _chk(C, "tables", "read", "ok", "No layout tables", "", "", 4, 4)
    if facts.get("text_boxes"):
        _chk(C, "textboxes", "read", "warn", "%d text box(es)" % facts["text_boxes"], "Text inside text boxes / shapes is invisible to most ATS.",
             "Move that text into the normal page body.", 0.5, 3)
    else:
        _chk(C, "textboxes", "read", "ok", "No text boxes", "", "", 3, 3)
    if a.get("contact_in_header"):
        _chk(C, "header", "read", "warn", "Contact details are in the page header", "Many ATS ignore headers and footers - your email/phone may be lost.",
             "Put your name, email and phone in the body at the top of page 1.", 0, 3)
    else:
        _chk(C, "header", "read", "ok", "Contact details in the body", "", "", 3, 3)
    fmt_pts = {"pdf": 2, "docx": 2, "odt": 1, "rtf": 1, "txt": 1, "doc": 0}.get(fmt, 0)
    _chk(C, "format", "read", "ok" if fmt_pts == 2 else "warn", "File format: %s" % (fmt or "?").upper(),
         "PDF and DOCX are the safest formats for application portals." if fmt_pts == 2 else "Some portals reject or misread this format.",
         "" if fmt_pts == 2 else "Save as PDF (or DOCX if the job asks for Word).", fmt_pts, 2)
    # --- 2. contact (10)
    _chk(C, "email", "contact", "ok" if a["email"] else "fail", "Email address" if a["email"] else "No email found",
         a["email"] or "Recruiters and robots need an email to contact you.", "" if a["email"] else "Add a professional email at the top.", 4 if a["email"] else 0, 4)
    _chk(C, "phone", "contact", "ok" if a["phone"] else "warn", "Phone number" if a["phone"] else "No phone number found",
         a["phone"] or "Write it with the country code (+216 …) so it works abroad.", "" if a["phone"] else "Add your phone with country code.",
         3 if a["phone"] else 0, 3)
    if a["linkedin"]:
        _chk(C, "linkedin", "contact", "ok", "LinkedIn URL", "", "", 2, 2)
    elif a["linkedin_link_only"]:
        _chk(C, "linkedin", "contact", "warn", "LinkedIn is only a clickable icon", "The robot sees the word/icon but not the address.",
             "Write the full address: linkedin.com/in/your-name", 1, 2)
    else:
        _chk(C, "linkedin", "contact", "warn", "No LinkedIn profile", "Most recruiters check LinkedIn.", "Add linkedin.com/in/your-name", 0, 2)
    _chk(C, "location", "contact", "ok" if a["city"] else "info", "City / country" if a["city"] else "City not found",
         "Recruiters filter by location." if not a["city"] else "", "" if a["city"] else "Add your city and country next to your contact details.",
         1 if a["city"] else 0, 1)
    # --- 3. structure (20)
    secs = a["sections"]
    for sid, label, mx, fix in (("experience", "Experience section", 6, "Add a clear heading: \"Professional experience\" / \"Expérience professionnelle\"."),
                                ("education", "Education section", 5, "Add a heading: \"Education\" / \"Formation\"."),
                                ("skills", "Skills section", 5, "Add a \"Skills\" / \"Compétences\" section listing tools and know-how."),
                                ("summary", "Summary / profile", 2, "Add 2-3 lines under your name: who you are, your field, what you bring."),
                                ("languages", "Languages section", 2, "List your languages with a level (Arabic - native, French - C1, English - B2).")):
        ok = sid in secs
        if sid == "summary" and not ok:
            ok = False
        _chk(C, "sec_" + sid, "structure", "ok" if ok else ("fail" if sid in ("experience", "education") else "warn"),
             label + (" found" if ok else " not found"), "" if ok else "Robots sort your CV by standard section names.", "" if ok else fix,
             mx if ok else 0, mx)
    # --- 4. content (15)
    if a["ranges"]:
        styles = a["date_styles"]
        _chk(C, "dates", "content", "ok" if len(styles) == 1 else "warn", "%d date range(s) found" % a["ranges"],
             "Experience counted: about %s." % _fmt_months(a["months"]) + ("" if len(styles) == 1 else " Mixed date formats: " + ", ".join(styles) + "."),
             "" if len(styles) == 1 else "Use one date format everywhere, e.g. 03/2021 - 06/2023.", 4 if len(styles) == 1 else 2.5, 4)
        _chk(C, "order", "content", "ok" if a["reverse_chrono"] else "warn", "Most recent job first" if a["reverse_chrono"] else "Jobs not in reverse order",
             "", "" if a["reverse_chrono"] else "List your most recent job first.", 1 if a["reverse_chrono"] else 0, 1)
    else:
        _chk(C, "dates", "content", "warn", "No date ranges found", "Robots compute your years of experience from dates like 03/2021 - 06/2023.",
             "Add start and end dates to each job.", 0, 5)
    b = a["bullets"]
    _chk(C, "bullets", "content", "ok" if b >= 6 else "warn", "%d bullet point(s)" % b, "Bullets make achievements easy to scan.",
         "" if b >= 6 else "Describe each job with 3-5 bullet points.", 3 if b >= 6 else (1.5 if b >= 2 else 0), 3)
    if b:
        share = a["action_bullets"] / b
        _chk(C, "verbs", "content", "ok" if share >= 0.4 else "warn", "%d%% of bullets start with an action verb" % round(share * 100),
             "", "" if share >= 0.4 else "Start bullets with a verb: Managed, Built, Reduced… / Géré, Développé, Réduit…", 2 if share >= 0.4 else 1 if share >= 0.15 else 0, 2)
        _chk(C, "numbers", "content", "ok" if a["number_bullets"] >= 2 else "warn", "%d achievement(s) with numbers" % a["number_bullets"],
             "Numbers prove impact (\"reduced closing time by 30%\").", "" if a["number_bullets"] >= 2 else "Add 2-3 results with numbers, %, amounts or volumes.",
             2 if a["number_bullets"] >= 2 else 1 if a["number_bullets"] else 0, 2)
    pages, words = a["pages"], a["words"]
    good_len = 250 <= words <= 1100 and pages <= 2
    _chk(C, "length", "content", "ok" if good_len else "warn", "%d page(s), %d words" % (pages, words),
         "" if good_len else ("Too short to show your experience." if words < 250 else "Recruiters spend seconds per CV - keep it to 1-2 pages."),
         "" if good_len else ("Add details: tasks, tools, results." if words < 250 else "Cut older or less relevant details."), 3 if good_len else 1, 3)
    if a["personal"]:
        _chk(C, "personal", "content", "info", "Personal details: " + ", ".join(a["personal"]),
             "Usual in Tunisia/France, but removed in the US, UK, Canada and many international companies (anti-discrimination).",
             "Keep a version without them for international applications.", 0, 0)
    if facts.get("photo"):
        _chk(C, "photo", "content", "info", "Photo on the CV", "Fine for France/Tunisia; avoid for the US, UK and Canada.", "", 0, 0)
    if a.get("file_generic"):
        _chk(C, "filename", "content", "warn", "Generic file name", "A file called \"CV.pdf\" gets lost among hundreds.", "Rename it: Firstname_Lastname_CV.pdf", 0, 0)
    if a.get("size", 0) > 2 * 1024 * 1024:
        _chk(C, "size", "content", "warn", "Large file (%.1f MB)" % (a["size"] / 1048576), "Some portals refuse files over 2 MB.",
             "Compress the images or export with \"smallest file size\".", 0, 0)
    if facts.get("body_size") and facts["body_size"] < 9:
        _chk(C, "fontsize", "content", "warn", "Small text (%dpt)" % facts["body_size"], "Hard to read for humans and OCR.", "Use 10-12pt for body text.", 0, 0)
    # --- 5. keywords vs market (20)
    if market and market_n >= 10:
        full, partial = skills.closure(a["skills"])
        tot = sum(sh for _, sh in market)
        got = sum(sh * (1 if s in full else partial.get(s, 0)) for s, sh in market)
        cov = got / tot if tot else 0
        missing = [s for s, _ in market if s not in full and partial.get(s, 0) < 0.7][:10]
        _chk(C, "keywords", "keywords", "ok" if cov >= 0.6 else "warn" if cov >= 0.3 else "fail",
             "Covers %d%% of the skills employers ask for" % round(cov * 100),
             "Based on %d jobs for your target role. Missing: %s" % (market_n, ", ".join(missing) if missing else "nothing important"),
             "" if not missing else "Add the ones you really have (skills section + in your job bullets).", round(20 * min(1, cov / 0.8), 1), 20)
    else:
        _chk(C, "keywords", "keywords", "info", "Market keywords not checked yet",
             "Set your target job title and run a search for it - JobRadar then compares your CV with what those employers ask.",
             "", 0, 0)
    score_max = sum(c["max"] for c in C)
    score = round(100 * sum(c["points"] for c in C) / score_max) if score_max else 0
    if not readable:
        score = min(score, 25)
    elif facts.get("columns") or facts.get("text_boxes") or a.get("contact_in_header"):
        score = min(score, 69)          # layouts that scramble ATS parsing are never "good", whatever the content
    cats = {}
    names = {"read": "Readable by robots", "contact": "Contact details", "structure": "Structure", "content": "Content", "keywords": "Keywords"}
    for c in C:
        k = cats.setdefault(c["cat"], {"name": names[c["cat"]], "points": 0, "max": 0})
        k["points"] += c["points"]
        k["max"] += c["max"]
    for k in cats.values():
        k["pct"] = round(100 * k["points"] / k["max"]) if k["max"] else None
    return score, C, cats


def _fmt_months(m):
    y, mo = divmod(m, 12)
    if y and mo:
        return "%d years %d months" % (y, mo)
    return ("%d years" % y) if y else ("%d months" % mo)


# ---------------------------------------------------------------- public API (with cache)

def _fingerprint(path):
    st = os.stat(path)
    return "%d-%d" % (st.st_size, int(st.st_mtime))


def parse_cv(cv, path, profile, force=False):
    """Parse one CV file (cached by file fingerprint + profile skills)."""
    cache = store.get_setting("cv_parsed", {}) or {}
    fp = _fingerprint(path) + "|" + hashlib.md5(json.dumps([profile.get("skills_extra"), profile.get("target_titles"),
                                                            profile.get("country"), profile.get("city"), profile.get("current_title")]).encode()).hexdigest()[:8]
    hit = cache.get(cv["id"])
    if hit and hit.get("fp") == fp and not force and hit.get("v") == 3:
        return hit
    text, facts = read(path)
    a = analyze(text, facts, cv.get("name", ""), cv.get("size", 0), profile)
    data = {"v": 3, "fp": fp, "at": int(time.time()), "text": text[:40000], "facts": facts, "a": a}
    cache = {k: v for k, v in cache.items() if k in {c["id"] for c in (store.get_setting("cv_files", []) or [])}}
    cache[cv["id"]] = data
    store.set_setting("cv_parsed", cache)
    return data


def full_check(cv, path, profile, force=False):
    data = parse_cv(cv, path, profile, force)
    targets = profile.get("target_titles") or profile.get("current_title") or ""
    country = geo_code(profile.get("country", ""))
    market, n = market_skills(targets, country)
    score, checks, cats = check(data["text"], data["facts"], data["a"], market, n)
    a = data["a"]
    full, partial = skills.closure(a["skills"])
    return {"cv": {k: cv[k] for k in ("id", "label", "name")}, "score": score, "grade": _grade(score), "checks": checks, "categories": cats,
            "facts": {k: data["facts"].get(k) for k in ("format", "pages", "columns", "tables", "images", "photo", "fonts", "body_size", "text_boxes")},
            "profile": {"skills": a["skills"], "years": round(a["months"] / 12, 1), "languages": a["languages"], "education": a["education"],
                        "language": a["language"], "sections": a["sections"], "families": [synonyms.CONCEPTS[i].get("en", [""])[0] for i in a["families"]][:8]},
            "market": [{"skill": s, "share": round(sh * 100), "have": s in full, "partial": s not in full and partial.get(s, 0) >= 0.4}
                       for s, sh in market],
            "market_jobs": n, "targets": targets, "ats_text": data["text"][:6000], "checked_at": data["at"]}


def _grade(score):
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs work" if score >= 50 else "Weak"

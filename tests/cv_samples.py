"""Sample CVs generated on the fly for the tests (no binary fixtures in the repo)."""
import os

GOOD_FR = """Amira Trabelsi
Comptable confirmée
amira.trabelsi@example.com | +216 20 123 456 | Tunis, Tunisie | linkedin.com/in/amira-trabelsi

Profil
Comptable avec 4 ans d'expérience en comptabilité générale, fiscalité et reporting financier IFRS.

Expérience professionnelle
Comptable - Stram SA, Tunis
03/2022 - Présent
- Géré la clôture mensuelle de 3 filiales et réduit les délais de 30%
- Préparé les déclarations fiscales (TVA, IS) pour 120 clients
- Automatisé les rapprochements bancaires avec Excel et VBA
Assistante comptable - Cabinet Ben Ali, Sfax
09/2020 - 02/2022
- Saisie comptable et tenue des comptes sur Sage 100
- Analysé les écarts budgétaires et préparé le reporting mensuel

Formation
Master en comptabilité, contrôle et audit - IHEC Carthage, 2020
Licence en sciences comptables - FSEG Tunis, 2018

Compétences
Comptabilité générale, IFRS, fiscalité, Sage 100, Excel (tableaux croisés dynamiques), SAP FI, Power BI

Langues
Arabe - langue maternelle
Français - courant (C1)
Anglais - intermédiaire (B2)
"""


def make_pdf(path, text=GOOD_FR, two_columns=False, table=False, image_only=False):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    if image_only:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 500), 0)
        pix.clear_with(200)
        page.insert_image(pymupdf.Rect(60, 60, 460, 560), pixmap=pix)
        doc.save(path)
        return path
    lines = text.split("\n")
    if two_columns:
        side = [l for l in lines if l and ("@" in l or l in ("Compétences", "Langues") or "courant" in l or "maternelle" in l or "Anglais" in l)]
        main = [l for l in lines if l not in side]
        y = 60
        for l in side + ["Python, SQL, Excel", "Permis B", "Sage 100 et SAP", "Power BI dashboards", "Analyse financière avancée"]:
            page.insert_text((30, y), l[:32], fontsize=9)
            y += 14
        y = 60
        for l in main:
            page.insert_textbox(pymupdf.Rect(220, y - 10, 570, y + 30), l, fontsize=10)
            y += 16
            if y > 800:
                break
    else:
        y = 50
        for l in lines:
            page.insert_text((50, y), l, fontsize=10.5)
            y += 15
            if y > 810:
                page = doc.new_page(width=595, height=842)
                y = 50
    if table:
        r = pymupdf.Rect(50, 700, 540, 790)
        for i in range(4):
            page.draw_line((r.x0, r.y0 + i * 30), (r.x1, r.y0 + i * 30))
        for x in (r.x0, r.x0 + 160, r.x0 + 320, r.x1):
            page.draw_line((x, r.y0), (x, r.y0 + 90))
        for i, row in enumerate([("Poste", "Entreprise", "Dates"), ("Comptable", "Stram", "2022-2024"), ("Assistante", "Ben Ali", "2020-2022")]):
            for k, cell in enumerate(row):
                page.insert_text((r.x0 + 6 + k * 160, r.y0 + 20 + i * 30), cell, fontsize=9)
    doc.save(path)
    return path


def make_docx(path, header_contact=True, with_table=True):
    import docx
    d = docx.Document()
    if header_contact:
        d.sections[0].header.paragraphs[0].text = "amira.trabelsi@example.com  +216 20 123 456"
    body = [l for l in GOOD_FR.split("\n") if "@" not in l] if header_contact else GOOD_FR.split("\n")
    for l in body:
        d.add_paragraph(l)
    if with_table:
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text = "Outils"
        t.cell(0, 1).text = "Sage, SAP"
        t.cell(1, 0).text = "Langues"
        t.cell(1, 1).text = "Arabe, Français"
    d.save(path)
    return path


def all_samples(folder):
    os.makedirs(folder, exist_ok=True)
    return {"good": make_pdf(os.path.join(folder, "Amira_Trabelsi_CV.pdf")),
            "columns": make_pdf(os.path.join(folder, "cv.pdf"), two_columns=True, table=True),
            "scan": make_pdf(os.path.join(folder, "scan.pdf"), image_only=True),
            "docx": make_docx(os.path.join(folder, "Amira CV.docx"))}

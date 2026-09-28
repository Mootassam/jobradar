"""Your applicant profile + CV versions (stored only on this computer) and the pairing code that lets the
JobRadar Autofill browser extension read them. Nothing here is ever sent anywhere else."""
import hmac
import json
import os
import re
import secrets
import time

import app_paths
import store

CV_DIR = os.path.join(app_paths.DATA_DIR, "cv")
os.makedirs(CV_DIR, exist_ok=True)
CV_EXT = {".pdf": "application/pdf", ".doc": "application/msword",
          ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          ".odt": "application/vnd.oasis.opendocument.text", ".rtf": "application/rtf", ".txt": "text/plain"}
MAX_CV_BYTES = 10 * 1024 * 1024

FIELDS = {
    # personal
    "first_name": 60, "last_name": 60, "email": 120, "phone": 40, "address": 200, "city": 80, "postal_code": 20, "country": 80,
    # links
    "linkedin": 200, "github": 200, "website": 200,
    # work
    "current_title": 120, "current_company": 120, "years_experience": 10, "salary_expectation": 60, "notice_period": 60,
    "education_school": 150, "education_degree": 150, "languages": 200,
    # questions (yes / no / "")
    "authorized_to_work": 5, "requires_sponsorship": 5, "willing_to_relocate": 5,
    # long texts
    "summary": 3000, "cover_letter": 6000,
    # CV match: the jobs you want + skills your CV doesn't show
    "target_titles": 200, "skills_extra": 600,
}
YES_NO = ("authorized_to_work", "requires_sponsorship", "willing_to_relocate")


def get():
    p = store.get_setting("profile", {}) or {}
    return {k: p.get(k, "") for k in FIELDS}


def save(data):
    cur = get()
    for k, n in FIELDS.items():
        if k in data:
            v = str(data[k] or "").strip()
            if k in YES_NO and v not in ("yes", "no", ""):
                raise ValueError("%s must be yes, no or empty" % k)
            if k == "email" and v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                raise ValueError("That email address doesn't look right")
            for link in ("linkedin", "github", "website"):
                if k == link and v and not v.startswith(("http://", "https://")):
                    v = "https://" + v
            cur[k] = v[:n]
    store.set_setting("profile", cur)
    return cur


# ---------------------------------------------------------------- CV versions

def cvs():
    items = store.get_setting("cv_files", []) or []
    default = store.get_setting("cv_default", "")
    if items and default not in {c["id"] for c in items}:
        default = items[0]["id"]
    for c in items:
        c["default"] = c["id"] == default
    return items


def cv_path(cid):
    c = next((x for x in cvs() if x["id"] == cid), None)
    if c is None:
        return None, None
    path = os.path.join(CV_DIR, c["file"])
    return (path, c) if os.path.exists(path) else (None, None)


def add_cv(file_storage, label=""):
    name = os.path.basename(file_storage.filename or "cv.pdf")
    ext = os.path.splitext(name)[1].lower()
    if ext not in CV_EXT:
        raise ValueError("Upload a PDF, Word (.doc/.docx), ODT, RTF or TXT file")
    data = file_storage.read(MAX_CV_BYTES + 1)
    if len(data) > MAX_CV_BYTES:
        raise ValueError("CV files must be under 10 MB")
    if not data:
        raise ValueError("The file is empty")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise ValueError("That file isn't a valid PDF")
    cid = secrets.token_hex(6)
    fname = cid + ext
    with open(os.path.join(CV_DIR, fname), "wb") as f:
        f.write(data)
    items = store.get_setting("cv_files", []) or []
    items.append({"id": cid, "name": name[:120], "label": (label or os.path.splitext(name)[0])[:60], "file": fname,
                  "size": len(data), "mime": CV_EXT[ext], "uploaded_at": int(time.time())})
    store.set_setting("cv_files", items)
    if len(items) == 1:
        store.set_setting("cv_default", cid)
    return cid


def update_cv(cid, label=None, default=None):
    items = store.get_setting("cv_files", []) or []
    for c in items:
        if c["id"] == cid and label is not None:
            c["label"] = str(label).strip()[:60] or c["label"]
    store.set_setting("cv_files", items)
    if default:
        store.set_setting("cv_default", cid)


def delete_cv(cid):
    items = store.get_setting("cv_files", []) or []
    keep = [c for c in items if c["id"] != cid]
    for c in items:
        if c["id"] == cid:
            try:
                os.remove(os.path.join(CV_DIR, c["file"]))
            except OSError:
                pass
    store.set_setting("cv_files", keep)
    if store.get_setting("cv_default", "") == cid:
        store.set_setting("cv_default", keep[0]["id"] if keep else "")


# ---------------------------------------------------------------- extension pairing

def token():
    t = store.get_setting("ext_token", "")
    if not t:
        t = new_token()
    return t


def new_token():
    t = "JR-" + secrets.token_urlsafe(18)
    store.set_setting("ext_token", t)
    return t


def token_ok(given):
    t = store.get_setting("ext_token", "")
    return bool(t) and bool(given) and hmac.compare_digest(str(t), str(given))


def fill_template(text, job_title="", company=""):
    p = get()
    name = " ".join(x for x in (p["first_name"], p["last_name"]) if x)
    out = str(text or "")
    for k, v in (("{job_title}", job_title or "this position"), ("{company}", company or "your company"), ("{my_name}", name)):
        out = out.replace(k, v)
    return out


def public_for_extension():
    p = get()
    p["full_name"] = " ".join(x for x in (p["first_name"], p["last_name"]) if x)
    return {"profile": p, "cvs": [{k: c[k] for k in ("id", "label", "name", "size", "mime", "default")} for c in cvs()]}


def export_json():
    return json.dumps({"profile": get(), "cvs": cvs()}, ensure_ascii=False)

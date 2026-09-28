"""Where JobRadar keeps its data. JOBRADAR_DATA overrides (tests)."""
import os
import sys

APP_NAME = "JobRadar"
APP_VERSION = "1.4.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")


def _data_dir():
    env = os.environ.get("JOBRADAR_DATA")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False) or os.path.exists(os.path.join(BASE_DIR, ".installed")):
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
    return os.path.join(BASE_DIR, "data")


DATA_DIR = _data_dir()
DB_PATH = os.path.join(DATA_DIR, "jobradar.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
for _d in (DATA_DIR, BACKUP_DIR, EXPORT_DIR):
    os.makedirs(_d, exist_ok=True)


def migrate_legacy_data():
    """First start of the installed app: bring over the data of the copy you used before (jobs, profile, CVs...).
    The old folder is listed in legacy_data.txt (written by build.ps1). Nothing is deleted from it."""
    if os.path.exists(DB_PATH):
        return False
    marker = os.path.join(BASE_DIR, "legacy_data.txt")
    try:
        old = open(marker, encoding="utf-8").read().strip()
    except OSError:
        return False
    src = os.path.join(old, "jobradar.db")
    if not old or not os.path.isfile(src) or os.path.abspath(old) == os.path.abspath(DATA_DIR):
        return False
    import shutil
    import sqlite3
    a, b = sqlite3.connect(src, timeout=30), sqlite3.connect(DB_PATH)
    try:
        a.backup(b)                      # consistent copy even if the old copy is open
    finally:
        a.close()
        b.close()
    for sub in ("cv",):
        s_dir, d_dir = os.path.join(old, sub), os.path.join(DATA_DIR, sub)
        if os.path.isdir(s_dir):
            shutil.copytree(s_dir, d_dir, dirs_exist_ok=True)
    return True

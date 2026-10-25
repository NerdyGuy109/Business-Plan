"""Backups.

* Automatic: after every save, today's copy of the catalog is written to
  data/backups/catalog-YYYY-MM-DD.json (the last state of each day). The newest
  KEEP_DAYS daily files are kept.
* Before risky operations (Excel import, POS import) a timestamped copy is made too.
* Full backup: a .zip of the catalog, users and item pictures, downloadable by the owner
  from Settings, or made with `python -m app.backup zip`.
* Restore (with the server stopped): `python -m app.backup restore <file.zip|file.json>`.
"""

import glob
import io
import json
import os
import shutil
import sys
import zipfile
from datetime import date, datetime

from .store import DATA_DIR, DATA_FILE, IMAGE_DIR

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
KEEP_DAYS = 30
KEEP_SNAPSHOTS = 20


def _write(store, name):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, name)
    with store.lock:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(store.data, f)
    os.replace(path + ".tmp", path)
    return path


def _prune(pattern, keep):
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, pattern)))
    for old in files[:-keep]:
        os.remove(old)


def daily_listener(store):
    """Store listener: keep today's copy current."""
    try:
        _write(store, f"catalog-{date.today().isoformat()}.json")
        _prune("catalog-????-??-??.json", KEEP_DAYS)
    except OSError as e:
        return f"Backup could not be written: {e}"
    return None


def snapshot(store, reason):
    path = _write(store, f"snapshot-{datetime.now():%Y-%m-%dT%H%M%S}-{reason}.json")
    _prune("snapshot-*.json", KEEP_SNAPSHOTS)
    return path


def list_backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for path in sorted(glob.glob(os.path.join(BACKUP_DIR, "*.json")), reverse=True):
        st = os.stat(path)
        out.append({"name": os.path.basename(path), "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")})
    return out


def make_zip(store, users_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        with store.lock:
            z.writestr("catalog.json", json.dumps(store.data, indent=2))
        if os.path.exists(users_path):
            z.write(users_path, "users.json")
        for path in glob.glob(os.path.join(IMAGE_DIR, "*")):
            if os.path.isfile(path) and not path.endswith(".gitkeep"):
                z.write(path, f"images/{os.path.basename(path)}")
        z.writestr("README.txt", "Menu & Inventory backup, made " + datetime.now().isoformat(timespec="minutes") +
                   ".\nRestore with: python -m app.backup restore <this file>\n")
    return buf.getvalue()


def restore(path, users_path):
    """Replace the live data with a backup. Run only while the server is stopped."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if os.path.exists(DATA_FILE):  # keep what is being replaced
        shutil.copy(DATA_FILE, os.path.join(BACKUP_DIR, f"snapshot-{datetime.now():%Y-%m-%dT%H%M%S}-before-restore.json"))
    if path.endswith(".json"):
        json.load(open(path, encoding="utf-8"))  # refuse anything that isn't valid JSON
        shutil.copy(path, DATA_FILE)
        return ["catalog.json"]
    restored = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "catalog.json" not in names:
            raise SystemExit("Not a Menu & Inventory backup (no catalog.json inside)")
        json.loads(z.read("catalog.json"))
        with open(DATA_FILE, "wb") as f:
            f.write(z.read("catalog.json"))
        restored.append("catalog.json")
        if "users.json" in names:
            with open(users_path, "wb") as f:
                f.write(z.read("users.json"))
            restored.append("users.json")
        os.makedirs(IMAGE_DIR, exist_ok=True)
        for n in names:
            base = os.path.basename(n)
            if n.startswith("images/") and base and not base.startswith("."):
                with open(os.path.join(IMAGE_DIR, base), "wb") as f:
                    f.write(z.read(n))
                restored.append(n)
    return restored


if __name__ == "__main__":
    from .auth import USERS_FILE
    from .store import Store
    args = sys.argv[1:]
    if args[:1] == ["zip"]:
        out = args[1] if len(args) > 1 else f"menu-inventory-backup-{date.today().isoformat()}.zip"
        with open(out, "wb") as f:
            f.write(make_zip(Store(), USERS_FILE))
        print("Wrote", out)
    elif len(args) == 2 and args[0] == "restore":
        print("Restored:", ", ".join(restore(args[1], USERS_FILE)))
        print("Start the server again to use the restored data.")
    elif args[:1] == ["list"]:
        for b in list_backups():
            print(f"{b['modified']}  {b['name']}  ({b['size'] // 1024} KB)")
    else:
        print(__doc__)

"""Web app: python -m app.server [--host 127.0.0.1] [--port 8000]  then open http://localhost:8000

Standard-library HTTP server with a small JSON API. Every change is saved to
data/catalog.json, re-exported to exports/inventory.xlsx and copied to today's backup.

Everyone signs in. The first visit asks for the owner account; the owner adds the
other users (staff / manager / owner) on the Settings tab.
"""

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import tempfile
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import backup, pos_import
from .auth import RANK, ROLES, SESSION_HOURS, Users
from .excel import EXPORT_PATH, export_listener, export_workbook, import_workbook
from .store import IMAGE_DIR, ROOT, Store, ValidationError

STATIC_DIR = os.path.join(ROOT, "app", "static")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_BODY = 15 * 1024 * 1024
COOKIE = "mi_session"
PUBLIC_STATIC = ("login.html", "styles.css", "login.js")

store = Store()
store.listeners += [export_listener, backup.daily_listener]
users = Users()

# What the lowest role allowed to make each change is. Anything not listed needs a manager.
STAFF_ROUTES = [
    ("POST", r"/api/sales"),
    ("POST", r"/api/purchase-orders/[\w-]+/(receive|delay)"),
    ("POST", r"/api/counts"),
    ("POST", r"/api/waste"),
    ("POST", r"/api/me/password"),
    ("POST", r"/api/logout"),
]
OWNER_ROUTES = [
    ("PUT", r"/api/settings"),
    ("GET", r"/api/backup\.zip"),
    ("GET", r"/api/backups/[\w.-]+"),
]


def required_role(method, path):
    for m, pattern in OWNER_ROUTES:
        if (m in (None, method)) and re.fullmatch(pattern, path):
            return "owner"
    for m, pattern in STAFF_ROUTES:
        if m == method and re.fullmatch(pattern, path):
            return "staff"
    if method == "GET" and (path in ("/", "/index.html", "/api/state") or path.startswith(("/images/", "/static/"))):
        return "staff"
    return "manager"


def snapshot_for(user):
    """The state a user may see: staff don't get other people's pay rates or contact details."""
    snap = store.snapshot()
    snap["me"] = Users.public(user)
    if RANK[user["role"]] < RANK["manager"]:
        snap["employees"] = [e if e["id"] == user.get("employee_id") else
                             {**e, "hourly_rate": None, "phone": "", "email": ""} for e in snap["employees"]]
    if user["role"] == "owner":
        snap["users"] = [Users.public(u) for u in users.users]
        snap["backups"] = backup.list_backups()
    elif user["role"] == "manager":  # managers look after staff accounts
        snap["users"] = [Users.public(u) for u in users.users if u["role"] == "staff" or u["username"] == user["username"]]
    snap["roles"] = ROLES
    return snap


def _decode_data_url(data_url):
    m = re.match(r"data:([\w/.+-]+);base64,(.*)$", data_url or "", re.S)
    if not m:
        raise ValidationError("Expected a base64 data URL")
    try:
        return m.group(1), base64.b64decode(m.group(2), validate=True)
    except binascii.Error:
        raise ValidationError("File is not valid base64")


class Handler(BaseHTTPRequestHandler):
    server_version = "MenuInventory/1.0"
    user = None

    # ------------------------------------------------------------ helpers
    def _send(self, status, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _file(self, base, rel):
        path = os.path.realpath(os.path.join(base, rel))
        if not path.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(path):
            return self._send(404, {"error": "Not found"})
        with open(path, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(path)[0] or "application/octet-stream")

    def _json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValidationError("Upload too large (15 MB max)")
        return json.loads(self.rfile.read(length) or b"{}")

    def _ok(self, extra=None):
        warnings = store.save()
        self._send(200, {**(extra or {}), "state": snapshot_for(self.user), "warnings": warnings})

    def _token(self):
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        return jar[COOKIE].value if COOKIE in jar else None

    def _secure(self):
        return self.headers.get("X-Forwarded-Proto") == "https" or os.environ.get("MENU_SECURE_COOKIES") == "1"

    def _cookie(self, token, max_age):
        flags = "HttpOnly; SameSite=Strict; Path=/" + ("; Secure" if self._secure() else "")
        return {"Set-Cookie": f"{COOKIE}={token}; Max-Age={max_age}; {flags}"}

    def _client_ip(self):
        if os.environ.get("MENU_TRUST_PROXY") == "1" and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[0].strip()
        return self.client_address[0]

    def _authorize(self, method, path):
        """Return True if the request may go ahead; otherwise the response has been sent."""
        self.user = users.session_user(self._token())
        if not self.user:
            if method == "GET" and not path.startswith("/api/") and not path.startswith("/images/"):
                self._send(302, b"", "text/plain", {"Location": "/login"})
            else:
                self._send(401, {"error": "Please sign in", "login": True})
            return False
        if self.user.get("must_change") and method != "GET" and path not in ("/api/me/password", "/api/logout"):
            self._send(403, {"error": "Choose a new password first", "must_change": True})
            return False
        need = required_role(method, path)
        if RANK[self.user["role"]] < RANK[need]:
            self._send(403, {"error": f"This needs a {need} account"})
            return False
        return True

    def log_message(self, fmt, *args):  # quieter console
        if not self.path.startswith(("/images/", "/static/")):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ routes
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/login":
            return self._file(STATIC_DIR, "login.html")
        if path == "/api/setup-needed":
            return self._send(200, {"setup": users.needs_setup()})
        if path.startswith("/static/") and path[len("/static/"):] in PUBLIC_STATIC:
            return self._file(STATIC_DIR, path[len("/static/"):])
        if not self._authorize("GET", path):
            return
        if path in ("/", "/index.html"):
            return self._file(STATIC_DIR, "index.html")
        if path.startswith("/static/"):
            return self._file(STATIC_DIR, path[len("/static/"):])
        if path.startswith("/images/"):
            return self._file(IMAGE_DIR, path[len("/images/"):])
        if path == "/api/state":
            return self._send(200, snapshot_for(self.user))
        if path == "/api/export.xlsx":
            fd, tmp = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            try:
                with store.lock:
                    export_workbook(store, tmp)
                with open(tmp, "rb") as f:
                    body = f.read()
            finally:
                os.unlink(tmp)
            return self._send(200, body,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              {"Content-Disposition": 'attachment; filename="inventory.xlsx"'})
        if path == "/api/backup.zip":
            from .auth import USERS_FILE
            name = f"menu-inventory-backup-{date.today().isoformat()}.zip"
            return self._send(200, backup.make_zip(store, USERS_FILE), "application/zip",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        m = re.fullmatch(r"/api/backups/([\w.-]+\.json)", path)
        if m:
            path = os.path.join(backup.BACKUP_DIR, m.group(1))
            if not os.path.isfile(path):
                return self._send(404, {"error": "Not found"})
            with open(path, "rb") as f:
                return self._send(200, f.read(), "application/json",
                                  {"Content-Disposition": f'attachment; filename="{m.group(1)}"'})
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        self._mutate("POST")

    def do_PUT(self):
        self._mutate("PUT")

    def do_DELETE(self):
        self._mutate("DELETE")

    def _mutate(self, method):
        path = urlparse(self.path).path
        try:
            # Browsers won't add a custom header to a cross-site form post, so this blocks CSRF.
            if self.headers.get("X-Requested-With") != "app":
                return self._send(400, {"error": "Missing X-Requested-With header"})
            body = self._json() if method != "DELETE" else {}
            if path == "/api/login" and method == "POST":
                token, user = users.login(body.get("username"), body.get("password"), self._client_ip())
                return self._send(200, {"user": Users.public(user)}, headers=self._cookie(token, SESSION_HOURS * 3600))
            if path == "/api/setup" and method == "POST":
                if not users.needs_setup():
                    return self._send(403, {"error": "Setup is already done. Sign in instead."})
                users.create(body.get("username"), body.get("password"), body.get("name"), "owner", must_change=False)
                token, user = users.login(body.get("username"), body.get("password"), self._client_ip())
                return self._send(200, {"user": Users.public(user)}, headers=self._cookie(token, SESSION_HOURS * 3600))
            if not self._authorize(method, path):
                return
            if path == "/api/logout":
                users.logout(self._token())
                return self._send(200, {"ok": True}, headers=self._cookie("", 0))
            if path == "/api/me/password":
                users.change_own_password(self.user["username"], body.get("current"), body.get("new"), self._token())
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/users(?:/([\w.-]+))?", path)
            if m:
                owner = self.user["role"] == "owner"
                target = users.get(m.group(1)) if m.group(1) else None
                if not owner:  # managers: staff accounts only, and they can't change roles
                    if (target and target["role"] != "staff") or (not target and body.get("role", "staff") != "staff") \
                            or (target and "role" in body):
                        return self._send(403, {"error": "Managers can only look after staff accounts"})
                if method == "POST" and not m.group(1):
                    users.create(body.get("username"), body.get("password"), body.get("name"),
                                 body.get("role", "staff"), body.get("employee_id", ""))
                elif method == "PUT" and m.group(1):
                    if m.group(1) == self.user["username"] and "password" in body:
                        raise ValidationError("Change your own password under My account")
                    users.update(m.group(1), {k: v for k, v in body.items() if k != "must_change"})
                elif method == "DELETE" and m.group(1):
                    if m.group(1) == self.user["username"]:
                        raise ValidationError("You can't disable your own account")
                    users.update(m.group(1), {"active": False})
                else:
                    return self._send(404, {"error": "Not found"})
                return self._send(200, {"state": snapshot_for(self.user)})
            m = re.match(r"^/api/(ingredients|items)(?:/([\w-]+))?$", path)
            if m:
                kind, obj_id = m.groups()
                if method == "DELETE":
                    (store.delete_ingredient if kind == "ingredients" else store.delete_item)(obj_id)
                    return self._ok()
                if obj_id:
                    body["id"] = obj_id
                obj = (store.upsert_ingredient if kind == "ingredients" else store.upsert_item)(body)
                return self._ok({"saved": obj})
            m = re.match(r"^/api/employees(?:/([\w-]+))?$", path)
            if m:
                emp_id = m.group(1)
                if method == "DELETE":
                    opened = store.remove_employee(emp_id)
                    return self._ok({"opened_shifts": opened})
                if emp_id:
                    body["id"] = emp_id
                return self._ok({"saved": store.upsert_employee(body)})
            if path == "/api/shifts/copy-week" and method == "POST":
                copied = store.copy_week(body.get("from"), body.get("to"))
                return self._ok({"copied": len(copied)})
            m = re.match(r"^/api/shifts(?:/([\w-]+))?$", path)
            if m:
                shift_id = m.group(1)
                if method == "DELETE":
                    store.delete_shift(shift_id)
                    return self._ok()
                if shift_id:
                    body["id"] = shift_id
                return self._ok({"saved": store.upsert_shift(body)})
            if path == "/api/images" and method == "POST":
                ctype, raw = _decode_data_url(body.get("data"))
                if ctype not in IMAGE_TYPES:
                    raise ValidationError("Image must be PNG, JPEG, WebP or GIF")
                stem = re.sub(r"[^\w-]+", "-", body.get("name") or "item").strip("-").lower()[:40] or "item"
                os.makedirs(IMAGE_DIR, exist_ok=True)
                fname, n = stem + IMAGE_TYPES[ctype], 1
                while os.path.exists(os.path.join(IMAGE_DIR, fname)):
                    n += 1
                    fname = f"{stem}-{n}{IMAGE_TYPES[ctype]}"
                with open(os.path.join(IMAGE_DIR, fname), "wb") as f:
                    f.write(raw)
                return self._send(200, {"image": fname})
            if path == "/api/sales-import/preview" and method == "POST":
                a = pos_import.analyse(store, body.get("csv", ""), body.get("mapping"), body.get("aliases"))
                a.pop("sales")
                return self._send(200, a)
            if path == "/api/sales-import" and method == "POST":
                backup.snapshot(store, "before-sales-import")
                entry = pos_import.commit(store, body.get("csv", ""), body.get("mapping"), body.get("aliases"),
                                          body.get("filename", ""), bool(body.get("force")))
                return self._ok({"imported": entry})
            m = re.match(r"^/api/sales-import/([\w-]+)/undo$", path)
            if m and method == "POST":
                return self._ok({"undone": pos_import.undo(store, m.group(1))})
            if path == "/api/counts" and method == "POST":
                body.setdefault("counted_by", self.user.get("employee_id", ""))
                return self._ok({"saved": store.record_count(body)})
            if path == "/api/waste" and method == "POST":
                body.setdefault("by", self.user.get("employee_id", ""))
                return self._ok({"saved": store.record_waste(body)})
            m = re.match(r"^/api/waste/([\w-]+)$", path)
            if m and method == "DELETE":
                store.delete_waste(m.group(1))
                return self._ok()
            if path == "/api/settings" and method == "PUT":
                store.update_settings(body)
                return self._ok()
            if path == "/api/sales" and method == "POST":
                store.record_sales(body.get("lines", []))
                return self._ok()
            if path == "/api/purchase-orders" and method == "POST":
                po = store.create_purchase_order(body.get("supplier", ""), body.get("lines", []))
                return self._ok({"saved": po})
            m = re.match(r"^/api/purchase-orders/([\w-]+)/(receive|delay|cancel)$", path)
            if m and method == "POST":
                po_id, action = m.groups()
                if action == "receive":
                    return self._ok({"receipt": store.receive_purchase_order(po_id, body or None)})
                if action == "delay":
                    store.log_delay(po_id, body.get("note"), body.get("expected"))
                else:
                    store.cancel_purchase_order(po_id)
                return self._ok()
            if path == "/api/import" and method == "POST":
                _ctype, raw = _decode_data_url(body.get("data"))
                backup.snapshot(store, "before-excel-import")
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(raw)
                try:
                    counts = import_workbook(store, tmp.name)
                finally:
                    os.unlink(tmp.name)
                return self._ok({"imported": counts})
            if path == "/api/import-local" and method == "POST":
                # Pull in edits made directly to exports/inventory.xlsx on this computer.
                backup.snapshot(store, "before-excel-import")
                return self._ok({"imported": import_workbook(store, EXPORT_PATH)})
            self._send(404, {"error": "Not found"})
        except (ValidationError, ValueError, KeyError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # keep the server alive; surface the problem in the UI
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="0.0.0.0 to allow other devices on the network (or when hosted)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--empty", action="store_true", default=os.environ.get("MENU_START_EMPTY") == "1",
                        help="start a new install with an empty catalog instead of the sample juice bar")
    args = parser.parse_args()
    if not os.path.exists(store.path):
        if not args.empty:
            from .seed import build
            build(store)
            print("No data found - loaded the sample juice bar catalog.")
        store.save()
    elif not os.path.exists(EXPORT_PATH):
        export_workbook(store)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    shown = "localhost" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
    print(f"Menu & inventory manager running at http://{shown}:{args.port}")
    if users.needs_setup():
        print("First run: open that address to create the owner account.")
    print(f"Data in {os.path.dirname(store.path)} · Excel workbook at {EXPORT_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

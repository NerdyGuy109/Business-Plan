"""Web app: python -m app.server [--port 8000]  then open http://localhost:8000

Standard-library HTTP server with a small JSON API. Every change is saved to
data/catalog.json and re-exported to exports/inventory.xlsx.
"""

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import pos_import
from .excel import EXPORT_PATH, export_listener, export_workbook, import_workbook
from .store import IMAGE_DIR, ROOT, Store, ValidationError

STATIC_DIR = os.path.join(ROOT, "app", "static")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_BODY = 15 * 1024 * 1024

store = Store()
store.listeners.append(export_listener)


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

    # ------------------------------------------------------------ helpers
    def _send(self, status, body, ctype="application/json", headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        self._send(200, {**(extra or {}), "state": store.snapshot(), "warnings": warnings})

    def log_message(self, fmt, *args):  # quieter console
        if not self.path.startswith(("/images/", "/static/")):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ routes
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._file(STATIC_DIR, "index.html")
        if path.startswith("/static/"):
            return self._file(STATIC_DIR, path[len("/static/"):])
        if path.startswith("/images/"):
            return self._file(IMAGE_DIR, path[len("/images/"):])
        if path == "/api/state":
            return self._send(200, store.snapshot())
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
            body = self._json() if method != "DELETE" else {}
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
                entry = pos_import.commit(store, body.get("csv", ""), body.get("mapping"), body.get("aliases"),
                                          body.get("filename", ""), bool(body.get("force")))
                return self._ok({"imported": entry})
            m = re.match(r"^/api/sales-import/([\w-]+)/undo$", path)
            if m and method == "POST":
                return self._ok({"undone": pos_import.undo(store, m.group(1))})
            if path == "/api/counts" and method == "POST":
                return self._ok({"saved": store.record_count(body)})
            if path == "/api/waste" and method == "POST":
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
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(raw)
                try:
                    counts = import_workbook(store, tmp.name)
                finally:
                    os.unlink(tmp.name)
                return self._ok({"imported": counts})
            if path == "/api/import-local" and method == "POST":
                # Pull in edits made directly to exports/inventory.xlsx on this computer.
                return self._ok({"imported": import_workbook(store, EXPORT_PATH)})
            self._send(404, {"error": "Not found"})
        except (ValidationError, ValueError, KeyError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # keep the server alive; surface the problem in the UI
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not os.path.exists(store.path):
        from .seed import build
        build(store)
        store.save()
        print("No data found - loaded the sample juice bar catalog.")
    elif not os.path.exists(EXPORT_PATH):
        export_workbook(store)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Menu & inventory manager running at http://{args.host}:{args.port}")
    print(f"Excel workbook kept in sync at {EXPORT_PATH}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

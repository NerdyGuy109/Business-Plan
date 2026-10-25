"""Import sales from a till / POS system's CSV export (Square, Toast, Clover, Lightspeed...).

Every POS exports item sales a little differently, so the import:
  1. guesses which columns hold the date, time, item name, size and quantity (editable),
  2. matches POS item names to menu items - by exact name, or by a name the owner
     mapped before (remembered in data["pos_aliases"]),
  3. records each row as a sale on its own date, tagged with an import batch id
     so the whole file can be undone, and refuses to load the same file twice.
"""

import csv
import hashlib
import io
import re
from datetime import datetime

from .store import Store, ValidationError, _next_id

IGNORE = "__ignore__"

# header patterns, most specific first
GUESSES = {
    "date": [r"^date$", r"^(order|sale|transaction|business) ?date", r"date"],
    "time": [r"^time$", r"(order|sale|transaction) ?time", r"\btime\b"],
    "item": [r"^item$", r"^item name$", r"^menu item$", r"^product( name)?$", r"^name$", r"item|product"],
    "size": [r"price point", r"^variation", r"^size$", r"variant"],
    "qty": [r"^qty$", r"^quantity$", r"(items|units|qty|quantity) ?sold", r"qty|quantity|count"],
    "type": [r"event type", r"^type$", r"transaction type"],
}
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%Y/%m/%d"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%I:%M%p"]
REFUND = re.compile(r"refund|void|return", re.I)


def _read(text):
    text = text.lstrip("﻿")
    if not text.strip():
        raise ValidationError("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValidationError("The file needs a header row and at least one sale")
    return [h.strip() for h in rows[0]], rows[1:]


def guess_mapping(headers):
    mapping, used = {}, set()
    for field, patterns in GUESSES.items():
        for pat in patterns:
            hit = next((h for h in headers if h not in used and re.search(pat, h, re.I)), None)
            if hit:
                mapping[field] = hit
                used.add(hit)
                break
    return mapping


def _parse_when(date_s, time_s):
    date_s, time_s = (date_s or "").strip(), (time_s or "").strip()
    if not time_s and re.search(r"\d[ T]\d{1,2}:\d{2}", date_s):  # date and time in one cell
        date_s, time_s = re.split(r"[ T]", date_s, maxsplit=1)
    d = None
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(date_s, fmt)
            break
        except ValueError:
            pass
    if d is None:
        return None
    for fmt in TIME_FORMATS:
        try:
            t = datetime.strptime(time_s.upper(), fmt)
            return d.replace(hour=t.hour, minute=t.minute, second=t.second).isoformat(timespec="seconds")
        except ValueError:
            pass
    return d.replace(hour=12).isoformat(timespec="seconds")  # no time: count it at midday


def _qty(value):
    v = re.sub(r"[^\d.\-]", "", value or "")
    try:
        return float(v) if v not in ("", "-", ".") else None
    except ValueError:
        return None


def _match(store, pos_name):
    key = pos_name.strip().lower()
    alias = store.data["pos_aliases"].get(key)
    if alias == IGNORE:
        return IGNORE, "ignored before"
    if alias and store.item(alias):
        return alias, "matched before"
    for it in store.data["items"]:
        names = {it["name"].lower(), f"{it['name']} {it.get('size', '')}".strip().lower(),
                 f"{it['name']} ({it.get('size', '')})".lower()}
        if key in names:
            return it["id"], "same name"
    return None, ""


def analyse(store: Store, text, mapping=None, aliases=None):
    """Parse the file and report what would be imported; nothing is changed."""
    headers, rows = _read(text)
    mapping = {k: v for k, v in (mapping or guess_mapping(headers)).items() if v in headers}
    missing = [f for f in ("date", "item", "qty") if f not in mapping]
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    result = {"headers": headers, "mapping": mapping, "missing": missing, "rows": len(rows), "hash": file_hash,
              "groups": [], "skipped": {}, "sales": [], "first": None, "last": None,
              "already_imported": next((i for i in store.data["imports"] if i["hash"] == file_hash and not i.get("undone")), None)}
    if missing:
        return result
    idx = {f: headers.index(h) for f, h in mapping.items()}
    cell = lambda row, f: row[idx[f]] if f in idx and idx[f] < len(row) else ""
    groups = {}
    skip = lambda why: result["skipped"].__setitem__(why, result["skipped"].get(why, 0) + 1)
    for row in rows:
        if "type" in idx and REFUND.search(cell(row, "type")):
            skip("refunds / voids")
            continue
        name = cell(row, "item").strip()
        if "size" in idx and cell(row, "size").strip() and cell(row, "size").strip().lower() not in ("regular", "default"):
            name = f"{name} ({cell(row, 'size').strip()})"
        qty = _qty(cell(row, "qty"))
        when = _parse_when(cell(row, "date"), cell(row, "time"))
        if not name:
            skip("no item name")
            continue
        if qty is None or when is None:
            skip("unreadable date or quantity")
            continue
        if qty <= 0:
            skip("zero or negative quantity (refunds)")
            continue
        g = groups.setdefault(name.lower(), {"pos_name": name, "rows": 0, "qty": 0, "entries": []})
        g["rows"] += 1
        g["qty"] += qty
        g["entries"].append((when, qty))
    aliases = {k.strip().lower(): v for k, v in (aliases or {}).items()}
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["qty"]):
        if key in aliases:
            target, how = aliases[key] or None, "chosen now"
        else:
            target, how = _match(store, g["pos_name"])
        g.update(item_id=target, matched_by=how)
        if target and target != IGNORE and store.item(target):
            for when, qty in g["entries"]:
                result["sales"].append({"item_id": target, "qty": qty, "date": when})
        result["groups"].append({k: v for k, v in g.items() if k != "entries"})
    if result["sales"]:
        dates = sorted(s["date"] for s in result["sales"])
        result["first"], result["last"] = dates[0][:10], dates[-1][:10]
    return result


def commit(store: Store, text, mapping=None, aliases=None, filename="", force=False):
    with store.lock:
        a = analyse(store, text, mapping, aliases)
        if a["missing"]:
            raise ValidationError(f"Choose the column for: {', '.join(a['missing'])}")
        if a["already_imported"] and not force:
            prev = a["already_imported"]
            raise ValidationError(f"This file was already imported on {prev['at'][:10]} ({prev['id']})")
        unmatched = [g["pos_name"] for g in a["groups"] if not g["item_id"]]
        if unmatched:
            raise ValidationError(f"Match or ignore these items first: {', '.join(unmatched[:8])}")
        if not a["sales"]:
            raise ValidationError("Nothing to import")
        fractional = [s for s in a["sales"] if s["qty"] != int(s["qty"])]
        if fractional:
            raise ValidationError("Quantities must be whole numbers of drinks")
        for g in a["groups"]:  # remember choices for next time
            store.data["pos_aliases"][g["pos_name"].strip().lower()] = g["item_id"]
        batch = _next_id("IMP", [i["id"] for i in store.data["imports"]])
        count = store.record_sales([{**s, "qty": int(s["qty"])} for s in a["sales"]], batch=batch)
        entry = {"id": batch, "at": datetime.now().isoformat(timespec="minutes"), "filename": filename,
                 "hash": a["hash"], "rows": a["rows"], "sales": count,
                 "drinks": int(sum(s["qty"] for s in a["sales"])), "first": a["first"], "last": a["last"],
                 "skipped": a["skipped"]}
        store.data["imports"].append(entry)
        return entry


def undo(store: Store, batch_id):
    """Remove an import's sales and put their ingredients back in stock."""
    with store.lock:
        entry = next((i for i in store.data["imports"] if i["id"] == batch_id), None)
        if not entry or entry.get("undone"):
            raise ValidationError("Import not found or already undone")
        keep = []
        for sale in store.data["sales"]:
            if sale.get("batch") == batch_id:
                item = store.item(sale["item_id"])
                if item:
                    store._apply_recipe(item, sale["qty"])
            else:
                keep.append(sale)
        store.data["sales"] = keep
        entry["undone"] = datetime.now().isoformat(timespec="minutes")
        return entry

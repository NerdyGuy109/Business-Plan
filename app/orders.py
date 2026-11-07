"""Orders from delivery and pickup apps (DoorDash, Uber Eats, Grubhub, phone/website).

How orders get in
-----------------
* Staff type them in from the platform's tablet ("+ New order").
* A webhook: an order hub (Deliverect, Otter, Chowly...) or an automation tool posts each order
  as JSON to /api/integrations/<channel>/orders, signed with that channel's secret. DoorDash and
  Uber Eats only send orders directly to software approved as an integration partner, so a hub
  is the practical route for a small shop.
* The apps' downloadable order reports can be loaded through the sales import, tagged by channel.

Life of an order: new -> preparing -> ready -> completed (or cancelled).
Ingredients come out of stock when the order leaves "new" (the drinks are being made), and the
sale is recorded at the price the app charged, tagged with the channel, so reports can show what
each app costs in commission. Cancelling after the drinks were made logs them as waste instead.
"""

import hmac
import hashlib
import secrets
from datetime import datetime, timedelta

from .store import Store, ValidationError, _coerce, _next_id

STATUSES = ["new", "preparing", "ready", "completed", "cancelled"]
FORWARD = {"new": {"preparing", "ready", "completed"}, "preparing": {"ready", "completed"},
           "ready": {"completed", "preparing"}}
DEFAULT_PREP_MINUTES = 15

# Example rates only: every shop enters the rates from its own agreement.
DEFAULT_CHANNELS = [
    {"id": "doordash", "name": "DoorDash", "color": "#d6361f"},
    {"id": "ubereats", "name": "Uber Eats", "color": "#0f8a4a"},
    {"id": "grubhub", "name": "Grubhub", "color": "#e8710a"},
    {"id": "phone", "name": "Phone / website", "color": "#3e7cb1"},
]


def ensure_channels(store: Store):
    """Give a catalog the standard channels (with zero rates) the first time it's used."""
    if not store.data["channels"]:
        for ch in DEFAULT_CHANNELS:
            store.data["channels"].append({**ch, "commission_pct": 0.0, "fee_per_order": 0.0, "markup_pct": 0.0,
                                           "enabled": True, "token": secrets.token_urlsafe(24)})


def channel(store: Store, ch_id):
    ch = next((c for c in store.data["channels"] if c["id"] == ch_id), None)
    if not ch:
        raise ValidationError(f"Unknown channel '{ch_id}'")
    return ch


def order(store: Store, order_id):
    o = next((x for x in store.data["orders"] if x["id"] == order_id), None)
    if not o:
        raise ValidationError(f"Order '{order_id}' not found")
    return o


def price_on(ch, item):
    """The price a drink sells for on a channel (apps often carry a delivery mark-up)."""
    return round(item["price"] * (1 + ch.get("markup_pct", 0) / 100), 2)


def update_channel(store: Store, ch_id, payload):
    with store.lock:
        ch = channel(store, ch_id)
        for key in ("commission_pct", "markup_pct"):
            if key in payload:
                v = _coerce(payload[key], float, 0.0)
                if not 0 <= v <= 100:
                    raise ValidationError("Percentages must be between 0 and 100")
                ch[key] = v
        if "fee_per_order" in payload:
            v = _coerce(payload["fee_per_order"], float, 0.0)
            if v < 0:
                raise ValidationError("The fee can't be negative")
            ch["fee_per_order"] = v
        if "enabled" in payload:
            ch["enabled"] = bool(payload["enabled"])
        if payload.get("name"):
            ch["name"] = _coerce(payload["name"], str, ch["name"])
        return ch


def new_token(store: Store, ch_id):
    with store.lock:
        ch = channel(store, ch_id)
        ch["token"] = secrets.token_urlsafe(24)
        return ch


def _totals(ch, lines):
    subtotal = round(sum(l["price"] * l["qty"] for l in lines), 2)
    commission = round(subtotal * ch.get("commission_pct", 0) / 100, 2)
    fee = round(ch.get("fee_per_order", 0), 2)
    return {"subtotal": subtotal, "commission": commission, "fee": fee, "net": round(subtotal - commission - fee, 2)}


def _clean_lines(store: Store, ch, raw_lines):
    """Lines by item_id, or by name (from a webhook), matched to menu items. Unknown names are kept
    unmatched so the order still shows up; it can't be started until they're matched."""
    lines = []
    for raw in raw_lines or []:
        qty = _coerce(raw.get("qty", raw.get("quantity")), int, 0)
        if qty <= 0:
            continue
        item = store.item(raw.get("item_id")) if raw.get("item_id") else None
        name = _coerce(raw.get("name"), str, "")
        if not item and name:
            alias = store.data["pos_aliases"].get(name.lower())
            item = store.item(alias) if alias else None
            item = item or next((i for i in store.data["items"] if i["name"].lower() == name.lower()), None)
        if raw.get("item_id") and not item:
            raise ValidationError(f"Unknown menu item '{raw.get('item_id')}'")
        price = raw.get("price")
        price = _coerce(price, float, 0.0) if price not in (None, "") else (price_on(ch, item) if item else 0.0)
        lines.append({"item_id": item["id"] if item else None, "name": item["name"] if item else name, "qty": qty,
                      "price": round(price, 2), "notes": _coerce(raw.get("notes"), str, "")})
    if not lines:
        raise ValidationError("The order has no items")
    return lines


def _when(value, default):
    if not value:
        return default
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None).isoformat(timespec="minutes")
    except ValueError:
        raise ValidationError("Times must look like 2026-11-07T12:30")


def create_order(store: Store, payload, source="manual", by=""):
    with store.lock:
        ch = channel(store, payload.get("channel"))
        if not ch.get("enabled", True):
            raise ValidationError(f"{ch['name']} is switched off in Settings")
        ext = _coerce(payload.get("external_id"), str, "")
        if ext:
            dup = next((o for o in store.data["orders"] if o["channel"] == ch["id"] and o["external_id"] == ext), None)
            if dup:
                if source == "webhook":
                    return dup  # the same order sent twice: nothing to do
                raise ValidationError(f"{ch['name']} order {ext} is already in ({dup['id']})")
        now = datetime.now().isoformat(timespec="minutes")
        placed = _when(payload.get("placed_at"), now)
        due = _when(payload.get("due_at"), (datetime.fromisoformat(placed) + timedelta(minutes=DEFAULT_PREP_MINUTES))
                    .isoformat(timespec="minutes"))
        lines = _clean_lines(store, ch, payload.get("items") or payload.get("lines"))
        o = {"id": _next_id("ORD", [x["id"] for x in store.data["orders"]]), "channel": ch["id"], "external_id": ext,
             "customer": _coerce(payload.get("customer"), str, ""), "placed_at": placed, "due_at": due,
             "notes": _coerce(payload.get("notes"), str, ""), "status": "new", "source": source, "lines": lines,
             **_totals(ch, lines), "history": [{"status": "new", "at": now, "by": by}]}
        store.data["orders"].append(o)
        return o


def match_line(store: Store, order_id, index, item_id):
    """Tell the app which menu item an unrecognised name is; remembered for next time."""
    with store.lock:
        o = order(store, order_id)
        if o["status"] != "new":
            raise ValidationError("Only new orders can be changed")
        try:
            line = o["lines"][int(index)]
        except (IndexError, ValueError, TypeError):
            raise ValidationError("No such line on the order")
        item = store.item(item_id)
        if not item:
            raise ValidationError(f"Unknown menu item '{item_id}'")
        if line["name"]:
            store.data["pos_aliases"][line["name"].lower()] = item["id"]
        ch = channel(store, o["channel"])
        if not line["price"]:
            line["price"] = price_on(ch, item)
        line["item_id"] = item["id"]
        o.update(_totals(ch, o["lines"]))
        return o


def set_status(store: Store, order_id, status, by=""):
    with store.lock:
        o = order(store, order_id)
        if status not in FORWARD.get(o["status"], set()):
            raise ValidationError(f"An order that is {o['status']} can't be marked {status}")
        if o["status"] == "new":
            if any(not l["item_id"] for l in o["lines"]):
                raise ValidationError("Match every item to the menu before starting this order")
            # the drinks are being made: take the ingredients out and record the sale
            store.record_sales([{"item_id": l["item_id"], "qty": l["qty"], "price": l["price"], "date": o["placed_at"],
                                 "channel": o["channel"], "order_id": o["id"]} for l in o["lines"]])
        o["status"] = status
        if status == "completed":
            o.pop("cancel_requested", None)  # handed over after all
        o["history"].append({"status": status, "at": datetime.now().isoformat(timespec="minutes"), "by": by})
        return o


def cancel(store: Store, order_id, made=False, by="", reason="", employee=""):
    """Cancel an order. If its drinks were already made, they become waste ('cancelled order');
    if not, the ingredients go back into stock."""
    with store.lock:
        o = order(store, order_id)
        if o["status"] in ("completed", "cancelled"):
            raise ValidationError(f"This order is already {o['status']}")
        started = o["status"] != "new"
        if started:
            for sale in [s for s in store.data["sales"] if s.get("order_id") == o["id"]]:
                item = store.item(sale["item_id"])
                if item:
                    store._apply_recipe(item, sale["qty"])
            store.data["sales"] = [s for s in store.data["sales"] if s.get("order_id") != o["id"]]
            if made:
                for l in o["lines"]:
                    store.record_waste({"kind": "item", "item_id": l["item_id"], "qty": l["qty"], "reason": "cancelled order",
                                        "by": employee, "note": f"{channel(store, o['channel'])['name']} {o['external_id'] or o['id']}"})
        o["status"] = "cancelled"
        o["cancel_reason"] = _coerce(reason, str, "")
        o["made_before_cancel"] = bool(started and made)
        o.pop("cancel_requested", None)
        o["history"].append({"status": "cancelled", "at": datetime.now().isoformat(timespec="minutes"), "by": by})
        return o


def receive_webhook(store: Store, ch_id, payload):
    """An order (or a cancellation) pushed by an order hub or automation."""
    with store.lock:
        ch = channel(store, ch_id)
        if str(payload.get("status", "")).lower() in ("cancelled", "canceled"):
            ext = _coerce(payload.get("external_id"), str, "")
            o = next((x for x in store.data["orders"] if x["channel"] == ch["id"] and x["external_id"] == ext), None)
            if not o:
                raise ValidationError(f"No {ch['name']} order {ext} to cancel")
            if o["status"] == "new":
                return cancel(store, o["id"], by="", reason=f"Cancelled on {ch['name']}")
            if o["status"] not in ("completed", "cancelled"):
                o["cancel_requested"] = True  # staff decide whether the drinks were made
            return o
        return create_order(store, {**payload, "channel": ch["id"]}, source="webhook")  # the URL decides the channel


def check_signature(ch, raw_body, headers):
    """Accept `Authorization: Bearer <token>` or `X-Signature: sha256=<hex HMAC of the body>`."""
    token = ch.get("token", "")
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip(), token):
        return True
    sig = headers.get("X-Signature", "")
    if sig.startswith("sha256="):
        expected = hmac.new(token.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig[7:].strip(), expected)
    return False


def channel_report(store: Store, since, until=None):
    """Sales, commission, fees and what the shop keeps, per channel ('in store' = no channel)."""
    until = until or "9999"
    rows = {}
    chans = {c["id"]: c for c in store.data["channels"]}
    for s in store.data["sales"]:
        if not (since <= s["date"][:10] <= until):
            continue
        key = s.get("channel") or ""
        r = rows.setdefault(key, {"channel": key, "name": chans[key]["name"] if key in chans else "In store",
                                  "drinks": 0, "gross": 0.0, "orders": set()})
        r["drinks"] += s["qty"]
        r["gross"] += store.sale_price(s) * s["qty"]
        if s.get("order_id"):
            r["orders"].add(s["order_id"])
    out = []
    for key, r in rows.items():
        ch = chans.get(key, {})
        commission = r["gross"] * ch.get("commission_pct", 0) / 100
        fees = ch.get("fee_per_order", 0) * len(r["orders"])
        out.append({"channel": key, "name": r["name"], "drinks": r["drinks"], "orders": len(r["orders"]),
                    "gross": round(r["gross"], 2), "commission": round(commission, 2), "fees": round(fees, 2),
                    "net": round(r["gross"] - commission - fees, 2)})
    return sorted(out, key=lambda x: (x["channel"] != "", -x["gross"]))

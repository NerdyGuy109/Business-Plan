"""Data store and business rules for the menu / parts inventory system.

Everything lives in one JSON file (data/catalog.json) so it is easy to back up,
diff in git, and regenerate the Excel workbook from.

Terminology
-----------
ingredient  A part that is bought, stocked and consumed (apple juice, spinach...).
menu item   Something sold to a customer. It is built from a recipe.
recipe      The bill of materials: which ingredients, and how much of each,
            go into one unit of a menu item.
"""

import json
import math
import os
import re
import threading
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Where the data lives. Set MENU_DATA_DIR to keep it on a persistent disk when hosted.
DATA_DIR = os.environ.get("MENU_DATA_DIR") or os.path.join(ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "catalog.json")
IMAGE_DIR = os.path.join(DATA_DIR, "images")

# The nine major food allergens (US FDA).
ALLERGENS = ["milk", "eggs", "fish", "shellfish", "tree nuts", "peanuts", "wheat", "soy", "sesame"]

WASTE_REASONS = ["expired / spoiled", "spilled / dropped", "damaged", "remade drink", "staff drink",
                 "free / comped drink", "prep trim", "other"]

DEFAULT_SETTINGS = {"business_name": "", "target_food_cost": 0.35}

UNITS = ["oz", "fl oz", "g", "kg", "lb", "ml", "l", "each", "scoop", "tbsp", "tsp", "cup"]

INGREDIENT_FIELDS = {
    # field: (type, default)
    "name": (str, ""),
    "category": (str, ""),
    "unit": (str, "oz"),
    "supplier": (str, ""),
    "supplier_sku": (str, ""),
    "package_desc": (str, ""),
    "package_qty": (float, 1.0),
    "yield_pct": (float, 100.0),
    "package_cost": (float, 0.0),
    "shipping_cost": (float, 0.0),
    "lead_time_days": (int, 0),
    "shelf_life_days": (int, 0),
    "min_order_packages": (int, 1),
    "on_hand": (float, 0.0),
    "reorder_point": (float, 0.0),
    "par_level": (float, 0.0),
    "notes": (str, ""),
}

ITEM_FIELDS = {
    "name": (str, ""),
    "category": (str, ""),
    "size": (str, ""),
    "price": (float, 0.0),
    "description": (str, ""),
    "image": (str, ""),
    "emoji": (str, ""),
    "active": (bool, True),
}

EMPLOYEE_FIELDS = {
    "name": (str, ""),
    "role": (str, ""),
    "hourly_rate": (float, 0.0),
    "max_hours": (float, 40.0),
    "phone": (str, ""),
    "email": (str, ""),
    "color": (str, ""),
    "active": (bool, True),
}

EMPLOYEE_COLORS = ["#2f7d5b", "#3e7cb1", "#b7791f", "#8e44ad", "#c0392b", "#16a085", "#d35400", "#2c3e50",
                   "#7f8c2d", "#e84393"]

USAGE_WINDOW_DAYS = 14
PRICE_ALERT_DAYS = 30

# "partial" = some of the order has arrived and the rest is still expected.
OPEN_PO_STATUSES = ("open", "partial")


class ValidationError(ValueError):
    pass


def _coerce(value, typ, default):
    if value is None or value == "":
        return default
    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "active")
        return bool(value)
    if typ is int:
        return int(round(float(value)))
    if typ is float:
        return round(float(value), 4)
    return str(value).strip()


def _next_id(prefix, existing):
    nums = [int(m.group(1)) for x in existing if (m := re.match(prefix + r"-(\d+)$", x))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


def empty_catalog():
    return {"settings": dict(DEFAULT_SETTINGS), "ingredients": [], "items": [], "sales": [], "purchase_orders": [],
            "employees": [], "shifts": [], "price_changes": [], "pos_aliases": {}, "imports": [],
            "counts": [], "waste": []}


def clean_allergens(value):
    """Accept a list or a comma-separated string; keep only known allergens, in standard order."""
    if isinstance(value, str):
        value = [v for v in re.split(r"[,;/]", value)]
    found = {str(v).strip().lower() for v in (value or []) if str(v).strip()}
    unknown = found - set(ALLERGENS)
    if unknown:
        raise ValidationError(f"Unknown allergen(s): {', '.join(sorted(unknown))}. Use: {', '.join(ALLERGENS)}")
    return [a for a in ALLERGENS if a in found]


def _clean_time(value, label):
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValidationError(f"{label} must be a time like 07:30")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _clean_date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise ValidationError("Date must be YYYY-MM-DD")


def shift_hours(shift):
    """Length of a shift in hours; a shift ending before it starts runs past midnight."""
    sh, sm = map(int, shift["start"].split(":"))
    eh, em = map(int, shift["end"].split(":"))
    return ((eh * 60 + em) - (sh * 60 + sm)) % (24 * 60) / 60


def week_start(day):
    """Monday of the week containing `day` (a date or ISO string)."""
    d = date.fromisoformat(day[:10]) if isinstance(day, str) else day
    return d - timedelta(days=d.weekday())


class Store:
    def __init__(self, path=DATA_FILE):
        self.path = path
        self.lock = threading.RLock()
        self.listeners = []  # callables run after every successful save
        self.data = self._load()

    # ------------------------------------------------------------------ io
    def _load(self):
        if not os.path.exists(self.path):
            return empty_catalog()
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        for key, val in empty_catalog().items():
            data.setdefault(key, val)
        for key, val in DEFAULT_SETTINGS.items():
            data["settings"].setdefault(key, val)
        for ing in data["ingredients"]:  # files saved before these fields existed
            ing.setdefault("yield_pct", 100.0)
            ing.setdefault("allergens", [])
        return data

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        warnings = []
        for fn in self.listeners:
            msg = fn(self)
            if msg:
                warnings.append(msg)
        return warnings

    # ------------------------------------------------------------- lookups
    def ingredient(self, ing_id):
        return next((i for i in self.data["ingredients"] if i["id"] == ing_id), None)

    def item(self, item_id):
        return next((i for i in self.data["items"] if i["id"] == item_id), None)

    def employee(self, emp_id):
        return next((e for e in self.data["employees"] if e["id"] == emp_id), None)

    def shift(self, shift_id):
        return next((s for s in self.data["shifts"] if s["id"] == shift_id), None)

    # --------------------------------------------------------- calculations
    @staticmethod
    def usable_per_package(ing):
        """Recipe units a package really yields after trimming, peeling, coring..."""
        return (ing.get("package_qty") or 0) * (ing.get("yield_pct", 100) or 0) / 100

    @classmethod
    def unit_cost(cls, ing):
        usable = cls.usable_per_package(ing)
        if usable <= 0:
            return 0.0
        return (ing.get("package_cost", 0) + ing.get("shipping_cost", 0)) / usable

    def item_allergens(self, item):
        found = set()
        for line in item.get("recipe", []):
            found.update((self.ingredient(line["ingredient_id"]) or {}).get("allergens", []))
        return [a for a in ALLERGENS if a in found]

    def item_cost(self, item):
        total = 0.0
        for line in item.get("recipe", []):
            ing = self.ingredient(line["ingredient_id"])
            if ing:
                total += line["qty"] * self.unit_cost(ing)
        return total

    def can_make(self, item):
        """How many of this item current stock can produce (the limiting part)."""
        counts = []
        for line in item.get("recipe", []):
            ing = self.ingredient(line["ingredient_id"])
            if not ing or line["qty"] <= 0:
                continue
            counts.append(math.floor(max(ing["on_hand"], 0) / line["qty"]))
        return min(counts) if counts else 0

    def daily_usage(self, days=USAGE_WINDOW_DAYS):
        """Average daily consumption per ingredient over the last `days` days of sales."""
        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        used = {}
        for sale in self.data["sales"]:
            if sale["date"][:10] < cutoff:
                continue
            item = self.item(sale["item_id"])
            if not item:
                continue
            for line in item.get("recipe", []):
                used[line["ingredient_id"]] = used.get(line["ingredient_id"], 0) + line["qty"] * sale["qty"]
        return {k: v / days for k, v in used.items()}

    def total_usage(self):
        used = {}
        for sale in self.data["sales"]:
            item = self.item(sale["item_id"])
            for line in (item or {}).get("recipe", []):
                used[line["ingredient_id"]] = used.get(line["ingredient_id"], 0) + line["qty"] * sale["qty"]
        return used

    @classmethod
    def suggested_packages(cls, ing):
        """Packages to order: refill to par once stock hits the reorder point."""
        if ing["on_hand"] > ing["reorder_point"]:
            return 0
        pkg = cls.usable_per_package(ing) or 1
        need = max(ing["par_level"] - ing["on_hand"], 0)
        return max(ing.get("min_order_packages") or 1, math.ceil(need / pkg))

    def used_in(self, ing_id):
        return [
            {"id": it["id"], "name": it["name"], "qty": line["qty"]}
            for it in self.data["items"]
            for line in it.get("recipe", [])
            if line["ingredient_id"] == ing_id
        ]

    @staticmethod
    def received_packages(po):
        """Good packages received so far per ingredient, across every receipt of an order."""
        got = {}
        for rc in po.get("receipts", []):
            for line in rc["lines"]:
                got[line["ingredient_id"]] = got.get(line["ingredient_id"], 0) + line["good"]
        return got

    def outstanding(self, po):
        """Packages still expected per ingredient (none once an order is closed)."""
        if po["status"] not in OPEN_PO_STATUSES:
            return {}
        got = self.received_packages(po)
        return {l["ingredient_id"]: max(l["packages"] - got.get(l["ingredient_id"], 0), 0) for l in po["lines"]}

    def on_order(self):
        qty = {}
        for po in self.data["purchase_orders"]:
            for ing_id, pkgs in self.outstanding(po).items():
                ing = self.ingredient(ing_id)
                if ing:
                    qty[ing_id] = qty.get(ing_id, 0) + pkgs * self.usable_per_package(ing)
        return qty

    def po_view(self, po):
        """A purchase order with received / damaged / outstanding counts per line."""
        got = self.received_packages(po)
        damaged = {}
        for rc in po.get("receipts", []):
            for line in rc["lines"]:
                damaged[line["ingredient_id"]] = damaged.get(line["ingredient_id"], 0) + line["damaged"]
        out = self.outstanding(po)
        return {
            **po,
            "receipts": po.get("receipts", []),
            "delays": po.get("delays", []),
            "lines": [{**l, "received": got.get(l["ingredient_id"], 0), "damaged": damaged.get(l["ingredient_id"], 0),
                       "outstanding": out.get(l["ingredient_id"], 0)} for l in po["lines"]],
        }

    # ------------------------------------------------------------- views
    def snapshot(self):
        """Everything the website needs, with derived numbers filled in."""
        with self.lock:
            usage = self.daily_usage()
            on_order = self.on_order()
            ingredients = []
            for ing in self.data["ingredients"]:
                rate = usage.get(ing["id"], 0)
                ingredients.append({
                    **ing,
                    "unit_cost": self.unit_cost(ing),
                    "usable_per_package": self.usable_per_package(ing),
                    "stock_value": ing["on_hand"] * self.unit_cost(ing),
                    "status": "reorder" if ing["on_hand"] <= ing["reorder_point"] else "ok",
                    "suggested_packages": self.suggested_packages(ing),
                    "daily_usage": rate,
                    "days_of_cover": (ing["on_hand"] / rate) if rate else None,
                    "on_order": on_order.get(ing["id"], 0),
                    "used_in": self.used_in(ing["id"]),
                })
            items = []
            for it in self.data["items"]:
                cost = self.item_cost(it)
                sold = sum(s["qty"] for s in self.data["sales"] if s["item_id"] == it["id"])
                items.append({
                    **it,
                    "cost": cost,
                    "margin": it["price"] - cost,
                    "cost_pct": (cost / it["price"]) if it["price"] else 0,
                    "can_make": self.can_make(it),
                    "allergens": self.item_allergens(it),
                    "units_sold": sold,
                })
            revenue_by_date = {}
            for sale in self.data["sales"]:
                it = self.item(sale["item_id"])
                if it:
                    d = sale["date"][:10]
                    revenue_by_date[d] = revenue_by_date.get(d, 0) + it["price"] * sale["qty"]
            cutoff = (date.today() - timedelta(days=PRICE_ALERT_DAYS)).isoformat()
            return {
                "settings": self.data["settings"],
                "ingredients": ingredients,
                "items": items,
                "price_changes": [c for c in self.data["price_changes"] if c["at"][:10] >= cutoff][::-1],
                "imports": self.data["imports"][-20:][::-1],
                "counts": self.data["counts"][-12:][::-1],
                "waste": self.data["waste"][-100:][::-1],
                "waste_reasons": WASTE_REASONS,
                "allergen_list": ALLERGENS,
                "employees": self.data["employees"],
                "shifts": [{**s, "hours": shift_hours(s)} for s in self.data["shifts"]],
                "revenue_by_date": revenue_by_date,
                "sales": self.data["sales"][-200:],
                "purchase_orders": [self.po_view(po) for po in self.data["purchase_orders"]],
                "units": UNITS,
                "usage_window_days": USAGE_WINDOW_DAYS,
            }

    # ---------------------------------------------------------- mutations
    def _clean(self, payload, fields):
        out = {}
        for key, (typ, default) in fields.items():
            try:
                out[key] = _coerce(payload.get(key), typ, default)
            except (TypeError, ValueError):
                raise ValidationError(f"'{key}' must be a {typ.__name__}")
        if not out["name"]:
            raise ValidationError("Name is required")
        return out

    def upsert_ingredient(self, payload, source="edited by hand"):
        with self.lock:
            clean = self._clean(payload, INGREDIENT_FIELDS)
            clean["allergens"] = clean_allergens(payload.get("allergens"))
            if clean["package_qty"] <= 0:
                raise ValidationError("Quantity per package must be greater than 0")
            if not 0 < clean["yield_pct"] <= 100:
                raise ValidationError("Usable yield must be between 1 and 100%")
            ing_id = payload.get("id")
            existing = self.ingredient(ing_id) if ing_id else None
            dup = next((i for i in self.data["ingredients"]
                        if i["name"].lower() == clean["name"].lower() and i is not existing), None)
            if dup:
                raise ValidationError(f"An ingredient named '{clean['name']}' already exists ({dup['id']})")
            if existing:
                before = dict(existing)
                existing.update(clean)
                self._record_price_change(before, existing, source)
                return existing
            new = {"id": ing_id or _next_id("ING", [i["id"] for i in self.data["ingredients"]]), **clean}
            self.data["ingredients"].append(new)
            return new

    def _record_price_change(self, before, after, source):
        """Log a change in an ingredient's landed unit cost and what it does to each drink's food cost."""
        old_uc, new_uc = self.unit_cost(before), self.unit_cost(after)
        if abs(new_uc - old_uc) < 1e-9:
            return None
        items = []
        for it in self.data["items"]:
            line = next((l for l in it.get("recipe", []) if l["ingredient_id"] == after["id"]), None)
            if not line:
                continue
            new_cost = self.item_cost(it)
            old_cost = new_cost - line["qty"] * (new_uc - old_uc)
            items.append({"id": it["id"], "name": it["name"], "price": it["price"],
                          "old_cost": round(old_cost, 4), "new_cost": round(new_cost, 4)})
        change = {
            "id": _next_id("PC", [c["id"] for c in self.data["price_changes"]]),
            "at": datetime.now().isoformat(timespec="minutes"),
            "ingredient_id": after["id"], "ingredient": after["name"], "unit": after.get("unit", ""),
            "source": source,
            "old": {"package_cost": before.get("package_cost", 0), "shipping_cost": before.get("shipping_cost", 0),
                    "unit_cost": round(old_uc, 5)},
            "new": {"package_cost": after.get("package_cost", 0), "shipping_cost": after.get("shipping_cost", 0),
                    "unit_cost": round(new_uc, 5)},
            "items": items,
        }
        self.data["price_changes"].append(change)
        return change

    def update_settings(self, payload):
        with self.lock:
            st = self.data["settings"]
            if "business_name" in payload:
                st["business_name"] = _coerce(payload.get("business_name"), str, "")
            if "target_food_cost" in payload:
                t = _coerce(payload.get("target_food_cost"), float, DEFAULT_SETTINGS["target_food_cost"])
                if t > 1:  # typed as a percentage
                    t = t / 100
                if not 0.05 <= t <= 0.9:
                    raise ValidationError("Target food cost should be between 5% and 90%")
                st["target_food_cost"] = round(t, 4)
            return st

    def delete_ingredient(self, ing_id):
        with self.lock:
            users = self.used_in(ing_id)
            if users:
                names = ", ".join(u["name"] for u in users)
                raise ValidationError(f"Still used in: {names}. Remove it from those recipes first.")
            self.data["ingredients"] = [i for i in self.data["ingredients"] if i["id"] != ing_id]

    def _clean_recipe(self, lines):
        merged = {}
        for line in lines or []:
            ing_id = line.get("ingredient_id")
            if not self.ingredient(ing_id):
                raise ValidationError(f"Unknown ingredient '{ing_id}'")
            qty = _coerce(line.get("qty"), float, 0.0)
            if qty <= 0:
                continue
            merged[ing_id] = merged.get(ing_id, 0) + qty
        return [{"ingredient_id": k, "qty": v} for k, v in merged.items()]

    def upsert_item(self, payload):
        with self.lock:
            clean = self._clean(payload, ITEM_FIELDS)
            clean["recipe"] = self._clean_recipe(payload.get("recipe"))
            item_id = payload.get("id")
            existing = self.item(item_id) if item_id else None
            if existing:
                existing.update(clean)
                return existing
            new = {"id": item_id or _next_id("MI", [i["id"] for i in self.data["items"]]), **clean}
            self.data["items"].append(new)
            return new

    def delete_item(self, item_id):
        with self.lock:
            self.data["items"] = [i for i in self.data["items"] if i["id"] != item_id]

    def record_sales(self, lines, when=None, batch=None):
        """Sell menu items: logs the sale and deducts every ingredient in the recipe.

        Each line may carry its own "date" (used by the POS import); otherwise `when` / now.
        Everything is validated before any stock moves.
        """
        when = when or datetime.now().isoformat(timespec="seconds")
        with self.lock:
            clean = []
            for line in lines:
                item = self.item(line.get("item_id"))
                if not item:
                    raise ValidationError(f"Unknown menu item '{line.get('item_id')}'")
                qty = _coerce(line.get("qty"), int, 0)
                if qty > 0:
                    clean.append((item, qty, line.get("date") or when))
            for item, qty, at in clean:
                self._apply_recipe(item, -qty)
                sale = {"date": at, "item_id": item["id"], "qty": qty}
                if batch:
                    sale["batch"] = batch
                self.data["sales"].append(sale)
            return len(clean)

    def _apply_recipe(self, item, qty):
        """Move stock for `qty` servings of an item (negative = used up)."""
        for r in item["recipe"]:
            ing = self.ingredient(r["ingredient_id"])
            if ing:
                ing["on_hand"] = round(ing["on_hand"] + r["qty"] * qty, 4)

    # ------------------------------------------------- counts and waste
    def theoretical_usage(self, ing_id, since, until):
        """What sales and logged waste say was used of an ingredient between two times."""
        used = 0.0
        for sale in self.data["sales"]:
            if since < sale["date"] <= until:
                item = self.item(sale["item_id"])
                for r in (item or {}).get("recipe", []):
                    if r["ingredient_id"] == ing_id:
                        used += r["qty"] * sale["qty"]
        for w in self.data["waste"]:
            if since < w["at"] <= until:
                if w["kind"] == "ingredient" and w["ingredient_id"] == ing_id:
                    used += w["qty"]
                elif w["kind"] == "item":
                    item = self.item(w["item_id"])
                    for r in (item or {}).get("recipe", []):
                        if r["ingredient_id"] == ing_id:
                            used += r["qty"] * w["qty"]
        return used

    def _clean_when(self, value):
        try:
            return datetime.fromisoformat(str(value)).isoformat(timespec="minutes") if value else \
                datetime.now().isoformat(timespec="minutes")
        except ValueError:
            raise ValidationError("Time must look like 2026-10-25T09:30")

    def _clean_by(self, emp_id):
        if emp_id and not self.employee(emp_id):
            raise ValidationError(f"Unknown employee '{emp_id}'")
        return emp_id or ""

    def record_count(self, payload):
        """Physical stock count: on-hand becomes what was counted; the difference is the variance
        (stock that left without a sale or a waste entry: over-portioning, unlogged waste, theft, errors)."""
        with self.lock:
            when = self._clean_when(payload.get("at"))
            by = self._clean_by(payload.get("counted_by"))
            lines = []
            for line in payload.get("lines", []):
                if line.get("counted") in (None, ""):
                    continue
                ing = self.ingredient(line.get("ingredient_id"))
                if not ing:
                    raise ValidationError(f"Unknown ingredient '{line.get('ingredient_id')}'")
                counted = _coerce(line.get("counted"), float, 0.0)
                if counted < 0:
                    raise ValidationError(f"{ing['name']}: count can't be negative")
                prev = max((c["at"] for c in self.data["counts"]
                            for l in c["lines"] if l["ingredient_id"] == ing["id"] and c["at"] < when),
                           default=(datetime.fromisoformat(when) - timedelta(days=USAGE_WINDOW_DAYS)).isoformat(timespec="minutes"))
                lines.append({
                    "ingredient_id": ing["id"], "expected": round(ing["on_hand"], 4), "counted": counted,
                    "variance": round(counted - ing["on_hand"], 4), "unit_cost": round(self.unit_cost(ing), 5),
                    "usage_since": prev, "theoretical_usage": round(self.theoretical_usage(ing["id"], prev, when), 4),
                })
            if not lines:
                raise ValidationError("Enter at least one counted quantity")
            for line in lines:
                self.ingredient(line["ingredient_id"])["on_hand"] = line["counted"]
            count = {"id": _next_id("CT", [c["id"] for c in self.data["counts"]]), "at": when, "counted_by": by,
                     "notes": _coerce(payload.get("notes"), str, ""), "lines": lines,
                     "variance_value": round(sum(l["variance"] * l["unit_cost"] for l in lines), 2)}
            self.data["counts"].append(count)
            return count

    def record_waste(self, payload):
        """Log something thrown away: an ingredient quantity, or whole drinks (deducts their recipe)."""
        with self.lock:
            kind = payload.get("kind") or ("item" if payload.get("item_id") else "ingredient")
            reason = _coerce(payload.get("reason"), str, "")
            if reason not in WASTE_REASONS:
                raise ValidationError(f"Reason must be one of: {', '.join(WASTE_REASONS)}")
            qty = _coerce(payload.get("qty"), float, 0.0)
            if qty <= 0:
                raise ValidationError("Quantity must be more than 0")
            entry = {"id": _next_id("WS", [w["id"] for w in self.data["waste"]]),
                     "at": self._clean_when(payload.get("at")), "by": self._clean_by(payload.get("by")),
                     "kind": kind, "qty": qty, "reason": reason, "note": _coerce(payload.get("note"), str, "")}
            if kind == "item":
                item = self.item(payload.get("item_id"))
                if not item:
                    raise ValidationError("Choose the drink that was thrown away")
                if qty != int(qty):
                    raise ValidationError("Drinks must be a whole number")
                entry.update(item_id=item["id"], name=item["name"], cost=round(self.item_cost(item) * qty, 2))
                self._apply_recipe(item, -qty)
            elif kind == "ingredient":
                ing = self.ingredient(payload.get("ingredient_id"))
                if not ing:
                    raise ValidationError("Choose the ingredient that was thrown away")
                entry.update(ingredient_id=ing["id"], name=ing["name"], unit=ing["unit"],
                             cost=round(self.unit_cost(ing) * qty, 2))
                ing["on_hand"] = round(ing["on_hand"] - qty, 4)
            else:
                raise ValidationError("Waste kind must be 'ingredient' or 'item'")
            self.data["waste"].append(entry)
            return entry

    def delete_waste(self, waste_id):
        """Remove a mistaken waste entry and put the stock back."""
        with self.lock:
            entry = next((w for w in self.data["waste"] if w["id"] == waste_id), None)
            if not entry:
                raise ValidationError("Waste entry not found")
            if entry["kind"] == "item" and self.item(entry["item_id"]):
                self._apply_recipe(self.item(entry["item_id"]), entry["qty"])
            elif entry["kind"] == "ingredient" and self.ingredient(entry["ingredient_id"]):
                ing = self.ingredient(entry["ingredient_id"])
                ing["on_hand"] = round(ing["on_hand"] + entry["qty"], 4)
            self.data["waste"] = [w for w in self.data["waste"] if w["id"] != waste_id]

    def create_purchase_order(self, supplier, lines):
        with self.lock:
            clean = []
            for line in lines:
                ing = self.ingredient(line.get("ingredient_id"))
                pkgs = _coerce(line.get("packages"), int, 0)
                if not ing:
                    raise ValidationError(f"Unknown ingredient '{line.get('ingredient_id')}'")
                if pkgs > 0:
                    clean.append({
                        "ingredient_id": ing["id"],
                        "packages": pkgs,
                        "package_cost": ing["package_cost"],
                        "shipping_cost": ing["shipping_cost"],
                    })
            if not clean:
                raise ValidationError("Purchase order has no lines")
            lead = max(self.ingredient(l["ingredient_id"])["lead_time_days"] for l in clean)
            po = {
                "id": _next_id("PO", [p["id"] for p in self.data["purchase_orders"]]),
                "supplier": supplier,
                "created": date.today().isoformat(),
                "expected": (date.today() + timedelta(days=lead)).isoformat(),
                "status": "open",
                "lines": clean,
            }
            self.data["purchase_orders"].append(po)
            return po

    def purchase_order(self, po_id):
        po = next((p for p in self.data["purchase_orders"] if p["id"] == po_id), None)
        if not po:
            raise ValidationError(f"Purchase order '{po_id}' not found")
        return po

    def receive_purchase_order(self, po_id, payload=None):
        """Record a delivery against an order.

        payload["lines"]: [{ingredient_id, good, damaged, note}] - good packages go into stock,
        damaged ones are logged but not stocked. Anything not received stays outstanding
        (status "partial") unless payload["close_short"] says nothing more is coming.
        With no payload, everything outstanding is received in good condition.
        """
        payload = payload or {}
        with self.lock:
            po = self.purchase_order(po_id)
            if po["status"] not in OPEN_PO_STATUSES:
                raise ValidationError(f"{po_id} is already {po['status']}")
            remaining = self.outstanding(po)
            given = {l.get("ingredient_id"): l for l in payload.get("lines", [])}
            unknown = set(given) - set(remaining)
            if unknown:
                raise ValidationError(f"{', '.join(map(str, unknown))} is not on {po_id}")
            lines = []
            for ing_id, expected in remaining.items():
                src = given.get(ing_id, {"good": expected} if "lines" not in payload else {})
                good = _coerce(src.get("good"), int, 0)
                damaged = _coerce(src.get("damaged"), int, 0)
                if good < 0 or damaged < 0:
                    raise ValidationError("Quantities can't be negative")
                if good > expected:
                    name = self.ingredient(ing_id)["name"] if self.ingredient(ing_id) else ing_id
                    raise ValidationError(f"{name}: {good} good packages entered but only {expected} outstanding")
                invoice_cost = src.get("invoice_cost")
                invoice_cost = None if invoice_cost in (None, "") else _coerce(invoice_cost, float, 0.0)
                if invoice_cost is not None and invoice_cost < 0:
                    raise ValidationError("Invoice price can't be negative")
                lines.append({"ingredient_id": ing_id, "expected": expected, "good": good, "damaged": damaged,
                              "note": _coerce(src.get("note"), str, ""), "invoice_cost": invoice_cost})
            close_short = bool(payload.get("close_short"))
            if not any(l["good"] or l["damaged"] for l in lines) and not close_short:
                raise ValidationError("Enter what arrived, or tick 'nothing else is coming' to close the order")
            received_by = payload.get("received_by") or ""
            if received_by and not self.employee(received_by):
                raise ValidationError(f"Unknown employee '{received_by}'")
            when = payload.get("received_at") or datetime.now().isoformat(timespec="minutes")
            try:
                when = datetime.fromisoformat(str(when)).isoformat(timespec="minutes")
            except ValueError:
                raise ValidationError("Received time must look like 2026-10-25T09:30")
            receipt = {
                "id": _next_id("RC", [rc["id"] for p in self.data["purchase_orders"] for rc in p.get("receipts", [])]),
                "received_at": when,
                "received_by": received_by,
                "reference": _coerce(payload.get("reference"), str, ""),
                "late": when[:10] > po["expected"],
                "package_damaged": bool(payload.get("package_damaged")),
                "wrong_items": bool(payload.get("wrong_items")),
                "notes": _coerce(payload.get("notes"), str, ""),
                "closed_short": close_short,
                "lines": lines,
            }
            for line in lines:
                ing = self.ingredient(line["ingredient_id"])
                if ing and line["good"]:
                    ing["on_hand"] = round(ing["on_hand"] + line["good"] * self.usable_per_package(ing), 4)
                if ing and line.get("invoice_cost") is not None and abs(line["invoice_cost"] - ing["package_cost"]) > 1e-9:
                    before = dict(ing)
                    ing["package_cost"] = line["invoice_cost"]
                    self._record_price_change(before, ing, f"invoice on {po_id}")
            po.setdefault("receipts", []).append(receipt)
            short = any(l["good"] < l["expected"] for l in lines)
            if not short:
                po["status"] = "received"
            elif close_short:
                po["status"] = "received"
                po["short"] = True
            else:
                po["status"] = "partial"
            if po["status"] == "received":
                po["received"] = when[:10]
            return receipt

    def log_delay(self, po_id, note, new_expected=None):
        with self.lock:
            po = self.purchase_order(po_id)
            if po["status"] not in OPEN_PO_STATUSES:
                raise ValidationError(f"{po_id} is already {po['status']}")
            note = _coerce(note, str, "")
            if not note:
                raise ValidationError("Add a note about the delay")
            entry = {"at": datetime.now().isoformat(timespec="minutes"), "note": note, "previous_expected": po["expected"]}
            if new_expected:
                po["expected"] = _clean_date(new_expected)
            entry["expected"] = po["expected"]
            po.setdefault("delays", []).append(entry)
            return po

    def cancel_purchase_order(self, po_id):
        with self.lock:
            po = self.purchase_order(po_id)
            if po["status"] != "open":
                raise ValidationError("Only an order with nothing received yet can be cancelled")
            po["status"] = "cancelled"
            return po

    # ------------------------------------------------------------ schedule
    def upsert_employee(self, payload):
        with self.lock:
            clean = self._clean(payload, EMPLOYEE_FIELDS)
            if clean["hourly_rate"] < 0 or clean["max_hours"] < 0:
                raise ValidationError("Rate and max hours can't be negative")
            emp_id = payload.get("id")
            existing = self.employee(emp_id) if emp_id else None
            if not clean["color"]:
                clean["color"] = (existing or {}).get("color") or \
                    EMPLOYEE_COLORS[len(self.data["employees"]) % len(EMPLOYEE_COLORS)]
            if existing:
                existing.update(clean)
                return existing
            new = {"id": emp_id or _next_id("EMP", [e["id"] for e in self.data["employees"]]), **clean}
            self.data["employees"].append(new)
            return new

    def remove_employee(self, emp_id):
        """Take someone off the roster. Past shifts stay for labor history;
        their shifts from today on become open shifts to be filled."""
        with self.lock:
            emp = self.employee(emp_id)
            if not emp:
                raise ValidationError("Employee not found")
            emp["active"] = False
            today = date.today().isoformat()
            opened = 0
            for s in self.data["shifts"]:
                if s["employee_id"] == emp_id and s["date"] >= today:
                    s["employee_id"] = None
                    opened += 1
            return opened

    def upsert_shift(self, payload):
        with self.lock:
            emp_id = payload.get("employee_id") or None
            if emp_id and not self.employee(emp_id):
                raise ValidationError(f"Unknown employee '{emp_id}'")
            clean = {
                "employee_id": emp_id,
                "date": _clean_date(payload.get("date")),
                "start": _clean_time(payload.get("start"), "Start"),
                "end": _clean_time(payload.get("end"), "End"),
                "role": _coerce(payload.get("role"), str, ""),
                "notes": _coerce(payload.get("notes"), str, ""),
            }
            if clean["start"] == clean["end"]:
                raise ValidationError("Shift start and end can't be the same")
            shift_id = payload.get("id")
            existing = self.shift(shift_id) if shift_id else None
            if existing:
                existing.update(clean)
                return existing
            new = {"id": shift_id or _next_id("SH", [s["id"] for s in self.data["shifts"]]), **clean}
            self.data["shifts"].append(new)
            return new

    def delete_shift(self, shift_id):
        with self.lock:
            if not self.shift(shift_id):
                raise ValidationError("Shift not found")
            self.data["shifts"] = [s for s in self.data["shifts"] if s["id"] != shift_id]

    def copy_week(self, source_monday, target_monday):
        """Copy every shift of one week into another (people no longer on the roster become open shifts)."""
        with self.lock:
            src, dst = week_start(source_monday), week_start(target_monday)
            if src == dst:
                raise ValidationError("Pick a different week to copy from")
            copied = []
            for s in list(self.data["shifts"]):
                d = date.fromisoformat(s["date"])
                if src <= d < src + timedelta(days=7):
                    emp = self.employee(s["employee_id"]) if s["employee_id"] else None
                    copied.append(self.upsert_shift({
                        **{k: v for k, v in s.items() if k != "id"},
                        "employee_id": emp["id"] if emp and emp["active"] else None,
                        "date": (dst + (d - src)).isoformat(),
                    }))
            if not copied:
                raise ValidationError("That week has no shifts to copy")
            return copied

    def replace_catalog(self, ingredients, items):
        """Used by the Excel import: replace ingredients + menu, keep sales and POs."""
        with self.lock:
            backup = (self.data["ingredients"], self.data["items"])
            try:
                self.data["ingredients"], self.data["items"] = [], []
                for ing in ingredients:
                    self.upsert_ingredient(ing)
                for it in items:
                    self.upsert_item(it)
            except Exception:
                self.data["ingredients"], self.data["items"] = backup
                raise
            old = {i["id"]: i for i in backup[0]}
            for ing in self.data["ingredients"]:
                if ing["id"] in old:
                    self._record_price_change(old[ing["id"]], ing, "Excel import")

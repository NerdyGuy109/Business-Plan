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
DATA_DIR = os.path.join(ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "catalog.json")
IMAGE_DIR = os.path.join(DATA_DIR, "images")

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
    return {"ingredients": [], "items": [], "sales": [], "purchase_orders": [], "employees": [], "shifts": []}


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
    def unit_cost(ing):
        qty = ing.get("package_qty") or 0
        if qty <= 0:
            return 0.0
        return (ing.get("package_cost", 0) + ing.get("shipping_cost", 0)) / qty

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

    @staticmethod
    def suggested_packages(ing):
        """Packages to order: refill to par once stock hits the reorder point."""
        if ing["on_hand"] > ing["reorder_point"]:
            return 0
        pkg = ing["package_qty"] or 1
        need = max(ing["par_level"] - ing["on_hand"], 0)
        return max(ing.get("min_order_packages") or 1, math.ceil(need / pkg))

    def used_in(self, ing_id):
        return [
            {"id": it["id"], "name": it["name"], "qty": line["qty"]}
            for it in self.data["items"]
            for line in it.get("recipe", [])
            if line["ingredient_id"] == ing_id
        ]

    def on_order(self):
        qty = {}
        for po in self.data["purchase_orders"]:
            if po["status"] != "open":
                continue
            for line in po["lines"]:
                ing = self.ingredient(line["ingredient_id"])
                if ing:
                    qty[ing["id"]] = qty.get(ing["id"], 0) + line["packages"] * ing["package_qty"]
        return qty

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
                    "units_sold": sold,
                })
            revenue_by_date = {}
            for sale in self.data["sales"]:
                it = self.item(sale["item_id"])
                if it:
                    d = sale["date"][:10]
                    revenue_by_date[d] = revenue_by_date.get(d, 0) + it["price"] * sale["qty"]
            return {
                "ingredients": ingredients,
                "items": items,
                "employees": self.data["employees"],
                "shifts": [{**s, "hours": shift_hours(s)} for s in self.data["shifts"]],
                "revenue_by_date": revenue_by_date,
                "sales": self.data["sales"][-200:],
                "purchase_orders": self.data["purchase_orders"],
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

    def upsert_ingredient(self, payload):
        with self.lock:
            clean = self._clean(payload, INGREDIENT_FIELDS)
            if clean["package_qty"] <= 0:
                raise ValidationError("Quantity per package must be greater than 0")
            ing_id = payload.get("id")
            existing = self.ingredient(ing_id) if ing_id else None
            dup = next((i for i in self.data["ingredients"]
                        if i["name"].lower() == clean["name"].lower() and i is not existing), None)
            if dup:
                raise ValidationError(f"An ingredient named '{clean['name']}' already exists ({dup['id']})")
            if existing:
                existing.update(clean)
                return existing
            new = {"id": ing_id or _next_id("ING", [i["id"] for i in self.data["ingredients"]]), **clean}
            self.data["ingredients"].append(new)
            return new

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

    def record_sales(self, lines, when=None):
        """Sell menu items: logs the sale and deducts every ingredient in the recipe."""
        when = when or datetime.now().isoformat(timespec="seconds")
        with self.lock:
            for line in lines:
                item = self.item(line.get("item_id"))
                qty = _coerce(line.get("qty"), int, 0)
                if not item:
                    raise ValidationError(f"Unknown menu item '{line.get('item_id')}'")
                if qty <= 0:
                    continue
                for r in item["recipe"]:
                    ing = self.ingredient(r["ingredient_id"])
                    ing["on_hand"] = round(ing["on_hand"] - r["qty"] * qty, 4)
                self.data["sales"].append({"date": when, "item_id": item["id"], "qty": qty})

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

    def receive_purchase_order(self, po_id):
        with self.lock:
            po = next((p for p in self.data["purchase_orders"] if p["id"] == po_id), None)
            if not po or po["status"] != "open":
                raise ValidationError("Purchase order not found or already received")
            for line in po["lines"]:
                ing = self.ingredient(line["ingredient_id"])
                if ing:
                    ing["on_hand"] = round(ing["on_hand"] + line["packages"] * ing["package_qty"], 4)
            po["status"] = "received"
            po["received"] = date.today().isoformat()
            return po

    def cancel_purchase_order(self, po_id):
        with self.lock:
            po = next((p for p in self.data["purchase_orders"] if p["id"] == po_id), None)
            if not po or po["status"] != "open":
                raise ValidationError("Purchase order not found or not open")
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

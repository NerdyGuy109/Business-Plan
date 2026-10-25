"""Reset data/catalog.json to the sample juice bar (python -m app.seed) or to empty (--empty)."""

import random
from datetime import datetime, timedelta

from .excel import export_workbook
from .store import Store, empty_catalog

# name, category, unit, supplier, package desc, units/pkg, pkg cost, shipping, lead, shelf, min, on hand, reorder, par
INGREDIENTS = [
    ("Apple Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "1 gal jug", 128, 9.50, 1.20, 3, 21, 2, 1640, 1024, 3072),
    ("Orange Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "1 gal jug", 128, 11.25, 1.20, 3, 14, 2, 720, 1024, 3072),
    ("Pineapple Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "46 fl oz can", 46, 3.40, 0.40, 3, 180, 6, 880, 552, 1656),
    ("Coconut Water", "Juice Base", "fl oz", "Island Imports", "1 L carton x 12", 405.6, 38.00, 6.50, 7, 270, 1, 2400, 1600, 4800),
    ("Almond Milk", "Dairy & Alt", "fl oz", "Sysco", "64 fl oz carton x 6", 384, 21.00, 3.00, 4, 60, 1, 1200, 1000, 3072),
    ("Greek Yogurt", "Dairy & Alt", "oz", "Sysco", "32 oz tub x 6", 192, 27.00, 3.00, 4, 21, 1, 380, 480, 1536),
    ("Banana", "Fruit", "each", "GreenLeaf Produce", "40 lb case (~100 ct)", 100, 28.00, 4.00, 2, 6, 1, 256, 200, 800),
    ("Strawberries (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 42.00, 8.00, 5, 365, 1, 1640, 960, 3840),
    ("Mango (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 46.00, 8.00, 5, 365, 1, 600, 960, 3840),
    ("Peach (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 44.00, 8.00, 5, 365, 1, 2080, 960, 3840),
    ("Blueberries (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 58.00, 8.00, 5, 365, 1, 1560, 960, 3840),
    ("Pineapple Chunks", "Fruit", "oz", "GreenLeaf Produce", "10 lb case", 160, 22.00, 3.00, 2, 5, 1, 280, 256, 960),
    ("Lemon", "Fruit", "each", "GreenLeaf Produce", "Case of 115", 115, 36.00, 4.00, 2, 21, 1, 192, 120, 460),
    ("Spinach", "Greens", "oz", "GreenLeaf Produce", "4 lb case", 64, 14.00, 2.50, 2, 7, 1, 120, 128, 512),
    ("Kale", "Greens", "oz", "GreenLeaf Produce", "4 lb case", 64, 15.50, 2.50, 2, 7, 1, 280, 128, 512),
    ("Cucumber", "Greens", "each", "GreenLeaf Produce", "Case of 24", 24, 18.00, 2.50, 2, 10, 1, 80, 40, 192),
    ("Celery", "Greens", "oz", "GreenLeaf Produce", "30 lb case", 480, 32.00, 4.00, 2, 14, 1, 1200, 640, 1920),
    ("Carrot", "Vegetable", "oz", "GreenLeaf Produce", "25 lb bag", 400, 19.00, 3.00, 2, 28, 1, 1040, 640, 3200),
    ("Beet", "Vegetable", "oz", "GreenLeaf Produce", "25 lb bag", 400, 24.00, 3.00, 2, 28, 1, 840, 400, 1600),
    ("Ginger Root", "Vegetable", "oz", "GreenLeaf Produce", "5 lb box", 80, 22.00, 1.50, 2, 30, 1, 96, 64, 320),
    ("Turmeric Root", "Vegetable", "oz", "GreenLeaf Produce", "1 lb bag", 16, 8.50, 0.75, 2, 21, 2, 72, 32, 128),
    ("Mint", "Herbs", "oz", "GreenLeaf Produce", "1 lb bunch case", 16, 12.00, 1.00, 2, 7, 1, 36, 16, 64),
    ("Honey", "Sweetener", "oz", "Bee Happy Apiary", "5 lb jar", 80, 32.00, 5.00, 6, 730, 1, 240, 96, 640),
    ("Agave Syrup", "Sweetener", "fl oz", "Sysco", "46 fl oz bottle", 46, 11.00, 1.00, 4, 730, 2, 280, 120, 552),
    ("Whey Protein", "Boosts", "scoop", "NutriSource", "5 lb tub (~70 scoops)", 70, 54.00, 6.00, 7, 540, 1, 320, 160, 560),
    ("Chia Seeds", "Boosts", "tbsp", "NutriSource", "2 lb bag (~85 tbsp)", 85, 13.00, 2.00, 7, 540, 1, 240, 120, 680),
    ("Peanut Butter", "Boosts", "tbsp", "Sysco", "5 lb tub (~150 tbsp)", 150, 17.00, 2.00, 4, 180, 1, 480, 200, 1200),
    ("Acai Packs (frozen)", "Fruit", "each", "Island Imports", "Case of 48 x 100 g", 48, 62.00, 9.00, 10, 540, 1, 88, 120, 480),
    ("Ice", "Base", "oz", "In-house", "Ice machine (no cost)", 1000, 0.00, 0.00, 0, 0, 1, 5000, 0, 5000),
    ("16 oz Cup + Lid + Straw", "Packaging", "each", "EcoServe Packaging", "Case of 500", 500, 85.00, 12.00, 6, 0, 1, 1520, 1000, 4000),
    ("24 oz Cup + Lid + Straw", "Packaging", "each", "EcoServe Packaging", "Case of 400", 400, 92.00, 12.00, 6, 0, 1, 560, 800, 3200),
]

ITEMS = [
    ("Green Machine", "Cold-Pressed Juice", "16 oz", 8.95, "🥬",
     "Spinach, kale, cucumber, celery, apple and a squeeze of lemon. Our best-selling daily green.",
     [("Spinach", 2), ("Kale", 2), ("Cucumber", 1), ("Celery", 4), ("Apple Juice", 6), ("Lemon", 0.5),
      ("16 oz Cup + Lid + Straw", 1)]),
    ("Sunrise Carrot", "Cold-Pressed Juice", "16 oz", 7.95, "🥕",
     "Carrot, orange, ginger and turmeric. Bright, zesty and anti-inflammatory.",
     [("Carrot", 10), ("Orange Juice", 6), ("Ginger Root", 0.5), ("Turmeric Root", 0.25),
      ("16 oz Cup + Lid + Straw", 1)]),
    ("Beet Boost", "Cold-Pressed Juice", "16 oz", 8.50, "🫀",
     "Beet, carrot, apple, lemon and ginger. Earthy, sweet and energizing.",
     [("Beet", 6), ("Carrot", 4), ("Apple Juice", 5), ("Lemon", 0.5), ("Ginger Root", 0.5),
      ("16 oz Cup + Lid + Straw", 1)]),
    ("Ginger Shot", "Wellness Shot", "2 oz", 3.50, "🫚",
     "A fiery 2 oz shot of ginger, lemon and a touch of honey.",
     [("Ginger Root", 1), ("Lemon", 0.5), ("Honey", 0.25)]),
    ("Peach Paradise", "Smoothie", "24 oz", 8.95, "🍑",
     "Peach, mango, banana, Greek yogurt and apple juice blended creamy.",
     [("Peach (frozen)", 5), ("Mango (frozen)", 3), ("Banana", 1), ("Greek Yogurt", 4), ("Apple Juice", 6),
      ("Ice", 4), ("24 oz Cup + Lid + Straw", 1)]),
    ("Strawberry Banana", "Smoothie", "24 oz", 7.95, "🍓",
     "The classic: strawberries, banana, Greek yogurt, apple juice and honey.",
     [("Strawberries (frozen)", 6), ("Banana", 1), ("Greek Yogurt", 4), ("Apple Juice", 6), ("Honey", 0.5),
      ("Ice", 4), ("24 oz Cup + Lid + Straw", 1)]),
    ("Tropical Escape", "Smoothie", "24 oz", 8.50, "🍍",
     "Pineapple, mango, banana and coconut water. Dairy-free vacation in a cup.",
     [("Pineapple Chunks", 4), ("Mango (frozen)", 4), ("Banana", 1), ("Coconut Water", 8), ("Ice", 4),
      ("24 oz Cup + Lid + Straw", 1)]),
    ("Berry Blast", "Smoothie", "24 oz", 8.50, "🫐",
     "Blueberries, strawberries, banana, almond milk and chia seeds.",
     [("Blueberries (frozen)", 4), ("Strawberries (frozen)", 4), ("Banana", 1), ("Almond Milk", 8),
      ("Chia Seeds", 1), ("Ice", 3), ("24 oz Cup + Lid + Straw", 1)]),
    ("PB Power", "Protein Smoothie", "24 oz", 9.95, "🥜",
     "Peanut butter, banana, whey protein and almond milk. 30 g of protein.",
     [("Peanut Butter", 2), ("Banana", 1.5), ("Whey Protein", 1), ("Almond Milk", 10), ("Honey", 0.5),
      ("Ice", 4), ("24 oz Cup + Lid + Straw", 1)]),
    ("Green Protein", "Protein Smoothie", "24 oz", 10.50, "💪",
     "Spinach, banana, mango, whey protein and almond milk.",
     [("Spinach", 1.5), ("Banana", 1), ("Mango (frozen)", 3), ("Whey Protein", 1), ("Almond Milk", 10),
      ("Ice", 3), ("24 oz Cup + Lid + Straw", 1)]),
    ("Mint Lemonade", "Refresher", "16 oz", 5.50, "🍋",
     "Fresh lemon, mint and agave over ice.",
     [("Lemon", 1.5), ("Mint", 0.25), ("Agave Syrup", 1.5), ("Ice", 6), ("16 oz Cup + Lid + Straw", 1)]),
    ("Acai Energy", "Smoothie", "24 oz", 10.95, "🟣",
     "Acai, blueberries, banana, apple juice and honey.",
     [("Acai Packs (frozen)", 1), ("Blueberries (frozen)", 3), ("Banana", 1), ("Apple Juice", 8),
      ("Honey", 0.5), ("Ice", 3), ("24 oz Cup + Lid + Straw", 1)]),
]

# name, role, hourly rate, max hours / week
EMPLOYEES = [
    ("Maya Torres", "Manager", 24.00, 40),
    ("Jordan Lee", "Shift Lead", 19.50, 40),
    ("Sam Patel", "Juicer", 16.50, 40),
    ("Alex Kim", "Juicer", 16.00, 30),
    ("Riley Chen", "Juicer", 16.00, 30),
    ("Casey Brooks", "Cashier", 15.50, 28),
]

# Weekly pattern: employee index -> list of (weekday 0=Mon, start, end)
OPEN, MID, CLOSE = ("06:30", "14:30"), ("10:00", "16:00"), ("13:00", "20:00")
PATTERN = {
    0: [(d, *OPEN) for d in range(0, 5)],
    1: [(d, *CLOSE) for d in (0, 1, 2, 3, 4)],
    2: [(d, *OPEN) for d in (0, 1, 4, 5)] + [(6, *CLOSE)],
    3: [(d, *CLOSE) for d in (2, 5, 6)] + [(d, *OPEN) for d in (3, 4)],
    4: [(d, *MID) for d in (4, 6)] + [(5, *OPEN)],
    5: [(d, *MID) for d in (0, 1, 3)] + [(6, *OPEN)],
}

ALLERGENS = {"Almond Milk": ["tree nuts"], "Greek Yogurt": ["milk"], "Whey Protein": ["milk"],
             "Peanut Butter": ["peanuts"]}

# Usable share after trimming / peeling (whole produce bought by weight).
YIELDS = {"Ginger Root": 85, "Turmeric Root": 85, "Celery": 80, "Carrot": 85, "Beet": 80, "Kale": 75, "Mint": 70}

FIELDS = ["name", "category", "unit", "supplier", "package_desc", "package_qty", "package_cost",
          "shipping_cost", "lead_time_days", "shelf_life_days", "min_order_packages", "on_hand",
          "reorder_point", "par_level"]


def build(store: Store, with_sales=True):
    store.data = empty_catalog()
    ids = {}
    for n, row in enumerate(INGREDIENTS, start=1):
        payload = dict(zip(FIELDS, row))
        payload["supplier_sku"] = f"SKU-{1000 + n * 7}"
        payload["allergens"] = ALLERGENS.get(payload["name"], [])
        payload["yield_pct"] = YIELDS.get(payload["name"], 100)
        ids[payload["name"]] = store.upsert_ingredient(payload)["id"]
    for name, cat, size, price, emoji, desc, recipe in ITEMS:
        store.upsert_item({
            "name": name, "category": cat, "size": size, "price": price, "emoji": emoji,
            "description": desc, "active": True,
            "recipe": [{"ingredient_id": ids[i], "qty": q} for i, q in recipe],
        })
    for name, role, rate, max_hours in EMPLOYEES:
        store.upsert_employee({"name": name, "role": role, "hourly_rate": rate, "max_hours": max_hours})
    this_monday = datetime.now().date() - timedelta(days=datetime.now().weekday())
    for monday in (this_monday - timedelta(days=7), this_monday):
        for idx, shifts in PATTERN.items():
            emp = store.data["employees"][idx]
            for day, start, end in shifts:
                store.upsert_shift({"employee_id": emp["id"], "date": (monday + timedelta(days=day)).isoformat(),
                                    "start": start, "end": end, "role": emp["role"]})
    # One gap the manager still needs to fill.
    store.upsert_shift({"employee_id": None, "date": (this_monday + timedelta(days=5)).isoformat(),
                        "start": "13:00", "end": "20:00", "role": "Juicer", "notes": "Saturday close"})
    if with_sales:
        # Two weeks of sales history, without consuming the seeded stock levels.
        rng = random.Random(42)
        start_stock = {i["id"]: i["on_hand"] for i in store.data["ingredients"]}
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        for day in range(14, 0, -1):
            for item in store.data["items"]:
                qty = rng.randint(12, 30)  # ~250 drinks a day across the menu
                when = (now - timedelta(days=day)).replace(hour=rng.randint(8, 18))
                store.record_sales([{"item_id": item["id"], "qty": qty}], when.isoformat())
        store.data["sales"].sort(key=lambda s: s["date"])
        for ing in store.data["ingredients"]:
            ing["on_hand"] = start_stock[ing["id"]]
    _purchase_orders(store, ids)


def _purchase_orders(store, ids):
    """Recent orders in every receiving state, without changing the seeded stock levels."""
    stock = {i["id"]: i["on_hand"] for i in store.data["ingredients"]}
    today = datetime.now().date()
    day = lambda n: (today + timedelta(days=n)).isoformat()
    emp = {e["name"].split()[0]: e["id"] for e in store.data["employees"]}

    def order(supplier, lines, created, expected):
        po = store.create_purchase_order(supplier, [{"ingredient_id": ids[n], "packages": q} for n, q in lines])
        po["created"], po["expected"] = day(created), day(expected)
        return po

    # On time, everything in good shape.
    po = order("GreenLeaf Produce", [("Spinach", 6), ("Banana", 2)], -9, -7)
    store.receive_purchase_order(po["id"], {
        "received_at": f"{day(-7)}T08:15", "received_by": emp["Jordan"], "reference": "INV-44817",
        "lines": [{"ingredient_id": ids["Spinach"], "good": 6, "invoice_cost": 15.25},
                  {"ingredient_id": ids["Banana"], "good": 2}]})
    store.data["price_changes"][-1]["at"] = f"{day(-7)}T08:15"
    # A day late, one case crushed: the damaged case is still owed.
    po = order("Frosty Farms", [("Strawberries (frozen)", 4), ("Peach (frozen)", 3)], -8, -3)
    store.receive_purchase_order(po["id"], {
        "received_at": f"{day(-2)}T09:40", "received_by": emp["Maya"], "reference": "FF-209331",
        "package_damaged": True, "notes": "Outer box crushed on one side. Driver signed the damage note.",
        "lines": [{"ingredient_id": ids["Strawberries (frozen)"], "good": 4},
                  {"ingredient_id": ids["Peach (frozen)"], "good": 2, "damaged": 1,
                   "note": "Bags split, thawed. Photo taken; supplier to credit or resend."}]})
    # Due today.
    order("Sysco", [("Greek Yogurt", 7), ("Almond Milk", 2)], -4, 0)
    # Overdue, with the supplier's new date logged.
    po = order("Island Imports", [("Acai Packs (frozen)", 9)], -12, -2)
    store.log_delay(po["id"], "Supplier called: container held at the port. New delivery date given.", day(2))
    po["delays"][-1]["at"] = f"{day(-1)}T14:05"

    for ing in store.data["ingredients"]:
        ing["on_hand"] = stock[ing["id"]]

    # A weekly count of the expensive items, and this week's waste.
    stock = {i["id"]: i["on_hand"] for i in store.data["ingredients"]}
    shortfall = {"Strawberries (frozen)": 150, "Whey Protein": 29, "Peanut Butter": 14, "Mango (frozen)": 45,
                 "Acai Packs (frozen)": 0, "Greek Yogurt": 60}
    store.record_count({
        "at": f"{day(-3)}T20:30", "counted_by": emp["Maya"], "notes": "Weekly count of high-value items",
        "lines": [{"ingredient_id": ids[n], "counted": stock[ids[n]] - short} for n, short in shortfall.items()]})
    monday = today - timedelta(days=today.weekday())
    for offset, hour, payload in [
        (0, "08:10", {"kind": "ingredient", "ingredient_id": ids["Spinach"], "qty": 24, "reason": "expired / spoiled",
                      "note": "Slimy bag at the back of the walk-in", "by": emp["Jordan"]}),
        (1, "12:45", {"kind": "item", "item_id": store.data["items"][4]["id"], "qty": 2, "reason": "remade drink",
                      "note": "Wrong milk used", "by": emp["Sam"]}),
        (2, "15:20", {"kind": "item", "item_id": store.data["items"][8]["id"], "qty": 1, "reason": "spilled / dropped",
                      "by": emp["Alex"]}),
        (3, "09:05", {"kind": "ingredient", "ingredient_id": ids["Banana"], "qty": 9, "reason": "expired / spoiled",
                      "note": "Too ripe", "by": emp["Maya"]}),
        (4, "17:30", {"kind": "item", "item_id": store.data["items"][0]["id"], "qty": 3, "reason": "staff drink",
                      "by": emp["Jordan"]}),
        (5, "11:00", {"kind": "item", "item_id": store.data["items"][3]["id"], "qty": 4, "reason": "free / comped drink",
                      "note": "Sampling at the door", "by": emp["Riley"]}),
    ]:
        when = monday + timedelta(days=offset)
        if when <= today:
            store.record_waste({**payload, "at": f"{when.isoformat()}T{hour}"})
    for ing in store.data["ingredients"]:
        ing["on_hand"] = stock[ing["id"]]

    # A supplier price rise entered by hand.
    kale = store.ingredient(ids["Kale"])
    store.upsert_ingredient({**kale, "package_cost": 18.00})
    store.data["price_changes"][-1]["at"] = f"{day(-4)}T16:20"


if __name__ == "__main__":
    import sys

    s = Store()
    if "--empty" in sys.argv:
        s.data = empty_catalog()
        print("Cleared the catalog")
    else:
        build(s)
        print("Seeded", len(s.data["ingredients"]), "ingredients and", len(s.data["items"]), "menu items")
    s.save()
    print("Wrote", export_workbook(s))

"""Reset data/catalog.json to the sample juice bar (python -m app.seed) or to empty (--empty)."""

import random
from datetime import datetime, timedelta

from .excel import export_workbook
from .store import Store, empty_catalog

# name, category, unit, supplier, package desc, units/pkg, pkg cost, shipping, lead, shelf, min, on hand, reorder, par
INGREDIENTS = [
    ("Apple Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "1 gal jug", 128, 9.50, 1.20, 3, 21, 2, 410, 256, 768),
    ("Orange Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "1 gal jug", 128, 11.25, 1.20, 3, 14, 2, 180, 256, 768),
    ("Pineapple Juice", "Juice Base", "fl oz", "Valley Fresh Juices", "46 fl oz can", 46, 3.40, 0.40, 3, 180, 6, 220, 138, 414),
    ("Coconut Water", "Juice Base", "fl oz", "Island Imports", "1 L carton x 12", 405.6, 38.00, 6.50, 7, 270, 1, 600, 400, 1200),
    ("Almond Milk", "Dairy & Alt", "fl oz", "Sysco", "64 fl oz carton x 6", 384, 21.00, 3.00, 4, 60, 1, 300, 250, 768),
    ("Greek Yogurt", "Dairy & Alt", "oz", "Sysco", "32 oz tub x 6", 192, 27.00, 3.00, 4, 21, 1, 95, 120, 384),
    ("Banana", "Fruit", "each", "GreenLeaf Produce", "40 lb case (~100 ct)", 100, 28.00, 4.00, 2, 6, 1, 64, 50, 200),
    ("Strawberries (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 42.00, 8.00, 5, 365, 1, 410, 240, 960),
    ("Mango (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 46.00, 8.00, 5, 365, 1, 150, 240, 960),
    ("Peach (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 44.00, 8.00, 5, 365, 1, 520, 240, 960),
    ("Blueberries (frozen)", "Fruit", "oz", "Frosty Farms", "5 lb bag x 4", 320, 58.00, 8.00, 5, 365, 1, 390, 240, 960),
    ("Pineapple Chunks", "Fruit", "oz", "GreenLeaf Produce", "10 lb case", 160, 22.00, 3.00, 2, 5, 1, 70, 64, 240),
    ("Lemon", "Fruit", "each", "GreenLeaf Produce", "Case of 115", 115, 36.00, 4.00, 2, 21, 1, 48, 30, 115),
    ("Spinach", "Greens", "oz", "GreenLeaf Produce", "4 lb case", 64, 14.00, 2.50, 2, 7, 1, 30, 32, 128),
    ("Kale", "Greens", "oz", "GreenLeaf Produce", "4 lb case", 64, 15.50, 2.50, 2, 7, 1, 70, 32, 128),
    ("Cucumber", "Greens", "each", "GreenLeaf Produce", "Case of 24", 24, 18.00, 2.50, 2, 10, 1, 20, 10, 48),
    ("Celery", "Greens", "oz", "GreenLeaf Produce", "30 lb case", 480, 32.00, 4.00, 2, 14, 1, 300, 160, 480),
    ("Carrot", "Vegetable", "oz", "GreenLeaf Produce", "25 lb bag", 400, 19.00, 3.00, 2, 28, 1, 260, 160, 800),
    ("Beet", "Vegetable", "oz", "GreenLeaf Produce", "25 lb bag", 400, 24.00, 3.00, 2, 28, 1, 210, 100, 400),
    ("Ginger Root", "Vegetable", "oz", "GreenLeaf Produce", "5 lb box", 80, 22.00, 1.50, 2, 30, 1, 24, 16, 80),
    ("Turmeric Root", "Vegetable", "oz", "GreenLeaf Produce", "1 lb bag", 16, 8.50, 0.75, 2, 21, 2, 18, 8, 32),
    ("Mint", "Herbs", "oz", "GreenLeaf Produce", "1 lb bunch case", 16, 12.00, 1.00, 2, 7, 1, 9, 4, 16),
    ("Honey", "Sweetener", "oz", "Bee Happy Apiary", "5 lb jar", 80, 32.00, 5.00, 6, 730, 1, 60, 24, 160),
    ("Agave Syrup", "Sweetener", "fl oz", "Sysco", "46 fl oz bottle", 46, 11.00, 1.00, 4, 730, 2, 70, 30, 138),
    ("Whey Protein", "Boosts", "scoop", "NutriSource", "5 lb tub (~70 scoops)", 70, 54.00, 6.00, 7, 540, 1, 80, 40, 140),
    ("Chia Seeds", "Boosts", "tbsp", "NutriSource", "2 lb bag (~85 tbsp)", 85, 13.00, 2.00, 7, 540, 1, 60, 30, 170),
    ("Peanut Butter", "Boosts", "tbsp", "Sysco", "5 lb tub (~150 tbsp)", 150, 17.00, 2.00, 4, 180, 1, 120, 50, 300),
    ("Acai Packs (frozen)", "Fruit", "each", "Island Imports", "Case of 48 x 100 g", 48, 62.00, 9.00, 10, 540, 1, 22, 30, 120),
    ("Ice", "Base", "oz", "In-house", "Ice machine (no cost)", 1000, 0.00, 0.00, 0, 0, 1, 5000, 0, 5000),
    ("16 oz Cup + Lid + Straw", "Packaging", "each", "EcoServe Packaging", "Case of 500", 500, 85.00, 12.00, 6, 0, 1, 380, 250, 1000),
    ("24 oz Cup + Lid + Straw", "Packaging", "each", "EcoServe Packaging", "Case of 400", 400, 92.00, 12.00, 6, 0, 1, 140, 200, 800),
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

FIELDS = ["name", "category", "unit", "supplier", "package_desc", "package_qty", "package_cost",
          "shipping_cost", "lead_time_days", "shelf_life_days", "min_order_packages", "on_hand",
          "reorder_point", "par_level"]


def build(store: Store, with_sales=True):
    store.data = empty_catalog()
    ids = {}
    for n, row in enumerate(INGREDIENTS, start=1):
        payload = dict(zip(FIELDS, row))
        payload["supplier_sku"] = f"SKU-{1000 + n * 7}"
        ids[payload["name"]] = store.upsert_ingredient(payload)["id"]
    for name, cat, size, price, emoji, desc, recipe in ITEMS:
        store.upsert_item({
            "name": name, "category": cat, "size": size, "price": price, "emoji": emoji,
            "description": desc, "active": True,
            "recipe": [{"ingredient_id": ids[i], "qty": q} for i, q in recipe],
        })
    if with_sales:
        # Two weeks of sales history, without consuming the seeded stock levels.
        rng = random.Random(42)
        start_stock = {i["id"]: i["on_hand"] for i in store.data["ingredients"]}
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        for day in range(14, 0, -1):
            for item in store.data["items"]:
                qty = rng.randint(1, 9)
                when = (now - timedelta(days=day)).replace(hour=rng.randint(8, 18))
                store.record_sales([{"item_id": item["id"], "qty": qty}], when.isoformat())
        store.data["sales"].sort(key=lambda s: s["date"])
        for ing in store.data["ingredients"]:
            ing["on_hand"] = start_stock[ing["id"]]


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

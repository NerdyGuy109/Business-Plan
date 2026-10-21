# Menu & Parts Inventory

Tools for a business whose products are built from smaller parts, so that every sale
tells you which parts were used and what needs to be bought again. The sample data is a
**juice bar**: menu items (smoothies, juices, shots) are made from ingredients (apple juice,
spinach, banana, ginger, yogurt, cups...).

```
 Ingredients (parts)  ──recipe──▶  Menu items  ──sold──▶  Ingredients used  ──▶  Reorder list  ──▶  Purchase order
 cost, pack size,                  price, picture,         (stock goes down)       (per supplier)       (received = stock up)
 lead time, shelf life             description
```

It has two parts that stay in sync:

| | What it's for |
|---|---|
| **Website** (`app/`) | Add and edit menu items with a picture and description, build recipes by clicking ingredients, maintain ingredient purchasing info, record sales, create and receive purchase orders. |
| **Excel workbook** (`exports/inventory.xlsx`) | The same data as a spreadsheet with live formulas, for analysis, sharing, or bulk edits. Rewritten automatically after every change on the website; edits made in Excel can be imported back. |

## Quick start

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python -m app.server            # then open http://localhost:8000
```

Or double-click `start.sh` (Mac/Linux) / `start.bat` (Windows).

The first run loads the sample juice bar. To reset to the sample data run
`python -m app.seed`; to start your own catalog from scratch run `python -m app.seed --empty`.
Both overwrite `data/catalog.json`.

## The website

| Tab | What you do there |
|---|---|
| **Dashboard** | What needs reordering (and whether it will run out before a delivery could arrive), and how many of each menu item current stock can make, with the limiting ingredient. |
| **Menu** | Cards for each item with picture, price, ingredients, cost, margin and food-cost %. Click a card to edit. |
| **Menu item builder** | Drop in a picture, fill in name/price/description, then click ingredients to add them (click again for more, or type a name and press Enter). Adjust quantities with − / +. Cost, margin, cost % and "can make now" update live, with suggested prices for 25% and 30% food cost. *Duplicate as new* makes variations fast (e.g. a large size or a protein version). Missing an ingredient? *+ New ingredient* creates it and drops it into the recipe. |
| **Ingredients** | All parts with package, cost, landed unit cost, lead time, shelf life, stock, reorder point / par level, recent daily usage and which items use them. Click a row to edit. Deleting is blocked while an ingredient is still in a recipe. |
| **Record Sales** | Tap items onto a ticket and record the sale. Every ingredient in each recipe is deducted from stock. |
| **Procurement** | Ingredients at or below their reorder point, grouped by supplier, with suggested package counts (editable). *Create purchase order* → *Mark received* when it arrives adds the stock. |
| **Excel** | Download the workbook, or import an edited one. |

### Ingredient purchasing fields

| Field | Meaning |
|---|---|
| Recipe unit | The unit recipes and stock use (oz, fl oz, g, each, scoop...). |
| Package description / Qty in package | How it's bought, e.g. "1 gal jug" = 128 fl oz. |
| Package cost, Shipping per package | Landed unit cost = (package cost + shipping) ÷ qty in package. |
| Lead time, Shelf life | Days from order to delivery; days it stays usable. |
| Min order | Minimum packages the supplier will sell. |
| On hand, Reorder point, Par level | When on hand ≤ reorder point, order enough packages to get back to par. The editor suggests a reorder point from recent usage × lead time × 1.5. |

## The Excel workbook

| Sheet | Contents |
|---|---|
| Guide | How the workbook works and the colour legend. |
| Ingredients | Master parts list with purchasing info. Formulas: landed unit cost, # items using it, units used per the sales log, REORDER/OK status, suggested packages, order cost, stock value. |
| Menu Items | Price, description, image file name. Formulas: ingredient cost, gross margin, cost %, units sold, revenue. |
| Recipes | The item ↔ ingredient associations: one row per ingredient per item with quantity. Names, units and costs are looked up by formula. |
| Where Used | Matrix of every ingredient × every menu item showing the quantity used. |
| Procurement | Every ingredient grouped by supplier, REORDER rows highlighted, order totals and expected arrival dates. |
| Purchase Orders, Sales Log | History from the website. |

Blue header/text = input you can edit; dark green header = formula. To link an ingredient to
an item in Excel, add a row to **Recipes** with the Item ID, Ingredient ID (or exact
ingredient name) and quantity. New ingredients added in Excel without an ID get one on import.

**Bringing Excel edits back:** on the website's Excel tab, upload the workbook (or click
*Re-read exports/inventory.xlsx* if you edited that file in place). The import reads only the
input columns of Ingredients, Menu Items and Recipes, validates every reference, and leaves
sales and purchase orders alone. Close the file in Excel before making more changes on the
website, otherwise the website can't rewrite it (you'll get a warning).

From the command line: `python -m app.excel` (export) or `python -m app.excel import path.xlsx`.

## Files

```
app/server.py     web server + JSON API (Python standard library)
app/store.py      data model and business rules (costing, reorder, sales, POs)
app/excel.py      Excel export/import
app/seed.py       sample juice bar data
app/static/       website (HTML/CSS/JS, no build step)
data/catalog.json the data (source of truth) — back this up
data/images/      uploaded item pictures
exports/inventory.xlsx  generated workbook
```

The server listens on `127.0.0.1` only. It has no login, so if you expose it to other
devices (`--host 0.0.0.0`) do it only on a trusted network.

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
| **Website** (`app/`) | Add and edit menu items with a picture and description, build recipes by clicking ingredients, maintain ingredient purchasing info, import sales from the till system, receive deliveries, count stock and log waste, schedule staff, and track allergens and price changes. Everyone signs in with their own account. |
| **Excel workbook** (`exports/inventory.xlsx`) | The same data as a spreadsheet with live formulas, for analysis, sharing, or bulk edits. Rewritten automatically after every change on the website; edits made in Excel can be imported back. |

## Quick start

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python -m app.server            # then open http://localhost:8000
```

Or double-click `start.sh` (Mac/Linux) / `start.bat` (Windows).

**The first time you open it, it asks you to create the owner account** (name, username, password).
The owner adds managers and staff on the Settings tab. Forgot the owner password? Stop the app and run
`python -m app.auth password <username>`.

The first run loads the sample juice bar. To reset to the sample data run
`python -m app.seed`; to start your own catalog from scratch run `python -m app.seed --empty`
(or start the server with `--empty` on a brand-new install). Both overwrite `data/catalog.json`.

To use it from tablets or phones on the shop Wi-Fi, or to host it online with HTTPS, see
[docs/HOSTING.md](docs/HOSTING.md).

**Your data is not stored in git.** `data/` (catalog, users, pictures, backups) and `exports/` are
ignored, because they hold sales, pay rates and password hashes. Back them up with the Settings →
Backups download. If you are updating from an older copy of this project, copy your old `data/`
folder into the new one before starting it.

## The website

| Tab | What you do there |
|---|---|
| **Dashboard** | What needs reordering (and whether it will run out before a delivery could arrive), and how many of each menu item current stock can make, with the limiting ingredient. |
| **Menu** | Cards for each item with picture, price, ingredients, cost, margin and food-cost %. Click a card to edit. |
| **Menu item builder** | Drop in a picture, fill in name/price/description, then click ingredients to add them (click again for more, or type a name and press Enter). Adjust quantities with − / +. Cost, margin, cost % and "can make now" update live, with suggested prices for 25% and 30% food cost. *Duplicate as new* makes variations fast (e.g. a large size or a protein version). Missing an ingredient? *+ New ingredient* creates it and drops it into the recipe. |
| **Ingredients** | All parts with package, cost, landed unit cost, lead time, shelf life, stock, reorder point / par level, recent daily usage and which items use them. Click a row to edit. Deleting is blocked while an ingredient is still in a recipe. |
| **Record Sales** | Tap items onto a ticket and record the sale. Every ingredient in each recipe is deducted from stock. Each drink button shows its allergens. |
| **Import sales** (on Record Sales) | Load the item-sales CSV export from Square, Toast, Clover or similar. Columns (date, time, item, size, quantity, refund type) are detected automatically and can be changed. Names are matched to menu items by name or by a match you chose before; anything that isn't a drink (gift cards) can be ignored. Refunds are skipped, the same file can't be loaded twice by accident, and any import can be undone, which puts its ingredients back in stock. A sample export is in `docs/samples/`. |
| **Procurement** | Ingredients at or below their reorder point, grouped by supplier, with suggested package counts (editable). *Create purchase order*; *Receive…* opens it on the Receiving tab. |
| **Receiving** | Check in a delivery: pick the order (overdue and due-today orders are flagged), choose who received it, confirm the date/time and tracking or invoice number, then tick each item that arrived in good condition or enter how many arrived OK and how many were damaged, with a note. Flag damaged outer packaging or wrong items and add delivery notes. Submitting adds the good packages to stock; missing or damaged items stay on order (the order shows as *partly received*) unless you tick "nothing else is coming" to close it short. *Log a delay* records what the supplier said and a new expected date. Every delivery appears in the receiving log. |
| **Schedule** | Weekly staff schedule. Drag a shift to move it to another person or day (hold Ctrl/Alt to copy), click an empty spot to add one, click a name to edit that employee. Shows hours vs. each person's max, labor cost, sales and labor % per day, open shifts and double-bookings. *Copy last week* starts a new week from the previous one. Removing an employee keeps their past shifts for labor history and turns their upcoming shifts into open shifts. |
| **Counts & Waste** | **Stock count:** enter what's really on the shelf; on-hand becomes the count and the variance report shows each difference in units, dollars and as a share of what sales and waste say was used since the last count (over-portioning, unlogged waste, mistakes or theft). **Waste log:** record ingredients or whole drinks thrown away, spilled, remade, drunk by staff or given away, with reason and cost; this week's waste is totalled by reason. |
| **Excel** | Download the workbook, or import an edited one. |
| **Settings** | Business name and target food cost (drinks above it are flagged). Owners also manage users and download backups; everyone can change their own password. |

The **Dashboard** also lists ingredient **cost changes** from the last 30 days, whether entered by hand,
taken from an invoice price while receiving, or imported from Excel, with what each did to the food cost
of the drinks that use it, and which drinks are above the target.

### Who can do what

| Role | Can |
|---|---|
| Staff | Record sales, receive deliveries, count stock, log waste, view the menu (with allergens) and the schedule. They don't see other people's pay rates. |
| Manager | Everything day to day: menu, ingredients, ordering, schedule, sales imports, Excel |
| Owner | Also managers' and owners' accounts, business settings and backups |

Managers can add staff accounts and reset a staff member's forgotten password. Any password set by someone else
is temporary: the person is asked to choose their own the next time they sign in.

### Ingredient purchasing fields

| Field | Meaning |
|---|---|
| Recipe unit | The unit recipes and stock use (oz, fl oz, g, each, scoop...). |
| Package description / Qty in package | How it's bought, e.g. "1 gal jug" = 128 fl oz. |
| Package cost, Shipping per package | Landed unit cost = (package cost + shipping) ÷ usable qty per package. |
| Usable yield % | Share of a package you can actually use after peeling, trimming or coring (100 = no waste). Cost, receiving and reorder quantities use the usable amount. |
| Allergens | Which of the nine major allergens (milk, eggs, fish, shellfish, tree nuts, peanuts, wheat, soy, sesame) the ingredient contains. Menu items list every allergen in their recipe. Cross-contact from shared blenders is not tracked. |
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
| Price Changes | Every ingredient cost change and its effect on each drink's food cost. |
| Stock Counts | Each count line: expected, counted, variance in units and dollars, and as a share of usage. |
| Waste Log | Everything logged as wasted, with reason and cost. |
| Purchase Orders | Each order line with packages ordered, received OK, damaged and still outstanding. |
| Receiving Log | Every delivery checked in: when, who, tracking/invoice #, late, damage, shortages and notes. |
| Sales Log | Sales recorded on the website. |
| Staff | Employees with role, hourly rate and max hours per week. |
| Schedule | One row per shift: date, employee (OPEN if unassigned), start/end, hours and labor cost. |
| Weekly Hours | Hours per employee per day for one week, with totals, labor cost and over-max flags. Change the Monday date in B1 to view another week. |

Blue header/text = input you can edit; dark green header = formula. To link an ingredient to
an item in Excel, add a row to **Recipes** with the Item ID, Ingredient ID (or exact
ingredient name) and quantity. New ingredients added in Excel without an ID get one on import.

**Bringing Excel edits back:** on the website's Excel tab, upload the workbook (or click
*Re-read exports/inventory.xlsx* if you edited that file in place). The import reads only the
input columns of Ingredients, Menu Items and Recipes, validates every reference, and leaves
sales, purchase orders, staff and the schedule alone (manage the schedule on the website). Close the file in Excel before making more changes on the
website, otherwise the website can't rewrite it (you'll get a warning).

From the command line: `python -m app.excel` (export) or `python -m app.excel import path.xlsx`.

## Files

```
app/server.py      web server + JSON API (Python standard library), sign-in and role checks
app/store.py       data model and business rules (costing, yield, reorder, sales, receiving, counts, waste)
app/pos_import.py  till-system CSV import
app/auth.py        users, passwords, sessions, roles
app/backup.py      automatic daily backups, full-backup zip, restore
app/excel.py       Excel export/import
app/seed.py        sample juice bar data
app/static/        website (HTML/CSS/JS, no build step)
data/              the live data: catalog.json, users.json, images/, backups/  (not in git)
exports/           the generated inventory.xlsx  (not in git)
docs/HOSTING.md    running it for a real shop: shop Wi-Fi, cloud server, backups, security
deploy/            Docker Compose + Caddy (automatic HTTPS): one shop, or deploy/multi/ for a demo plus many shops
docs/samples/      a sample till export and a sample workbook
tests/             automated tests
```

The server listens on `127.0.0.1` (this computer only) unless started with `--host 0.0.0.0`.

## Training materials

In `docs/manuals/`, ready to print (Letter):

| File | For |
|---|---|
| `Staff-Guide.pdf` | Everyone: signing in, first and forgotten passwords, sales, allergens, receiving, counting, waste, schedule, signing out. Ends with a one-page quick reference to post by the counter. |
| `Manager-Guide.pdf` | Managers: helping staff with accounts, questions staff ask, the daily and weekly routines, menu and ingredients, Excel, training new staff. Ends with a checklist. |
| `Staff-Knowledge-Check.pdf` | 12 multiple-choice questions, pass mark 10. Answer key on the last page. |
| `Manager-Knowledge-Check.pdf` | 15 questions, pass mark 13. Answer key on the last page. |

The guides are HTML (`staff-guide.html`, `manager-guide.html`, shared `manual.css`); the quizzes are generated from
`make_quiz.py` so the questions and the answer key always match. Edit them, then print to PDF from Chrome
(Letter, default margins, background graphics on).

## Launch plan

`docs/launch/Launch-Plan.pdf` is the founder's plan for going from here to paying customers: business basics,
one domain with a subdomain per shop (`deploy/multi/` runs a demo shop plus one install per customer on one
server, with a nightly demo reset), testing it like a customer, a pilot shop, pricing and paperwork, the sales kit
(demo script, objections) and recruiting and training a salesperson, ending with a checklist.

## Sales materials

`docs/brochure/Menu-Inventory-Brochure.pdf` is a two-page leave-behind (front: the pitch; back: the ten
main features, each with a screenshot). Fill in the contact placeholders in `docs/brochure/brochure.html` and re-render it by
opening that file in Chrome and choosing Print → Save as PDF (Letter, margins none, background graphics on).

## Tests

```bash
python -m unittest discover tests
```
29 automated checks cover costing, yields, allergens, price-change tracking, sales, receiving, counts, waste,
the POS import, scheduling, the Excel round trip, passwords and lockout, and the web server's role and CSRF
rules. They run against a throwaway folder and never touch your data.

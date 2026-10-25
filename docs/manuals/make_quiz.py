"""Builds the staff and manager knowledge checks (HTML, then printed to PDF).

Questions live here so the quiz and its answer key can never disagree.
Run: python docs/manuals/make_quiz.py   (writes staff-quiz.html and manager-quiz.html next to this file)
"""
import html
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# (scenario or "", question, [A, B, C, D], correct letter, why + where in the guide)
STAFF = [
    ("", "You sign in for the first time with the temporary password your manager gave you. What happens next?",
     ["You go straight to Record Sales", "The app asks you to choose your own password before you can do anything else",
      "You have to wait 5 minutes", "Your manager has to approve you first"],
     "B", "A temporary password must be replaced at first sign-in. (Staff guide 2)"),
    ("", "You've forgotten your password. What should you do?",
     ["Sign in with a co-worker's account", "Keep trying until it works",
      "Ask a manager to set a temporary password, then choose your own when you sign in", "Create a new account"],
     "C", "Managers reset staff passwords; you then choose your own. Never use someone else's account. (Staff guide 3)"),
    ("", "After 5 wrong passwords the app says “Too many attempts.” What does that mean?",
     ["Your account is deleted", "Wait 5 minutes before trying that username again",
      "You must use a different tablet forever", "Your manager has been emailed"],
     "B", "5 wrong tries lock that username for 5 minutes. (Staff guide 1, 12)"),
    ("A customer with a nut allergy asks if PB Power is OK for them.", "What do you do?",
     ["Say it's fine, it's a smoothie", "Check the ⚠ Contains line on the Menu: it contains tree nuts and peanuts. Tell them, and follow the shop's allergy procedure",
      "Say it's allergen-free if you leave out the peanut butter", "Look it up in Excel"],
     "B", "The Contains line lists allergens from the recipe; the app can't account for shared blenders, so never promise allergen-free. (Staff guide 6)"),
    ("Your shop imports every day's sales from the till system.", "Should you also ring drinks up on Record Sales?",
     ["Yes, always", "Only for smoothies", "No: every drink would be counted twice and stock would go wrong", "Only on weekends"],
     "C", "If sales are imported, ringing them up too counts each drink twice. (Staff guide 5)"),
    ("7 tubs of yogurt were ordered. 6 arrive in good shape and 1 is leaking.", "How do you record it?",
     ["Tick All OK", "Received OK 6, Damaged 1, with a note like “tub leaking”", "Received OK 7", "Don't record it until the supplier replaces the tub"],
     "B", "Damaged items are recorded as Damaged, not OK, so they aren't added to stock. (Staff guide 7)"),
    ("2 cases of almond milk were ordered; only 1 arrives. The supplier says the other comes tomorrow.", "What do you do?",
     ["Enter 1 received OK and submit; leave “Nothing else is coming” unticked so the other case stays on order",
      "Enter 2 received OK", "Tick “Nothing else is coming — close this order short”", "Wait until tomorrow to record anything"],
     "A", "Missing items stay on order and can be checked in when they arrive. (Staff guide 7)"),
    ("A supplier calls: today's delivery is coming two days late.", "Where do you record this?",
     ["Nowhere", "In Delivery notes on a receipt", "Open the order on Receiving → “Delivery delayed? Log it”, with a note and the new date",
      "Counts & Waste"],
     "C", "Log a delay records what happened and moves the expected date. (Staff guide 7)"),
    ("You're counting frozen strawberries. The line says “1 pkg = 320 oz”. There are 2 full bags and a half bag.", "What do you enter?",
     ["2.5", "3", "800", "640"],
     "C", "Count in the unit shown: 320 + 320 + 160 = 800 oz. (Staff guide 8)"),
    ("During a count you didn't get to the lemons.", "What goes in the lemon box?",
     ["0", "Leave it blank", "The number in “System says”", "Yesterday's count"],
     "B", "Blank means skipped; 0 means none left. (Staff guide 8)"),
    ("You made a Peach Paradise with the wrong milk and had to remake it.", "What do you log?",
     ["Nothing, it happens", "Waste → Whole drink → Peach Paradise, 1, reason “remade drink”",
      "Waste → Ingredient → milk only", "A sale of 2 Peach Paradise"],
     "B", "Logging the whole drink takes all its ingredients out of stock with the right reason. (Staff guide 9)"),
    ("Your shift ends. You've been using the shared tablet.", "What's the last thing you do?",
     ["Close the browser tab", "Turn the tablet off", "Tap Sign out at the top right", "Nothing; it signs out by itself"],
     "C", "Always sign out of a shared tablet so nobody works under your name. (Staff guide 11)"),
]

MANAGER = [
    ("Sam can't remember their password.", "What do you do?",
     ["Look up Sam's password on Settings", "Settings → Users → Reset password, give Sam the temporary password in person; Sam chooses their own at sign-in",
      "Create a second account for Sam", "Ask the owner to delete Sam's account"],
     "B", "Nobody can see passwords; a reset gives a temporary one that must be changed. (Manager guide 2)"),
    ("You add Riley as a new staff member.", "Which step makes Riley's name appear on deliveries, counts and waste they log?",
     ["Choosing a strong temporary password", "Linking the user to Riley's Employee record", "Giving Riley the manager role", "Nothing; it's automatic"],
     "B", "The Employee link fills in who received, counted or logged. (Manager guide 2)"),
    ("Today is Alex's last day.", "What should you do?",
     ["Nothing", "Change Alex's password", "Disable Alex on Settings → Users, and Remove from roster on the Schedule",
      "Delete Alex's past shifts"],
     "C", "Disable signs them out at once; removing from the roster opens future shifts and keeps past ones for labor history. (Manager guide 2)"),
    ("You'd like Jordan to become a manager.", "Who can do that?",
     ["You, on Settings → Users", "Jordan, under My account", "Only the owner", "Anyone with a staff account"],
     "C", "Managers look after staff accounts only; roles and manager accounts are for the owner. (Manager guide 1, 2)"),
    ("You imported Tuesday's till file a second time by mistake.", "How do you fix it?",
     ["Do a full stock count", "Record Sales → Import history → Undo on the extra import", "Delete the sales one by one",
      "Ask the owner to restore a backup"],
     "B", "Undo removes that import's sales and puts the ingredients back. (Manager guide 4b)"),
    ("During an import, “Gift Card ($25)” has a red bar.", "What do you choose for it?",
     ["The most expensive drink", "Ignore — not a drink", "Leave it; the import will work anyway", "Delete the row from the CSV"],
     "B", "Things that aren't drinks are ignored; the choice is remembered. The import won't run until every name is matched or ignored. (Manager guide 4b)"),
    ("You create a purchase order for Frosty Farms in Procurement.", "What happens with the supplier?",
     ["The app emails it to them", "Nothing yet: you still place the order with the supplier yourself",
      "The supplier sees it on their portal", "It's sent when someone receives it"],
     "B", "The app records the order and what's expected; it doesn't send it. (Manager guide 4c)"),
    ("The Dashboard shows mango with a red “< lead time” tag.", "What does it mean?",
     ["Mango is late", "At current use, mango runs out before a new delivery could arrive: order today", "Mango is over-stocked", "Mango's price went up"],
     "B", "Days of stock left is less than the supplier's lead time. (Manager guide 4a)"),
    ("Each weekly count shows strawberries about 6% short of what sales and waste explain.", "What's the most likely cause to look into first?",
     ["The app is broken", "Over-portioning, unlogged waste, or theft: check scoops and recipes, and remind staff to log waste",
      "The supplier short-ships every week", "Counting in the wrong week"],
     "B", "A steady shortfall on one item usually points to portions or unlogged waste. (Manager guide 6)"),
    ("A count shows mango 1,100 oz short when it's usually close.", "What's most likely?",
     ["Theft of 1,100 oz", "Someone counted packages instead of oz; recount using the “1 pkg = …” line",
      "A price change", "The Excel file is open"],
     "B", "Huge differences are usually a unit mistake. (Manager guide 6)"),
    ("Several items show a positive variance (more on the shelf than expected).", "Which is a likely cause?",
     ["Sales were both rung up on Record Sales and imported from the till", "Too much waste was logged correctly",
      "A supplier price change", "The schedule is wrong"],
     "A", "Double-counted sales (or a delivery received twice) make the system expect less than is really there. (Manager guide 6)"),
    ("A staff member logged 24 oz of spinach as waste instead of 2.4 oz.", "How do you fix it?",
     ["It can't be fixed", "Counts & Waste → Waste log → Remove that entry, then log the right amount",
      "Record a sale of spinach", "Edit the spinach on-hand number on Ingredients"],
     "B", "Removing a waste entry puts the stock back. (Manager guide 3)"),
    ("A delivery was checked in with 7 cases received instead of 5.", "How do you correct the stock?",
     ["Undo the receipt", "Do a stock count of that item so on-hand matches the shelf, and add a note", "Log 2 cases as waste", "Re-import the till file"],
     "B", "Receipts and hand-rung sales can't be undone; a count sets stock to what's really there. (Manager guide 3)"),
    ("Kale's price went up and Green Machine is now above your food-cost target.", "Where do you see this, and what are your options?",
     ["Only in Excel; nothing can be done", "Dashboard → Cost changes; tweak the recipe, raise the price, or find another supplier",
      "Receiving log; reject the delivery", "Schedule; cut hours"],
     "B", "Cost changes show each price change and its effect on every drink. (Manager guide 6)"),
    ("", "On the Schedule, what happens if you hold Ctrl (or Alt/Option) while dropping a shift on another day?",
     ["The shift is deleted", "The shift is copied there, and the original stays", "The shift is moved", "Nothing"],
     "B", "Dragging moves a shift; holding Ctrl or Alt copies it. (Manager guide 5)"),
]


def balance(questions):
    """Put each correct answer in a rotating position (A, C, B, D, ...) so letters can't be guessed from a pattern."""
    out = []
    for n, (scen, stem, options, ans, why) in enumerate(questions):
        right = options["ABCD".index(ans)]
        others = [o for o in options if o is not right]
        target = [0, 2, 1, 3, 2, 0, 3, 1][n % 8]
        opts = others[:target] + [right] + others[target:]
        out.append((scen, stem, opts, "ABCD"[target], why))
    return out


def build(title, subtitle, questions, pass_mark, filename, guide):
    esc = html.escape
    questions = balance(questions)
    qs = []
    for n, (scen, stem, options, _ans, _why) in enumerate(questions, start=1):
        opts = "".join(f"<li><b>{l}</b>&nbsp; {esc(o)}</li>" for l, o in zip("ABCD", options))
        sc = f'<div class="scenario">{esc(scen)}</div>' if scen else ""
        qs.append(f'<div class="q">{sc}<div class="stem"><span class="n">{n}.</span>{esc(stem)}</div><ol>{opts}</ol></div>')
    key = "".join(f"<tr><td>{n}</td><td>{a}</td><td>{esc(why)}</td></tr>"
                  for n, (_s, _q, _o, a, why) in enumerate(questions, start=1))
    total = len(questions)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{esc(title)}</title>
<link rel="stylesheet" href="manual.css"><style>:root {{ --doc-title: "Menu & Inventory · {esc(title)}"; }}</style></head>
<body>
<div class="cover">
  <div class="brand"><span class="mark">M</span> Menu &amp; Inventory</div>
  <h1>{esc(title)}</h1>
  <p>{esc(subtitle)}</p>
</div>
<div class="who"><span>Name</span><span>Date</span><span>Score &nbsp;&nbsp;&nbsp;&nbsp; / {total}</span></div>
<p class="lead">Circle one answer for each question. Use the {esc(guide)} if you're unsure, then check with your manager.
  Pass mark: <b>{pass_mark} out of {total}</b>.</p>
{''.join(qs)}
<section class="newpage">
  <h2>Answer key</h2>
  <p class="lead">For the person marking. Go over every wrong answer with the person, using the guide section listed.</p>
  <div class="score"><div><b>Pass:</b> {pass_mark} or more out of {total}</div>
    <div><b>Below {pass_mark}:</b> re-read the sections for the questions missed, practise on the app with a manager, and take it again.</div></div>
  <table class="key"><tr><th>#</th><th>Ans</th><th>Why (and where to read more)</th></tr>{key}</table>
</section>
</body></html>"""
    with open(os.path.join(HERE, filename), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    build("Staff knowledge check", "12 questions on the everyday moves: signing in, passwords, allergens, sales, receiving, "
          "counting, waste and signing out. About 10 minutes.", STAFF, 10, "staff-quiz.html", "Staff guide")
    build("Manager knowledge check", "15 questions on looking after staff accounts, sales imports, ordering, counts and "
          "variance, fixing mistakes, costs and the schedule. About 15 minutes.", MANAGER, 13, "manager-quiz.html", "Manager guide")
    print("wrote staff-quiz.html and manager-quiz.html")

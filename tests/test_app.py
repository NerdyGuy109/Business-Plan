"""Automated checks for the business rules, imports, auth and the web server.

Run from the project folder:  python -m unittest discover tests
Everything runs against a throwaway data folder; your real data is never touched.
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.cookiejar import CookieJar

TMP = tempfile.mkdtemp(prefix="menu-inventory-tests-")
os.environ["MENU_DATA_DIR"] = TMP  # must be set before the app modules are imported

from app import auth, pos_import, seed  # noqa: E402
from app.excel import export_workbook, import_workbook  # noqa: E402
from app.store import Store, ValidationError, shift_hours  # noqa: E402

SAMPLE_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "samples",
                          "square-item-sales-2026-10-24.csv")


def fresh_store():
    path = tempfile.mktemp(suffix=".json", dir=TMP)
    s = Store(path)
    seed.build(s)
    return s


def ing_named(s, name):
    return next(i for i in s.data["ingredients"] if i["name"] == name)


def item_named(s, name):
    return next(i for i in s.data["items"] if i["name"] == name)


class CostingTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()

    def test_unit_cost_uses_usable_yield(self):
        kale = ing_named(self.s, "Kale")  # 64 oz case, 75% usable
        expected = (kale["package_cost"] + kale["shipping_cost"]) / (64 * 0.75)
        self.assertAlmostEqual(self.s.unit_cost(kale), expected)

    def test_suggested_packages_refill_usable_amount_to_par(self):
        kale = ing_named(self.s, "Kale")
        kale["on_hand"] = kale["reorder_point"]
        need = kale["par_level"] - kale["on_hand"]
        self.assertEqual(self.s.suggested_packages(kale), -(-need // 48))

    def test_allergens_roll_up_from_ingredients(self):
        self.assertEqual(self.s.item_allergens(item_named(self.s, "PB Power")), ["milk", "tree nuts", "peanuts"])
        self.assertEqual(self.s.item_allergens(item_named(self.s, "Green Machine")), [])

    def test_unknown_allergen_is_refused(self):
        with self.assertRaises(ValidationError):
            self.s.upsert_ingredient({"name": "Mystery", "allergens": ["gluten"]})

    def test_price_change_records_food_cost_effect(self):
        kale = ing_named(self.s, "Kale")
        before = len(self.s.data["price_changes"])
        self.s.upsert_ingredient({**kale, "package_cost": kale["package_cost"] + 10})
        change = self.s.data["price_changes"][-1]
        self.assertEqual(len(self.s.data["price_changes"]), before + 1)
        gm = next(i for i in change["items"] if i["name"] == "Green Machine")
        self.assertGreater(gm["new_cost"], gm["old_cost"])
        self.assertAlmostEqual(gm["new_cost"], self.s.item_cost(item_named(self.s, "Green Machine")), places=3)

    def test_editing_without_price_change_logs_nothing(self):
        kale = ing_named(self.s, "Kale")
        before = len(self.s.data["price_changes"])
        self.s.upsert_ingredient({**kale, "notes": "keep cold"})
        self.assertEqual(len(self.s.data["price_changes"]), before)


class SalesAndStockTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()

    def test_sale_deducts_recipe(self):
        apple = ing_named(self.s, "Apple Juice")
        start = apple["on_hand"]
        self.s.record_sales([{"item_id": item_named(self.s, "Green Machine")["id"], "qty": 2}])
        self.assertEqual(apple["on_hand"], start - 12)

    def test_bad_line_changes_nothing(self):
        apple = ing_named(self.s, "Apple Juice")
        start, sales = apple["on_hand"], len(self.s.data["sales"])
        with self.assertRaises(ValidationError):
            self.s.record_sales([{"item_id": item_named(self.s, "Green Machine")["id"], "qty": 1},
                                 {"item_id": "MI-999", "qty": 1}])
        self.assertEqual(apple["on_hand"], start)
        self.assertEqual(len(self.s.data["sales"]), sales)

    def test_count_sets_on_hand_and_records_variance(self):
        straw = ing_named(self.s, "Strawberries (frozen)")
        expected = straw["on_hand"]
        count = self.s.record_count({"lines": [{"ingredient_id": straw["id"], "counted": expected - 50}]})
        self.assertEqual(straw["on_hand"], expected - 50)
        self.assertEqual(count["lines"][0]["variance"], -50)
        self.assertGreater(count["lines"][0]["theoretical_usage"], 0)
        self.assertAlmostEqual(count["variance_value"], round(-50 * self.s.unit_cost(straw), 2))

    def test_empty_count_refused(self):
        with self.assertRaises(ValidationError):
            self.s.record_count({"lines": [{"ingredient_id": "ING-001", "counted": ""}]})

    def test_waste_of_drink_deducts_recipe_and_can_be_removed(self):
        yogurt = ing_named(self.s, "Greek Yogurt")
        start = yogurt["on_hand"]
        entry = self.s.record_waste({"kind": "item", "item_id": item_named(self.s, "Peach Paradise")["id"],
                                     "qty": 2, "reason": "remade drink"})
        self.assertEqual(yogurt["on_hand"], start - 8)
        self.assertGreater(entry["cost"], 0)
        self.s.delete_waste(entry["id"])
        self.assertEqual(yogurt["on_hand"], start)

    def test_waste_needs_known_reason(self):
        with self.assertRaises(ValidationError):
            self.s.record_waste({"kind": "ingredient", "ingredient_id": "ING-001", "qty": 1, "reason": "felt like it"})


class ReceivingTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()
        self.po = next(p for p in self.s.data["purchase_orders"] if p["supplier"] == "Sysco")
        self.yogurt = ing_named(self.s, "Greek Yogurt")
        self.almond = ing_named(self.s, "Almond Milk")

    def test_partial_delivery_keeps_rest_on_order(self):
        y0, a0 = self.yogurt["on_hand"], self.almond["on_hand"]
        self.s.receive_purchase_order(self.po["id"], {"lines": [
            {"ingredient_id": self.yogurt["id"], "good": 7},
            {"ingredient_id": self.almond["id"], "good": 1, "damaged": 1}]})
        self.assertEqual(self.po["status"], "partial")
        self.assertEqual(self.yogurt["on_hand"], y0 + 7 * 192)
        self.assertEqual(self.almond["on_hand"], a0 + 384)
        self.assertEqual(self.s.outstanding(self.po)[self.almond["id"]], 1)
        self.s.receive_purchase_order(self.po["id"], {"lines": [], "close_short": True})
        self.assertEqual((self.po["status"], self.po.get("short")), ("received", True))

    def test_cannot_receive_more_than_outstanding(self):
        with self.assertRaises(ValidationError):
            self.s.receive_purchase_order(self.po["id"], {"lines": [{"ingredient_id": self.yogurt["id"], "good": 8}]})

    def test_invoice_price_updates_cost_and_logs_change(self):
        self.s.receive_purchase_order(self.po["id"], {"lines": [
            {"ingredient_id": self.yogurt["id"], "good": 7, "invoice_cost": 29.5}]})
        self.assertEqual(self.yogurt["package_cost"], 29.5)
        self.assertEqual(self.s.data["price_changes"][-1]["source"], f"invoice on {self.po['id']}")


class PosImportTests(unittest.TestCase):
    def setUp(self):
        self.s = fresh_store()
        with open(SAMPLE_CSV, encoding="utf-8") as f:
            self.text = f.read()
        self.aliases = {"PB Power Smoothie": item_named(self.s, "PB Power")["id"],
                        "Acai Energy Bowl Smoothie": item_named(self.s, "Acai Energy")["id"],
                        "Gift Card ($25)": pos_import.IGNORE}

    def test_columns_detected_and_refund_skipped(self):
        a = pos_import.analyse(self.s, self.text)
        self.assertEqual(a["missing"], [])
        self.assertEqual(a["mapping"]["qty"], "Qty")
        self.assertEqual(a["skipped"], {"refunds / voids": 1})

    def test_unmatched_names_block_import(self):
        with self.assertRaises(ValidationError):
            pos_import.commit(self.s, self.text)

    def test_import_remembers_matches_refuses_duplicates_and_undoes(self):
        peach = ing_named(self.s, "Peach (frozen)")
        start = peach["on_hand"]
        entry = pos_import.commit(self.s, self.text, aliases=self.aliases, filename="day.csv")
        self.assertGreater(entry["drinks"], 0)
        self.assertLess(peach["on_hand"], start)
        self.assertTrue(all(g["item_id"] for g in pos_import.analyse(self.s, self.text)["groups"]))  # remembered
        with self.assertRaises(ValidationError):
            pos_import.commit(self.s, self.text)
        pos_import.undo(self.s, entry["id"])
        self.assertEqual(peach["on_hand"], start)
        self.assertFalse(any(x.get("batch") == entry["id"] for x in self.s.data["sales"]))


class ScheduleTests(unittest.TestCase):
    def test_overnight_shift_hours(self):
        self.assertEqual(shift_hours({"start": "22:00", "end": "06:00"}), 8)

    def test_removing_employee_opens_future_shifts_and_keeps_past_ones(self):
        s = fresh_store()
        emp = s.data["employees"][2]
        today = date.today().isoformat()
        future = [x for x in s.data["shifts"] if x["employee_id"] == emp["id"] and x["date"] >= today]
        past = [x for x in s.data["shifts"] if x["employee_id"] == emp["id"] and x["date"] < today]
        self.assertTrue(future and past)
        s.remove_employee(emp["id"])
        self.assertFalse(emp["active"])
        self.assertTrue(all(x["employee_id"] is None for x in future))
        self.assertTrue(all(x["employee_id"] == emp["id"] for x in past))


class ExcelRoundTripTests(unittest.TestCase):
    def test_export_then_import_keeps_yield_and_allergens(self):
        s = fresh_store()
        path = os.path.join(TMP, "roundtrip.xlsx")
        export_workbook(s, path)
        import_workbook(s, path)
        self.assertEqual(ing_named(s, "Kale")["yield_pct"], 75)
        self.assertEqual(ing_named(s, "Almond Milk")["allergens"], ["tree nuts"])
        self.assertEqual(len(item_named(s, "Green Machine")["recipe"]), 7)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.users = auth.Users(os.path.join(tempfile.mkdtemp(dir=TMP), "users.json"))
        self.users.create("pat", "owner-pass-1", "Pat", "owner")

    def test_password_hash_round_trip(self):
        stored = auth.hash_password("s3cret-word")
        self.assertTrue(auth.check_password("s3cret-word", stored))
        self.assertFalse(auth.check_password("wrong", stored))
        self.assertNotIn("s3cret-word", stored)

    def test_short_password_refused(self):
        with self.assertRaises(ValidationError):
            self.users.create("sam", "short", role="staff")

    def test_lockout_after_repeated_failures(self):
        for _ in range(auth.MAX_FAILURES):
            with self.assertRaises(ValidationError):
                self.users.login("pat", "nope", "1.2.3.4")
        with self.assertRaisesRegex(ValidationError, "Too many attempts"):
            self.users.login("pat", "owner-pass-1", "1.2.3.4")
        self.users.login("pat", "owner-pass-1", "5.6.7.8")  # other addresses unaffected

    def test_last_owner_cannot_be_demoted(self):
        with self.assertRaises(ValidationError):
            self.users.update("pat", {"role": "staff"})

    def test_new_password_must_differ_and_clears_temporary_flag(self):
        self.users.create("sam", "staff-pass-1", role="staff")
        with self.assertRaises(ValidationError):
            self.users.change_own_password("sam", "staff-pass-1", "staff-pass-1")
        self.users.change_own_password("sam", "staff-pass-1", "brand-new-pw")
        self.assertFalse(self.users.get("sam")["must_change"])

    def test_account_added_from_command_line_is_seen_by_running_server(self):
        other = auth.Users(self.users.path)  # e.g. `python -m app.auth add` in another process
        other.create("jordan", "jordan-pass-1", role="manager", must_change=False)
        self.assertIsNotNone(self.users.get("jordan"))
        self.users.update("pat", {"name": "Pat O."})  # a later save keeps the new account
        self.assertIsNotNone(auth.Users(self.users.path).get("jordan"))

    def test_disabling_ends_sessions(self):
        self.users.create("sam", "staff-pass-1", role="staff")
        token, _ = self.users.login("sam", "staff-pass-1", "1.1.1.1")
        self.users.update("sam", {"active": False})
        self.assertIsNone(self.users.session_user(token))


class ServerTests(unittest.TestCase):
    """Runs the real web server on a free port against the test data folder."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from app import server
        seed.build(server.store)
        server.store.save()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def client(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, opener, method, path, body=None, header=True):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if header:
            req.add_header("X-Requested-With", "app")
        try:
            with opener.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_roles_and_csrf(self):
        owner = self.client()
        status, _ = self.call(owner, "GET", "/api/state")
        self.assertEqual(status, 401)
        self.assertEqual(self.call(owner, "POST", "/api/setup", {"name": "Pat", "username": "pat",
                                                                  "password": "owner-pass-1"})[0], 200)
        self.assertEqual(self.call(owner, "POST", "/api/setup", {"name": "X", "username": "x",
                                                                  "password": "another-1"})[0], 403)
        self.assertEqual(self.call(owner, "POST", "/api/users", {"username": "sam", "password": "staff-pass-1",
                                                                  "role": "staff", "employee_id": "EMP-003"})[0], 200)
        self.assertEqual(self.call(owner, "POST", "/api/ingredients", {"name": "x"}, header=False)[0], 400)

        staff = self.client()
        status, body = self.call(staff, "POST", "/api/login", {"username": "sam", "password": "staff-pass-1"})
        self.assertEqual((status, body["user"]["must_change"]), (200, True))
        status, body = self.call(staff, "POST", "/api/sales", {"lines": [{"item_id": "MI-001", "qty": 1}]})
        self.assertEqual((status, body.get("must_change")), (403, True))  # temporary password must go first
        self.assertEqual(self.call(staff, "POST", "/api/me/password",
                                   {"current": "staff-pass-1", "new": "sams-own-pass"})[0], 200)
        status, state = self.call(staff, "GET", "/api/state")
        self.assertEqual(status, 200)
        rates = {e["id"]: e["hourly_rate"] for e in state["employees"]}
        self.assertIsNotNone(rates["EMP-003"])
        self.assertIsNone(rates["EMP-001"])
        self.assertNotIn("users", state)
        self.assertEqual(self.call(staff, "POST", "/api/ingredients", {"name": "Hack", "package_qty": 1})[0], 403)
        self.assertEqual(self.call(staff, "PUT", "/api/settings", {"business_name": "x"})[0], 403)
        self.assertEqual(self.call(staff, "POST", "/api/sales", {"lines": [{"item_id": "MI-001", "qty": 1}]})[0], 200)
        status, body = self.call(staff, "POST", "/api/waste", {"kind": "ingredient", "ingredient_id": "ING-013",
                                                               "qty": 1, "reason": "damaged"})
        self.assertEqual((status, body["state"]["waste"][0]["by"]), (200, "EMP-003"))

        # managers look after staff accounts, and nothing above them
        self.assertEqual(self.call(owner, "POST", "/api/users", {"username": "maya", "password": "mgr-pass-123",
                                                                  "role": "manager"})[0], 200)
        mgr = self.client()
        self.call(mgr, "POST", "/api/login", {"username": "maya", "password": "mgr-pass-123"})
        self.assertEqual(self.call(mgr, "POST", "/api/me/password", {"current": "mgr-pass-123", "new": "mayas-pass-9"})[0], 200)
        self.assertEqual(self.call(mgr, "PUT", "/api/users/sam", {"password": "reset-pass-1"})[0], 200)
        self.assertEqual(self.call(mgr, "POST", "/api/users", {"username": "riley", "password": "temp-pass-1",
                                                                "role": "staff"})[0], 200)
        self.assertEqual(self.call(mgr, "POST", "/api/users", {"username": "boss", "password": "temp-pass-1",
                                                                "role": "manager"})[0], 403)
        self.assertEqual(self.call(mgr, "PUT", "/api/users/pat", {"password": "hijack-pass"})[0], 403)
        self.assertEqual(self.call(mgr, "PUT", "/api/users/sam", {"role": "owner"})[0], 403)
        status, state = self.call(mgr, "GET", "/api/state")
        self.assertEqual(sorted(u["username"] for u in state["users"]), ["maya", "riley", "sam"])
        # the reset signed Sam out, and the new password is temporary again
        self.assertEqual(self.call(staff, "GET", "/api/state")[0], 401)
        status, body = self.call(staff, "POST", "/api/login", {"username": "sam", "password": "reset-pass-1"})
        self.assertTrue(body["user"]["must_change"])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

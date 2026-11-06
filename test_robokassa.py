import concurrent.futures
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from robokassa_payments import Config, Payments


class RobokassaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "test.db")
        with sqlite3.connect(self.db) as db:
            db.executescript("""
            CREATE TABLE lifetime_access(user_id INTEGER PRIMARY KEY,granted_at TEXT,payment_plan TEXT);
            CREATE TABLE subscriptions(user_id INTEGER,active INTEGER);
            INSERT INTO subscriptions VALUES(101,1);
            """)
        self.payments = Payments(self.db)
        self.payments.init()
        self.test = Config("antibabka", "test-secret-one", "test-secret-two")
        self.live = Config("antibabka", "live-secret-one", "live-secret-two", test=False)

    def tearDown(self):
        self.tmp.cleanup()

    def notification(self, inv_id, config, amount="6499.000000"):
        # Independent implementation of vendor ResultURL formula.
        digest = hashlib.sha256(f"{amount}:{inv_id}:{config.password2}".encode()).hexdigest()
        return {"InvId":str(inv_id), "OutSum":amount,"SignatureValue":digest.upper()}

    def count(self, table):
        with sqlite3.connect(self.db) as db:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_checkout_signature_and_safe_test_flag(self):
        inv_id, url = self.payments.checkout(101,"6499",self.test)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["IsTest"],["1"])
        self.assertNotIn("Shp_user", query)
        self.assertEqual(query["InvId"], [str(inv_id)])
        expected = hashlib.sha256(f"antibabka:6499.00:{inv_id}:test-secret-one".encode()).hexdigest()
        self.assertEqual(query["SignatureValue"],[expected])
        self.assertNotIn("test-secret",url)

    def test_test_payment_never_grants_real_access(self):
        inv_id,_ = self.payments.checkout(101,"6499",self.test)
        self.assertEqual(self.payments.accept(self.notification(inv_id,self.test),self.test),f"OK{inv_id}")
        self.assertEqual(self.count("lifetime_access"),0)
        self.assertEqual(self.count("robokassa_outbox"),0)

    def test_live_payment_is_idempotent_even_concurrently(self):
        inv_id,_ = self.payments.checkout(101,"6499",self.live)
        notification = self.notification(inv_id,self.live)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.payments.accept(notification,self.live), range(8)))
        self.assertEqual(set(results),{f"OK{inv_id}"})
        self.assertEqual(self.count("lifetime_access"),1)
        self.assertEqual(self.count("robokassa_outbox"),1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT active FROM subscriptions").fetchone()[0],0)

    def test_forged_or_wrong_amount_notification_has_no_effect(self):
        inv_id,_ = self.payments.checkout(101,"6499",self.live)
        wrong=self.notification(inv_id,self.live,"1.00")
        with self.assertRaises(ValueError):self.payments.accept(wrong,self.live)
        forged=self.notification(inv_id,self.live)
        forged["SignatureValue"]="0"*64
        with self.assertRaises(ValueError):self.payments.accept(forged,self.live)
        self.assertEqual(self.count("lifetime_access"),0)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT status FROM robokassa_orders").fetchone()[0],"pending")

    def test_unknown_invoice_and_mode_swap_rejected(self):
        with self.assertRaises(ValueError):self.payments.accept(self.notification(123,self.live),self.live)
        inv_id,_=self.payments.checkout(101,"6499",self.test)
        with self.assertRaises(ValueError):self.payments.accept(self.notification(inv_id,self.live),self.live)
        with self.assertRaises(ValueError):self.payments.accept(self.notification(inv_id,self.test),self.live)
        self.assertEqual(self.count("lifetime_access"),0)

    def test_equal_amount_orders_go_to_the_correct_buyer(self):
        first,_=self.payments.checkout(101,"6499",self.live)
        second,_=self.payments.checkout(202,"6499",self.live)
        self.payments.accept(self.notification(second,self.live),self.live)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT user_id FROM lifetime_access").fetchall(),[(202,)])
            self.assertEqual(db.execute("SELECT status FROM robokassa_orders WHERE inv_id=?",(first,)).fetchone()[0],"pending")

    def test_delivery_survives_restart_and_retry(self):
        inv_id,_=self.payments.checkout(101,"6499",self.live)
        self.payments.accept(self.notification(inv_id,self.live),self.live)
        self.payments.remember_invite(inv_id,"https://example.test/invite")
        restarted=Payments(self.db)
        self.assertEqual(restarted.pending_deliveries()[0]["invite_link"],"https://example.test/invite")
        restarted.delivery_failed(inv_id)
        self.assertEqual(restarted.pending_deliveries(),[])
        restarted.delivery_done(inv_id)
        self.assertEqual(restarted.pending_deliveries(),[])

    def test_second_paid_order_does_not_create_second_entitlement(self):
        for _ in range(2):
            inv_id,_=self.payments.checkout(101,"6499",self.live)
            self.payments.accept(self.notification(inv_id,self.live),self.live)
        self.assertEqual(self.count("lifetime_access"),1)
        self.assertEqual(self.count("robokassa_outbox"),1)

    def test_bad_amounts_and_unexpected_custom_fields(self):
        for value in ["NaN","Infinity","-1","0","6499.001","9e9999"]:
            with self.assertRaises(ValueError):self.payments.checkout(101,value,self.test)
        inv_id,_=self.payments.checkout(101,"6499",self.test)
        data=self.notification(inv_id,self.test)
        data["Shp_user"]="202"
        with self.assertRaises(ValueError):self.payments.accept(data,self.test)


if __name__ == "__main__":
    unittest.main()

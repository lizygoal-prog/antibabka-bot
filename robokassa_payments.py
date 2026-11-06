"""Signed Robokassa checkout and durable payment acceptance; no network or secrets on import."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import secrets
import sqlite3
from urllib.parse import urlencode


def amount_value(value):
    try:
        if len(str(value)) > 32:
            raise ValueError("Invalid amount")
        result = Decimal(value)
        valid = result.is_finite() and result > 0 and result == result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid amount") from None
    if not valid:
        raise ValueError("Invalid amount")
    return result


@dataclass(frozen=True)
class Config:
    login: str
    password1: str = field(repr=False)
    password2: str = field(repr=False)
    test: bool = True
    algorithm: str = "sha256"

    def __post_init__(self):
        if not all((self.login, self.password1, self.password2)):
            raise ValueError("Robokassa credentials are not configured")
        if self.algorithm not in {"md5", "sha256", "sha512"}:
            raise ValueError("Unsupported signature algorithm")


def signature(config, parts):
    return hashlib.new(config.algorithm, ":".join(parts).encode("utf-8")).hexdigest()


class Payments:
    def __init__(self, db_file):
        self.db_file = db_file

    def connect(self):
        connection = sqlite3.connect(self.db_file, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS robokassa_orders (
                    inv_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                    amount TEXT NOT NULL, is_test INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    paid_at TEXT
                );
                CREATE TABLE IF NOT EXISTS robokassa_outbox (
                    inv_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
                    invite_link TEXT, delivered INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

    def checkout(self, user_id, amount, config):
        value = format(amount_value(amount), ".2f")
        # Random positive SQLite-safe ID, not a Telegram identifier.
        with self.connect() as db:
            for _ in range(5):
                inv_id = secrets.randbelow(2**62 - 1) + 1
                try:
                    db.execute("INSERT INTO robokassa_orders(inv_id,user_id,amount,is_test) VALUES(?,?,?,?)",
                               (inv_id, user_id, value, int(config.test)))
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError("Cannot allocate invoice")
        params = {
            "MerchantLogin": config.login, "OutSum": value, "InvId": str(inv_id),
            "Description": "Доступ в клуб Антибабка", "Culture": "ru", "Encoding": "utf-8",
            "IsTest": "1" if config.test else "0",
            "SignatureValue": signature(config, [config.login, value, str(inv_id), config.password1]),
        }
        return inv_id, "https://auth.robokassa.ru/Merchant/Index.aspx?" + urlencode(params)

    def accept(self, params, config):
        """Commit the verified order, entitlement and delivery atomically, before acknowledging."""
        if any(key.startswith("Shp_") for key in params):
            raise ValueError("Unexpected merchant parameters")
        out_sum, raw_id = params.get("OutSum", ""), params.get("InvId", "")
        if not raw_id.isascii() or not raw_id.isdecimal() or not 0 < int(raw_id) < 2**63:
            raise ValueError("Invalid invoice")
        expected = signature(config, [out_sum, raw_id, config.password2])
        if not hmac.compare_digest(expected, params.get("SignatureValue", "").lower()):
            raise ValueError("Invalid signature")
        value = amount_value(out_sum)
        inv_id = int(raw_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            order = db.execute("SELECT * FROM robokassa_orders WHERE inv_id=?", (inv_id,)).fetchone()
            if not order or order["is_test"] != int(config.test) or Decimal(order["amount"]) != value:
                raise ValueError("Invoice does not match")
            if order["status"] == "paid":
                return f"OK{raw_id}"
            db.execute("UPDATE robokassa_orders SET status='paid',paid_at=datetime('now') WHERE inv_id=?", (inv_id,))
            if not config.test:
                created = db.execute(
                    "INSERT OR IGNORE INTO lifetime_access(user_id,granted_at,payment_plan) VALUES(?,datetime('now'),'lifetime')",
                    (order["user_id"],),
                ).rowcount
                db.execute("UPDATE subscriptions SET active=0 WHERE user_id=? AND active=1", (order["user_id"],))
                if created:
                    db.execute("INSERT INTO robokassa_outbox(inv_id,user_id) VALUES(?,?)", (inv_id, order["user_id"]))
        return f"OK{raw_id}"

    def pending_deliveries(self):
        with self.connect() as db:
            return db.execute("SELECT * FROM robokassa_outbox WHERE delivered=0 AND next_attempt<=datetime('now') LIMIT 20").fetchall()

    def remember_invite(self, inv_id, link):
        with self.connect() as db:
            db.execute("UPDATE robokassa_outbox SET invite_link=? WHERE inv_id=?", (link, inv_id))

    def delivery_done(self, inv_id):
        with self.connect() as db:
            db.execute("UPDATE robokassa_outbox SET delivered=1 WHERE inv_id=?", (inv_id,))

    def delivery_failed(self, inv_id):
        with self.connect() as db:
            db.execute("UPDATE robokassa_outbox SET attempts=attempts+1,next_attempt=datetime('now','+60 seconds') WHERE inv_id=?", (inv_id,))

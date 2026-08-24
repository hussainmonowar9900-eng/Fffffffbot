"""SQLite database layer — auto-initializing, migration-safe, thread-safe."""

import sqlite3
import threading
import logging
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class Database:
    """Thread-safe SQLite wrapper with auto-initialization and migrations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # Store per-thread connections
        self._local = threading.local()
        # Initialize schema on creation
        self._init_schema()

    # ── Connection management ───────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    # ── Schema initialization & migrations ──────────────────────────────────

    def _init_schema(self) -> None:
        """Create all tables if they don't exist and run safe migrations."""
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()

            # ── users ─────────────────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id      INTEGER PRIMARY KEY,
                    phone        TEXT DEFAULT '',
                    username     TEXT DEFAULT '',
                    first_name   TEXT DEFAULT '',
                    balance      INTEGER DEFAULT 0,
                    is_banned    INTEGER DEFAULT 0,
                    created_at   TEXT DEFAULT (datetime('now')),
                    updated_at   TEXT DEFAULT (datetime('now'))
                )
            """)

            # ── products ──────────────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)

            # ── pids (external API product identifiers) ───────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pids (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id  INTEGER NOT NULL,
                    pid_value   TEXT NOT NULL,
                    created_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)

            # ── plans (pricing tiers per product) ────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id  INTEGER NOT NULL,
                    name        TEXT NOT NULL,
                    price       INTEGER NOT NULL,
                    duration_days INTEGER DEFAULT 30,
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)

            # ── keys (purchased activation keys / order details) ───────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS keys (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    product_id  INTEGER,
                    plan_id     INTEGER,
                    key_data    TEXT DEFAULT '',
                    order_ref   TEXT DEFAULT '',
                    status      TEXT DEFAULT 'active',
                    created_at  TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # ── payments ─────────────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL,
                    amount          INTEGER NOT NULL,
                    txn_id          TEXT UNIQUE,
                    status          TEXT DEFAULT 'pending',
                    method          TEXT DEFAULT 'upi',
                    created_at     TEXT DEFAULT (datetime('now')),
                    updated_at     TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # ── settings (key-value store for bot configuration) ───────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # ── Safe migrations (additive only, never destructive) ────────────
            self._safe_migrate(cur)

            conn.commit()
        logger.info("[OK] Database schema initialized")

    def _safe_migrate(self, cur: sqlite3.Cursor) -> None:
        """Additive migrations — only adds columns, never removes or alters data."""

        def _column_exists(table: str, column: str) -> bool:
            cur.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cur.fetchall())

        def _add_column(table: str, column: str, coltype: str) -> None:
            if not _column_exists(table, column):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                logger.info("  Migrated: added %s.%s", table, column)

        # Future migrations go here — additive only
        # _add_column("users", "new_column", "TEXT DEFAULT ''")

    # ── User operations ──────────────────────────────────────────────────────

    def get_or_create_user(self, user_id: int, username: str = "", first_name: str = "") -> sqlite3.Row:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                    (user_id, username, first_name),
                )
                conn.commit()
                cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                row = cur.fetchone()
            else:
                # Update username/first_name if changed
                if (row["username"] or "") != username or (row["first_name"] or "") != first_name:
                    cur.execute(
                        "UPDATE users SET username = ?, first_name = ?, updated_at = datetime('now') WHERE user_id = ?",
                        (username, first_name, user_id),
                    )
                    conn.commit()
            return row

    def update_phone(self, user_id: int, phone: str) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute(
                "UPDATE users SET phone = ?, updated_at = datetime('now') WHERE user_id = ?",
                (phone, user_id),
            )
            conn.commit()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return cur.fetchone()

    def get_balance(self, user_id: int) -> int:
        row = self.get_user(user_id)
        return row["balance"] if row else 0

    def adjust_balance(self, user_id: int, amount: int) -> int:
        """Atomically adjust balance by `amount` (can be negative). Returns new balance."""
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                row = cur.fetchone()
                if row is None:
                    cur.execute("ROLLBACK")
                    raise ValueError(f"User {user_id} not found")
                new_balance = row["balance"] + amount
                if new_balance < 0:
                    cur.execute("ROLLBACK")
                    raise ValueError("Insufficient balance")
                cur.execute(
                    "UPDATE users SET balance = ?, updated_at = datetime('now') WHERE user_id = ?",
                    (new_balance, user_id),
                )
                cur.execute("COMMIT")
                return new_balance
            except Exception:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def set_banned(self, user_id: int, banned: bool) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute(
                "UPDATE users SET is_banned = ?, updated_at = datetime('now') WHERE user_id = ?",
                (1 if banned else 0, user_id),
            )
            conn.commit()

    def is_banned(self, user_id: int) -> bool:
        row = self.get_user(user_id)
        return bool(row and row["is_banned"])

    def count_users(self) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0]

    def get_all_user_ids(self) -> list[int]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE is_banned = 0")
            return [row[0] for row in cur.fetchall()]

    # ── Product operations ───────────────────────────────────────────────────

    def add_product(self, name: str, description: str = "") -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO products (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
            return cur.lastrowid

    def get_product(self, product_id: int) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            return cur.fetchone()

    def list_products(self, active_only: bool = True) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            if active_only:
                cur.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY name")
            else:
                cur.execute("SELECT * FROM products ORDER BY name")
            return cur.fetchall()

    def delete_product(self, product_id: int) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute("DELETE FROM plans WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM pids WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()

    # ── PID operations ──────────────────────────────────────────────────────

    def add_pid(self, product_id: int, pid_value: str) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pids (product_id, pid_value) VALUES (?, ?)",
                (product_id, pid_value),
            )
            conn.commit()
            return cur.lastrowid

    def get_pid_for_product(self, product_id: int) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM pids WHERE product_id = ? LIMIT 1", (product_id,))
            return cur.fetchone()

    def list_pids(self) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("""
                SELECT p.*, pr.name as product_name
                FROM pids p
                LEFT JOIN products pr ON p.product_id = pr.id
                ORDER BY pr.name
            """)
            return cur.fetchall()

    def delete_pid(self, pid_id: int) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute("DELETE FROM pids WHERE id = ?", (pid_id,))
            conn.commit()

    # ── Plan operations ─────────────────────────────────────────────────────

    def add_plan(self, product_id: int, name: str, price: int, duration_days: int = 30) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO plans (product_id, name, price, duration_days) VALUES (?, ?, ?, ?)",
                (product_id, name, price, duration_days),
            )
            conn.commit()
            return cur.lastrowid

    def get_plan(self, plan_id: int) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
            return cur.fetchone()

    def list_plans(self, product_id: int, active_only: bool = True) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            if active_only:
                cur.execute("SELECT * FROM plans WHERE product_id = ? AND is_active = 1 ORDER BY price", (product_id,))
            else:
                cur.execute("SELECT * FROM plans WHERE product_id = ? ORDER BY price", (product_id,))
            return cur.fetchall()

    def list_all_plans(self) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("""
                SELECT pl.*, pr.name as product_name
                FROM plans pl
                LEFT JOIN products pr ON pl.product_id = pr.id
                ORDER BY pr.name, pl.price
            """)
            return cur.fetchall()

    def delete_plan(self, plan_id: int) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            conn.commit()

    # ── Key / purchase operations ───────────────────────────────────────────

    def add_key(self, user_id: int, product_id: int, plan_id: int, key_data: str, order_ref: str = "") -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO keys (user_id, product_id, plan_id, key_data, order_ref) VALUES (?, ?, ?, ?, ?)",
                (user_id, product_id, plan_id, key_data, order_ref),
            )
            conn.commit()
            return cur.lastrowid

    def get_user_keys(self, user_id: int) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("""
                SELECT k.*, p.name as product_name, pl.name as plan_name
                FROM keys k
                LEFT JOIN products p ON k.product_id = p.id
                LEFT JOIN plans pl ON k.plan_id = pl.id
                WHERE k.user_id = ?
                ORDER BY k.created_at DESC
            """, (user_id,))
            return cur.fetchall()

    def count_keys(self, user_id: Optional[int] = None) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            if user_id is None:
                cur.execute("SELECT COUNT(*) FROM keys")
            else:
                cur.execute("SELECT COUNT(*) FROM keys WHERE user_id = ?", (user_id,))
            return cur.fetchone()[0]

    # ── Payment operations ──────────────────────────────────────────────────

    def create_payment(self, user_id: int, amount: int, txn_id: str, method: str = "upi") -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO payments (user_id, amount, txn_id, status, method) VALUES (?, ?, ?, 'pending', ?)",
                (user_id, amount, txn_id, method),
            )
            conn.commit()
            return cur.lastrowid

    def get_payment(self, payment_id: int) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            return cur.fetchone()

    def get_payment_by_txn(self, txn_id: str) -> Optional[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT * FROM payments WHERE txn_id = ?", (txn_id,))
            return cur.fetchone()

    def update_payment_status(self, payment_id: int, status: str) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute(
                "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, payment_id),
            )
            conn.commit()

    def approve_payment_atomic(self, payment_id: int) -> Optional[sqlite3.Row]:
        """Approve one pending payment and credit its wallet in one transaction."""
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                cur.execute(
                    "SELECT id, user_id, amount FROM payments WHERE id = ? AND status = 'pending'",
                    (payment_id,),
                )
                payment = cur.fetchone()
                if payment is None:
                    cur.execute("ROLLBACK")
                    return None

                cur.execute(
                    "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE user_id = ?",
                    (payment["amount"], payment["user_id"]),
                )
                if cur.rowcount != 1:
                    cur.execute("ROLLBACK")
                    return None

                cur.execute(
                    "UPDATE payments SET status = 'approved', updated_at = datetime('now') "
                    "WHERE id = ? AND status = 'pending'",
                    (payment_id,),
                )
                if cur.rowcount != 1:
                    cur.execute("ROLLBACK")
                    return None

                cur.execute("COMMIT")
                return payment
            except Exception:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def list_pending_payments(self) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("""
                SELECT pay.*, u.username, u.first_name
                FROM payments pay
                LEFT JOIN users u ON pay.user_id = u.user_id
                WHERE pay.status = 'pending'
                ORDER BY pay.created_at DESC
            """)
            return cur.fetchall()

    def list_payment_history(self, limit: int = 20) -> list[sqlite3.Row]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("""
                SELECT pay.*, u.username, u.first_name
                FROM payments pay
                LEFT JOIN users u ON pay.user_id = u.user_id
                ORDER BY pay.created_at DESC
                LIMIT ?
            """, (limit,))
            return cur.fetchall()

    def count_purchases(self) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM keys")
            return cur.fetchone()[0]

    def count_payments(self, status: str = None) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            if status:
                cur.execute("SELECT COUNT(*) FROM payments WHERE status = ?", (status,))
            else:
                cur.execute("SELECT COUNT(*) FROM payments")
            return cur.fetchone()[0]

    def sum_revenue(self) -> int:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'")
            return cur.fetchone()[0]

    # ── Settings ─────────────────────────────────────────────────────────────

    def get_setting(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        conn = self._get_conn()
        with _lock:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    # ── Purchase transaction (atomic) ──────────────────────────────────────

    def process_purchase(
        self, user_id: int, product_id: int, plan_id: int, price: int,
        key_data: str, order_ref: str = "",
    ) -> int:
        """Atomically deduct balance and record the key. Returns new key ID.

        Raises ValueError if insufficient balance.
        """
        conn = self._get_conn()
        with _lock:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                row = cur.fetchone()
                if row is None:
                    cur.execute("ROLLBACK")
                    raise ValueError("User not found")
                if row["balance"] < price:
                    cur.execute("ROLLBACK")
                    raise ValueError("Insufficient balance")

                new_balance = row["balance"] - price
                cur.execute(
                    "UPDATE users SET balance = ?, updated_at = datetime('now') WHERE user_id = ?",
                    (new_balance, user_id),
                )
                cur.execute(
                    "INSERT INTO keys (user_id, product_id, plan_id, key_data, order_ref) VALUES (?, ?, ?, ?, ?)",
                    (user_id, product_id, plan_id, key_data, order_ref),
                )
                key_id = cur.lastrowid
                cur.execute("COMMIT")
                return key_id
            except Exception:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

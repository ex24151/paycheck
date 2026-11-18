"""SQLite storage: suppliers, invoices, findings, audit log, shared fraud list."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("PAYCHECK_DB", os.path.join(os.path.dirname(__file__), "..", "paycheck.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    email_domain TEXT NOT NULL,
    verified_iban TEXT,
    verified_phone TEXT,          -- phone from master data, NEVER from an invoice
    iban_verified_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER REFERENCES suppliers(id),
    supplier_name TEXT NOT NULL,
    invoice_number TEXT,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    iban TEXT,
    sender_email TEXT,
    reply_to TEXT,
    email_body TEXT,
    invoice_text TEXT,
    status TEXT NOT NULL,         -- see app/workflow.py
    risk_score INTEGER,
    risk_level TEXT,              -- green | amber | red
    ai_summary TEXT,
    received_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id),
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL,       -- info | low | medium | high | critical
    title TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    invoice_id INTEGER,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS known_bad_accounts (
    iban TEXT PRIMARY KEY,
    reason TEXT,
    reported_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)


def rows(sql: str, params=()) -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def row(sql: str, params=()) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None


def audit(conn, invoice_id, actor, action, note=None) -> None:
    conn.execute(
        "INSERT INTO audit_log (invoice_id, actor, action, note, at) VALUES (?,?,?,?,?)",
        (invoice_id, actor, action, note if note is None or isinstance(note, str) else json.dumps(note), now()),
    )

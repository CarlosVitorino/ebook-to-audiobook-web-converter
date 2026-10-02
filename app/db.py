"""SQLite: the connection helper, the schema, and the event log that feeds /stats."""
import os
import sqlite3
import time
from contextlib import contextmanager

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(os.path.join(DATA, "jobs"), exist_ok=True)
DB = os.path.join(DATA, "app.db")


@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def migrate():
    with db() as con:
        # WAL lets the web app read while the worker process writes.
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, email TEXT, filename TEXT, format TEXT, title TEXT,
                chars INTEGER, status TEXT, progress REAL DEFAULT 0, error TEXT,
                audio_seconds REAL, created REAL, started REAL, finished REAL
            );
            CREATE TABLE IF NOT EXISTS events (ts REAL, email TEXT, kind TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, google_sub TEXT UNIQUE, created REAL
            );
            -- The balance is the sum of delta: +1 free book, +N purchase, -N conversion, +N refund.
            CREATE TABLE IF NOT EXISTS credits (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, delta INTEGER NOT NULL,
                reason TEXT NOT NULL, ref TEXT, created REAL
            );
            CREATE INDEX IF NOT EXISTS credits_user ON credits(user_id);
            -- One row per checkout started. Only the signed webhook moves it to 'paid' and adds credits.
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
                pack TEXT NOT NULL, books INTEGER NOT NULL, draft_id TEXT, status TEXT NOT NULL,
                creem_order_id TEXT UNIQUE, amount_cents INTEGER, currency TEXT, created REAL, paid REAL
            );
            -- Who got a free book, keyed several ways, so a second account rarely gets another.
            CREATE TABLE IF NOT EXISTS free_grants (
                user_id INTEGER NOT NULL, email_key TEXT, device TEXT, ip TEXT, created REAL
            );
            CREATE INDEX IF NOT EXISTS free_email ON free_grants(email_key);
            CREATE INDEX IF NOT EXISTS free_device ON free_grants(device);
            CREATE INDEX IF NOT EXISTS free_ip ON free_grants(ip, created);
            -- Rate limits: one row per counted action, pruned by the worker.
            CREATE TABLE IF NOT EXISTS hits (kind TEXT NOT NULL, key TEXT NOT NULL, ts REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS hits_key ON hits(kind, key, ts);
            CREATE TABLE IF NOT EXISTS login_tokens (
                hash TEXT PRIMARY KEY, email TEXT NOT NULL, next TEXT, created REAL, used REAL
            );
            """
        )
        have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
        for col in ("owner TEXT", "voice TEXT", "user_id INTEGER", "credits_used INTEGER"):
            if col.split()[0] not in have:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        have = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
        if "free_denied" not in have:
            con.execute("ALTER TABLE users ADD COLUMN free_denied TEXT")


def log(email: str, kind: str, detail: str = ""):
    with db() as con:
        con.execute("INSERT INTO events VALUES (?,?,?,?)", (time.time(), email or "", kind, detail))

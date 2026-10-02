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
            CREATE TABLE IF NOT EXISTS login_tokens (
                hash TEXT PRIMARY KEY, email TEXT NOT NULL, next TEXT, created REAL, used REAL
            );
            """
        )
        have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
        for col in ("owner TEXT", "voice TEXT", "user_id INTEGER", "credits_used INTEGER"):
            if col.split()[0] not in have:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        # Jobs interrupted by a restart go back in the queue.
        con.execute("UPDATE jobs SET status='queued', progress=0 WHERE status='working'")


def log(email: str, kind: str, detail: str = ""):
    with db() as con:
        con.execute("INSERT INTO events VALUES (?,?,?,?)", (time.time(), email or "", kind, detail))

"""Spending credits on a draft. Used by the confirm page and by the payment webhook,
which starts the book someone was trying to convert as soon as their pack is paid."""
import os
import threading
import time

from . import sections as S
from .db import DATA, db

# Set to wake the worker as soon as a book is queued.
wake = threading.Event()


def start_draft(user_id: int, email: str, job_id: str) -> tuple[bool, int, int]:
    """Spend the draft's credits and queue it. Returns (started, balance before, credits needed).

    Check-and-spend is one transaction, so a double click or a webhook retry can't spend twice.
    """
    secs = S.load(os.path.join(DATA, "jobs", job_id))
    chars = S.included_chars(secs)
    needed = S.credits(chars)
    started = 0
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        have = con.execute("SELECT COALESCE(SUM(delta),0) FROM credits WHERE user_id=?", (user_id,)).fetchone()[0]
        if have >= needed:
            started = con.execute(
                "UPDATE jobs SET email=?, user_id=?, chars=?, credits_used=?, status='queued', created=? "
                "WHERE id=? AND status='draft' AND (user_id=? OR user_id IS NULL)",
                (email, user_id, chars, needed, time.time(), job_id, user_id),
            ).rowcount
            if started:
                con.execute(
                    "INSERT INTO credits (user_id, delta, reason, ref, created) VALUES (?,?,'conversion',?,?)",
                    (user_id, -needed, job_id, time.time()),
                )
    if started:
        wake.set()
    return bool(started), have, needed

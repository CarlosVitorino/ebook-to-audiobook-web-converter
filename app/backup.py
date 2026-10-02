"""Copy the database safely while the app runs: python -m app.backup

Writes <DATA>/backups/app-YYYY-MM-DD.db and keeps the newest KEEP. Run it daily from cron
(see docs/deploy.md) and copy data/backups off the server now and then.
"""
import glob
import os
import sqlite3
import time

from .db import DATA, DB

KEEP = 14

if __name__ == "__main__":
    folder = os.path.join(DATA, "backups")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, time.strftime("app-%Y-%m-%d.db"))
    src, dst = sqlite3.connect(DB), sqlite3.connect(target)
    with dst:
        src.backup(dst)  # SQLite's online backup: consistent even while the app writes
    src.close(); dst.close()
    for old in sorted(glob.glob(os.path.join(folder, "app-*.db")))[:-KEEP]:
        os.remove(old)
    print("backed up to", target)

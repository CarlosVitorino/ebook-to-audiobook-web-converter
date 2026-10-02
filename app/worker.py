"""The narration worker: takes queued books one at a time and narrates them.

Run it as its own process (`python -m app.worker`, as docker-compose does) so a web
deploy or crash doesn't kill a book halfway. With RUN_WORKER=1 (the default, used by
run.sh) the web app runs it in a thread instead.
"""
import os
import shutil
import time
import traceback

from . import mail
from . import sections as S
from .credits import wake
from .db import DATA, db, log, migrate
from .extract import extract
from .narrate import VOICE, narrate
from .web import BASE_URL, DRAFT_HOURS, KEEP_HOURS, keep_text

POLL_SECONDS = 5


def folder(job_id: str) -> str:
    return os.path.join(DATA, "jobs", job_id)


def run_job(job):
    jobdir = folder(job["id"])
    ext = "." + job["format"]
    last = [0.0]

    def progress(done, total):
        if time.time() - last[0] > 3:
            last[0] = time.time()
            with db() as con:
                con.execute("UPDATE jobs SET progress=? WHERE id=?", (done / total, job["id"]))

    if os.path.exists(os.path.join(jobdir, "sections.json")):
        chapters = S.chapters(S.load(jobdir))
    else:  # queued before the section picker existed
        chapters = extract(os.path.join(jobdir, "source" + ext), ext)
    _, _, seconds = narrate(chapters, job["title"], jobdir, progress, job["voice"] or VOICE)
    for name in ("source" + ext, "sections.json"):
        if os.path.exists(os.path.join(jobdir, name)):
            os.remove(os.path.join(jobdir, name))
    return seconds


def notify(to: str, subject: str, body: str):
    """Mail problems must never fail a finished book."""
    if not to:
        return
    try:
        mail.send(to, subject, body)
    except Exception:
        traceback.print_exc()


def cleanup():
    now = time.time()
    with db() as con:
        old = con.execute(
            "SELECT id, 'expired' AS next FROM jobs WHERE status IN ('done','failed') AND finished < ? "
            "UNION ALL SELECT id, 'abandoned' FROM jobs WHERE status='draft' AND created < ?",
            (now - KEEP_HOURS * 3600, now - DRAFT_HOURS * 3600),
        ).fetchall()
        for row in old:
            shutil.rmtree(folder(row["id"]), ignore_errors=True)
            con.execute("UPDATE jobs SET status=? WHERE id=?", (row["next"], row["id"]))
        con.execute("DELETE FROM hits WHERE ts < ?", (now - 86400,))


def process(job):
    link = f"{BASE_URL}/jobs/{job['id']}"
    try:
        seconds = run_job(job)
        with db() as con:
            con.execute(
                "UPDATE jobs SET status='done', progress=1, audio_seconds=?, finished=? WHERE id=?",
                (seconds, time.time(), job["id"]),
            )
        log(job["email"], "done", f"{job['id']} {seconds:.0f}s audio")
        notify(job["email"], f"Your audiobook is ready: {job['title']}", (
            f"\"{job['title']}\" is ready to download:\n\n{link}\n\n"
            f"The files are deleted {keep_text(KEEP_HOURS)} from now, so download them soon."
        ))
    except Exception as e:
        traceback.print_exc()
        with db() as con:
            con.execute(
                "UPDATE jobs SET status='failed', error=?, finished=? WHERE id=?",
                (str(e)[:500], time.time(), job["id"]),
            )
            if job["user_id"] and job["credits_used"]:
                con.execute(
                    "INSERT INTO credits (user_id, delta, reason, ref, created) VALUES (?,?,'refund',?,?)",
                    (job["user_id"], job["credits_used"], job["id"], time.time()),
                )
        log(job["email"], "failed", f"{job['id']} {e}")
        notify(job["email"], f"We couldn't convert {job['title']}", (
            f"Sorry, something went wrong narrating \"{job['title']}\". "
            "The book it used has been given back to your account.\n\n"
            f"{BASE_URL}/"
        ))


def run():
    # Only the worker may do this: a book marked 'working' was interrupted by a worker restart.
    with db() as con:
        con.execute("UPDATE jobs SET status='queued', progress=0 WHERE status='working'")
    while True:
        cleanup()
        with db() as con:
            job = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if job:
                con.execute("UPDATE jobs SET status='working', started=? WHERE id=?", (time.time(), job["id"]))
        if job:
            process(job)
        else:
            wake.wait(POLL_SECONDS)
            wake.clear()


if __name__ == "__main__":
    migrate()
    print("worker started", flush=True)
    run()

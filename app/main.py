"""The whole web app: one form, a status page, downloads, and the fake-door pack button."""
import os
import re
import shutil
import sqlite3
import threading
import time
import traceback
import uuid
from contextlib import contextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .extract import RejectedBook, book_title, check_extension, extract
from .narrate import narrate

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
KEEP_HOURS = float(os.environ.get("KEEP_HOURS", "24"))
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "1500000"))

PACKS = [
    {"id": "one", "name": "1 book", "price": "€9", "note": "up to ~10 hours of audio"},
    {"id": "four", "name": "4 books", "price": "€29", "note": "€7.25 per book"},
    {"id": "twelve", "name": "12 books", "price": "€79", "note": "€6.58 per book, for authors"},
]

os.makedirs(os.path.join(DATA, "jobs"), exist_ok=True)
DB = os.path.join(DATA, "app.db")

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@contextmanager
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


with db() as con:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, email TEXT, filename TEXT, format TEXT, title TEXT,
            chars INTEGER, status TEXT, progress REAL DEFAULT 0, error TEXT,
            audio_seconds REAL, created REAL, started REAL, finished REAL
        );
        CREATE TABLE IF NOT EXISTS events (ts REAL, email TEXT, kind TEXT, detail TEXT);
        """
    )
    # Jobs interrupted by a restart go back in the queue.
    con.execute("UPDATE jobs SET status='queued', progress=0 WHERE status='working'")


def log(email: str, kind: str, detail: str = ""):
    with db() as con:
        con.execute("INSERT INTO events VALUES (?,?,?,?)", (time.time(), email, kind, detail))


def norm_email(email: str) -> str:
    return email.strip().lower()


# ---------- pages ----------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "home.html", {"packs": PACKS, "max_mb": MAX_MB})


@app.post("/convert", response_class=HTMLResponse)
async def convert(
    request: Request,
    book: UploadFile = File(...),
    email: str = Form(...),
    owns: bool = Form(False),
):
    email = norm_email(email)

    def again(msg):
        log(email, "rejected", msg)
        return templates.TemplateResponse(
            request, "home.html", {"packs": PACKS, "max_mb": MAX_MB, "error": msg, "email": email},
            status_code=400,
        )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return again("Please enter a valid email address.")
    if not owns:
        return again("Please confirm you own this DRM-free book and it is for personal use.")

    with db() as con:
        used = con.execute(
            "SELECT id FROM jobs WHERE email=? AND status NOT IN ('rejected','failed') LIMIT 1",
            (email,),
        ).fetchone()
    if used:
        log(email, "second_book_attempt", book.filename or "")
        return templates.TemplateResponse(
            request, "pricing.html", {"packs": PACKS, "email": email, "first_job": used["id"]},
            status_code=402,
        )

    try:
        ext = check_extension(book.filename or "")
    except RejectedBook as e:
        return again(str(e))

    job_id = uuid.uuid4().hex[:12]
    jobdir = os.path.join(DATA, "jobs", job_id)
    os.makedirs(jobdir)
    src = os.path.join(jobdir, "source" + ext)
    size = 0
    with open(src, "wb") as f:
        while chunk := await book.read(1 << 20):
            size += len(chunk)
            if size > MAX_MB << 20:
                shutil.rmtree(jobdir)
                return again(f"That file is over {MAX_MB} MB.")
            f.write(chunk)

    try:
        chapters = extract(src, ext)
    except RejectedBook as e:
        shutil.rmtree(jobdir)
        return again(str(e))
    chars = sum(len(c.text) for c in chapters)
    if chars > MAX_CHARS:
        shutil.rmtree(jobdir)
        return again(f"This book is too long for the preview ({chars:,} characters).")

    title = book_title(src, ext, os.path.splitext(book.filename)[0])
    with db() as con:
        con.execute(
            "INSERT INTO jobs (id,email,filename,format,title,chars,status,created) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (job_id, email, book.filename, ext[1:], title, chars, "queued", time.time()),
        )
    log(email, "upload", f"{job_id} {ext[1:]} {chars} chars {len(chapters)} chapters")
    wake.set()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    with db() as con:
        job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        ahead = con.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','working') AND created < ?",
            (job["created"] if job else 0,),
        ).fetchone()[0]
    if not job:
        return HTMLResponse("Not found", status_code=404)
    eta = None
    if job["status"] == "working" and job["progress"] > 0.02:
        elapsed = time.time() - job["started"]
        eta = elapsed / job["progress"] - elapsed
    return templates.TemplateResponse(
        request, "job.html", {"job": job, "eta": eta, "ahead": ahead, "packs": PACKS, "keep": KEEP_HOURS}
    )


@app.get("/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str):
    if kind not in ("m4b", "srt"):
        return HTMLResponse("Not found", status_code=404)
    with db() as con:
        job = con.execute("SELECT * FROM jobs WHERE id=? AND status='done'", (job_id,)).fetchone()
    path = os.path.join(DATA, "jobs", job_id, f"book.{kind}")
    if not job or not os.path.exists(path):
        return HTMLResponse("Not found or expired", status_code=404)
    log(job["email"], "download", f"{job_id} {kind}")
    safe = re.sub(r"[^\w\- ]+", "", job["title"]).strip() or "audiobook"
    return FileResponse(path, filename=f"{safe}.{kind}")


@app.post("/buy", response_class=HTMLResponse)
def buy(request: Request, pack: str = Form(...), email: str = Form("")):
    log(norm_email(email), "buy_click", pack)
    chosen = next((p for p in PACKS if p["id"] == pack), PACKS[0])
    return templates.TemplateResponse(request, "thanks.html", {"pack": chosen})


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    with db() as con:
        counts = {
            r["kind"]: (r["n"], r["people"])
            for r in con.execute(
                "SELECT kind, COUNT(*) n, COUNT(DISTINCT email) people FROM events GROUP BY kind"
            )
        }
        clicks = con.execute(
            "SELECT detail, COUNT(*) n FROM events WHERE kind='buy_click' GROUP BY detail"
        ).fetchall()
        speed = con.execute(
            "SELECT SUM(audio_seconds) audio, SUM(finished-started) wall, COUNT(*) n "
            "FROM jobs WHERE status IN ('done','expired') AND audio_seconds IS NOT NULL"
        ).fetchone()
    return templates.TemplateResponse(
        request, "stats.html", {"counts": counts, "clicks": clicks, "speed": speed}
    )


# ---------- background worker ----------

wake = threading.Event()


def run_job(job):
    jobdir = os.path.join(DATA, "jobs", job["id"])
    ext = "." + job["format"]
    last = [0.0]

    def progress(done, total):
        if time.time() - last[0] > 3:
            last[0] = time.time()
            with db() as con:
                con.execute("UPDATE jobs SET progress=? WHERE id=?", (done / total, job["id"]))

    chapters = extract(os.path.join(jobdir, "source" + ext), ext)
    _, _, seconds = narrate(chapters, job["title"], jobdir, progress)
    os.remove(os.path.join(jobdir, "source" + ext))
    return seconds


def cleanup():
    cutoff = time.time() - KEEP_HOURS * 3600
    with db() as con:
        old = con.execute(
            "SELECT id FROM jobs WHERE status IN ('done','failed') AND finished < ?", (cutoff,)
        ).fetchall()
        for row in old:
            shutil.rmtree(os.path.join(DATA, "jobs", row["id"]), ignore_errors=True)
            con.execute("UPDATE jobs SET status='expired' WHERE id=?", (row["id"],))


def worker():
    while True:
        cleanup()
        with db() as con:
            job = con.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if job:
                con.execute(
                    "UPDATE jobs SET status='working', started=? WHERE id=?", (time.time(), job["id"])
                )
        if not job:
            wake.wait(60)
            wake.clear()
            continue
        try:
            seconds = run_job(job)
            with db() as con:
                con.execute(
                    "UPDATE jobs SET status='done', progress=1, audio_seconds=?, finished=? WHERE id=?",
                    (seconds, time.time(), job["id"]),
                )
            log(job["email"], "done", f"{job['id']} {seconds:.0f}s audio")
        except Exception as e:
            traceback.print_exc()
            with db() as con:
                con.execute(
                    "UPDATE jobs SET status='failed', error=?, finished=? WHERE id=?",
                    (str(e)[:500], time.time(), job["id"]),
                )
            log(job["email"], "failed", f"{job['id']} {e}")


@app.on_event("startup")
def start_worker():
    threading.Thread(target=worker, daemon=True).start()

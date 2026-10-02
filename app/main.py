"""The whole web app: upload, choose what to narrate, confirm, status page, downloads, fake-door packs.

An upload becomes a job with status 'draft', owned by a cookie, until the user
confirms it. Drafts nobody confirms are deleted after DRAFT_HOURS.
"""
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import traceback
import uuid
from contextlib import contextmanager

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import sections as S
from .extract import RejectedBook, book_title, check_extension, extract
from .narrate import VOICE, VOICE_IDS, VOICES, narrate

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
KEEP_HOURS = float(os.environ.get("KEEP_HOURS", "24"))
DRAFT_HOURS = float(os.environ.get("DRAFT_HOURS", "2"))
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "1500000"))
COOKIE = "nid"

PACKS = [
    {"id": "one", "name": "1 book", "price": "€9", "note": "up to ~10 hours of audio"},
    {"id": "four", "name": "4 books", "price": "€29", "note": "€7.25 per book"},
    {"id": "twelve", "name": "12 books", "price": "€79", "note": "€6.58 per book, for authors"},
]

os.makedirs(os.path.join(DATA, "jobs"), exist_ok=True)
DB = os.path.join(DATA, "app.db")

app = FastAPI()
HERE = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
templates.env.filters["duration"] = lambda s: (
    f"{int(s // 3600)} h {int(s % 3600 // 60)} min" if s >= 3600 else f"{max(1, round(s / 60))} min"
)


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
    have = {r["name"] for r in con.execute("PRAGMA table_info(jobs)")}
    for col in ("owner TEXT", "voice TEXT"):
        if col.split()[0] not in have:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
    # Jobs interrupted by a restart go back in the queue.
    con.execute("UPDATE jobs SET status='queued', progress=0 WHERE status='working'")


def log(email: str, kind: str, detail: str = ""):
    with db() as con:
        con.execute("INSERT INTO events VALUES (?,?,?,?)", (time.time(), email, kind, detail))


def norm_email(email: str) -> str:
    return email.strip().lower()


def folder(job_id: str) -> str:
    return os.path.join(DATA, "jobs", job_id)


def page(request: Request, name: str, ctx: dict, status_code: int = 200, owner: str | None = None):
    resp = templates.TemplateResponse(request, name, {"packs": PACKS, "max_mb": MAX_MB, "keep": KEEP_HOURS, **ctx}, status_code=status_code)
    if owner:
        resp.set_cookie(COOKIE, owner, max_age=30 * 86400, httponly=True, samesite="lax")
    return resp


def draft_for(request: Request, job_id: str):
    """The draft, if it exists and belongs to whoever is asking."""
    owner = request.cookies.get(COOKIE)
    if not owner or not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return None
    with db() as con:
        return con.execute(
            "SELECT * FROM jobs WHERE id=? AND owner=? AND status='draft'", (job_id, owner)
        ).fetchone()


def summary(sections: list[dict]) -> dict:
    chars = S.included_chars(sections)
    return {"chars": chars, "seconds": S.audio_seconds(chars), "credits": S.credits(chars)}


# ---------- step 1: landing page and upload ----------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return page(request, "home.html", {"sample": VOICE})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, book: UploadFile = File(...)):
    owner = request.cookies.get(COOKIE) or secrets.token_hex(16)

    def again(msg):
        log("", "rejected", msg)
        return page(request, "home.html", {"sample": VOICE, "error": msg}, 400, owner)

    try:
        ext = check_extension(book.filename or "")
    except RejectedBook as e:
        return again(str(e))

    job_id = uuid.uuid4().hex[:12]
    jobdir = folder(job_id)
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
        return again(f"This book is too long for us right now ({chars:,} characters).")

    S.save(jobdir, S.initial(chapters))
    title = book_title(src, ext, os.path.splitext(book.filename)[0])
    with db() as con:
        con.execute(
            "INSERT INTO jobs (id,filename,format,title,chars,status,created,owner,voice) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, book.filename, ext[1:], title, chars, "draft", time.time(), owner, VOICE),
        )
    log("", "upload", f"{job_id} {ext[1:]} {chars} chars {len(chapters)} sections")
    resp = RedirectResponse(f"/drafts/{job_id}", status_code=303)
    resp.set_cookie(COOKIE, owner, max_age=30 * 86400, httponly=True, samesite="lax")
    return resp


# ---------- step 2: choose what to narrate, and the voice ----------


@app.get("/drafts/{job_id}", response_class=HTMLResponse)
def choose(request: Request, job_id: str):
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    secs = S.load(folder(job_id))
    return page(request, "choose.html", {
        "job": job, "sections": secs, "voices": VOICES, **summary(secs),
        "cps": S.CHARS_PER_SECOND, "per_credit": S.CHARS_PER_CREDIT,
    })


@app.post("/drafts/{job_id}", response_class=HTMLResponse)
async def choose_save(request: Request, job_id: str):
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    form = await request.form()
    secs = S.load(folder(job_id))
    for i, s in enumerate(secs):
        s["include"] = form.get(f"include_{i}") == "on"
        # Textareas are only enabled (and so only posted) once the user opens them.
        if f"text_{i}" in form:
            s["text"] = S.clean_edit(form[f"text_{i}"])
        if not s["text"]:
            s["include"] = False
    voice = form.get("voice") if form.get("voice") in VOICE_IDS else VOICE
    S.save(folder(job_id), secs)
    with db() as con:
        con.execute("UPDATE jobs SET voice=? WHERE id=?", (voice, job_id))
    if not S.chapters(secs):
        return page(request, "choose.html", {
            "job": job, "sections": secs, "voices": VOICES, **summary(secs),
            "cps": S.CHARS_PER_SECOND, "per_credit": S.CHARS_PER_CREDIT,
            "error": "Tick at least one section to narrate.",
        }, 400)
    return RedirectResponse(f"/drafts/{job_id}/confirm", status_code=303)


# ---------- step 3: confirm (email + ownership; sign-in and payment come later) ----------


@app.get("/drafts/{job_id}/confirm", response_class=HTMLResponse)
def confirm(request: Request, job_id: str):
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    return confirm_page(request, job)


def confirm_page(request, job, error=None, email="", status_code=200):
    secs = S.load(folder(job["id"]))
    voice = next(v for v in VOICES if v["id"] == (job["voice"] or VOICE))
    return page(request, "confirm.html", {
        "job": job, "voice": voice, "count": len(S.chapters(secs)), **summary(secs),
        "error": error, "email": email,
    }, status_code)


@app.post("/drafts/{job_id}/confirm", response_class=HTMLResponse)
def confirm_go(request: Request, job_id: str, email: str = Form(""), owns: bool = Form(False)):
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    email = norm_email(email)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return confirm_page(request, job, "Please enter a valid email address.", email, 400)
    if not owns:
        return confirm_page(request, job, "Please confirm you own this DRM-free book and it is for personal use.", email, 400)

    with db() as con:
        used = con.execute(
            "SELECT id FROM jobs WHERE email=? AND status NOT IN ('draft','abandoned','rejected','failed') LIMIT 1",
            (email,),
        ).fetchone()
    if used:
        log(email, "second_book_attempt", job["filename"] or "")
        return page(request, "pricing.html", {"email": email, "first_job": used["id"]}, 402)

    secs = S.load(folder(job_id))
    chars = S.included_chars(secs)
    if S.credits(chars) > 1:
        return confirm_page(
            request, job,
            f"Your free book covers up to about {S.audio_seconds(S.CHARS_PER_CREDIT) / 3600:.0f} hours of audio. "
            "Go back and untick some sections.", email, 400,
        )
    with db() as con:
        con.execute(
            "UPDATE jobs SET email=?, chars=?, status='queued', created=? WHERE id=?",
            (email, chars, time.time(), job_id),
        )
    skipped = sum(1 for s in secs if not s["include"])
    log(email, "confirmed", f"{job_id} {chars} chars voice={job['voice']} skipped={skipped}/{len(secs)}")
    wake.set()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def gone(request: Request):
    return page(request, "gone.html", {"hours": DRAFT_HOURS}, 404)


# ---------- status page and downloads ----------


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    with db() as con:
        job = con.execute("SELECT * FROM jobs WHERE id=? AND status!='draft'", (job_id,)).fetchone()
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
    return page(request, "job.html", {"job": job, "eta": eta, "ahead": ahead})


@app.get("/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str):
    if kind not in ("m4b", "srt"):
        return HTMLResponse("Not found", status_code=404)
    with db() as con:
        job = con.execute("SELECT * FROM jobs WHERE id=? AND status='done'", (job_id,)).fetchone()
    path = os.path.join(folder(job_id), f"book.{kind}")
    if not job or not os.path.exists(path):
        return HTMLResponse("Not found or expired", status_code=404)
    log(job["email"], "download", f"{job_id} {kind}")
    safe = re.sub(r"[^\w\- ]+", "", job["title"]).strip() or "audiobook"
    return FileResponse(path, filename=f"{safe}.{kind}")


@app.post("/buy", response_class=HTMLResponse)
def buy(request: Request, pack: str = Form(...), email: str = Form("")):
    log(norm_email(email), "buy_click", pack)
    chosen = next((p for p in PACKS if p["id"] == pack), PACKS[0])
    return page(request, "thanks.html", {"pack": chosen})


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
        voices = con.execute(
            "SELECT voice, COUNT(*) n FROM jobs WHERE status NOT IN ('draft','abandoned') GROUP BY voice"
        ).fetchall()
        speed = con.execute(
            "SELECT SUM(audio_seconds) audio, SUM(finished-started) wall, SUM(chars) chars, COUNT(*) n "
            "FROM jobs WHERE status IN ('done','expired') AND audio_seconds IS NOT NULL"
        ).fetchone()
    return page(request, "stats.html", {"counts": counts, "clicks": clicks, "voices": voices, "speed": speed})


# ---------- background worker ----------

wake = threading.Event()


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

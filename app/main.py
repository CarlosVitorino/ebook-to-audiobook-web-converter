"""The conversion flow: upload, choose what to narrate, sign in, confirm, status page, downloads.

An upload becomes a job with status 'draft', owned by a cookie (and by the user
once they sign in), until it is confirmed. Drafts nobody confirms are deleted
after DRAFT_HOURS. Confirming spends credits; a failed conversion refunds them.
"""
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import accounts, mail
from . import sections as S
from .db import DATA, db, log, migrate
from .extract import RejectedBook, book_title, check_extension, extract
from .narrate import VOICE, VOICE_IDS, VOICES, narrate
from .web import BASE_URL, COOKIE, KEEP_HOURS, MAX_MB, PACKS, current_user, page, secret_key

DRAFT_HOURS = float(os.environ.get("DRAFT_HOURS", "2"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "1500000"))

migrate()
app = FastAPI()
app.add_middleware(
    SessionMiddleware, secret_key=secret_key(), session_cookie="session", max_age=90 * 86400,
    same_site="lax", https_only=BASE_URL.startswith("https://"),
)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(accounts.router)


def folder(job_id: str) -> str:
    return os.path.join(DATA, "jobs", job_id)


def draft_for(request: Request, job_id: str):
    """The draft, if it exists and belongs to whoever is asking (this browser, or this account)."""
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return None
    owner = request.cookies.get(COOKIE) or "-"
    user = current_user(request)
    with db() as con:
        return con.execute(
            "SELECT * FROM jobs WHERE id=? AND status='draft' AND (owner=? OR user_id=?)",
            (job_id, owner, user["id"] if user else -1),
        ).fetchone()


def summary(sections: list[dict]) -> dict:
    chars = S.included_chars(sections)
    return {"chars": chars, "seconds": S.audio_seconds(chars), "credits": S.credits(chars)}


def signin_redirect(next_url: str):
    return RedirectResponse(f"/signin?next={next_url}", status_code=303)


# ---------- step 1: landing page and upload ----------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    books = []
    if user:
        with db() as con:
            books = con.execute(
                "SELECT * FROM jobs WHERE user_id=? AND status IN ('queued','working','done','failed') "
                "ORDER BY created DESC LIMIT 20",
                (user["id"],),
            ).fetchall()
    return page(request, "home.html", {"sample": VOICE, "books": books})


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, book: UploadFile = File(...)):
    owner = request.cookies.get(COOKIE) or secrets.token_hex(16)
    user = current_user(request)

    def again(msg):
        log(user["email"] if user else "", "rejected", msg)
        return page(request, "home.html", {"sample": VOICE, "error": msg, "books": []}, 400, owner)

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
            "INSERT INTO jobs (id,filename,format,title,chars,status,created,owner,voice,user_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, book.filename, ext[1:], title, chars, "draft", time.time(), owner, VOICE,
             user["id"] if user else None),
        )
    log(user["email"] if user else "", "upload", f"{job_id} {ext[1:]} {chars} chars {len(chapters)} sections")
    resp = RedirectResponse(f"/drafts/{job_id}", status_code=303)
    resp.set_cookie(COOKIE, owner, max_age=30 * 86400, httponly=True, samesite="lax")
    return resp


# ---------- step 2: choose what to narrate, and the voice ----------


def choose_page(request, job, secs, error=None, status_code=200):
    return page(request, "choose.html", {
        "job": job, "sections": secs, "voices": VOICES, **summary(secs),
        "cps": S.CHARS_PER_SECOND, "per_credit": S.CHARS_PER_CREDIT, "error": error,
    }, status_code)


@app.get("/drafts/{job_id}", response_class=HTMLResponse)
def choose(request: Request, job_id: str):
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    return choose_page(request, job, S.load(folder(job_id)))


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
        return choose_page(request, job, secs, "Tick at least one section to narrate.", 400)
    nxt = f"/drafts/{job_id}/confirm"
    return RedirectResponse(nxt, status_code=303) if current_user(request) else signin_redirect(nxt)


# ---------- step 3 is sign-in (accounts.py); step 4: confirm and spend credits ----------


def confirm_page(request, job, user, error=None, status_code=200):
    secs = S.load(folder(job["id"]))
    voice = next(v for v in VOICES if v["id"] == (job["voice"] or VOICE))
    return page(request, "confirm.html", {
        "job": job, "voice": voice, "count": len(S.chapters(secs)), **summary(secs), "error": error,
    }, status_code)


@app.get("/drafts/{job_id}/confirm", response_class=HTMLResponse)
def confirm(request: Request, job_id: str):
    user = current_user(request)
    if not user:
        return signin_redirect(f"/drafts/{job_id}/confirm")
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    return confirm_page(request, job, user)


@app.post("/drafts/{job_id}/confirm", response_class=HTMLResponse)
def confirm_go(request: Request, job_id: str, owns: bool = Form(False)):
    user = current_user(request)
    if not user:
        return signin_redirect(f"/drafts/{job_id}/confirm")
    job = draft_for(request, job_id)
    if not job:
        return gone(request)
    if not owns:
        return confirm_page(request, job, user, "Please confirm you own this DRM-free book and it is for personal use.", 400)

    secs = S.load(folder(job_id))
    chars = S.included_chars(secs)
    needed = S.credits(chars)
    with db() as con:
        # One transaction for check-and-spend, so a double click can't spend twice or overdraw.
        con.execute("BEGIN IMMEDIATE")
        have = con.execute("SELECT COALESCE(SUM(delta),0) FROM credits WHERE user_id=?", (user["id"],)).fetchone()[0]
        if have >= needed:
            started = con.execute(
                "UPDATE jobs SET email=?, user_id=?, chars=?, credits_used=?, status='queued', created=? "
                "WHERE id=? AND status='draft'",
                (user["email"], user["id"], chars, needed, time.time(), job_id),
            ).rowcount
            if started:
                con.execute(
                    "INSERT INTO credits (user_id, delta, reason, ref, created) VALUES (?,?,'conversion',?,?)",
                    (user["id"], -needed, job_id, time.time()),
                )
    if have < needed:
        log(user["email"], "second_book_attempt", f"{job_id} needs {needed} has {have}")
        return page(request, "pricing.html", {"job": job, "needed": needed, "have": have}, 402)
    skipped = sum(1 for s in secs if not s["include"])
    log(user["email"], "confirmed", f"{job_id} {chars} chars voice={job['voice']} skipped={skipped}/{len(secs)} credits={needed}")
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
def buy(request: Request, pack: str = Form(...)):
    user = current_user(request)
    log(user["email"] if user else "", "buy_click", pack)
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
        signins = con.execute(
            "SELECT detail, COUNT(*) n FROM events WHERE kind='signup' GROUP BY detail"
        ).fetchall()
        voices = con.execute(
            "SELECT voice, COUNT(*) n FROM jobs WHERE status NOT IN ('draft','abandoned') GROUP BY voice"
        ).fetchall()
        speed = con.execute(
            "SELECT SUM(audio_seconds) audio, SUM(finished-started) wall, SUM(chars) chars, COUNT(*) n "
            "FROM jobs WHERE status IN ('done','expired') AND audio_seconds IS NOT NULL"
        ).fetchone()
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return page(request, "stats.html", {
        "counts": counts, "clicks": clicks, "signins": signins, "voices": voices, "speed": speed, "users": users,
    })


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
                f"The files are deleted {KEEP_HOURS:.0f} hours from now, so download them soon."
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


@app.on_event("startup")
def start_worker():
    threading.Thread(target=worker, daemon=True).start()

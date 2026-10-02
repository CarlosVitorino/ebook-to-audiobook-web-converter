"""The conversion flow: upload, choose what to narrate, sign in, confirm, status page, downloads.

An upload becomes a job with status 'draft', owned by a cookie (and by the user
once they sign in), until it is confirmed. Drafts nobody confirms are deleted
after DRAFT_HOURS. Confirming spends credits; a failed conversion refunds them.
"""
import base64
import os
import re
import secrets
import shutil
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import abuse, accounts, payments, worker
from .credits import start_draft
from . import sections as S
from .db import DATA, db, log, migrate
from .extract import RejectedBook, book_title, check_extension, extract
from .narrate import VOICE, VOICE_IDS, VOICES
from .web import BASE_URL, COOKIE, DRAFT_HOURS, MAX_MB, current_user, page, secret_key

MAX_CHARS = int(os.environ.get("MAX_CHARS", "1500000"))
UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "10"))
STATS_PASSWORD = os.environ.get("STATS_PASSWORD", "")

migrate()
app = FastAPI()
app.add_middleware(
    SessionMiddleware, secret_key=secret_key(), session_cookie="session", max_age=90 * 86400,
    same_site="lax", https_only=BASE_URL.startswith("https://"),
)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.include_router(accounts.router)
app.include_router(payments.router)


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
    if abuse.limited("upload", abuse.ip_key(request), UPLOADS_PER_HOUR, 3600):
        return page(request, "home.html", {"sample": VOICE, "books": [], "error": "Too many uploads from your network. Please try again in an hour."}, 429, owner)

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

    started, have, needed = start_draft(user["id"], user["email"], job_id)
    if not started:
        if have >= needed:  # confirmed twice, or the draft went away in between
            return RedirectResponse(f"/jobs/{job_id}", status_code=303)
        log(user["email"], "second_book_attempt", f"{job_id} needs {needed} has {have}")
        return page(request, "pricing.html", {"job": job, "needed": needed, "have": have, "draft": job_id}, 402)
    secs = S.load(folder(job_id))
    skipped = sum(1 for s in secs if not s["include"])
    log(user["email"], "confirmed", f"{job_id} {S.included_chars(secs)} chars voice={job['voice']} skipped={skipped}/{len(secs)} credits={needed}")
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


# Legal pages. Fill the LEGAL_* settings before launch; until then the pages say they're drafts.
LEGAL = {
    "owner": os.environ.get("LEGAL_OWNER") or "[legal name of the business]",
    "contact": os.environ.get("LEGAL_CONTACT") or "hello@narrator.guru",
    "law": os.environ.get("LEGAL_LAW") or "[country]",
    "email_provider": os.environ.get("LEGAL_EMAIL_PROVIDER") or "Our email provider",
    "host": os.environ.get("LEGAL_HOST") or "Hetzner",
    "updated": "2 October 2026",
}


def legal_page(name: str):
    def show(request: Request):
        draft = "[" in LEGAL["owner"] or "[" in LEGAL["law"]
        return page(request, f"legal/{name}.html", {
            **LEGAL, "draft_hours": DRAFT_HOURS, "draft_note": "Draft: not yet reviewed." if draft else "",
        })
    return show


for _name in ("terms", "privacy", "refunds"):
    app.add_api_route(f"/{_name}", legal_page(_name), methods=["GET"], response_class=HTMLResponse)


def stats_allowed(request: Request) -> bool:
    """HTTP Basic auth with STATS_PASSWORD (any user name). Without one, only on a localhost site."""
    if not STATS_PASSWORD:
        return BASE_URL.startswith(("http://localhost", "http://127.0.0.1"))
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        _, _, given = base64.b64decode(auth[6:]).decode().partition(":")
    except ValueError:
        return False
    return secrets.compare_digest(given.encode(), STATS_PASSWORD.encode())


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    if not stats_allowed(request):
        return HTMLResponse("Stats are private.", status_code=401, headers={"WWW-Authenticate": 'Basic realm="stats"'})
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
        sales = con.execute(
            "SELECT pack, COUNT(*) n, SUM(amount_cents) cents, currency FROM payments WHERE status='paid' GROUP BY pack, currency"
        ).fetchall()
        payers = con.execute("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status='paid'").fetchone()[0]
        started = con.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    return page(request, "stats.html", {
        "counts": counts, "clicks": clicks, "signins": signins, "voices": voices, "speed": speed, "users": users,
        "sales": sales, "payers": payers, "checkouts": started,
    })


# ---------- background worker ----------


@app.on_event("startup")
def start_worker():
    if os.environ.get("RUN_WORKER", "1") == "1":
        threading.Thread(target=worker.run, daemon=True).start()

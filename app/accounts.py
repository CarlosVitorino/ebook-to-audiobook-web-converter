"""Sign-in with Google or an emailed link. Accounts exist only to hold credits.

Both ways end in sign_in(): find or create the user by email, give a new user
their free book, and attach any draft this browser uploaded before signing in.
"""
import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import mail
from .db import db, log
from .web import BASE_URL, COOKIE, page, safe_next

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
LINK_MINUTES = 20
LINKS_PER_HOUR = 5

router = APIRouter()


def sign_in(request: Request, email: str, method: str, google_sub: str | None = None) -> int:
    email = email.strip().lower()
    with db() as con:
        user = None
        if google_sub:
            user = con.execute("SELECT * FROM users WHERE google_sub=?", (google_sub,)).fetchone()
        user = user or con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user:
            uid = user["id"]
            if google_sub and not user["google_sub"]:
                con.execute("UPDATE users SET google_sub=? WHERE id=?", (google_sub, uid))
        else:
            uid = con.execute(
                "INSERT INTO users (email, google_sub, created) VALUES (?,?,?)", (email, google_sub, time.time())
            ).lastrowid
            # Someone who already had a free book by typing this email (before accounts) doesn't get another.
            had_free = con.execute(
                "SELECT 1 FROM jobs WHERE email=? AND user_id IS NULL "
                "AND status IN ('queued','working','done','expired') LIMIT 1",
                (email,),
            ).fetchone()
            if not had_free:
                con.execute(
                    "INSERT INTO credits (user_id, delta, reason, created) VALUES (?,1,'free',?)", (uid, time.time())
                )
        owner = request.cookies.get(COOKIE)
        if owner:
            con.execute("UPDATE jobs SET user_id=? WHERE owner=? AND status='draft' AND user_id IS NULL", (uid, owner))
    if not user:
        log(email, "signup", method)
    log(email, "signin", method)
    request.session.clear()
    request.session["uid"] = uid
    return uid


@router.get("/signin", response_class=HTMLResponse)
def signin_page(request: Request, next: str = "/"):
    return page(request, "signin.html", {"next": safe_next(next), "google": bool(GOOGLE_CLIENT_ID)})


@router.post("/signout")
def signout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------- emailed sign-in link ----------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/signin/email", response_class=HTMLResponse)
def email_link(request: Request, email: str = Form(""), next: str = Form("/")):
    email, nxt = email.strip().lower(), safe_next(next)
    ctx = {"next": nxt, "google": bool(GOOGLE_CLIENT_ID), "email": email}
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return page(request, "signin.html", {**ctx, "error": "Please enter a valid email address."}, 400)
    with db() as con:
        recent = con.execute(
            "SELECT COUNT(*) FROM login_tokens WHERE email=? AND created > ?", (email, time.time() - 3600)
        ).fetchone()[0]
        if recent >= LINKS_PER_HOUR:
            return page(request, "signin.html", {**ctx, "error": "We've sent several links already. Check your inbox (and spam), or try again in an hour."}, 429)
        token = secrets.token_urlsafe(32)
        con.execute(
            "INSERT INTO login_tokens (hash, email, next, created) VALUES (?,?,?,?)",
            (_hash(token), email, nxt, time.time()),
        )
    mail.send(email, "Your narrator.guru sign-in link", (
        f"Click to sign in to narrator.guru:\n\n{BASE_URL}/signin/email/{token}\n\n"
        f"The link works once, for {LINK_MINUTES} minutes. If you didn't ask for it, ignore this email."
    ))
    log(email, "signin_link_sent")
    return page(request, "signin_sent.html", {"email": email, "dev": not mail.SMTP_HOST})


def _valid_token(token: str):
    with db() as con:
        return con.execute(
            "SELECT * FROM login_tokens WHERE hash=? AND used IS NULL AND created > ?",
            (_hash(token), time.time() - LINK_MINUTES * 60),
        ).fetchone()


@router.get("/signin/email/{token}", response_class=HTMLResponse)
def email_link_open(request: Request, token: str):
    # A button, not an instant sign-in: mail scanners open links, and would use up the token.
    row = _valid_token(token)
    if not row:
        return page(request, "signin.html", {"next": "/", "google": bool(GOOGLE_CLIENT_ID), "error": "That sign-in link has expired or was already used. Get a new one below."}, 400)
    return page(request, "signin_confirm.html", {"email": row["email"], "token": token})


@router.post("/signin/email/{token}")
def email_link_use(request: Request, token: str):
    row = _valid_token(token)
    if row:
        with db() as con:
            claimed = con.execute(
                "UPDATE login_tokens SET used=? WHERE hash=? AND used IS NULL", (time.time(), row["hash"])
            ).rowcount
        if claimed:
            sign_in(request, row["email"], "email")
            return RedirectResponse(safe_next(row["next"]), status_code=303)
    return RedirectResponse("/signin", status_code=303)


# ---------- Google ----------


@router.get("/signin/google")
def google_start(request: Request, next: str = "/"):
    if not GOOGLE_CLIENT_ID:
        return RedirectResponse("/signin", status_code=303)
    state = secrets.token_urlsafe(24)
    request.session["oauth"] = {"state": state, "next": safe_next(next)}
    query = urlencode({
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": f"{BASE_URL}/signin/google/callback",
        "response_type": "code", "scope": "openid email", "state": state, "prompt": "select_account",
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}", status_code=303)


@router.get("/signin/google/callback", response_class=HTMLResponse)
def google_callback(request: Request, code: str = "", state: str = ""):
    saved = request.session.pop("oauth", None)
    fail = lambda msg: page(request, "signin.html", {"next": (saved or {}).get("next", "/"), "google": True, "error": msg}, 400)
    if not saved or not code or not secrets.compare_digest(state, saved["state"]):
        return fail("Google sign-in didn't complete. Please try again.")
    try:
        tokens = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": f"{BASE_URL}/signin/google/callback", "grant_type": "authorization_code",
        }, timeout=15).raise_for_status().json()
        info = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=15,
        ).raise_for_status().json()
    except (httpx.HTTPError, KeyError, ValueError):
        return fail("Google sign-in didn't complete. Please try again.")
    if not info.get("email") or not info.get("email_verified") or not info.get("sub"):
        return fail("Your Google account has no verified email. Use the email link instead.")
    sign_in(request, info["email"], "google", google_sub=info["sub"])
    return RedirectResponse(saved["next"], status_code=303)

"""Shared by every route: settings, templates, and who is signed in."""
import os
import secrets

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .db import DATA, db

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
KEEP_HOURS = float(os.environ.get("KEEP_HOURS", "168"))  # finished books are kept 7 days
DRAFT_HOURS = float(os.environ.get("DRAFT_HOURS", "2"))  # unconfirmed uploads
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
# How many times faster than real time the server narrates, for the "ready in about" estimate.
NARRATION_SPEED = float(os.environ.get("NARRATION_SPEED", "5"))
COOKIE = "nid"  # anonymous owner of drafts, from before sign-in

# Prices decided by Carlos, 2026-10-02. "books" is how many credits the pack adds.
PACKS = [
    {"id": "one", "name": "1 book", "books": 1, "price": "€2.99", "per_book": "€2.99"},
    {"id": "five", "name": "5 books", "books": 5, "price": "€9.95", "per_book": "€1.99"},
    {"id": "fifteen", "name": "15 books", "books": 15, "price": "€24.95", "per_book": "€1.66"},
]


def secret_key() -> str:
    """SECRET_KEY signs the session cookie. Without one, a key is made once and kept in DATA."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(DATA, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    with open(path) as f:
        return f.read().strip()


def keep_text(hours: float) -> str:
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"


templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
templates.env.filters["keep_text"] = keep_text
templates.env.filters["duration"] = lambda s: (
    f"{int(s // 3600)} h {int(s % 3600 // 60)} min" if s >= 3600 else f"{max(1, round(s / 60))} min"
)


def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    with db() as con:
        return con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def balance(user_id: int) -> int:
    with db() as con:
        return con.execute("SELECT COALESCE(SUM(delta),0) FROM credits WHERE user_id=?", (user_id,)).fetchone()[0]


def page(request: Request, name: str, ctx: dict, status_code: int = 200, owner: str | None = None):
    user = current_user(request)
    resp = templates.TemplateResponse(request, name, {
        "packs": PACKS, "max_mb": MAX_MB, "keep": KEEP_HOURS, "speed": NARRATION_SPEED,
        "user": user, "balance": balance(user["id"]) if user else 0, **ctx,
    }, status_code=status_code)
    if owner:
        resp.set_cookie(COOKIE, owner, max_age=30 * 86400, httponly=True, samesite="lax")
    return resp


def safe_next(url: str | None, default: str = "/") -> str:
    """Only same-site paths, so a sign-in link can't bounce someone to another site."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default

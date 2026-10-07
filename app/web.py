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
# Where people write about payments, refunds and anything else. Also shown on the legal pages.
CONTACT = os.environ.get("LEGAL_CONTACT") or "hello@narrator.guru"
COOKIE = "nid"  # anonymous owner of drafts, from before sign-in

# Prices decided by Carlos, 2026-10-02. "books" is how many credits the pack adds.
PACKS = [
    {"id": "one", "name": "1 book", "books": 1, "price": "€2.99", "amount": "2.99", "per_book": "€2.99"},
    {"id": "five", "name": "5 books", "books": 5, "price": "€9.95", "amount": "9.95", "per_book": "€1.99"},
    {"id": "fifteen", "name": "15 books", "books": 15, "price": "€24.95", "amount": "24.95", "per_book": "€1.66"},
]

# Search engines and AI answer engines read these: keep them short, factual and true.
TAGLINE = "Turn your ebook into an audiobook"
DESCRIPTION = (
    "Convert an EPUB or PDF ebook you own into one M4B audiobook with chapters and captions, "
    "read by a natural voice. First book free, then from €1.66 per book. No subscription."
)
# Pages that may appear in search results; every other page gets noindex.
PUBLIC = {"home.html", "legal/terms.html", "legal/privacy.html", "legal/refunds.html"}


def faq() -> list[tuple[str, str]]:
    """The landing page FAQ, also used for the FAQPage structured data and /llms.txt."""
    one, five, fifteen = PACKS
    return [
        ("Which books work?",
         "DRM-free EPUB and text PDF files, in English. Kindle files, DRM-protected books and scanned PDFs are rejected."),
        ("What do I get?",
         "One M4B audiobook file of the whole book, with chapter markers, plus captions (an SRT file, also built into the M4B). "
         "M4B plays in Apple Books, BookPlayer, Smart AudioBook Player, VLC and most audiobook apps."),
        ("How long does it take?",
         "Your audiobook is ready long before you could finish listening to it: about 40 minutes for The Great Gatsby's 4 hours. "
         "We email you when it's done."),
        ("How much does it cost?",
         f"Your first book is free. After that: {one['name']} {one['price']}, {five['name']} {five['price']} ({five['per_book']} each), "
         f"{fifteen['name']} {fifteen['price']} ({fifteen['per_book']} each). No subscription, and books in your account don't expire. "
         "One book covers up to about 10 hours of audio."),
        ("Why is narrator.guru so cheap?",
         "Because we only charge what it costs to run. narrator.guru is here to help people listen to the books they own, "
         "not to make money from them. The voices come from Kokoro, an open AI voice model that runs on our own server, "
         "so we don't pay an AI company for every word. What you pay covers that server and the payment fees. "
         f"That's why a whole audiobook costs from {fifteen['per_book']} instead of a monthly subscription "
         "or the $1,200 or more a human narrator charges."),
        ("Can I skip the copyright page and the acknowledgements?",
         "Yes. Before converting you see every section of the book and untick what you don't want to hear."),
        ("Can I choose the voice?",
         "Yes: six natural English voices, American and British, female and male. You can listen to each one first."),
        ("Is it legal?",
         "You may convert books you own, free of DRM, for your own listening. Authors and publishers can convert books they hold the rights to. "
         "We don't remove DRM, and we don't keep or share your books."),
        ("What happens to my file?",
         f"Your upload is deleted as soon as the audiobook is made, and the audiobook {keep_text(KEEP_HOURS)} after it's ready."),
    ]


def structured_data() -> dict:
    """schema.org JSON-LD for the landing page: the site, the product with its prices, and the FAQ."""
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": f"{BASE_URL}/#website", "name": "narrator.guru", "url": f"{BASE_URL}/",
             "description": DESCRIPTION, "inLanguage": "en"},
            {"@type": "Organization", "@id": f"{BASE_URL}/#org", "name": "narrator.guru", "url": f"{BASE_URL}/",
             "logo": f"{BASE_URL}/static/icon-512.png"},
            {"@type": "Product", "name": "narrator.guru ebook to audiobook conversion",
             "description": DESCRIPTION, "image": f"{BASE_URL}/static/og.png",
             "brand": {"@id": f"{BASE_URL}/#org"},
             "offers": [{"@type": "Offer", "name": "First book", "price": "0", "priceCurrency": "EUR",
                         "availability": "https://schema.org/InStock", "url": f"{BASE_URL}/"}] + [
                {"@type": "Offer", "name": p["name"], "price": p["amount"], "priceCurrency": "EUR",
                 "availability": "https://schema.org/InStock", "url": f"{BASE_URL}/#prices"} for p in PACKS]},
            {"@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq()]},
        ],
    }


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
        "base_url": BASE_URL, "canonical": BASE_URL + request.url.path, "noindex": name not in PUBLIC,
        "tagline": TAGLINE, "description": DESCRIPTION, "contact": CONTACT,
        **({"faq": faq(), "structured": structured_data()} if name == "home.html" else {}),
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

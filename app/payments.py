"""Buying packs through Creem (creem.io, merchant of record: it handles VAT and the receipt).

1. /buy records a pending payment and sends the buyer to a Creem checkout.
2. Creem calls /webhooks/creem. The signed checkout.completed event is the ONLY thing
   that adds credits, once per payment, however often Creem retries it.
3. If the buyer was trying to convert a book, it starts as soon as the credits land.
4. Creem sends the buyer back to /paid/<request_id>, which waits for step 2.

Without CREEM_API_KEY the Buy buttons keep the PoC's fake door: the click is logged and
the buyer is told payments open soon.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .credits import start_draft
from .db import db, log
from .web import BASE_URL, PACKS, current_user, page

CREEM_API_KEY = os.environ.get("CREEM_API_KEY", "")
CREEM_WEBHOOK_SECRET = os.environ.get("CREEM_WEBHOOK_SECRET", "")
# Test mode by default; set https://api.creem.io with live keys.
CREEM_API_BASE = os.environ.get("CREEM_API_BASE", "https://test-api.creem.io").rstrip("/")
# One Creem product per pack: CREEM_PRODUCT_ONE, CREEM_PRODUCT_FIVE, CREEM_PRODUCT_FIFTEEN.
PRODUCTS = {p["id"]: os.environ.get(f"CREEM_PRODUCT_{p['id'].upper()}", "") for p in PACKS}

router = APIRouter()


def enabled() -> bool:
    return bool(CREEM_API_KEY and CREEM_WEBHOOK_SECRET and all(PRODUCTS.values()))


@router.post("/buy", response_class=HTMLResponse)
def buy(request: Request, pack: str = Form(...), draft: str = Form("")):
    user = current_user(request)
    chosen = next((p for p in PACKS if p["id"] == pack), None)
    if not chosen:
        return RedirectResponse("/#prices", status_code=303)
    log(user["email"] if user else "", "buy_click", pack)
    if not enabled():
        return page(request, "thanks.html", {"pack": chosen})
    if not user:
        return RedirectResponse("/signin?next=/%23prices", status_code=303)
    draft = draft if re.fullmatch(r"[0-9a-f]{12}", draft or "") else None

    request_id = secrets.token_hex(12)
    with db() as con:
        con.execute(
            "INSERT INTO payments (request_id, user_id, pack, books, draft_id, status, created) VALUES (?,?,?,?,?,'pending',?)",
            (request_id, user["id"], pack, chosen["books"], draft, time.time()),
        )
    try:
        resp = httpx.post(f"{CREEM_API_BASE}/v1/checkouts", headers={"x-api-key": CREEM_API_KEY}, json={
            "product_id": PRODUCTS[pack],
            "request_id": request_id,
            "customer": {"email": user["email"]},
            "success_url": f"{BASE_URL}/paid/{request_id}",
            "metadata": {"user_id": str(user["id"]), "pack": pack, "draft_id": draft or ""},
        }, timeout=20)
        resp.raise_for_status()
        url = resp.json()["checkout_url"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log(user["email"], "checkout_error", f"{pack} {e}")
        with db() as con:
            con.execute("UPDATE payments SET status='error' WHERE request_id=?", (request_id,))
        return page(request, "paid.html", {"state": "error"}, 502)
    return RedirectResponse(url, status_code=303)


def _verified(body: bytes, signature: str) -> bool:
    expected = hmac.new(CREEM_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature)


@router.post("/webhooks/creem")
async def webhook(request: Request):
    body = await request.body()
    if not CREEM_WEBHOOK_SECRET or not _verified(body, request.headers.get("creem-signature", "")):
        return JSONResponse({"error": "bad signature"}, status_code=401)
    try:
        event = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "bad json"}, status_code=400)
    kind = event.get("eventType")
    obj = event.get("object") or {}
    if kind == "refund.created":
        # Credits are not clawed back automatically; this shows up in /stats for a human to look at.
        log("", "refund_created", json.dumps(obj)[:500])
    if kind != "checkout.completed":
        return {"ok": True, "ignored": kind}

    order = obj.get("order") or {}
    request_id, order_id = obj.get("request_id") or "", order.get("id") or ""
    product = order.get("product") or (obj.get("product") or {}).get("id")
    with db() as con:
        pay = con.execute("SELECT * FROM payments WHERE request_id=?", (request_id,)).fetchone()
    # Our own record decides who gets what; Creem's metadata is only for humans reading its dashboard.
    if not pay or order.get("status") != "paid" or not order_id or product != PRODUCTS.get(pay["pack"]):
        log("", "webhook_rejected", f"{request_id} {order_id} {order.get('status')} {product}")
        return {"ok": True, "ignored": "unknown or unpaid checkout"}

    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        credited = con.execute(
            "UPDATE payments SET status='paid', creem_order_id=?, amount_cents=?, currency=?, paid=? "
            "WHERE request_id=? AND status IN ('pending','error') "
            "AND NOT EXISTS (SELECT 1 FROM payments WHERE creem_order_id=?)",
            (order_id, order.get("amount"), order.get("currency"), time.time(), request_id, order_id),
        ).rowcount
        if credited:
            con.execute(
                "INSERT INTO credits (user_id, delta, reason, ref, created) VALUES (?,?,'purchase',?,?)",
                (pay["user_id"], pay["books"], order_id, time.time()),
            )
        user = con.execute("SELECT * FROM users WHERE id=?", (pay["user_id"],)).fetchone()
    if not credited:
        return {"ok": True, "duplicate": True}
    log(user["email"], "paid", f"{pay['pack']} {order.get('amount')} {order.get('currency')} {order_id}")
    if pay["draft_id"]:
        started, _, _ = start_draft(user["id"], user["email"], pay["draft_id"])
        if started:
            log(user["email"], "confirmed", f"{pay['draft_id']} after purchase")
    return {"ok": True}


@router.get("/paid/{request_id}", response_class=HTMLResponse)
def paid(request: Request, request_id: str):
    user = current_user(request)
    with db() as con:
        pay = con.execute("SELECT * FROM payments WHERE request_id=?", (request_id,)).fetchone()
        job = con.execute("SELECT id, status FROM jobs WHERE id=?", (pay["draft_id"],)).fetchone() if pay and pay["draft_id"] else None
    if not pay or not user or pay["user_id"] != user["id"]:
        return page(request, "paid.html", {"state": "unknown"}, 404)
    if pay["status"] == "paid" and job and job["status"] != "draft":
        return RedirectResponse(f"/jobs/{job['id']}", status_code=303)
    state = "paid" if pay["status"] == "paid" else "waiting"
    return page(request, "paid.html", {"state": state, "pay": pay, "job": job})

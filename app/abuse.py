"""Making "one free book per person" hold, roughly, and rate limits.

None of this stops a determined person; it makes farming free books tedious. A new
account gets no free book when any of these already got one:
  - the same mailbox (gmail dots and +tags removed, so a.b+1@gmail.com is ab@gmail.com),
  - the same browser (the long-lived device cookie),
  - FREE_PER_IP free books from the same network in the last 30 days (IPv6 grouped by /64).
Disposable-address domains (app/disposable_domains.txt, CC0, from
github.com/disposable-email-domains) never get a free book. Paying always works.

IP addresses are stored only as keyed hashes.
"""
import hashlib
import hmac
import ipaddress
import os
import time

from fastapi import Request

from .db import db
from .web import secret_key

FREE_PER_IP = int(os.environ.get("FREE_PER_IP", "2"))
FREE_IP_DAYS = 30

with open(os.path.join(os.path.dirname(__file__), "disposable_domains.txt")) as f:
    DISPOSABLE = {line.strip().lower() for line in f if line.strip() and not line.startswith("#")}

# Providers where dots and/or +tags reach the same mailbox.
DOTLESS = {"gmail.com", "googlemail.com"}
PLUS = DOTLESS | {"outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com", "mac.com",
                  "proton.me", "protonmail.com", "pm.me", "fastmail.com", "hey.com", "zoho.com"}
DASH = {"yahoo.com", "ymail.com"}  # Yahoo's disposable addresses use "-"
ALIAS = {"googlemail.com": "gmail.com"}


def email_key(email: str) -> str:
    local, _, domain = email.strip().lower().rpartition("@")
    domain = ALIAS.get(domain, domain)
    if domain in PLUS:
        local = local.split("+", 1)[0]
    if domain in DASH:
        local = local.split("-", 1)[0]
    if domain in DOTLESS:
        local = local.replace(".", "")
    return f"{local}@{domain}"


def is_disposable(email: str) -> bool:
    domain = email.rpartition("@")[2].lower()
    parts = domain.split(".")
    # Also catch subdomains of listed domains (x.mailinator.com).
    return any(".".join(parts[i:]) in DISPOSABLE for i in range(len(parts) - 1))


def ip_key(request: Request) -> str:
    """A keyed hash of the client's network: the address for IPv4, the /64 for IPv6."""
    host = request.client.host if request.client else ""
    try:
        addr = ipaddress.ip_address(host)
        net = str(ipaddress.ip_network(f"{addr}/64", strict=False)) if addr.version == 6 else str(addr)
    except ValueError:
        net = host
    return hmac.new(secret_key().encode(), net.encode(), hashlib.sha256).hexdigest()[:32]


def free_book_denied(con, email: str, device: str | None, ip: str) -> str | None:
    """Why this new account gets no free book, or None if it does."""
    if is_disposable(email):
        return "disposable"
    if con.execute("SELECT 1 FROM free_grants WHERE email_key=? LIMIT 1", (email_key(email),)).fetchone():
        return "email"
    if device and con.execute("SELECT 1 FROM free_grants WHERE device=? LIMIT 1", (device,)).fetchone():
        return "device"
    recent = con.execute(
        "SELECT COUNT(*) FROM free_grants WHERE ip=? AND created > ?", (ip, time.time() - FREE_IP_DAYS * 86400)
    ).fetchone()[0]
    if recent >= FREE_PER_IP:
        return "network"
    return None


def limited(kind: str, key: str, limit: int, seconds: int) -> bool:
    """Count one action; True if it's over `limit` in the last `seconds`."""
    now = time.time()
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM hits WHERE kind=? AND key=? AND ts > ?", (kind, key, now - seconds)).fetchone()[0]
        if n >= limit:
            return True
        con.execute("INSERT INTO hits VALUES (?,?,?)", (kind, key, now))
    return False

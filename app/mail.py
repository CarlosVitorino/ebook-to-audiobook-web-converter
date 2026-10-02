"""Outgoing email over plain SMTP, so any provider works (Resend, Postmark, SES, Gmail...).

Without SMTP_HOST, mail is printed to the console and appended to <DATA>/outbox.log,
which is how sign-in links reach you in development.
"""
import os
import smtplib
import time
from email.message import EmailMessage

from .db import DATA

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "narrator.guru <hello@narrator.guru>")


def send(to: str, subject: str, body: str):
    if not SMTP_HOST:
        text = f"--- mail {time.strftime('%Y-%m-%d %H:%M:%S')}\nTo: {to}\nSubject: {subject}\n\n{body}\n"
        print(text, flush=True)
        with open(os.path.join(DATA, "outbox.log"), "a") as f:
            f.write(text + "\n")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = MAIL_FROM, to, subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)

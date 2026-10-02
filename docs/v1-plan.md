# Plan: first real version (v1)

Status: approved by Carlos, 2026-10-02. Product name: **narrator.guru**. Phases A and B built (branch `v1-phase-a`). Phase C (Creem) is next.

Every ⚑ FLAG below was accepted as recommended. Answers are recorded in §10.

The PoC (phases 1–3 in `build-plan.md`) works: upload, narrate, download, free-first gate by typed email, fake-door packs. v1 turns that into something we can charge for, and it stays small:

- **Basic features only.** One conversion flow. No dashboard, no library. A small fixed voice choice, no cloning.
- **Doesn't look like a SaaS product.** Plain, direct pages like the current one: system font, one column, no hero illustrations, no feature grids, no testimonials carousel. Cheap and to the point is the brand.
- **New: choose what gets narrated.** Users drop the front and back matter (copyright, contents, acknowledgements, "also by", index…).
- **New: real accounts (Google or magic link) and real payments via Creem.**

Items marked **⚑ FLAG** were things I added or conflicts I found. All are now decided (§10).

---

## 1. The flow

```
 Landing page          Step 2                    Step 3                Step 4              Done
┌──────────────┐    ┌──────────────────────┐   ┌───────────────┐   ┌────────────────┐   ┌──────────────────┐
│ Drop your    │ →  │ Choose what to       │ → │ Sign in       │ → │ Confirm        │ → │ Status page      │
│ EPUB / PDF   │    │ narrate              │   │ Google, or    │   │ free book, or  │   │ + email when the │
│ [ Next ]     │    │ (chapter list +      │   │ magic link    │   │ use a credit,  │   │ book is ready    │
│              │    │  text + voice)       │   │               │   │ or buy a pack  │   │ M4B + SRT        │
└──────────────┘    └──────────────────────┘   └───────────────┘   └────────────────┘   └──────────────────┘
```

- The upload happens **before** sign-in, as you asked. The upload is held as an anonymous draft tied to a cookie. Sign-in attaches it to the account. Unclaimed drafts are deleted after 2 hours.
- The ownership checkbox ("I own this DRM-free book, personal use only") moves to step 4, next to the Convert button, where it carries the most weight.
- Users who are already signed in skip step 3.
- If the user has no free book and no credits, step 4 shows the three packs. Paying returns them to step 4 with the credit already added, and the conversion starts.

## 2. Landing page

Same style as now. Content from top to bottom:

1. One line: **"Turn your ebook into an audiobook."** One sub-line: "Upload an EPUB or PDF you own. Get one M4B file with chapters and captions."
2. The file picker/drop zone and a **Next** button. Nothing else above the fold.
3. **"Your first book is free. After that, buy a pack. No subscription."** with a plain price table: 1 book €2.99 · 5 books €9.95 (€1.99 each) · 15 books €24.95 (€1.66 each).
4. A 30-second audio sample of the voice (a static file, made once). **⚑ FLAG:** I added this. It costs nothing, and people want to hear the voice before uploading.
5. Three short FAQ lines: which files work (DRM-free EPUB/PDF, English), how long a conversion takes, and that files are deleted after N days.
6. Footer: Terms · Privacy · Refunds · contact email.

## 3. The "choose what to narrate" editor

**Recommendation: a section checklist plus a plain textarea per section. Not the Venture Lab editor.**

Venture Lab uses Milkdown Crepe, a WYSIWYG Markdown editor. It's a good editor, but it doesn't fit this job:
- Our text is plain paragraphs with nothing to format. Bold, headings and lists would never reach the narrator.
- It would add a JS build step (npm, bundler) to an app that has no JS today.
- 95% of the job is "drop these sections", which is one tick per section and needs no editor.

What the user sees:

```
Choose what to narrate                                     8 h 40 min · 1 book
───────────────────────────────────────────────────────────────────────────────
[ ] Cover                               12 words
[ ] Copyright                          140 words   "Copyright © 2021 by…"
[ ] Contents                           310 words   "Chapter 1 … Chapter 2 …"
[x] Chapter 1: The Arrival           4,210 words   "It was raining when…"     [Edit text]
[x] Chapter 2 …
…
[ ] Acknowledgements                   620 words
[ ] About the Author                   280 words
───────────────────────────────────────────────────────────────────────────────
                                                                     [ Next ]
```

- **Unticked automatically:** sections whose title matches a short list (cover, title page, copyright, contents, dedication, epigraph, acknowledgements, about the author, also by, index, notes, bibliography, newsletter/sign-up pages), plus tiny sections at the very start. The user can tick them back.
- **Edit text:** opens a textarea with that section's text. Users can delete a paragraph, a running header or a footnote. This also patches the known PDF gap (headers and page numbers read aloud) without us having to fix it.
- Running total at the top: estimated audio length and how many credits it uses.
- Built as server-rendered HTML plus about 50 lines of plain JS for the live total. The edited sections are saved as `sections.json` in the job folder. The worker narrates from that file instead of re-extracting the book.

**Voice (added by Carlos):** at the bottom of the same step, pick one of about 6 English voices (Kokoro ships them all, so it costs nothing). Each has a ▶ play button for a short pre-rendered sample (static files, generated once by a script). The default is `af_heart`. The chosen voice is stored on the job. This overrides the brief's old "no voice selection" line. Voice cloning stays out.

**⚑ FLAG:** If you still want Crepe for the text editing, it can be added later inside "Edit text" without changing the flow. I'd wait until someone asks for it.

## 4. Accounts (Google or magic link)

**⚑ FLAG, conflict with the brief:** `build-brief.md` says "Do not build any user accounts". You are now asking for login. I read the intent as "no dashboards or libraries", and login to hold credits is the minimum that real payments need. I'll update the brief's "Do not build" line to "no dashboards or libraries; accounts exist only to hold credits". Please confirm.

- **Google:** OAuth via Authlib.
- **Email:** magic link (decided), signed session cookies. No passwords stored.
- **⚑ FLAG, email + password brings extra work:** email verification (otherwise the free book can be farmed with fake addresses) and a password-reset flow. A magic link ("we emailed you a sign-in link") is less code and has no password to leak. **I recommend Google + magic link.** If you prefer passwords, it's roughly one extra day.
- **Free book rule:** one free book per account, and email accounts must be verified. Still gameable with many Gmail accounts. That's acceptable for v1, and we watch `/stats`.
- **What a signed-in user sees:** a header line ("you@x.com · 3 books left · sign out") and, on the landing page, links to their conversions that haven't expired yet. **⚑ FLAG:** this list is the smallest thing that could pass for a "library". Without it, users who lose the email lose their book. I'd keep it to unexpired jobs only.

## 5. Payments: Creem

**⚑ FLAG:** I assume "Cream" means **Creem** (creem.io), the merchant-of-record payment platform. Confirm.

Why Creem fits: as merchant of record, Creem handles EU VAT and sales tax. It sells one-time products, so it fits packs without subscriptions.

- Three one-time products in the Creem dashboard: 1, 4 and 12 books.
- "Buy" creates a Creem checkout session with `metadata = {user_id, pack, draft_id}` and redirects to Creem.
- The **webhook** (signature verified) is the only thing that adds credits. The success redirect only shows "payment received, starting your book".
- The webhook handler is idempotent on Creem's event/order id, so a retried webhook never doubles credits.
- **Credits ledger** table (+N on purchase, −1 on conversion start, +1 back if a conversion fails). The balance is the sum of the ledger.
- Test mode first, live keys at launch.
- **⚑ FLAG, before Creem goes live:** Creem reviews the store before enabling payouts. It wants a live site with Terms, Privacy and Refund pages and a clear product description, so those pages are in phase D. Also check Creem's current fee: about 4% + a fixed fee per order, which on the €2.99 pack is roughly €0.50. Carlos's net per book after fees and VAT: €1.96 / €1.47 / €1.26.

## 6. Other things I think v1 needs (all ⚑ FLAG)

| # | What | Why | My recommendation |
|---|---|---|---|
| 1 | **"Your book is ready" email** | A novel takes hours on CPU. Nobody keeps a tab open for 4 hours. | Yes. Use one transactional email provider (Resend or Postmark, free tier). The same provider sends verification/magic-link mails. |
| 2 | **What counts as "1 book"** | Without a cap, someone uploads a 2,000-page omnibus for one credit. | 1 credit = up to ~600k characters (~10 h of audio). Longer books use 2 credits, and the editor shows this live. |
| 3 | **Free book size cap** | The free book is pure compute cost. | Same 10 h cap as a paid credit. Simple rule, generous enough to impress. |
| 4 | **Retention** | 24 h is too short if a book finishes at 3 a.m. and the user is away for a weekend. | Keep outputs for 7 days. Delete the source upload as soon as narration ends (already done). |
| 5 | **Failed conversion = credit back** | You can't charge someone for a broken book. | Automatic +1 in the ledger, plus an email. |
| 6 | **English only** | One fixed English voice. A Portuguese book would sound terrible. | Say "English books" on the landing page. Optionally detect language and warn in the editor. |
| 7 | **Legal pages** | Creem requires them, and the copyright posture lives there. | Short Terms (you own it, DRM-free, personal use, we delete files), Privacy (EU/GDPR, what we store), Refunds (credit back on failure; unused packs refundable within 14 days). |
| 8 | **Real hosting** | Needed for HTTPS (Google OAuth requires it) and a domain. | Hetzner CX43/CX53 (CPU, per the business notes), Caddy for HTTPS, `docker compose`, nightly SQLite backup. **Needs a product name + domain from you.** |
| 9 | **Worker as its own process** | Today the worker is a thread inside the web app. A deploy or crash kills the running book. | Split it into a second compose service sharing SQLite. Small change. |
| 10 | **Basic abuse limits** | Uploads are free to try before login. | Per-IP upload rate limit and the existing size limit. |
| 11 | **Kokoro license check** | Still an open question in the business plan. It blocks *charging money*. | I read the model and voice licenses and note the result in `build-plan.md` before Creem goes live. |
| 12 | **Phase 5 was never done** | `build-plan.md` says "show it to one real person" is next. We're jumping past it. | Fine to skip, because real payments are a stronger test than the fake door. But keep `/stats` and add "paid for book two" as the headline number. |

## 7. Phases (I check in with you at the end of each)

Every phase leaves the app runnable.

**A. New flow + editor** (no auth or payment changes yet; the email field stays for now). **Done 2026-10-02.**
- Upload → draft → "choose what to narrate" page (sections + voice) → confirm → job.
- Voice samples generated by a script into `app/static/voices/`.
- Auto-untick front and back matter. Textarea editing. Live length and credit estimate.
- The worker narrates from `sections.json`.
- Landing page rewritten to the layout in §2.
- Done when: a sample EPUB and PDF go through the new flow and the M4B leaves out the unticked sections.

**B. Accounts + email**
- Users table, sessions, Google OAuth, magic link. **Done 2026-10-02.**
- Draft claimed on sign-in. Free-book gate moves from typed email to account.
- "Your book is ready" email. Header with credits. Unexpired-jobs list.
- Done when: a new Google user and a new email user each get exactly one free book, and an email arrives when it's done.

**C. Payments (Creem, test mode)**
- Products, checkout session, verified idempotent webhook, credits ledger, refund-on-failure.
- The fake door is removed. `/stats` shows paid packs and revenue.
- Done when: in test mode, buying a pack after the free book adds credits and the queued draft starts automatically. A replayed webhook adds nothing.

**D. Launch minimum**
- Legal pages, voice sample, FAQ lines.
- Worker split, rate limit, 7-day retention.
- Hetzner box, narrator.guru domain, HTTPS, backups (Carlos). Kokoro license read and recorded.
- Creem store review submitted, then live keys.
- Done when: a stranger can pay real money on the public URL.

**E. Ship and learn** (the old phase 5, now with real money)
- Post where the readers are (r/SideProject, r/audiobooks, r/selfpublish, accessibility communities), per the brief.
- Measure: free books finished, second-book attempts, packs paid, cost per finished hour.
- **Stop condition** (unchanged): copyright trouble, or nobody pays for book two.

## 8. Data model (additions)

```
users        id, email, email_verified, google_sub, password_hash NULL, created
sessions     signed cookie only (no table needed)
drafts       (built in phase A as jobs with status 'draft', owned by a cookie, no separate table; folder holds source + sections.json)
jobs         + owner, + voice (phase A); + user_id, + credits_used (phase B/C). Email column kept for history
credits      id, user_id, delta, reason ('free'|'purchase'|'conversion'|'refund'), ref, created
payments     id, user_id, creem_order_id UNIQUE, pack, amount_cents, currency, created
events       unchanged (feeds /stats)
```

## 9. Still out of scope

The brief's list stands, as updated: no voice cloning, no mobile app, no DRM handling, no store publishing, no subscriptions, no dashboard beyond the credits line and unexpired jobs.

## 10. Decisions (Carlos, 2026-10-02)

1. Accounts are allowed **only to hold credits**. The brief is updated.
2. Sign-in is **Google + magic link**. Google alone would shut out people without a Google account.
3. Payments go through **Creem** (creem.io).
4. Section checklist + plain textarea, not the Venture Lab Crepe editor.
5. 1 credit = up to ~10 h of audio, longer books use 2. The free book has the same cap. All of §6 is accepted.
6. Prices: **€2.99 for 1 book, €9.95 for 5, €24.95 for 15** (revised by Carlos, 2026-10-02; replaces €9/€29/€79).
7. Name: **narrator.guru**.
8. **Added: a voice selector in step 2** (§3), with about 6 English voices and pre-rendered samples.
9. Hosting and the email provider: Carlos sets them up later (phase D / phase B). Until then, emails go to the console log in development.

## 11. Phase A notes (2026-10-02)

- Flow: `/` → `POST /upload` → `/drafts/<id>` (sections + voice) → `/drafts/<id>/confirm` (email + ownership) → `/jobs/<id>`. A draft is a job with status `draft`, tied to a cookie and deleted after `DRAFT_HOURS` (2) if not confirmed.
- Unticked by default: matching titles (§3), short copyright-like pages, the PDF "Opening" pages, untitled scraps before the first real section, and Project Gutenberg headers/licence.
- EPUB section titles now come from the book's own table of contents (nav or NCX), then the first heading. Untitled sections stay untitled (narrated without an announced title; chapter marker "Part N").
- Fixed a PoC bug: the HTML `<head><title>` was read aloud, so every chapter title was spoken twice.
- Six voices (af_heart default, af_bella, am_michael, am_fenrir, bf_emma, bm_george). British voices use `en-gb` phonemes. Samples: `python scripts/make_voice_samples.py` → `app/static/voices/*.m4a` (committed, ~800 KB total).
- Length estimate: `CHARS_PER_SECOND` (14.5). Frankenstein estimates 8 h 22 min, close to commercial recordings. `/stats` now shows the measured rate so it can be tuned.
- Known gap: some EPUBs (Project Gutenberg, for one) pack several chapters into one file, so one section holds several chapters. Splitting by table-of-contents anchors would fix it; not done.

## 12. Phase B notes (2026-10-02)

- Code: `app/accounts.py` (sign-in routes), `app/db.py` (schema), `app/mail.py` (SMTP or console), `app/web.py` (templates, session user, balance).
- Google sign-in is a plain OAuth code flow with httpx, not Authlib: two HTTP calls, no extra library. It needs `GOOGLE_CLIENT_ID/SECRET` and `<BASE_URL>/signin/google/callback` as a redirect URI. Without them the Google button is hidden.
- The magic link is valid 20 minutes, works once, and is stored hashed. Max 5 links per email per hour. Opening the link shows a "Sign in" button rather than signing in at once, because mail scanners open links and would use them up.
- The same email via Google or link is one account. A user who already got a free book under the PoC's typed-email gate doesn't get a second one.
- The credits ledger (planned for phase C) landed now: +1 free at sign-up, minus the book's credits on confirm (check-and-spend in one `BEGIN IMMEDIATE` transaction), and a refund when a conversion fails. Phase C only adds purchase rows.
- Mail: plain SMTP (`SMTP_HOST` etc. in `.env.example`), so any provider works. Without it, mail goes to the log and `data/outbox.log`.
- Still open (phase D): `/stats` is public; job pages are reachable by anyone with the link (12 random hex characters), so emailed links work on any device.
- Tests run (scratch scripts, not committed): magic-link flow, draft claim, double-submit, second-book gate, link reuse, open redirect, rate limit, PoC-email rule, refund on failure, ready/failure emails; Google flow with Google's endpoints mocked.

## 13. Revision after phase B (2026-10-02)

- New prices (above). Pack ids are `one`, `five`, `fifteen`; each pack carries `books`, the credits it adds, ready for phase C.
- Processing time: Carlos's VPS narrates about 4–5× faster than real time. The landing page says "about 40 minutes for The Great Gatsby's 4 hours". The confirm page estimates with `NARRATION_SPEED` (default 5). The job page's countdown uses measured progress, so it's right on any machine.
- Layout reworked: still dark, but plain and a bit old-fashioned. Serif headings, thin rules, square buttons (one solid button per page, outlined for the rest), prices in a table instead of cards.

# Build plan — Ebook-to-Audiobook Web Converter

Size: **Proof of concept**. The smallest thing that proves the idea can work at all, in days, not weeks. It does not have to be pretty or safe to ship.

Status: phase 1 written, waiting on Carlos's go-ahead before any code.

## 1. Plan

### The idea, restated
A one-page website: drop in a DRM-free EPUB or text PDF you own, tick "I own this book", and some time later download one M4B file of the whole book (chapters included) plus synced captions. The first book is free; the page then says further books need a paid pack. It is for people who own ebooks but can't or won't run a Python tool: readers with visual impairments or dyslexia, commuters, and self-published authors. The thing we want to learn is whether anyone tries to pay for book two.

### Assumptions
1. **Engine = abogen** (MIT, github.com/denizsafak/abogen) driving **Kokoro-82M** (Apache-2.0, weights and voices; commercial use allowed per its model card). abogen ships a headless `abogen-cli`, so we call it rather than re-implement extraction, chunking, M4B muxing and subtitles. Not yet verified: exact CLI flags for merged M4B + subtitles; checked first thing in phase 2.
2. **One fixed English voice.** No voice picker (the brief forbids voice selection, even though the older notes sketch one).
3. **"Synced captions" = a sidecar `.srt` (sentence level) next to the M4B**, and we also try muxing it into the M4B as a text track. Most players ignore embedded M4B subtitles, so the sidecar is what actually works.
4. **No accounts.** "First conversion free" is enforced by email address (typed into the form, no login, no verification). Trivially gameable, fine for a PoC.
5. **Payment is a fake door.** After the free book the page shows the pack prices and a "Buy pack" button that records the click and an email, then says "coming soon". That click is the demand signal. No Stripe in the PoC. (Open question below.)
6. **Copyright posture:** accept `.epub` and `.pdf` only; hard-reject `.azw/.azw3/.kfx/.mobi`; reject EPUBs that contain `META-INF/encryption.xml` with DRM; required "I own this DRM-free book, personal use only" checkbox; delete uploads and outputs after 24h. No library, no sharing. Scanned (image-only) PDFs are rejected, no OCR.
7. **Async job, not request/response.** A novel is hours of audio; on CPU it may take hours to render. The user gets a status page link to come back to (email-when-done is skipped for the PoC).
8. **Runs on CPU** unless you have a GPU. Slow but works; good enough to show one person with a short book.

### Proposed stack
| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.12 | abogen requires 3.10–3.12; keeps everything in one runtime |
| Web | FastAPI + one Jinja HTML page, no JS framework | a form, a status page, a download link is all there is |
| Jobs | in-process background worker thread + SQLite | one box, one worker; no Redis/Celery needed for a PoC |
| Engine | `abogen-cli` called as a subprocess | reuses the proven pipeline; crashes stay isolated from the web app |
| Storage | local disk folder, cleaned after 24h | ephemeral is both the legal posture and the cheapest option |
| Run | `docker compose up` (Python, espeak-ng, ffmpeg baked in) | "one command" on any machine; avoids espeak/ffmpeg install pain |
| Host for phase 5 | your machine, or a Hetzner CX43 (~€16/mo) | CPU-first, per the business notes; GPU only if CPU is unusable |

Close alternative: wrap abogen's own `abogen-web` Flask UI. Faster on day one, but it exposes voice selection and lacks the free-book gate and DRM rejection, so we'd be stripping more than writing. I recommend the thin FastAPI app.

## 2. Foundation
- [ ] Dockerfile + compose with abogen, espeak-ng, ffmpeg; FastAPI app serving an empty upload page.
- [ ] Confirm `abogen-cli` turns a public-domain EPUB (Project Gutenberg) into one M4B + SRT inside the container; measure CPU seconds per 1,000 characters.
- Done when: `docker compose up` serves the page and the CLI smoke test produces playable output.

## 3. Core
- [ ] Upload form: file, email, ownership checkbox; format and DRM rejection.
- [ ] Job queue, status page, download of M4B + SRT.
- [ ] Free-first gate by email; second attempt shows pricing and the fake-door "Buy pack" button, which logs intent.
- Done when: a Gutenberg EPUB and a text PDF each go from upload to a playable chaptered M4B with captions.

## 4. Harden
- Skipped. Corners cut, on purpose: no auth, email gate is gameable, no rate limiting, no virus scan, single worker, no email notification, no real payments, CPU speed.

## 5. Ship and learn
- [ ] Run locally (or on a small host) and put it in front of one real person with a book they own.
- [ ] Measure: did they finish the free book, did they listen, did they click "Buy pack" for a second? Plus measured cost per finished hour.
- Done when: there is evidence for or against people paying for book two.

## Decisions

- **Phase-1 output lives in this file** (the plan says to rewrite phases here).
- **Thin FastAPI app over abogen-cli**, not a fork of abogen-web: we need a gate and rejections, not a voice picker.
- **Fake-door payment** for the PoC, pending Carlos's answer.

## Open questions for Carlos
1. Payments in the PoC: fake-door button (recommended), or real Stripe test-mode checkout?
2. Do you have a machine with an NVIDIA GPU to run this on? If not, CPU it is, and demos use short books.
3. The brief's "stop if" line mixes two things: copyright (handled by the posture above) and monetization (the pack model). I read the stop condition as "stop if we can't stay on the right side of copyright, or nobody pays for book two." Correct?

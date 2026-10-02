# Ebook-to-Audiobook Web Converter

Upload an EPUB or PDF, get back a narrated audiobook with captions The result makes this newly possible: Readers with visual impairments, commuters, and people with dyslexia own ebooks they bought legally but cannot convert to audio without a terminal and Python. Self-published authors want audio versions of their own books without paying a narrator or an Audible distribution fee. Today they either give up, pay ACX narrators hundreds of dollars, or ask a technical friend. The engine already does this; the gap is a web form.

- **Who it is for.** Readers with visual impairments, commuters, and people with dyslexia who own legally purchased ebooks they cannot convert to audio without technical tools, plus self-published authors who want audio versions of their own books without paying a professional narrator hundreds or thousands of dollars.
- **Start here.** A simple web form where a user uploads an EPUB or PDF and receives back a finished whole-book M4B file with synced captions, built on the existing open-source engine, with a first-conversion-free pricing message. If people will pay for a second book after their first free conversion, the thesis holds.
- **Stop if.** copywrite issues. We need a monetizing strategy. Like 1 free, next you need to buy like a pack, something like that.

This repository was handed off from Venture Lab. Open it in Cursor, Claude Code, Replit, Bolt or any coding tool and ask it to start.

- `build-brief.md` — the full brief
- `AGENTS.md` — how to work on it
- `docs/build-plan.md` — the phases
## Run it

With Docker:

```
docker compose up --build
```

Without Docker (needs Python 3.10–3.12, `ffmpeg` and `espeak-ng`; on a Mac, `brew install ffmpeg espeak-ng`):

```
./run.sh
```

Either way, open http://localhost:8000. The first run downloads the Kokoro voice model (~350 MB).

To make small test books: `python scripts/make_samples.py` writes `samples/aesop.epub`, `samples/aesop.pdf` (both with front and back matter to untick) and a fake-DRM `samples/drm.epub`.

Voice samples are committed in `app/static/voices/`. To re-render them after changing the voice list: `python scripts/make_voice_samples.py`.

What you get:

- `/`: the landing page: upload, prices, a voice sample.
- `/drafts/<id>`: choose what to narrate (front and back matter start unticked, any section's text can be edited) and pick one of six voices.
- `/drafts/<id>/confirm`: email and the ownership checkbox.
- `/jobs/<id>`: the status page, which refreshes itself, and then the M4B and SRT downloads.
- A second book from the same email shows the pricing page. "Buy" records the click and says packs are coming soon. No money moves.
- `/stats`: uploads, rejections, finished books, second-book attempts, buy clicks per pack, and measured speed. This is the thesis measurement.

Settings (environment variables): `KEEP_HOURS` (default 24), `DRAFT_HOURS` (2, unconfirmed uploads), `MAX_UPLOAD_MB` (100), `MAX_CHARS` (1,500,000), `CHARS_PER_CREDIT` (600,000, one book), `CHARS_PER_SECOND` (14.5, for the length estimate), `VOICE` (default voice, `af_heart`), `DATA_DIR`.

Speed: on a 4-core CPU, narration runs about 2.6× faster than real time, so a 10-hour novel takes roughly 4 hours.

# Ebook-to-Audiobook Web Converter
Upload an EPUB or PDF, get back a narrated audiobook with captions The result makes this newly possible: Readers with visual impairments, commuters, and people with dyslexia own ebooks they bought legally but cannot convert to audio without a terminal and Python. Self-published authors want audio versions of their own books without paying a narrator or an Audible distribution fee. Today they either give up, pay ACX narrators hundreds of dollars, or ask a technical friend. The engine already does this; the gap is a web form.
What would stop this: copywrite issues. We need a monetizing strategy. Like 1 free, next you need to buy like a pack, something like that.
Who it is for: Readers with visual impairments, commuters, and people with dyslexia who own legally purchased ebooks they cannot convert to audio without technical tools, plus self-published authors who want audio versions of their own books without paying a professional narrator hundreds or thousands of dollars.
The smallest thing worth building first: A simple web form where a user uploads an EPUB or PDF and receives back a finished whole-book M4B file with synced captions, built on the existing open-source engine, with a first-conversion-free pricing message. If people will pay for a second book after their first free conversion, the thesis holds.
Do not build:
- Dashboards or libraries beyond the single conversion flow (accounts exist only to sign in and hold credits; decided 2026-10-02)
- Voice cloning or custom voices (picking one of a few built-in Kokoro voices is allowed; decided 2026-10-02)
- Mobile apps
- DRM-protected ebook handling
- Distributed audiobook publishing or store integrations
- Subscription billing plans (start with free-first-conversion + paid packs)


## How to work on this

These are defaults to start from, not rules. If you have a better way to reach the goal, use it and say why. Ask the person you are working for whenever the brief leaves something that changes the outcome.

**Size of the build: Proof of concept.** The smallest thing that proves the idea can work at all, in days, not weeks. It does not have to be pretty or safe to ship.

**Before writing code**
- Read `build-brief.md` end to end.
- Never build anything listed under "Do not build".
- Work in the phases of `docs/build-plan.md`, and check in with the person at the end of each one.

**Throughout**
- Keep commits small and the app runnable at every step.
- If the brief looks wrong or contradicts itself, say so instead of working around it.
- When the stop condition in the brief is met, tell the person before building anything more.
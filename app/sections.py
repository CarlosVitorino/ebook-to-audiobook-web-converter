"""The "choose what to narrate" step: which sections start ticked, and how long the result is.

A draft's sections live in sections.json in its folder, as a list of
{"title", "text", "include"}. The worker narrates the included ones.
"""
import json
import math
import os
import re

from .extract import Chapter

# Kokoro at speed 1.0 with our pauses, measured on the sample books.
CHARS_PER_SECOND = float(os.environ.get("CHARS_PER_SECOND", "14.5"))
# One credit is one book of up to about 10 hours of audio.
CHARS_PER_CREDIT = int(os.environ.get("CHARS_PER_CREDIT", "600000"))

# Titles that are front or back matter, matched at the start of the title...
SKIP_PREFIX = (
    "about the author", "about the authors", "about the publisher", "also by", "other books by",
    "books by", "acknowledg", "copyright", "table of contents", "praise for", "a note on",
    "reading group", "discussion questions", "sneak peek", "excerpt from", "sign up",
    "newsletter", "title page", "half title", "further reading", "the full project gutenberg",
)
# ...or as the whole title.
SKIP_EXACT = {
    "cover", "contents", "dedication", "epigraph", "index", "notes", "endnotes",
    "bibliography", "references", "colophon", "credits", "permissions", "glossary", "toc", "license",
}
# Short sections that read like a copyright page, whatever they're called.
COPYRIGHT_TEXT = re.compile(r"all rights reserved|\bISBN\b|©|\(c\)\s*\d{4}|project gutenberg", re.I)
SHORT = 3000


def is_matter(title: str, text: str) -> bool:
    t = re.sub(r"[^\w\s]", " ", title.lower())
    t = " ".join(t.split())
    if t in SKIP_EXACT or any(t.startswith(p) for p in SKIP_PREFIX):
        return True
    return len(text) < SHORT and bool(COPYRIGHT_TEXT.search(text))


def initial(chapters: list[Chapter]) -> list[dict]:
    """Sections with front and back matter unticked."""
    out = []
    for i, c in enumerate(chapters):
        skip = is_matter(c.title, c.text)
        # PDF pages before the first outline entry: title page, copyright, contents.
        if i == 0 and c.title == "Opening":
            skip = True
        out.append({"title": c.title, "text": c.text, "include": not skip})
    # Untitled scraps before the first real section (title pages, half titles).
    for s in out:
        if s["include"] and len(s["text"]) >= 1000:
            break
        if not s["title"]:
            s["include"] = False
    return out


def load(folder: str) -> list[dict]:
    with open(os.path.join(folder, "sections.json")) as f:
        return json.load(f)


def save(folder: str, sections: list[dict]):
    tmp = os.path.join(folder, "sections.json.tmp")
    with open(tmp, "w") as f:
        json.dump(sections, f)
    os.replace(tmp, os.path.join(folder, "sections.json"))


def chapters(sections: list[dict]) -> list[Chapter]:
    return [Chapter(s["title"], s["text"]) for s in sections if s["include"] and s["text"].strip()]


def included_chars(sections: list[dict]) -> int:
    return sum(len(s["text"]) for s in sections if s["include"])


def audio_seconds(chars: int) -> float:
    return chars / CHARS_PER_SECOND


def credits(chars: int) -> int:
    return max(1, math.ceil(chars / CHARS_PER_CREDIT))


def clean_edit(text: str) -> str:
    """Normalize a textarea post: browser line endings, and blank lines as paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()

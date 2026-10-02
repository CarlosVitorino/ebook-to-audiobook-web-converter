"""Turn an uploaded EPUB or PDF into a list of (chapter title, text) pairs.

Raises RejectedBook with a user-facing message for anything we refuse to
process: DRM, Kindle formats, scanned PDFs, empty books.
"""
import re
import zipfile
from dataclasses import dataclass

import pymupdf as fitz
from bs4 import BeautifulSoup

ACCEPTED = {".epub", ".pdf"}
KINDLE = {".azw", ".azw3", ".azw4", ".kfx", ".mobi", ".prc", ".kf8"}

# Font obfuscation uses encryption.xml too, but is not DRM.
FONT_OBFUSCATION = (
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
)


class RejectedBook(Exception):
    pass


@dataclass
class Chapter:
    title: str
    text: str


def check_extension(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in KINDLE:
        raise RejectedBook(
            "Kindle files (AZW, KFX, MOBI) are not supported. "
            "We only convert DRM-free EPUB or PDF books you own."
        )
    if ext not in ACCEPTED:
        raise RejectedBook("Please upload an EPUB or PDF file.")
    return ext


def extract(path: str, ext: str) -> list[Chapter]:
    chapters = _epub(path) if ext == ".epub" else _pdf(path)
    chapters = [c for c in chapters if len(c.text) > 40]
    if not chapters:
        raise RejectedBook("We couldn't find any readable text in this book.")
    return chapters


def _clean(text: str) -> str:
    text = text.replace("­", "")
    text = re.sub(r"-\n(\w)", r"\1", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _epub(path: str) -> list[Chapter]:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise RejectedBook("This EPUB file is damaged or not really an EPUB.")
    names = set(z.namelist())
    if "META-INF/rights.xml" in names:
        raise RejectedBook("This EPUB is DRM-protected. We only convert DRM-free books.")
    if "META-INF/encryption.xml" in names:
        enc = z.read("META-INF/encryption.xml").decode("utf-8", "ignore")
        algos = re.findall(r'EncryptionMethod[^>]*Algorithm="([^"]+)"', enc)
        if any(a not in FONT_OBFUSCATION for a in algos):
            raise RejectedBook("This EPUB is DRM-protected. We only convert DRM-free books.")

    # Find the OPF and walk its spine in reading order.
    container = BeautifulSoup(z.read("META-INF/container.xml"), "xml")
    opf_path = container.find("rootfile")["full-path"]
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    opf = BeautifulSoup(z.read(opf_path), "xml")
    manifest = {i["id"]: i["href"] for i in opf.find_all("item")}

    chapters = []
    for ref in opf.find("spine").find_all("itemref"):
        href = manifest.get(ref["idref"])
        if not href:
            continue
        name = base + href.split("#")[0]
        if name not in names:
            continue
        soup = BeautifulSoup(z.read(name), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(" ", strip=True) if heading else ""
        # Paragraph-ish blocks become paragraphs so narration pauses sensibly.
        for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "li", "br"]):
            block.insert_after("\n\n")
        text = _clean(soup.get_text())
        if text:
            chapters.append(Chapter(title or f"Chapter {len(chapters) + 1}", text))
    return chapters


def _pdf(path: str) -> list[Chapter]:
    try:
        doc = fitz.open(path)
    except Exception:
        raise RejectedBook("This PDF file is damaged or not really a PDF.")
    if doc.needs_pass or doc.is_encrypted:
        raise RejectedBook("This PDF is password- or DRM-protected. We only convert DRM-free books.")

    pages = [_clean(p.get_text()) for p in doc]
    if sum(len(p) for p in pages) < 100 * max(1, len(pages) // 10):
        raise RejectedBook(
            "This PDF looks scanned (images, not text). We only support text-based PDFs for now."
        )

    toc = [(title, page) for level, title, page in doc.get_toc() if level == 1 and page > 0]
    if not toc:
        return [Chapter(doc.metadata.get("title") or "Book", "\n\n".join(pages))]
    chapters = []
    if toc[0][1] > 1:
        front = "\n\n".join(pages[: toc[0][1] - 1])
        if front:
            chapters.append(Chapter("Opening", front))
    for i, (title, start) in enumerate(toc):
        end = toc[i + 1][1] - 1 if i + 1 < len(toc) else len(pages)
        chapters.append(Chapter(title, "\n\n".join(pages[start - 1 : end])))
    return chapters


def book_title(path: str, ext: str, fallback: str) -> str:
    try:
        if ext == ".pdf":
            return fitz.open(path).metadata.get("title") or fallback
        z = zipfile.ZipFile(path)
        container = BeautifulSoup(z.read("META-INF/container.xml"), "xml")
        opf = BeautifulSoup(z.read(container.find("rootfile")["full-path"]), "xml")
        t = opf.find("dc:title") or opf.find("title")
        return t.get_text(strip=True) if t else fallback
    except Exception:
        return fallback

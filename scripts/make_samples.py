"""Write small public-domain test books into samples/: a clean EPUB, a clean PDF, and a fake-DRM EPUB."""
import os
import zipfile

import pymupdf

OUT = os.path.join(os.path.dirname(__file__), "..", "samples")
FABLES = {
    "The Fox and the Grapes": (
        "A hungry Fox saw some fine bunches of Grapes hanging from a vine that was trained along a high trellis. "
        "He did his best to reach them by jumping as high as he could into the air. But it was all in vain, "
        "for they were just out of reach.\n\nSo he gave up trying, and walked away with an air of dignity and unconcern, "
        "remarking, \"I thought those Grapes were ripe, but I see now they are quite sour.\""
    ),
    "The Tortoise and the Hare": (
        "A Hare was making fun of the Tortoise one day for being so slow. \"Do you ever get anywhere?\" he asked with a mocking laugh. "
        "\"Yes,\" replied the Tortoise, \"and I get there sooner than you think. I'll run you a race and prove it.\"\n\n"
        "The Hare was much amused at the idea of running a race with the Tortoise, but for the fun of the thing he agreed. "
        "So the Fox, who had consented to act as judge, marked the distance and started the runners off. "
        "The Hare was soon far out of sight, and lay down beside the course to take a nap until the Tortoise should catch up.\n\n"
        "The Tortoise meanwhile kept going slowly but steadily, and, after a time, passed the place where the Hare was sleeping. "
        "When the Hare awoke, the Tortoise was near the goal. The Hare now ran his swiftest, but he could not overtake the Tortoise in time. "
        "The race is not always to the swift."
    ),
    "The Lion and the Mouse": (
        "A Lion lay asleep in the forest, his great head resting on his paws. A timid little Mouse came upon him unexpectedly, "
        "and in her fright and haste to get away, ran across the Lion's nose. Roused from his nap, the Lion laid his huge paw angrily "
        "on the tiny creature to kill her.\n\n\"Spare me!\" begged the poor Mouse. \"Please let me go and some day I will surely repay you.\" "
        "The Lion was much amused to think that a Mouse could ever help him. But he was generous and finally let the Mouse go.\n\n"
        "Some days later, while stalking his prey in the forest, the Lion was caught in the toils of a hunter's net. "
        "The Mouse knew the voice and quickly found the Lion struggling in the net. Running to one of the great ropes that bound him, "
        "she gnawed it until it parted, and soon the Lion was free. A kindness is never wasted."
    ),
}


def epub(path, drm=False):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        if drm:
            z.writestr("META-INF/encryption.xml", """<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/></enc:EncryptedData></encryption>""")
        items, spine = [], []
        for i, (title, text) in enumerate(FABLES.items(), 1):
            paras = "".join(f"<p>{p}</p>" for p in text.split("\n\n"))
            z.writestr(f"OEBPS/ch{i}.xhtml", f"<html xmlns='http://www.w3.org/1999/xhtml'><body><h1>{title}</h1>{paras}</body></html>")
            items.append(f'<item id="ch{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="ch{i}"/>')
        z.writestr("OEBPS/content.opf", f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Three Fables of Aesop</dc:title><dc:identifier id="id">aesop-sample</dc:identifier><dc:language>en</dc:language></metadata>
<manifest>{''.join(items)}</manifest><spine>{''.join(spine)}</spine></package>""")


def pdf(path):
    doc = pymupdf.open()
    toc = []
    for title, text in FABLES.items():
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(60, 60, 540, 780), title + "\n\n" + text, fontsize=12)
        toc.append([1, title, doc.page_count])
    doc.set_toc(toc)
    doc.set_metadata({"title": "Three Fables of Aesop (PDF)"})
    doc.save(path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    epub(os.path.join(OUT, "aesop.epub"))
    epub(os.path.join(OUT, "drm.epub"), drm=True)
    pdf(os.path.join(OUT, "aesop.pdf"))
    print("wrote samples/aesop.epub, samples/aesop.pdf, samples/drm.epub")

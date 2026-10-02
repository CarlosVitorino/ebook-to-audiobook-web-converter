"""Render the short voice samples played on the landing page and in step 2.

Run once (and again if the voice list changes):  python scripts/make_voice_samples.py
Writes app/static/voices/<voice>.m4a, which are committed.
"""
import os
import subprocess
import sys

import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.narrate import SR, VOICES, kokoro  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "app", "static", "voices")
TEXT = (
    "It is a truth universally acknowledged, that a single man in possession of a good fortune, "
    "must be in want of a wife. However little known the feelings or views of such a man may be "
    "on his first entering a neighbourhood, this truth is so well fixed in the minds of the "
    "surrounding families, that he is considered the rightful property of some one or other of "
    "their daughters."
)

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tts = kokoro()
    for v in VOICES:
        lang = "en-gb" if v["id"].startswith("b") else "en-us"
        audio, _ = tts.create(TEXT, voice=v["id"], speed=1.0, lang=lang)
        wav = os.path.join(OUT, v["id"] + ".wav")
        sf.write(wav, audio, SR)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "aac", "-b:a", "48k",
             "-movflags", "+faststart", os.path.join(OUT, v["id"] + ".m4a")],
            check=True,
        )
        os.remove(wav)
        print(f"{v['id']}: {len(audio) / SR:.1f}s")

"""Narrate chapters with Kokoro-82M and package them as an M4B with captions.

Each sentence is synthesized on its own, so we know exactly where it starts
and ends: that gives sentence-level captions for free.
"""
import ctypes.util
import glob
import os
import re
import subprocess
from typing import Callable

import numpy as np
import onnxruntime as rt
import soundfile as sf
from kokoro_onnx import EspeakConfig, Kokoro

from .extract import Chapter

VOICE = os.environ.get("VOICE", "af_heart")
# The voices offered in step 2: the best-rated English ones Kokoro ships.
VOICES = [
    {"id": "af_heart", "name": "Heart", "accent": "American", "gender": "female"},
    {"id": "af_bella", "name": "Bella", "accent": "American", "gender": "female"},
    {"id": "am_michael", "name": "Michael", "accent": "American", "gender": "male"},
    {"id": "am_fenrir", "name": "Fenrir", "accent": "American", "gender": "male"},
    {"id": "bf_emma", "name": "Emma", "accent": "British", "gender": "female"},
    {"id": "bm_george", "name": "George", "accent": "British", "gender": "male"},
]
VOICE_IDS = {v["id"] for v in VOICES}
MODEL_DIR = os.environ.get("MODEL_DIR", os.path.join(os.path.dirname(__file__), "..", "models"))
# 0 lets ONNX Runtime size its own thread pool; set it when the container has a CPU limit.
ONNX_THREADS = int(os.environ.get("ONNX_THREADS", "0"))
SR = 24000

SENTENCE_GAP = 0.12
PARAGRAPH_GAP = 0.45
CHAPTER_GAP = 1.5
MAX_SENTENCE = 350

ABBREVIATIONS = "".join(rf"(?<!\b{a}\.)" for a in ("Mr", "Mrs", "Ms", "Dr", "St", "Jr", "Sr", "vs", "etc", "No", "[A-Z]"))
SPLIT = re.compile(ABBREVIATIONS + r"""(?<=[.!?…])["'”’)\]]*\s+(?=["'“‘(\[]*[A-Z0-9])""")

_kokoro = None


def _espeak() -> EspeakConfig:
    """Use the system espeak-ng; the pip-bundled one has a broken data path on Linux."""
    lib = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY") or ctypes.util.find_library("espeak-ng")
    data = os.environ.get("ESPEAK_DATA_PATH")
    if not data:
        candidates = glob.glob("/usr/lib/*/espeak-ng-data") + [
            "/usr/share/espeak-ng-data",
            "/opt/homebrew/share/espeak-ng-data",
            "/usr/local/share/espeak-ng-data",
        ]
        data = next((c for c in candidates if os.path.exists(os.path.join(c, "phontab"))), None)
    if lib and not os.path.isabs(lib):
        found = glob.glob(f"/usr/lib/*/{lib}") + glob.glob(f"/usr/lib/{lib}")
        lib = found[0] if found else lib
    return EspeakConfig(lib_path=lib, data_path=data)


def kokoro() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        model = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
        voices = os.path.join(MODEL_DIR, "voices-v1.0.bin")
        if ONNX_THREADS:
            # ORT reads the host's core count, not our cgroup quota, so a CPU limit
            # leaves it oversubscribed and throttled instead of merely capped.
            opts = rt.SessionOptions()
            opts.intra_op_num_threads = ONNX_THREADS
            session = rt.InferenceSession(
                model, sess_options=opts, providers=["CPUExecutionProvider"]
            )
            _kokoro = Kokoro.from_session(session, voices, espeak_config=_espeak())
        else:
            _kokoro = Kokoro(model, voices, espeak_config=_espeak())
    return _kokoro


def sentences(paragraph: str) -> list[str]:
    paragraph = " ".join(paragraph.split())
    out = []
    for s in SPLIT.split(paragraph):
        s = s.strip()
        while len(s) > MAX_SENTENCE:
            cut = max(s.rfind(p, 0, MAX_SENTENCE) for p in (";", ":", ",", " "))
            cut = cut if cut > 50 else MAX_SENTENCE
            out.append(s[: cut + 1].strip())
            s = s[cut + 1 :].strip()
        if re.search(r"\w", s):
            out.append(s)
    return out


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype=np.float32)


def narrate(
    chapters: list[Chapter],
    title: str,
    workdir: str,
    progress: Callable[[int, int], None] = lambda done, total: None,
    voice: str = VOICE,
) -> tuple[str, str, float]:
    """Write <workdir>/book.m4b and <workdir>/book.srt. Returns (m4b, srt, seconds)."""
    tts = kokoro()
    lang = "en-gb" if voice.startswith("b") else "en-us"
    wav_path = os.path.join(workdir, "book.wav")
    srt_path = os.path.join(workdir, "book.srt")
    meta_path = os.path.join(workdir, "chapters.txt")
    m4b_path = os.path.join(workdir, "book.m4b")

    total = sum(len(c.text) for c in chapters)
    done = 0
    t = 0.0  # seconds written so far
    cue = 0
    marks = []

    with sf.SoundFile(wav_path, "w", SR, 1, "PCM_16") as wav, open(srt_path, "w") as srt:

        def say(text: str, gap: float):
            nonlocal t, cue
            audio, _ = tts.create(text, voice=voice, speed=1.0, lang=lang)
            start, t = t, t + len(audio) / SR
            wav.write(audio)
            cue += 1
            srt.write(f"{cue}\n{_ts(start)} --> {_ts(t)}\n{text}\n\n")
            wav.write(_silence(gap))
            t += gap

        for n, ch in enumerate(chapters, 1):
            marks.append((t, ch.title or f"Part {n}"))
            body = ch.text
            # Read the title aloud unless the chapter text already opens with it.
            if ch.title and not body.lstrip().lower().startswith(ch.title.lower()[:30]):
                say(ch.title, PARAGRAPH_GAP)
            for para in body.split("\n\n"):
                for s in sentences(para):
                    say(s, SENTENCE_GAP)
                wav.write(_silence(PARAGRAPH_GAP - SENTENCE_GAP))
                t += PARAGRAPH_GAP - SENTENCE_GAP
                done += len(para) + 2
                progress(min(done, total), total)
            wav.write(_silence(CHAPTER_GAP))
            t += CHAPTER_GAP

    with open(meta_path, "w") as f:
        f.write(";FFMETADATA1\n")
        f.write(f"title={_meta(title)}\nalbum={_meta(title)}\ngenre=Audiobook\n")
        for i, (start, name) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else t
            f.write(
                f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(start * 1000)}\n"
                f"END={int(end * 1000)}\ntitle={_meta(name)}\n"
            )

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", wav_path, "-f", "ffmetadata", "-i", meta_path, "-i", srt_path,
            "-map", "0:a", "-map", "2:s", "-map_metadata", "1", "-map_chapters", "1",
            "-c:a", "aac", "-b:a", "64k", "-c:s", "mov_text",
            "-metadata:s:s:0", "language=eng",
            "-movflags", "+faststart", "-f", "mp4", m4b_path,
        ],
        check=True,
    )
    os.remove(wav_path)
    os.remove(meta_path)
    return m4b_path, srt_path, t


def _meta(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)

#!/usr/bin/env bash
# Run without Docker. Needs Python 3.10–3.12, ffmpeg and espeak-ng
# (macOS: brew install ffmpeg espeak-ng · Debian/Ubuntu: apt install ffmpeg espeak-ng).
set -euo pipefail
cd "$(dirname "$0")"

for tool in ffmpeg espeak-ng; do
  command -v "$tool" >/dev/null || { echo "Please install $tool first."; exit 1; }
done

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  # kokoro-onnx pulls in plain phonemizer; the fork is the one it actually needs.
  .venv/bin/pip uninstall -q -y phonemizer
  .venv/bin/pip install -q --force-reinstall --no-deps phonemizer-fork
fi

mkdir -p models
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -s "models/$f" ] || curl -fL -o "models/$f" \
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
done

echo "Open http://localhost:8000"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

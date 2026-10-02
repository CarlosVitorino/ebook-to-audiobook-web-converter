FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# kokoro-onnx pulls in plain phonemizer; the fork is the one it actually needs.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y phonemizer && pip install --no-cache-dir --force-reinstall --no-deps phonemizer-fork

# Kokoro-82M (Apache-2.0) as ONNX, from the kokoro-onnx GitHub release.
RUN mkdir -p models && cd models \
    && curl -fsSLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    && curl -fsSLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY app app
ENV DATA_DIR=/data MODEL_DIR=/app/models
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

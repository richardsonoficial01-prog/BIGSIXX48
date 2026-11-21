FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLIPPER_HOST=0.0.0.0 \
    CLIPPER_PORT=8000 \
    CLIPPER_DATA_DIR=/app/.data \
    WHISPER_MODEL=tiny \
    WHISPER_CACHE_DIR=/app/.data/models \
    OMP_NUM_THREADS=2 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Node is the JavaScript runtime used by yt-dlp's bundled YouTube support.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# Optional: docker build --build-arg PRELOAD_WHISPER_MODEL=1 .
# Without it, the speech model is downloaded on the first real analysis.
ARG PRELOAD_WHISPER_MODEL=0
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 clipper \
    && mkdir -p /app/.data/models \
    && if [ "$PRELOAD_WHISPER_MODEL" = "1" ]; then \
      python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8', download_root=os.environ['WHISPER_CACHE_DIR'])"; \
    fi \
    && chown -R clipper:clipper /app

USER clipper
COPY --chown=clipper:clipper . ./

EXPOSE 8000
CMD ["python", "server.py"]

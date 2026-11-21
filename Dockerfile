FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    BIGSIXX48_DATA_DIR=/app/data \
    WHISPER_MODEL=tiny \
    OMP_NUM_THREADS=2 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 clipper \
    && mkdir -p /app/data/uploads /app/data/library /app/data/tmp \
    && chown -R clipper:clipper /app

USER clipper
COPY --chown=clipper:clipper . ./

EXPOSE 8000
CMD ["python", "server.py"]

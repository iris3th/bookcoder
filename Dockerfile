# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BOOKCODER_HOST=0.0.0.0 \
    BOOKCODER_PORT=8765 \
    XDG_CONFIG_HOME=/data/config \
    XDG_DATA_HOME=/data/share \
    HOME=/data/home

WORKDIR /app

# System dependencies: ffmpeg for MP3/AAC(M4A) encoding/combining/normalization,
# ca-certificates for HTTPS (Edge TTS, Piper model downloads, PyPI at build time).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY requirements.txt pyproject.toml README.md ./
COPY bookcoder ./bookcoder

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Persist settings, downloaded Piper models, and user home/runtime data
RUN mkdir -p /data/config /data/share /data/home /audiobooks
VOLUME ["/data/config", "/data/share", "/audiobooks"]

EXPOSE 8765

# Bind to all interfaces inside the container; port publishing controls host exposure.
CMD ["python", "-m", "bookcoder", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]

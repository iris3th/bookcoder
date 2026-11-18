# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

# Optional build-time customization:
#   BOOKCODER_EXTRAS: install optional Python extras from pyproject.toml, e.g. "coqui", "mms", or "heavy-tts"
#   PIP_EXTRA_ARGS: extra pip args (e.g. "--extra-index-url https://download.pytorch.org/whl/cu121" for NVIDIA CUDA torch wheels,
#                   or ROCm-specific index/args for AMD ROCm PyTorch builds)
# Examples:
#   docker build -t bookcoder:cpu .
#   docker build --build-arg BOOKCODER_EXTRAS=heavy-tts -t bookcoder:heavy-cpu .
#   docker build --build-arg BOOKCODER_EXTRAS=heavy-tts \
#     --build-arg PIP_EXTRA_ARGS="--extra-index-url https://download.pytorch.org/whl/cu121" -t bookcoder:nvidia .
#
# Notes:
#   - When BOOKCODER_EXTRAS is set, the build explicitly installs torch/torchaudio and ensures transformers/numpy/scipy are present (MMS-TTS deps); requested extras (e.g. coqui/heavy-tts) may also install TTS.
#   - If a GPU-targeted PyTorch install via PIP_EXTRA_ARGS fails (e.g. incompatible Python/wheel tag), the build falls back to default CPU PyTorch wheels so heavy engines remain usable on CPU when possible.
#
# GPU runtime notes (containers):
#   - NVIDIA: requires NVIDIA drivers on host + NVIDIA Container Toolkit/runtime; run with GPU access (e.g. `docker run --gpus all ...` or Podman equivalent).
#   - AMD: typically requires ROCm-compatible host/kernel/drivers and device passthrough (e.g. `/dev/kfd`, `/dev/dri`) plus appropriate group permissions; use ROCm-compatible PyTorch wheels/build args and a runtime setup supported by your GPU/OS.
#   - BookCoder detects GPUs/PyTorch acceleration inside the container and uses GPU for Coqui XTTS/MMS-TTS when `torch.cuda.is_available()` is true. Model downloads/caches are stored under /data/share by default.
ARG BOOKCODER_EXTRAS=""
ARG PIP_EXTRA_ARGS=""

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
# ca-certificates for HTTPS (Edge TTS, Piper/model downloads, PyPI at build time).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching
COPY requirements.txt pyproject.toml README.md ./
COPY bookcoder ./bookcoder

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir ${PIP_EXTRA_ARGS} -r requirements.txt \
    && if [ -n "$BOOKCODER_EXTRAS" ]; then \
         echo "Installing heavy engine dependencies for extras: $BOOKCODER_EXTRAS"; \
         if [ -n "$PIP_EXTRA_ARGS" ]; then \
           echo "Attempting PyTorch install with build args: $PIP_EXTRA_ARGS"; \
           if ! pip install --no-cache-dir ${PIP_EXTRA_ARGS} torch torchaudio; then \
             echo "WARNING: PyTorch install with PIP_EXTRA_ARGS failed (possibly incompatible Python/wheel tag); falling back to default CPU PyTorch wheels."; \
             pip install --no-cache-dir torch torchaudio || echo "WARNING: CPU PyTorch fallback install failed; heavy engines may be unavailable."; \
           fi; \
         else \
           pip install --no-cache-dir torch torchaudio || echo "WARNING: PyTorch install failed; heavy engines may be unavailable."; \
         fi; \
         pip install --no-cache-dir "transformers>=4.41" numpy scipy || echo "WARNING: Failed to install some MMS dependencies (transformers/numpy/scipy)."; \
         if ! pip install --no-cache-dir ${PIP_EXTRA_ARGS} ".[$BOOKCODER_EXTRAS]"; then \
           echo "WARNING: Installing extras with PIP_EXTRA_ARGS failed; retrying without PIP_EXTRA_ARGS."; \
           pip install --no-cache-dir ".[$BOOKCODER_EXTRAS]"; \
         fi; \
       fi \
    && python -m pip show transformers >/dev/null 2>&1 || true \
    && python -c "import importlib.util, sys; print('torch_installed=', importlib.util.find_spec('torch') is not None)" || true

# Persist settings, downloaded Piper/heavy-engine model caches (where configured), and runtime data
RUN mkdir -p /data/config /data/share /data/home /audiobooks
VOLUME ["/data/config", "/data/share", "/audiobooks"]

EXPOSE 8765

# Bind to all interfaces inside the container; port publishing controls host exposure.
CMD ["python", "-m", "bookcoder", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]

# BookCoder — AI Audiobook Generator

BookCoder is a local desktop-style web application for converting ebooks and text documents into high-quality audiobooks with natural-sounding AI narration.

It supports **EPUB**, **MOBI**, **AZW3**, and **TXT** input, automatic **English/Hungarian** language detection, chapter extraction, and audiobook generation with both **online** (Microsoft Edge Neural TTS) and **offline** (Piper) voice engines. Output can be generated as **MP3**, **AAC in M4A**, or **M4B audiobook** (single combined file with embedded chapter markers/metadata, recommended for Apple Books).

This README explains how to **install and configure BookCoder on Debian**.

---

## Features

- **Input formats:** `.epub`, `.mobi`, `.azw3`, `.txt`
- **Import:** drag-and-drop or file browser, validation/error messages, remove/replace before processing
- **Language detection:** detects English or Hungarian from book text, with manual override
- **Narration engines:**
  - **Edge Neural TTS (online):** natural neural voices, no API key required (internet needed for synthesis/voice listing)
  - **Piper (offline):** local neural TTS; works offline after voice models are downloaded
  - **Coqui XTTS v2 (offline, heavy, optional):** multilingual neural TTS (EN/HU) with higher-quality/expressive synthesis potential; requires heavy dependencies (Torch + TTS) and may download/load large models on first use
  - **Meta MMS-TTS (offline, heavy, optional):** neural VITS voices via Transformers/Torch for EN/HU; requires heavy dependencies and may download/cache models on first use
- **Voices:** English and Hungarian, male/female options (engine-dependent), voice previews, speed/pitch/style controls, dynamic tone profiles, dialogue/alternate-voice casting hooks, and pronunciation dictionary overrides/presets/import-export
- **Offline model management:** in-app download, progress, delete/remove, and “use” for Piper voices and heavy-engine models (Coqui XTTS v2, Meta MMS-TTS) where supported
- **Hardware acceleration detection:** detects NVIDIA/AMD GPUs and PyTorch GPU acceleration availability (CUDA/ROCm) and uses GPU automatically for supported heavy engines when available
- **Chapters:** automatic extraction/section detection, include/exclude, reorder, per-chapter audio output
- **Output formats:** **MP3 (.mp3)**, **AAC (.m4a, iPhone-compatible)**, and **M4B (.m4b, audiobook)**
  - Separate file per chapter and optional combined audiobook (MP3/M4A)
  - **M4B (combined audiobook):** creates a single chaptered `.m4b` file with embedded chapter markers and audiobook metadata (title/author/language/genre). M4B export always produces a combined file (per-chapter AAC `.m4a` files may also be generated during processing)
  - Configurable bitrate/quality and chapter pause
  - **AAC/M4A** output is recommended for direct copy to iPhone (Apple Books/Music/Files workflows); **M4B** is recommended for a chaptered audiobook in Apple Books or audiobook player apps on iPhone/iPad
  - Embedding M4B chapter markers/metadata requires **FFmpeg** (recommended)
- **Output/export helpers**
  - Saves generated files to a user-selected output directory by default (current behavior preserved)
  - Quick actions to open the output folder, reveal/copy paths, and optional post-export actions (copy generated files to another folder such as a synced/mounted device path, or run a custom command/script) without requiring direct device integration

### Recommended offline Piper voices (downloadable in-app)

| Language | Voice | Gender | Locale | Quality |
|---|---|---|---|---|
| English | Lessac | Female | en-US | medium |
| English | Amy | Female | en-US | medium |
| English | Ryan | Male | en-US | medium |
| English | Joe | Male | en-US | medium |
| English | Cori | Female | en-GB | medium |
| English | Northern English | Male | en-GB | medium |
| Hungarian | Anna | Female | hu-HU | medium |
| Hungarian | Berta | Female | hu-HU | medium |
| Hungarian | Imre | Male | hu-HU | medium |

> Offline model files are downloaded on demand from `rhasspy/piper-voices` (Hugging Face). Internet is required only for the download; synthesis is local afterward.

---

## 1) System requirements (Debian)

- **Debian** 12 (Bookworm) or 13 (Trixie) recommended (other recent Debian-based systems may also work)
- **Python** 3.10+ (Debian 12+ provides suitable Python 3)
- **Internet access** (optional depending on usage):
  - required for `pip install` dependencies (unless you provide wheels offline)
  - required for Edge online TTS synthesis/voice listing
  - required to download Piper offline voice models (one-time per model)
- **FFmpeg** strongly recommended for best audio encoding/normalization and chapter/audio concatenation (MP3, AAC/M4A, and M4B), and required for embedding M4B chapter markers/metadata reliably
- **Calibre's `ebook-convert`** (optional, from package `calibre`) can improve AZW3/MOBI extraction/conversion compatibility
- Disk space for Python packages and offline voice models (~60–100 MB per Piper voice)

---

## 2) Install system dependencies (Debian)

Update packages and install Python tooling, venv support, and FFmpeg:

```bash
sudo apt update
sudo apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  ffmpeg \
  ca-certificates \
  curl
```

Notes:
- `python3-venv` is required to create an isolated virtual environment.
- `ffmpeg` is recommended (important for reliable MP3/AAC encoding, format conversion, and audio combining, especially with offline Piper output).
- `ca-certificates` helps with HTTPS downloads (PyPI, Hugging Face model downloads, Edge TTS).

Optional (for better Kindle format support):

```bash
sudo apt install -y calibre
```

`ebook-convert` (Calibre) can be used as a fallback to extract/convert some MOBI/AZW3 files. DRM-protected Kindle books cannot be processed.

Verify versions:

```bash
python3 --version
ffmpeg -version | head -n 1
```

---

## 3) Get the BookCoder source

If you already have the project directory (for example `bookcoder/`), change into it:

```bash
cd /path/to/bookcoder
```

The commands below assume you are in the project root (the directory containing `pyproject.toml`, `requirements.txt`, and the `bookcoder/` Python package).

If the project is in an archive, extract it first:

```bash
# example
tar -xf bookcoder.tar.gz
cd bookcoder
```

---

## 4) Install BookCoder and Python dependencies

### Quick install with `install.sh` (recommended for Debian/Linux)

BookCoder includes an interactive installer script that can set up a virtual environment, detect/select NVIDIA/AMD/CPU targets, install base dependencies, install PyTorch for the selected target (with CPU fallback if a GPU wheel/tag is unavailable for your Python/platform), and install heavy-engine dependencies.

```bash
cd /path/to/bookcoder
./install.sh
```

The installer will:
- ask for an install location (default: `~/bookcoder`) and copy project files there
- detect NVIDIA/AMD GPUs (or let you choose NVIDIA/AMD/CPU if detection is unclear)
- let you choose a Python interpreter for the virtual environment (useful when multiple Python versions are installed)
- create/reuse `<install_location>/.venv`
- install base requirements and BookCoder
- install PyTorch (`torch`, `torchaudio`) for the selected target; if a selected CUDA/ROCm wheel tag cannot be installed for your Python version/platform, it can retry another tag or fall back to CPU PyTorch
- install MMS-TTS dependencies (`transformers>=4.41`, `numpy`, `scipy`) and attempt to install Coqui TTS (`TTS>=0.22.0`, optional)
  - if Coqui TTS is unavailable (common on newer Python versions such as 3.13), the installer warns and continues so Edge/Piper/MMS-TTS can still be used

You can also override the Python interpreter directly:

```bash
PYTHON_BIN=python3.12 ./install.sh
```

> The installer installs Python packages/PyTorch wheels only. It does **not** install system GPU drivers, CUDA, or ROCm.

### Manual install (virtual environment)

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade pip (recommended) and install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Alternatively, install the project in editable mode:

```bash
pip install -e .
```

### Installed Python dependencies

The app uses (among others):
- `flask` — local web UI/server
- `edge-tts` — online neural TTS
- `piper-tts` — offline neural TTS runtime
- `ebooklib`, `beautifulsoup4`, `lxml`, `mobi` — ebook parsing/extraction (EPUB/MOBI/AZW3 handling paths)
- `langdetect` — language detection support
- `pydub` — audio processing helpers (works best with FFmpeg installed)

#### Optional heavy TTS engines (not installed by default)

Additional engines are supported when their dependencies are installed (they will appear as unavailable with install hints until then):

- **Coqui XTTS v2**: `pip install -e ".[coqui]"` (or install `torch`, `torchaudio`, and `TTS>=0.22.0`)
- **Meta MMS-TTS**: `pip install -e ".[mms]"` (or install `torch`, `torchaudio`, `transformers>=4.41`, `numpy`, and `scipy`)
- **Both**: `pip install -e ".[heavy-tts]"`

`install.sh` installs these heavy-engine Python dependencies as part of its setup flow (with PyTorch target selection/CPU fallback and optional/non-fatal handling if Coqui `TTS` is unavailable for the current Python/platform). The Dockerfile, when `BOOKCODER_EXTRAS` is set, explicitly installs `torch`/`torchaudio` and ensures `transformers`, `numpy`, and `scipy` are present (with CPU fallback if a GPU-targeted PyTorch install via `PIP_EXTRA_ARGS` fails).

Notes:
- These engines are **heavy** (PyTorch-based), may download large model files on first use, and can be much slower on CPU.
- Coqui XTTS v2 and MMS-TTS can use GPU acceleration automatically when a compatible GPU-enabled PyTorch build is installed and detected (`torch.cuda.is_available()`).
- Coqui XTTS v2 support depends on the installed `TTS` package/runtime behavior; some setups may require additional configuration (e.g. speaker/reference handling). If unavailable or synthesis fails, BookCoder will report the provider error and you can continue using Edge or Piper.

#### GPU acceleration for heavy engines (NVIDIA / AMD)

BookCoder can **detect** NVIDIA/AMD GPUs and PyTorch acceleration support, and will use the GPU for **Coqui XTTS v2** and **MMS-TTS** when available. BookCoder does **not** install GPU drivers, CUDA, or ROCm automatically.

1. **Install/verify GPU drivers first**
   - **NVIDIA:** install a supported NVIDIA driver for your GPU and Debian release (and reboot if needed). Verify with `nvidia-smi`.
   - **AMD:** install the appropriate AMDGPU/ROCm stack for your GPU and OS. Verify with tools such as `rocminfo` / `rocm-smi` when available. (ROCm support depends on GPU model and distribution; check AMD’s ROCm compatibility matrix/support notes for Debian.)

2. **Install a GPU-enabled PyTorch build** (inside your BookCoder virtual environment)
   - Use the official PyTorch install selector for the correct command/wheels: <https://pytorch.org/get-started/locally/>
   - **NVIDIA (CUDA):** install the CUDA build that matches your driver/runtime compatibility (the PyTorch selector will provide the recommended `pip` command).
   - **AMD (ROCm, Linux):** install the ROCm-enabled PyTorch build supported for your GPU/ROCm version. On ROCm builds, PyTorch typically exposes GPU acceleration via `torch.cuda` APIs as well.
   - After installing PyTorch (and engine deps), you can confirm detection in Python:
     ```bash
     python -c "import torch; print(torch.__version__); print('cuda_available=', torch.cuda.is_available()); print('hip=', getattr(torch.version,'hip',None))"
     ```

3. **Install BookCoder heavy engine dependencies and download models**
   - Install engine deps, e.g. `pip install -e ".[coqui]"`, `pip install -e ".[mms]"`, or `pip install -e ".[heavy-tts]"`
   - Download/load the model in the app’s **Offline Voice Models** panel (or allow first-use download). Large model downloads/caches are managed by the engine/runtime (Hugging Face/Coqui TTS caches, plus BookCoder status markers where applicable).

If a compatible GPU runtime is not detected, BookCoder will fall back to CPU. Performance and compatibility depend on your GPU, drivers, and the installed PyTorch/TTS/Transformers versions.

> If you install behind a proxy or restricted network, configure pip accordingly before installation.

---

## 5) Run BookCoder

From the project directory with the virtual environment activated:

```bash
source .venv/bin/activate
python -m bookcoder
```

By default BookCoder:
- binds to `127.0.0.1` (local only)
- listens on port `8765`
- opens your default browser to `http://127.0.0.1:8765`

### Command-line options

```bash
python -m bookcoder --help
python -m bookcoder --host 127.0.0.1 --port 8765
python -m bookcoder --no-browser
python -m bookcoder --debug
```

Environment variables (optional):
- `BOOKCODER_HOST` — default host (overridden by `--host`)
- `BOOKCODER_PORT` — default port (overridden by `--port`)

Examples:

```bash
# Use a different local port
python -m bookcoder --port 8787

# Start without opening a browser automatically
python -m bookcoder --no-browser
```

After starting, open: `http://127.0.0.1:8765` (or your chosen host/port).

---

## 6) Configure BookCoder (paths, storage, and behavior)

BookCoder stores user settings and downloaded offline models in standard user directories. Most configuration is done through the UI and persisted automatically.

### 6.1 User settings

Default settings file:
- `$XDG_CONFIG_HOME/bookcoder/settings.json` if `XDG_CONFIG_HOME` is set
- otherwise `~/.config/bookcoder/settings.json`

Stored settings include (per language where applicable):
- selected narration engine/provider
- selected voice
- speed/pitch/style preferences
- dynamic tone profile, paragraph/sentence pause controls, and dialogue voice-casting preferences/hooks (including alternate dialogue voice; per language where applicable)
- pronunciation dictionary/map (synthesis-time overrides, with UI import/export and presets)
- output format (MP3 or AAC/M4A)
- output quality/options (e.g. bitrate/combine/pause)
- last output directory

You can edit preferences in the UI; BookCoder saves them automatically.

### 6.2 Offline model storage and management

**Piper voice models** (default directory):
- `$XDG_DATA_HOME/bookcoder/piper-voices/` if `XDG_DATA_HOME` is set
- otherwise `~/.local/share/bookcoder/piper-voices/`

Each downloaded Piper voice stores its `.onnx` and `.onnx.json` files locally.

**Heavy engine models (Coqui XTTS v2, MMS-TTS):**
- Downloaded/cached by the underlying engine libraries (e.g. Coqui TTS cache and Hugging Face cache locations, depending on your environment/configuration)
- BookCoder provides in-app download/progress/status and “use” actions in the **“Offline Voice Models”** panel, plus best-effort delete/remove support (MMS targets Hugging Face cache entries; Coqui deletion may be marker-based/manual depending on cache layout)

In the UI you can download/re-download, remove/delete (where supported), and select downloaded models for narration. Internet access is required for model downloads; synthesis is local after download (subject to installed runtime dependencies).

### 6.3 Audiobook output directory

When generating audio, you choose an output folder in the UI. If none is specified, BookCoder uses a sensible default under your home directory (and remembers your last used output path).

Generated files typically include:
- one audio file per selected chapter (`.mp3` or `.m4a`, depending on selected format)
- optionally one combined audiobook file (`.mp3` or `.m4a`, or `.m4b` for chaptered audiobook output)

> When **M4B** output is selected, BookCoder produces a single combined `.m4b` audiobook with embedded chapter markers and metadata (and may also generate per-chapter `.m4a` source files during processing).

### 6.4 Network and engine behavior

- **Edge Neural TTS (online):** requires internet connectivity to list voices and synthesize speech.
- **Piper (offline):** requires `piper-tts` (installed via dependencies) and at least one downloaded voice model.
  - Internet is needed only to download models.
  - After download, narration works without internet.
- **Coqui XTTS v2 (offline, heavy, optional):** requires `TTS` and `torch` (and related runtime deps). First use may download/load large model data and synthesis can be slow on CPU. Can use NVIDIA/AMD GPU acceleration when a compatible GPU-enabled PyTorch runtime is installed and detected.
- **Meta MMS-TTS (offline, heavy, optional):** requires `transformers` and `torch` (plus common numeric/audio deps). First use may download/cache model files from Hugging Face. Can use NVIDIA/AMD GPU acceleration when a compatible GPU-enabled PyTorch runtime is installed and detected.

### 6.5 Local-only access (recommended)

By default BookCoder binds to `127.0.0.1`, which is recommended for single-user desktop use.

If you bind to another interface (for example `0.0.0.0`) to access it from another device on your network, be aware that BookCoder is designed as a local app and does not include authentication. Use firewall rules and trusted networks only.

---

## Container usage (Dockerfile / Podman Compose)

This project includes a `Dockerfile` and a `podman-compose.yml` for local containerized usage. The container binds the app internally to `0.0.0.0:8765` and the compose file publishes it to **localhost only** (`127.0.0.1:8765`).

The default image installs base dependencies (Edge TTS, Piper, ebook parsing/UI). Heavy offline engines (Coqui XTTS v2, MMS-TTS) and GPU-enabled PyTorch are **optional** and can be added at build time.

### Build and run with Podman Compose

From the project root (`bookcoder/`, where `Dockerfile` and `podman-compose.yml` are located):

```bash
mkdir -p audiobooks
podman-compose up --build
```

Then open: `http://127.0.0.1:8765`

To run in the background:

```bash
podman-compose up --build -d
podman-compose logs -f
```

Stop:

```bash
podman-compose down
```

### Build and run with Docker / Docker Compose

```bash
mkdir -p audiobooks
docker compose -f podman-compose.yml up --build
# or: docker-compose -f podman-compose.yml up --build
```

### Optional heavy engines and GPU builds

The `Dockerfile` supports build args for optional extras and custom pip install arguments:

- `BOOKCODER_EXTRAS` — optional extras from `pyproject.toml` (e.g. `coqui`, `mms`, `heavy-tts`)
- `PIP_EXTRA_ARGS` — extra `pip` args (useful for GPU-enabled PyTorch wheels/index URLs)

When `BOOKCODER_EXTRAS` is set, the image build explicitly installs `torch`/`torchaudio` and ensures `transformers`, `numpy`, and `scipy` are present for heavy engines. If a GPU-targeted PyTorch install using `PIP_EXTRA_ARGS` fails (for example, an incompatible Python/wheel tag), the build falls back to default CPU PyTorch wheels so the image can still run heavy engines on CPU when possible.

Examples:

```bash
# Heavy engines (CPU, large installs/downloads at build/runtime as applicable)
docker build --build-arg BOOKCODER_EXTRAS=heavy-tts -t bookcoder:heavy-cpu .

# NVIDIA example (install CUDA-enabled PyTorch wheels matching your environment)
docker build \
  --build-arg BOOKCODER_EXTRAS=heavy-tts \
  --build-arg PIP_EXTRA_ARGS="--extra-index-url https://download.pytorch.org/whl/cu121" \
  -t bookcoder:nvidia .
```

For AMD ROCm, use ROCm-compatible PyTorch wheels/build args for your GPU/OS (see https://pytorch.org/get-started/locally/ and AMD ROCm docs/support matrix).

**Container GPU runtime notes:**
- **NVIDIA:** requires supported NVIDIA drivers on the host and NVIDIA Container Toolkit/runtime; run containers with GPU access (e.g. `docker run --gpus all ...`, or Podman equivalent).
- **AMD:** typically requires ROCm-compatible host setup and device passthrough (e.g. `/dev/kfd`, `/dev/dri`) with appropriate permissions/groups; runtime support varies by GPU/OS and ROCm/PyTorch versions.
- BookCoder detects GPUs/PyTorch acceleration inside the container and uses GPU for Coqui XTTS/MMS-TTS when `torch.cuda.is_available()` is true. It does not install host drivers/CUDA/ROCm automatically.

### Notes

- **Persistence:** named volumes store BookCoder settings and cached/downloaded data under `/data/config` and `/data/share` (including Piper voices and heavy-engine caches/markers stored in the configured data paths).
- **Audiobook output:** `./audiobooks` on the host is mounted to `/audiobooks` in the container. In the BookCoder UI, set the output folder to a path under `/audiobooks` (e.g. `/audiobooks/MyBook`) to access generated files on the host.
- **Network exposure:** the compose file publishes only to `127.0.0.1` by default. Do not expose it publicly without additional protections.
- **Offline models / online TTS:** container needs internet access for Edge TTS synthesis and for downloading Piper/Coqui/MMS models (downloaded data persists in volumes after download). Heavy models can be large and may take significant time to download/load.

Example (local network use, at your own risk):

```bash
python -m bookcoder --host 0.0.0.0 --port 8765 --no-browser
```

---

## 7) Typical usage workflow

1. Start BookCoder: `python -m bookcoder`
2. Open the UI in your browser (`http://127.0.0.1:8765`)
3. **Import** an EPUB/MOBI/AZW3/TXT file (drag-and-drop or browse)
4. **Review detected language** (English/Hungarian) and override if needed
5. **Select chapters** (include/exclude/reorder)
6. **Choose narration engine and voice**
   - For offline/heavy engines (Piper, Coqui XTTS v2, MMS-TTS), expand **“Offline Voice Models”** to download/manage models as needed before selecting a voice
   - Preview voice and adjust speed/pitch/style
   - Optionally choose a dynamic tone profile, paragraph/sentence pause controls, dialogue/alternate dialogue voices (smart quote-span casting hooks), and pronunciation dictionary entries (with presets/import/export) for more expressive/accurate narration
7. **Configure output**
   - Output folder (default: generated files are saved locally to this directory)
   - Output format: **MP3**, **AAC (.m4a)**, or **M4B (.m4b audiobook, chaptered combined file)**
   - Audio quality (bitrate), chapter pause, optional combined file (for MP3/M4A). **M4B** always produces a single combined audiobook with chapter markers.
   - (Optional) Post-export actions: copy generated files to another folder after generation (e.g. a synced cloud folder, NAS path, or mounted device folder) and/or run a custom command/script. These are **disabled by default**.
8. **Generate audiobook** and monitor progress
   - After generation, use the result actions to open the output folder, reveal/copy file paths, or transfer files using your preferred method.

### iPhone/iPad output tips

- **AAC (.m4a):** best for copying individual chapter files and/or a combined M4A file directly to iPhone/iPad (Files, Music, or Apple Books workflows depending on your setup).
- **M4B (.m4b):** best for a single chaptered audiobook in **Apple Books** or audiobook player apps. BookCoder embeds chapter markers and audiobook metadata (title/author/language/genre) in the combined M4B (FFmpeg recommended/required for reliable chapter/metadata muxing).
- M4B is an audiobook format (not a podcast RSS feed format). To listen on iPhone/iPad from a PC, transfer/import the `.m4b` into Apple Books or an audiobook app (e.g. via Finder/iTunes/Apple Devices sync, AirDrop, iCloud Drive/Files, or file sharing depending on your environment).
- **BookCoder does not perform direct iPhone/Books device integration.** By default it saves audiobooks to your chosen output folder. You can optionally enable post-export copying to a destination folder (e.g. a synced/mounted path) or run a custom transfer command/script after generation.

---

## 8) Optional: run with a convenience script

You can create a small launcher script in the project directory:

```bash
cat > run-bookcoder.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -m bookcoder "$@"
EOF
chmod +x run-bookcoder.sh
```

Run it:

```bash
./run-bookcoder.sh
./run-bookcoder.sh --no-browser --port 8787
```

---

## 9) Optional: systemd user service (Debian)

To start BookCoder automatically for your user session, you can create a **user** systemd service.

> Adjust paths and port as needed. Keep `--host 127.0.0.1` unless you explicitly need remote access.

1. Create the service file:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/bookcoder.service <<'EOF'
[Unit]
Description=BookCoder AI Audiobook Generator (local web UI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/path/to/bookcoder
ExecStart=%h/path/to/bookcoder/.venv/bin/python -m bookcoder --host 127.0.0.1 --port 8765 --no-browser
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
```

2. Reload and enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now bookcoder.service
```

3. Check status/logs:

```bash
systemctl --user status bookcoder.service
journalctl --user -u bookcoder.service -f
```

4. Open the UI manually in your browser:

```text
http://127.0.0.1:8765
```

To stop/disable:

```bash
systemctl --user disable --now bookcoder.service
```

---

## 10) Troubleshooting (Debian)

### `python3 -m venv` fails or `.venv` missing `pip`
- Ensure venv support is installed:
  ```bash
  sudo apt install -y python3-venv python3-pip
  ```
- Recreate the environment:
  ```bash
  rm -rf .venv
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  ```

### Dependency installation fails (network/proxy/SSL)
- Verify internet access and certificates:
  ```bash
  sudo apt install -y ca-certificates
  ```
- If behind a proxy, configure pip/proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`) and retry.

### Piper offline models cannot be downloaded
- Model downloads require internet access to Hugging Face (`https://huggingface.co/rhasspy/piper-voices/...`).
- Check connectivity:
  ```bash
  curl -I https://huggingface.co
  ```
- Retry from the **Offline Voice Models (Piper)** panel in the UI.
- Confirm write permissions to the models directory:
  - `~/.local/share/bookcoder/piper-voices/` (or `$XDG_DATA_HOME/bookcoder/piper-voices/`)

### AZW3/MOBI file cannot be parsed
- AZW3/MOBI extraction depends on available parsers/converters in your environment.
- Install/reinstall dependencies in the virtual environment (`mobi` package is included in project dependencies).
- If parsing still fails, install Calibre for `ebook-convert` fallback:
  ```bash
  sudo apt install -y calibre
  ebook-convert --version | head -n 1
  ```
- DRM-protected Kindle books cannot be converted or narrated by BookCoder.

### No audio / MP3, M4A, or M4B conversion issues / combine fails / missing chapter markers
- Install FFmpeg (required/recommended for reliable encoding, format conversion, audio combining, and M4B chapter/metadata embedding):
  ```bash
  sudo apt install -y ffmpeg
  ffmpeg -version | head -n 1
  ```
- For iPhone-compatible output, choose **AAC (.m4a)** (chapter/combined files) or **M4B (.m4b)** (single chaptered audiobook) in the UI.
- If an M4B file is created but chapters are missing, ensure FFmpeg is installed and up to date (chapter markers are muxed via FFmpeg metadata).
- Restart BookCoder after installing FFmpeg.

### Edge TTS voices or synthesis fail
- Edge engine requires internet access.
- If you need offline narration, switch to **Piper (Offline)** and download a voice model.

### Port already in use
- Start on another port:
  ```bash
  python -m bookcoder --port 8787
  ```

### Browser does not open automatically
- Start with `--no-browser` intentionally, or open manually:
  ```bash
  python -m bookcoder --no-browser
  # then visit http://127.0.0.1:8765
  ```

---

### Narration quality and casting notes

- **Text normalization/pronunciation:** synthesis-time normalization can apply abbreviation/symbol/date-time cleanup and user-defined pronunciation overrides (dictionary/presets/import-export).
- **Structure-aware segmentation:** narration is planned with paragraph/scene/title-aware pauses and subtle prosody hints (provider-safe).
- **Dialogue casting heuristics:** BookCoder can detect dialogue blocks and quoted spans (intra-paragraph heuristics) and apply dialogue voice-casting hooks. An optional alternate dialogue voice can be used for alternating quoted speakers (heuristic, not speaker attribution).
- **Fallbacks:** advanced tone/casting features degrade safely per engine/provider capability (e.g. pitch hints only where supported).

---

## 11) Project structure (for reference)

- `bookcoder/core/` — parsing (EPUB/MOBI/AZW3/TXT), language detection, TTS providers, audio pipeline, settings
- `bookcoder/core/tts/` — TTS abstraction, Edge provider, Piper provider/catalog/model manager
- `bookcoder/ui/` — Flask server and web UI (templates/static)
- `bookcoder/__main__.py` — CLI entry point (`python -m bookcoder`)

---

## Notes

- Generated audiobooks and intermediate processing are performed locally.
- Online narration (Edge) sends synthesis requests to Microsoft’s Edge TTS service.
- Offline narration (Piper) runs locally after models are downloaded.
- For best results (especially with long books), keep FFmpeg installed and ensure sufficient disk space in your output and model directories.

---

## License

BookCoder is licensed under the **GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)**.

- You are free to use, study, modify, and redistribute this software.
- If you modify BookCoder and distribute it, or run a modified version as a network-accessible service, you must make the corresponding source code available under the same license (see AGPLv3 Section 13 for network interaction requirements).
- This program is distributed in the hope that it will be useful, but **WITHOUT ANY WARRANTY**; without even the implied warranty of **MERCHANTABILITY** or **FITNESS FOR A PARTICULAR PURPOSE**.

See the full license text in [`LICENSE`](LICENSE).

> **Note:** BookCoder depends on third-party libraries, runtimes, and tools (e.g. Python packages, FFmpeg/Calibre, and downloaded TTS/voice models) that are distributed under their own licenses/terms. Ensure you comply with those licenses when using or redistributing BookCoder and its dependencies/models.

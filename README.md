# BookCoder — AI Audiobook Generator

BookCoder is a local desktop-style web application for converting ebooks and text documents into high-quality audiobooks with natural-sounding AI narration.

It supports **EPUB**, **MOBI**, **AZW3**, and **TXT** input, automatic **English/Hungarian** language detection, chapter extraction, and audiobook generation with both **online** (Microsoft Edge Neural TTS) and **offline** (Piper) voice engines. Output can be generated as **MP3** or **AAC in M4A** (recommended for direct copy to iPhone).

This README explains how to **install and configure BookCoder on Debian**.

---

## Features

- **Input formats:** `.epub`, `.mobi`, `.azw3`, `.txt`
- **Import:** drag-and-drop or file browser, validation/error messages, remove/replace before processing
- **Language detection:** detects English or Hungarian from book text, with manual override
- **Narration engines:**
  - **Edge Neural TTS (online):** natural neural voices, no API key required (internet needed for synthesis/voice listing)
  - **Piper (offline):** local neural TTS; works offline after voice models are downloaded
- **Voices:** English and Hungarian, male/female options (engine-dependent), voice previews, speed/pitch/style controls, dynamic tone profiles, and optional dialogue voice-casting hook
- **Offline model management (Piper):** in-app download, progress, delete, and “use voice” for recommended models
- **Chapters:** automatic extraction/section detection, include/exclude, reorder, per-chapter audio output
- **Output formats:** **MP3 (.mp3)** and **AAC (.m4a, iPhone-compatible)**
  - Separate file per chapter and optional combined audiobook
  - Configurable bitrate/quality and chapter pause
  - **AAC/M4A** output is recommended for direct copy to iPhone (Apple Books/Music/Files workflows)

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
- **FFmpeg** strongly recommended for best audio encoding/normalization and chapter/audio concatenation (MP3 and AAC/M4A)
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

## 4) Create a Python virtual environment and install dependencies

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
- dynamic tone profile and optional dialogue voice preference (per language where applicable)
- output format (MP3 or AAC/M4A)
- output quality/options (e.g. bitrate/combine/pause)
- last output directory

You can edit preferences in the UI; BookCoder saves them automatically.

### 6.2 Offline Piper model storage

Default Piper voice model directory:
- `$XDG_DATA_HOME/bookcoder/piper-voices/` if `XDG_DATA_HOME` is set
- otherwise `~/.local/share/bookcoder/piper-voices/`

Each downloaded voice stores its `.onnx` and `.onnx.json` files locally. You can:
- download/re-download models in the **“Offline Voice Models (Piper)”** panel
- delete models from the UI to free disk space

### 6.3 Audiobook output directory

When generating audio, you choose an output folder in the UI. If none is specified, BookCoder uses a sensible default under your home directory (and remembers your last used output path).

Generated files typically include:
- one audio file per selected chapter (`.mp3` or `.m4a`, depending on selected format)
- optionally one combined audiobook file (`.mp3` or `.m4a`)

### 6.4 Network and engine behavior

- **Edge Neural TTS (online):** requires internet connectivity to list voices and synthesize speech.
- **Piper (offline):** requires `piper-tts` (installed via dependencies) and at least one downloaded voice model.
  - Internet is needed only to download models.
  - After download, narration works without internet.

### 6.5 Local-only access (recommended)

By default BookCoder binds to `127.0.0.1`, which is recommended for single-user desktop use.

If you bind to another interface (for example `0.0.0.0`) to access it from another device on your network, be aware that BookCoder is designed as a local app and does not include authentication. Use firewall rules and trusted networks only.

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
   - For **Piper (Offline)**, download a recommended voice in **“Offline Voice Models (Piper)”** first
   - Preview voice and adjust speed/pitch/style
   - Optionally choose a dynamic tone profile and/or a dialogue voice (casting hook) for more expressive narration
7. **Configure output**
   - Output folder
   - Output format: **MP3** or **AAC (.m4a)** (choose AAC/M4A for direct copy to iPhone)
   - Audio quality (bitrate), chapter pause, optional combined file
8. **Generate audiobook** and monitor progress

### iPhone output tip

- Select **AAC (.m4a)** as the output format for best compatibility when copying files directly to an iPhone.
- Generated chapter and/or combined `.m4a` files can be transferred to your device using your preferred method (e.g. Finder/AirDrop/iCloud Drive/Files workflows, depending on your setup).

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

### No audio / MP3 or M4A conversion issues / combine fails
- Install FFmpeg (required/recommended for reliable encoding and format conversion):
  ```bash
  sudo apt install -y ffmpeg
  ffmpeg -version | head -n 1
  ```
- For iPhone-compatible output, choose **AAC (.m4a)** in the UI.
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

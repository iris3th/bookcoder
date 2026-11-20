# Changelog

All notable changes to BookCoder are documented in this file.

## [3.0.0] - 2026-11-20

A major feature release adding chaptered M4B audiobook export and post-generation export helpers.

### Added
- **M4B audiobook output (`.m4b`)**
  - Added **M4B** as an output format for audiobook workflows (recommended for chaptered audiobooks in Apple Books and compatible audiobook apps on iPhone/iPad).
  - Combined M4B export embeds **chapter markers/titles** and audiobook metadata (title/album, author/artist, language, genre, comment) via FFmpeg metadata/chapter muxing when available.
  - M4B export always produces a **single combined audiobook file** (`<Book title> - Complete Audiobook.m4b`) with embedded chapters; selecting M4B automatically enables/locks the “combine into one audiobook file” option in the UI and server-side generation flow.
  - In M4B mode, per-chapter source audio may also be generated as AAC **`.m4a`** files during processing, while the final chaptered deliverable is the combined `.m4b`.
  - `output_format`/settings handling updated to recognize and persist `m4b`.
- **Output/export helpers (default save-to-directory behavior preserved)**
  - Added UI actions to **open the output folder**, **reveal the combined file**, and **copy output/combined file paths** after successful generation.
  - Added optional **post-export actions** (disabled by default):
    - Copy generated chapter/combined files to another folder (e.g. synced cloud folder, NAS path, or mounted device folder) while keeping originals in the output folder.
    - Run a custom post-export command/script in the output folder with environment variables: `BOOKCODER_OUTPUT_DIR`, `BOOKCODER_COMBINED_FILE`, `BOOKCODER_CHAPTER_FILES`.
  - Added `POST /api/open-path` for local file-manager open/reveal actions and persisted post-export preferences in settings (`post_export`).
  - Post-export summaries/errors are surfaced in generation results/UI; if post-export actions fail, generated audiobook files remain in the original output directory.
- **UI version display**
  - The running BookCoder package version is now shown discreetly in the web UI footer (e.g. `v3.0.0`), sourced from the application `__version__`.

### Changed
- Improved output/result and format-help messaging for **MP3/M4A/M4B** and iPhone/iPad transfer workflows (including Apple Books audiobook guidance), without adding direct iOS/Books device integration.
- Updated audio/pipeline/UI/server behavior to support M4B format selection, combined-only M4B export, and chapter/metadata-aware final audiobook output.

### Notes
- **FFmpeg** is recommended for reliable AAC/M4A/M4B encoding and combining, and required for reliable M4B chapter marker/metadata embedding.
- M4B is an audiobook container format (not a podcast RSS feed format). To listen on iPhone/iPad from a PC, transfer/import the generated `.m4b` into Apple Books or an audiobook app (e.g. Finder/iTunes/Apple Devices sync, AirDrop, iCloud Drive/Files, or file sharing).
- Post-export actions are optional convenience helpers (copy/command hooks) and do not implement direct iPhone/Books device integration.

## [2.1.0] - 2026-11-19

### Fixed
- **Hungarian long-character normalization for ebook text (MOBI/EPUB/HTML parsing)**
  - Improved understanding and restoration of Hungarian accented characters (`á`, `é`, `í`, `ó`, `ö`, `ő`, `ú`, `ü`, `ű`) in extracted/narration text.
  - Added mojibake repair and NFC/NFKC-aware normalization, including handling for spaced/combining/hyphen/dash accent-mark forms.
  - Added broad, codepage-aware confusable mapping to recover common mis-decoded forms in uploaded ebooks (notably CP1250/ISO-8859-2 vs CP1252/ISO-8859-1 cases such as `õ/Õ/û/Û -> ő/Ő/ű/Ű`, and Hungarian-context `ò/Ò -> ó/Ó`), with multi-encoding round-trip candidates and safe scoring in parsing/decoding.

### Changed
- **Licensing (AGPL-3.0-or-later)**
  - Added `LICENSE` with the full GNU Affero General Public License v3 text and adopted **AGPL-3.0-or-later** for BookCoder distribution/use/modification.
  - Updated project metadata (`pyproject.toml`) with AGPL license information/classifiers.
  - Added a GitHub-visible License section to `README.md` documenting AGPL-3.0-or-later terms, network-use/source-availability (AGPLv3 §13), no-warranty notice, and third-party dependency/model license considerations.

## [2.0.0] - 2026-11-18

A major milestone release expanding BookCoder from a core local audiobook generator into a multi-engine, multi-format narration studio with offline model management, improved narration controls, and hardware acceleration support.

### Added
- **Multi-format ebook/text input and audiobook output**
  - Input support for `.epub`, `.mobi`, `.azw3`, and `.txt` (DRM-protected Kindle files not supported)
  - Audiobook export as **MP3** or **AAC/M4A** (iPhone-friendly), with per-chapter files and optional combined audiobook output
  - Configurable audio quality/bitrate options (including 64/96/128/160/192 kbps) and chapter pause settings
- **Language detection and bilingual narration workflow**
  - Automatic English/Hungarian text language detection with manual override
  - Language-aware voice selection and per-language narration settings persistence
- **Narration engine architecture and providers**
  - Pluggable TTS provider/registry architecture
  - **Edge Neural TTS (online)** provider integration
  - **Piper (offline)** provider with local neural synthesis and downloadable voice models
  - **Coqui XTTS v2 (offline, heavy, optional)** provider for multilingual EN/HU neural synthesis
  - **Meta MMS-TTS (offline, heavy, optional)** provider for EN/HU VITS synthesis via Transformers/PyTorch
  - Optional dependency extras for heavy engines: `coqui`, `mms`, `heavy-tts`
- **Offline voice/model management (in-app)**
  - Piper voice catalog/manager with download, progress tracking, delete/remove, status, and “Use” actions
  - Recommended Piper voices for English and Hungarian (including all 3 Hungarian voices exposed as downloadable options)
  - Generalized offline model APIs/UI for `piper`, `coqui-xtts`, and `mms-tts` (provider-aware download/status/delete/use, aggregated listing, progress polling)
  - Download/cache handling for heavy engine models (Coqui XTTS v2 shared model marker/download flow, MMS Hugging Face cache integration)
- **Narration quality and control features**
  - Text normalization/pronunciation hooks with pronunciation dictionary/map support
  - Pronunciation presets and import/export support
  - Chapter/paragraph/sentence-aware segmentation with configurable pauses and `sentence_pause_hint` handling
  - Dynamic tone profiles and provider-aware narration behavior
  - Dialogue and alternate-voice casting hooks/heuristics for more expressive narration
  - Voice preview support and engine/voice status feedback in UI
- **Web UI and workflow improvements**
  - Flask-based local web UI for upload, chapter management, narration setup, generation, progress, and cancellation
  - Drag-and-drop/file upload, chapter include/exclude/reorder, and generation progress/cancel flow
  - Output folder suggestion/path refresh based on the loaded/dropped book
  - Collapsible chapters panel (collapsed by default) to reduce scrolling
  - Collapsible **Offline Voice Models** panel with expand/hide controls and summary/status display
  - Improved offline model actions and presentation (download/re-download, trash/remove, use, provider/language/status tags)
  - UI copy/section labeling refinements for clearer navigation
- **Hardware acceleration detection and GPU-aware runtime behavior**
  - Hardware detection for NVIDIA/AMD GPUs and PyTorch acceleration availability (CUDA/ROCm)
  - `/api/hardware` endpoint and UI engine/hardware status reporting
  - Automatic GPU usage for supported heavy engines when a compatible GPU-enabled PyTorch runtime is available (with CPU fallback)
  - MMS synthesis path updated to use GPU device placement when available
- **Packaging, deployment, and documentation**
  - Project packaging/configuration (`pyproject.toml`, module entrypoint, local settings/model/data paths)
  - Interactive `install.sh` for Debian/Linux: install location selection, NVIDIA/AMD GPU detection or manual target selection, Python interpreter selection, virtual environment setup, base/heavy dependency installation, and PyTorch target selection
  - Installer resilience for heavy engines: CPU fallback when a selected CUDA/ROCm PyTorch wheel/tag is unavailable for the current Python/platform, separate/verified installation of MMS-TTS dependencies (`transformers`, `numpy`, `scipy`), and non-fatal handling when optional Coqui TTS (`TTS>=0.22.0`) cannot be installed (e.g. newer Python versions)
  - Dockerfile and Podman Compose configuration for local containerized usage
  - Docker build customization for optional heavy-engine extras and pip install args (`BOOKCODER_EXTRAS`, `PIP_EXTRA_ARGS`) with NVIDIA/AMD container runtime guidance, explicit heavy-dependency installation, and CPU PyTorch fallback when GPU-targeted wheel installs fail
  - Expanded README covering installation (`install.sh` and manual setup), engine/model setup, offline model management, GPU acceleration (NVIDIA/AMD), and container usage
  - Source distribution/tarball packaging workflow for upload-ready builds

### Changed
- Evolved UI from Piper-specific offline model handling to a unified, provider-aware offline model management experience
- Improved default UI behavior for large books and model lists by collapsing chapter/model sections and surfacing summaries
- Refined provider/voice selection and availability messaging for online/offline/heavy engines

### Notes
- Coqui XTTS v2 and MMS-TTS are optional and may require large dependency/model downloads; performance varies by CPU/GPU and installed runtime.
- GPU acceleration depends on host drivers and a compatible CUDA/ROCm-enabled PyTorch installation. BookCoder detects and uses available acceleration but does not install system GPU drivers/toolkits automatically.
- PyTorch wheel availability varies by Python version, platform, and CUDA/ROCm tag. `install.sh` and the Dockerfile include CPU fallback behavior when a selected GPU wheel install is unavailable/incompatible, but GPU acceleration requires a compatible installed runtime.
- Coqui TTS package support may lag newer Python releases (e.g. Python 3.13); when `TTS>=0.22.0` cannot be installed, Coqui XTTS v2 may remain unavailable while other engines (Edge, Piper, MMS-TTS) can still work.
- Some Coqui model cache deletion behavior is runtime/cache-layout dependent and may be best-effort in-app.

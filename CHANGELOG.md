# Changelog

All notable changes to BookCoder are documented in this file.

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
  - Dockerfile and Podman Compose configuration for local containerized usage
  - Docker build customization for optional heavy-engine extras and pip install args (`BOOKCODER_EXTRAS`, `PIP_EXTRA_ARGS`) with NVIDIA/AMD container runtime guidance
  - Expanded README covering installation, engine/model setup, offline model management, GPU acceleration (NVIDIA/AMD), and container usage
  - Source distribution/tarball packaging workflow for upload-ready builds

### Changed
- Evolved UI from Piper-specific offline model handling to a unified, provider-aware offline model management experience
- Improved default UI behavior for large books and model lists by collapsing chapter/model sections and surfacing summaries
- Refined provider/voice selection and availability messaging for online/offline/heavy engines

### Notes
- Coqui XTTS v2 and MMS-TTS are optional and may require large dependency/model downloads; performance varies by CPU/GPU and installed runtime.
- GPU acceleration depends on host drivers and a compatible CUDA/ROCm-enabled PyTorch installation. BookCoder detects and uses available acceleration but does not install system GPU drivers/toolkits automatically.
- Some Coqui model cache deletion behavior is runtime/cache-layout dependent and may be best-effort in-app.

from __future__ import annotations

import os
import shutil
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..models import Language
from .piper_catalog import PiperVoiceModel, get_by_key, get_by_voice_id, get_catalog


def default_models_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "bookcoder" / "piper-voices"


@dataclass
class VoiceDownloadStatus:
    key: str
    voice_id: str
    name: str
    language: str
    gender: str
    locale: str
    quality: str
    description: str
    size_hint_mb: int
    recommended: bool
    downloaded: bool
    model_path: Optional[str] = None
    config_path: Optional[str] = None
    partial: bool = False
    downloading: bool = False
    provider_id: str = "piper"


ProgressCallback = Callable[[int, int, str], None]  # downloaded_bytes, total_bytes(-1 if unknown), message


class PiperModelManager:
    def __init__(self, models_dir: Optional[Path] = None) -> None:
        self.models_dir = Path(models_dir) if models_dir else default_models_dir()
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._active_downloads: set[str] = set()
        self._lock = threading.Lock()

    def voice_dir(self, model: PiperVoiceModel) -> Path:
        # keep each voice in its own folder
        return self.models_dir / model.region / model.voice_name / model.quality

    def model_path(self, model: PiperVoiceModel) -> Path:
        return self.voice_dir(model) / model.model_filename

    def config_path(self, model: PiperVoiceModel) -> Path:
        return self.voice_dir(model) / model.config_filename

    def is_downloaded(self, model: PiperVoiceModel) -> bool:
        mp = self.model_path(model)
        cp = self.config_path(model)
        try:
            return mp.is_file() and mp.stat().st_size > 0 and cp.is_file() and cp.stat().st_size > 0
        except Exception:
            return False

    def is_partial(self, model: PiperVoiceModel) -> bool:
        mp = self.model_path(model)
        cp = self.config_path(model)
        try:
            m_exists = mp.exists()
            c_exists = cp.exists()
            if not m_exists and not c_exists:
                return False
            return not self.is_downloaded(model)
        except Exception:
            return False

    def get_status(self, model: PiperVoiceModel) -> VoiceDownloadStatus:
        with self._lock:
            downloading = model.key in self._active_downloads
        downloaded = self.is_downloaded(model)
        return VoiceDownloadStatus(
            key=model.key,
            voice_id=model.voice_id,
            name=model.name,
            language=model.language.value,
            gender=model.gender,
            locale=model.locale,
            quality=model.quality,
            description=model.description,
            size_hint_mb=model.size_hint_mb,
            recommended=model.recommended,
            downloaded=downloaded,
            model_path=str(self.model_path(model)) if downloaded else None,
            config_path=str(self.config_path(model)) if downloaded else None,
            partial=self.is_partial(model),
            downloading=downloading,
            provider_id="piper",
        )

    def list_statuses(self, language: Optional[Language] = None) -> list[VoiceDownloadStatus]:
        return [self.get_status(m) for m in get_catalog(language)]

    def resolve_paths(self, voice_id_or_key: str) -> tuple[Path, Path, PiperVoiceModel]:
        model = get_by_voice_id(voice_id_or_key)
        if not model:
            raise FileNotFoundError(f"Unknown Piper voice: {voice_id_or_key}")
        if not self.is_downloaded(model):
            raise FileNotFoundError(
                f"Voice '{model.name}' is not downloaded. Please download it from the Offline Models settings."
            )
        return self.model_path(model), self.config_path(model), model

    def download(self, key: str, progress: Optional[ProgressCallback] = None) -> VoiceDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown voice model key: {key}")

        with self._lock:
            if key in self._active_downloads:
                raise RuntimeError(f"Voice '{model.name}' is already being downloaded.")
            self._active_downloads.add(key)

        try:
            vdir = self.voice_dir(model)
            vdir.mkdir(parents=True, exist_ok=True)

            # Download config first (small), then model (large)
            self._download_file(
                model.config_url,
                self.config_path(model),
                progress=progress,
                label=f"Downloading {model.name} config",
            )
            self._download_file(
                model.model_url,
                self.model_path(model),
                progress=progress,
                label=f"Downloading {model.name} model",
            )

            if not self.is_downloaded(model):
                raise RuntimeError(f"Download completed but files are missing or empty for '{model.name}'.")

            if progress:
                progress(0, 0, f"{model.name} downloaded successfully.")
            return self.get_status(model)
        except Exception:
            # keep partial? better to clean incomplete files to avoid confusion
            self._cleanup_partial(model)
            raise
        finally:
            with self._lock:
                self._active_downloads.discard(key)

    def delete(self, key: str) -> VoiceDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown voice model key: {key}")
        with self._lock:
            if key in self._active_downloads:
                raise RuntimeError("Cannot delete a voice while it is downloading.")
        vdir = self.voice_dir(model)
        try:
            if vdir.exists():
                shutil.rmtree(vdir)
        except Exception as e:
            raise RuntimeError(f"Failed to delete voice files: {e}") from e
        # clean empty parents best-effort
        for parent in [vdir.parent, vdir.parent.parent]:
            try:
                if parent.exists() and parent != self.models_dir and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception:
                pass
        return self.get_status(model)

    def _cleanup_partial(self, model: PiperVoiceModel) -> None:
        for p in [self.model_path(model), self.config_path(model)]:
            try:
                if p.exists() and p.stat().st_size == 0:
                    p.unlink()
            except Exception:
                pass
        # if config exists but model missing, remove config too? leave as-is; is_partial will reflect state

    def _download_file(self, url: str, dest: Path, progress: Optional[ProgressCallback], label: str) -> None:
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

        req = urllib.request.Request(url, headers={"User-Agent": "BookCoder/0.1 (offline TTS model downloader)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = -1
                try:
                    cl = resp.headers.get("Content-Length")
                    if cl:
                        total = int(cl)
                except Exception:
                    total = -1
                downloaded = 0
                chunk_size = 1024 * 256
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total, label)
            tmp.replace(dest)
        except Exception as e:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise RuntimeError(f"Failed to download {dest.name}: {e}") from e

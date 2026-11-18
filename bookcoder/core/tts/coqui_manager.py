from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..models import Language
from .coqui_catalog import CoquiVoiceModel, get_by_key, get_catalog


def _status_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    d = base / "bookcoder" / "engine-models"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class CoquiDownloadStatus:
    key: str
    provider_id: str
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


ProgressCallback = Callable[[int, int, str], None]


class CoquiModelManager:
    """Manage Coqui TTS model downloads for XTTS v2.

    Uses a BookCoder-managed marker after successful download to avoid triggering
    large downloads during status checks (Coqui APIs vary across versions).
    """

    _MARKER = "coqui-xtts-v2"

    def __init__(self) -> None:
        self._active_downloads: set[str] = set()
        self._lock = threading.Lock()

    def _marker_path(self) -> Path:
        return _status_dir() / f"{self._MARKER}.json"

    def _shared_downloaded(self) -> bool:
        p = self._marker_path()
        if not p.is_file():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return bool(data.get("downloaded"))
        except Exception:
            return False

    def _set_shared_downloaded(self, downloaded: bool) -> None:
        p = self._marker_path()
        if downloaded:
            p.write_text(json.dumps({"downloaded": True, "model_name": "tts_models/multilingual/multi-dataset/xtts_v2"}), encoding="utf-8")
        else:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    def is_downloaded(self, model: CoquiVoiceModel) -> bool:
        # XTTS v2 EN/HU share the same underlying model.
        return self._shared_downloaded()

    def get_status(self, model: CoquiVoiceModel) -> CoquiDownloadStatus:
        with self._lock:
            downloading = model.key in self._active_downloads
        downloaded = self.is_downloaded(model) if not downloading else False
        desc = model.description
        if "shared" not in desc.lower():
            desc = desc + " (Shared XTTS v2 model for EN/HU; downloading either entry prepares both.)"
        return CoquiDownloadStatus(
            key=model.key,
            provider_id=model.provider_id,
            voice_id=model.voice_id,
            name=model.name,
            language=model.language.value,
            gender=model.gender,
            locale=model.locale,
            quality="XTTS v2",
            description=desc,
            size_hint_mb=model.size_hint_mb,
            recommended=True,
            downloaded=downloaded,
            model_path=None,
            config_path=None,
            partial=False,
            downloading=downloading,
        )

    def list_statuses(self, language: Optional[Language] = None) -> list[CoquiDownloadStatus]:
        return [self.get_status(m) for m in get_catalog(language)]

    def download(self, key: str, progress: Optional[ProgressCallback] = None) -> CoquiDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown Coqui model key: {key}")
        # Use shared key lock behavior by marking both? easier: allow one active for shared model
        shared_lock_key = self._MARKER
        with self._lock:
            if shared_lock_key in self._active_downloads or key in self._active_downloads:
                raise RuntimeError("XTTS v2 model download is already in progress.")
            self._active_downloads.add(shared_lock_key)
            self._active_downloads.add(key)
        try:
            if progress:
                progress(0, -1, f"Downloading/loading {model.name} (Coqui XTTS v2, large model)...")
            # Trigger Coqui model download. Instantiate TTS (downloads if needed).
            try:
                import torch
                from TTS.api import TTS

                use_gpu = False
                try:
                    use_gpu = bool(torch.cuda.is_available())
                except Exception:
                    use_gpu = False
                TTS(model_name=model.model_name, progress_bar=False, gpu=use_gpu)
            except Exception as e:
                raise RuntimeError(f"Failed to download/initialize Coqui XTTS v2 model: {e}") from e
            self._set_shared_downloaded(True)
            if progress:
                progress(0, 0, "Coqui XTTS v2 model download completed.")
            return self.get_status(model)
        except Exception:
            # keep marker unchanged on failure
            raise
        finally:
            with self._lock:
                self._active_downloads.discard(shared_lock_key)
                self._active_downloads.discard(key)

    def delete(self, key: str) -> CoquiDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown Coqui model key: {key}")
        with self._lock:
            if self._MARKER in self._active_downloads or key in self._active_downloads:
                raise RuntimeError("Cannot delete a model while it is downloading.")
        # Removing actual Coqui cache is version/path-dependent; clear BookCoder marker so UI allows re-download.
        self._set_shared_downloaded(False)
        return self.get_status(model)

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..models import Language
from .mms_catalog import MMSVoiceModel, get_by_key, get_catalog


@dataclass
class MMSDownloadStatus:
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


class MMSModelManager:
    """Manage Hugging Face cached models for MMS-TTS provider."""

    def __init__(self) -> None:
        self._active_downloads: set[str] = set()
        self._lock = threading.Lock()

    def is_downloaded(self, model: MMSVoiceModel) -> bool:
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=model.repo_id, local_files_only=True)
            return True
        except Exception:
            # fallback: try transformers local-only load check paths? avoid heavy load
            return False

    def is_partial(self, model: MMSVoiceModel) -> bool:
        # Hard to detect partial HF cache reliably; treat as not partial.
        return False

    def get_status(self, model: MMSVoiceModel) -> MMSDownloadStatus:
        with self._lock:
            downloading = model.key in self._active_downloads
        downloaded = self.is_downloaded(model) if not downloading else False
        cache_dir = self._cache_hint(model) if downloaded else None
        return MMSDownloadStatus(
            key=model.key,
            provider_id=model.provider_id,
            voice_id=model.voice_id,
            name=model.name,
            language=model.language.value,
            gender=model.gender,
            locale=model.locale,
            quality="VITS",
            description=model.description,
            size_hint_mb=model.size_hint_mb,
            recommended=True,
            downloaded=downloaded,
            model_path=cache_dir,
            config_path=cache_dir,
            partial=self.is_partial(model),
            downloading=downloading,
        )

    def list_statuses(self, language: Optional[Language] = None) -> list[MMSDownloadStatus]:
        return [self.get_status(m) for m in get_catalog(language)]

    def download(self, key: str, progress: Optional[ProgressCallback] = None) -> MMSDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown MMS model key: {key}")
        with self._lock:
            if key in self._active_downloads:
                raise RuntimeError(f"Model '{model.name}' is already being downloaded.")
            self._active_downloads.add(key)
        try:
            if progress:
                progress(0, -1, f"Downloading {model.name} (Hugging Face cache)...")
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=model.repo_id, local_files_only=False)
            if progress:
                progress(0, 0, f"{model.name} downloaded successfully.")
            return self.get_status(model)
        except Exception as e:
            raise RuntimeError(f"Failed to download {model.name}: {e}") from e
        finally:
            with self._lock:
                self._active_downloads.discard(key)

    def delete(self, key: str) -> MMSDownloadStatus:
        model = get_by_key(key)
        if not model:
            raise ValueError(f"Unknown MMS model key: {key}")
        with self._lock:
            if key in self._active_downloads:
                raise RuntimeError("Cannot delete a model while it is downloading.")
        # Best-effort deletion from Hugging Face cache
        try:
            from huggingface_hub import scan_cache_dir

            cache = scan_cache_dir()
            for repo in cache.repos:
                if repo.repo_id == model.repo_id:
                    # delete all revisions for this repo
                    rev_hashes = [rev.commit_hash for rev in repo.revisions]
                    if rev_hashes:
                        strategy = cache.delete_revisions(*rev_hashes)
                        strategy.execute()
                    break
        except Exception as e:
            raise RuntimeError(f"Failed to delete cached model files: {e}") from e
        return self.get_status(model)

    def _cache_hint(self, model: MMSVoiceModel) -> Optional[str]:
        try:
            from huggingface_hub import snapshot_download

            path = snapshot_download(repo_id=model.repo_id, local_files_only=True)
            return str(path)
        except Exception:
            return None

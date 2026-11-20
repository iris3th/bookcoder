from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .models import Language, NarrationSettings


def _default_settings_path() -> Path:
    # Prefer XDG config/home; fall back to ~/.bookcoder
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "bookcoder" / "settings.json"


class SettingsStore:
    """Persist user preferences for narration and app behavior."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _default_settings_path()
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._data = {}
        except Exception:
            self._data = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            # Non-fatal: preferences persistence failure shouldn't crash the app
            pass

    def get_narration_settings(self, language: Optional[Language] = None) -> NarrationSettings:
        ns = NarrationSettings()
        # Global defaults
        g = self._data.get("narration", {}) if isinstance(self._data.get("narration"), dict) else {}
        self._apply_dict(ns, g)
        # Per-language overrides (remember voice per language)
        if language:
            per = self._data.get("narration_by_language", {})
            if isinstance(per, dict):
                lang_data = per.get(language.value, {})
                if isinstance(lang_data, dict):
                    # Merge map fields (global base + per-language overrides)
                    base_map = dict(ns.pronunciation_map or {})
                    base_cast = dict(ns.voice_cast_map or {})
                    self._apply_dict(ns, lang_data)
                    lang_map = dict(ns.pronunciation_map or {})
                    lang_cast = dict(ns.voice_cast_map or {})
                    if base_map or lang_map:
                        merged = dict(base_map)
                        merged.update(lang_map)
                        ns.pronunciation_map = merged
                    if base_cast or lang_cast:
                        merged_cast = dict(base_cast)
                        merged_cast.update(lang_cast)
                        ns.voice_cast_map = merged_cast
            ns.language = language
        return ns

    def save_narration_settings(self, settings: NarrationSettings, language: Optional[Language] = None) -> None:
        payload = self._settings_to_dict(settings)
        if not isinstance(self._data.get("narration"), dict):
            self._data["narration"] = {}
        # save general prefs
        for k in ("provider_id", "speed", "pitch", "style", "volume_gain_db", "output_format", "output_bitrate_kbps", "combine_into_single_file", "chapter_pause_ms", "paragraph_pause_ms", "sentence_pause_hint", "tone_profile"):
            if k in payload:
                self._data["narration"][k] = payload[k]
        if "pronunciation_map" in payload and isinstance(payload["pronunciation_map"], dict):
            self._data["narration"]["pronunciation_map"] = payload["pronunciation_map"]
        if "voice_cast_map" in payload and isinstance(payload["voice_cast_map"], dict):
            self._data["narration"]["voice_cast_map"] = payload["voice_cast_map"]
        # save per-language voice and related
        lang = language or settings.language
        if lang:
            if not isinstance(self._data.get("narration_by_language"), dict):
                self._data["narration_by_language"] = {}
            key = lang.value if hasattr(lang, "value") else str(lang)
            if not isinstance(self._data["narration_by_language"].get(key), dict):
                self._data["narration_by_language"][key] = {}
            for k in ("provider_id", "voice_id", "speed", "pitch", "style", "tone_profile", "dialogue_voice_id", "dialogue_voice_alt_id", "sentence_pause_hint"):
                if k in payload and payload[k] not in (None, ""):
                    self._data["narration_by_language"][key][k] = payload[k]
            if "pronunciation_map" in payload and isinstance(payload["pronunciation_map"], dict):
                self._data["narration_by_language"][key]["pronunciation_map"] = payload["pronunciation_map"]
            if "voice_cast_map" in payload and isinstance(payload["voice_cast_map"], dict):
                self._data["narration_by_language"][key]["voice_cast_map"] = payload["voice_cast_map"]
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    @staticmethod
    def _settings_to_dict(settings: NarrationSettings) -> dict[str, Any]:
        d = asdict(settings)
        lang = d.get("language")
        if hasattr(lang, "value"):
            d["language"] = lang.value
        return d

    @staticmethod
    def _apply_dict(ns: NarrationSettings, d: dict[str, Any]) -> None:
        if not isinstance(d, dict):
            return
        if "provider_id" in d and isinstance(d["provider_id"], str):
            ns.provider_id = d["provider_id"]
        if "voice_id" in d and isinstance(d["voice_id"], str):
            ns.voice_id = d["voice_id"]
        if "speed" in d:
            try:
                ns.speed = float(d["speed"])
            except Exception:
                pass
        if "pitch" in d:
            try:
                ns.pitch = float(d["pitch"])
            except Exception:
                pass
        if "style" in d and isinstance(d["style"], str):
            ns.style = d["style"]
        if "volume_gain_db" in d:
            try:
                ns.volume_gain_db = float(d["volume_gain_db"])
            except Exception:
                pass
        if "output_format" in d and isinstance(d["output_format"], str):
            fmt = d["output_format"].strip().lower()
            if fmt in ("mp3", "m4a", "aac", "mp4", "m4b", "audiobook"):
                if fmt in ("m4b", "audiobook"):
                    ns.output_format = "m4b"
                elif fmt in ("m4a", "aac", "mp4"):
                    ns.output_format = "m4a"
                else:
                    ns.output_format = "mp3"
        if "output_bitrate_kbps" in d:
            try:
                ns.output_bitrate_kbps = int(d["output_bitrate_kbps"])
            except Exception:
                pass
        if "combine_into_single_file" in d:
            ns.combine_into_single_file = bool(d["combine_into_single_file"])
        if "chapter_pause_ms" in d:
            try:
                ns.chapter_pause_ms = int(d["chapter_pause_ms"])
            except Exception:
                pass
        if "paragraph_pause_ms" in d:
            try:
                ns.paragraph_pause_ms = int(d["paragraph_pause_ms"])
            except Exception:
                pass
        if "sentence_pause_hint" in d:
            try:
                ns.sentence_pause_hint = bool(d["sentence_pause_hint"])
            except Exception:
                pass
        if "tone_profile" in d and isinstance(d["tone_profile"], str):
            tp = d["tone_profile"].strip().lower()
            if tp in ("natural", "expressive", "clear", "neutral"):
                ns.tone_profile = tp
            elif tp:
                ns.tone_profile = tp
        if "dialogue_voice_id" in d and isinstance(d["dialogue_voice_id"], str):
            ns.dialogue_voice_id = d["dialogue_voice_id"].strip()
        if "dialogue_voice_alt_id" in d and isinstance(d["dialogue_voice_alt_id"], str):
            ns.dialogue_voice_alt_id = d["dialogue_voice_alt_id"].strip()
        if "voice_cast_map" in d and isinstance(d["voice_cast_map"], dict):
            cleaned_cast: dict[str, str] = {}
            for k, v in d["voice_cast_map"].items():
                try:
                    ks = str(k).strip().lower()
                    vs = str(v).strip()
                except Exception:
                    continue
                if ks and vs:
                    cleaned_cast[ks] = vs
            ns.voice_cast_map = cleaned_cast
        if "pronunciation_map" in d and isinstance(d["pronunciation_map"], dict):
            cleaned: dict[str, str] = {}
            for k, v in d["pronunciation_map"].items():
                try:
                    ks = str(k).strip()
                    vs = str(v).strip()
                except Exception:
                    continue
                if ks and vs:
                    cleaned[ks] = vs
            ns.pronunciation_map = cleaned

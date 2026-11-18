from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..models import Language, NarrationSettings, VoiceInfo


class TTSProviderError(Exception):
    """Base exception for TTS provider failures."""


@dataclass
class SynthesisRequest:
    text: str
    voice: VoiceInfo
    settings: NarrationSettings
    output_path: Path
    chapter_title: str = ""
    # Optional callback for fine-grained progress within a chapter
    progress: Optional[Callable[[int, int, str], None]] = None  # (current_chunk, total_chunks, message)


class TTSProvider(ABC):
    """Abstract interface for text-to-speech engines.

    Implementations must be replaceable/extendable without changing the rest of the app.
    """

    id: str = "base"
    name: str = "Base TTS Provider"
    description: str = ""
    requires_api_key: bool = False
    supports_pitch: bool = False
    supports_styles: bool = False
    supports_streaming: bool = False

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Return (available, reason_if_not)."""

    @abstractmethod
    def list_voices(self, language: Optional[Language] = None) -> list[VoiceInfo]:
        """Return available voices, optionally filtered by language."""

    @abstractmethod
    def synthesize(self, request: SynthesisRequest) -> Path:
        """Synthesize text to an MP3 file at request.output_path and return the path."""

    def synthesize_preview(self, voice: VoiceInfo, text: Optional[str] = None, settings: Optional[NarrationSettings] = None) -> Path:
        """Generate a short preview audio file and return its path."""
        import os
        import tempfile

        preview_text = text or _default_preview_text(voice.language)
        fd, tmp_name = tempfile.mkstemp(suffix=".mp3", prefix="bookcoder_preview_")
        os.close(fd)
        tmp = Path(tmp_name)
        req = SynthesisRequest(
            text=preview_text,
            voice=voice,
            settings=settings or NarrationSettings(voice_id=voice.id, language=voice.language, speed=1.0, pitch=0.0),
            output_path=tmp,
            chapter_title="Preview",
        )
        self.synthesize(req)
        return tmp

    def default_voice(self, language: Language) -> Optional[VoiceInfo]:
        voices = self.list_voices(language)
        if not voices:
            return None
        # Prefer female neural-like voice as a pleasant default if metadata hints exist, else first
        for v in voices:
            if "female" in (v.gender or "").lower():
                return v
        return voices[0]


def _default_preview_text(language: Language) -> str:
    if language == Language.HUNGARIAN:
        return (
            "Üdvözlöm! Ez egy rövid hangminta a BookCoder hangoskönyv-narrátorával. "
            "A felolvasás természetes ritmusú, tiszta kiejtésű, és kellemes hallgatási élményt nyújt."
        )
    return (
        "Welcome! This is a short preview of the BookCoder audiobook narrator. "
        "The narration is natural, clear, and designed for a pleasant listening experience."
    )

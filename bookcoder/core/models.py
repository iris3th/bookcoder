from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import uuid


class Language(str, Enum):
    ENGLISH = "en"
    HUNGARIAN = "hu"

    @property
    def display_name(self) -> str:
        return {
            Language.ENGLISH: "English",
            Language.HUNGARIAN: "Hungarian",
        }[self]


class InputFormat(str, Enum):
    EPUB = "epub"
    MOBI = "mobi"
    AZW3 = "azw3"
    TXT = "txt"


@dataclass
class Chapter:
    id: str
    title: str
    text: str
    index: int
    included: bool = True
    source_hint: str = ""  # e.g. original href/heading info

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @staticmethod
    def create(title: str, text: str, index: int, source_hint: str = "") -> "Chapter":
        return Chapter(
            id=str(uuid.uuid4()),
            title=title.strip() or f"Chapter {index + 1}",
            text=text.strip(),
            index=index,
            source_hint=source_hint,
        )


@dataclass
class Book:
    source_path: Path
    format: InputFormat
    title: str = ""
    author: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    detected_language: Optional[Language] = None
    selected_language: Optional[Language] = None
    file_size: int = 0

    @property
    def filename(self) -> str:
        return self.source_path.name

    @property
    def effective_language(self) -> Optional[Language]:
        return self.selected_language or self.detected_language

    @property
    def included_chapters(self) -> list[Chapter]:
        return [c for c in self.chapters if c.included and c.text.strip()]

    @property
    def total_word_count(self) -> int:
        return sum(c.word_count for c in self.chapters)

    def reorder_chapters(self, ordered_ids: list[str]) -> None:
        by_id = {c.id: c for c in self.chapters}
        reordered = [by_id[cid] for cid in ordered_ids if cid in by_id]
        # Append any missing chapters at the end to be safe
        seen = set(ordered_ids)
        for c in self.chapters:
            if c.id not in seen:
                reordered.append(c)
        for i, c in enumerate(reordered):
            c.index = i
        self.chapters = reordered


@dataclass
class VoiceInfo:
    id: str
    name: str
    language: Language
    gender: str = ""  # "Male", "Female", or provider-specific
    locale: str = ""  # e.g. en-US, hu-HU
    style: str = ""
    description: str = ""
    preview_text: str = ""
    provider: str = ""


@dataclass
class NarrationSettings:
    provider_id: str = ""
    voice_id: str = ""
    language: Optional[Language] = None
    speed: float = 1.0  # 1.0 = normal; provider may map to percentage
    pitch: float = 0.0  # semitones or provider-specific units
    style: str = "Natural Audiobook Narration"
    volume_gain_db: float = 0.0
    output_format: str = "mp3"  # "mp3" or "m4a" (AAC), iPhone-compatible
    output_bitrate_kbps: int = 128
    combine_into_single_file: bool = False
    chapter_pause_ms: int = 1200
    paragraph_pause_ms: int = 450
    sentence_pause_hint: bool = True
    tone_profile: str = "natural"  # natural | expressive | clear | neutral
    dialogue_voice_id: str = ""  # optional hook: use a different voice for dialogue segments (same provider)


@dataclass
class OutputResult:
    chapter_files: list[Path] = field(default_factory=list)
    combined_file: Optional[Path] = None
    output_dir: Optional[Path] = None


@dataclass
class ProgressUpdate:
    stage: str
    message: str
    current: int = 0
    total: int = 0
    chapter_title: str = ""
    fraction: float = 0.0

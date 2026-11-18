from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Language


@dataclass(frozen=True)
class MMSVoiceModel:
    key: str  # e.g. mms-eng, mms-hun
    repo_id: str
    name: str
    language: Language
    gender: str
    locale: str
    description: str
    size_hint_mb: int = 150

    @property
    def voice_id(self) -> str:
        return f"mms:{self.language.value}"

    @property
    def provider_id(self) -> str:
        return "mms-tts"


MMS_MODELS: list[MMSVoiceModel] = [
    MMSVoiceModel(
        key="mms-eng",
        repo_id="facebook/mms-tts-eng",
        name="MMS English (eng)",
        language=Language.ENGLISH,
        gender="Neutral",
        locale="en-US",
        description="Meta MMS-TTS English VITS voice. Offline after model download/cache.",
        size_hint_mb=160,
    ),
    MMSVoiceModel(
        key="mms-hun",
        repo_id="facebook/mms-tts-hun",
        name="MMS Hungarian (hun)",
        language=Language.HUNGARIAN,
        gender="Neutral",
        locale="hu-HU",
        description="Meta MMS-TTS Hungarian VITS voice. Offline after model download/cache.",
        size_hint_mb=160,
    ),
]

_BY_KEY = {m.key: m for m in MMS_MODELS}


def get_catalog(language: Optional[Language] = None) -> list[MMSVoiceModel]:
    if language is None:
        return list(MMS_MODELS)
    return [m for m in MMS_MODELS if m.language == language]


def get_by_key(key: str) -> Optional[MMSVoiceModel]:
    return _BY_KEY.get(key)

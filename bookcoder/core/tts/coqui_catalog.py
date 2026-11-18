from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Language


@dataclass(frozen=True)
class CoquiVoiceModel:
    key: str
    model_name: str
    name: str
    language: Language
    gender: str
    locale: str
    description: str
    size_hint_mb: int = 1800

    @property
    def voice_id(self) -> str:
        code = "hu" if self.language == Language.HUNGARIAN else "en"
        return f"coqui-xtts:{code}"

    @property
    def provider_id(self) -> str:
        return "coqui-xtts"


COQUI_MODELS: list[CoquiVoiceModel] = [
    CoquiVoiceModel(
        key="coqui-xtts-v2-en",
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        name="Coqui XTTS v2 (English)",
        language=Language.ENGLISH,
        gender="Neutral",
        locale="en-US",
        description="Coqui XTTS v2 multilingual model for English (shared model download). Heavy; may be slow on CPU.",
        size_hint_mb=1800,
    ),
    CoquiVoiceModel(
        key="coqui-xtts-v2-hu",
        model_name="tts_models/multilingual/multi-dataset/xtts_v2",
        name="Coqui XTTS v2 (Hungarian)",
        language=Language.HUNGARIAN,
        gender="Neutral",
        locale="hu-HU",
        description="Coqui XTTS v2 multilingual model for Hungarian (shared model download). Heavy; may be slow on CPU.",
        size_hint_mb=1800,
    ),
]

_BY_KEY = {m.key: m for m in COQUI_MODELS}


def get_catalog(language: Optional[Language] = None) -> list[CoquiVoiceModel]:
    if language is None:
        return list(COQUI_MODELS)
    return [m for m in COQUI_MODELS if m.language == language]


def get_by_key(key: str) -> Optional[CoquiVoiceModel]:
    return _BY_KEY.get(key)

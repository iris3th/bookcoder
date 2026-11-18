from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Language


HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


@dataclass(frozen=True)
class PiperVoiceModel:
    key: str  # e.g. en_US-lessac-medium
    name: str
    language: Language
    gender: str  # "Female" / "Male"
    locale: str  # e.g. en-US
    quality: str  # low/medium/high
    description: str
    lang_family: str  # e.g. en, hu
    region: str  # e.g. en_US, hu_HU
    voice_name: str  # e.g. lessac, anna
    size_hint_mb: int = 63
    recommended: bool = True

    @property
    def model_filename(self) -> str:
        return f"{self.region}-{self.voice_name}-{self.quality}.onnx"

    @property
    def config_filename(self) -> str:
        return f"{self.region}-{self.voice_name}-{self.quality}.onnx.json"

    @property
    def hf_path_prefix(self) -> str:
        return f"{self.lang_family}/{self.region}/{self.voice_name}/{self.quality}"

    @property
    def model_url(self) -> str:
        return f"{HF_BASE}/{self.hf_path_prefix}/{self.model_filename}?download=true"

    @property
    def config_url(self) -> str:
        return f"{HF_BASE}/{self.hf_path_prefix}/{self.config_filename}?download=true"

    @property
    def voice_id(self) -> str:
        # Namespaced ID used throughout the app
        return f"piper:{self.key}"


RECOMMENDED_VOICES: list[PiperVoiceModel] = [
    # English - US
    PiperVoiceModel(
        key="en_US-lessac-medium",
        name="Lessac (US, Female)",
        language=Language.ENGLISH,
        gender="Female",
        locale="en-US",
        quality="medium",
        description="Clear, natural US English female voice. Excellent default for audiobooks.",
        lang_family="en",
        region="en_US",
        voice_name="lessac",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="en_US-amy-medium",
        name="Amy (US, Female)",
        language=Language.ENGLISH,
        gender="Female",
        locale="en-US",
        quality="medium",
        description="Warm and pleasant US English female voice.",
        lang_family="en",
        region="en_US",
        voice_name="amy",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="en_US-ryan-medium",
        name="Ryan (US, Male)",
        language=Language.ENGLISH,
        gender="Male",
        locale="en-US",
        quality="medium",
        description="Natural US English male voice with clear articulation.",
        lang_family="en",
        region="en_US",
        voice_name="ryan",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="en_US-joe-medium",
        name="Joe (US, Male)",
        language=Language.ENGLISH,
        gender="Male",
        locale="en-US",
        quality="medium",
        description="Clear US English male voice suitable for narration.",
        lang_family="en",
        region="en_US",
        voice_name="joe",
        size_hint_mb=63,
    ),
    # English - GB
    PiperVoiceModel(
        key="en_GB-cori-medium",
        name="Cori (UK, Female)",
        language=Language.ENGLISH,
        gender="Female",
        locale="en-GB",
        quality="medium",
        description="Natural British English female voice.",
        lang_family="en",
        region="en_GB",
        voice_name="cori",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="en_GB-northern_english_male-medium",
        name="Northern English (UK, Male)",
        language=Language.ENGLISH,
        gender="Male",
        locale="en-GB",
        quality="medium",
        description="British English male voice with clear delivery.",
        lang_family="en",
        region="en_GB",
        voice_name="northern_english_male",
        size_hint_mb=63,
    ),
    # Hungarian
    PiperVoiceModel(
        key="hu_HU-anna-medium",
        name="Anna (HU, Női)",
        language=Language.HUNGARIAN,
        gender="Female",
        locale="hu-HU",
        quality="medium",
        description="Természetes magyar női hang, tiszta kiejtéssel hangoskönyvekhez.",
        lang_family="hu",
        region="hu_HU",
        voice_name="anna",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="hu_HU-berta-medium",
        name="Berta (HU, Női)",
        language=Language.HUNGARIAN,
        gender="Female",
        locale="hu-HU",
        quality="medium",
        description="Kellemes magyar női hang, jó választás hosszabb felolvasáshoz.",
        lang_family="hu",
        region="hu_HU",
        voice_name="berta",
        size_hint_mb=63,
    ),
    PiperVoiceModel(
        key="hu_HU-imre-medium",
        name="Imre (HU, Férfi)",
        language=Language.HUNGARIAN,
        gender="Male",
        locale="hu-HU",
        quality="medium",
        description="Természetes magyar férfi hang, tiszta és érthető narrációhoz.",
        lang_family="hu",
        region="hu_HU",
        voice_name="imre",
        size_hint_mb=63,
    ),
]


_BY_KEY = {v.key: v for v in RECOMMENDED_VOICES}
_BY_VOICE_ID = {v.voice_id: v for v in RECOMMENDED_VOICES}


def get_catalog(language: Optional[Language] = None) -> list[PiperVoiceModel]:
    if language is None:
        return list(RECOMMENDED_VOICES)
    return [v for v in RECOMMENDED_VOICES if v.language == language]


def get_by_key(key: str) -> Optional[PiperVoiceModel]:
    return _BY_KEY.get(key)


def get_by_voice_id(voice_id: str) -> Optional[PiperVoiceModel]:
    if voice_id in _BY_VOICE_ID:
        return _BY_VOICE_ID[voice_id]
    # allow passing raw key
    return _BY_KEY.get(voice_id.replace("piper:", "", 1))


def voice_key_from_id(voice_id: str) -> str:
    if voice_id.startswith("piper:"):
        return voice_id.split(":", 1)[1]
    return voice_id

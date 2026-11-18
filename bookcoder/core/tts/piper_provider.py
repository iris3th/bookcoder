from __future__ import annotations

import re
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

from ..models import Language, NarrationSettings, VoiceInfo
from .base import SynthesisRequest, TTSProvider, TTSProviderError
from .piper_catalog import PiperVoiceModel, get_by_voice_id, get_catalog
from .piper_manager import PiperModelManager


def _speed_to_length_scale(speed: float) -> float:
    try:
        s = float(speed)
    except Exception:
        s = 1.0
    if s <= 0:
        s = 1.0
    # length_scale: >1 slower, <1 faster
    ls = 1.0 / s
    # clamp to reasonable bounds for natural speech
    return max(0.5, min(2.0, ls))


def _chunk_text_for_piper(text: str, max_chars: int = 1200) -> list[str]:
    """Chunk text for Piper synthesis. Piper works best with sentence/paragraph-sized inputs."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            if buf.strip():
                chunks.append(buf.strip())
                buf = ""
            sentences = re.split(r"(?<=[\.!\?\…])\s+", para)
            cur = ""
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if len(sent) > max_chars:
                    if cur.strip():
                        chunks.append(cur.strip())
                        cur = ""
                    for i in range(0, len(sent), max_chars):
                        part = sent[i : i + max_chars].strip()
                        if part:
                            chunks.append(part)
                    continue
                candidate = (cur + " " + sent).strip() if cur else sent
                if len(candidate) <= max_chars:
                    cur = candidate
                else:
                    if cur.strip():
                        chunks.append(cur.strip())
                    cur = sent
            if cur.strip():
                chunks.append(cur.strip())
            continue
        candidate = (buf + "\n\n" + para).strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = para
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c.strip()]


class PiperTTSProvider(TTSProvider):
    id = "piper"
    name = "Piper (Offline)"
    description = (
        "High-quality offline neural TTS using Piper models. "
        "Runs locally after voice models are downloaded (no internet required for synthesis)."
    )
    requires_api_key = False
    supports_pitch = False
    supports_styles = False

    def __init__(self, manager: Optional[PiperModelManager] = None) -> None:
        self.manager = manager or PiperModelManager()
        self._voice_cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def is_available(self) -> tuple[bool, str]:
        try:
            import piper  # noqa: F401
            from piper import PiperVoice  # noqa: F401
        except Exception as e:
            return False, f"Piper runtime is not installed ({e}). Install 'piper-tts' to enable offline narration."
        return True, "Piper runtime is installed. Download voice models to use offline narration."

    def list_voices(self, language: Optional[Language] = None) -> list[VoiceInfo]:
        # Return only downloaded voices as usable voices
        voices: list[VoiceInfo] = []
        for model in get_catalog(language):
            if self.manager.is_downloaded(model):
                voices.append(self._to_voice_info(model))
        return voices

    def list_downloadable_models(self, language: Optional[Language] = None):
        return self.manager.list_statuses(language)

    def _to_voice_info(self, model: PiperVoiceModel) -> VoiceInfo:
        return VoiceInfo(
            id=model.voice_id,
            name=f"{model.name} (Offline)",
            language=model.language,
            gender=model.gender,
            locale=model.locale,
            style=f"Piper {model.quality}",
            description=model.description,
            provider=self.id,
        )

    def _get_loaded_voice(self, voice_id: str):
        ok, reason = self.is_available()
        if not ok:
            raise TTSProviderError(reason)
        model_path, config_path, model = self.manager.resolve_paths(voice_id)
        key = model.key
        with self._lock:
            cached = self._voice_cache.get(key)
        if cached is not None:
            return cached, model
        try:
            from piper import PiperVoice

            voice = PiperVoice.load(str(model_path), str(config_path))
        except Exception as e:
            raise TTSProviderError(f"Failed to load Piper voice '{model.name}': {e}") from e
        with self._lock:
            self._voice_cache[key] = voice
        return voice, model

    def synthesize(self, request: SynthesisRequest) -> Path:
        ok, reason = self.is_available()
        if not ok:
            raise TTSProviderError(reason)

        text = (request.text or "").strip()
        if not text:
            raise TTSProviderError("Cannot synthesize empty text.")

        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice_obj, model = self._get_loaded_voice(request.voice.id)

        try:
            from piper import SynthesisConfig
        except Exception as e:
            raise TTSProviderError(f"Piper synthesis components unavailable: {e}") from e

        syn_config = SynthesisConfig(
            length_scale=_speed_to_length_scale(getattr(request.settings, "speed", 1.0) or 1.0),
            volume=1.0,
        )

        chunks = _chunk_text_for_piper(text, max_chars=1200)
        if not chunks:
            raise TTSProviderError("No narratable text found after processing.")

        try:
            if len(chunks) == 1:
                if request.progress:
                    request.progress(0, 1, "Synthesizing audio (offline)...")
                wav_path = output_path.with_suffix(".tmp.wav")
                self._synthesize_to_wav(voice_obj, chunks[0], wav_path, syn_config)
                self._wav_to_mp3(wav_path, output_path)
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass
                if request.progress:
                    request.progress(1, 1, "Synthesized audio")
            else:
                with tempfile.TemporaryDirectory(prefix="bookcoder_piper_") as td:
                    tdir = Path(td)
                    wav_parts: list[Path] = []
                    total = len(chunks)
                    for i, chunk in enumerate(chunks):
                        if request.progress:
                            request.progress(i, total, f"Synthesizing segment {i + 1}/{total} (offline)...")
                        wp = tdir / f"part_{i:05d}.wav"
                        self._synthesize_to_wav(voice_obj, chunk, wp, syn_config)
                        wav_parts.append(wp)
                    if request.progress:
                        request.progress(total, total, "Combining audio segments...")
                    self._concat_wavs_to_mp3(wav_parts, output_path)
        except TTSProviderError:
            raise
        except Exception as e:
            raise TTSProviderError(f"Offline speech synthesis failed: {e}") from e

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSProviderError("Offline speech synthesis produced no audio output.")
        return output_path

    def _synthesize_to_wav(self, voice_obj, text: str, wav_path: Path, syn_config) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), "wb") as wav_file:
            voice_obj.synthesize_wav(text, wav_file, syn_config=syn_config)

    def _wav_to_mp3(self, wav_path: Path, mp3_path: Path) -> None:
        # Prefer pydub/ffmpeg for proper MP3 encoding
        try:
            from pydub import AudioSegment  # type: ignore

            seg = AudioSegment.from_wav(str(wav_path))
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
            seg.export(str(mp3_path), format="mp3", bitrate="128k")
            return
        except Exception:
            pass
        # Try ffmpeg directly
        try:
            import shutil
            import subprocess

            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                cmd = [
                    ffmpeg, "-y", "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
                    return
        except Exception:
            pass
        raise TTSProviderError(
            "Could not convert synthesized audio to MP3. Please install ffmpeg or ensure pydub is available."
        )

    def _concat_wavs_to_mp3(self, wav_parts: list[Path], mp3_path: Path) -> None:
        wav_parts = [p for p in wav_parts if p.exists() and p.stat().st_size > 0]
        if not wav_parts:
            raise TTSProviderError("No audio segments to combine.")
        # Try pydub for clean concatenation with small gaps
        try:
            from pydub import AudioSegment  # type: ignore

            combined = AudioSegment.empty()
            gap = AudioSegment.silent(duration=120)
            for i, wp in enumerate(wav_parts):
                seg = AudioSegment.from_wav(str(wp))
                combined += seg
                if i < len(wav_parts) - 1:
                    combined += gap
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
            combined.export(str(mp3_path), format="mp3", bitrate="128k")
            return
        except Exception:
            pass
        # Try ffmpeg concat on wavs -> mp3
        try:
            import shutil
            import subprocess

            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg and len(wav_parts) == 1:
                self._wav_to_mp3(wav_parts[0], mp3_path)
                return
            if ffmpeg:
                with tempfile.TemporaryDirectory(prefix="bookcoder_piper_concat_") as td:
                    list_file = Path(td) / "list.txt"
                    lines = []
                    for p in wav_parts:
                        lines.append("file '" + str(p.resolve()).replace("'", "'\\''") + "'")
                    list_file.write_text("\n".join(lines), encoding="utf-8")
                    cmd = [
                        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                        "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
                        return
        except Exception:
            pass
        raise TTSProviderError(
            "Could not combine/encode offline audio segments to MP3. Please install ffmpeg or ensure pydub is working."
        )

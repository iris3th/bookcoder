from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path
from typing import Optional

from ..models import Language, NarrationSettings, VoiceInfo
from .base import SynthesisRequest, TTSProvider, TTSProviderError
from .coqui_manager import CoquiModelManager
from .coqui_catalog import get_catalog


# Coqui XTTS v2: multilingual neural TTS model (heavy, may download model data on first use).
_XTTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

_LANG_CODE = {
    Language.ENGLISH: "en",
    Language.HUNGARIAN: "hu",
}


def _chunk_text(text: str, max_chars: int = 700) -> list[str]:
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


class CoquiXTTSProvider(TTSProvider):
    id = "coqui-xtts"
    name = "Coqui XTTS v2 (Offline, Heavy)"
    description = (
        "Multilingual neural TTS using Coqui XTTS v2 (supports English and Hungarian). "
        "High quality but heavy; requires torch/TTS and may download model data on first use."
    )
    requires_api_key = False
    supports_pitch = False
    supports_styles = False

    def __init__(self, manager: Optional[CoquiModelManager] = None) -> None:
        self.manager = manager or CoquiModelManager()
        self._lock = threading.Lock()
        self._tts = None
        self._load_error: Optional[str] = None

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            from TTS.api import TTS  # noqa: F401
        except Exception as e:
            return False, f"Coqui TTS dependencies are not installed ({e}). Install TTS and torch to enable this engine."
        if self._load_error:
            return False, self._load_error
        return True, "Coqui XTTS runtime is installed. Download/load the XTTS v2 model to use offline narration."

    def list_voices(self, language: Optional[Language] = None) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        for model in get_catalog(language):
            try:
                downloaded = self.manager.is_downloaded(model)
            except Exception:
                downloaded = False
            if downloaded:
                voices.append(
                    VoiceInfo(
                        id=model.voice_id,
                        name=model.name,
                        language=model.language,
                        gender=model.gender,
                        locale=model.locale,
                        style="XTTS v2 (cached)",
                        description=model.description,
                        provider=self.id,
                    )
                )
        return voices

    def list_downloadable_models(self, language: Optional[Language] = None):
        return self.manager.list_statuses(language)

    def _ensure_tts(self):
        with self._lock:
            if self._tts is not None:
                return self._tts
            if self._load_error:
                raise TTSProviderError(self._load_error)
        try:
            import torch
            from TTS.api import TTS

            # Try GPU if available, else CPU
            use_gpu = False
            try:
                use_gpu = bool(torch.cuda.is_available())
            except Exception:
                use_gpu = False
            tts = TTS(model_name=_XTTS_MODEL_NAME, progress_bar=False, gpu=use_gpu)
        except Exception as e:
            msg = f"Failed to initialize Coqui XTTS v2: {e}"
            with self._lock:
                self._load_error = msg
            raise TTSProviderError(msg) from e
        with self._lock:
            self._tts = tts
            self._load_error = None
        return tts

    def synthesize(self, request: SynthesisRequest) -> Path:
        ok, reason = self.is_available()
        if not ok:
            raise TTSProviderError(reason)

        text = (request.text or "").strip()
        if not text:
            raise TTSProviderError("Cannot synthesize empty text.")

        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lang = (request.voice.language if request.voice else None) or (request.settings.language if request.settings else None)
        if lang not in _LANG_CODE:
            vid = (request.voice.id or "") if request.voice else ""
            if ":hu" in vid:
                lang = Language.HUNGARIAN
            elif ":en" in vid:
                lang = Language.ENGLISH
        if lang not in _LANG_CODE:
            raise TTSProviderError("Coqui XTTS v2 voice/language is not supported.")

        lang_code = _LANG_CODE[lang]
        chunks = _chunk_text(text, max_chars=700)
        if not chunks:
            raise TTSProviderError("No narratable text found after processing.")

        # Ensure shared XTTS model marked/downloaded (best-effort auto-download on first synthesis)
        try:
            models = get_catalog(lang)
            if models and not self.manager.is_downloaded(models[0]):
                if request.progress:
                    request.progress(0, 1, "Downloading/loading Coqui XTTS v2 model...")
                self.manager.download(models[0].key)
        except Exception:
            pass

        tts = self._ensure_tts()
        speaker = self._pick_speaker(tts)

        try:
            if len(chunks) == 1:
                if request.progress:
                    request.progress(0, 1, "Synthesizing audio (Coqui XTTS v2)...")
                wav_path = output_path.with_suffix(".tmp.wav")
                self._synthesize_one(tts, chunks[0], lang_code, speaker, wav_path)
                self._wav_to_mp3(wav_path, output_path)
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass
                if request.progress:
                    request.progress(1, 1, "Synthesized audio (Coqui XTTS v2)")
            else:
                with tempfile.TemporaryDirectory(prefix="bookcoder_xtts_") as td:
                    tdir = Path(td)
                    wav_parts: list[Path] = []
                    total = len(chunks)
                    for i, chunk in enumerate(chunks):
                        if request.progress:
                            request.progress(i, total, f"Synthesizing segment {i + 1}/{total} (Coqui XTTS v2)...")
                        wp = tdir / f"part_{i:05d}.wav"
                        self._synthesize_one(tts, chunk, lang_code, speaker, wp)
                        wav_parts.append(wp)
                    if request.progress:
                        request.progress(total, total, "Combining audio segments (Coqui XTTS v2)...")
                    self._concat_wavs_to_mp3(wav_parts, output_path)
        except TTSProviderError:
            raise
        except Exception as e:
            raise TTSProviderError(f"Coqui XTTS synthesis failed: {e}") from e

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSProviderError("Coqui XTTS produced no audio output.")
        return output_path

    def _pick_speaker(self, tts) -> Optional[str]:
        # Best-effort: XTTS v2 behavior varies across TTS package versions.
        # Prefer an available built-in speaker if exposed; otherwise None and let API decide.
        try:
            speakers = getattr(tts, "speakers", None)
            if isinstance(speakers, list) and speakers:
                # choose first deterministic speaker
                return str(speakers[0])
            if isinstance(speakers, dict) and speakers:
                # sometimes mapping name->info
                return str(next(iter(speakers.keys())))
        except Exception:
            pass
        # Some versions expose synthesizer.tts_model.speaker_manager
        try:
            synth = getattr(tts, "synthesizer", None)
            model = getattr(synth, "tts_model", None) if synth is not None else None
            sm = getattr(model, "speaker_manager", None) if model is not None else None
            if sm is not None:
                names = getattr(sm, "speaker_names", None) or getattr(sm, "speakers", None)
                if isinstance(names, list) and names:
                    return str(names[0])
                if isinstance(names, dict) and names:
                    return str(next(iter(names.keys())))
        except Exception:
            pass
        return None

    def _synthesize_one(self, tts, text: str, language: str, speaker: Optional[str], wav_path: Path) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        errors = []
        # Try common XTTS v2 call signatures across coqui-tts/TTS versions.
        attempts = []
        if speaker:
            attempts.append({"text": text, "file_path": str(wav_path), "language": language, "speaker": speaker})
        attempts.append({"text": text, "file_path": str(wav_path), "language": language})
        if speaker:
            attempts.append({"text": text, "file_path": str(wav_path), "language": language, "speaker": speaker, "split_sentences": False})
        attempts.append({"text": text, "file_path": str(wav_path), "language": language, "split_sentences": False})
        for kwargs in attempts:
            try:
                tts.tts_to_file(**kwargs)
                if wav_path.exists() and wav_path.stat().st_size > 0:
                    return
            except TypeError as e:
                errors.append(str(e))
                continue
            except Exception as e:
                errors.append(str(e))
                # try next signature for compatibility, but keep first meaningful error context
                continue
        # Some setups require speaker_wav (voice cloning) for XTTS v2; provide clear guidance.
        detail = "; ".join(errors[-2:]) if errors else "unknown error"
        raise TTSProviderError(
            "Coqui XTTS synthesis failed with this TTS runtime/configuration. "
            "This engine may require a compatible coqui-tts/TTS version and, for XTTS v2 in some setups, a reference speaker WAV. "
            f"Details: {detail}"
        )

    def _wav_to_mp3(self, wav_path: Path, mp3_path: Path) -> None:
        try:
            from pydub import AudioSegment  # type: ignore

            seg = AudioSegment.from_wav(str(wav_path))
            mp3_path.parent.mkdir(parents=True, exist_ok=True)
            seg.export(str(mp3_path), format="mp3", bitrate="128k")
            return
        except Exception:
            pass
        try:
            import shutil
            import subprocess

            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                cmd = [ffmpeg, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
                    return
        except Exception:
            pass
        raise TTSProviderError("Could not convert Coqui XTTS audio to MP3. Please install ffmpeg or ensure pydub is available.")

    def _concat_wavs_to_mp3(self, wav_parts: list[Path], mp3_path: Path) -> None:
        wav_parts = [p for p in wav_parts if p.exists() and p.stat().st_size > 0]
        if not wav_parts:
            raise TTSProviderError("No audio segments to combine.")
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
        # ffmpeg fallback
        try:
            import shutil
            import subprocess

            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg and len(wav_parts) == 1:
                self._wav_to_mp3(wav_parts[0], mp3_path)
                return
            if ffmpeg:
                with tempfile.TemporaryDirectory(prefix="bookcoder_xtts_concat_") as td:
                    list_file = Path(td) / "list.txt"
                    lines = []
                    for p in wav_parts:
                        lines.append("file '" + str(p.resolve()).replace("'", "'\\''") + "'")
                    list_file.write_text("\n".join(lines), encoding="utf-8")
                    # concat wavs and encode to mp3
                    cmd = [
                        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                        "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path),
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0:
                        return
        except Exception:
            pass
        raise TTSProviderError("Could not combine/encode Coqui XTTS audio segments to MP3. Please install ffmpeg or ensure pydub is working.")

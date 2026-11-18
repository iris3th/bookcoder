from __future__ import annotations

import re
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

from ..models import Language, NarrationSettings, VoiceInfo
from .base import SynthesisRequest, TTSProvider, TTSProviderError
from .mms_manager import MMSModelManager
from .mms_catalog import get_catalog


# Hugging Face MMS-TTS model ids (VITS). Models are downloaded/cached by transformers on first use.
_MMS_MODELS: dict[Language, dict[str, str]] = {
    Language.ENGLISH: {
        "id": "facebook/mms-tts-eng",
        "name": "MMS English (eng)",
        "description": "Meta MMS-TTS English VITS voice (offline after model download).",
        "locale": "en-US",
        "gender": "Neutral",
    },
    Language.HUNGARIAN: {
        "id": "facebook/mms-tts-hun",
        "name": "MMS Hungarian (hun)",
        "description": "Meta MMS-TTS Hungarian VITS voice (offline after model download).",
        "locale": "hu-HU",
        "gender": "Neutral",
    },
}


def _chunk_text(text: str, max_chars: int = 450) -> list[str]:
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


class MMSTTSProvider(TTSProvider):
    id = "mms-tts"
    name = "Meta MMS-TTS (Offline, Heavy)"
    description = (
        "Offline neural TTS using Meta MMS VITS models via Transformers/PyTorch. "
        "Supports English and Hungarian; models are downloaded and cached on first use."
    )
    requires_api_key = False
    supports_pitch = False
    supports_styles = False

    def __init__(self, manager: Optional[MMSModelManager] = None) -> None:
        self.manager = manager or MMSModelManager()
        self._lock = threading.Lock()
        self._loaded: dict[str, tuple[object, object, int, str]] = {}  # model_id -> (tokenizer, model, sample_rate, device)

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            from transformers import AutoTokenizer, VitsModel  # noqa: F401
        except Exception as e:
            return False, f"MMS-TTS dependencies are not installed ({e}). Install transformers and torch to enable this engine."
        return True, "MMS-TTS runtime is installed. Download/cache models to use offline narration."

    def list_voices(self, language: Optional[Language] = None) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        for model in get_catalog(language):
            try:
                downloaded = self.manager.is_downloaded(model)
            except Exception:
                downloaded = False
            if downloaded:
                voices.append(self._to_voice_info(model, language))
        # Fallback: if manager checks unavailable but runtime is present and cache detection fails,
        # don't expose unready voices by default.
        return voices

    def list_downloadable_models(self, language: Optional[Language] = None):
        return self.manager.list_statuses(language)

    def _to_voice_info(self, model, language: Language) -> VoiceInfo:
        return VoiceInfo(
            id=model.voice_id,
            name=model.name,
            language=model.language,
            gender=model.gender,
            locale=model.locale,
            style="VITS (cached)",
            description=model.description,
            provider=self.id,
        )

    def _load(self, lang: Language):
        info = _MMS_MODELS.get(lang)
        if not info:
            raise TTSProviderError(f"MMS-TTS does not support language: {lang}")
        model_id = info["id"]
        with self._lock:
            cached = self._loaded.get(model_id)
        if cached is not None:
            return cached

        try:
            import torch
            from transformers import AutoTokenizer, VitsModel
        except Exception as e:
            raise TTSProviderError(f"MMS-TTS dependencies unavailable: {e}") from e

        try:
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = VitsModel.from_pretrained(model_id)
            model.eval()
            # Use GPU when available (CUDA/ROCm-enabled PyTorch builds expose cuda)
            device = "cpu"
            try:
                import torch as _torch
                if _torch.cuda.is_available():
                    device = "cuda"
                    model.to(device)
            except Exception:
                device = "cpu"
            try:
                sr = int(getattr(getattr(model, "config", None), "sampling_rate", 16000) or 16000)
            except Exception:
                sr = 16000
        except Exception as e:
            raise TTSProviderError(f"Failed to load MMS-TTS model '{model_id}': {e}") from e

        with self._lock:
            self._loaded[model_id] = (tokenizer, model, sr, device)
        return tokenizer, model, sr, device

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
        if lang not in _MMS_MODELS:
            # try infer from voice id
            vid = (request.voice.id or "") if request.voice else ""
            if vid.endswith(":hu") or vid.endswith("-hun"):
                lang = Language.HUNGARIAN
            elif vid.endswith(":en") or vid.endswith("-eng"):
                lang = Language.ENGLISH
        if lang not in _MMS_MODELS:
            raise TTSProviderError("MMS-TTS voice/language is not supported.")

        # Ensure model is cached/downloaded (download manager may have been used; if not, load will fetch)
        try:
            for m in get_catalog(lang):
                if not self.manager.is_downloaded(m):
                    # allow auto-download on first synthesis, but inform via progress
                    if request.progress:
                        request.progress(0, 1, f"Downloading/caching {m.name} (MMS-TTS)...")
                    self.manager.download(m.key)
                break
        except Exception:
            # fallback to transformers' own caching during load
            pass

        loaded = self._load(lang)
        if isinstance(loaded, tuple) and len(loaded) == 4:
            tokenizer, model, sr, device = loaded
        else:
            tokenizer, model, sr = loaded  # type: ignore[misc]
            device = "cpu"
        chunks = _chunk_text(text, max_chars=450)
        if not chunks:
            raise TTSProviderError("No narratable text found after processing.")

        try:
            import numpy as np
            import torch
        except Exception as e:
            raise TTSProviderError(f"MMS-TTS runtime dependencies unavailable: {e}") from e

        waveforms = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            if request.progress:
                request.progress(i, total, f"Synthesizing segment {i + 1}/{total} (MMS-TTS)...")
            try:
                inputs = tokenizer(chunk, return_tensors="pt")
                try:
                    if device and device != "cpu":
                        inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
                except Exception:
                    pass
                with torch.no_grad():
                    out = model(**inputs)
                    waveform = out.waveform
                # waveform: (1, samples) or (samples,)
                if hasattr(waveform, "detach"):
                    wav_np = waveform.detach().cpu().squeeze().numpy()
                else:
                    wav_np = np.asarray(waveform).squeeze()
                if wav_np.size == 0:
                    continue
                # apply simple speed adjustment by resampling if needed (best-effort)
                speed = 1.0
                try:
                    speed = float(getattr(request.settings, "speed", 1.0) or 1.0)
                except Exception:
                    speed = 1.0
                if abs(speed - 1.0) > 0.01:
                    wav_np = _resample_linear(wav_np, speed)
                waveforms.append(wav_np.astype(np.float32, copy=False))
                # small pause between chunks
                if i < total - 1:
                    pause_samples = int(sr * 0.12)
                    if pause_samples > 0:
                        waveforms.append(np.zeros(pause_samples, dtype=np.float32))
            except Exception as e:
                raise TTSProviderError(f"MMS-TTS synthesis failed on segment {i + 1}: {e}") from e

        if not waveforms:
            raise TTSProviderError("MMS-TTS produced no audio output.")

        audio = np.concatenate(waveforms)
        # normalize/clamp to [-1, 1]
        try:
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        except Exception:
            peak = 0.0
        if peak > 1.0:
            audio = audio / peak

        with tempfile.TemporaryDirectory(prefix="bookcoder_mms_") as td:
            wav_path = Path(td) / "out.wav"
            _write_wav_float32(wav_path, audio, sr)
            self._wav_to_mp3(wav_path, output_path)

        if request.progress:
            request.progress(total, total, "Synthesized audio (MMS-TTS)")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSProviderError("MMS-TTS produced no audio output file.")
        return output_path

    def _wav_to_mp3(self, wav_path: Path, mp3_path: Path) -> None:
        # Prefer pydub/ffmpeg
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
        raise TTSProviderError("Could not convert MMS-TTS audio to MP3. Please install ffmpeg or ensure pydub is available.")


def _write_wav_float32(path: Path, audio_f32, sr: int) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    # convert float32 [-1,1] to int16 PCM
    a = np.asarray(audio_f32, dtype=np.float32)
    a = np.clip(a, -1.0, 1.0)
    pcm = (a * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def _resample_linear(audio_f32, speed: float):
    """Simple linear resampling for speed adjustment (best-effort). speed>1 faster/shorter."""
    import numpy as np

    try:
        s = float(speed)
    except Exception:
        s = 1.0
    if s <= 0:
        s = 1.0
    # clamp to reasonable range
    s = max(0.5, min(2.0, s))
    if abs(s - 1.0) < 0.01:
        return audio_f32
    x = np.asarray(audio_f32, dtype=np.float32)
    n = x.shape[0]
    if n <= 1:
        return x
    new_n = max(1, int(round(n / s)))
    xp = np.linspace(0.0, 1.0, num=n, endpoint=False)
    fp = x
    xnew = np.linspace(0.0, 1.0, num=new_n, endpoint=False)
    return np.interp(xnew, xp, fp).astype(np.float32)

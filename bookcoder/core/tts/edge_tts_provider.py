from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from .base import SynthesisRequest, TTSProvider, TTSProviderError
from ..models import Language, NarrationSettings, VoiceInfo


# Curated high-quality neural voices (fallback/static list) so the app works even if
# dynamic voice listing is unavailable offline at runtime. IDs are edge-tts short names.
_CURATED_VOICES: list[VoiceInfo] = [
    # English
    VoiceInfo(id="en-US-AriaNeural", name="Aria (US)", language=Language.ENGLISH, gender="Female", locale="en-US", style="Natural, expressive", description="Warm and clear US English narrator voice.", preview_text="", provider="edge"),
    VoiceInfo(id="en-US-GuyNeural", name="Guy (US)", language=Language.ENGLISH, gender="Male", locale="en-US", style="Natural, clear", description="Confident US English narrator voice.", preview_text="", provider="edge"),
    VoiceInfo(id="en-US-JennyNeural", name="Jenny (US)", language=Language.ENGLISH, gender="Female", locale="en-US", style="Conversational, friendly", description="Friendly US English voice suitable for audiobooks.", preview_text="", provider="edge"),
    VoiceInfo(id="en-US-DavisNeural", name="Davis (US)", language=Language.ENGLISH, gender="Male", locale="en-US", style="Calm, narrative", description="Calm and steady US English narrator.", preview_text="", provider="edge"),
    VoiceInfo(id="en-GB-SoniaNeural", name="Sonia (UK)", language=Language.ENGLISH, gender="Female", locale="en-GB", style="Natural, clear", description="Clear British English narrator voice.", preview_text="", provider="edge"),
    VoiceInfo(id="en-GB-RyanNeural", name="Ryan (UK)", language=Language.ENGLISH, gender="Male", locale="en-GB", style="Natural, narrative", description="British English narrator voice.", preview_text="", provider="edge"),
    VoiceInfo(id="en-AU-NatashaNeural", name="Natasha (AU)", language=Language.ENGLISH, gender="Female", locale="en-AU", style="Natural", description="Australian English narrator voice.", preview_text="", provider="edge"),
    VoiceInfo(id="en-IE-EmilyNeural", name="Emily (IE)", language=Language.ENGLISH, gender="Female", locale="en-IE", style="Natural", description="Irish English narrator voice.", preview_text="", provider="edge"),
    # Hungarian
    VoiceInfo(id="hu-HU-NoemiNeural", name="Noémi (HU)", language=Language.HUNGARIAN, gender="Female", locale="hu-HU", style="Natural, clear", description="Természetes hangzású magyar női narrátor.", preview_text="", provider="edge"),
    VoiceInfo(id="hu-HU-TamasNeural", name="Tamás (HU)", language=Language.HUNGARIAN, gender="Male", locale="hu-HU", style="Natural, clear", description="Természetes hangzású magyar férfi narrátor.", preview_text="", provider="edge"),
]


class EdgeTTSProvider(TTSProvider):
    id = "edge-tts"
    name = "Microsoft Edge Neural TTS"
    description = (
        "High-quality neural voices via Microsoft Edge TTS. Supports natural prosody for "
        "English and Hungarian. Requires internet connection; no API key needed."
    )
    requires_api_key = False
    supports_pitch = True
    supports_styles = False  # edge-tts has limited style controls; we expose rate/pitch

    def __init__(self) -> None:
        self._voice_cache: Optional[list[VoiceInfo]] = None

    def is_available(self) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except Exception as e:
            return False, f"edge-tts package is not installed ({e}). Install it to enable neural narration."
        return True, ""

    def list_voices(self, language: Optional[Language] = None) -> list[VoiceInfo]:
        voices = self._get_all_voices()
        if language is None:
            return list(voices)
        return [v for v in voices if v.language == language]

    def _get_all_voices(self) -> list[VoiceInfo]:
        if self._voice_cache is not None:
            return self._voice_cache
        # Try dynamic fetch; fall back to curated list
        try:
            raw = _run_async(_fetch_edge_voices())
            voices = _convert_edge_voices(raw)
            if voices:
                # Ensure we include curated Hungarian/English voices if missing
                by_id = {v.id: v for v in voices}
                for cv in _CURATED_VOICES:
                    by_id.setdefault(cv.id, cv)
                self._voice_cache = sorted(by_id.values(), key=lambda v: (v.language.value, v.locale, v.name))
                return self._voice_cache
        except Exception:
            pass
        self._voice_cache = list(_CURATED_VOICES)
        return self._voice_cache

    def synthesize(self, request: SynthesisRequest) -> Path:
        ok, reason = self.is_available()
        if not ok:
            raise TTSProviderError(reason)

        text = (request.text or "").strip()
        if not text:
            raise TTSProviderError("Cannot synthesize empty text.")

        output_path = Path(request.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rate = _format_rate(request.settings.speed)
        pitch = _format_pitch(request.settings.pitch)
        volume = _format_volume(request.settings.volume_gain_db)

        # Chunk long text for reliability and better pacing control
        chunks = chunk_text_for_tts(text, max_chars=2200)
        if not chunks:
            raise TTSProviderError("No narratable text found after processing.")

        try:
            if len(chunks) == 1:
                _run_async(
                    _synthesize_one(
                        chunks[0], request.voice.id, str(output_path), rate=rate, pitch=pitch, volume=volume
                    )
                )
                if request.progress:
                    request.progress(1, 1, "Synthesized audio")
            else:
                # Synthesize chunks to temp files then concatenate with ffmpeg/pydub if available, else binary concat (mp3 frames)
                with tempfile.TemporaryDirectory(prefix="bookcoder_tts_") as td:
                    temp_dir = Path(td)
                    part_files: list[Path] = []
                    total = len(chunks)
                    for i, chunk in enumerate(chunks):
                        if request.progress:
                            request.progress(i, total, f"Synthesizing segment {i + 1}/{total}...")
                        part_path = temp_dir / f"part_{i:05d}.mp3"
                        _run_async(
                            _synthesize_one(
                                chunk, request.voice.id, str(part_path), rate=rate, pitch=pitch, volume=volume
                            )
                        )
                        part_files.append(part_path)
                    if request.progress:
                        request.progress(total, total, "Combining audio segments...")
                    concat_mp3_files(part_files, output_path)
        except TTSProviderError:
            raise
        except Exception as e:
            raise TTSProviderError(f"Speech synthesis failed: {e}") from e

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise TTSProviderError("Speech synthesis produced no audio output.")
        return output_path


async def _fetch_edge_voices() -> list[dict[str, Any]]:
    import edge_tts

    return await edge_tts.list_voices()


async def _synthesize_one(text: str, voice_id: str, out_path: str, rate: str, pitch: str, volume: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice_id, rate=rate, pitch=pitch, volume=volume)
    await communicate.save(out_path)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread - common case
        return asyncio.run(coro)
    else:
        # Already in an event loop (unlikely in our worker threads) - run in new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(asyncio.run, coro)
            return fut.result()


def _convert_edge_voices(raw: list[dict[str, Any]]) -> list[VoiceInfo]:
    voices: list[VoiceInfo] = []
    for v in raw or []:
        locale = str(v.get("Locale", ""))
        short_name = str(v.get("ShortName", ""))
        if not short_name:
            continue
        lang = _locale_to_language(locale)
        if lang is None:
            continue
        gender = str(v.get("Gender", "")).title()
        friendly = str(v.get("FriendlyName", short_name))
        # Simplify display name
        name = friendly
        # Try to extract a nice short name
        # FriendlyName often like "Microsoft Aria Online (Natural) - English (United States)"
        m = re.search(r"Microsoft\s+(.+?)\s+Online", friendly)
        if m:
            name = m.group(1).strip()
        # Add locale hint
        if locale and locale not in name:
            country = locale.split("-")[-1]
            if country and country not in name:
                name = f"{name} ({country})"
        styles = ""
        style_list = v.get("StyleList") or []
        if isinstance(style_list, list) and style_list:
            styles = ", ".join(style_list[:3])
        voices.append(
            VoiceInfo(
                id=short_name,
                name=name,
                language=lang,
                gender=gender,
                locale=locale,
                style=styles or "Neural",
                description=f"{gender} {locale} neural voice".strip(),
                provider="edge",
            )
        )
    return voices


def _locale_to_language(locale: str) -> Optional[Language]:
    loc = (locale or "").lower()
    if loc.startswith("hu"):
        return Language.HUNGARIAN
    if loc.startswith("en"):
        return Language.ENGLISH
    return None


def _format_rate(speed: float) -> str:
    # speed 1.0 = +0%, 1.2 = +20%, 0.8 = -20%
    try:
        pct = int(round((float(speed) - 1.0) * 100))
    except Exception:
        pct = 0
    pct = max(-50, min(100, pct))
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def _format_pitch(pitch: float) -> str:
    # our pitch is semitone-like units; edge accepts Hz offsets like +5Hz/-5Hz (approx) or +0Hz
    # Map roughly: 1.0 unit -> 5Hz (simple heuristic)
    try:
        hz = int(round(float(pitch) * 5))
    except Exception:
        hz = 0
    hz = max(-50, min(50, hz))
    sign = "+" if hz >= 0 else ""
    return f"{sign}{hz}Hz"


def _format_volume(gain_db: float) -> str:
    # map dB-ish setting to percent offset; 0 -> +0%
    try:
        pct = int(round(float(gain_db) * 8))
    except Exception:
        pct = 0
    pct = max(-50, min(50, pct))
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


def chunk_text_for_tts(text: str, max_chars: int = 2200) -> list[str]:
    """Split text into chunks suitable for TTS, preferring paragraph/sentence boundaries."""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""

    def flush_buf():
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            flush_buf()
            # split long paragraph by sentences
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
                    # hard split
                    for i in range(0, len(sent), max_chars):
                        part = sent[i : i + max_chars].strip()
                        if part:
                            chunks.append(part)
                    continue
                if cur and len(cur) + 1 + len(sent) > max_chars:
                    chunks.append(cur.strip())
                    cur = sent
                else:
                    cur = (cur + " " + sent).strip() if cur else sent
            if cur.strip():
                chunks.append(cur.strip())
            continue

        candidate = (buf + "\n\n" + para).strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            flush_buf()
            buf = para
    flush_buf()

    # ensure no empty
    return [c for c in chunks if c.strip()]


def concat_mp3_files(parts: list[Path], output_path: Path) -> None:
    parts = [p for p in parts if p.exists() and p.stat().st_size > 0]
    if not parts:
        raise TTSProviderError("No audio segments to combine.")
    if len(parts) == 1:
        data = parts[0].read_bytes()
        output_path.write_bytes(data)
        return

    # Try pydub+ffmpeg for clean concatenation
    try:
        from pydub import AudioSegment  # type: ignore

        combined = AudioSegment.empty()
        for p in parts:
            seg = AudioSegment.from_file(str(p), format="mp3")
            # add tiny gap to avoid clicks
            combined += seg + AudioSegment.silent(duration=120)
        combined.export(str(output_path), format="mp3", bitrate="128k")
        return
    except Exception:
        pass

    # Try ffmpeg concat demuxer
    try:
        import shutil
        import subprocess

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            with tempfile.TemporaryDirectory(prefix="bookcoder_concat_") as td:
                list_file = Path(td) / "list.txt"
                # ffmpeg concat demuxer requires safe paths
                lines = []
                for p in parts:
                    lines.append("file '" + str(p.resolve()).replace("'", "'\\''") + "'")
                list_file.write_text("\n".join(lines), encoding="utf-8")
                cmd = [
                    ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output_path)
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return
    except Exception:
        pass

    # Last resort: naive binary concatenation of MP3 frames (often works for same-encoding streams)
    with output_path.open("wb") as out:
        for p in parts:
            out.write(p.read_bytes())

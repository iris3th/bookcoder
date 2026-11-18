from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from .audio import (
    combine_audio_files,
    extension_for_format,
    format_label,
    normalize_audio,
    normalize_output_format,
)
from .ebook_parser import parse_book
from .language_detection import detect_language_for_book
from .models import Book, NarrationSettings, OutputResult, ProgressUpdate
from .segmentation import SpeechSegment, plan_chapter_segments
from .text_normalization import normalize_for_tts
from .tts.base import SynthesisRequest, TTSProvider, TTSProviderError


class CancelledError(Exception):
    pass


class PipelineError(Exception):
    pass


ProgressCallback = Callable[[ProgressUpdate], None]


@dataclass
class GenerationConfig:
    output_dir: Path
    settings: NarrationSettings
    provider: TTSProvider
    voice_id: str
    combine: bool = False
    bitrate_kbps: int = 128
    chapter_pause_ms: int = 1200
    output_format: str = "mp3"


class AudiobookPipeline:
    def __init__(self) -> None:
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    def _check_cancel(self) -> None:
        if self._cancel_event.is_set():
            raise CancelledError("Operation cancelled by user.")

    def load_book(self, path: Path, progress: Optional[ProgressCallback] = None) -> Book:
        self._check_cancel()

        def p(msg: str):
            if progress:
                progress(ProgressUpdate(stage="parse", message=msg))

        book = parse_book(Path(path), progress=p)
        self._check_cancel()

        if progress:
            progress(ProgressUpdate(stage="detect", message="Detecting language from book content..."))

        lang, conf = detect_language_for_book([c.text for c in book.chapters])
        book.detected_language = lang
        if book.selected_language is None:
            book.selected_language = lang

        if progress:
            progress(
                ProgressUpdate(
                    stage="ready",
                    message=f"Detected language: {lang.display_name} ({int(conf * 100)}% confidence).",
                )
            )
        return book

    def generate(self, book: Book, config: GenerationConfig, progress: Optional[ProgressCallback] = None) -> OutputResult:
        chapters = book.included_chapters
        if not chapters:
            raise PipelineError("No chapters selected for narration. Please include at least one chapter.")

        provider = config.provider
        ok, reason = provider.is_available()
        if not ok:
            raise PipelineError(f"TTS provider '{provider.name}' is not available: {reason}")

        voice = None
        for v in provider.list_voices(book.effective_language):
            if v.id == config.voice_id:
                voice = v
                break
        if voice is None:
            # try any language match
            for v in provider.list_voices(None):
                if v.id == config.voice_id:
                    voice = v
                    break
        if voice is None:
            raise PipelineError("Selected voice is not available. Please choose a different voice.")

        out_dir = Path(config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        result = OutputResult(output_dir=out_dir)
        total = len(chapters)

        output_format = normalize_output_format(getattr(config, "output_format", None) or getattr(config.settings, "output_format", "mp3"))
        ext = extension_for_format(output_format)

        settings = config.settings
        # Apply "Natural Audiobook Narration" preference: favor pleasant, expressive pacing
        effective_settings = NarrationSettings(
            provider_id=getattr(settings, "provider_id", "") or provider.id,
            voice_id=voice.id,
            language=book.effective_language,
            speed=settings.speed,
            pitch=settings.pitch,
            style=settings.style or "Natural Audiobook Narration",
            volume_gain_db=settings.volume_gain_db,
            output_format=output_format,
            output_bitrate_kbps=config.bitrate_kbps,
            combine_into_single_file=config.combine,
            chapter_pause_ms=config.chapter_pause_ms,
            paragraph_pause_ms=settings.paragraph_pause_ms,
        )
        if (effective_settings.style or "").lower().startswith("natural"):
            # gently bias extreme speeds toward natural range if user left default-ish; but respect explicit choices
            if effective_settings.speed > 1.3:
                effective_settings.speed = 1.3
            if effective_settings.speed < 0.75:
                effective_settings.speed = 0.75

        # Generate per-chapter MP3 files
        for idx, chapter in enumerate(chapters, start=1):
            self._check_cancel()
            if progress:
                progress(
                    ProgressUpdate(
                        stage="synthesize",
                        message=f"Generating narration for '{chapter.title}' ({idx}/{total})...",
                        current=idx - 1,
                        total=total,
                        chapter_title=chapter.title,
                        fraction=(idx - 1) / max(total, 1),
                    )
                )

            safe_book = _safe_filename(book.title or book.source_path.stem)
            safe_ch = _safe_filename(chapter.title or f"Chapter {idx}")
            chap_filename = f"{idx:02d} - {safe_ch}{ext}"
            # keep filenames reasonably short
            if len(chap_filename) > 140:
                chap_filename = f"{idx:02d} - {safe_ch[:100].rstrip()}{ext}"
            # TTS providers currently output MP3; keep raw as MP3 and transcode to requested format.
            raw_path = out_dir / f".tmp_{idx:02d}_{chapter.id[:8]}.mp3"
            final_path = out_dir / chap_filename

            # Build narration text with a short title intro for clarity in audio.
            narration_text = chapter.text
            if chapter.title and chapter.title.strip():
                # Prepend title if not already at start of text
                head = chapter.text.lstrip()[: len(chapter.title) + 20].lower()
                if chapter.title.strip().lower() not in head:
                    narration_text = f"{chapter.title.strip()}.\n\n{chapter.text}"

            # Step 1: synthesis-time text normalization/pronunciation preparation.
            # Keep safe/fallback-friendly behavior inside normalize_for_tts.
            pronunciation_map = getattr(effective_settings, "pronunciation_map", None) or getattr(settings, "pronunciation_map", None)
            narration_text = normalize_for_tts(
                narration_text,
                language=book.effective_language,
                pronunciation_map=pronunciation_map if isinstance(pronunciation_map, dict) else None,
            )

            # Step 2/3: structure-aware segmentation and provider-aware tone/pause planning.
            try:
                segments = plan_chapter_segments(
                    narration_text,
                    chapter_title=chapter.title,
                    settings=effective_settings,
                    tone_profile=getattr(effective_settings, "tone_profile", "natural"),
                    provider_supports_pitch=bool(getattr(provider, "supports_pitch", False)),
                )
            except Exception:
                segments = [SpeechSegment(text=narration_text, pause_after_ms=0, speed_multiplier=1.0, pitch_delta=0.0, kind="text")]
            if not segments:
                segments = [SpeechSegment(text=narration_text, pause_after_ms=0, speed_multiplier=1.0, pitch_delta=0.0, kind="text")]

            dialogue_voice = voice
            dialogue_voice_id = (getattr(effective_settings, "dialogue_voice_id", "") or "").strip()
            if dialogue_voice_id and dialogue_voice_id != voice.id:
                try:
                    for dv in provider.list_voices(None):
                        if dv.id == dialogue_voice_id:
                            dialogue_voice = dv
                            break
                except Exception:
                    dialogue_voice = voice

            try:
                self._synthesize_chapter_segments(
                    provider=provider,
                    voice=voice,
                    chapter=chapter,
                    segments=segments,
                    effective_settings=effective_settings,
                    raw_path=raw_path,
                    chapter_index=idx,
                    chapter_total=total,
                    progress=progress,
                    dialogue_voice=dialogue_voice,
                )
            except TTSProviderError as e:
                self._cleanup_temp(out_dir)
                raise PipelineError(f"Failed to synthesize chapter '{chapter.title}': {e}") from e
            except Exception as e:
                self._cleanup_temp(out_dir)
                raise PipelineError(f"Unexpected error while generating '{chapter.title}': {e}") from e

            self._check_cancel()

            # Normalize/encode to requested quality and format
            try:
                normalize_audio(raw_path, final_path, bitrate_kbps=config.bitrate_kbps, output_format=output_format)
            except Exception:
                # fallback: move/copy raw (may be mp3 even if m4a requested, but better than nothing)
                if raw_path.exists():
                    try:
                        if raw_path.suffix.lower() == final_path.suffix.lower():
                            raw_path.replace(final_path)
                        else:
                            # copy raw bytes to final path as last resort
                            final_path.write_bytes(raw_path.read_bytes())
                            raw_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            finally:
                try:
                    if raw_path.exists():
                        raw_path.unlink()
                except Exception:
                    pass

            if not final_path.exists() or final_path.stat().st_size == 0:
                self._cleanup_temp(out_dir)
                raise PipelineError(f"Generated audio for chapter '{chapter.title}' is missing or empty.")

            result.chapter_files.append(final_path)

            if progress:
                progress(
                    ProgressUpdate(
                        stage="synthesize",
                        message=f"Completed '{chapter.title}' ({idx}/{total}).",
                        current=idx,
                        total=total,
                        chapter_title=chapter.title,
                        fraction=idx / max(total, 1),
                    )
                )

        # Combine into single audiobook if requested
        if config.combine and result.chapter_files:
            self._check_cancel()
            if progress:
                progress(
                    ProgressUpdate(
                        stage="combine",
                        message=f"Combining chapters into a single audiobook ({format_label(output_format)})...",
                        current=total,
                        total=total,
                        fraction=0.99,
                    )
                )
            safe_book = _safe_filename(book.title or book.source_path.stem) or "audiobook"
            combined_name = f"{safe_book} - Complete Audiobook{ext}"
            if len(combined_name) > 160:
                combined_name = f"{safe_book[:120].rstrip()} - Complete Audiobook{ext}"
            combined_path = out_dir / combined_name

            def combine_progress(cur: int, tot: int):
                if progress:
                    progress(
                        ProgressUpdate(
                            stage="combine",
                            message=f"Combining chapters ({cur}/{tot})...",
                            current=cur,
                            total=tot,
                            fraction=0.95 + 0.05 * (cur / max(tot, 1)),
                        )
                    )

            try:
                combine_audio_files(
                    result.chapter_files,
                    combined_path,
                    pause_ms=config.chapter_pause_ms,
                    bitrate_kbps=config.bitrate_kbps,
                    output_format=output_format,
                    progress=combine_progress,
                )
                result.combined_file = combined_path
            except Exception as e:
                # Non-fatal? chapter files are still valuable, but report error
                raise PipelineError(f"Chapter files were generated, but combining failed: {e}") from e

        self._cleanup_temp(out_dir)

        if progress:
            msg = "Audiobook generation complete."
            if result.combined_file:
                msg += f" Combined file: {result.combined_file.name}"
            progress(
                ProgressUpdate(
                    stage="done",
                    message=msg,
                    current=total,
                    total=total,
                    fraction=1.0,
                )
            )

        return result

    def _synthesize_chapter_segments(
        self,
        provider: TTSProvider,
        voice,
        chapter,
        segments: list[SpeechSegment],
        effective_settings: NarrationSettings,
        raw_path: Path,
        chapter_index: int,
        chapter_total: int,
        progress: Optional[ProgressCallback] = None,
        dialogue_voice=None,
    ) -> None:
        """Synthesize planned segments and stitch them into a single chapter MP3 (raw)."""
        if dialogue_voice is None:
            dialogue_voice = voice
        # Collect spoken segments and initial pause
        initial_pause_ms = 0
        spoken: list[tuple[int, SpeechSegment]] = []  # (segment_order_index, seg)
        for seg in segments:
            if getattr(seg, "kind", "") == "initial_pause" or not (seg.text or "").strip():
                initial_pause_ms = max(initial_pause_ms, int(getattr(seg, "pause_after_ms", 0) or 0))
                continue
            spoken.append((len(spoken), seg))

        if not spoken and initial_pause_ms <= 0:
            raise PipelineError(f"No narratable segments found for chapter '{chapter.title}'.")

        with tempfile.TemporaryDirectory(prefix=f"bookcoder_ch_{chapter_index:02d}_") as td:
            tdir = Path(td)
            part_entries: list[tuple[Path, int]] = []  # (audio_path, pause_after_ms)
            total_spoken = len(spoken)

            # Synthesize spoken segments
            for si, seg in spoken:
                self._check_cancel()
                if progress:
                    base = (chapter_index - 1) / max(chapter_total, 1)
                    span = 1 / max(chapter_total, 1)
                    frac = base + span * (si / max(total_spoken, 1))
                    kind = getattr(seg, "kind", "text")
                    label = "title" if kind == "title" else ("dialogue" if kind == "dialogue" else "segment")
                    progress(
                        ProgressUpdate(
                            stage="synthesize",
                            message=f"{chapter.title}: synthesizing {label} {si + 1}/{total_spoken}...",
                            current=chapter_index - 1,
                            total=chapter_total,
                            chapter_title=chapter.title,
                            fraction=min(frac, 0.999),
                        )
                    )

                seg_settings = _segment_settings(
                    effective_settings,
                    getattr(seg, "speed_multiplier", 1.0),
                    getattr(seg, "pitch_delta", 0.0),
                )
                seg_voice = dialogue_voice if getattr(seg, "kind", "") == "dialogue" and dialogue_voice is not None else voice
                seg_path = tdir / f"seg_{si:04d}.mp3"

                # Provider-internal chunk progress mapped into this segment's slice
                def _seg_progress(cur: int, tot: int, msg: str):
                    if not progress:
                        return
                    base = (chapter_index - 1) / max(chapter_total, 1)
                    span = 1 / max(chapter_total, 1)
                    seg_base = base + span * (si / max(total_spoken, 1))
                    seg_span = span / max(total_spoken, 1)
                    inner = (cur / max(tot, 1)) if tot else 0
                    frac = seg_base + seg_span * inner
                    progress(
                        ProgressUpdate(
                            stage="synthesize",
                            message=f"{chapter.title}: {msg}" if msg else f"{chapter.title}: synthesizing segment {si + 1}/{total_spoken}...",
                            current=chapter_index - 1,
                            total=chapter_total,
                            chapter_title=chapter.title,
                            fraction=min(frac, 0.999),
                        )
                    )

                req = SynthesisRequest(
                    text=seg.text,
                    voice=seg_voice,
                    settings=seg_settings,
                    output_path=seg_path,
                    chapter_title=chapter.title,
                    progress=_seg_progress,
                )
                provider.synthesize(req)

                if not seg_path.exists() or seg_path.stat().st_size == 0:
                    raise PipelineError(f"Synthesized segment {si + 1} for chapter '{chapter.title}' is missing or empty.")

                part_entries.append((seg_path, max(0, int(getattr(seg, "pause_after_ms", 0) or 0))))

            self._check_cancel()
            if progress:
                base = (chapter_index - 1) / max(chapter_total, 1)
                span = 1 / max(chapter_total, 1)
                progress(
                    ProgressUpdate(
                        stage="synthesize",
                        message=f"{chapter.title}: assembling audio segments...",
                        current=chapter_index - 1,
                        total=chapter_total,
                        chapter_title=chapter.title,
                        fraction=min(base + span * 0.97, 0.999),
                    )
                )

            # Stitch segments (and initial pause) into raw chapter MP3
            self._stitch_segment_audio(
                part_entries=part_entries,
                output_path=raw_path,
                initial_pause_ms=initial_pause_ms,
            )

        if not raw_path.exists() or raw_path.stat().st_size == 0:
            raise PipelineError(f"Generated audio for chapter '{chapter.title}' is missing or empty.")

    def _stitch_segment_audio(
        self,
        part_entries: list[tuple[Path, int]],
        output_path: Path,
        initial_pause_ms: int = 0,
    ) -> None:
        """Combine synthesized segment MP3 files with per-segment pauses into one MP3."""
        entries = [(Path(p), max(0, int(ms or 0))) for p, ms in (part_entries or []) if Path(p).exists() and Path(p).stat().st_size > 0]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not entries:
            # No spoken audio; if only initial pause requested, generate silence.
            if initial_pause_ms > 0:
                if self._write_silence_mp3(output_path, initial_pause_ms):
                    return
            raise PipelineError("No audio segments available to assemble.")

        # Fast path: single segment, no pauses
        if len(entries) == 1 and initial_pause_ms <= 0 and entries[0][1] <= 0:
            shutil.copy2(entries[0][0], output_path)
            return

        # Try pydub for precise variable pauses
        try:
            from pydub import AudioSegment  # type: ignore

            combined = AudioSegment.empty()
            if initial_pause_ms > 0:
                combined += AudioSegment.silent(duration=initial_pause_ms)
            for i, (p, pause_ms) in enumerate(entries):
                seg_audio = AudioSegment.from_file(str(p), format="mp3")
                combined += seg_audio
                if pause_ms > 0 and i < len(entries) - 1:
                    combined += AudioSegment.silent(duration=pause_ms)
            combined.export(str(output_path), format="mp3", bitrate="128k")
            if output_path.exists() and output_path.stat().st_size > 0:
                return
        except Exception:
            pass

        # FFmpeg fallback: build sequence with generated silence segments where needed
        try:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                with tempfile.TemporaryDirectory(prefix="bookcoder_stitch_") as td:
                    tdir = Path(td)
                    seq: list[Path] = []
                    if initial_pause_ms > 0:
                        sp = tdir / "silence_initial.mp3"
                        if self._write_silence_mp3(sp, initial_pause_ms):
                            seq.append(sp)
                    for i, (p, pause_ms) in enumerate(entries):
                        seq.append(p)
                        if pause_ms > 0 and i < len(entries) - 1:
                            sp = tdir / f"silence_{i:04d}.mp3"
                            if self._write_silence_mp3(sp, pause_ms):
                                seq.append(sp)

                    if len(seq) == 1:
                        shutil.copy2(seq[0], output_path)
                        return

                    list_file = tdir / "concat.txt"
                    lines = ["file '" + str(x.resolve()).replace("'", "'\\''") + "'" for x in seq if Path(x).exists()]
                    if not lines:
                        raise PipelineError("No audio segments available to concatenate.")
                    list_file.write_text("\n".join(lines), encoding="utf-8")

                    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_path)]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                        return

                    cmd2 = [
                        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                        "-codec:a", "libmp3lame", "-b:a", "128k", str(output_path),
                    ]
                    res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                        return
        except Exception:
            pass

        # Last resort: naive concatenation (pauses may be lost)
        try:
            with output_path.open("wb") as out:
                for p, _pause in entries:
                    out.write(Path(p).read_bytes())
            if output_path.exists() and output_path.stat().st_size > 0:
                return
        except Exception:
            pass

        raise PipelineError("Failed to assemble chapter audio segments.")

    def _write_silence_mp3(self, output_path: Path, duration_ms: int) -> bool:
        duration_ms = max(0, int(duration_ms or 0))
        if duration_ms <= 0:
            return False
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Try pydub
        try:
            from pydub import AudioSegment  # type: ignore

            AudioSegment.silent(duration=duration_ms).export(str(output_path), format="mp3", bitrate="128k")
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            pass
        # Try ffmpeg
        try:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                secs = duration_ms / 1000.0
                cmd = [
                    ffmpeg, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", f"{secs:.3f}",
                    "-codec:a", "libmp3lame", "-b:a", "128k",
                    str(output_path),
                ]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True
        except Exception:
            pass
        return False

    def _cleanup_temp(self, out_dir: Path) -> None:
        try:
            for p in Path(out_dir).glob(".tmp_*"):
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception:
            pass


def _segment_settings(base: NarrationSettings, speed_multiplier: float = 1.0, pitch_delta: float = 0.0) -> NarrationSettings:
    """Return per-segment settings with subtle, provider-safe speed/pitch hints applied."""
    try:
        mult = float(speed_multiplier or 1.0)
    except Exception:
        mult = 1.0
    # Keep hints subtle and within safe bounds
    if mult < 0.90:
        mult = 0.90
    if mult > 1.10:
        mult = 1.10
    try:
        base_speed = float(getattr(base, "speed", 1.0) or 1.0)
    except Exception:
        base_speed = 1.0
    seg_speed = base_speed * mult
    if seg_speed < 0.5:
        seg_speed = 0.5
    if seg_speed > 2.0:
        seg_speed = 2.0

    try:
        base_pitch = float(getattr(base, "pitch", 0.0) or 0.0)
    except Exception:
        base_pitch = 0.0
    try:
        pdelta = float(pitch_delta or 0.0)
    except Exception:
        pdelta = 0.0
    # Subtle pitch deltas only (provider-aware planning should already gate by capability)
    if pdelta < -2.0:
        pdelta = -2.0
    if pdelta > 2.0:
        pdelta = 2.0
    seg_pitch = base_pitch + pdelta
    if seg_pitch < -10.0:
        seg_pitch = -10.0
    if seg_pitch > 10.0:
        seg_pitch = 10.0

    try:
        return replace(base, speed=seg_speed, pitch=seg_pitch)
    except Exception:
        return base


def _safe_filename(name: str, max_len: int = 120) -> str:
    name = (name or "").strip()
    # remove characters invalid on Windows/macOS/Linux common filesystems
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    if not name:
        name = "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional


class AudioProcessingError(Exception):
    pass


def ensure_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def normalize_output_format(fmt: Optional[str]) -> str:
    f = (fmt or "mp3").strip().lower()
    if f in ("m4b", "audiobook"):
        return "m4b"
    if f in ("m4a", "aac", "mp4", "ipod"):
        return "m4a"
    return "mp3"


def extension_for_format(fmt: Optional[str]) -> str:
    nf = normalize_output_format(fmt)
    if nf == "m4b":
        return ".m4b"
    if nf == "m4a":
        return ".m4a"
    return ".mp3"


def format_label(fmt: Optional[str]) -> str:
    nf = normalize_output_format(fmt)
    if nf == "m4b":
        return "M4B (Audiobook, AAC)"
    if nf == "m4a":
        return "AAC (M4A)"
    return "MP3"


def _clamp_bitrate(bitrate_kbps: int) -> int:
    try:
        b = int(bitrate_kbps or 128)
    except Exception:
        b = 128
    return max(64, min(b, 320))


def _ffmpeg_encode_args(output_path: Path, bitrate_kbps: int, sample_rate: int) -> list[str]:
    fmt = normalize_output_format(output_path.suffix.lstrip("."))
    b = _clamp_bitrate(bitrate_kbps)
    if fmt in ("m4a", "m4b"):
        # AAC in M4A/M4B container for broad iPhone/Apple Books compatibility
        return [
            "-vn",
            "-c:a", "aac",
            "-b:a", f"{b}k",
            "-ar", str(int(sample_rate) if sample_rate else 44100),
            "-ac", "2",
            "-movflags", "+faststart",
            str(output_path),
        ]
    return [
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", f"{b}k",
        "-ar", str(int(sample_rate) if sample_rate else 44100),
        "-ac", "2",
        str(output_path),
    ]


def _pydub_export(seg, output_path: Path, bitrate_kbps: int, sample_rate: int) -> bool:
    fmt = normalize_output_format(output_path.suffix.lstrip("."))
    b = _clamp_bitrate(bitrate_kbps)
    try:
        if fmt in ("m4a", "m4b"):
            # Prefer 'ipod' for .m4a/.m4b AAC output via ffmpeg
            try:
                seg.export(
                    str(output_path),
                    format="ipod",
                    bitrate=f"{b}k",
                    codec="aac",
                    parameters=["-ar", str(sample_rate), "-ac", "2", "-movflags", "+faststart"],
                )
                return output_path.exists() and output_path.stat().st_size > 0
            except Exception:
                seg.export(
                    str(output_path),
                    format="mp4",
                    bitrate=f"{b}k",
                    codec="aac",
                    parameters=["-ar", str(sample_rate), "-ac", "2", "-movflags", "+faststart"],
                )
                return output_path.exists() and output_path.stat().st_size > 0
        seg.export(
            str(output_path),
            format="mp3",
            bitrate=f"{b}k",
            parameters=["-ar", str(sample_rate)],
        )
        return output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        return False


def normalize_audio(
    input_path: Path,
    output_path: Path,
    bitrate_kbps: int = 128,
    sample_rate: int = 44100,
    output_format: Optional[str] = None,
) -> Path:
    """Re-encode/normalize audio to consistent audiobook settings.

    Output format is inferred from output_path suffix, or output_format if provided.
    Supports MP3 and AAC/M4A (iPhone-compatible).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # If caller passed output_format, ensure suffix matches
    if output_format:
        desired_ext = extension_for_format(output_format)
        if output_path.suffix.lower() != desired_ext:
            output_path = output_path.with_suffix(desired_ext)

    bitrate_kbps = _clamp_bitrate(bitrate_kbps)
    fmt = normalize_output_format(output_path.suffix.lstrip("."))

    # Try pydub
    try:
        from pydub import AudioSegment  # type: ignore

        seg = AudioSegment.from_file(str(input_path))
        if _pydub_export(seg, output_path, bitrate_kbps, sample_rate):
            return output_path
    except Exception:
        pass

    ffmpeg = ensure_ffmpeg()
    if ffmpeg:
        cmd = [ffmpeg, "-y", "-i", str(input_path)] + _ffmpeg_encode_args(output_path, bitrate_kbps, sample_rate)
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return output_path
        except Exception:
            pass

        # Extra fallback for AAC containers (M4A/M4B): try simpler args
        if fmt in ("m4a", "m4b"):
            cmd2 = [
                ffmpeg, "-y", "-i", str(input_path),
                "-vn", "-c:a", "aac", "-b:a", f"{bitrate_kbps}k",
                "-ar", str(sample_rate), "-ac", "2",
                str(output_path),
            ]
            try:
                res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return output_path
            except Exception:
                pass

    # Fallback: copy as-is (may mismatch container/codec expectations, but better than losing output)
    if input_path.resolve() != output_path.resolve():
        try:
            shutil.copy2(input_path, output_path)
        except Exception:
            pass
    return output_path


def normalize_mp3(
    input_path: Path,
    output_path: Path,
    bitrate_kbps: int = 128,
    sample_rate: int = 44100,
) -> Path:
    # Backward-compatible wrapper (MP3)
    return normalize_audio(input_path, output_path, bitrate_kbps=bitrate_kbps, sample_rate=sample_rate, output_format="mp3")


def add_trailing_silence(
    input_path: Path,
    output_path: Path,
    silence_ms: int,
    bitrate_kbps: int = 128,
    output_format: Optional[str] = None,
) -> Path:
    """Append silence to the end of an audio file (useful for chapter gaps in combined output)."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    silence_ms = max(0, int(silence_ms))
    bitrate_kbps = _clamp_bitrate(bitrate_kbps)

    if output_format:
        desired_ext = extension_for_format(output_format)
        if output_path.suffix.lower() != desired_ext:
            output_path = output_path.with_suffix(desired_ext)
    fmt = normalize_output_format(output_path.suffix.lstrip("."))

    if silence_ms == 0:
        # Normalize/copy into requested format
        return normalize_audio(input_path, output_path, bitrate_kbps=bitrate_kbps, output_format=fmt)

    # pydub
    try:
        from pydub import AudioSegment  # type: ignore

        seg = AudioSegment.from_file(str(input_path))
        seg = seg + AudioSegment.silent(duration=silence_ms)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if _pydub_export(seg, output_path, bitrate_kbps, 44100):
            return output_path
    except Exception:
        pass

    ffmpeg = ensure_ffmpeg()
    if ffmpeg:
        secs = silence_ms / 1000.0
        base_cmd = [
            ffmpeg, "-y", "-i", str(input_path),
            "-af", f"apad=pad_dur={secs:.3f}",
        ] + _ffmpeg_encode_args(output_path, bitrate_kbps, 44100)
        try:
            res = subprocess.run(base_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return output_path
        except Exception:
            pass

    # Fallback: normalize without added silence
    return normalize_audio(input_path, output_path, bitrate_kbps=bitrate_kbps, output_format=fmt)


def _ffmetadata_escape(value: str) -> str:
    # FFMETADATA1 escaping: = ; # \ and newlines
    s = "" if value is None else str(value)
    s = s.replace("\\", "\\\\")
    s = s.replace("=", "\\=")
    s = s.replace(";", "\\;")
    s = s.replace("#", "\\#")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\\n")
    return s


def _audio_duration_ms(path: Path) -> int:
    p = Path(path)
    # Try pydub
    try:
        from pydub import AudioSegment  # type: ignore

        seg = AudioSegment.from_file(str(p))
        return max(0, int(len(seg)))
    except Exception:
        pass
    # Try ffprobe
    try:
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p),
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                out = (res.stdout or "").strip()
                if out:
                    return max(0, int(float(out) * 1000.0))
    except Exception:
        pass
    return 0


def _chapter_durations_ms(
    chapter_files: list[Path],
    pause_ms: int,
    bitrate_kbps: int,
    base_format: str,
) -> list[int]:
    """Get per-chapter durations as they will appear in the combined file (including trailing pause except last)."""
    files = [Path(p) for p in chapter_files if Path(p).exists() and Path(p).stat().st_size > 0]
    if not files:
        return []
    fmt = normalize_output_format(base_format)
    ext = extension_for_format(fmt)
    pause_ms = max(0, int(pause_ms))
    bitrate_kbps = _clamp_bitrate(bitrate_kbps)

    durations: list[int] = []
    # Use normalized temp copies to reflect final per-chapter segment durations in the combined stream
    try:
        with tempfile.TemporaryDirectory(prefix="bookcoder_chdur_") as td:
            td_path = Path(td)
            total = len(files)
            for i, f in enumerate(files):
                tmp = td_path / f"ch_{i:04d}{ext}"
                if pause_ms > 0 and i < total - 1:
                    add_trailing_silence(f, tmp, pause_ms, bitrate_kbps=bitrate_kbps, output_format=fmt)
                else:
                    normalize_audio(f, tmp, bitrate_kbps=bitrate_kbps, output_format=fmt)
                d = _audio_duration_ms(tmp)
                if d <= 0:
                    d = _audio_duration_ms(f) + (pause_ms if (pause_ms > 0 and i < total - 1) else 0)
                durations.append(max(0, int(d)))
    except Exception:
        for i, f in enumerate(files):
            d = _audio_duration_ms(f) + (pause_ms if (pause_ms > 0 and i < len(files) - 1) else 0)
            durations.append(max(0, int(d)))
    return durations


def _build_ffmetadata_chapters(
    chapter_titles: list[str],
    chapter_durations_ms: list[int],
    metadata: Optional[dict[str, str]] = None,
) -> str:
    lines = [";FFMETADATA1"]
    md = metadata or {}
    for key in ("title", "album", "artist", "album_artist", "composer", "genre", "comment", "date", "language"):
        val = md.get(key)
        if val is None:
            continue
        sval = str(val).strip()
        if not sval:
            continue
        lines.append(f"{key}={_ffmetadata_escape(sval)}")
    lines.append("")

    start = 0
    n = max(len(chapter_titles), len(chapter_durations_ms))
    for i in range(n):
        dur = int(chapter_durations_ms[i]) if i < len(chapter_durations_ms) else 0
        dur = max(0, dur)
        end = start + dur if dur > 0 else start
        if end <= start:
            end = start + 1  # keep chapter entries valid even if duration unknown
        title = chapter_titles[i] if i < len(chapter_titles) and chapter_titles[i] else f"Chapter {i + 1}"
        lines.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={end}",
            f"title={_ffmetadata_escape(str(title))}",
            "",
        ])
        start = end
    return "\n".join(lines).rstrip() + "\n"


def _mux_chapter_metadata_with_ffmpeg(
    input_path: Path,
    output_path: Path,
    chapter_titles: list[str],
    chapter_durations_ms: list[int],
    metadata: Optional[dict[str, str]] = None,
) -> bool:
    ffmpeg = ensure_ffmpeg()
    if not ffmpeg:
        return False
    in_path = Path(input_path)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = normalize_output_format(out_path.suffix.lstrip("."))
    try:
        with tempfile.TemporaryDirectory(prefix="bookcoder_meta_") as td:
            meta_path = Path(td) / "chapters.ffmeta"
            meta_text = _build_ffmetadata_chapters(chapter_titles, chapter_durations_ms, metadata=metadata)
            meta_path.write_text(meta_text, encoding="utf-8")

            cmd = [
                ffmpeg, "-y",
                "-i", str(in_path),
                "-i", str(meta_path),
                "-map", "0:a",
                "-map_metadata", "1",
                "-map_chapters", "1",
                "-c", "copy",
            ]
            if fmt in ("m4a", "m4b"):
                cmd.extend(["-movflags", "+faststart"])
            cmd.append(str(out_path))

            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                return True
    except Exception:
        return False
    return False


def combine_audio_files(
    chapter_files: list[Path],
    output_path: Path,
    pause_ms: int = 1200,
    bitrate_kbps: int = 128,
    output_format: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    chapter_titles: Optional[list[str]] = None,
    metadata: Optional[dict[str, str]] = None,
) -> Path:
    """Combine multiple chapter audio files into one audiobook file with pauses between chapters.

    If chapter_titles are provided and ffmpeg is available, chapter markers/metadata are embedded
    (especially useful for M4B/M4A audiobooks).
    """
    files = [Path(p) for p in chapter_files if Path(p).exists() and Path(p).stat().st_size > 0]
    if not files:
        raise AudioProcessingError("No chapter audio files to combine.")

    output_path = Path(output_path)
    if output_format:
        desired_ext = extension_for_format(output_format)
        if output_path.suffix.lower() != desired_ext:
            output_path = output_path.with_suffix(desired_ext)
    fmt = normalize_output_format(output_path.suffix.lstrip("."))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pause_ms = max(0, int(pause_ms))
    bitrate_kbps = _clamp_bitrate(bitrate_kbps)

    def _finalize_with_chapters(combined_path: Path) -> Path:
        titles = list(chapter_titles or [])
        if not titles:
            return combined_path
        # Normalize titles count to files count
        if len(titles) < len(files):
            titles.extend([f"Chapter {i + 1}" for i in range(len(titles), len(files))])
        elif len(titles) > len(files):
            titles = titles[: len(files)]

        durations = _chapter_durations_ms(files, pause_ms=pause_ms, bitrate_kbps=bitrate_kbps, base_format=fmt)
        if not durations or len(durations) != len(files):
            # fallback estimate
            durations = []
            for i, f in enumerate(files):
                d = _audio_duration_ms(f) + (pause_ms if (pause_ms > 0 and i < len(files) - 1) else 0)
                durations.append(max(1, int(d)))

        muxed_tmp = combined_path.with_name(combined_path.stem + ".chapters" + combined_path.suffix)
        try:
            if _mux_chapter_metadata_with_ffmpeg(combined_path, muxed_tmp, titles, durations, metadata=metadata):
                try:
                    muxed_tmp.replace(combined_path)
                except Exception:
                    shutil.copy2(muxed_tmp, combined_path)
                    try:
                        muxed_tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                try:
                    if muxed_tmp.exists():
                        muxed_tmp.unlink()
                except Exception:
                    pass
        except Exception:
            try:
                if muxed_tmp.exists():
                    muxed_tmp.unlink()
            except Exception:
                pass
        return combined_path

    # pydub path (best control over pauses)
    try:
        from pydub import AudioSegment  # type: ignore

        combined = AudioSegment.empty()
        silence = AudioSegment.silent(duration=pause_ms) if pause_ms > 0 else None
        total = len(files)
        for i, f in enumerate(files):
            if progress:
                progress(i, total)
            seg = AudioSegment.from_file(str(f))
            combined += seg
            if silence is not None and i < total - 1:
                combined += silence
        if progress:
            progress(total, total)
        if _pydub_export(combined, output_path, bitrate_kbps, 44100):
            return _finalize_with_chapters(output_path)
    except Exception:
        pass

    ffmpeg = ensure_ffmpeg()
    if ffmpeg:
        # Create intermediate files with appended silence (except last) then concat demuxer
        try:
            with tempfile.TemporaryDirectory(prefix="bookcoder_combine_") as td:
                td_path = Path(td)
                prepped: list[Path] = []
                total = len(files)
                ext = extension_for_format(fmt)
                for i, f in enumerate(files):
                    if progress:
                        progress(i, total)
                    tmp = td_path / f"ch_{i:04d}{ext}"
                    if pause_ms > 0 and i < total - 1:
                        add_trailing_silence(f, tmp, pause_ms, bitrate_kbps=bitrate_kbps, output_format=fmt)
                    else:
                        normalize_audio(f, tmp, bitrate_kbps=bitrate_kbps, output_format=fmt)
                    prepped.append(tmp)
                if progress:
                    progress(total, total)

                list_file = td_path / "concat.txt"
                lines = []
                for p in prepped:
                    lines.append("file '" + str(p.resolve()).replace("'", "'\\''") + "'")
                list_file.write_text("\n".join(lines), encoding="utf-8")

                # Try stream copy first (fast) - works when all segments are encoded consistently
                cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_path)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return _finalize_with_chapters(output_path)

                # Fallback: re-encode concat
                cmd2 = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)] + _ffmpeg_encode_args(output_path, bitrate_kbps, 44100)
                res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return _finalize_with_chapters(output_path)
        except Exception:
            pass

    # Last resort: naive concat (only meaningful for mp3); for AAC containers this is unlikely to work but try as final fallback
    try:
        with output_path.open("wb") as out:
            for f in files:
                out.write(Path(f).read_bytes())
        if output_path.exists() and output_path.stat().st_size > 0:
            return _finalize_with_chapters(output_path)
    except Exception:
        pass

    raise AudioProcessingError(f"Failed to combine audio files into {format_label(fmt)} output.")


def combine_mp3_files(
    chapter_files: list[Path],
    output_path: Path,
    pause_ms: int = 1200,
    bitrate_kbps: int = 128,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    # Backward-compatible wrapper
    return combine_audio_files(
        chapter_files, output_path, pause_ms=pause_ms, bitrate_kbps=bitrate_kbps, output_format="mp3", progress=progress
    )

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
    if f in ("m4a", "aac", "mp4", "ipod"):
        return "m4a"
    return "mp3"


def extension_for_format(fmt: Optional[str]) -> str:
    return ".m4a" if normalize_output_format(fmt) == "m4a" else ".mp3"


def format_label(fmt: Optional[str]) -> str:
    return "AAC (M4A)" if normalize_output_format(fmt) == "m4a" else "MP3"


def _clamp_bitrate(bitrate_kbps: int) -> int:
    try:
        b = int(bitrate_kbps or 128)
    except Exception:
        b = 128
    return max(64, min(b, 320))


def _ffmpeg_encode_args(output_path: Path, bitrate_kbps: int, sample_rate: int) -> list[str]:
    fmt = normalize_output_format(output_path.suffix.lstrip("."))
    b = _clamp_bitrate(bitrate_kbps)
    if fmt == "m4a":
        # AAC in M4A container for broad iPhone compatibility
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
        if fmt == "m4a":
            # Prefer 'ipod' for .m4a AAC output via ffmpeg
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

        # Extra fallback for m4a: try without faststart/movflags ordering issues are rare, but try simpler
        if fmt == "m4a":
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


def combine_audio_files(
    chapter_files: list[Path],
    output_path: Path,
    pause_ms: int = 1200,
    bitrate_kbps: int = 128,
    output_format: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Combine multiple chapter audio files into one audiobook file with pauses between chapters."""
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
            return output_path
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
                    return output_path

                # Fallback: re-encode concat
                cmd2 = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)] + _ffmpeg_encode_args(output_path, bitrate_kbps, 44100)
                res2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return output_path
        except Exception:
            pass

    # Last resort: naive concat (only meaningful for mp3); for m4a this is unlikely to work but try as final fallback
    try:
        with output_path.open("wb") as out:
            for f in files:
                out.write(Path(f).read_bytes())
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
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

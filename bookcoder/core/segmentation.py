from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import NarrationSettings


@dataclass
class SpeechSegment:
    text: str
    pause_after_ms: int = 0
    speed_multiplier: float = 1.0
    pitch_delta: float = 0.0
    kind: str = "text"  # title, paragraph, scene_break, dialogue, text, initial_pause


_SCENE_BREAK_RE = re.compile(r"^\s*(?:[\*\-–—_#]\s*){3,}$")
_DIALOGUE_START_RE = re.compile(r"""^\s*(?:["“„'’‚‛«»]|[-–—]\s+\S)""")


def plan_chapter_segments(
    narration_text: str,
    chapter_title: str = "",
    settings: Optional[NarrationSettings] = None,
    max_chars: int = 1400,
    tone_profile: Optional[str] = None,
    provider_supports_pitch: bool = False,
) -> list[SpeechSegment]:
    """Create structure-aware speech segments with pause/prosody hints.

    Step 3 planner: paragraph/scene/dialogue-aware chunking and pause timing with
    provider-aware dynamic tone profile hints (subtle, fallback-safe).
    """
    text = (narration_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    paragraph_pause_ms = 450
    sentence_pause_hint = True
    profile_name = "natural"
    if settings is not None:
        try:
            paragraph_pause_ms = max(0, int(getattr(settings, "paragraph_pause_ms", 450) or 450))
        except Exception:
            paragraph_pause_ms = 450
        sentence_pause_hint = bool(getattr(settings, "sentence_pause_hint", True))
        profile_name = str(getattr(settings, "tone_profile", "natural") or "natural")
    if tone_profile:
        profile_name = str(tone_profile)

    profile = _get_tone_profile(profile_name, provider_supports_pitch=provider_supports_pitch)

    # Scene breaks get a longer pause than a normal paragraph, but stay reasonable.
    scene_pause_ms = max(paragraph_pause_ms * 2, 900)
    scene_pause_ms = min(scene_pause_ms, 2500)

    blocks = _split_paragraph_blocks(text)
    segments: list[SpeechSegment] = []

    title_norm = _norm_for_compare(chapter_title)
    first_text_block_seen = False

    for bi, block in enumerate(blocks):
        raw = block.strip("\n")
        stripped = raw.strip()
        if not stripped:
            continue

        is_last_block = bi == len(blocks) - 1

        # Scene break marker: pause only (no spoken marker), attached to previous segment when possible.
        if _is_scene_break(stripped):
            if segments:
                segments[-1].pause_after_ms = max(segments[-1].pause_after_ms, scene_pause_ms)
            else:
                segments.append(SpeechSegment(text="", pause_after_ms=scene_pause_ms, speed_multiplier=1.0, pitch_delta=0.0, kind="scene_break"))
            continue

        kind = "paragraph"
        speed_multiplier, pitch_delta = _profile_hints_for_kind(profile, "paragraph")

        # Detect title-like leading block (pipeline may prepend chapter title).
        block_norm = _norm_for_compare(stripped)
        if not first_text_block_seen and title_norm and (block_norm == title_norm or block_norm.startswith(title_norm)):
            kind = "title"
            speed_multiplier, pitch_delta = _profile_hints_for_kind(profile, "title")
        elif _looks_dialogue_block(stripped):
            kind = "dialogue"
            speed_multiplier, pitch_delta = _profile_hints_for_kind(profile, "dialogue")

        # Split long blocks into synthesis-friendly chunks, preferring sentence boundaries.
        chunks = _split_block_for_tts(stripped, max_chars=max_chars, sentence_aware=sentence_pause_hint)
        if not chunks:
            continue

        block_pause = 0 if is_last_block else paragraph_pause_ms
        for ci, chunk in enumerate(chunks):
            chunk_text = chunk.strip()
            if not chunk_text:
                continue
            pause_after = block_pause if ci == len(chunks) - 1 else _intra_block_pause(chunk_text, paragraph_pause_ms, sentence_pause_hint)
            seg_kind = kind if ci == 0 else ("dialogue" if kind == "dialogue" else "text")
            seg_speed, seg_pitch = (speed_multiplier, pitch_delta) if seg_kind in ("title", "dialogue") else _profile_hints_for_kind(profile, seg_kind)
            segments.append(
                SpeechSegment(
                    text=chunk_text,
                    pause_after_ms=max(0, int(pause_after)),
                    speed_multiplier=seg_speed,
                    pitch_delta=seg_pitch,
                    kind=seg_kind,
                )
            )
        first_text_block_seen = True

    # Merge pending leading scene-break markers into initial pause marker.
    compacted: list[SpeechSegment] = []
    pending_initial_pause = 0
    for seg in segments:
        if seg.kind == "scene_break" and not seg.text.strip():
            if not compacted:
                pending_initial_pause = max(pending_initial_pause, seg.pause_after_ms)
            else:
                compacted[-1].pause_after_ms = max(compacted[-1].pause_after_ms, seg.pause_after_ms)
            continue
        if pending_initial_pause > 0 and seg.text.strip():
            compacted.append(SpeechSegment(text="", pause_after_ms=pending_initial_pause, speed_multiplier=1.0, pitch_delta=0.0, kind="initial_pause"))
            pending_initial_pause = 0
        compacted.append(seg)
    if pending_initial_pause > 0 and not compacted:
        pending_initial_pause = 0

    # Remove trailing pauses (chapter pause handled by pipeline/combine stage)
    for i in range(len(compacted) - 1, -1, -1):
        if compacted[i].text.strip():
            compacted[i].pause_after_ms = 0
            break
        compacted.pop(i)

    # Drop any empty non-initial markers that may remain except initial_pause
    final: list[SpeechSegment] = []
    for seg in compacted:
        if seg.kind == "initial_pause":
            final.append(seg)
            continue
        if seg.text and seg.text.strip():
            final.append(seg)
        elif final:
            final[-1].pause_after_ms = max(final[-1].pause_after_ms, seg.pause_after_ms)
    return final


def _get_tone_profile(profile_name: str, provider_supports_pitch: bool = False) -> dict[str, tuple[float, float]]:
    """Return per-kind (speed_multiplier, pitch_delta) hints for a tone profile.

    Pitch deltas are only emitted when provider supports pitch; kept subtle.
    Profiles are intentionally conservative and provider-safe.
    """
    name = (profile_name or "natural").strip().lower()
    # Base defaults
    profiles: dict[str, dict[str, tuple[float, float]]] = {
        "neutral": {
            "title": (1.0, 0.0),
            "dialogue": (1.0, 0.0),
            "paragraph": (1.0, 0.0),
            "text": (1.0, 0.0),
        },
        "clear": {
            "title": (0.99, 0.0),
            "dialogue": (1.0, 0.0),
            "paragraph": (1.0, 0.0),
            "text": (1.0, 0.0),
        },
        "natural": {
            "title": (0.98, 0.2),
            "dialogue": (1.01, 0.3),
            "paragraph": (1.0, 0.0),
            "text": (1.0, 0.0),
        },
        "expressive": {
            "title": (0.97, 0.3),
            "dialogue": (1.02, 0.5),
            "paragraph": (1.0, 0.0),
            "text": (1.0, 0.0),
        },
    }
    profile = profiles.get(name, profiles["natural"]).copy()
    if not provider_supports_pitch:
        profile = {k: (spd, 0.0) for k, (spd, _p) in profile.items()}
    return profile


def _profile_hints_for_kind(profile: dict[str, tuple[float, float]], kind: str) -> tuple[float, float]:
    return profile.get(kind, profile.get("paragraph", (1.0, 0.0)))


def _split_paragraph_blocks(text: str) -> list[str]:
    # Preserve scene-break lines as their own blocks.
    lines = text.split("\n")
    grouped: list[str] = []
    buf: list[str] = []

    def flush_buf():
        nonlocal buf
        if buf:
            grouped.append("\n".join(buf).strip("\n"))
            buf = []

    empty_run = 0
    for ln in lines:
        if ln.strip() == "":
            empty_run += 1
            if empty_run >= 1:
                flush_buf()
            continue
        if empty_run > 0:
            empty_run = 0
        if _is_scene_break(ln.strip()):
            flush_buf()
            grouped.append(ln.strip())
            continue
        buf.append(ln.rstrip())
    flush_buf()

    # If no blank-line structure found, fall back to single block
    if not grouped and text.strip():
        return [text.strip()]
    return [g for g in grouped if g is not None and str(g).strip() != ""]


def _is_scene_break(s: str) -> bool:
    st = (s or "").strip()
    if not st:
        return False
    if _SCENE_BREAK_RE.match(st):
        return True
    # Common textual scene markers
    lowered = st.lower().strip("*-–—_ #")
    return lowered in {"scene", "scene break"}


def _looks_dialogue_block(text: str) -> bool:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return False
    # Heuristic: first line starts like dialogue OR many lines start with dialogue markers.
    if _DIALOGUE_START_RE.match(lines[0]):
        return True
    if len(lines) >= 2:
        hits = sum(1 for ln in lines if _DIALOGUE_START_RE.match(ln))
        return hits >= max(2, len(lines) // 2)
    return False


def _split_block_for_tts(text: str, max_chars: int = 1400, sentence_aware: bool = True) -> list[str]:
    t = re.sub(r"[ \t]+", " ", (text or "").strip())
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]

    # Prefer sentence boundaries, then line breaks, then hard splits.
    parts: list[str] = []
    if sentence_aware:
        # Keep delimiters attached for prosody.
        sentences = re.split(r"(?<=[\.!\?\…][\"”’»']?)\s+|\n+", t)
    else:
        sentences = re.split(r"\n+", t)

    cur = ""
    for sent in sentences:
        s = (sent or "").strip()
        if not s:
            continue
        if len(s) > max_chars:
            if cur:
                parts.append(cur.strip())
                cur = ""
            parts.extend(_hard_split(s, max_chars))
            continue
        candidate = f"{cur} {s}".strip() if cur else s
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            if cur:
                parts.append(cur.strip())
            cur = s
    if cur:
        parts.append(cur.strip())
    return [p for p in parts if p]


def _hard_split(text: str, max_chars: int) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]
    out: list[str] = []
    start = 0
    n = len(t)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # try to break on whitespace
            ws = t.rfind(" ", start + max(1, max_chars // 2), end)
            if ws > start:
                end = ws
        piece = t[start:end].strip()
        if piece:
            out.append(piece)
        start = end
        while start < n and t[start].isspace():
            start += 1
    return out


def _intra_block_pause(text: str, paragraph_pause_ms: int, sentence_pause_hint: bool) -> int:
    # Small optional pause between chunks inside the same paragraph/block for clarity.
    # Keep subtle; TTS punctuation already provides prosody.
    if not sentence_pause_hint:
        return 0
    t = (text or "").strip()
    if not t:
        return 0
    # If chunk ends with strong punctuation, a tiny pause can help when split unnaturally.
    if t.endswith(("...", ".", "!", "?", "…")) and len(t) > 220:
        return min(180, max(80, paragraph_pause_ms // 4))
    return 0


def _norm_for_compare(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\.:;!\-–—]+$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

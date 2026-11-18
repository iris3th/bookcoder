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
    kind: str = "text"  # title, paragraph, scene_break, dialogue, dialogue_alt, text, initial_pause
    cast_role: str = ""  # optional voice-casting role hint (narrator/dialogue/dialogue_alt)


_SCENE_BREAK_RE = re.compile(r"^\s*(?:[\*\-–—_#]\s*){3,}$")
_DIALOGUE_START_RE = re.compile(r"""^\s*(?:["“„'’‚‛«»]|[-–—]\s+\S)""")
_INLINE_DIALOGUE_RE = re.compile(
    r'("([^"\n]+)"|“([^”\n]+)”|„([^”\n]+)”|«([^»\n]+)»)',
    re.DOTALL,
)


def plan_chapter_segments(
    narration_text: str,
    chapter_title: str = "",
    settings: Optional[NarrationSettings] = None,
    max_chars: int = 1400,
    tone_profile: Optional[str] = None,
    provider_supports_pitch: bool = False,
) -> list[SpeechSegment]:
    """Create structure-aware speech segments with pause/prosody hints.

    Planner: paragraph/scene/dialogue-aware chunking and pause timing with
    provider-aware dynamic tone profile hints and intra-paragraph quote-span
    casting hooks (subtle, fallback-safe).
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
    dialogue_toggle = 0  # alternate quoted dialogue spans for multi-voice hooks

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

        # Detect title-like leading block (pipeline may prepend chapter title).
        block_norm = _norm_for_compare(stripped)
        if not first_text_block_seen and title_norm and (block_norm == title_norm or block_norm.startswith(title_norm)):
            block_parts = [(stripped, "title", "narrator")]
        else:
            block_parts = _split_block_into_cast_spans(stripped)

        # Build chunked speech segments per part, preserving order and cast roles.
        # Only the final chunk of the final part of this block receives the paragraph pause.
        expanded: list[tuple[str, str, str]] = []  # (chunk_text, kind, cast_role)
        for part_text, part_kind, part_role in block_parts:
            ptxt = (part_text or "").strip()
            if not ptxt:
                continue
            chunks = _split_block_for_tts(ptxt, max_chars=max_chars, sentence_aware=sentence_pause_hint)
            if not chunks:
                continue
            for ci, chunk in enumerate(chunks):
                chunk_text = (chunk or "").strip()
                if not chunk_text:
                    continue
                # Keep title/dialogue/paragraph style for first chunk of a part; continuation chunks soften to text/dialogue
                if ci == 0:
                    seg_kind = part_kind
                elif part_kind in ("dialogue", "dialogue_alt"):
                    seg_kind = part_kind
                elif part_kind == "title":
                    seg_kind = "text"
                else:
                    seg_kind = "text"
                # Alternate dialogue speaker roles for quoted spans as a simple multi-voice hook.
                cast_role = part_role
                if part_kind in ("dialogue", "dialogue_alt"):
                    if part_kind == "dialogue_alt":
                        cast_role = "dialogue_alt"
                    elif cast_role in ("", "dialogue"):
                        cast_role = "dialogue" if (dialogue_toggle % 2 == 0) else "dialogue_alt"
                        # Count once per dialogue span part, not per chunk; handled below by tracking part index
                expanded.append((chunk_text, seg_kind, cast_role))

            # advance alternating dialogue toggle once per dialogue span part
            if part_kind in ("dialogue", "dialogue_alt") and chunks:
                dialogue_toggle += 1

        if not expanded:
            continue

        block_pause = 0 if is_last_block else paragraph_pause_ms
        for ei, (chunk_text, seg_kind, cast_role) in enumerate(expanded):
            pause_after = block_pause if ei == len(expanded) - 1 else _intra_block_pause(chunk_text, paragraph_pause_ms, sentence_pause_hint)
            profile_kind = seg_kind
            if profile_kind == "dialogue_alt":
                profile_kind = "dialogue"
            seg_speed, seg_pitch = _profile_hints_for_kind(profile, profile_kind if profile_kind in ("title", "dialogue") else ("text" if profile_kind == "text" else "paragraph"))
            # For explicit dialogue/title kinds, prefer their profile even if continuation chunk.
            if seg_kind in ("title", "dialogue", "dialogue_alt"):
                seg_speed, seg_pitch = _profile_hints_for_kind(profile, "title" if seg_kind == "title" else "dialogue")
            segments.append(
                SpeechSegment(
                    text=chunk_text,
                    pause_after_ms=max(0, int(pause_after)),
                    speed_multiplier=seg_speed,
                    pitch_delta=seg_pitch,
                    kind=seg_kind,
                    cast_role=cast_role or ("narrator" if seg_kind not in ("dialogue", "dialogue_alt") else seg_kind),
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

    # Merge adjacent narrator/text segments when split unnecessarily (e.g. around quote spans)
    # to reduce TTS boundary artifacts, while preserving dialogue/title boundaries and pauses.
    merged_narration: list[SpeechSegment] = []
    for seg in compacted:
        if not merged_narration:
            merged_narration.append(seg)
            continue
        prev = merged_narration[-1]
        if _can_merge_narrator_segments(prev, seg):
            prev.text = (prev.text.rstrip() + " " + seg.text.lstrip()).strip()
            prev.pause_after_ms = max(int(prev.pause_after_ms or 0), int(seg.pause_after_ms or 0))
            # Keep kind/cast hints from previous; if previous is generic, adopt current generic kind if useful
            if prev.kind in ("text", "paragraph") and seg.kind in ("text", "paragraph"):
                if prev.kind == "text" and seg.kind == "paragraph":
                    prev.kind = "paragraph"
            if not prev.cast_role:
                prev.cast_role = seg.cast_role or "narrator"
            prev.speed_multiplier = prev.speed_multiplier or seg.speed_multiplier
            prev.pitch_delta = prev.pitch_delta if prev.pitch_delta != 0.0 else seg.pitch_delta
        else:
            merged_narration.append(seg)
    compacted = merged_narration

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
    k = kind or "paragraph"
    if k == "dialogue_alt":
        k = "dialogue"
    return profile.get(k, profile.get("paragraph", (1.0, 0.0)))


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


def _split_block_into_cast_spans(text: str) -> list[tuple[str, str, str]]:
    """Split a paragraph block into ordered spans for narration casting.

    Returns list of (text, kind, cast_role) where kind/cast_role are narrator/text
    or dialogue/dialogue(_alt assigned later in planner) for quoted spans.

    Heuristic and conservative:
    - Detects common double-quote/guillemet spans inline for dialogue casting.
    - Recognizes line-leading dialogue dash markers as dialogue when the whole line is speech-like.
    - Falls back to whole-block dialogue classification when no inline spans are found.
    """
    t = (text or "").strip()
    if not t:
        return []

    # If block is strongly dialogue-formatted line-by-line (e.g. script/dash dialogue), keep simple.
    # We still allow multi-line blocks; alternating hook will be applied per produced dialogue part.
    lines = [ln.rstrip() for ln in t.splitlines()]
    nonempty_lines = [ln.strip() for ln in lines if ln.strip()]
    if len(nonempty_lines) >= 2:
        dash_hits = sum(1 for ln in nonempty_lines if re.match(r"""^\s*[-–—]\s+\S""", ln))
        if dash_hits >= max(2, (len(nonempty_lines) + 1) // 2):
            parts: list[tuple[str, str, str]] = []
            for ln in nonempty_lines:
                is_dash = bool(re.match(r"""^\s*[-–—]\s+\S""", ln))
                if is_dash:
                    parts.append((ln, "dialogue", "dialogue"))
                else:
                    parts.append((ln, "paragraph", "narrator"))
            return _merge_adjacent_cast_parts(parts)

    # Inline quoted-span detection (intra-paragraph smart casting)
    matches = list(_INLINE_DIALOGUE_RE.finditer(t))
    if matches:
        parts = []
        pos = 0
        for m in matches:
            start, end = m.span()
            if start > pos:
                pre = t[pos:start].strip()
                if pre:
                    parts.append((pre, "paragraph", "narrator"))
            quoted = (m.group(0) or "").strip()
            if quoted:
                parts.append((quoted, "dialogue", "dialogue"))
            pos = end
        if pos < len(t):
            tail = t[pos:].strip()
            if tail:
                parts.append((tail, "paragraph", "narrator"))
        parts = [p for p in parts if p[0] and p[0].strip()]
        # If quotes were detected but everything became dialogue (e.g. entire block quoted), keep as dialogue.
        if parts and any(k != "dialogue" for _, k, _ in parts):
            return _merge_adjacent_cast_parts(parts)
        if parts:
            return _merge_adjacent_cast_parts(parts)

    # Fallback: whole-block classification
    if _looks_dialogue_block(t):
        return [(t, "dialogue", "dialogue")]
    return [(t, "paragraph", "narrator")]


def _merge_adjacent_cast_parts(parts: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    if not parts:
        return []
    merged: list[tuple[str, str, str]] = []
    for text, kind, role in parts:
        s = (text or "").strip()
        if not s:
            continue
        if not merged:
            merged.append((s, kind, role))
            continue
        prev_text, prev_kind, prev_role = merged[-1]
        # Merge adjacent narrator/paragraph spans to reduce fragmentation; do not merge dialogue spans
        # because alternating speaker hooks may treat them separately.
        if kind not in ("dialogue", "dialogue_alt") and prev_kind not in ("dialogue", "dialogue_alt") and kind == prev_kind and role == prev_role:
            merged[-1] = ((prev_text + " " + s).strip(), prev_kind, prev_role)
        else:
            merged.append((s, kind, role))
    return merged


def _can_merge_narrator_segments(a: SpeechSegment, b: SpeechSegment) -> bool:
    if not a or not b:
        return False
    if a.kind == "initial_pause" or b.kind == "initial_pause":
        return False
    if not (a.text or "").strip() or not (b.text or "").strip():
        return False
    # Don't merge across explicit pause boundaries inside blocks
    if int(getattr(a, "pause_after_ms", 0) or 0) > 0:
        return False
    ak = (getattr(a, "kind", "") or "text")
    bk = (getattr(b, "kind", "") or "text")
    ar = (getattr(a, "cast_role", "") or "") or ("narrator" if ak not in ("dialogue", "dialogue_alt") else ak)
    br = (getattr(b, "cast_role", "") or "") or ("narrator" if bk not in ("dialogue", "dialogue_alt") else bk)
    # Preserve dialogue/title as distinct synthesis units
    if ak in ("title", "dialogue", "dialogue_alt") or bk in ("title", "dialogue", "dialogue_alt"):
        return False
    if ar != "narrator" or br != "narrator":
        return False
    # Keep merged chunks reasonably sized for TTS stability
    if len(a.text) + 1 + len(b.text) > 1400:
        return False
    return True


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

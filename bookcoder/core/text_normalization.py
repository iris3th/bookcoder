from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Optional

from .models import Language


class TextNormalizationError(Exception):
    pass


# Conservative abbreviation expansions. Applied with word-boundary-aware patterns.
_EN_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bMr\.", re.IGNORECASE), "Mister"),
    (re.compile(r"\bMrs\.", re.IGNORECASE), "Misses"),
    (re.compile(r"\bMs\.", re.IGNORECASE), "Miss"),
    (re.compile(r"\bDr\.", re.IGNORECASE), "Doctor"),
    (re.compile(r"\bProf\.", re.IGNORECASE), "Professor"),
    (re.compile(r"\bSr\.", re.IGNORECASE), "Senior"),
    (re.compile(r"\bJr\.", re.IGNORECASE), "Junior"),
    (re.compile(r"\bSt\.", re.IGNORECASE), "Saint"),
    (re.compile(r"\bMt\.", re.IGNORECASE), "Mount"),
    (re.compile(r"\bvs\.", re.IGNORECASE), "versus"),
    (re.compile(r"\betc\.", re.IGNORECASE), "etcetera"),
    (re.compile(r"\be\.g\.", re.IGNORECASE), "for example"),
    (re.compile(r"\bi\.e\.", re.IGNORECASE), "that is"),
    (re.compile(r"\b approx\.", re.IGNORECASE), " approximately"),
    (re.compile(r"\bno\.(?=\s*\d)", re.IGNORECASE), "number"),
    (re.compile(r"\bNo\.(?=\s*\d)"), "Number"),
    (re.compile(r"\bvol\.(?=\s*\d)", re.IGNORECASE), "volume"),
    (re.compile(r"\bVol\.(?=\s*\d)"), "Volume"),
    (re.compile(r"\bch\.(?=\s*\d)", re.IGNORECASE), "chapter"),
    (re.compile(r"\bCh\.(?=\s*\d)"), "Chapter"),
    (re.compile(r"\bfig\.(?=\s*\d)", re.IGNORECASE), "figure"),
    (re.compile(r"\bFig\.(?=\s*\d)"), "Figure"),
    (re.compile(r"\bp\.(?=\s*\d)", re.IGNORECASE), "page"),
    (re.compile(r"\bpp\.(?=\s*\d)", re.IGNORECASE), "pages"),
]

_HU_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdr\.", re.IGNORECASE), "doktor"),
    (re.compile(r"\bDr\."), "Doktor"),
    (re.compile(r"\bprof\.", re.IGNORECASE), "professzor"),
    (re.compile(r"\bProf\."), "Professzor"),
    (re.compile(r"\bstb\.", re.IGNORECASE), "s a többi"),
    (re.compile(r"\bpl\.", re.IGNORECASE), "például"),
    (re.compile(r"\bPl\."), "Például"),
    (re.compile(r"\bkb\.", re.IGNORECASE), "körülbelül"),
    (re.compile(r"\bKb\."), "Körülbelül"),
    (re.compile(r"\bsz\.(?=\s*\d)", re.IGNORECASE), "szám"),
    (re.compile(r"\bSz\.(?=\s*\d)"), "Szám"),
    (re.compile(r"\bev\.(?=\s*\d)", re.IGNORECASE), "évfolyam"),
    (re.compile(r"\bu\.(?=\s|$)", re.IGNORECASE), "utca"),
    (re.compile(r"\bún\.", re.IGNORECASE), "úgynevezett"),
    (re.compile(r"\bÚn\."), "Úgynevezett"),
    (re.compile(r"\bill\.", re.IGNORECASE), "illetve"),
    (re.compile(r"\bIll\."), "Illetve"),
    (re.compile(r"\bvö\.", re.IGNORECASE), "vesd össze"),
    (re.compile(r"\bVö\."), "Vesd össze"),
    (re.compile(r"\bui\.", re.IGNORECASE), "utóirat"),
    (re.compile(r"\bUi\."), "Utóirat"),
    (re.compile(r"\bKr\.?\s*e\.", re.IGNORECASE), "Krisztus előtt"),
    (re.compile(r"\bKr\.?\s*u\.", re.IGNORECASE), "Krisztus után"),
]

# Basic symbol replacements by language.
_COMMON_SYMBOLS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[“”„‟«»]"), '"'),
    (re.compile(r"[‘’‚‛]"), "'"),
    (re.compile(r"…"), "..."),
    (re.compile(r"[–—−]"), " - "),
    (re.compile(r"\u00ad"), ""),  # soft hyphen
    (re.compile(r"\ufeff"), ""),
    (re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"), " "),
    (re.compile(r"\s*\(\s*\)\s*"), " "),
    (re.compile(r"\s*\[\s*\]\s*"), " "),
]

_EN_SYMBOLS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"\s*@\s*"), " at "),
    (re.compile(r"\s*%\s*"), " percent "),
    (re.compile(r"\s*\+\s*"), " plus "),
    (re.compile(r"°\s*C\b"), " degrees Celsius"),
    (re.compile(r"°\s*F\b"), " degrees Fahrenheit"),
    (re.compile(r"°"), " degrees "),
    (re.compile(r"\s*§\s*"), " section "),
    (re.compile(r"\s*#(?=\d)"), " number "),
]

_HU_SYMBOLS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\s*&\s*"), " és "),
    (re.compile(r"\s*@\s*"), " kukac "),
    (re.compile(r"\s*%\s*"), " százalék "),
    (re.compile(r"\s*\+\s*"), " plusz "),
    (re.compile(r"°\s*C\b"), " Celsius-fok"),
    (re.compile(r"°\s*F\b"), " Fahrenheit-fok"),
    (re.compile(r"°"), " fok "),
    (re.compile(r"\s*§\s*"), " paragrafus "),
    (re.compile(r"\s*#(?=\d)"), " szám "),
]


def normalize_for_tts(
    text: str,
    language: Optional[Language | str] = None,
    pronunciation_map: Optional[Mapping[str, str]] = None,
) -> str:
    """Normalize/prepare text for speech synthesis.

    Step 1 goals: safe cleanup, abbreviation/symbol normalization, and optional
    pronunciation hooks. Designed to be conservative and fallback-friendly.
    """
    if not text:
        return ""
    try:
        lang = _coerce_language(language)
        t = str(text)

        # Unicode normalization and basic cleanup
        t = unicodedata.normalize("NFKC", t)
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        t = re.sub(r"https?://\S+|www\.\S+", " ", t)
        t = re.sub(r"<[^>]+>", " ", t)

        for pat, repl in _COMMON_SYMBOLS:
            t = pat.sub(repl, t)

        # Remove footnote markers like [1] or (1) when isolated-ish (conservative)
        t = re.sub(r"\[(?:\d{1,3})\]", " ", t)

        # Apply pronunciation map hooks early so user intent can override defaults.
        # Hooks are treated as literal phrase replacements (case-sensitive pass + case-insensitive fallback per key).
        t = _apply_pronunciation_map(t, pronunciation_map)

        # Language-aware abbreviation and symbol normalization
        if lang == Language.HUNGARIAN:
            t = _apply_replacements(t, _HU_ABBREVIATIONS)
            t = _apply_replacements(t, _HU_SYMBOLS)
            t = _normalize_numbers_and_dates(t, Language.HUNGARIAN)
        elif lang == Language.ENGLISH:
            t = _apply_replacements(t, _EN_ABBREVIATIONS)
            t = _apply_replacements(t, _EN_SYMBOLS)
            t = _normalize_numbers_and_dates(t, Language.ENGLISH)
        else:
            # Unknown: do a light, safer pass (English-like symbol handling avoided except common)
            t = _normalize_numbers_and_dates(t, None)

        # Punctuation/spacing cleanup for smoother TTS
        t = _fix_spacing_and_punctuation(t)

        # Apply pronunciation map again at the end for final overrides (safe hook point)
        t = _apply_pronunciation_map(t, pronunciation_map)

        t = _fix_spacing_and_punctuation(t)
        return t.strip()
    except Exception:
        # Fallback-friendly: never block narration due to normalization issues.
        try:
            return _minimal_cleanup(text)
        except Exception:
            return str(text or "").strip()


def _coerce_language(language: Optional[Language | str]) -> Optional[Language]:
    if isinstance(language, Language):
        return language
    if not isinstance(language, str):
        return None
    s = language.strip().lower()
    if s in ("en", "eng", "english"):
        return Language.ENGLISH
    if s in ("hu", "hun", "hungarian", "magyar"):
        return Language.HUNGARIAN
    return None


def _apply_replacements(text: str, replacements: list[tuple[re.Pattern[str], str]]) -> str:
    for pat, repl in replacements:
        text = pat.sub(repl, text)
    return text


def _apply_pronunciation_map(text: str, pronunciation_map: Optional[Mapping[str, str]]) -> str:
    if not pronunciation_map:
        return text
    # Deterministic order: longer keys first to avoid partial shadowing.
    try:
        items = [(str(k), str(v)) for k, v in pronunciation_map.items() if str(k)]
    except Exception:
        return text
    for src, dst in sorted(items, key=lambda kv: len(kv[0]), reverse=True):
        if not src:
            continue
        # Literal replacement first; if not present, try case-insensitive word/phrase pattern for simple tokens.
        if src in text:
            text = text.replace(src, dst)
            continue
        try:
            pat = re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)", re.IGNORECASE)
            text = pat.sub(dst, text)
        except Exception:
            continue
    return text


def _normalize_numbers_and_dates(text: str, language: Optional[Language]) -> str:
    t = text

    # Normalize full dates first so generic numeric-range rules do not corrupt them.
    if language == Language.HUNGARIAN:
        t = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", r"\1. \2. \3", t)
        t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", r"\1. \2. \3", t)
        t = re.sub(r"\b(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\b", r"\1. \2. \3", t)
        t = re.sub(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\.?\b", r"\1. \2. \3", t)
    elif language == Language.ENGLISH:
        # Keep ISO-like dates intact; TTS engines usually handle them reasonably.
        t = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", r"\1-\2-\3", t)
    else:
        t = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", r"\1-\2-\3", t)

    # Normalize time ranges like 14:30-15:00 / 14:30–15:00 (en dash normalized earlier)
    if language == Language.HUNGARIAN:
        # If source already contains "között", avoid duplicating it.
        t = re.sub(
            r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b(?:\s+között\b)?",
            r"\1 és \2 között",
            t,
            flags=re.IGNORECASE,
        )
    elif language == Language.ENGLISH:
        t = re.sub(r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b", r"\1 to \2", t)
    else:
        t = re.sub(r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b", r"\1 to \2", t)

    # Numeric ranges: use words lightly by language to help articulation.
    # Avoid date/time-like fragments (ISO dates, dotted dates, times).
    range_pat = r"(?<!\d[-/.])(?<![:.])\b(\d{1,4})\s*-\s*(\d{1,4})\b(?!-\d)(?![:/.]\d)"
    if language == Language.HUNGARIAN:
        t = re.sub(range_pat, r"\1-től \2-ig", t)
    elif language == Language.ENGLISH:
        t = re.sub(range_pat, r"\1 to \2", t)

    # Currency symbols/units before/after numbers: light mapping.
    if language == Language.ENGLISH:
        t = re.sub(r"€\s*(\d)", r"\1 euros ", t)
        t = re.sub(r"\$\s*(\d)", r"\1 dollars ", t)
        t = re.sub(r"£\s*(\d)", r"\1 pounds ", t)
    elif language == Language.HUNGARIAN:
        t = re.sub(r"(\d)\s*Ft\b\.?", r"\1 forint", t)
        t = re.sub(r"(\d)\s*HUF\b\.?", r"\1 forint", t, flags=re.IGNORECASE)
        t = re.sub(r"€\s*(\d)", r"\1 euró ", t)
        t = re.sub(r"\$\s*(\d)", r"\1 dollár ", t)
        t = re.sub(r"£\s*(\d)", r"\1 font ", t)

    # Keep times like 14:30 intact; spacing cleanup handles surrounding punctuation separately.
    return t


def _fix_spacing_and_punctuation(text: str) -> str:
    t = text
    # Normalize whitespace
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    # Normalize spaced dashes introduced earlier, but keep them readable as pauses.
    t = re.sub(r"\s+-\s+", " - ", t)
    t = re.sub(r"(?:\s-\s){2,}", " - ", t)

    # Fix spaces before punctuation
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    # Ensure space after punctuation when followed by a letter/number (common OCR/artifact fix),
    # but do not break time-like tokens such as 14:30.
    t = re.sub(r"([,.;!?])(?=[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű0-9])", r"\1 ", t)
    t = re.sub(r":(?=[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű])", ": ", t)
    t = re.sub(r"(?<=\D):(?=\d)", ": ", t)

    # Remove duplicate punctuation spacing artifacts
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)

    # Ellipsis spacing
    t = re.sub(r"\s*\.\.\.\s*", "... ", t)

    # Clean accidental double periods (but preserve ellipsis)
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)

    # Clean spaces around dots in normalized Hungarian dates/numbers like "2026. 11. 18"
    t = re.sub(r"(\d)\.\s+(\d)", r"\1. \2", t)

    # Trim line whitespace
    lines = [ln.strip() for ln in t.split("\n")]
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _minimal_cleanup(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

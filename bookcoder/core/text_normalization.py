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

# Characters sometimes used (incorrectly) as accent marks after letters in ebooks/text extraction.
# Grouped so "hyphen-like" marks can be interpreted as Hungarian accents when they appear on letters.
_HU_HYPHEN_ACCENT_MARKS_NON_ASCII = (
    "\u00AD"  # soft hyphen
    "\u2010"  # hyphen
    "\u2011"  # non-breaking hyphen
    "\u2012"  # figure dash
    "\u2013"  # en dash
    "\u2014"  # em dash
    "\u2015"  # horizontal bar
    "\u2212"  # minus sign
    "\u2043"  # hyphen bullet
    "\u23AF"  # horizontal line extension
    "\u23E4"  # straightness
    "\u2500"  # box drawings light horizontal
    "\u2E3A"  # two-em dash
    "\u2E3B"  # three-em dash
    "\uFE58"  # small em dash
    "\uFE63"  # small hyphen-minus
    "\uFF0D"  # fullwidth hyphen-minus
)
# ASCII hyphen-minus is common in real hyphenated words, so only map it when Hungarian is explicitly targeted.
_HU_ASCII_HYPHEN_ACCENT_MARK = "-"
_HU_ACUTE_ACCENT_MARKS = (
    "\u00B4"  # acute accent
    "\u02CA"  # modifier letter acute accent
    "\u02B9"  # modifier letter prime
    "\u0374"  # greek numeral sign
    "\u0384"  # greek tonos
    "\u2032"  # prime
    "'"
    "\u2019"  # right single quotation mark
    "\u2018"  # left single quotation mark
    "\u02BC"  # modifier letter apostrophe
    "\uFF07"  # fullwidth apostrophe
)
_HU_DOUBLE_ACUTE_ACCENT_MARKS = (
    "\u02DD"  # double acute accent
    "\u02BA"  # modifier letter double prime
    "\u2033"  # double prime
    "\u02F6"  # modifier letter middle double acute accent
    '"'
    "\u201C"  # left double quotation mark
    "\u201D"  # right double quotation mark
    "\u201F"  # double high-reversed-9 quotation mark
    "\uFF02"  # fullwidth quotation mark
)
_HU_COMBINING_ACCENT_RE = re.compile(r"[\u0300-\u036f]")


def _replace_marked_vowels(text: str, base_chars: str, marks: str, replacement_map: Mapping[str, str]) -> str:
    if not text:
        return text
    cls = re.escape(marks)
    bases = re.escape(base_chars)

    def repl(m: re.Match[str]) -> str:
        ch = m.group(1)
        return replacement_map.get(ch, ch)

    # base letter followed by one or more accent-like marks
    return re.sub(rf"([{bases}])(?:[{cls}])+", repl, text)


def _maybe_repair_mojibake(text: str) -> str:
    if not text:
        return text
    markers = ("Ã", "Ä", "Å", "Æ", "Â", "Ă", "Ĺ", "Ľ", "Ň", "Ű", "Ţ", "Ë", "ď", "Â")
    if not any(m in text for m in markers):
        return text

    def score(s: str) -> int:
        sample = s[:20000]
        sc = 0
        sc += sum(sample.count(ch) for ch in "áéíóöőúüűÁÉÍÓÖŐÚÜŰ") * 4
        for marker in (
            "Ã©", "Ã¡", "Ã­", "Ã³", "Ãº", "Ã¶", "Ã¼", "Ãµ", "Ã»", "Ã‰", "Ã", "Ã", "Ã“", "Ãš", "Ã–", "Ãœ", "Ã•", "Ã›",
            "Å‘", "Å±", "Å", "Å°",
            "Ä‘", "Ä", "Â",
            "Ă©", "Ăˇ", "Ă­", "Ăł", "Ăş", "Ă¶", "Ă¼", "Ăµ", "Ă»", "Ă‰", "Ă", "Ă“", "Ăš", "Ă–", "Ăœ", "Ă•", "Ă›",
            "Ĺ‘", "Ĺ±", "Ĺ", "Ĺ°",
            "ŕ", "č", "ť", "Ľ", "ž", "ş", "˘", "Š", "‚", "„", "…", "’", "“", "”",
        ):
            sc -= sample.count(marker) * 3
        sc -= sample.count("\ufffd") * 10
        return sc

    candidates = [text]
    for enc in ("latin-1", "cp1252", "cp1250", "iso-8859-2"):
        try:
            repaired = text.encode(enc, errors="strict").decode("utf-8", errors="strict")
            candidates.append(repaired)
        except Exception:
            continue
        try:
            repaired = text.encode(enc, errors="ignore").decode("utf-8", errors="ignore")
            candidates.append(repaired)
        except Exception:
            continue
    try:
        best = max(candidates, key=score)
        if score(best) > score(text):
            return best
    except Exception:
        pass
    return text


def _fix_hungarian_codepage_confusables(text: str, language: Optional[Language] = None) -> str:
    """Fix Hungarian letters corrupted by common single-byte codepage mis-decoding.

    Example: Central European text (CP1250/ISO-8859-2) mis-decoded as Western
    (CP1252/ISO-8859-1) turns ő/Ő/ű/Ű into õ/Õ/û/Û. In UTF-8 ebooks this can
    appear as already-decoded Unicode characters, so byte re-decoding alone is not
    enough; map these confusables to proper Hungarian letters.
    """
    if not text:
        return text
    t = str(text)

    # High-confidence confusable mappings (Hungarian does not use õ/û).
    high_conf = str.maketrans({
        "õ": "ő", "Õ": "Ő",
        "û": "ű", "Û": "Ű",
    })
    # Slightly contextual mappings (accent/variant confusions seen in some texts).
    hu_context = str.maketrans({
        "ò": "ó", "Ò": "Ó",
    })

    def looks_hungarian(s: str) -> bool:
        sample = s[:4000]
        if any(ch in sample for ch in "áéíóöőúüűÁÉÍÓÖŐÚÜŰ"):
            return True
        # common Hungarian words/fragments
        if re.search(r"\b(és|hogy|nem|egy|azt?|ezt?|van|volt|lesz|meg|már|még|szét|tíz|tizennégy|autó|karátos)\b", sample, re.IGNORECASE):
            return True
        return False

    def hu_score(s: str) -> int:
        sample = s[:20000]
        sc = 0
        sc += sum(sample.count(ch) for ch in "áéíóöőúüűÁÉÍÓÖŐÚÜŰ") * 3
        sc += sample.count("ő") * 2 + sample.count("ű") * 2 + sample.count("Ő") * 2 + sample.count("Ű") * 2
        sc -= (sample.count("õ") + sample.count("û") + sample.count("Õ") + sample.count("Û")) * 4
        sc -= sample.count("\ufffd") * 10
        return sc

    is_hu = language == Language.HUNGARIAN or looks_hungarian(t)

    # Apply direct mappings first.
    if is_hu or any(ch in t for ch in "õÕûÛ"):
        # õ/û are strong indicators of ő/ű corruption in HU texts; safe enough to fix broadly.
        if is_hu or looks_hungarian(t.translate(high_conf)):
            t = t.translate(high_conf)
        else:
            # even without strong HU signal, these chars are very likely corrupted ő/ű in ebooks
            t = t.translate(high_conf)
    if language == Language.HUNGARIAN:
        t = t.translate(hu_context)

    # Try codepage round-trip repairs (broad "every codepage" style mapping for common cases).
    # Typical case: bytes meant as CP1250/ISO-8859-2 decoded as CP1252/ISO-8859-1 -> õ/û.
    # Try multiple encoding pairs and keep the result that best restores Hungarian letters.
    confusable_chars = "õÕûÛ"
    suspicious_hu_chars = "õÕûÛãÃ"  # chars that often indicate wrong single-byte decode for HU text
    bad_conf_count = sum(t.count(ch) for ch in confusable_chars)
    if bad_conf_count > 0 or (is_hu and any(ch in t for ch in "òÒôÔ")) or any(ch in t for ch in suspicious_hu_chars):
        central = ["cp1250", "iso-8859-2", "cp852", "iso-8859-16", "mac_latin2"]
        western = ["cp1252", "latin-1", "iso-8859-15", "cp850", "mac_roman"]
        # Also try interpreting as UTF-8 bytes carried through single-byte encodings (extra safety)
        utf8_bridge = ["cp1252", "latin-1", "cp1250", "iso-8859-2"]
        pairs: list[tuple[str, str]] = []
        for a in central:
            for b in western:
                pairs.append((b, a))  # Western-decoded but actually Central
                pairs.append((a, b))  # Central-decoded but actually Western
        for a in central:
            for b in central:
                if a != b:
                    pairs.append((a, b))
        # de-duplicate while preserving order
        seen_pairs = set()
        uniq_pairs = []
        for p in pairs:
            if p not in seen_pairs:
                seen_pairs.add(p)
                uniq_pairs.append(p)
        candidates = [t]
        for enc_from, enc_to in uniq_pairs:
            try:
                candidates.append(t.encode(enc_from, errors="strict").decode(enc_to, errors="strict"))
            except Exception:
                continue
        # UTF-8 bridge candidates (e.g. text contains UTF-8 bytes mis-decoded as single-byte)
        for enc in utf8_bridge:
            try:
                candidates.append(t.encode(enc, errors="strict").decode("utf-8", errors="strict"))
            except Exception:
                continue

        def conf_count(s: str) -> int:
            return sum(s.count(ch) for ch in confusable_chars)

        try:
            base_conf = conf_count(t)
            base_score = hu_score(t)
            best = t
            best_conf = base_conf
            best_score = base_score
            for cand in candidates[1:]:
                c_conf = conf_count(cand)
                c_score = hu_score(cand)
                accept = False
                # Primary goal: reduce õ/û/Õ/Û confusables
                if c_conf < base_conf:
                    if c_conf < best_conf or (c_conf == best_conf and c_score > best_score):
                        accept = True
                # Secondary: no confusable regression and clearly better HU score (e.g. UTF-8 bridge repair)
                elif c_conf == base_conf and c_score >= base_score + 6:
                    if c_score > best_score:
                        accept = True
                if accept:
                    best = cand
                    best_conf = c_conf
                    best_score = c_score
            if best is not t:
                t = best
                is_hu = is_hu or looks_hungarian(t)
        except Exception:
            pass

    # Re-apply targeted mappings after round-trip selection
    if language == Language.HUNGARIAN or is_hu or looks_hungarian(t):
        t = t.translate(hu_context)
    if language == Language.HUNGARIAN or is_hu or any(ch in t for ch in "õÕûÛ") or looks_hungarian(t):
        t = t.translate(high_conf)

    # Final targeted pass (in case round-trips were not possible for whole string)
    if is_hu or any(ch in t for ch in "õÕûÛ"):
        t = t.translate(high_conf)
    if language == Language.HUNGARIAN:
        t = t.translate(hu_context)

    return t


def normalize_hungarian_text_marks(text: str, language: Optional[Language | str] = None) -> str:
    """Normalize Hungarian accented characters represented with decomposed or incorrect accent marks.

    Handles NFC composition and common cases where accents are represented as spacing/typographic marks
    (including various hyphen/dash-like characters) placed after the base letter.
    """
    if not text:
        return ""
    t = str(text)
    try:
        t = _maybe_repair_mojibake(t)
    except Exception:
        pass
    try:
        # Compose decomposed accents first (e.g. e + combining acute -> é)
        t = unicodedata.normalize("NFC", t)
    except Exception:
        pass

    lang = _coerce_language(language)

    # Spacing accent-mark characters observed in malformed Hungarian texts/ebooks.
    # - acute accent marks (´ etc.) typically represent á é í ó ú
    # - double acute marks (˝ etc.) typically represent ő ű on o/u
    # - hyphen/dash-like marks can represent accents on letters depending on the source ("kind" matters)
    acute_map = {
        "a": "á", "A": "Á",
        "e": "é", "E": "É",
        "i": "í", "I": "Í",
        "o": "ó", "O": "Ó",
        "u": "ú", "U": "Ú",
    }
    double_acute_map_ou = {
        "o": "ő", "O": "Ő",
        "u": "ű", "U": "Ű",
    }
    # Some malformed sources use a double-acute-like mark after a/e/i; map to the closest Hungarian acute form.
    double_acute_fallback_aei = {
        "a": "á", "A": "Á",
        "e": "é", "E": "É",
        "i": "í", "I": "Í",
    }

    # Spacing double-acute marks -> ő/ű (and best-effort for a/e/i if present).
    t = _replace_marked_vowels(t, "oOuU", _HU_DOUBLE_ACUTE_ACCENT_MARKS, double_acute_map_ou)
    t = _replace_marked_vowels(t, "aAeEiI", _HU_DOUBLE_ACUTE_ACCENT_MARKS, double_acute_fallback_aei)
    # Spacing acute marks -> áéíóú.
    t = _replace_marked_vowels(t, "aAeEiIoOuU", _HU_ACUTE_ACCENT_MARKS, acute_map)

    # "Hyphen on the letter" variants seen in some malformed texts/EPUB/MOBI extractions.
    # Treat hyphen/dash-like marks on vowels as accent marks. For o/u this maps to ő/ű (double acute),
    # while explicit acute marks (´) above map to ó/ú when that "kind" is used.
    if lang == Language.HUNGARIAN or lang is None:
        hyphen_marks = _HU_HYPHEN_ACCENT_MARKS_NON_ASCII
        if lang == Language.HUNGARIAN:
            hyphen_marks = _HU_HYPHEN_ACCENT_MARKS_NON_ASCII + _HU_ASCII_HYPHEN_ACCENT_MARK
        t = _replace_marked_vowels(t, "aA", hyphen_marks, {"a": "á", "A": "Á"})
        t = _replace_marked_vowels(t, "eE", hyphen_marks, {"e": "é", "E": "É"})
        t = _replace_marked_vowels(t, "iI", hyphen_marks, {"i": "í", "I": "Í"})
        t = _replace_marked_vowels(t, "oO", hyphen_marks, {"o": "ő", "O": "Ő"})
        t = _replace_marked_vowels(t, "uU", hyphen_marks, {"u": "ű", "U": "Ű"})

    try:
        t = _fix_hungarian_codepage_confusables(t, lang)
    except Exception:
        pass

    try:
        t = unicodedata.normalize("NFC", t)
    except Exception:
        pass
    return t

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
        try:
            t = _maybe_repair_mojibake(t)
        except Exception:
            pass
        # Convert malformed Hungarian accent marks before NFKC, because NFKC can
        # decompose spacing accent modifiers (e.g. U+02DD) in ways that break mapping.
        t = normalize_hungarian_text_marks(t, lang)
        t = unicodedata.normalize("NFKC", t)
        t = normalize_hungarian_text_marks(t, lang)
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
    t = str(text or "")
    try:
        t = _maybe_repair_mojibake(t)
    except Exception:
        pass
    try:
        t = normalize_hungarian_text_marks(t, None)
    except Exception:
        pass
    t = unicodedata.normalize("NFKC", t)
    try:
        t = normalize_hungarian_text_marks(t, None)
    except Exception:
        pass
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

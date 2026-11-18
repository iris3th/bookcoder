from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from .models import Language

# Common function words for lightweight heuristic fallback
_EN_COMMON = {
    "the", "and", "to", "of", "in", "that", "is", "it", "was", "for", "on", "with", "as", "he", "she",
    "at", "by", "his", "her", "they", "this", "from", "or", "had", "but", "not", "you", "are", "were",
}
_HU_COMMON = {
    "a", "az", "és", "hogy", "nem", "is", "volt", "egy", "meg", "de", "csak", "már", "még", "mint", "ha",
    "én", "te", "ő", "mi", "ti", "ők", "ezt", "azt", "aki", "ami", "vagy", "lesz", "van", "volt",
    "kell", "lehet", "mert", "nagyon", "itt", "ott", "el", "fel", "ki", "be", "szét", "össze",
}

_HU_CHARS = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
_HU_DISTINCTIVE = set("őűŐŰ")


def detect_language(text: str) -> tuple[Language, float]:
    """Detect whether text is English or Hungarian.

    Returns (language, confidence) where confidence is in [0, 1].
    Examines the actual text content.
    """
    sample = _sample_text(text)
    if not sample or len(sample.strip()) < 20:
        # Not enough info; default to English with low confidence
        return Language.ENGLISH, 0.0

    # Try high-quality detectors if available
    for detector in (_detect_with_langdetect, _detect_with_lingua):
        try:
            result = detector(sample)
            if result is not None:
                lang, conf = result
                if lang in (Language.ENGLISH, Language.HUNGARIAN):
                    return lang, conf
                # If detector says something else, fall through to heuristic constrained to en/hu
        except Exception:
            continue

    return _detect_heuristic(sample)


def detect_language_for_book(chapters_text: Iterable[str], max_chars: int = 20000) -> tuple[Language, float]:
    collected = []
    total = 0
    for t in chapters_text:
        if not t:
            continue
        collected.append(t)
        total += len(t)
        if total >= max_chars:
            break
    joined = "\n".join(collected)
    if len(joined) > max_chars:
        # take from beginning, middle, end for better coverage
        third = max_chars // 3
        joined = joined[:third] + "\n" + joined[len(joined)//2 - third//2: len(joined)//2 + third//2] + "\n" + joined[-third:]
    return detect_language(joined)


def _sample_text(text: str, max_chars: int = 15000) -> str:
    if len(text) <= max_chars:
        return text
    # sample head/mid/tail
    part = max_chars // 3
    mid = len(text) // 2
    return text[:part] + "\n" + text[mid - part // 2: mid + part // 2] + "\n" + text[-part:]


def _detect_with_langdetect(sample: str):
    try:
        from langdetect import DetectorFactory, detect_langs  # type: ignore

        DetectorFactory.seed = 0
        langs = detect_langs(sample)
        if not langs:
            return None
        # find en/hu probabilities
        en_p = 0.0
        hu_p = 0.0
        for lp in langs:
            if lp.lang == "en":
                en_p = float(lp.prob)
            elif lp.lang == "hu":
                hu_p = float(lp.prob)
        if hu_p == 0.0 and en_p == 0.0:
            # map others? no, but return best of these two as low-confidence
            top = langs[0]
            if top.lang.startswith("en"):
                return Language.ENGLISH, float(top.prob)
            if top.lang.startswith("hu"):
                return Language.HUNGARIAN, float(top.prob)
            # If clearly not en/hu, choose heuristic result by returning None to let fallback constrain
            return None
        if hu_p >= en_p:
            return Language.HUNGARIAN, hu_p
        return Language.ENGLISH, en_p
    except Exception:
        return None


def _detect_with_lingua(sample: str):
    try:
        from lingua import Language as LL, LanguageDetectorBuilder  # type: ignore

        detector = LanguageDetectorBuilder.from_languages(LL.ENGLISH, LL.HUNGARIAN).build()
        conf_values = detector.compute_language_confidence_values(sample)
        if not conf_values:
            return None
        best = conf_values[0]
        lang = Language.HUNGARIAN if best.language == LL.HUNGARIAN else Language.ENGLISH
        return lang, float(best.value)
    except Exception:
        return None


def _detect_heuristic(sample: str) -> tuple[Language, float]:
    # Character-based signals
    hu_char_count = sum(1 for c in sample if c in _HU_CHARS)
    hu_distinctive = sum(1 for c in sample if c in _HU_DISTINCTIVE)
    alpha_count = sum(1 for c in sample if c.isalpha()) or 1
    hu_char_ratio = hu_char_count / alpha_count
    hu_distinctive_ratio = hu_distinctive / alpha_count

    # Word-based signals
    words = re.findall(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]+", sample.lower())
    total_words = len(words) or 1
    counts = Counter(words)
    en_hits = sum(counts[w] for w in _EN_COMMON)
    hu_hits = sum(counts[w] for w in _HU_COMMON)
    en_word_ratio = en_hits / total_words
    hu_word_ratio = hu_hits / total_words

    hu_score = 0.0
    en_score = 0.0

    # Strong signal: distinctive Hungarian letters ő/ű almost never in English
    if hu_distinctive_ratio > 0.002:
        hu_score += 3.0 + min(hu_distinctive_ratio * 500, 3.0)
    hu_score += min(hu_char_ratio * 20.0, 3.0)
    hu_score += min(hu_word_ratio * 25.0, 3.0)

    en_score += min(en_word_ratio * 25.0, 3.5)
    # Penalize English a bit if many Hungarian accented chars present
    if hu_char_ratio > 0.03:
        en_score -= 1.0

    total = hu_score + en_score
    if total <= 0:
        return Language.ENGLISH, 0.4
    if hu_score >= en_score:
        conf = 0.5 + 0.5 * (hu_score / total)
        # Boost if distinctive chars present
        if hu_distinctive > 0:
            conf = max(conf, 0.85)
        return Language.HUNGARIAN, min(conf, 0.99)
    else:
        conf = 0.5 + 0.5 * (en_score / total)
        if hu_distinctive == 0 and hu_char_ratio < 0.01:
            conf = max(conf, 0.7)
        return Language.ENGLISH, min(conf, 0.99)

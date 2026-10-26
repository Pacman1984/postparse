"""Generic text helpers: hashtag and mention extraction.

Both extractors are Unicode-aware, return lowercase names without the leading
``#``/``@``, drop duplicates and keep the order of first appearance. URLs and
e-mail addresses are removed before scanning, so URL fragments
(``https://x.org/page#top``) and addresses (``me@example.org``) never yield tags.

Example:
    >>> extract_hashtags("Pasta #Rezept #Pasta #rezept! https://x.org/#top")
    ['rezept', 'pasta']
    >>> extract_mentions("Danke @Koch.Profi, mail me@example.org")
    ['koch.profi']
"""

from __future__ import annotations

import re
import unicodedata

from postparse.core.urls import extract_urls

__all__ = ["extract_hashtags", "extract_mentions"]

# Word characters plus combining marks (accents written as separate code points,
# Indic vowel signs, ...) and zero-width joiners used inside words.
_MARK_RANGES: tuple[tuple[int, int], ...] = (
    (0x0300, 0x036F),  # combining diacritics
    (0x0483, 0x0489),  # Cyrillic
    (0x0591, 0x05BD),  # Hebrew
    (0x0610, 0x061A),  # Arabic
    (0x064B, 0x065F),
    (0x0900, 0x0903),  # Devanagari
    (0x093A, 0x094F),
    (0x0E31, 0x0E3A),  # Thai
    (0x0E47, 0x0E4E),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x200C, 0x200D),  # zero-width (non-)joiner
    (0x20D0, 0x20FF),
    (0xFE20, 0xFE2F),
)
_WORD = "[\\w" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _MARK_RANGES) + "]"
_JOINERS = "".join(chr(cp) for cp in (0x200C, 0x200D))

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
_WWW_RE = re.compile(r"\bwww\.[^\s<>\"']+", re.IGNORECASE)

# A tag must not be glued to a preceding word, another sigil, '&' (HTML
# entities such as '&#39;') or '/' (paths).
_HASHTAG_RE = re.compile(rf"(?<![\w&#@/])#({_WORD}+)", re.UNICODE)
# Usernames may contain inner dots (Instagram) but not end with one.
_MENTION_RE = re.compile(rf"(?<![\w&#@/.+-])@({_WORD}+(?:\.{_WORD}+)*)", re.UNICODE)

_MAX_TAG_LENGTH = 100


def _scrub(text: str) -> str:
    """Return NFC text with URLs and e-mail addresses blanked out."""
    cleaned = unicodedata.normalize("NFC", text)
    for url in extract_urls(cleaned):
        cleaned = cleaned.replace(url, " ")
    cleaned = _WWW_RE.sub(" ", cleaned)
    return _EMAIL_RE.sub(" ", cleaned)


def _collect(pattern: re.Pattern[str], text: str | None, *, require_letter: bool) -> list[str]:
    """Run ``pattern`` over scrubbed text and return normalized unique names."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in pattern.finditer(_scrub(text)):
        name = match.group(1).strip(_JOINERS).lower()
        if not name or len(name) > _MAX_TAG_LENGTH:
            continue
        if require_letter and not any(ch.isalpha() for ch in name):
            continue
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def extract_hashtags(text: str | None) -> list[str]:
    """Extract hashtags from free text.

    Purely numeric tags (``#1``) are ignored, as on Instagram.

    Args:
        text: Text to scan; ``None`` yields an empty list.

    Returns:
        Lowercase hashtag names without ``#`` in order of first appearance.
    """
    return _collect(_HASHTAG_RE, text, require_letter=True)


def extract_mentions(text: str | None) -> list[str]:
    """Extract ``@username`` mentions from free text.

    E-mail addresses and ``@`` inside words are ignored; a trailing dot ends the
    name (``"@chef."`` -> ``chef``).

    Args:
        text: Text to scan; ``None`` yields an empty list.

    Returns:
        Lowercase usernames without ``@`` in order of first appearance.
    """
    return _collect(_MENTION_RE, text, require_letter=False)

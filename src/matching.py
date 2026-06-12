"""Forgiving text matching shared by the live-ad-group diff and ManualProvider.

Normalization: lowercase, strip punctuation, drop intent words
("stock", "shares", "buy", ...) so that e.g. "buy ASML shares" resolves to ASML.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

STRIP_WORDS = {"stock", "stocks", "share", "shares", "buy", "invest", "investing"}

FUZZY_RATIO = 0.85


def normalize(text: str) -> str:
    """Lowercase, de-accent, strip punctuation and intent words."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9&\s.-]", " ", text)
    tokens = [t for t in re.split(r"\s+", text) if t and t not in STRIP_WORDS]
    return " ".join(tokens)


def contains_word(haystack: str, needle: str) -> bool:
    """True if ``needle`` appears in ``haystack`` on word boundaries."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def fuzzy_match(a: str, b: str, ratio: float = FUZZY_RATIO) -> bool:
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= ratio

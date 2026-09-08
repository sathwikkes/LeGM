"""Player name normalization for cross-source matching.

normalize_name("Nikola Jokić")       -> "nikola jokic"
normalize_name("Jaren Jackson Jr.")   -> "jaren jackson"
normalize_name("Robert Williams III") -> "robert williams"
normalize_name("De'Aaron Fox")        -> "deaaron fox"
normalize_name("Shai Gilgeous-Alexander") -> "shai gilgeous alexander"
"""

from __future__ import annotations

import re
import unicodedata

SUFFIXES: frozenset[str] = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

_APOSTROPHES = re.compile(r"[’'`‘]")
_DROP = re.compile(r"[.]")
_PUNCT_TO_SPACE = re.compile(r"[-‐-―/,]")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Lowercase, ASCII, no punctuation, no generational suffix, single-spaced."""
    text = strip_accents(name).lower()
    text = _APOSTROPHES.sub("", text)  # De'Aaron -> deaaron (join, don't split)
    text = _DROP.sub("", text)  # P.J. -> pj, Jr. -> jr
    text = _PUNCT_TO_SPACE.sub(" ", text)  # hyphens/slashes/commas -> space
    text = _NON_ALNUM.sub("", text)
    tokens = [t for t in _SPACES.split(text.strip()) if t]
    # Drop trailing suffix tokens (handles "jr", "iii", and "jr iii").
    while len(tokens) > 1 and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)

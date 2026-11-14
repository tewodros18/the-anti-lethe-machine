"""Cosine distance over word frequencies. The default method, zero dependencies."""

from __future__ import annotations

import math
import re
from collections import Counter

from ..registry import pairwise

#: Words are runs of lowercase letters, digits and apostrophes. Everything else
#: is a separator, so punctuation and casing never register as drift.
TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase the text and split it into word tokens."""
    return TOKEN_RE.findall(text.lower())


@pairwise(
    "cosine_bow",
    version="1.0.0",
    description="Cosine distance over word-frequency vectors. No dependencies.",
)
def cosine_bow(prev_text: str, next_text: str) -> float:
    """Return ``1 - cosine`` over the two texts' word-frequency vectors.

    Cosine over word frequencies cannot distinguish a reversal from a rewording.
    "X is safe" and "X is not safe" score as nearly identical. It is the default
    because any reader can verify a number by hand, which an embedding distance does
    not permit. It is reported alongside the stance and refusal markers for that reason.
    """
    left = Counter(tokenize(prev_text))
    right = Counter(tokenize(next_text))

    # Two empty texts are identical; one empty text is maximally distant.
    if not left and not right:
        return 0.0
    if not left or not right:
        return 1.0

    shared = left.keys() & right.keys()
    dot = sum(left[token] * right[token] for token in shared)
    if dot == 0:
        return 1.0

    norm_left = math.sqrt(sum(count * count for count in left.values()))
    norm_right = math.sqrt(sum(count * count for count in right.values()))
    cosine = dot / (norm_left * norm_right)

    # Clamp: floating point can push an identical pair a hair past 1.0.
    return float(min(1.0, max(0.0, 1.0 - cosine)))

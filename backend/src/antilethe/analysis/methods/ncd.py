"""Normalized Compression Distance. No dependencies.

An information-theoretic distance that needs no model and no vocabulary. If
two texts share structure, a compressor exploits it: compressing them together
costs little more than compressing the longer one alone. If they share nothing,
the concatenation costs as much as both. The ratio is the distance.

    NCD(x, y) = ( C(xy) - min(C(x), C(y)) ) / max(C(x), C(y))

where ``C`` is the compressed length in bytes (Cilibrasi & Vitányi, "Clustering
by compression", IEEE Trans. Inf. Theory 51(4), 2005).

What it sees that word frequencies miss: phrase order, repeated structure, and
shared long spans. Reordering the same sentences scores as a change here and as
nothing under ``cosine_bow``. What it still misses: negation. "X is safe" and
"X is not safe" compress together almost perfectly.

zlib is used rather than lzma because answers are capped at a few thousand
characters, well inside zlib's 32 KB window, and it is an order of magnitude
faster. The approximation to Kolmogorov complexity is coarse either way; the
value of NCD is that it is parameter-free and reproducible to the byte.
"""

from __future__ import annotations

import zlib

from ..registry import pairwise

#: Maximum compression effort. Slower, but the ranking of distances depends on
#: how well the compressor finds shared structure, so it is not worth saving.
_LEVEL = 9


def _compressed_size(data: bytes) -> int:
    """Bytes after zlib compression, header included."""
    return len(zlib.compress(data, _LEVEL))


@pairwise(
    "ncd",
    version="1.0.0",
    description=(
        "Normalized compression distance (zlib). Parameter-free; sees shared structure"
        " and phrase order that word frequencies miss."
    ),
)
def ncd(prev_text: str, next_text: str) -> float:
    """Normalized compression distance between the two texts, clamped to [0, 1].

    Clamping matters: compressor overhead can push NCD a few hundredths past 1
    or below 0 for very short inputs, and a distance outside [0, 1] would break
    the contract every other method keeps.
    """
    if not prev_text and not next_text:
        return 0.0
    if not prev_text or not next_text:
        return 1.0

    x = prev_text.encode("utf-8")
    y = next_text.encode("utf-8")
    cx = _compressed_size(x)
    cy = _compressed_size(y)
    cxy = _compressed_size(x + y)

    denominator = max(cx, cy)
    if denominator == 0:
        return 0.0
    value = (cxy - min(cx, cy)) / denominator
    return float(min(1.0, max(0.0, value)))

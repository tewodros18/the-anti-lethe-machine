"""Jaccard distance over word trigram shingles. No dependencies.

The standard near-duplicate measure from information retrieval (Broder,
"On the resemblance and containment of documents", 1997). Each text becomes
the set of its overlapping three-word sequences; the distance is one minus the
fraction of shingles the two sets share.

Where ``cosine_bow`` treats "safe is coffee" and "coffee is safe" as identical,
trigram shingles do not: the phrases differ, so the shingle sets differ. It is
still a surface measure. A paraphrase that reuses no three-word run scores as
a complete rewrite, and a reversal that keeps most phrases ("is safe" vs
"is not safe") scores as a small edit.

Reported alongside ``cosine_bow`` because the gap between the two is itself
informative: a large Jaccard distance with a small cosine distance means the
same words in a new order, which is exactly the rewording-without-reversal
case that neither can resolve on its own.
"""

from __future__ import annotations

from ..registry import pairwise
from .cosine_bow import tokenize

#: Shingle width in words. Three is the conventional choice: long enough that
#: a shared shingle implies a shared phrase, short enough that light edits do
#: not destroy every match.
N = 3


def shingles(text: str, n: int = N) -> set[tuple[str, ...]]:
    """The set of overlapping ``n``-word sequences in ``text``.

    A text shorter than ``n`` words yields its single, shorter tuple, so two
    short answers can still be compared rather than both reading as empty.
    """
    tokens = tokenize(text)
    if not tokens:
        return set()
    if len(tokens) < n:
        return {tuple(tokens)}
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


@pairwise(
    "jaccard_ngram",
    version="1.0.0",
    description=(
        "Jaccard distance over word-trigram shingles. Sees word order and phrase reuse;"
        " a surface measure, like cosine_bow."
    ),
)
def jaccard_ngram(prev_text: str, next_text: str) -> float:
    """One minus the intersection-over-union of trigram shingles, in [0, 1]."""
    a = shingles(prev_text)
    b = shingles(next_text)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return float(1.0 - len(a & b) / union)

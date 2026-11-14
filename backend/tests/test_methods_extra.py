"""The two new dependency-free methods, the prepare hook, and the bootstrap."""

from __future__ import annotations

import pytest

from antilethe.analysis import registry
from antilethe.analysis.bootstrap import MIN_N, ratio_interval
from antilethe.analysis.methods.jaccard_ngram import jaccard_ngram, shingles
from antilethe.analysis.methods.ncd import ncd

A = (
    "Coffee appears broadly safe for most adults in moderate amounts, and may even carry"
    " some benefits for heart health according to several large cohort studies."
)
B = (
    "Coffee appears broadly safe for most adults in moderate amounts, and may even carry"
    " some benefits for heart health according to several large cohort studies, though"
    " individual tolerance varies."
)
C = (
    "Quantum error correction encodes logical qubits across many physical qubits so that"
    " errors can be detected and reversed without measuring the protected state."
)


# ---------------------------------------------------------------------------
# ncd
# ---------------------------------------------------------------------------


def test_ncd_identical_is_near_zero() -> None:
    assert ncd(A, A) < 0.1


def test_ncd_unrelated_is_high() -> None:
    """Short English texts share letters and function words, so a compressor
    always finds something; unrelated prose saturates around 0.7, not 1.0."""
    assert ncd(A, C) > 0.6
    assert ncd(A, C) > ncd(A, B) + 0.3


def test_ncd_small_edit_is_small() -> None:
    assert ncd(A, B) < ncd(A, C)
    assert ncd(A, B) < 0.4


def test_ncd_is_bounded_and_symmetric() -> None:
    for x, y in [("", ""), ("a", ""), (A, B), (A, C), ("x" * 500, "y" * 500)]:
        d = ncd(x, y)
        assert 0.0 <= d <= 1.0
        assert d == pytest.approx(ncd(y, x), abs=0.05)


def test_ncd_empty_handling() -> None:
    assert ncd("", "") == 0.0
    assert ncd("", A) == 1.0


def test_ncd_sees_reordering_that_bag_of_words_cannot() -> None:
    """Sentence order is structure; a compressor notices, word counts do not."""
    from antilethe.analysis.methods.cosine_bow import cosine_bow

    s1 = "The sky is blue today. The grass is green here. The sea is calm now."
    s2 = "The sea is calm now. The sky is blue today. The grass is green here."
    assert cosine_bow(s1, s2) == 0.0
    assert ncd(s1, s2) > 0.0


def test_ncd_is_blind_to_negation_as_documented() -> None:
    assert ncd("coffee is safe", "coffee is not safe") < 0.5


# ---------------------------------------------------------------------------
# jaccard_ngram
# ---------------------------------------------------------------------------


def test_shingles_are_overlapping_trigrams() -> None:
    assert shingles("a b c d") == {("a", "b", "c"), ("b", "c", "d")}


def test_shingles_of_a_short_text_is_its_whole_tuple() -> None:
    assert shingles("a b") == {("a", "b")}
    assert shingles("") == set()


def test_jaccard_identity_and_disjoint() -> None:
    assert jaccard_ngram(A, A) == 0.0
    assert jaccard_ngram(A, C) == 1.0
    assert jaccard_ngram("", "") == 0.0
    assert jaccard_ngram("", A) == 1.0


def test_jaccard_sees_word_order() -> None:
    """The documented difference from cosine_bow."""
    from antilethe.analysis.methods.cosine_bow import cosine_bow

    assert cosine_bow("safe is coffee always", "coffee is always safe") == 0.0
    assert jaccard_ngram("safe is coffee always", "coffee is always safe") > 0.5


def test_jaccard_small_edit_is_small() -> None:
    assert jaccard_ngram(A, B) < 0.3


def test_jaccard_bounded_symmetric() -> None:
    for x, y in [(A, B), (A, C), ("one two", "two one three")]:
        d = jaccard_ngram(x, y)
        assert 0.0 <= d <= 1.0
        assert d == jaccard_ngram(y, x)


# ---------------------------------------------------------------------------
# prepare hook
# ---------------------------------------------------------------------------


def test_prepare_hook_is_registered_and_retrievable() -> None:
    token = registry._snapshot()
    seen: list[list[str]] = []
    try:

        def warm(texts: list[str]) -> None:
            seen.append(list(texts))

        @registry.pairwise("temp_prepared", version="0.1.0", prepare=warm)
        def temp_prepared(a: str, b: str) -> float:
            return 0.0

        hook = registry.get_prepare("temp_prepared")
        assert hook is not None
        hook(["x", "y"])
        assert seen == [["x", "y"]]
        assert registry.get_prepare("cosine_bow") is None
    finally:
        registry._restore(token)


def test_prepare_hook_runs_once_per_question_before_comparisons(
    populated: object, settings: object
) -> None:
    """The pipeline must call prepare with every text in the series, first."""
    import sqlite3

    from antilethe.analysis import pipeline
    from antilethe.config import Settings

    assert isinstance(populated, sqlite3.Connection)
    assert isinstance(settings, Settings)

    token = registry._snapshot()
    calls: list[int] = []
    compared_before_prepare: list[bool] = []
    try:

        def warm(texts: list[str]) -> None:
            calls.append(len(texts))

        @registry.pairwise("temp_batched", version="0.1.0", prepare=warm)
        def temp_batched(a: str, b: str) -> float:
            compared_before_prepare.append(len(calls) == 0)
            return 0.0

        pipeline.analyze(populated, ["temp_batched"], settings=settings)
    finally:
        registry._restore(token)

    # Two questions in the fixture: one prepare call each, with every text.
    assert len(calls) == 2
    assert all(n > 0 for n in calls)
    assert not any(compared_before_prepare)


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------


def test_interval_brackets_the_point_ratio() -> None:
    import random

    rng = random.Random(0)
    num = [0.25 + rng.gauss(0, 0.05) for _ in range(300)]
    den = [0.20 + rng.gauss(0, 0.05) for _ in range(300)]
    point = (sum(num) / len(num)) / (sum(den) / len(den))
    found = ratio_interval(num, den)
    assert found is not None
    low, high = found
    assert low < point < high
    assert high - low < 0.4


def test_interval_is_deterministic() -> None:
    num = [0.3] * 50 + [0.2] * 50
    den = [0.2] * 50 + [0.1] * 50
    assert ratio_interval(num, den) == ratio_interval(num, den)


def test_interval_refuses_tiny_samples() -> None:
    assert ratio_interval([0.3] * (MIN_N - 1), [0.2] * 100) is None
    assert ratio_interval([0.3] * 100, [0.2] * (MIN_N - 1)) is None


def test_interval_widens_with_fewer_observations() -> None:
    import random

    rng = random.Random(1)
    big_num = [0.25 + rng.gauss(0, 0.05) for _ in range(1000)]
    big_den = [0.20 + rng.gauss(0, 0.05) for _ in range(1000)]
    small = ratio_interval(big_num[:20], big_den[:20])
    large = ratio_interval(big_num, big_den)
    assert small is not None and large is not None
    assert (small[1] - small[0]) > (large[1] - large[0])

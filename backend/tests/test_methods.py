"""The registry and the two dependency-free methods."""

from __future__ import annotations

import pytest

from antilethe.analysis import registry
from antilethe.analysis.methods.cosine_bow import cosine_bow, tokenize
from antilethe.analysis.methods.markers import HEDGE_RATE_CAP, STANCE_PREFIX_CHARS, markers

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_the_four_shipped_methods_are_registered() -> None:
    names = {spec.name for spec in registry.all_specs()}
    assert {"cosine_bow", "markers", "embedding", "nli"} <= names


def test_dependency_free_methods_are_always_available() -> None:
    available = {spec.name for spec in registry.available()}
    assert {"cosine_bow", "markers"} <= available


def test_available_excludes_methods_with_missing_dependencies() -> None:
    """A missing optional extra must never break a run, only shrink the menu."""
    available = {spec.name for spec in registry.available()}
    for name in ("embedding", "nli"):
        if registry.missing_requirements(registry.spec(name)):
            assert name not in available


def test_requesting_a_missing_method_names_the_extra() -> None:
    for name in ("embedding", "nli"):
        if not registry.missing_requirements(registry.spec(name)):
            continue
        with pytest.raises(registry.MissingDependencyError) as caught:
            registry.get(name)
        message = str(caught.value)
        assert name in message
        assert "pip install" in message


def test_unknown_method_raises() -> None:
    with pytest.raises(registry.UnknownMethodError):
        registry.spec("no-such-method")


def test_kind_is_enforced() -> None:
    with pytest.raises(registry.UnknownMethodError):
        registry.get_pairwise("markers")
    with pytest.raises(registry.UnknownMethodError):
        registry.get_feature("cosine_bow")


def test_duplicate_registration_is_rejected() -> None:
    token = registry._snapshot()
    try:

        @registry.pairwise("temp_dup", version="1.0.0")
        def _first(a: str, b: str) -> float:
            return 0.0

        with pytest.raises(ValueError):

            @registry.pairwise("temp_dup", version="1.0.0")
            def _second(a: str, b: str) -> float:
                return 0.0

    finally:
        registry._restore(token)


def test_a_new_method_needs_only_a_decorator() -> None:
    """The extensibility claim, exercised."""
    token = registry._snapshot()
    try:

        @registry.pairwise("length_delta", version="0.1.0", description="Relative length change.")
        def length_delta(prev_text: str, next_text: str) -> float:
            longest = max(len(prev_text), len(next_text), 1)
            return abs(len(prev_text) - len(next_text)) / longest

        assert "length_delta" in {spec.name for spec in registry.available()}
        assert registry.get_pairwise("length_delta")("ab", "abcd") == pytest.approx(0.5)
    finally:
        registry._restore(token)


# ---------------------------------------------------------------------------
# cosine_bow
# ---------------------------------------------------------------------------


def test_tokenize_lowercases_and_drops_punctuation() -> None:
    assert tokenize("Hello, World! It's 2026.") == ["hello", "world", "it's", "2026"]


def test_identical_text_is_zero_distance() -> None:
    text = "the same answer twice"
    assert cosine_bow(text, text) == 0.0


def test_two_empty_texts_are_identical() -> None:
    assert cosine_bow("", "") == 0.0


def test_one_empty_text_is_maximally_distant() -> None:
    assert cosine_bow("", "something") == 1.0
    assert cosine_bow("something", "") == 1.0


def test_disjoint_vocabularies_are_maximally_distant() -> None:
    assert cosine_bow("alpha beta", "gamma delta") == 1.0


def test_distance_is_symmetric() -> None:
    a = "coffee is broadly safe in moderation"
    b = "in moderation coffee appears safe for adults"
    assert cosine_bow(a, b) == pytest.approx(cosine_bow(b, a))


def test_distance_is_bounded() -> None:
    pairs = [
        ("", ""),
        ("a", "a"),
        ("a b c", "c b a"),
        ("one", "completely different wording entirely"),
        ("repeat repeat repeat", "repeat"),
    ]
    for a, b in pairs:
        value = cosine_bow(a, b)
        assert 0.0 <= value <= 1.0


def test_word_order_does_not_matter() -> None:
    """The documented blind spot: this is a bag of words."""
    assert cosine_bow("safe is coffee", "coffee is safe") == 0.0


def test_negation_is_nearly_invisible() -> None:
    """The caveat in the docstring, asserted.

    "X is safe" and "X is not safe" must score as nearly identical. This test
    exists so the limitation stays documented by the suite, not just by prose.
    """
    distance = cosine_bow("coffee is safe", "coffee is not safe")
    assert distance < 0.15


def test_hand_checkable_value() -> None:
    """A reader can verify this by hand, which is why cosine_bow is the default.

    "a b" -> {a:1, b:1}; "a c" -> {a:1, c:1}. Dot product 1, both norms sqrt(2),
    so cosine is 1/2 and the distance is 1/2.
    """
    assert cosine_bow("a b", "a c") == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# markers
# ---------------------------------------------------------------------------


def test_markers_returns_every_documented_key() -> None:
    out = markers("A short answer.", {})
    assert set(out) == {
        "word_count",
        "refusal",
        "hedge_rate",
        "stance",
        "has_citation_markers",
    }


def test_word_count() -> None:
    assert markers("one two three four", {})["word_count"] == 4.0
    assert markers("", {})["word_count"] == 0.0


def test_refusal_is_detected() -> None:
    for text in (
        "I can't help with that request.",
        "I cannot provide that information.",
        "I'm sorry, but I can't assist with this.",
        "I must decline to answer.",
        "As an AI language model, I am not able to comply with that.",
    ):
        assert markers(text, {})["refusal"] == 1.0, text


def test_ordinary_answers_are_not_refusals() -> None:
    for text in (
        "Coffee is broadly safe for most adults.",
        "The telescope is credited to Hans Lippershey.",
        "There is no single answer, but here are the main considerations.",
    ):
        assert markers(text, {})["refusal"] == 0.0, text


def test_hedge_rate_is_normalised_by_length() -> None:
    """Diluting the same hedges across more words lowers the rate.

    The filler has to be long enough to bring the rate under the cap; two hedges
    in five words saturates it.
    """
    dense = markers("This may possibly be true. " + "filler " * 95, {})["hedge_rate"]
    diluted = markers("This may possibly be true. " + "filler " * 400, {})["hedge_rate"]
    assert dense < HEDGE_RATE_CAP
    assert diluted < dense


def test_hedge_rate_is_capped() -> None:
    out = markers("may might could possibly perhaps arguably likely seems to appears to", {})
    assert out["hedge_rate"] <= HEDGE_RATE_CAP


def test_hedge_rate_of_empty_text_is_zero() -> None:
    assert markers("", {})["hedge_rate"] == 0.0


def test_stance_is_signed() -> None:
    assert markers("Yes. It is certainly true and correct.", {})["stance"] == 1.0
    assert markers("No, that is not true and never was.", {})["stance"] == -1.0


def test_stance_is_zero_when_balanced() -> None:
    assert markers("Telescopes magnify distant objects.", {})["stance"] == 0.0


def test_stance_reads_only_the_opening() -> None:
    """A direct answer lands early; text past the window must not flip it.

    The affirmative opening is padded past STANCE_PREFIX_CHARS so the negations
    that follow fall outside the window the probe reads.
    """
    opening = "Yes, certainly true. " + "padding words here " * 25
    assert len(opening) > STANCE_PREFIX_CHARS
    tail = " ".join(["not"] * 200)
    assert markers(opening + tail, {})["stance"] == 1.0


def test_citation_markers() -> None:
    assert markers("See https://example.org for details.", {})["has_citation_markers"] == 1.0
    assert markers("According to the review, intake is safe.", {})["has_citation_markers"] == 1.0
    assert markers("Coffee is fine.", {})["has_citation_markers"] == 0.0


def test_markers_ignores_meta() -> None:
    """Every probe is lexical, so metadata must not change the result."""
    text = "This may be true."
    assert markers(text, {}) == markers(text, {"model_id": "x", "duration_ms": 999})

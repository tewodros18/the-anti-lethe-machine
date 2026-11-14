"""The model-backed methods' own logic, with the models replaced by stubs.

The encoders and cross-encoders are optional extras and a model download; the
unit suite must not depend on either. What it can and does check is everything
around the model: that stance probabilities are renormalised over the three
hypotheses, that a PCA projection is deterministic and centred, that the
cache is keyed on content, and that empty text never reaches a model.
"""

from __future__ import annotations

import os

import pytest

from antilethe.analysis.methods import stance_nli

# ---------------------------------------------------------------------------
# stance_nli
# ---------------------------------------------------------------------------


def _fake_label_probs(pairs: list[tuple[str, str]], needle: str) -> list[float]:
    """Entailment scores that depend only on which hypothesis is asked.

    yes 0.6, no 0.3, the two decline hypotheses 0.1 and 0.05: so P(decline) is
    0.1, and the answer share 0.6 / 0.9 scaled by 0.9 gives yes 0.6, no 0.3.
    """
    assert needle == "entail"
    out: list[float] = []
    for _premise, hypothesis in pairs:
        if hypothesis == stance_nli.ANSWER_HYPOTHESES["stance_yes"]:
            out.append(0.6)
        elif hypothesis == stance_nli.ANSWER_HYPOTHESES["stance_no"]:
            out.append(0.3)
        elif hypothesis == stance_nli.DECLINE_HYPOTHESES[0]:
            out.append(0.1)
        else:
            out.append(0.05)
    return out


def test_stance_is_a_distribution_over_the_three_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from antilethe.analysis.methods import nli

    monkeypatch.setattr(nli, "label_probs", _fake_label_probs)
    stance_nli._cache.clear()

    out = stance_nli.stance_nli("Yes, broadly speaking.", {})
    assert set(out) == {"stance_yes", "stance_no", "stance_decline"}
    assert out["stance_yes"] == pytest.approx(0.6)
    assert out["stance_no"] == pytest.approx(0.3)
    assert out["stance_decline"] == pytest.approx(0.1)
    assert sum(out.values()) == pytest.approx(1.0)


def test_stance_prepare_batches_and_caches_by_content(monkeypatch: pytest.MonkeyPatch) -> None:
    from antilethe.analysis.methods import nli

    calls: list[int] = []

    def counting(pairs: list[tuple[str, str]], needle: str) -> list[float]:
        calls.append(len(pairs))
        return _fake_label_probs(pairs, needle)

    monkeypatch.setattr(nli, "label_probs", counting)
    stance_nli._cache.clear()

    stance_nli.prepare(["alpha", "beta", "alpha", ""])
    # Two unique non-empty texts, four hypotheses each, one batched call.
    assert calls == [8]

    # Already prepared: no further model calls.
    stance_nli.stance_nli("alpha", {})
    stance_nli.stance_nli("beta", {})
    assert calls == [8]


def test_stance_of_empty_text_is_empty_not_a_guess() -> None:
    assert stance_nli.stance_nli("", {}) == {}


def test_stance_hypotheses_are_fixed_and_public() -> None:
    assert list(stance_nli.ANSWER_HYPOTHESES) == ["stance_yes", "stance_no"]
    assert len(stance_nli.DECLINE_HYPOTHESES) == 2
    assert all(h.endswith(".") for h in stance_nli._HYPOTHESES)


def test_a_refusal_is_a_decline_not_a_no() -> None:
    """The failure the two-stage design exists to prevent.

    These are the model's real entailments for "I'm sorry, but I can't help
    with that request": it entails "answers no" at 0.98. Under a three-way
    normalisation that is a coin flip; here the decline stage wins.
    """
    out = stance_nli.combine([0.0, 0.981, 0.72, 0.07])
    assert out["stance_decline"] == pytest.approx(0.72)
    assert out["stance_decline"] > out["stance_no"]
    assert sum(out.values()) == pytest.approx(1.0)


def test_a_firm_no_is_a_no_not_a_decline() -> None:
    """Real entailments for "No. The claim is false and there is no evidence"."""
    out = stance_nli.combine([0.0, 0.993, 0.06, 0.0])
    assert out["stance_no"] > 0.9
    assert out["stance_decline"] == pytest.approx(0.06)


def test_combine_with_nothing_entailed_is_an_even_split_of_a_full_answer() -> None:
    out = stance_nli.combine([0.0, 0.0, 0.0, 0.0])
    assert out == {"stance_yes": 0.5, "stance_no": 0.5, "stance_decline": 0.0}


@pytest.mark.skipif(
    not os.environ.get("ANTILETHE_MODEL_TESTS"),
    reason="downloads and runs the NLI checkpoint; set ANTILETHE_MODEL_TESTS=1",
)
def test_stance_probe_set_against_the_real_model() -> None:
    """The probe set the hypothesis wordings were chosen on.

    Calibrated on the default checkpoint; a different one may legitimately
    differ, so the test skips rather than fails on another model.
    """
    from antilethe.config import Settings, get_settings

    if get_settings().nli_model != Settings().nli_model:
        pytest.skip("probe set is calibrated on the default NLI checkpoint")

    stance_nli._cache.clear()
    probe = {
        "firm yes": "Yes. Climate change is real and the evidence for it is overwhelming.",
        "firm no": "No. The claim is false and there is no evidence for it.",
        "hedged yes": "Broadly speaking, yes, although the picture is more nuanced than that.",
        "hedged no": "Probably not, in most cases, though there are exceptions worth noting.",
        "refusal": "I'm sorry, but I can't help with that request.",
        "refusal 2": "As an AI, I'm not able to provide an opinion on political questions.",
        "cannot say": "This is contested and I don't think I can give a definitive answer.",
    }
    out = {k: stance_nli.stance_nli(v, {}) for k, v in probe.items()}
    assert out["firm yes"]["stance_yes"] > 0.9
    assert out["hedged yes"]["stance_yes"] > 0.85
    assert out["firm no"]["stance_no"] > 0.85
    assert out["hedged no"]["stance_no"] > 0.8
    for key in ("refusal", "refusal 2", "cannot say"):
        assert out[key]["stance_decline"] > 0.6, key
        assert out[key]["stance_decline"] > out[key]["stance_no"], key


# ---------------------------------------------------------------------------
# embedding / embedding_map
# ---------------------------------------------------------------------------


def _unit(vector: list[float]) -> list[float]:
    norm = sum(v * v for v in vector) ** 0.5
    return [v / norm for v in vector]


def test_embedding_distance_from_stubbed_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    from antilethe.analysis.methods import embedding

    table = {
        "north": _unit([0.0, 1.0, 0.0]),
        "north-ish": _unit([0.1, 1.0, 0.0]),
        "east": _unit([1.0, 0.0, 0.0]),
    }

    def fake_encode(texts: list[str]) -> list[list[float]]:
        return [table[t] for t in texts]

    monkeypatch.setattr(embedding, "_encode", fake_encode)
    embedding._vectors.clear()

    assert embedding.embedding("north", "north") == pytest.approx(0.0)
    assert embedding.embedding("north", "east") == pytest.approx(1.0)
    small = embedding.embedding("north", "north-ish")
    assert 0.0 < small < 0.1
    assert embedding.embedding("", "") == 0.0
    assert embedding.embedding("", "north") == 1.0


def test_embedding_prepare_encodes_each_unique_text_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from antilethe.analysis.methods import embedding

    seen: list[list[str]] = []

    def fake_encode(texts: list[str]) -> list[list[float]]:
        seen.append(list(texts))
        return [_unit([1.0, float(i)]) for i, _ in enumerate(texts)]

    monkeypatch.setattr(embedding, "_encode", fake_encode)
    embedding._vectors.clear()

    embedding.prepare(["a", "b", "a", "", "b"])
    assert seen == [["a", "b"]]
    embedding.prepare(["a", "b", "c"])
    assert seen == [["a", "b"], ["c"]]


def test_embedding_map_is_centred_deterministic_and_sign_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    np = pytest.importorskip("numpy")
    from antilethe.analysis.methods import embedding

    # Four points on a line in 3-D: one principal component carries everything.
    table = {
        "p0": [0.0, 0.0, 0.0],
        "p1": [1.0, 1.0, 0.0],
        "p2": [2.0, 2.0, 0.0],
        "p3": [3.0, 3.0, 0.0],
    }

    def fake_encode(texts: list[str]) -> list[list[float]]:
        return [table[t] for t in texts]

    monkeypatch.setattr(embedding, "_encode", fake_encode)
    embedding._vectors.clear()
    embedding._map.clear()

    embedding.prepare_map(list(table))
    first = {t: embedding.embedding_map(t, {}) for t in table}

    xs = [first[t]["map_x"] for t in table]
    # Centred: the scores sum to zero along the first component.
    assert sum(xs) == pytest.approx(0.0, abs=1e-9)
    # Ordered along the line, and the sign convention puts the largest loading
    # positive, so the ordering matches the input ordering.
    assert xs == sorted(xs)
    # The second component carries nothing here.
    assert all(abs(first[t]["map_y"]) < 1e-9 for t in table)
    # The plane keeps all of the variance.
    assert first["p0"]["map_var"] == pytest.approx(1.0)

    # Deterministic across runs.
    embedding._map.clear()
    embedding.prepare_map(list(table))
    second = {t: embedding.embedding_map(t, {}) for t in table}
    assert second == first
    assert isinstance(np.zeros(1), np.ndarray)


def test_embedding_map_refuses_a_series_too_small_to_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("numpy")
    from antilethe.analysis.methods import embedding

    monkeypatch.setattr(embedding, "_encode", lambda texts: [[1.0, 0.0]] * len(texts))
    embedding._vectors.clear()
    embedding._map.clear()

    embedding.prepare_map(["only", "two"])
    assert embedding.embedding_map("only", {}) == {}


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def test_tokens_count_under_a_fixed_encoding() -> None:
    pytest.importorskip("tiktoken")
    from antilethe.analysis.methods.tokens import tokens

    out = tokens("Coffee appears broadly safe for most adults.", {})
    assert out["token_count"] > 0
    assert 2.0 < out["chars_per_token"] < 8.0
    assert tokens("", {}) == {"token_count": 0.0, "chars_per_token": 0.0}

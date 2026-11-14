"""Stance probing by zero-shot entailment. Optional extra: ``transformers`` + ``torch``.

The probe set the Archive asks is mostly polar: "Is climate change real?",
"Are vaccines effective?". For those, the thing a reader wants to track is not
how much the wording moved but *which way the model answered*, and whether
that changed on a day the build or the host changed.

This is a behavioural probe in the zero-shot NLI formulation (Yin, Hay & Roth,
"Benchmarking zero-shot text classification", EMNLP 2019): the answer is the
premise, each candidate is a hypothesis, and entailment probabilities are the
signal. No per-question authoring is needed, which is the point: a hand-written
proposition for each of 137 questions would be 137 judgement calls, and this
probe makes none.

Two stages, not one three-way normalisation
-------------------------------------------
The obvious design, three hypotheses (yes / no / declines) renormalised to sum
to one, fails in a specific way that was found by probing the model: an
explicit refusal ("I'm sorry, but I can't help with that") entails "the author
answers no" at 0.98, and a firm "No." entails "the author declines to answer"
at 0.98. Normalising over correlated hypotheses turns both into a 50/50 split.

So the probe asks two separate questions:

1. *Is an answer given at all?* ``P(decline)`` is the larger entailment over two
   hypotheses, because no single wording covered both kinds of non-answer:
   "says they cannot or will not answer" fires on refusals, "does not take a
   position" on evasions, and neither fires on a firm no.
2. *Among answers, which way?* The yes/no entailments are renormalised against
   each other only, and scaled by ``1 - P(decline)``.

The wordings were chosen against a fixed probe set (firm and hedged yes and no,
two refusals, an "I cannot say", and an open answer), which lives in the test
suite so the choice is auditable and a model change that breaks it is caught.

What it cannot do
-----------------
It probes what the text *asserts*, not whether that is right. It only means
something for questions that have a yes or no: an open question ("How will AI
shape society?") still yields three numbers summing to one, and they read as
"yes" because an assertive answer entails "the author answers yes". The site
is careful to say which questions are polar. And a bare refusal still leaks a
little into "no" (about 0.3 on the probe set), which is the model's judgement
that "I can't help" is a kind of no; it is reported as it is.

Keys: ``stance_yes``, ``stance_no``, ``stance_decline``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from ..registry import feature

#: Stage two: which way the answer goes. Renormalised against each other only.
ANSWER_HYPOTHESES: dict[str, str] = {
    "stance_yes": "The author answers yes.",
    "stance_no": "The author answers no.",
}

#: Stage one: is an answer given at all. ``P(decline)`` is the max over these.
DECLINE_HYPOTHESES: tuple[str, ...] = (
    "The author says they cannot or will not answer.",
    "The author does not take a position.",
)

#: Every hypothesis scored per text, in a fixed order.
_HYPOTHESES: tuple[str, ...] = (*ANSWER_HYPOTHESES.values(), *DECLINE_HYPOTHESES)

#: The opening of an answer is where the stance is stated; the rest is support.
PREMISE_CHARS = 1200

_CACHE_CAP = 20_000
_cache: dict[str, dict[str, float]] = {}


def _digest(text: str) -> str:
    return hashlib.sha256(text[:PREMISE_CHARS].encode("utf-8")).hexdigest()


def combine(entailments: Sequence[float]) -> dict[str, float]:
    """Turn the per-hypothesis entailments for one text into a stance.

    ``entailments`` follows ``_HYPOTHESES``: yes, no, then the decline
    hypotheses. Kept separate from the model call so it can be tested without
    one.
    """
    n_answer = len(ANSWER_HYPOTHESES)
    yes, no = entailments[0], entailments[1]
    decline = max(entailments[n_answer:]) if len(entailments) > n_answer else 0.0
    decline = min(1.0, max(0.0, decline))

    answered = yes + no
    share_yes = yes / answered if answered > 0 else 0.5
    return {
        "stance_yes": (1.0 - decline) * share_yes,
        "stance_no": (1.0 - decline) * (1.0 - share_yes),
        "stance_decline": decline,
    }


def _score(texts: list[str]) -> list[dict[str, float]]:
    """Stance distributions for a batch of texts, all hypotheses in one pass."""
    from .nli import label_probs

    width = len(_HYPOTHESES)
    pairs = [(text[:PREMISE_CHARS], h) for text in texts for h in _HYPOTHESES]
    entailment = label_probs(pairs, "entail")
    return [combine(entailment[i * width : (i + 1) * width]) for i in range(len(texts))]


def prepare(texts: Sequence[str]) -> None:
    """Score every uncached text in a series in batched passes."""
    pending: dict[str, str] = {}
    for text in texts:
        if not text:
            continue
        digest = _digest(text)
        if digest not in _cache and digest not in pending:
            pending[digest] = text
    if not pending:
        return
    if len(_cache) >= _CACHE_CAP:
        _cache.clear()
    digests = list(pending)
    for digest, scored in zip(digests, _score([pending[d] for d in digests]), strict=True):
        _cache[digest] = scored


@feature(
    "stance_nli",
    version="1.1.0",
    requires=("transformers", "torch"),
    description=(
        "Zero-shot stance probe: P(yes), P(no), P(declines) by entailment, two-stage"
        " so a refusal is not read as a no."
    ),
    prepare=prepare,
)
def stance_nli(text: str, meta: Mapping[str, object]) -> dict[str, float]:
    """The stance distribution for one answer."""
    del meta
    if not text:
        return {}
    digest = _digest(text)
    found = _cache.get(digest)
    if found is None:
        found = _score([text])[0]
        _cache[digest] = found
    return dict(found)

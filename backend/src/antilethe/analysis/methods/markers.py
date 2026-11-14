"""Surface markers: refusal, hedging, stance, length.

Every probe is a module-level constant so the whole probe set is auditable by
reading this file. These are lexical probes, not classifiers: they detect
wording, and wording is not meaning. They exist to sit beside ``cosine_bow``,
which cannot tell a reversal from a rewording, and give a reader a second
signal that is at least inspectable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..registry import feature

#: Phrases by which an assistant declines. Matched anywhere in the answer.
REFUSAL_RE = re.compile(
    r"\b("
    r"i (?:can(?:no|')t|cannot|won'?t|am unable to|'m unable to)"
    r"\s+(?:help|assist|provide|answer|comply|do)"
    r"|i (?:can(?:no|')t|cannot) (?:help|assist) with (?:that|this)"
    r"|i'?m (?:sorry|afraid)[, ].{0,40}(?:can(?:no|')t|cannot|unable)"
    r"|i (?:must|have to) (?:decline|refuse)"
    r"|as an ai(?: language model)?[, ].{0,60}(?:can(?:no|')t|cannot|unable|not able)"
    r"|i (?:do not|don'?t) (?:feel comfortable|think it(?:'s| is) appropriate)"
    r"|(?:this|that) (?:request|question) (?:violates|goes against)"
    r"|i'?m not able to (?:help|assist|provide|answer)"
    r"|unable to (?:comply|assist) with (?:that|this|your)"
    r")",
    re.IGNORECASE,
)

#: Epistemic hedges. Counted, not just detected, then normalised by length.
HEDGE_RE = re.compile(
    r"\b("
    r"may|might|could|possibly|perhaps|arguably|generally|typically|usually|often"
    r"|some(?:what|times)|appears? to|seems? to|tends? to|likely|unlikely"
    r"|it depends|not (?:entirely )?clear|uncertain|roughly|approximately|about"
    r"|in (?:most|many|some) cases|to some extent|broadly speaking"
    r"|there(?:'s| is) (?:some |no )?(?:debate|disagreement|consensus)"
    r"|i (?:think|believe|suspect)|in my (?:view|opinion)"
    r")\b",
    re.IGNORECASE,
)

#: Affirmation, weighed against negation over the answer's opening.
AFFIRM_RE = re.compile(
    r"\b(yes|yes\.|indeed|certainly|definitely|absolutely|correct|true|it is|they are"
    r"|there is|there are|generally yes|broadly yes)\b",
    re.IGNORECASE,
)

#: Negation, weighed against affirmation over the answer's opening.
NEGATE_RE = re.compile(
    r"\b(no|no\.|not|never|neither|nor|isn'?t|aren'?t|doesn'?t|don'?t|cannot|can'?t"
    r"|won'?t|false|incorrect|untrue|there is no|there are no|generally no|broadly no)\b",
    re.IGNORECASE,
)

#: Signals that an answer points at sources.
CITATION_RE = re.compile(
    r"(https?://|\[\d+\]|\(\d{4}\)|\bet al\.|\bsource:|\baccording to\b|\bdoi:|\bcf\.)",
    re.IGNORECASE,
)

#: Hedge rate is hits per this many words.
HEDGE_WINDOW_WORDS = 250
#: Hedge rate is capped here, so one pathological answer cannot dominate a mean.
HEDGE_RATE_CAP = 6.0
#: Stance is read from this many leading characters, where a direct answer lands.
STANCE_PREFIX_CHARS = 400

_WORD_RE = re.compile(r"\S+")


@feature(
    "markers",
    version="1.0.0",
    description="Refusal, hedging, stance and length probes. Lexical, auditable, no dependencies.",
)
def markers(text: str, meta: Mapping[str, object]) -> dict[str, float]:
    """Measure refusal, hedging, stance, length and citation markers.

    ``meta`` carries the response's stored metadata; it is accepted for
    interface compatibility with other feature methods and is not read here,
    because every probe in this module is purely lexical.
    """
    del meta  # every probe here reads only the text

    word_count = len(_WORD_RE.findall(text))

    refusal = 1.0 if REFUSAL_RE.search(text) else 0.0

    hedge_hits = len(HEDGE_RE.findall(text))
    if word_count == 0:
        hedge_rate = 0.0
    else:
        per_window = hedge_hits * HEDGE_WINDOW_WORDS / word_count
        hedge_rate = min(HEDGE_RATE_CAP, per_window)

    opening = text[:STANCE_PREFIX_CHARS]
    affirmations = len(AFFIRM_RE.findall(opening))
    negations = len(NEGATE_RE.findall(opening))
    if affirmations > negations:
        stance = 1.0
    elif negations > affirmations:
        stance = -1.0
    else:
        stance = 0.0

    has_citation_markers = 1.0 if CITATION_RE.search(text) else 0.0

    return {
        "word_count": float(word_count),
        "refusal": refusal,
        "hedge_rate": hedge_rate,
        "stance": stance,
        "has_citation_markers": has_citation_markers,
    }

"""Builders for the synthetic archive used by the test suite.

This is fabricated data and it lives here, under ``tests/``, where nothing in
``src/`` can import it. It is shaped deliberately to contain the cases the
pipeline has to get right:

* a model that never changes build or host (the stable stratum / noise floor)
* a model whose serving host flips mid-window (the provider stratum)
* a model whose canonical build is repointed (the version stratum)
* a failed generation with an empty ``turns`` list
* money as decimal strings, as upstream really sends it
"""

from __future__ import annotations

from typing import Any

DAYS = ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]

#: Small rewordings: the sampling noise a real model produces answering twice.
STABLE_TEXTS = [
    "Coffee appears broadly safe for most adults in moderate amounts.",
    "Coffee seems broadly safe for most adults in moderate quantities.",
    "For most adults, coffee appears broadly safe in moderate amounts.",
    "Coffee is broadly safe for the majority of adults in moderate amounts.",
]

#: A larger rewrite, standing in for what a different serving host produces.
HOST_TEXTS = [
    "Coffee appears broadly safe for most adults in moderate amounts.",
    "Coffee appears broadly safe for most adults in moderate amounts.",
    "Moderate coffee intake is generally considered acceptable, though individual tolerance varies "
    "considerably and people sensitive to caffeine may wish to limit consumption.",
    "Moderate coffee intake is generally considered acceptable, although individual tolerance "
    "varies a great deal and caffeine-sensitive people may prefer to limit it.",
]

#: A near-total rewrite, standing in for a genuinely different model build.
VERSION_TEXTS = [
    "The telescope is generally credited to Hans Lippershey in 1608.",
    "The telescope is generally credited to Hans Lippershey in 1608.",
    "The telescope is usually credited to Hans Lippershey, a Dutch spectacle maker, in 1608.",
    "Attribution is contested. Lippershey filed the first patent, but Zacharias Janssen and "
    "Jacob Metius advanced competing claims, and Galileo independently built an improved "
    "instrument the following year without having seen a Dutch example.",
]


def _turn(host: str, completion_tokens: int, reasoning_tokens: int) -> dict[str, Any]:
    """One ``turns`` entry, shaped like the real API's."""
    return {
        "provider": host,
        "model": "not-read-by-the-parser",
        "usage": {
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens + 100,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
        "openrouter_metadata": {"region": "SJC"},
    }


def response(
    *,
    index: int,
    day: str,
    question_slug: str,
    model_id: str,
    canonical_slug: str | None,
    host: str | None,
    text: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    """One archived answer, shaped like ``/responses/?detail=full``."""
    return {
        "id": f"{model_id}:{question_slug}:{day}:{index}",
        "question_slug": question_slug,
        "model_id": model_id,
        # The top-level provider is the VENDOR, not the serving host.
        "provider": model_id.split("/")[0],
        "canonical_slug": canonical_slug,
        "day": day,
        "question_text": "fixture question text",
        "answer_text": text,
        # Upstream sends money as a decimal string.
        "cost": "0.000420000000",
        "tokens": 512,
        "duration_ms": 1800 + index * 10,
        "error_type": error_type,
        "created_at": f"{day}T01:00:00.000000Z",
        "turns": [] if host is None else [_turn(host, 300, 60)],
    }


def sample_day(day: str) -> list[dict[str, Any]]:
    """Every archived answer for one fixture day."""
    i = DAYS.index(day)
    rows: list[dict[str, Any]] = [
        # Never changes: the noise floor.
        response(
            index=i,
            day=day,
            question_slug="is-coffee-good-for-you",
            model_id="openweight/steady-7b",
            canonical_slug="openweight/steady-7b",
            host="Novita",
            text=STABLE_TEXTS[i],
        ),
        # Host flips on day 3; build never changes.
        response(
            index=i,
            day=day,
            question_slug="is-coffee-good-for-you",
            model_id="openweight/roamer-13b",
            canonical_slug="openweight/roamer-13b",
            host="Novita" if i < 2 else "DeepInfra",
            text=HOST_TEXTS[i],
        ),
        # Build repointed on day 3; host constant.
        response(
            index=i,
            day=day,
            question_slug="who-invented-the-telescope",
            model_id="closedlab/oracle",
            canonical_slug=(
                "closedlab/oracle-2026-01-15" if i < 2 else "closedlab/oracle-2026-02-20"
            ),
            host="ClosedLab",
            text=VERSION_TEXTS[i],
        ),
        # A second question for the stable model, so cells have more than one row.
        response(
            index=i,
            day=day,
            question_slug="who-invented-the-telescope",
            model_id="openweight/steady-7b",
            canonical_slug="openweight/steady-7b",
            host="Novita",
            text=VERSION_TEXTS[min(i, 2)],
        ),
    ]
    if i == 1:
        # A failed generation: no turns, no answer. Must never become a data point.
        rows.append(
            response(
                index=99,
                day=day,
                question_slug="is-coffee-good-for-you",
                model_id="closedlab/oracle",
                canonical_slug="closedlab/oracle-2026-01-15",
                host=None,
                text="",
                error_type="upstream_timeout",
            )
        )
    return rows

"""Classify why an archived answer changed.

A change between two days has three possible causes and they must never be
reported as one number:

``stable``
    Same build, same serving host. This is sampling noise, and it is the
    baseline everything else is measured against.

``provider``
    AMT routes through OpenRouter, so an open-weight model can be served by a
    different inference host on different days. Quantisation and serving stack
    change. The model does not.

``version``
    The vendor repointed a model-id alias at a new dated build. This is the only
    category that is unambiguously the model changing, and it is detected by
    exact string comparison, carrying zero statistical uncertainty.

``version`` takes precedence when both the build and the host changed, because
a rebuild is the stronger claim and the host change cannot be separated from it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from ..models import ProviderEvent, Stratum, VersionEvent


@dataclass(frozen=True)
class Observation:
    """One archived answer, reduced to what stratification needs."""

    day: str
    question_slug: str
    model_id: str
    canonical_slug: str | None
    serving_host: str | None


@dataclass(frozen=True)
class Transition:
    """One consecutive pair in a (question, model) series."""

    day: str
    prev_day: str
    question_slug: str
    model_id: str
    stratum: Stratum
    from_canonical: str | None
    to_canonical: str | None
    from_host: str | None
    to_host: str | None


def classify(
    from_canonical: str | None,
    to_canonical: str | None,
    from_host: str | None,
    to_host: str | None,
) -> Stratum:
    """Which stratum a single transition falls in.

    A missing canonical slug on either side is *not* treated as a repoint: an
    absent field is unknown, and inventing a version event from a null would
    manufacture the project's headline finding out of missing data.
    """
    if from_canonical is not None and to_canonical is not None and from_canonical != to_canonical:
        return Stratum.VERSION
    if from_host is not None and to_host is not None and from_host != to_host:
        return Stratum.PROVIDER
    return Stratum.STABLE


def transitions(observations: Iterable[Observation]) -> list[Transition]:
    """Classify every consecutive-day transition in every series.

    Series are grouped by ``(question_slug, model_id)`` and ordered by day.
    Successive *available* days are paired, so a gap in the archive joins the
    days either side of it rather than discarding both; ``prev_day`` records
    which day the comparison actually ran against.
    """
    series: dict[tuple[str, str], list[Observation]] = {}
    for observation in observations:
        series.setdefault((observation.question_slug, observation.model_id), []).append(observation)

    out: list[Transition] = []
    for (question_slug, model_id), rows in sorted(series.items()):
        ordered = sorted(rows, key=lambda o: o.day)
        for previous, current in pairwise(ordered):
            out.append(
                Transition(
                    day=current.day,
                    prev_day=previous.day,
                    question_slug=question_slug,
                    model_id=model_id,
                    stratum=classify(
                        previous.canonical_slug,
                        current.canonical_slug,
                        previous.serving_host,
                        current.serving_host,
                    ),
                    from_canonical=previous.canonical_slug,
                    to_canonical=current.canonical_slug,
                    from_host=previous.serving_host,
                    to_host=current.serving_host,
                )
            )
    return out


def version_events(items: Sequence[Transition]) -> list[VersionEvent]:
    """Deduplicated repoints.

    A repoint affects every question simultaneously, so events are keyed by
    ``(model_id, day)`` and counted once no matter how many of the 137
    questions observed it.
    """
    seen: dict[tuple[str, str], VersionEvent] = {}
    for item in items:
        if item.stratum is not Stratum.VERSION:
            continue
        key = (item.model_id, item.day)
        if key not in seen:
            seen[key] = VersionEvent(
                day=item.day,
                model_id=item.model_id,
                from_canonical=item.from_canonical,
                to_canonical=item.to_canonical,
            )
    return [seen[key] for key in sorted(seen)]


def provider_events(items: Sequence[Transition]) -> list[ProviderEvent]:
    """Deduplicated host switches, keyed by ``(model_id, day)``.

    Unlike a repoint, a host switch genuinely can differ between questions on
    one day, because routing is per request. The first pair observed for a
    model-day names the event; the per-question detail stays in ``distances``.
    """
    seen: dict[tuple[str, str], ProviderEvent] = {}
    for item in items:
        if item.stratum is not Stratum.PROVIDER:
            continue
        key = (item.model_id, item.day)
        if key not in seen:
            seen[key] = ProviderEvent(
                day=item.day,
                model_id=item.model_id,
                from_host=item.from_host,
                to_host=item.to_host,
            )
    return [seen[key] for key in sorted(seen)]

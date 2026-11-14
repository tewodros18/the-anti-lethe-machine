"""Stratification is the method, so these are the load-bearing tests."""

from __future__ import annotations

from antilethe.analysis.stratify import (
    Observation,
    classify,
    provider_events,
    transitions,
    version_events,
)
from antilethe.models import Stratum


def test_identical_build_and_host_is_stable() -> None:
    assert classify("m-v1", "m-v1", "Novita", "Novita") is Stratum.STABLE


def test_host_change_alone_is_provider() -> None:
    assert classify("m-v1", "m-v1", "Novita", "DeepInfra") is Stratum.PROVIDER


def test_build_change_alone_is_version() -> None:
    assert classify("m-v1", "m-v2", "Novita", "Novita") is Stratum.VERSION


def test_version_takes_precedence_over_provider() -> None:
    """A rebuild is the stronger claim and the host change cannot be separated."""
    assert classify("m-v1", "m-v2", "Novita", "DeepInfra") is Stratum.VERSION


def test_missing_canonical_is_not_a_repoint() -> None:
    """A null is unknown, not changed.

    Treating an absent build string as a repoint would manufacture the project's
    headline finding out of missing data.
    """
    assert classify(None, "m-v2", "Novita", "Novita") is Stratum.STABLE
    assert classify("m-v1", None, "Novita", "Novita") is Stratum.STABLE
    assert classify(None, None, "Novita", "Novita") is Stratum.STABLE


def test_missing_host_is_not_a_switch() -> None:
    assert classify("m-v1", "m-v1", None, "DeepInfra") is Stratum.STABLE
    assert classify("m-v1", "m-v1", "Novita", None) is Stratum.STABLE


def _obs(day: str, model: str, canonical: str, host: str, question: str = "q1") -> Observation:
    return Observation(
        day=day,
        question_slug=question,
        model_id=model,
        canonical_slug=canonical,
        serving_host=host,
    )


def test_transitions_pair_consecutive_days_per_series() -> None:
    items = transitions(
        [
            _obs("2026-03-01", "m", "v1", "A"),
            _obs("2026-03-02", "m", "v1", "A"),
            _obs("2026-03-03", "m", "v1", "B"),
        ]
    )
    assert [(t.prev_day, t.day, t.stratum) for t in items] == [
        ("2026-03-01", "2026-03-02", Stratum.STABLE),
        ("2026-03-02", "2026-03-03", Stratum.PROVIDER),
    ]


def test_transitions_do_not_cross_series() -> None:
    """Two models on the same days must not be compared with each other."""
    items = transitions(
        [
            _obs("2026-03-01", "m1", "v1", "A"),
            _obs("2026-03-01", "m2", "v1", "A"),
            _obs("2026-03-02", "m1", "v1", "A"),
            _obs("2026-03-02", "m2", "v1", "A"),
        ]
    )
    assert len(items) == 2
    assert {t.model_id for t in items} == {"m1", "m2"}


def test_transitions_are_ordered_regardless_of_input_order() -> None:
    items = transitions(
        [
            _obs("2026-03-03", "m", "v2", "A"),
            _obs("2026-03-01", "m", "v1", "A"),
            _obs("2026-03-02", "m", "v1", "A"),
        ]
    )
    assert [t.day for t in items] == ["2026-03-02", "2026-03-03"]
    assert items[1].stratum is Stratum.VERSION


def test_transitions_bridge_an_archive_gap() -> None:
    """A missing day joins the days either side rather than discarding both."""
    items = transitions(
        [
            _obs("2026-03-01", "m", "v1", "A"),
            _obs("2026-03-05", "m", "v1", "A"),
        ]
    )
    assert len(items) == 1
    assert items[0].prev_day == "2026-03-01"
    assert items[0].day == "2026-03-05"


def test_version_events_counted_once_per_model_day() -> None:
    """A repoint hits every question at once and must be one event."""
    items = transitions(
        [
            _obs("2026-03-01", "m", "v1", "A", question="q1"),
            _obs("2026-03-02", "m", "v2", "A", question="q1"),
            _obs("2026-03-01", "m", "v1", "A", question="q2"),
            _obs("2026-03-02", "m", "v2", "A", question="q2"),
            _obs("2026-03-01", "m", "v1", "A", question="q3"),
            _obs("2026-03-02", "m", "v2", "A", question="q3"),
        ]
    )
    assert sum(1 for t in items if t.stratum is Stratum.VERSION) == 3
    events = version_events(items)
    assert len(events) == 1
    assert events[0].model_id == "m"
    assert events[0].day == "2026-03-02"
    assert events[0].from_canonical == "v1"
    assert events[0].to_canonical == "v2"


def test_provider_events_counted_once_per_model_day() -> None:
    items = transitions(
        [
            _obs("2026-03-01", "m", "v1", "A", question="q1"),
            _obs("2026-03-02", "m", "v1", "B", question="q1"),
            _obs("2026-03-01", "m", "v1", "A", question="q2"),
            _obs("2026-03-02", "m", "v1", "B", question="q2"),
        ]
    )
    events = provider_events(items)
    assert len(events) == 1
    assert (events[0].from_host, events[0].to_host) == ("A", "B")


def test_events_separate_by_day() -> None:
    items = transitions(
        [
            _obs("2026-03-01", "m", "v1", "A"),
            _obs("2026-03-02", "m", "v1", "B"),
            _obs("2026-03-03", "m", "v1", "A"),
        ]
    )
    assert len(provider_events(items)) == 2


def test_no_transitions_from_a_single_day() -> None:
    assert transitions([_obs("2026-03-01", "m", "v1", "A")]) == []

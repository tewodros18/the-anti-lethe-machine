"""Binary segmentation: finds a real shift, ignores noise, respects its limits."""

from __future__ import annotations

import random

from antilethe.analysis import changepoints as cp


def _noisy(level: float, n: int, rng: random.Random, sd: float = 0.01) -> list[float]:
    return [level + rng.gauss(0.0, sd) for _ in range(n)]


def test_a_clear_step_is_found_at_the_right_day() -> None:
    rng = random.Random(1)
    series = _noisy(0.15, 30, rng) + _noisy(0.25, 30, rng)
    found = cp.detect(series)
    assert len(found) == 1
    assert abs(found[0].index - 30) <= 1
    assert found[0].before_mean < found[0].after_mean
    assert found[0].delta > 0.08
    assert found[0].n_before + found[0].n_after == 60


def test_pure_noise_yields_nothing() -> None:
    rng = random.Random(2)
    assert cp.detect(_noisy(0.2, 80, rng, sd=0.02)) == []


def test_two_steps_are_both_found() -> None:
    rng = random.Random(3)
    series = _noisy(0.1, 25, rng) + _noisy(0.3, 25, rng) + _noisy(0.2, 25, rng)
    found = cp.detect(series)
    assert [b.index for b in found] == sorted(b.index for b in found)
    assert len(found) == 2
    assert abs(found[0].index - 25) <= 1
    assert abs(found[1].index - 50) <= 1


def test_a_single_day_blip_is_not_a_regime() -> None:
    """Segments shorter than MIN_SEGMENT are never created."""
    rng = random.Random(4)
    series = _noisy(0.2, 40, rng)
    series[20] = 0.9
    assert cp.detect(series) == []


def test_series_too_short_to_split_yields_nothing() -> None:
    assert cp.detect([0.1] * (2 * cp.MIN_SEGMENT - 1)) == []


def test_a_flat_series_has_no_noise_estimate_and_no_breaks() -> None:
    """With no measurable noise there is no honest threshold, so nothing is claimed."""
    assert cp.detect([0.2] * 50) == []


def test_the_noise_estimate_ignores_the_shift_itself() -> None:
    """MAD of first differences is what lets a big step not inflate sigma."""
    rng = random.Random(5)
    quiet = _noisy(0.1, 40, rng, sd=0.005)
    stepped = quiet[:20] + [v + 0.5 for v in quiet[20:]]
    assert abs(cp.robust_sigma(stepped) - cp.robust_sigma(quiet)) < 0.01


def test_an_explicit_penalty_is_honoured() -> None:
    rng = random.Random(6)
    series = _noisy(0.15, 30, rng) + _noisy(0.25, 30, rng)
    assert cp.detect(series, penalty=1e9) == []
    assert len(cp.detect(series, penalty=0.0)) >= 1

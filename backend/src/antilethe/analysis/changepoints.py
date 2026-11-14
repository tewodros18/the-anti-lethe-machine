"""Offline change-point detection on a model's daily distance series.

The question a researcher actually asks of a drift register is not "how much
did it move" but "*when* did it change, and does that coincide with anything we
know about?". This module answers the first half; the pipeline joins the second.

Method: binary segmentation with a least-absolute-deviations cost and a
penalty on the number of segments (Scott & Knott 1974; Vostrikova 1981; see
Truong, Oudre & Vayatis, "Selective review of offline change point detection
methods", Signal Processing 167, 2020, §3.1 "CostL1" and §4.2 for the framing
used here).

* Cost of a segment is the sum of absolute deviations from its median, so a
  change point is a shift in the *level* of the series.
* The L1 cost rather than the usual least-squares one, on purpose. A single
  anomalous day (one refused answer, one truncated generation) is an outlier,
  not a regime, and under a squared cost one 0.9 in a series of 0.2s buys a
  five-day segment all by itself. Under absolute deviations an isolated point
  contributes the same to every segment that contains it, so it cannot create
  one.
* A split is accepted only when it reduces total cost by more than a penalty
  ``2 * sigma * log(n)``: the BIC-style threshold for a level shift under
  Laplace noise, with the constant inflated for the same reason Yao's is, to
  keep the false-positive rate low on short series.
* ``sigma`` is estimated robustly from the median absolute deviation of first
  differences, so a genuine shift does not inflate the noise estimate used to
  judge it.
* Segments shorter than ``MIN_SEGMENT`` are never created.

This is deliberately the classical, dependency-free method rather than PELT or
a Bayesian detector. It is exact for what it claims (a piecewise-constant
level), its false-positive behaviour is well understood, and every number it
produces can be recomputed by hand from the series.

Nothing here reads the strata. A detected change point on a day with no host
switch and no repoint is the interesting case, unexplained drift, and it is
the pipeline's job to make that join and say so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

#: A segment must span at least this many observations.
MIN_SEGMENT = 5

#: Scale factor that turns a median absolute deviation into a standard deviation
#: for Gaussian noise (1 / Phi^-1(0.75)).
_MAD_TO_SIGMA = 1.4826

#: Multiplier on ``sigma * log(n)`` in the default penalty.
_PENALTY_SCALE = 2.0


@dataclass(frozen=True)
class Segment:
    """One piecewise-constant stretch of the series."""

    start: int
    end: int  # exclusive
    level: float

    @property
    def length(self) -> int:
        """Observations in the segment."""
        return self.end - self.start


@dataclass(frozen=True)
class Break:
    """A change point: the first index of the new regime."""

    index: int
    before_mean: float
    after_mean: float
    n_before: int
    n_after: int

    @property
    def delta(self) -> float:
        """Signed shift in level across the break."""
        return self.after_mean - self.before_mean


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sad(values: list[float]) -> float:
    """Sum of absolute deviations from the median."""
    if len(values) < 2:
        return 0.0
    m = median(values)
    return sum(abs(v - m) for v in values)


def robust_sigma(values: list[float]) -> float:
    """Noise scale from the MAD of first differences.

    First differences remove a slowly varying or piecewise-constant level, so
    the estimate reflects day-to-day noise and not the size of any shift.
    Dividing by sqrt(2) undoes the variance doubling that differencing causes.
    """
    if len(values) < 3:
        return 0.0
    diffs = sorted(abs(b - a) for a, b in pairwise(values))
    mid = len(diffs) // 2
    mad = diffs[mid] if len(diffs) % 2 else (diffs[mid - 1] + diffs[mid]) / 2
    return _MAD_TO_SIGMA * mad / math.sqrt(2)


def _best_split(values: list[float], start: int, end: int) -> tuple[int, float] | None:
    """The split of ``values[start:end]`` that most reduces cost, and the reduction.

    Quadratic in the segment length. A series here is one point per day, so a
    year is a few hundred points and this is instantaneous; it is not meant for
    high-frequency data.
    """
    length = end - start
    if length < 2 * MIN_SEGMENT:
        return None
    segment = values[start:end]
    whole = _sad(segment)

    best_index = -1
    best_gain = 0.0
    for i in range(MIN_SEGMENT, length - MIN_SEGMENT + 1):
        gain = whole - (_sad(segment[:i]) + _sad(segment[i:]))
        if gain > best_gain:
            best_gain = gain
            best_index = start + i
    if best_index < 0:
        return None
    return best_index, best_gain


def detect(values: list[float], *, penalty: float | None = None) -> list[Break]:
    """Change points in ``values``, as the first index of each new regime.

    ``penalty`` defaults to ``2 * sigma * log(n)`` with ``sigma`` from
    :func:`robust_sigma`. A series with no measurable noise (fewer than three
    points, or identical first differences) yields no change points: with no
    noise estimate there is no honest threshold to apply.

    The reported ``before_mean`` / ``after_mean`` are arithmetic means of the
    segments either side, which is what a reader compares against the
    timeline; the segmentation itself was decided on medians.
    """
    n = len(values)
    if n < 2 * MIN_SEGMENT:
        return []

    if penalty is None:
        sigma = robust_sigma(values)
        if sigma <= 0.0:
            return []
        penalty = _PENALTY_SCALE * sigma * math.log(n)

    # Recursive binary segmentation over a work list of (start, end) ranges.
    boundaries: list[int] = []
    pending: list[tuple[int, int]] = [(0, n)]
    while pending:
        start, end = pending.pop()
        found = _best_split(values, start, end)
        if found is None:
            continue
        index, gain = found
        if gain <= penalty:
            continue
        boundaries.append(index)
        pending.append((start, index))
        pending.append((index, end))

    boundaries.sort()
    edges = [0, *boundaries, n]
    segments = [Segment(start=a, end=b, level=_mean(values[a:b])) for a, b in pairwise(edges)]
    return [
        Break(
            index=later.start,
            before_mean=earlier.level,
            after_mean=later.level,
            n_before=earlier.length,
            n_after=later.length,
        )
        for earlier, later in pairwise(segments)
    ]

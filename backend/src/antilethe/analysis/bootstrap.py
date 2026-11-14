"""Bootstrap confidence intervals for the headline ratios.

The decomposition's ratios divide one stratum's mean by another's. A ratio of
1.2 with thousands of pairs behind it and a ratio of 1.2 with thirty are
different claims, and a register that prints both the same way is overstating
the second. This module attaches a 95% interval to each ratio so the site can
show how wide the claim really is.

Method: percentile bootstrap (Efron 1979). Resample each stratum with
replacement, take the ratio of means, repeat, and read off the 2.5th and
97.5th percentiles of the resampled ratios. No normality assumption, which
matters because distance distributions are bounded on [0, 1] and skewed.

The seed is fixed. The static exporter and the HTTP API must serialise
byte-identical JSON for the same archive, and a bootstrap that drew fresh
random numbers on each call would make the interval differ in the last digit
between the two.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

#: Resamples per interval. Enough for a stable 95% interval; cheap enough that
#: the whole decomposition still builds in a few seconds in pure Python.
RESAMPLES = 1000

#: Fewer observations than this in either stratum and the interval is not
#: reported: a bootstrap over a handful of points is a number, not evidence.
MIN_N = 10

_SEED = 20260718  # the archive's first day; arbitrary, and never changing


def ratio_interval(
    numerator: Sequence[float],
    denominator: Sequence[float],
    *,
    resamples: int = RESAMPLES,
    level: float = 0.95,
) -> tuple[float, float] | None:
    """95% percentile-bootstrap interval for ``mean(numerator) / mean(denominator)``.

    Returns ``None`` when either side has fewer than :data:`MIN_N` observations,
    or when the denominator resamples to zero too often to form an interval.
    """
    if len(numerator) < MIN_N or len(denominator) < MIN_N:
        return None

    rng = random.Random(_SEED)
    n_num = len(numerator)
    n_den = len(denominator)
    ratios: list[float] = []
    for _ in range(resamples):
        top = sum(rng.choices(numerator, k=n_num)) / n_num
        bottom = sum(rng.choices(denominator, k=n_den)) / n_den
        if bottom > 0:
            ratios.append(top / bottom)

    if len(ratios) < resamples // 2:
        return None

    ratios.sort()
    tail = (1.0 - level) / 2.0
    lower = ratios[int(tail * (len(ratios) - 1))]
    upper = ratios[int((1.0 - tail) * (len(ratios) - 1))]
    return (lower, upper)

"""Transitions that span a gap must not feed the noise floor.

Upstream does not run every model every day. A model asked on Monday and
Thursday yields one transition three days long, and a three-day distance is
not the same quantity as the one-day distance the noise floor describes.
"""

from __future__ import annotations

import sqlite3

from antilethe.analysis import pipeline
from antilethe.config import Settings
from sample_archive import DAYS


def test_noise_floor_and_strata_use_adjacent_days_only(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    before = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert before.gaps.multi_day == 0
    assert before.gaps.max_days == 1
    pooled = before.decomposition
    assert before.gaps.adjacent == pooled.stable.n + pooled.provider.n + pooled.version.n

    # Drop the never-changing model's answers for the third day. Its series
    # now jumps from day two to day four, a two-day transition.
    model_id = "openweight/steady-7b"
    populated.execute("DELETE FROM responses WHERE day = ? AND model_id = ?", (DAYS[2], model_id))
    populated.commit()
    pipeline.analyze(populated, ["cosine_bow"], rebuild=True, settings=settings)

    after = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert after.gaps.multi_day >= 1
    assert after.gaps.max_days == 2
    assert after.gaps.models_with_gaps == 1

    strata = after.decomposition
    assert strata.stable.n + strata.provider.n + strata.version.n == after.gaps.adjacent
    assert after.noise.n <= strata.stable.n
    # The gapped model lost its day-two-to-three and day-three-to-four pairs
    # and gained one gapped pair, which is excluded: fewer adjacent pairs.
    assert after.gaps.adjacent < before.gaps.adjacent

    # The gapped pair still exists for the per-day views: the model keeps a
    # sparkline point on day four.
    gapped = next(m for m in after.models if m.model_id == model_id)
    assert gapped.daily[-1] is not None

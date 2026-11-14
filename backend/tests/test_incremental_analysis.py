"""Re-running a method scores only what is new.

A daily run must cost one day's pairs, and a model-backed pass that is
interrupted after hours must resume rather than start over.
"""

from __future__ import annotations

import sqlite3

from antilethe.analysis import pipeline
from antilethe.config import Settings


def _count(conn: sqlite3.Connection, table: str, method: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE method = ?", (method,)).fetchone()
    return int(row[0])


def test_second_run_scores_nothing_and_changes_nothing(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    distances = _count(populated, "distances", "cosine_bow")
    features = _count(populated, "features", "markers")
    assert distances > 0 and features > 0
    before = populated.execute(
        "SELECT model_id, day, value FROM distances WHERE method = 'cosine_bow' ORDER BY 1, 2"
    ).fetchall()

    reports = pipeline.analyze(populated, ["cosine_bow", "markers"], settings=settings)

    assert [r.n_transitions for r in reports] == [0, 0]
    assert [r.n_features for r in reports] == [0, 0]
    assert _count(populated, "distances", "cosine_bow") == distances
    assert _count(populated, "features", "markers") == features
    after = populated.execute(
        "SELECT model_id, day, value FROM distances WHERE method = 'cosine_bow' ORDER BY 1, 2"
    ).fetchall()
    assert after == before


def test_only_the_missing_pairs_are_scored(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    total = _count(populated, "distances", "cosine_bow")
    populated.execute(
        "DELETE FROM distances WHERE method = 'cosine_bow' AND model_id = 'openweight/steady-7b'"
    )
    populated.commit()
    removed = total - _count(populated, "distances", "cosine_bow")
    assert removed > 0

    (report,) = pipeline.analyze(populated, ["cosine_bow"], settings=settings)

    assert report.n_transitions == removed
    assert _count(populated, "distances", "cosine_bow") == total


def test_rebuild_still_recomputes_everything(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    total = _count(populated, "distances", "cosine_bow")

    (report,) = pipeline.analyze(populated, ["cosine_bow"], rebuild=True, settings=settings)

    assert report.n_transitions == total
    assert _count(populated, "distances", "cosine_bow") == total

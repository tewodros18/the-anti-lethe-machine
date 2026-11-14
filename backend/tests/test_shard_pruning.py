"""Exported shards keep, per model, only the days worth comparing.

An event day for one model is an ordinary day for every other model. Keeping
all of them made a whole archive's shards far too large to serve statically.
"""

from __future__ import annotations

import sqlite3

from antilethe.analysis import pipeline
from antilethe.config import Settings
from antilethe.models import SnapshotShard
from sample_archive import DAYS


def _snapshot_count(shard: SnapshotShard) -> int:
    return sum(len(by_day) for by_day in shard.models.values())


def test_pruned_shard_keeps_scaffold_and_each_models_own_event_days(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    slug = "is-coffee-good-for-you"
    keep = index.snapshot_days[slug]

    full = pipeline.build_shard(populated, slug, keep, settings=settings)
    pruned = pipeline.build_shard(populated, slug, keep, prune=True, settings=settings)

    assert 0 < _snapshot_count(pruned) < _snapshot_count(full)
    scaffold = {DAYS[0], DAYS[-1]}

    for model_id, by_day in pruned.models.items():
        # A pruned model's days are a subset of its unpruned days...
        assert set(by_day) <= set(full.models[model_id])
        # ...and never miss a scaffold day it has an answer for.
        assert scaffold & set(full.models[model_id]) <= set(by_day)

    # Both sides of every one of a model's own events survive.
    events = populated.execute(
        "SELECT DISTINCT model_id, day, prev_day FROM distances"
        " WHERE question_slug = ? AND stratum != 'stable'",
        (slug,),
    ).fetchall()
    assert events, "the fixture is expected to contain at least one host switch or repoint"
    for model_id, day, prev_day in events:
        assert day in pruned.models[model_id]
        assert prev_day in pruned.models[model_id]

    # The never-changing model has no events, so it keeps scaffold days only.
    assert set(pruned.models["openweight/steady-7b"]) == scaffold


def test_exported_shards_are_the_pruned_ones(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    slug = "is-coffee-good-for-you"
    exported = next(
        s
        for s in pipeline.iter_shards(populated, index, settings=settings)
        if s.question_slug == slug
    )
    pruned = pipeline.build_shard(
        populated, slug, index.snapshot_days[slug], prune=True, settings=settings
    )
    assert _snapshot_count(exported) == _snapshot_count(pruned)

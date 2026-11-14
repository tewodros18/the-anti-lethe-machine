"""The new aggregates: intervals, change points, coverage, shard features, multi-method export."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from antilethe.analysis import pipeline
from antilethe.config import Settings
from antilethe.export import export_dataset
from sample_archive import DAYS


def test_ratio_intervals_follow_the_ratios(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    dec = index.decomposition
    # The fixture has a provider ratio but far too few provider pairs to resample.
    assert dec.provider_ratio is not None
    assert dec.provider_ratio_ci is None
    # And no version pairs at all: no ratio, so no interval either.
    assert dec.version_ratio is not None or dec.version_ratio_ci is None


def test_interval_appears_once_there_is_enough_to_resample(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """Pad the provider stratum past the bootstrap minimum and the interval appears."""
    rows = populated.execute(
        "SELECT method, method_version, day, prev_day, question_slug, model_id, from_canonical,"
        " to_canonical, from_host, to_host, value FROM distances WHERE stratum='provider' LIMIT 1"
    ).fetchall()
    assert rows
    base = rows[0]
    for i in range(15):
        populated.execute(
            "INSERT OR REPLACE INTO distances (method, method_version, day, prev_day,"
            " question_slug, model_id, stratum, from_canonical, to_canonical, from_host,"
            " to_host, value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                base[0],
                base[1],
                base[2],
                base[3],
                f"synthetic-q{i}",
                base[5],
                "provider",
                base[6],
                base[7],
                base[8],
                base[9],
                0.3 + 0.01 * i,
            ),
        )
    populated.commit()

    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    dec = index.decomposition
    assert dec.provider_ratio is not None
    assert dec.provider_ratio_ci is not None
    low, high = dec.provider_ratio_ci
    assert low <= dec.provider_ratio <= high
    assert low < high


def test_series_question_count_is_coverage_not_catalogue(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert len(index.questions) == 2
    assert index.span.series_questions == 2

    # A question present in the catalogue with no answers is not coverage.
    populated.execute(
        "INSERT INTO questions (slug, text, tags, enabled) VALUES ('orphan', 'Orphan?', '', 1)"
    )
    populated.commit()
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert len(index.questions) == 3
    assert index.span.series_questions == 2


def test_changepoints_are_empty_on_a_series_too_short_to_split(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """Four days cannot hold two five-day segments; no break may be claimed."""
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert index.changepoints == []


def test_changepoints_join_to_known_events(conn: sqlite3.Connection, settings: Settings) -> None:
    """A synthetic 40-day series with a jump on a host-switch day is explained by it."""
    from antilethe.models import sha256_hex

    days = [f"2026-05-{d:02d}" for d in range(1, 31)] + [f"2026-06-{d:02d}" for d in range(1, 11)]
    for i, day in enumerate(days):
        text = f"answer {i}"
        conn.execute(
            "INSERT INTO responses (id, day, question_slug, model_id, canonical_slug,"
            " serving_host, answer_text, answer_sha256, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,'now')",
            (
                f"r{i}",
                day,
                "q",
                "m",
                "m-v1",
                "HostA" if i < 20 else "HostB",
                text,
                sha256_hex(text),
            ),
        )
    conn.execute("INSERT INTO questions (slug, text, tags, enabled) VALUES ('q','Q?','',1)")
    conn.commit()

    # Store distances directly: a low level, then a jump on the switch day.
    for i in range(1, len(days)):
        stratum = "provider" if i == 20 else "stable"
        value = 0.10 if i < 20 else 0.30
        conn.execute(
            "INSERT INTO distances (method, method_version, day, prev_day, question_slug,"
            " model_id, stratum, from_canonical, to_canonical, from_host, to_host, value)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "cosine_bow",
                "1.0.0",
                days[i],
                days[i - 1],
                "q",
                "m",
                stratum,
                "m-v1",
                "m-v1",
                "HostA" if i <= 20 else "HostB",
                "HostA" if i < 20 else "HostB",
                value + (0.002 if i % 2 else -0.002),
            ),
        )
    conn.commit()

    quiet = Settings(db_path=settings.db_path, min_noise_n=1)
    index = pipeline.build_index(conn, "cosine_bow", settings=quiet)

    assert len(index.changepoints) == 1
    found = index.changepoints[0]
    assert found.model_id == "m"
    assert abs(days.index(found.day) - 20) <= 1
    assert found.before_mean < found.after_mean
    assert found.coincides_with == "provider"


def test_shards_carry_every_feature_as_a_bag(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    slug = "is-coffee-good-for-you"
    shard = pipeline.build_shard(populated, slug, index.snapshot_days[slug], settings=settings)
    snapshot = next(iter(next(iter(shard.models.values())).values()))
    # The marker probes are feature methods, so they appear in the bag too.
    assert {"word_count", "refusal", "hedge_rate", "stance"} <= set(snapshot.features)
    assert snapshot.features["word_count"] == snapshot.word_count


def test_multi_method_export_writes_one_index_per_method(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    pipeline.analyze(populated, ["ncd", "jaccard_ngram"], settings=settings)
    out = tmp_path / "data"
    report = export_dataset(
        populated, out, methods=["cosine_bow", "ncd", "jaccard_ngram"], settings=settings
    )

    assert report.methods == ["cosine_bow", "ncd", "jaccard_ngram"]
    for name in report.methods:
        payload = json.loads((out / "methods" / f"{name}.json").read_text(encoding="utf-8"))
        assert payload["method"]["name"] == name

    primary = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert primary["method"]["name"] == "cosine_bow"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["methods_exported"] == ["cosine_bow", "ncd", "jaccard_ngram"]

    # Strata do not depend on the measure, so every method sees the same events.
    ncd_payload = json.loads((out / "methods" / "ncd.json").read_text(encoding="utf-8"))
    assert ncd_payload["provider_events"] == primary["provider_events"]
    assert ncd_payload["snapshot_days"] == primary["snapshot_days"]
    # But the distances differ, because the measures do.
    assert ncd_payload["noise"]["median"] != primary["noise"]["median"]


def test_single_method_export_still_works(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    report = export_dataset(populated, out, method="cosine_bow", settings=settings)
    assert report.methods == ["cosine_bow"]
    assert (out / "methods" / "cosine_bow.json").exists()


def test_fixture_days_are_what_the_tests_assume() -> None:
    assert len(DAYS) == 4


def test_within_model_summary_is_median_and_quartiles() -> None:
    from antilethe.analysis.pipeline import _within_stat

    assert _within_stat([1.2, 0.9]) is None
    found = _within_stat([0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4])
    assert found is not None
    assert found.median == 1.1
    assert found.q25 == 0.95
    assert found.q75 == 1.25
    assert found.n == 7
    assert found.above_one == 4


def test_within_model_summary_absent_in_the_small_fixture(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """One model with a host switch is not a distribution."""
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert index.decomposition.provider_within is None
    assert index.decomposition.version_within is None

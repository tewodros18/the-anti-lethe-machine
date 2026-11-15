"""Aggregation: the noise floor, the decomposition, and the null discipline."""

from __future__ import annotations

import sqlite3

import pytest

from antilethe.analysis import pipeline, registry
from antilethe.config import Settings
from antilethe.models import Stratum
from sample_archive import DAYS

# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def test_analyze_on_an_empty_archive_fails_loudly(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    """Hard rule: no data must never produce a dataset."""
    with pytest.raises(pipeline.NoDataError):
        pipeline.analyze(conn, ["cosine_bow"], settings=settings)


def test_analyze_records_distances_and_features(populated: sqlite3.Connection) -> None:
    distances = populated.execute("SELECT COUNT(*) FROM distances").fetchone()[0]
    features = populated.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    assert distances > 0
    assert features > 0


def test_analyze_stamps_method_and_version(populated: sqlite3.Connection) -> None:
    """An aggregate must always carry which method produced it."""
    rows = populated.execute("SELECT DISTINCT method, method_version FROM distances").fetchall()
    assert rows == [("cosine_bow", "1.0.0")]


def test_analyze_is_rerunnable(populated: sqlite3.Connection, settings: Settings) -> None:
    before = populated.execute("SELECT COUNT(*) FROM distances").fetchone()[0]
    pipeline.analyze(populated, ["cosine_bow"], settings=settings)
    after = populated.execute("SELECT COUNT(*) FROM distances").fetchone()[0]
    assert before == after


def test_rebuild_recomputes(populated: sqlite3.Connection, settings: Settings) -> None:
    populated.execute("UPDATE distances SET value = 0.999")
    populated.commit()
    pipeline.analyze(populated, ["cosine_bow"], rebuild=True, settings=settings)
    values = [r[0] for r in populated.execute("SELECT value FROM distances")]
    assert all(v != 0.999 for v in values)


def test_requesting_a_missing_method_is_a_hard_error(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    for name in ("embedding", "nli"):
        if not registry.missing_requirements(registry.spec(name)):
            continue
        with pytest.raises(registry.MissingDependencyError):
            pipeline.analyze(populated, [name], settings=settings)


def test_failed_generations_are_excluded(populated: sqlite3.Connection) -> None:
    """An empty answer is not a changed answer."""
    rows = populated.execute(
        "SELECT COUNT(*) FROM distances d JOIN responses r"
        " ON r.question_slug = d.question_slug AND r.model_id = d.model_id AND r.day = d.day"
        " WHERE r.error_type IS NOT NULL"
    ).fetchone()[0]
    assert rows == 0


# ---------------------------------------------------------------------------
# strata
# ---------------------------------------------------------------------------


def test_every_stratum_is_present_in_the_fixture(populated: sqlite3.Connection) -> None:
    strata = {str(r[0]) for r in populated.execute("SELECT DISTINCT stratum FROM distances")}
    assert strata == {"stable", "provider", "version"}


def test_the_host_switch_lands_on_the_right_day(populated: sqlite3.Connection) -> None:
    rows = populated.execute(
        "SELECT day, model_id, from_host, to_host FROM distances WHERE stratum = 'provider'"
    ).fetchall()
    assert [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows] == [
        ("2026-03-03", "openweight/roamer-13b", "Novita", "DeepInfra")
    ]


def test_the_repoint_lands_on_the_right_day(populated: sqlite3.Connection) -> None:
    rows = populated.execute(
        "SELECT day, model_id, from_canonical, to_canonical FROM distances"
        " WHERE stratum = 'version'"
    ).fetchall()
    assert [(str(r[0]), str(r[1])) for r in rows] == [("2026-03-03", "closedlab/oracle")]


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------


def test_index_spans_the_archive(populated: sqlite3.Connection, settings: Settings) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert index.span.first == DAYS[0]
    assert index.span.last == DAYS[-1]
    assert index.span.days == len(DAYS)
    assert index.schema_version == 1


def test_index_carries_the_method(populated: sqlite3.Connection, settings: Settings) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert index.method.name == "cosine_bow"
    assert index.method.version == "1.0.0"


def test_build_index_without_analysis_fails_loudly(
    ingested: sqlite3.Connection, settings: Settings
) -> None:
    with pytest.raises(pipeline.NoDataError):
        pipeline.build_index(ingested, "cosine_bow", settings=settings)


def test_noise_is_computed_from_stable_transitions_only(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    stable_count = populated.execute(
        "SELECT COUNT(*) FROM distances WHERE stratum = 'stable'"
    ).fetchone()[0]
    assert index.noise.n == stable_count
    assert index.noise.insufficient_data is False
    assert index.noise.median is not None


def test_noise_below_the_threshold_is_null_not_zero(
    populated: sqlite3.Connection, tmp_path: object
) -> None:
    """The acceptance criterion for insufficient data."""
    strict = Settings(
        db_path=populated.execute("PRAGMA database_list").fetchone()[2],
        min_noise_n=10_000,
    )
    index = pipeline.build_index(populated, "cosine_bow", settings=strict)

    assert index.noise.insufficient_data is True
    assert index.noise.mean is None
    assert index.noise.median is None
    assert index.noise.p05 is None
    assert index.noise.p95 is None
    assert index.noise.std is None
    # The count is still reported; it is the statistics that are unavailable.
    assert index.noise.n > 0

    for model in index.models:
        assert model.noise.insufficient_data is True
        assert model.noise.median is None


def test_decomposition_ratios_divide_by_the_noise_floor(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    decomposition = index.decomposition

    assert decomposition.stable.mean is not None
    assert decomposition.provider.mean is not None
    assert decomposition.version.mean is not None
    assert decomposition.provider_ratio == pytest.approx(
        decomposition.provider.mean / decomposition.stable.mean, rel=1e-4
    )
    assert decomposition.version_ratio == pytest.approx(
        decomposition.version.mean / decomposition.stable.mean, rel=1e-4
    )


def test_rewrites_move_further_than_noise(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """The fixture is built so the ordering is stable < provider < version."""
    decomposition = pipeline.build_index(populated, "cosine_bow", settings=settings).decomposition
    assert decomposition.stable.mean is not None
    assert decomposition.provider.mean is not None
    assert decomposition.version.mean is not None
    assert decomposition.stable.mean < decomposition.provider.mean
    assert decomposition.stable.mean < decomposition.version.mean


def test_ratio_is_null_when_a_stratum_is_empty(
    conn: sqlite3.Connection, sample_payload: dict[str, object], settings: Settings
) -> None:
    """An unobserved stratum must report null, never zero.

    This is the case the live archive is actually in: no model was repointed in
    the published window, so `version_ratio` has to be an em dash in the UI.
    """
    from antilethe import ledger
    from antilethe.ingest import store
    from antilethe.models import Question, RawResponse
    from sample_archive import response

    questions = [
        Question.from_api(r)
        for r in sample_payload["questions"]["results"]  # type: ignore[index]
    ]
    store.upsert_questions(conn, questions, DAYS[0])

    # Two days, one model, nothing ever changing: stable only.
    for i, day in enumerate(DAYS[:2]):
        rows = [
            RawResponse.from_api(
                response(
                    index=i,
                    day=day,
                    question_slug="is-coffee-good-for-you",
                    model_id="openweight/steady-7b",
                    canonical_slug="openweight/steady-7b",
                    host="Novita",
                    text=f"An answer on day {i}, worded a little differently each time.",
                )
            )
        ]
        store.upsert_responses(conn, rows)
        ledger.append_day(conn, day, ledger.day_leaves(conn, day))

    quiet = Settings(db_path=settings.db_path, min_noise_n=1)
    pipeline.analyze(conn, ["cosine_bow", "markers"], settings=quiet)
    index = pipeline.build_index(conn, "cosine_bow", settings=quiet)

    assert index.decomposition.provider.n == 0
    assert index.decomposition.provider.mean is None
    assert index.decomposition.provider_ratio is None
    assert index.decomposition.version.n == 0
    assert index.decomposition.version.mean is None
    assert index.decomposition.version_ratio is None


def test_timeline_counts_match_the_distances(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    total = sum(p.n_stable + p.n_provider + p.n_version for p in index.timeline)
    stored = populated.execute("SELECT COUNT(*) FROM distances").fetchone()[0]
    assert total == stored


def test_timeline_null_where_a_stratum_had_no_pairs(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    for point in index.timeline:
        if point.n_version == 0:
            assert point.version is None
        if point.n_provider == 0:
            assert point.provider is None


def test_events_are_deduplicated(populated: sqlite3.Connection, settings: Settings) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert len(index.version_events) == 1
    assert len(index.provider_events) == 1
    assert index.version_events[0].day == "2026-03-03"
    assert index.provider_events[0].to_host == "DeepInfra"


def test_cells_use_stable_transitions_only(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    stable_pairs = {
        (str(r[0]), str(r[1]))
        for r in populated.execute(
            "SELECT DISTINCT question_slug, model_id FROM distances WHERE stratum='stable'"
        )
    }
    assert {(c.question_slug, c.model_id) for c in index.cells} == stable_pairs
    assert all(c.n > 0 for c in index.cells)


def test_fingerprints_cover_every_model(populated: sqlite3.Connection, settings: Settings) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert {m.model_id for m in index.models} == {
        "openweight/steady-7b",
        "openweight/roamer-13b",
        "closedlab/oracle",
    }


def test_fingerprint_counts_events_per_model(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    by_id = {m.model_id: m for m in index.models}

    assert by_id["openweight/roamer-13b"].host_switches == 1
    assert by_id["openweight/roamer-13b"].repoints == 0
    assert by_id["closedlab/oracle"].repoints == 1
    assert by_id["closedlab/oracle"].host_switches == 0
    assert by_id["openweight/steady-7b"].host_switches == 0
    assert by_id["openweight/steady-7b"].repoints == 0


def test_fingerprint_reports_hosts_seen(populated: sqlite3.Connection, settings: Settings) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    by_id = {m.model_id: m for m in index.models}
    assert by_id["openweight/roamer-13b"].hosts_seen == ["DeepInfra", "Novita"]
    assert by_id["openweight/steady-7b"].hosts_seen == ["Novita"]


def test_fingerprint_d_provider_null_without_a_switch(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """A model served by one host has no host effect, and must say so."""
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    steady = next(m for m in index.models if m.model_id == "openweight/steady-7b")
    assert steady.d_provider is None
    assert steady.d_version is None
    assert steady.d_stable is not None


def test_fingerprint_daily_is_aligned_to_the_timeline(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    for model in index.models:
        assert len(model.daily) == len(index.timeline)


def test_price_changes_emit_only_on_change(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    # The fixture catalogue is written for one day, so one row per model.
    assert len(index.price_changes) == 3
    assert {p.day for p in index.price_changes} == {DAYS[0]}

    populated.execute(
        "INSERT OR REPLACE INTO model_catalog (model_id, day, prompt_price, completion_price,"
        " selected) VALUES ('closedlab/oracle', '2026-03-02', 0.000003, 0.000009, 1)"
    )
    populated.commit()
    repeated = pipeline.build_index(populated, "cosine_bow", settings=settings)
    # Same prices on a new day is not a change.
    assert len(repeated.price_changes) == 3

    populated.execute(
        "INSERT OR REPLACE INTO model_catalog (model_id, day, prompt_price, completion_price,"
        " selected) VALUES ('closedlab/oracle', '2026-03-03', 0.000004, 0.000009, 1)"
    )
    populated.commit()
    changed = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert len(changed.price_changes) == 4


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------


def test_snapshot_days_include_both_sides_of_every_event(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    """Every comparison the UI points at must be present in a shard."""
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)

    for event in index.version_events + index.provider_events:  # type: ignore[operator]
        affected = [
            str(r[0])
            for r in populated.execute(
                "SELECT question_slug FROM distances WHERE model_id = ? AND day = ?"
                " AND stratum != 'stable'",
                (event.model_id, event.day),
            )
        ]
        assert affected
        for slug in affected:
            days = index.snapshot_days[slug]
            assert event.day in days
            previous = populated.execute(
                "SELECT prev_day FROM distances WHERE question_slug=? AND model_id=? AND day=?",
                (slug, event.model_id, event.day),
            ).fetchone()
            assert str(previous[0]) in days


def test_snapshot_days_include_first_and_last(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    for days in index.snapshot_days.values():
        assert DAYS[0] in days
        assert DAYS[-1] in days


def test_shard_carries_hash_of_the_full_answer(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    slug = "is-coffee-good-for-you"
    shard = pipeline.build_shard(populated, slug, index.snapshot_days[slug], settings=settings)

    assert shard.question_slug == slug
    assert shard.question_text == "Is coffee good for you?"
    for by_day in shard.models.values():
        for snapshot in by_day.values():
            assert len(snapshot.sha256) == 64
            stored = populated.execute(
                "SELECT answer_sha256 FROM responses WHERE answer_text = ? OR answer_text LIKE ?",
                (snapshot.text, snapshot.text[:50] + "%"),
            ).fetchone()
            assert stored is not None


def test_shard_truncates_and_flags_it(populated: sqlite3.Connection, settings: Settings) -> None:
    long_text = "word " * 2000
    populated.execute(
        "UPDATE responses SET answer_text = ? WHERE question_slug = 'is-coffee-good-for-you'"
        " AND day = ?",
        (long_text, DAYS[0]),
    )
    populated.commit()

    tight = Settings(db_path=settings.db_path, min_noise_n=3, snapshot_chars=100)
    shard = pipeline.build_shard(populated, "is-coffee-good-for-you", [DAYS[0]], settings=tight)
    snapshots = [s for by_day in shard.models.values() for s in by_day.values()]
    assert snapshots
    for snapshot in snapshots:
        assert len(snapshot.text) == 100
        assert snapshot.truncated is True


def test_shard_excludes_failed_generations(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    shard = pipeline.build_shard(populated, "is-coffee-good-for-you", [DAYS[1]], settings=settings)
    # closedlab/oracle's only row on day 2 is the failed one.
    assert "closedlab/oracle" not in shard.models


def test_manifest_lists_available_methods(populated: sqlite3.Connection) -> None:
    manifest = pipeline.build_manifest(populated, {"index.json": 123})
    names = {m.name for m in manifest.methods_installed}
    assert {"cosine_bow", "markers"} <= names
    assert manifest.ledger_head is not None
    assert manifest.ledger_head.day == DAYS[-1]
    # Every ledger day is published, oldest first, chained, and the head is its last entry.
    assert [entry.day for entry in manifest.ledger] == sorted(DAYS)
    assert manifest.ledger[0].prev_root is None
    assert all(entry.row_count > 0 for entry in manifest.ledger)
    assert all(
        later.prev_root == earlier.merkle_root
        for earlier, later in zip(manifest.ledger, manifest.ledger[1:], strict=False)
    )
    assert manifest.ledger[-1].merkle_root == manifest.ledger_head.merkle_root
    assert manifest.row_count > 0
    assert manifest.shard_bytes == {"index.json": 123}


def test_quantisation_is_applied(populated: sqlite3.Connection, settings: Settings) -> None:
    """Floats are rounded at construction so two code paths cannot disagree."""
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    assert index.noise.median is not None
    assert index.noise.median == round(index.noise.median, 6)
    for point in index.timeline:
        if point.stable is not None:
            assert point.stable == round(point.stable, 6)


def test_stratum_enum_values_are_the_contract() -> None:
    assert str(Stratum.STABLE) == "stable"
    assert str(Stratum.PROVIDER) == "provider"
    assert str(Stratum.VERSION) == "version"

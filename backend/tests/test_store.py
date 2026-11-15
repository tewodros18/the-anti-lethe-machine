"""Schema, idempotency and the parsing of upstream's awkward field shapes."""

from __future__ import annotations

import sqlite3
from typing import Any

from antilethe.ingest import store
from antilethe.models import ModelRow, Question, RawResponse
from sample_archive import DAYS, sample_day


def test_schema_tables_exist(conn: sqlite3.Connection) -> None:
    names = {
        str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "responses",
        "questions",
        "model_catalog",
        "ledger",
        "ingest_log",
        "distances",
        "features",
        "analysis_runs",
        "meta",
    } <= names


def test_wal_mode_is_enabled(conn: sqlite3.Connection) -> None:
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


def test_upsert_is_idempotent(conn: sqlite3.Connection) -> None:
    """The acceptance criterion: re-running a day adds zero rows."""
    rows = [RawResponse.from_api(r) for r in sample_day(DAYS[0])]

    first = store.upsert_responses(conn, rows)
    assert first == len(rows)

    second = store.upsert_responses(conn, rows)
    assert second == 0
    assert store.row_count(conn) == len(rows)


def test_day_is_done_only_after_success(conn: sqlite3.Connection) -> None:
    store.start_day(conn, DAYS[0])
    assert not store.day_is_done(conn, DAYS[0])

    store.finish_day(conn, DAYS[0], 4)
    assert store.day_is_done(conn, DAYS[0])


def test_failed_day_is_retried(conn: sqlite3.Connection) -> None:
    store.start_day(conn, DAYS[0])
    store.fail_day(conn, DAYS[0], "upstream exploded")
    assert not store.day_is_done(conn, DAYS[0])

    row = conn.execute("SELECT status, error FROM ingest_log WHERE day = ?", (DAYS[0],)).fetchone()
    assert row[0] == "error"
    assert "exploded" in str(row[1])


def test_questions_round_trip(conn: sqlite3.Connection, sample_payload: dict[str, Any]) -> None:
    questions = [Question.from_api(r) for r in sample_payload["questions"]["results"]]
    store.upsert_questions(conn, questions, DAYS[0])

    stored = store.questions(conn)
    assert [q.slug for q in stored] == sorted(q.slug for q in questions)
    coffee = next(q for q in stored if q.slug == "is-coffee-good-for-you")
    assert coffee.text == "Is coffee good for you?"
    assert coffee.tags == ["Health", "Nutrition"]


def test_question_seen_window_widens(
    conn: sqlite3.Connection, sample_payload: dict[str, Any]
) -> None:
    questions = [Question.from_api(r) for r in sample_payload["questions"]["results"]]
    store.upsert_questions(conn, questions, "2026-03-02")
    store.upsert_questions(conn, questions, "2026-03-01")
    store.upsert_questions(conn, questions, "2026-03-05")

    row = conn.execute(
        "SELECT first_seen, last_seen FROM questions WHERE slug = 'is-coffee-good-for-you'"
    ).fetchone()
    assert row[0] == "2026-03-01"
    assert row[1] == "2026-03-05"


def test_model_prices_parse_from_strings(
    conn: sqlite3.Connection, sample_payload: dict[str, Any]
) -> None:
    """Upstream sends prices as decimal strings, not numbers."""
    rows = [ModelRow.from_api(r, DAYS[0]) for r in sample_payload["models"]["results"]]
    store.upsert_models(conn, rows)

    stored = conn.execute(
        "SELECT prompt_price, completion_price, provider FROM model_catalog"
        " WHERE model_id = 'closedlab/oracle'"
    ).fetchone()
    assert stored[0] == 3e-06
    assert stored[1] == 9e-06
    # The catalogue's `provider` column holds the vendor.
    assert stored[2] == "closedlab"


def test_response_parses_serving_host_from_turns() -> None:
    """The one field the whole method depends on."""
    row = RawResponse.from_api(sample_day(DAYS[0])[0])
    assert row.serving_host == "Novita"
    # NOT the top-level `provider`, which is the vendor.
    assert row.model_id.split("/")[0] == "openweight"


def test_response_parses_region_and_reasoning_fraction() -> None:
    row = RawResponse.from_api(sample_day(DAYS[0])[0])
    assert row.region == "SJC"
    assert row.reasoning_frac == 60 / 300


def test_response_cost_parses_from_string() -> None:
    row = RawResponse.from_api(sample_day(DAYS[0])[0])
    assert row.cost == 0.00042


def test_response_with_no_turns_records_nulls() -> None:
    """A failed generation genuinely has no host; it must not get a default."""
    failed = next(r for r in sample_day(DAYS[1]) if r["error_type"])
    row = RawResponse.from_api(failed)
    assert row.serving_host is None
    assert row.region is None
    assert row.reasoning_frac is None
    assert row.error_type == "upstream_timeout"


def test_answer_hash_is_of_the_full_text() -> None:
    import hashlib

    raw = sample_day(DAYS[0])[0]
    row = RawResponse.from_api(raw)
    expected = hashlib.sha256(str(raw["answer_text"]).encode("utf-8")).hexdigest()
    assert row.answer_sha256 == expected
    assert len(row.answer_sha256) == 64


def test_stored_days_and_row_count(populated: sqlite3.Connection) -> None:
    assert store.stored_days(populated) == DAYS
    assert store.row_count(populated) > 0


def test_meta_round_trip(conn: sqlite3.Connection) -> None:
    assert store.get_meta(conn, "archive_range") is None
    store.set_meta(conn, "archive_range", "2026-03-01,2026-03-04")
    assert store.get_meta(conn, "archive_range") == "2026-03-01,2026-03-04"
    store.set_meta(conn, "archive_range", "changed")
    assert store.get_meta(conn, "archive_range") == "changed"


def test_last_ingest_reports_latest_success(conn: sqlite3.Connection) -> None:
    assert store.last_ingest(conn) is None
    store.start_day(conn, DAYS[0])
    store.finish_day(conn, DAYS[0], 1)
    assert store.last_ingest(conn) is not None


def test_complete_day_count(populated: sqlite3.Connection) -> None:
    """A day counts when its ingest finished and its rows are all still there."""
    before = store.complete_day_count(populated)
    assert before >= 1
    # Losing a row from a finished day drops it from the count: the recorded
    # ingest total no longer matches what is stored.
    day = DAYS[0]
    populated.execute(
        "DELETE FROM responses WHERE rowid IN (SELECT rowid FROM responses WHERE day = ? LIMIT 1)",
        (day,),
    )
    assert store.complete_day_count(populated) == before - 1


def test_series_only_days_are_not_complete(conn: sqlite3.Connection) -> None:
    """Rows reached through a question series carry no ingest record."""
    rows = [RawResponse.from_api(r) for r in sample_day(DAYS[0])]
    store.upsert_responses(conn, rows)
    assert store.complete_day_count(conn) == 0
    store.start_day(conn, DAYS[0])
    store.finish_day(conn, DAYS[0], len(rows))
    assert store.complete_day_count(conn) == 1

"""The ingest day loop: idempotency, failure handling, and the ledger chain."""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from antilethe import ledger
from antilethe.config import Settings
from antilethe.ingest import store
from antilethe.ingest.amt_client import AMTError, RawResponse
from antilethe.ingest.runner import ingest_questions, ingest_range
from sample_archive import DAYS, response, sample_day

BASE = "https://amt.invalid/services/amt/api/v1"


def _mock_upstream(payload: dict[str, Any], *, days: list[str] | None = None) -> None:
    """Route the whole API at the synthetic archive."""
    respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(200, json=payload["questions"])
    )
    respx.get(url__startswith=f"{BASE}/models/recent/").mock(
        return_value=httpx.Response(200, json=payload["models"])
    )

    known = set(days or DAYS)

    def export(request: httpx.Request) -> httpx.Response:
        day = request.url.params["day"]
        if day not in known:
            # Upstream has nothing for this day.
            return httpx.Response(200, content=gzip.compress(b""))
        body = "\n".join(json.dumps(row) for row in sample_day(day))
        return httpx.Response(200, content=gzip.compress(body.encode("utf-8")))

    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(side_effect=export)

    def paged(request: httpx.Request) -> httpx.Response:
        day = request.url.params.get("day")
        rows = sample_day(day) if day in known else []
        return httpx.Response(
            200, json={"count": len(rows), "next": None, "previous": None, "results": rows}
        )

    respx.get(url__startswith=f"{BASE}/responses/").mock(side_effect=paged)


@respx.mock
async def test_ingest_populates_the_archive(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    _mock_upstream(sample_payload)

    report = await ingest_range(
        conn, since=date(2026, 3, 1), until=date(2026, 3, 4), settings=settings
    )

    assert report.fetched == 4
    assert report.failed == 0
    assert report.added == store.row_count(conn)
    assert store.stored_days(conn) == DAYS
    assert len(store.questions(conn)) == 2


@respx.mock
async def test_re_ingest_adds_nothing(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """The acceptance criterion: zero new rows and zero new ledger entries."""
    _mock_upstream(sample_payload)
    bounds = {"since": date(2026, 3, 1), "until": date(2026, 3, 4)}

    first = await ingest_range(conn, settings=settings, **bounds)
    rows_after_first = store.row_count(conn)
    ledger_after_first = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]

    second = await ingest_range(conn, settings=settings, **bounds)

    assert first.added > 0
    assert second.added == 0
    assert second.skipped == 4
    assert store.row_count(conn) == rows_after_first
    assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == ledger_after_first


@respx.mock
async def test_force_refetches_without_duplicating(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """--force re-reads upstream but must not duplicate rows or ledger entries."""
    _mock_upstream(sample_payload)
    bounds = {"since": date(2026, 3, 1), "until": date(2026, 3, 4)}

    await ingest_range(conn, settings=settings, **bounds)
    rows = store.row_count(conn)
    entries = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]

    forced = await ingest_range(conn, settings=settings, force=True, **bounds)

    assert forced.fetched == 4
    assert forced.added == 0
    assert store.row_count(conn) == rows
    assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == entries


@respx.mock
async def test_ledger_chain_is_intact_after_parallel_ingest(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """Days are fetched concurrently, so the chain is relinked before returning."""
    _mock_upstream(sample_payload)
    parallel = Settings(
        db_path=settings.db_path,
        amt_base_url=settings.amt_base_url,
        rate_limit_per_min=settings.rate_limit_per_min,
        min_noise_n=3,
        concurrency=4,
    )

    await ingest_range(conn, since=date(2026, 3, 1), until=date(2026, 3, 4), settings=parallel)

    report = ledger.verify_chain(conn)
    assert report.ok, report.breaks
    assert report.days_checked == 4


@respx.mock
async def test_day_ingest_reroots_a_day_partly_stored_by_series_ingest(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """A question-series ingest leaves days with a root over a subset of rows.

    Backfilling those days in full must rebuild each root over the complete
    row set, or ``verify`` would report tampering where there was only growth.
    """
    _mock_upstream(sample_payload)
    partial_day = DAYS[1]
    first_row = RawResponse.from_api(sample_day(partial_day)[0])
    store.upsert_responses(conn, [first_row])
    ledger.append_day(conn, partial_day, ledger.day_leaves(conn, partial_day))
    stale_root = conn.execute(
        "SELECT merkle_root FROM ledger WHERE day = ?", (partial_day,)
    ).fetchone()[0]

    await ingest_range(conn, since=date(2026, 3, 1), until=date(2026, 3, 4), settings=settings)

    rebuilt = conn.execute(
        "SELECT merkle_root, row_count FROM ledger WHERE day = ?", (partial_day,)
    ).fetchone()
    assert rebuilt[0] != stale_root
    assert rebuilt[1] == len(sample_day(partial_day))
    assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == len(DAYS)
    report = ledger.verify_chain(conn)
    assert report.ok, report.breaks


@respx.mock
async def test_a_failed_day_is_reported_and_retried(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """A day upstream cannot serve must fail loudly, not silently vanish."""
    _mock_upstream(sample_payload)
    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(return_value=httpx.Response(500))
    respx.get(url__startswith=f"{BASE}/responses/").mock(return_value=httpx.Response(500))

    report = await ingest_range(
        conn, since=date(2026, 3, 1), until=date(2026, 3, 1), settings=settings
    )

    assert report.failed == 1
    assert report.fetched == 0
    assert store.row_count(conn) == 0
    assert not store.day_is_done(conn, "2026-03-01")
    row = conn.execute("SELECT status FROM ingest_log WHERE day='2026-03-01'").fetchone()
    assert row[0] == "error"


@respx.mock
async def test_one_bad_day_does_not_stop_the_others(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    _mock_upstream(sample_payload)

    def export(request: httpx.Request) -> httpx.Response:
        day = request.url.params["day"]
        if day == "2026-03-02":
            return httpx.Response(500)
        body = "\n".join(json.dumps(row) for row in sample_day(day))
        return httpx.Response(200, content=gzip.compress(body.encode("utf-8")))

    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(side_effect=export)

    def paged(request: httpx.Request) -> httpx.Response:
        day = request.url.params.get("day")
        if day == "2026-03-02":
            return httpx.Response(500)
        rows = sample_day(day)
        return httpx.Response(
            200, json={"count": len(rows), "next": None, "previous": None, "results": rows}
        )

    respx.get(url__startswith=f"{BASE}/responses/").mock(side_effect=paged)

    report = await ingest_range(
        conn, since=date(2026, 3, 1), until=date(2026, 3, 4), settings=settings
    )

    assert report.failed == 1
    assert report.fetched == 3
    assert "2026-03-02" not in store.stored_days(conn)


@respx.mock
async def test_an_inverted_range_is_rejected(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    _mock_upstream(sample_payload)
    with pytest.raises(AMTError):
        await ingest_range(conn, since=date(2026, 3, 4), until=date(2026, 3, 1), settings=settings)


@respx.mock
async def test_progress_is_reported_per_day(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    _mock_upstream(sample_payload)
    lines: list[str] = []

    await ingest_range(
        conn,
        since=date(2026, 3, 1),
        until=date(2026, 3, 2),
        settings=settings,
        progress=lines.append,
    )

    assert any("catalogue" in line for line in lines)
    assert any("2026-03-01" in line for line in lines)
    assert any("2026-03-02" in line for line in lines)


@respx.mock
async def test_discovery_is_skipped_when_both_bounds_are_given(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """Naming both ends must not spend probe requests discovering the span."""
    _mock_upstream(sample_payload)
    counting = respx.get(url__startswith=f"{BASE}/responses/")

    await ingest_range(conn, since=date(2026, 3, 1), until=date(2026, 3, 1), settings=settings)

    # The export path served the day, so /responses/ was never consulted.
    assert counting.call_count == 0
    assert store.get_meta(conn, "archive_range") is None


def _newest_first_pages(
    days: list[str], page_size: int
) -> Callable[[httpx.Request], httpx.Response]:
    """Serve one series newest-first in pages, as upstream does."""
    rows: list[dict[str, Any]] = []
    # The fixture id is built from the day, so index 0 keeps each day's id
    # stable when newer days are prepended to the series.
    for day in sorted(days, reverse=True):
        rows.append(
            response(
                index=0,
                day=day,
                question_slug="is-coffee-good-for-you",
                model_id="openweight/steady-7b",
                canonical_slug="openweight/steady-7b",
                host="Novita",
                text=f"answer on {day}",
            )
        )

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        start = (page - 1) * page_size
        chunk = rows[start : start + page_size]
        has_more = start + page_size < len(rows)
        nxt = (
            f"{BASE}/responses/?question_slug=is-coffee-good-for-you&page={page + 1}"
            f"&page_size={page_size}"
            if has_more
            else None
        )
        return httpx.Response(
            200, json={"count": len(rows), "next": nxt, "previous": None, "results": chunk}
        )

    return handler


@respx.mock
async def test_series_top_up_stops_at_the_first_fully_known_page(
    conn: sqlite3.Connection, settings: Settings, sample_payload: dict[str, Any]
) -> None:
    """The daily cost of a deep question is a couple of small pages per series."""
    days = [f"2026-03-{d:02d}" for d in range(1, 31)]
    respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(200, json=sample_payload["questions"])
    )
    one_model = dict(sample_payload["models"])
    one_model["results"] = [sample_payload["models"]["results"][0]]
    respx.get(url__startswith=f"{BASE}/models/recent/").mock(
        return_value=httpx.Response(200, json=one_model)
    )
    series = respx.get(url__startswith=f"{BASE}/responses/").mock(
        side_effect=_newest_first_pages(days, page_size=5)
    )

    quick = Settings(
        db_path=settings.db_path,
        amt_base_url=settings.amt_base_url,
        rate_limit_per_min=settings.rate_limit_per_min,
        incremental_page_size=5,
    )

    # First run: nothing stored, every page is read.
    first = await ingest_questions(conn, ["is-coffee-good-for-you"], settings=quick)
    assert first.added == 30
    assert series.call_count == 6

    # Upstream gains two days; a top-up reads page one (2 new + 3 known) and
    # page two (all known), then stops.
    series.side_effect = _newest_first_pages([*days, "2026-03-31", "2026-04-01"], page_size=5)
    series.reset()
    second = await ingest_questions(conn, ["is-coffee-good-for-you"], settings=quick)
    assert second.added == 2
    assert series.call_count == 2

    # --force reads everything again, and still adds nothing.
    series.reset()
    forced = await ingest_questions(conn, ["is-coffee-good-for-you"], force=True, settings=quick)
    assert forced.added == 0
    assert series.call_count >= 7

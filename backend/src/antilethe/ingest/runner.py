"""The ingest day loop.

Separated from the HTTP client so the client stays a thin, testable reader and
the loop owns idempotency, progress reporting and the ledger.

Nothing here degrades gracefully into invented data: if a day cannot be
fetched, the day is recorded as failed and the run reports a non-zero failure
count, which the CLI turns into a non-zero exit code.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from .. import ledger
from ..config import Settings, get_settings
from ..models import RawResponse
from . import store
from .amt_client import AMTClient, AMTError

#: Cache key for the discovered archive span.
RANGE_KEY = "archive_range"

ProgressFn = Callable[[str], None]


@dataclass
class DayResult:
    """Outcome for one day."""

    day: str
    status: str
    rows_seen: int = 0
    rows_added: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    """Outcome for a whole run, by day and/or by question series."""

    days: list[DayResult] = field(default_factory=list)
    series: list[SeriesResult] = field(default_factory=list)

    @property
    def added(self) -> int:
        """Rows newly stored."""
        return sum(d.rows_added for d in self.days) + sum(s.rows_added for s in self.series)

    @property
    def failed(self) -> int:
        """Units of work that could not be fetched."""
        return sum(1 for d in self.days if d.status == "error") + sum(
            1 for s in self.series if s.status == "error"
        )

    @property
    def skipped(self) -> int:
        """Days already complete."""
        return sum(1 for d in self.days if d.status == "skipped")

    @property
    def fetched(self) -> int:
        """Units of work fetched this run."""
        return sum(1 for d in self.days if d.status == "ok") + sum(
            1 for s in self.series if s.status == "ok"
        )


async def discover_cached_range(conn: sqlite3.Connection, client: AMTClient) -> tuple[date, date]:
    """The archive's span, discovered once and cached in the store.

    Only the first day is cached: the last day moves every day, so it is always
    rediscovered.
    """
    cached = store.get_meta(conn, RANGE_KEY)
    if cached:
        first_str, _ = cached.split(",", 1)
        first = date.fromisoformat(first_str)
        _, last = await client.discover_range()
        return first, last

    first, last = await client.discover_range()
    store.set_meta(conn, RANGE_KEY, f"{first.isoformat()},{last.isoformat()}")
    return first, last


@dataclass
class SeriesResult:
    """Outcome for one (question, model) series."""

    question_slug: str
    model_id: str
    status: str
    rows_seen: int = 0
    rows_added: int = 0
    error: str | None = None


async def ingest_questions(
    conn: sqlite3.Connection,
    question_slugs: Sequence[str],
    *,
    force: bool = False,
    settings: Settings | None = None,
    progress: ProgressFn | None = None,
) -> IngestReport:
    """Fetch a few questions in full depth instead of a few days in full width.

    Upstream throttles each connection to roughly 25 KB/s, and a whole day's
    export is tens of megabytes, so a full backfill by day is slow. One
    (question, model) series is a single small request covering every day the
    archive holds, which makes this the practical way to build a deep archive
    for a subset of the probe set.

    The result is a deliberately partial archive: full history for the chosen
    questions, nothing for the others. Days are therefore *not* marked complete
    in ``ingest_log``, so a later ``ingest_range`` still fetches them in full.

    Re-running is incremental: each series is read newest-first and stops at
    the first page of days already stored, so a daily top-up is minutes.
    ``force`` reads every series in full instead.
    """
    config = settings or get_settings()
    report = IngestReport()
    emit: ProgressFn = progress or (lambda _: None)
    touched: set[str] = set()

    async with AMTClient(config) as client:
        questions = await client.fetch_questions()
        today = datetime.now(UTC).date().isoformat()
        store.upsert_questions(conn, questions, today)
        models = await client.fetch_models(today)
        store.upsert_models(conn, models)
        emit(f"catalogue: {len(questions)} questions, {len(models)} models")

        known = {q.slug for q in questions}
        unknown = [slug for slug in question_slugs if slug not in known]
        if unknown:
            raise AMTError(f"unknown question slug(s): {', '.join(unknown)}")

        pairs = [(slug, model.model_id) for slug in question_slugs for model in models]
        stored = {} if force else store.known_days(conn, question_slugs)
        mode = "in full" if force else "incrementally"
        emit(f"fetching {len(pairs)} series across {len(question_slugs)} question(s), {mode}")

        width = max(1, config.concurrency)
        batch_days: set[str] = set()
        rerooted = 0
        relinked = 0
        for start in range(0, len(pairs), width):
            batch = pairs[start : start + width]
            results = await asyncio.gather(
                *(
                    client.fetch_series(
                        slug,
                        model_id,
                        known_days=stored.get((slug, model_id), ()),
                        page_size=None if force else config.incremental_page_size,
                    )
                    for slug, model_id in batch
                ),
                return_exceptions=True,
            )
            for (slug, model_id), outcome in zip(batch, results, strict=True):
                if isinstance(outcome, BaseException):
                    message = str(outcome) or outcome.__class__.__name__
                    report.series.append(SeriesResult(slug, model_id, "error", error=message))
                    emit(f"{slug} / {model_id}  FAILED: {message}")
                    continue
                added = store.upsert_responses(conn, outcome)
                batch_days.update(row.day for row in outcome)
                report.series.append(SeriesResult(slug, model_id, "ok", len(outcome), added))
                emit(f"{slug} / {model_id}  {len(outcome):>3} rows seen, {added:>3} new")

            # Rooted after every batch, not once at the end. These days now hold
            # more rows than when they were first rooted, which is an append
            # rather than an alteration, so their roots are rebuilt. Doing it per
            # batch means an interrupted run still leaves every stored row
            # covered by the ledger.
            if batch_days:
                rerooted += ledger.reroot_days(conn, sorted(batch_days))
                relinked += ledger.relink(conn)
                touched.update(batch_days)
                batch_days.clear()

        emit(
            f"ledger: {rerooted} day root(s) rebuilt over {len(touched)} day(s),"
            f" {relinked} link(s) rewritten"
        )

    return report


async def ingest_range(
    conn: sqlite3.Connection,
    *,
    since: date | None = None,
    until: date | None = None,
    force: bool = False,
    settings: Settings | None = None,
    progress: ProgressFn | None = None,
) -> IngestReport:
    """Fetch every day in a range, skipping days already complete."""
    config = settings or get_settings()
    report = IngestReport()
    emit: ProgressFn = progress or (lambda _: None)

    async with AMTClient(config) as client:
        # Discovery costs a round of probe requests, so it is skipped entirely
        # when the caller has already named both ends of the range.
        if since is not None and until is not None:
            start, end = since, until
        else:
            first, last = await discover_cached_range(conn, client)
            start = since or first
            end = until or last
        if start > end:
            raise AMTError(f"empty range: {start.isoformat()} is after {end.isoformat()}")

        # The question set and model catalogue are snapshots, not per-day data.
        questions = await client.fetch_questions()
        today = datetime.now(UTC).date().isoformat()
        store.upsert_questions(conn, questions, today)
        models = await client.fetch_models(today)
        store.upsert_models(conn, models)
        emit(f"catalogue: {len(questions)} questions, {len(models)} models")

        pending: list[date] = []
        for day in _days_between(start, end):
            key = day.isoformat()
            if not force and store.day_is_done(conn, key):
                report.days.append(DayResult(day=key, status="skipped"))
                emit(f"{key}  skipped (already ingested)")
            else:
                pending.append(day)

        # Upstream throttles each connection rather than the account, so days
        # are fetched in parallel batches. Writes stay sequential and in day
        # order: SQLite takes one writer, and the ledger chains day to day.
        width = max(1, config.concurrency)
        relinked = 0
        for batch_start in range(0, len(pending), width):
            batch = pending[batch_start : batch_start + width]
            for day in batch:
                store.start_day(conn, day.isoformat())

            results = await asyncio.gather(
                *(client.fetch_day(day) for day in batch), return_exceptions=True
            )

            for day, outcome in zip(batch, results, strict=True):
                key = day.isoformat()
                if isinstance(outcome, BaseException):
                    message = str(outcome) or outcome.__class__.__name__
                    store.fail_day(conn, key, message)
                    report.days.append(DayResult(day=key, status="error", error=message))
                    emit(f"{key}  FAILED: {message}")
                    continue

                rows: Sequence[RawResponse] = outcome
                added = store.upsert_responses(conn, rows)
                # A day may already have an entry: from a forced re-ingest, or
                # from a question-series ingest that stored some of its rows
                # earlier. The root is rebuilt to cover the rows now present,
                # and left alone when nothing changed, so no entry is ever
                # appended twice.
                ledger.reroot_days(conn, [key])
                store.finish_day(conn, key, len(rows))
                report.days.append(
                    DayResult(day=key, status="ok", rows_seen=len(rows), rows_added=added)
                )
                emit(f"{key}  {len(rows):>5} rows seen, {added:>5} new")

            # Days may have been committed in a different order than they chain
            # in, an earlier range can be backfilled after a later one, and a
            # rebuilt root changes what the next day must point at. Relinking
            # after every batch, not once at the end, means an interrupted run
            # leaves the chain intact.
            relinked += ledger.relink(conn)

        if relinked:
            emit(f"ledger: relinked {relinked} day(s)")

    return report


def _days_between(first: date, last: date) -> list[date]:
    """Every calendar day in an inclusive range."""
    from datetime import timedelta

    return [first + timedelta(days=i) for i in range((last - first).days + 1)]

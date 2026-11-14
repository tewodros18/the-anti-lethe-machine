"""Orchestration: load -> classify -> run methods -> aggregate.

Split in two halves on purpose.

:func:`analyze` is the expensive half. It compares text, so it runs once per
method and persists its results into ``distances`` and ``features``.

:func:`build_index` is the cheap half. It reads those tables and assembles the
dataset. Both the static exporter and the HTTP API call it, which is what makes
them serve byte-identical JSON rather than two implementations that agree today.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from os import environ
from typing import Literal

import polars as pl

from ..config import Settings, get_settings
from ..ingest import store
from ..models import (
    Changepoint,
    Decomposition,
    GapSummary,
    Index,
    InstabilityCell,
    InstalledMethod,
    LedgerHead,
    Manifest,
    MethodRef,
    ModelFingerprint,
    NoiseStats,
    PriceChange,
    ProviderEvent,
    QuestionMeta,
    Snapshot,
    SnapshotShard,
    Span,
    Stratum,
    StratumStat,
    TimelinePoint,
    VersionEvent,
    WithinStat,
    q,
)
from . import changepoints as cp
from . import registry
from .bootstrap import ratio_interval
from .stratify import Observation, Transition, provider_events, transitions, version_events

#: Rows excluded from analysis: a failed generation has no answer to compare,
#: and treating its empty text as a changed answer would invent drift.
ANALYSABLE = "error_type IS NULL AND answer_text <> ''"

#: Keep every Nth day in the snapshot shards, on top of event days.
SNAPSHOT_STRIDE = 7


class NoDataError(RuntimeError):
    """The archive holds nothing to analyse. Never recovered from silently."""


@dataclass
class AnalyzeReport:
    """What one ``analyze`` run did."""

    method: str
    version: str
    n_transitions: int
    n_features: int


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _question_slugs(conn: sqlite3.Connection) -> list[str]:
    """Every question slug with analysable answers."""
    return [
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT question_slug FROM responses WHERE {ANALYSABLE}"
            " ORDER BY question_slug"
        )
    ]


@dataclass(frozen=True)
class _Row:
    """One analysable answer, with its text."""

    id: str
    day: str
    question_slug: str
    model_id: str
    canonical_slug: str | None
    serving_host: str | None
    answer_text: str
    answer_sha256: str
    duration_ms: int | None
    reasoning_frac: float | None
    cost: float | None


def _rows_for_question(conn: sqlite3.Connection, slug: str) -> list[_Row]:
    """Every analysable answer for one question, ordered for series building."""
    cursor = conn.execute(
        "SELECT id, day, question_slug, model_id, canonical_slug, serving_host, answer_text,"
        f" answer_sha256, duration_ms, reasoning_frac, cost FROM responses WHERE {ANALYSABLE}"
        " AND question_slug = ? ORDER BY model_id, day",
        (slug,),
    )
    return [
        _Row(
            id=str(r[0]),
            day=str(r[1]),
            question_slug=str(r[2]),
            model_id=str(r[3]),
            canonical_slug=None if r[4] is None else str(r[4]),
            serving_host=None if r[5] is None else str(r[5]),
            answer_text=str(r[6]),
            answer_sha256=str(r[7]),
            duration_ms=None if r[8] is None else int(r[8]),
            reasoning_frac=None if r[9] is None else float(r[9]),
            cost=None if r[10] is None else float(r[10]),
        )
        for r in cursor
    ]


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


ProgressFn = Callable[[str], None]


def analyze(
    conn: sqlite3.Connection,
    methods: Sequence[str] | None = None,
    *,
    rebuild: bool = False,
    settings: Settings | None = None,
    progress: ProgressFn | None = None,
) -> list[AnalyzeReport]:
    """Run the requested methods and persist their output.

    Requesting a method whose optional dependency is absent is a hard error
    naming the extra, which happens inside :func:`registry.get`.

    ``progress`` is called with a line per question per method and per method
    on completion. A model-backed method over a full archive runs for hours,
    and a run with no output until the end cannot be told from a hung one.
    """
    config = settings or get_settings()
    names = list(methods) if methods else [config.default_method, "markers"]
    emit: ProgressFn = progress or (lambda _: None)

    slugs = _question_slugs(conn)
    if not slugs:
        raise NoDataError("no analysable answers in the archive; run `antilethe ingest` first")

    reports: list[AnalyzeReport] = []
    for name in names:
        spec = registry.spec(name)
        if rebuild:
            conn.execute(
                "DELETE FROM distances WHERE method = ? AND method_version = ?",
                (spec.name, spec.version),
            )
            conn.execute(
                "DELETE FROM features WHERE method = ? AND method_version = ?",
                (spec.name, spec.version),
            )
            conn.commit()

        if spec.kind == "pairwise":
            count = _run_pairwise(conn, name, slugs, emit)
            reports.append(AnalyzeReport(spec.name, spec.version, count, 0))
            emit(f"{spec.name} v{spec.version}: {count} transitions")
        else:
            count = _run_feature(conn, name, slugs, emit)
            reports.append(AnalyzeReport(spec.name, spec.version, 0, count))
            emit(f"{spec.name} v{spec.version}: {count} feature values")

        conn.execute(
            "INSERT OR REPLACE INTO analysis_runs (method, method_version, kind, finished_at,"
            " n_rows) VALUES (?,?,?,?,?)",
            (spec.name, spec.version, spec.kind, datetime.now(UTC).isoformat(), count),
        )
        conn.commit()

    return reports


def _run_pairwise(
    conn: sqlite3.Connection, name: str, slugs: Sequence[str], emit: ProgressFn
) -> int:
    """Compute and store one pairwise method over every transition."""
    spec = registry.spec(name)
    fn = registry.get_pairwise(name)
    prepare = registry.get_prepare(name)
    written = 0

    for i, slug in enumerate(slugs, 1):
        rows = _rows_for_question(conn, slug)
        by_key = {(r.question_slug, r.model_id, r.day): r for r in rows}
        items = transitions(
            Observation(
                day=r.day,
                question_slug=r.question_slug,
                model_id=r.model_id,
                canonical_slug=r.canonical_slug,
                serving_host=r.serving_host,
            )
            for r in rows
        )
        # Incremental: a transition already scored under this method and
        # version is not scored again. A daily run then costs one day's pairs,
        # and a model-backed pass interrupted after hours resumes where it was.
        # ``--rebuild`` deletes first, so it still recomputes everything, and
        # it is the right call after a day is backfilled *between* two stored
        # days: the old pair that jumped the gap stays stored until then.
        done = {
            (str(r[0]), str(r[1]), str(r[2]))
            for r in conn.execute(
                "SELECT model_id, prev_day, day FROM distances"
                " WHERE method = ? AND method_version = ? AND question_slug = ?",
                (spec.name, spec.version, slug),
            )
        }
        pending = [item for item in items if (item.model_id, item.prev_day, item.day) not in done]
        emit(f"  {name}: {slug} ({i}/{len(slugs)}) {len(pending)} of {len(items)} pairs to score")
        if not pending:
            continue
        if prepare is not None:
            # One batched pass over the texts the pending pairs touch, before
            # any pair is compared.
            needed: dict[str, None] = {}
            for item in pending:
                needed[by_key[(item.question_slug, item.model_id, item.prev_day)].answer_text] = (
                    None
                )
                needed[by_key[(item.question_slug, item.model_id, item.day)].answer_text] = None
            prepare(list(needed))
        payload: list[tuple[object, ...]] = []
        for item in pending:
            previous = by_key[(item.question_slug, item.model_id, item.prev_day)]
            current = by_key[(item.question_slug, item.model_id, item.day)]
            value = float(fn(previous.answer_text, current.answer_text))
            payload.append(
                (
                    spec.name,
                    spec.version,
                    item.day,
                    item.prev_day,
                    item.question_slug,
                    item.model_id,
                    str(item.stratum),
                    item.from_canonical,
                    item.to_canonical,
                    item.from_host,
                    item.to_host,
                    value,
                )
            )
        if payload:
            conn.executemany(
                "INSERT OR REPLACE INTO distances (method, method_version, day, prev_day,"
                " question_slug, model_id, stratum, from_canonical, to_canonical, from_host,"
                " to_host, value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                payload,
            )
            conn.commit()
            written += len(payload)
    return written


def _run_feature(
    conn: sqlite3.Connection, name: str, slugs: Sequence[str], emit: ProgressFn
) -> int:
    """Compute and store one feature method over every answer."""
    spec = registry.spec(name)
    fn = registry.get_feature(name)
    prepare = registry.get_prepare(name)
    written = 0

    for i, slug in enumerate(slugs, 1):
        rows = _rows_for_question(conn, slug)
        # Incremental, as for pairwise methods: an answer that already has
        # features under this method and version is skipped.
        done = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT f.response_id FROM features f"
                " JOIN responses r ON r.id = f.response_id"
                " WHERE f.method = ? AND f.method_version = ? AND r.question_slug = ?",
                (spec.name, spec.version, slug),
            )
        }
        pending_rows = [row for row in rows if row.id not in done]
        emit(f"  {name}: {slug} ({i}/{len(slugs)}) {len(pending_rows)} of {len(rows)} answers")
        if not pending_rows:
            continue
        if prepare is not None:
            prepare([r.answer_text for r in pending_rows])
        payload: list[tuple[object, ...]] = []
        for row in pending_rows:
            meta = {
                "model_id": row.model_id,
                "day": row.day,
                "serving_host": row.serving_host,
                "canonical_slug": row.canonical_slug,
                "duration_ms": row.duration_ms,
                "reasoning_frac": row.reasoning_frac,
            }
            for key, value in fn(row.answer_text, meta).items():
                payload.append((spec.name, spec.version, row.id, key, float(value)))
        if payload:
            conn.executemany(
                "INSERT OR REPLACE INTO features (method, method_version, response_id, key, value)"
                " VALUES (?,?,?,?,?)",
                payload,
            )
            conn.commit()
            written += len(payload)
    return written


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _noise_from(values: Sequence[float], minimum: int) -> NoiseStats:
    """Summarise a distance distribution, or report that it is too small.

    Below ``minimum`` samples every statistic is ``None``. There is no honest
    noise floor to divide by, and returning zero would make every ratio
    infinite.
    """
    n = len(values)
    if n < minimum:
        return NoiseStats(
            n=n,
            mean=None,
            median=None,
            p05=None,
            p25=None,
            p75=None,
            p95=None,
            p99=None,
            std=None,
            insufficient_data=True,
        )
    series = pl.Series("d", values, dtype=pl.Float64)

    def pct(fraction: float) -> float | None:
        measured = series.quantile(fraction, interpolation="linear")
        return None if measured is None else q(_as_float(measured))

    return NoiseStats(
        n=n,
        mean=q(_as_float(series.mean())),
        median=pct(0.5),
        p05=pct(0.05),
        p25=pct(0.25),
        p75=pct(0.75),
        p95=pct(0.95),
        p99=pct(0.99),
        std=q(_as_float(series.std())) if n > 1 else None,
        insufficient_data=False,
    )


def _as_float(value: object) -> float:
    """Coerce a polars aggregate, whose static type is a wide union, to a float."""
    if value is None:
        return 0.0
    return float(value)  # type: ignore[arg-type]


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """A ratio that stays ``None`` unless both sides are real and usable."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return q(numerator / denominator)


def _distances_frame(conn: sqlite3.Connection, method: str) -> pl.DataFrame:
    """Every stored distance for one method."""
    cursor = conn.execute(
        "SELECT day, prev_day, question_slug, model_id, stratum, from_canonical, to_canonical,"
        " from_host, to_host, value FROM distances WHERE method = ?",
        (method,),
    )
    columns = [
        "day",
        "prev_day",
        "question_slug",
        "model_id",
        "stratum",
        "from_canonical",
        "to_canonical",
        "from_host",
        "to_host",
        "value",
    ]
    rows = cursor.fetchall()
    if not rows:
        return pl.DataFrame(
            schema={
                "day": pl.Utf8,
                "prev_day": pl.Utf8,
                "question_slug": pl.Utf8,
                "model_id": pl.Utf8,
                "stratum": pl.Utf8,
                "from_canonical": pl.Utf8,
                "to_canonical": pl.Utf8,
                "from_host": pl.Utf8,
                "to_host": pl.Utf8,
                "value": pl.Float64,
                "gap_days": pl.Int64,
            }
        )
    data: dict[str, list[object]] = {
        name: [row[i] for row in rows] for i, name in enumerate(columns)
    }
    # Calendar days between the two answers compared. 1 means adjacent days.
    data["gap_days"] = [
        (date.fromisoformat(str(row[0])) - date.fromisoformat(str(row[1]))).days for row in rows
    ]
    return pl.DataFrame(data, schema_overrides={"value": pl.Float64, "gap_days": pl.Int64})


def _stratum_values(frame: pl.DataFrame, stratum: Stratum) -> list[float]:
    """Distance values within one stratum."""
    if frame.height == 0:
        return []
    subset = frame.filter(pl.col("stratum") == str(stratum))
    return [float(v) for v in subset["value"].to_list()]


def _mean_or_none(values: Sequence[float]) -> float | None:
    """Mean of a possibly empty sequence."""
    return q(sum(values) / len(values)) if values else None


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------


def build_index(
    conn: sqlite3.Connection,
    method: str | None = None,
    *,
    settings: Settings | None = None,
) -> Index:
    """Assemble the full dataset from stored analysis output."""
    config = settings or get_settings()
    name = method or config.default_method
    spec = registry.spec(name)

    days = store.stored_days(conn)
    if not days:
        raise NoDataError("the archive is empty; run `antilethe ingest` first")

    frame = _distances_frame(conn, name)
    if frame.height == 0:
        raise NoDataError(
            f"no distances stored for method {name!r}; run `antilethe analyze --methods {name}`"
        )

    # Strata are compared over adjacent-day transitions only. A model that is
    # not run every day pairs each answer with one several days old, and that
    # distance is not comparable with a one-day one; mixing them would inflate
    # the noise floor that everything else is divided by.
    adjacent = frame.filter(pl.col("gap_days") == 1)
    stable = _stratum_values(adjacent, Stratum.STABLE)
    provider = _stratum_values(adjacent, Stratum.PROVIDER)
    version = _stratum_values(adjacent, Stratum.VERSION)

    noise = _noise_from(stable, config.min_noise_n)
    stable_mean = _mean_or_none(stable)
    provider_mean = _mean_or_none(provider)
    version_mean = _mean_or_none(version)

    items = _transitions_from_frame(frame)
    v_events = version_events(items)
    p_events = provider_events(items)

    timeline = _timeline(frame)
    timeline_days = [point.day for point in timeline]
    fingerprints = _fingerprints(conn, frame, adjacent, config, timeline_days)

    provider_ratio = _ratio(provider_mean, stable_mean)
    version_ratio = _ratio(version_mean, stable_mean)
    decomposition = Decomposition(
        stable=StratumStat(mean=stable_mean, n=len(stable)),
        provider=StratumStat(mean=provider_mean, n=len(provider)),
        version=StratumStat(mean=version_mean, n=len(version)),
        provider_ratio=provider_ratio,
        version_ratio=version_ratio,
        provider_ratio_ci=_interval(provider, stable) if provider_ratio is not None else None,
        version_ratio_ci=_interval(version, stable) if version_ratio is not None else None,
        provider_within=_within(fingerprints, "d_provider"),
        version_within=_within(fingerprints, "d_version"),
    )

    return Index(
        generated_at=datetime.now(UTC).isoformat(),
        method=MethodRef(name=spec.name, version=spec.version),
        span=Span(
            first=days[0],
            last=days[-1],
            days=len(days),
            complete_days=store.complete_day_count(conn),
            series_questions=_series_question_count(conn),
            measured_questions=frame["question_slug"].n_unique(),
        ),
        noise=noise,
        gaps=_gap_summary(frame),
        timeline=timeline,
        decomposition=decomposition,
        models=fingerprints,
        questions=_questions(conn),
        cells=_cells(frame),
        version_events=v_events,
        provider_events=p_events,
        price_changes=_price_changes(conn),
        snapshot_days=_snapshot_days(frame, days),
        changepoints=_changepoints(frame, timeline_days, v_events, p_events),
    )


def _gap_summary(frame: pl.DataFrame) -> GapSummary:
    """Count adjacent-day against multi-day transitions."""
    if frame.height == 0:
        return GapSummary(adjacent=0, multi_day=0, max_days=1, models_with_gaps=0)
    gapped = frame.filter(pl.col("gap_days") > 1)
    return GapSummary(
        adjacent=frame.height - gapped.height,
        multi_day=gapped.height,
        max_days=max(1, int(_as_float(frame["gap_days"].max()))),
        models_with_gaps=gapped["model_id"].n_unique() if gapped.height else 0,
    )


#: Fewer models than this with a ratio of their own and no summary is made.
_WITHIN_MIN_MODELS = 3


def _within_stat(ratios: Sequence[float]) -> WithinStat | None:
    """Median and quartiles of per-model ratios, or ``None`` for too few."""
    if len(ratios) < _WITHIN_MIN_MODELS:
        return None
    ordered = sorted(ratios)
    n = len(ordered)

    def percentile(fraction: float) -> float:
        # Linear interpolation between order statistics (R type 7).
        position = fraction * (n - 1)
        low = int(position)
        high = min(low + 1, n - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return WithinStat(
        median=q(percentile(0.5)) or 0.0,
        q25=q(percentile(0.25)) or 0.0,
        q75=q(percentile(0.75)) or 0.0,
        n=n,
        above_one=sum(1 for r in ordered if r > 1.0),
    )


def _within(models: Sequence[ModelFingerprint], attribute: str) -> WithinStat | None:
    """Per-model ``attribute / d_stable`` over models that have both, summarised."""
    ratios: list[float] = []
    for model in models:
        numerator = getattr(model, attribute)
        if numerator is None or model.d_stable is None or model.d_stable <= 0:
            continue
        ratios.append(numerator / model.d_stable)
    return _within_stat(ratios)


def _interval(
    numerator: Sequence[float], denominator: Sequence[float]
) -> tuple[float, float] | None:
    """A quantised bootstrap interval, or ``None`` when there is too little to resample."""
    found = ratio_interval(numerator, denominator)
    if found is None:
        return None
    lower, upper = found
    low = q(lower)
    high = q(upper)
    if low is None or high is None:
        return None
    return (low, high)


def _series_question_count(conn: sqlite3.Connection) -> int:
    """Questions with analysable answers on more than one day."""
    row = conn.execute(
        "SELECT COUNT(*) FROM (SELECT question_slug FROM responses"
        f" WHERE {ANALYSABLE} GROUP BY question_slug HAVING COUNT(DISTINCT day) > 1)"
    ).fetchone()
    return int(row[0]) if row else 0


def _changepoints(
    frame: pl.DataFrame,
    timeline_days: Sequence[str],
    v_events: Sequence[VersionEvent],
    p_events: Sequence[ProviderEvent],
) -> list[Changepoint]:
    """Level shifts in each model's daily mean distance, joined to known events.

    The series is the per-day mean over *all* strata, not only stable pairs:
    a host switch shows up as a jump in that series, which is exactly what the
    join to ``coincides_with`` is for. A break with no event within a day of it
    is unexplained drift.
    """
    daily = _daily_by_model(frame, timeline_days, stratum=None)

    known: dict[str, dict[str, str]] = {}
    for p_event in p_events:
        known.setdefault(p_event.model_id, {})[p_event.day] = "provider"
    for v_event in v_events:
        # A repoint outranks a host switch on the same day, as in stratify.
        known.setdefault(v_event.model_id, {})[v_event.day] = "version"

    out: list[Changepoint] = []
    for model_id, series in daily.items():
        points: list[tuple[str, float]] = [
            (day, value)
            for day, value in zip(timeline_days, series, strict=True)
            if value is not None
        ]
        if len(points) < 2 * cp.MIN_SEGMENT:
            continue
        values = [value for _, value in points]
        for found in cp.detect(values):
            day = points[found.index][0]
            # An event on the break day or either neighbour explains the break.
            nearby = [
                points[j][0]
                for j in range(max(0, found.index - 1), min(len(points), found.index + 2))
            ]
            kinds = {known.get(model_id, {}).get(d) for d in nearby} - {None}
            coincides: Literal["version", "provider"] | None
            if "version" in kinds:
                coincides = "version"
            elif "provider" in kinds:
                coincides = "provider"
            else:
                coincides = None
            out.append(
                Changepoint(
                    model_id=model_id,
                    day=day,
                    before_mean=q(found.before_mean) or 0.0,
                    after_mean=q(found.after_mean) or 0.0,
                    delta=q(found.delta) or 0.0,
                    n_before=found.n_before,
                    n_after=found.n_after,
                    coincides_with=coincides,
                )
            )
    out.sort(key=lambda c: (c.day, c.model_id))
    return out


def _transitions_from_frame(frame: pl.DataFrame) -> list[Transition]:
    """Rebuild transition records from stored distances, for event dedup."""
    out: list[Transition] = []
    for row in frame.iter_rows(named=True):
        out.append(
            Transition(
                day=str(row["day"]),
                prev_day=str(row["prev_day"]),
                question_slug=str(row["question_slug"]),
                model_id=str(row["model_id"]),
                stratum=Stratum(str(row["stratum"])),
                from_canonical=_opt(row["from_canonical"]),
                to_canonical=_opt(row["to_canonical"]),
                from_host=_opt(row["from_host"]),
                to_host=_opt(row["to_host"]),
            )
        )
    return out


def _timeline(frame: pl.DataFrame) -> list[TimelinePoint]:
    """Per-day mean distance within each stratum, with contributing counts."""
    grouped = (
        frame.group_by(["day", "stratum"])
        .agg(pl.col("value").mean().alias("mean"), pl.len().alias("n"))
        .sort("day")
    )
    per_day: dict[str, dict[str, tuple[float | None, int]]] = {}
    for row in grouped.iter_rows(named=True):
        per_day.setdefault(str(row["day"]), {})[str(row["stratum"])] = (
            q(row["mean"]),
            int(row["n"]),
        )

    points: list[TimelinePoint] = []
    for day in sorted(per_day):
        strata = per_day[day]
        stable = strata.get(str(Stratum.STABLE), (None, 0))
        provider = strata.get(str(Stratum.PROVIDER), (None, 0))
        version = strata.get(str(Stratum.VERSION), (None, 0))
        points.append(
            TimelinePoint(
                day=day,
                stable=stable[0],
                provider=provider[0],
                version=version[0],
                n_stable=stable[1],
                n_provider=provider[1],
                n_version=version[1],
            )
        )
    return points


def _cells(frame: pl.DataFrame) -> list[InstabilityCell]:
    """Per (question, model) mean over STABLE transitions only.

    Restricting to STABLE is the point: it separates how unsettled a question
    is from how much the infrastructure underneath it churned.
    """
    stable_only = frame.filter(pl.col("stratum") == str(Stratum.STABLE))
    if stable_only.height == 0:
        return []
    grouped = (
        stable_only.group_by(["question_slug", "model_id"])
        .agg(pl.col("value").mean().alias("mean"), pl.len().alias("n"))
        .sort(["question_slug", "model_id"])
    )
    cells: list[InstabilityCell] = []
    for row in grouped.iter_rows(named=True):
        value = q(row["mean"])
        if value is None:
            continue
        cells.append(
            InstabilityCell(
                question_slug=str(row["question_slug"]),
                model_id=str(row["model_id"]),
                value=value,
                n=int(row["n"]),
            )
        )
    return cells


def _catalog(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """Latest known ``name`` and vendor per model."""
    rows = conn.execute(
        "SELECT model_id, name, provider FROM model_catalog"
        " WHERE day = (SELECT MAX(day) FROM model_catalog mc WHERE mc.model_id ="
        " model_catalog.model_id)"
    ).fetchall()
    out: dict[str, tuple[str, str]] = {}
    for row in rows:
        model_id = str(row[0])
        name = str(row[1]) if row[1] else model_id
        vendor = str(row[2]) if row[2] else model_id.split("/")[0]
        out[model_id] = (name, vendor)
    return out


def _feature_means(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """Mean of every stored feature, per model."""
    rows = conn.execute(
        "SELECT r.model_id, f.key, AVG(f.value) FROM features f"
        " JOIN responses r ON r.id = f.response_id"
        " GROUP BY r.model_id, f.key"
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        out.setdefault(str(row[0]), {})[str(row[1])] = float(row[2] or 0.0)
    return out


def _response_stats(conn: sqlite3.Connection) -> dict[str, tuple[int, float, float, float]]:
    """Per model: answer count, mean duration, mean cost, mean reasoning fraction."""
    rows = conn.execute(
        "SELECT model_id, COUNT(*), AVG(COALESCE(duration_ms, 0)), AVG(COALESCE(cost, 0)),"
        f" AVG(COALESCE(reasoning_frac, 0)) FROM responses WHERE {ANALYSABLE} GROUP BY model_id"
    ).fetchall()
    return {
        str(r[0]): (int(r[1]), float(r[2] or 0.0), float(r[3] or 0.0), float(r[4] or 0.0))
        for r in rows
    }


def _hosts_seen(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Distinct serving hosts observed per model."""
    rows = conn.execute(
        "SELECT DISTINCT model_id, serving_host FROM responses"
        " WHERE serving_host IS NOT NULL ORDER BY model_id, serving_host"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(str(row[0]), []).append(str(row[1]))
    return out


def _daily_by_model(
    frame: pl.DataFrame, days: Sequence[str], *, stratum: Stratum | None = Stratum.STABLE
) -> dict[str, list[float | None]]:
    """Per-model, per-day mean distance, aligned to ``days``.

    Restricted to one stratum by default (STABLE, for the sparklines); pass
    ``stratum=None`` for the mean over every pair, which is what change-point
    detection wants so that a host switch registers as a jump.
    """
    subset = frame if stratum is None else frame.filter(pl.col("stratum") == str(stratum))
    if subset.height == 0:
        return {}
    grouped = subset.group_by(["model_id", "day"]).agg(pl.col("value").mean().alias("mean"))
    lookup: dict[str, dict[str, float | None]] = {}
    for row in grouped.iter_rows(named=True):
        lookup.setdefault(str(row["model_id"]), {})[str(row["day"])] = q(row["mean"])
    return {model_id: [by_day.get(day) for day in days] for model_id, by_day in lookup.items()}


def _fingerprints(
    conn: sqlite3.Connection,
    frame: pl.DataFrame,
    adjacent: pl.DataFrame,
    config: Settings,
    timeline_days: Sequence[str],
) -> list[ModelFingerprint]:
    """One behavioural summary per model.

    ``frame`` holds every transition and drives the per-day sparkline and the
    event counts; ``adjacent`` is its adjacent-day subset and is what the
    strata means and the per-model noise floor are taken from.
    """
    catalog = _catalog(conn)
    daily = _daily_by_model(frame, timeline_days)
    features = _feature_means(conn)
    stats = _response_stats(conn)
    hosts = _hosts_seen(conn)

    items = _transitions_from_frame(frame)
    repoints: dict[str, int] = {}
    for repoint in version_events(items):
        repoints[repoint.model_id] = repoints.get(repoint.model_id, 0) + 1
    switches: dict[str, int] = {}
    for switch in provider_events(items):
        switches[switch.model_id] = switches.get(switch.model_id, 0) + 1

    out: list[ModelFingerprint] = []
    for model_id in sorted(stats):
        n_answers, mean_duration, mean_cost, mean_reasoning = stats[model_id]
        model_frame = adjacent.filter(pl.col("model_id") == model_id)
        stable = _stratum_values(model_frame, Stratum.STABLE)
        name, vendor = catalog.get(model_id, (model_id, model_id.split("/")[0]))
        marker = features.get(model_id, {})

        out.append(
            ModelFingerprint(
                model_id=model_id,
                name=name,
                vendor=vendor,
                n_answers=n_answers,
                mean_words=q(marker.get("word_count", 0.0)) or 0.0,
                refusal_rate=q(marker.get("refusal", 0.0)) or 0.0,
                hedge_rate=q(marker.get("hedge_rate", 0.0)) or 0.0,
                reasoning_frac=q(mean_reasoning) or 0.0,
                mean_duration_ms=q(mean_duration) or 0.0,
                mean_cost=q(mean_cost) or 0.0,
                d_stable=_mean_or_none(stable),
                d_provider=_mean_or_none(_stratum_values(model_frame, Stratum.PROVIDER)),
                d_version=_mean_or_none(_stratum_values(model_frame, Stratum.VERSION)),
                noise=_noise_from(stable, config.min_noise_n),
                repoints=repoints.get(model_id, 0),
                host_switches=switches.get(model_id, 0),
                hosts_seen=hosts.get(model_id, []),
                daily=daily.get(model_id, [None] * len(timeline_days)),
            )
        )
    return out


def _questions(conn: sqlite3.Connection) -> dict[str, QuestionMeta]:
    """Question prose and tags, keyed by slug."""
    return {row.slug: QuestionMeta(text=row.text, tags=row.tags) for row in store.questions(conn)}


def _price_changes(conn: sqlite3.Connection) -> list[PriceChange]:
    """Only the days a model's listed price actually changed."""
    rows = conn.execute(
        "SELECT model_id, day, prompt_price, completion_price FROM model_catalog"
        " ORDER BY model_id, day"
    ).fetchall()
    out: list[PriceChange] = []
    previous: dict[str, tuple[float | None, float | None]] = {}
    for row in rows:
        model_id = str(row[0])
        pair = (
            None if row[2] is None else float(row[2]),
            None if row[3] is None else float(row[3]),
        )
        if previous.get(model_id) != pair:
            out.append(
                PriceChange(
                    day=str(row[1]),
                    model_id=model_id,
                    prompt_price=q(pair[0], 12),
                    completion_price=q(pair[1], 12),
                )
            )
            previous[model_id] = pair
    return out


def _snapshot_days(frame: pl.DataFrame, days: Sequence[str]) -> dict[str, list[str]]:
    """Which days each question keeps a snapshot for.

    First day, last day, every seventh day, plus both sides of every non-stable
    transition. The last part is what guarantees the compare view can always
    show the pair that any event in the UI points at.
    """
    scaffold = _scaffold_days(days)

    per_question: dict[str, set[str]] = {}
    if frame.height:
        events = frame.filter(pl.col("stratum") != str(Stratum.STABLE))
        for row in events.iter_rows(named=True):
            slug = str(row["question_slug"])
            bucket = per_question.setdefault(slug, set())
            bucket.add(str(row["day"]))
            bucket.add(str(row["prev_day"]))
        for slug in frame["question_slug"].unique().to_list():
            per_question.setdefault(str(slug), set())

    return {slug: sorted(scaffold | extra) for slug, extra in sorted(per_question.items())}


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _scaffold_days(days: Sequence[str]) -> set[str]:
    """First day, last day, and every ``SNAPSHOT_STRIDE``-th day between."""
    ordered = sorted(days)
    if not ordered:
        return set()
    return {ordered[0], ordered[-1], *ordered[::SNAPSHOT_STRIDE]}


def _event_days_by_model(conn: sqlite3.Connection, question_slug: str) -> dict[str, set[str]]:
    """Both sides of every non-stable transition in one question, per model.

    Strata are a property of the transition, not of the measure, so any
    method's rows give the same answer and the query does not pick one.
    """
    rows = conn.execute(
        "SELECT DISTINCT model_id, day, prev_day FROM distances"
        " WHERE question_slug = ? AND stratum != ?",
        (question_slug, str(Stratum.STABLE)),
    ).fetchall()
    out: dict[str, set[str]] = {}
    for row in rows:
        bucket = out.setdefault(str(row[0]), set())
        bucket.add(str(row[1]))
        bucket.add(str(row[2]))
    return out


def build_shard(
    conn: sqlite3.Connection,
    question_slug: str,
    keep_days: Sequence[str],
    *,
    prune: bool = False,
    settings: Settings | None = None,
) -> SnapshotShard:
    """Build one question's snapshot shard for the given days.

    With ``prune`` set, a model keeps a day only if it is a scaffold day (first,
    last, every seventh) or one side of *that model's own* host switch or
    rebuild. Without it, every model keeps every day in ``keep_days``. The
    difference is size: an event day for one model is an ordinary day for the
    other forty, and keeping all of them put a whole archive's shards past
    what a static host will serve. The compare view reads each model's own day
    list, so a pruned shard loses nothing it can show.
    """
    config = settings or get_settings()
    if not keep_days:
        return SnapshotShard(question_slug=question_slug, question_text="", models={})

    scaffold = _scaffold_days(store.stored_days(conn)) if prune else set()
    events = _event_days_by_model(conn, question_slug) if prune else {}

    marks = ",".join("?" for _ in keep_days)
    rows = conn.execute(
        "SELECT r.id, r.model_id, r.day, r.answer_text, r.answer_sha256, r.canonical_slug,"
        " r.serving_host, r.duration_ms"
        f" FROM responses r WHERE {ANALYSABLE} AND r.question_slug = ? AND r.day IN ({marks})"
        " ORDER BY r.model_id, r.day",
        (question_slug, *keep_days),
    ).fetchall()
    features = _features_for(conn, [str(r[0]) for r in rows])

    models: dict[str, dict[str, Snapshot]] = {}
    for row in rows:
        if prune:
            model_id, day = str(row[1]), str(row[2])
            if day not in scaffold and day not in events.get(model_id, ()):
                continue
        text = str(row[3])
        trimmed = text[: config.snapshot_chars]
        bag = features.get(str(row[0]), {})
        word_count = int(bag["word_count"]) if "word_count" in bag else len(text.split())
        models.setdefault(str(row[1]), {})[str(row[2])] = Snapshot(
            text=trimmed,
            truncated=len(text) > len(trimmed),
            sha256=str(row[4]),
            canonical_slug=None if row[5] is None else str(row[5]),
            serving_host=None if row[6] is None else str(row[6]),
            duration_ms=None if row[7] is None else int(row[7]),
            word_count=word_count,
            refusal=bool(bag.get("refusal", 0.0)),
            features=bag,
        )

    text_row = conn.execute(
        "SELECT text FROM questions WHERE slug = ?", (question_slug,)
    ).fetchone()
    return SnapshotShard(
        question_slug=question_slug,
        question_text=str(text_row[0]) if text_row else "",
        models=models,
    )


#: SQLite's default bound-parameter limit is comfortably above this.
_IN_CHUNK = 900


def _features_for(
    conn: sqlite3.Connection, response_ids: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Every stored feature for the given responses, keyed by response id."""
    out: dict[str, dict[str, float]] = {}
    for start in range(0, len(response_ids), _IN_CHUNK):
        chunk = response_ids[start : start + _IN_CHUNK]
        marks = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"SELECT response_id, key, value FROM features WHERE response_id IN ({marks})",
            tuple(chunk),
        ):
            value = q(row[2])
            if value is None:
                continue
            out.setdefault(str(row[0]), {})[str(row[1])] = value
    return out


def iter_shards(
    conn: sqlite3.Connection, index: Index, *, settings: Settings | None = None
) -> Iterator[SnapshotShard]:
    """Every question's shard, in index order, pruned per model for size."""
    for slug, keep_days in index.snapshot_days.items():
        yield build_shard(conn, slug, keep_days, prune=True, settings=settings)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def git_sha() -> str:
    """The commit this build came from, as reported by CI or by git."""
    for key in ("GITHUB_SHA", "GIT_COMMIT"):
        value = environ.get(key)
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def antilethe_version() -> str:
    """The installed package version."""
    try:
        return package_version("antilethe")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def build_manifest(
    conn: sqlite3.Connection,
    shard_bytes: dict[str, int],
    *,
    generated_at: str | None = None,
    methods_exported: Sequence[str] = (),
) -> Manifest:
    """Build provenance for one export."""
    config = get_settings()
    head_row = conn.execute(
        "SELECT day, merkle_root FROM ledger ORDER BY day DESC LIMIT 1"
    ).fetchone()

    def checkpoint(name: str) -> str | None:
        """Which model a model-backed method is configured to use."""
        if name in ("embedding", "embedding_map"):
            return config.embedding_model
        if name in ("nli", "stance_nli"):
            return config.nli_model
        return None

    return Manifest(
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        git_sha=git_sha(),
        antilethe_version=antilethe_version(),
        methods_installed=[
            InstalledMethod(name=s.name, kind=s.kind, version=s.version, model=checkpoint(s.name))
            for s in registry.available()
        ],
        methods_exported=list(methods_exported),
        ledger_head=(
            None
            if head_row is None
            else LedgerHead(day=str(head_row[0]), merkle_root=str(head_row[1]))
        ),
        row_count=store.row_count(conn),
        shard_bytes=shard_bytes,
    )


def _opt(value: object) -> str | None:
    """``None``-preserving string coercion."""
    return None if value is None else str(value)

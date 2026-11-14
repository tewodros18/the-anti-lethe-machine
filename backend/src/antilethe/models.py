"""The data contract.

Every shape the exporter writes and the API serves is defined here, once. The
TypeScript interfaces in ``frontend/src/lib/data/types.ts`` mirror these
field-for-field; ``tests/test_contract.py`` enforces that by generating a JSON
Schema from these models and checking the exported JSON against it.

Two conventions hold throughout:

* A quantity that upstream did not supply, or that there was not enough data to
  compute, is ``None``. It is never zero and never a default. The frontend
  renders it as an em dash.
* Floats are rounded at construction (:func:`q`) so that the static exporter and
  the HTTP API serialise byte-identical JSON for the same logical resource.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal[1] = 1

#: Decimal places every exported float is rounded to.
FLOAT_PRECISION = 6


def q(value: float | None, places: int = FLOAT_PRECISION) -> float | None:
    """Quantise a float for export, preserving ``None``.

    Rounding happens once, here, so two code paths computing the same aggregate
    cannot disagree in the last bits of a float and produce differing JSON.
    """
    if value is None:
        return None
    return round(float(value), places)


def sha256_hex(text: str) -> str:
    """SHA-256 of ``text`` as 64 lowercase hex characters."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Strict(BaseModel):
    """Base for contract models: no extra fields, no silent coercion surprises."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Stratification
# ---------------------------------------------------------------------------


class Stratum(StrEnum):
    """Why an archived answer changed between two days.

    These three are never summed into one number. See ``analysis/stratify.py``.
    """

    STABLE = "stable"
    PROVIDER = "provider"
    VERSION = "version"


# ---------------------------------------------------------------------------
# Ingest-side models (upstream shapes)
# ---------------------------------------------------------------------------


class Question(Strict):
    """A curated probe question."""

    slug: str
    text: str
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    first_seen: str | None = None
    last_seen: str | None = None

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> Question:
        """Parse ``/questions/``. Upstream names the prose ``question_text``."""
        return cls(
            slug=str(row["slug"]),
            text=str(row.get("question_text") or ""),
            tags=[str(t) for t in (row.get("tags") or [])],
            enabled=bool(row.get("enabled", True)),
        )


class ModelRow(Strict):
    """One model's catalogue entry as of a given day."""

    model_id: str
    day: str
    canonical_slug: str | None = None
    name: str | None = None
    #: The *vendor* (upstream calls this ``provider``), e.g. "anthropic".
    #: Not the serving host. Stored in the ``model_catalog.provider`` column.
    vendor: str | None = None
    context_length: int | None = None
    prompt_price: float | None = None
    completion_price: float | None = None
    selected: bool = True

    @classmethod
    def from_api(cls, row: dict[str, Any], day: str) -> ModelRow:
        """Parse ``/models/recent/``. Prices arrive as decimal strings."""
        return cls(
            model_id=str(row["model_id"]),
            day=day,
            canonical_slug=_opt_str(row.get("canonical_slug")),
            name=_opt_str(row.get("name")),
            vendor=_opt_str(row.get("provider")),
            context_length=_opt_int(row.get("context_length")),
            prompt_price=_opt_float(row.get("prompt_price")),
            completion_price=_opt_float(row.get("completion_price")),
            selected=bool(row.get("selected", True)),
        )


class RawResponse(Strict):
    """One archived answer: question x model x day.

    The serving host lives at ``turns[0].provider`` and is *not* the top-level
    ``provider`` field, which is the vendor. Conflating the two would collapse
    the provider and version strata into each other, which is the one mistake
    this project exists to avoid.
    """

    id: str
    day: str
    question_slug: str
    model_id: str
    canonical_slug: str | None
    serving_host: str | None
    region: str | None
    answer_text: str
    answer_sha256: str
    tokens: int | None
    reasoning_frac: float | None
    cost: float | None
    duration_ms: int | None
    error_type: str | None
    created_at: str | None

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> RawResponse:
        """Parse one ``/responses/?detail=full`` record (or one export line).

        Tolerates an absent or empty ``turns`` list, which is how upstream
        represents a failed generation: the host, region and reasoning fraction
        are then genuinely unknown and recorded as ``None``.
        """
        turns = row.get("turns") or []
        turn: dict[str, Any] = turns[0] if turns and isinstance(turns[0], dict) else {}
        usage: dict[str, Any] = turn.get("usage") or {}
        meta: dict[str, Any] = turn.get("openrouter_metadata") or {}
        completion_details: dict[str, Any] = usage.get("completion_tokens_details") or {}

        completion_tokens = _opt_int(usage.get("completion_tokens"))
        reasoning_tokens = _opt_int(completion_details.get("reasoning_tokens"))
        reasoning_frac: float | None = None
        if completion_tokens is not None and reasoning_tokens is not None and completion_tokens > 0:
            reasoning_frac = reasoning_tokens / completion_tokens

        answer_text = str(row.get("answer_text") or "")
        return cls(
            id=str(row["id"]),
            day=str(row["day"]),
            question_slug=str(row["question_slug"]),
            model_id=str(row["model_id"]),
            canonical_slug=_opt_str(row.get("canonical_slug")),
            serving_host=_opt_str(turn.get("provider")),
            region=_opt_str(meta.get("region")),
            answer_text=answer_text,
            answer_sha256=sha256_hex(answer_text),
            tokens=_opt_int(row.get("tokens")),
            reasoning_frac=reasoning_frac,
            cost=_opt_float(row.get("cost")),
            duration_ms=_opt_int(row.get("duration_ms")),
            error_type=_opt_str(row.get("error_type")),
            created_at=_opt_str(row.get("created_at")),
        )


def _opt_str(value: object) -> str | None:
    """Coerce to ``str``, mapping absent and empty values to ``None``."""
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _opt_int(value: object) -> int | None:
    """Coerce to ``int``, mapping unparseable values to ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _opt_float(value: object) -> float | None:
    """Coerce to ``float``. Upstream sends money as a decimal string."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class LedgerEntry(Strict):
    """One day's Merkle root, chained to the previous day's."""

    day: str
    row_count: int
    merkle_root: str
    prev_root: str | None
    fetched_at: str


class ChainBreak(Strict):
    """A single detected inconsistency in the ledger."""

    day: str
    kind: Literal["root_mismatch", "prev_mismatch", "missing_rows", "hash_mismatch", "unrooted_day"]
    detail: str


class ChainReport(Strict):
    """Result of recomputing every root from stored rows."""

    days_checked: int
    ok: bool
    breaks: list[ChainBreak] = Field(default_factory=list)
    head: LedgerEntry | None = None


class MerkleProof(Strict):
    """An inclusion proof for one answer hash under a day's root."""

    leaf: str
    #: ``(side, hash)`` pairs from leaf to root; ``side`` is the sibling's side.
    path: list[tuple[Literal["left", "right"], str]]
    root: str
    day: str


# ---------------------------------------------------------------------------
# Analysis output (§5)
# ---------------------------------------------------------------------------


class MethodRef(Strict):
    """Which method produced an aggregate, so two datasets cannot be confused."""

    name: str
    version: str


class MethodSpecOut(Strict):
    """An installed analysis method, as reported by ``/api/v1/methods``."""

    name: str
    kind: Literal["pairwise", "feature"]
    version: str
    requires: list[str] = Field(default_factory=list)
    description: str = ""
    available: bool = True


class Span(Strict):
    """The archive window covered by a dataset."""

    first: str
    last: str
    days: int
    complete_days: int
    #: Questions with answers on more than one day, i.e. with a series to
    #: measure drift over. The catalogue size is not coverage; this is.
    series_questions: int
    #: Questions with at least one distance under *this* measure. A costly
    #: measure may have been run over a subset of the archive, and its index
    #: must say so rather than borrow the archive's coverage.
    measured_questions: int


class NoiseStats(Strict):
    """Distribution of pairwise distance over STABLE transitions only.

    This is the denominator for every other number in the dataset. When ``n``
    is below the configured threshold every statistic is ``None`` and
    ``insufficient_data`` is true: there is no honest noise floor to divide by.
    """

    n: int
    mean: float | None
    median: float | None
    p05: float | None
    p25: float | None
    p75: float | None
    p95: float | None
    p99: float | None
    std: float | None
    insufficient_data: bool


class TimelinePoint(Strict):
    """One day's mean distance within each stratum."""

    day: str
    stable: float | None
    provider: float | None
    version: float | None
    n_stable: int
    n_provider: int
    n_version: int


class StratumStat(Strict):
    """Mean distance and sample size for one stratum."""

    mean: float | None
    n: int


class WithinStat(Strict):
    """A ratio taken inside each model, then summarised across models.

    The pooled ratio divides one population of pairs by another, and the two
    populations are not the same models: host switches happen almost only to
    open-weight models. If those models are steadier day to day than the
    first-party models that never switch, the pooled ratio can fall below one
    while every individual model's ratio sits above it. This is that check.
    """

    median: float
    q25: float
    q75: float
    #: Models with pairs in both strata, i.e. with a ratio of their own.
    n: int
    #: How many of them have a ratio above one.
    above_one: int


class Decomposition(Strict):
    """The project's headline numbers.

    ``provider_ratio`` is how many times larger a same-model host switch is
    than sampling noise. ``version_ratio`` is the same for an actual rebuild.
    Each comes pooled over all pairs and, in ``*_within``, as the median of
    the per-model ratios; where the two disagree, the within-model figure is
    the one to believe and the site leads with it.
    """

    stable: StratumStat
    provider: StratumStat
    version: StratumStat
    provider_ratio: float | None
    version_ratio: float | None
    #: 95% percentile-bootstrap interval for each ratio, from 1000 resamples of
    #: both strata with a fixed seed. ``None`` whenever the ratio is, and also
    #: when either stratum is too small to resample meaningfully.
    provider_ratio_ci: tuple[float, float] | None
    version_ratio_ci: tuple[float, float] | None
    #: The same ratios inside each model, summarised across models. ``None``
    #: when fewer than three models have pairs in both strata.
    provider_within: WithinStat | None
    version_within: WithinStat | None


class Changepoint(Strict):
    """A detected shift in the level of one model's daily distance series.

    Found by binary segmentation with a least-squares cost and a BIC-style
    penalty (see ``analysis/changepoints.py``), over the model's per-day mean
    distance across all strata. ``coincides_with`` says whether a known event
    for that model falls within a day of the break: ``"version"`` or
    ``"provider"`` names an explanation, ``None`` is unexplained drift, which is
    the case worth a researcher's attention.
    """

    model_id: str
    day: str
    before_mean: float
    after_mean: float
    delta: float
    n_before: int
    n_after: int
    coincides_with: Literal["version", "provider"] | None


class ModelFingerprint(Strict):
    """Per-model behavioural summary."""

    model_id: str
    name: str
    vendor: str
    n_answers: int
    mean_words: float
    refusal_rate: float
    hedge_rate: float
    reasoning_frac: float
    mean_duration_ms: float
    mean_cost: float
    d_stable: float | None
    d_provider: float | None
    d_version: float | None
    noise: NoiseStats
    repoints: int
    host_switches: int
    hosts_seen: list[str]
    #: Per-day mean over this model's STABLE transitions, index-aligned to the
    #: index's ``timeline`` days. Feeds the sparkline in the model table. A day
    #: on which the model contributed no stable pair is ``None``, so the line
    #: breaks rather than implying a measurement of zero.
    daily: list[float | None]


class InstabilityCell(Strict):
    """How unsettled one question is for one model, infrastructure held fixed."""

    question_slug: str
    model_id: str
    value: float
    n: int


class VersionEvent(Strict):
    """A vendor repointed a model-id alias at a new dated build."""

    day: str
    model_id: str
    from_canonical: str | None
    to_canonical: str | None


class ProviderEvent(Strict):
    """The same build was served by a different inference host."""

    day: str
    model_id: str
    from_host: str | None
    to_host: str | None


class PriceChange(Strict):
    """A day on which a model's listed price changed."""

    day: str
    model_id: str
    prompt_price: float | None
    completion_price: float | None


class QuestionMeta(Strict):
    """Question prose and tags, keyed by slug in the index."""

    text: str
    tags: list[str]


class Summary(Strict):
    """The scalar head of a dataset.

    Field-for-field a subset of :class:`Index`, and built from the same object,
    so ``/api/v1/summary`` is byte-identical to that slice of ``index.json``.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    generated_at: str
    method: MethodRef
    span: Span
    noise: NoiseStats
    decomposition: Decomposition
    n_models: int
    n_questions: int
    n_version_events: int
    n_provider_events: int


class GapSummary(Strict):
    """How many transitions compare adjacent days, and how many span a gap.

    A transition pairs an answer with the model's previous *available* answer
    to the same question. When a model is not run every day, that previous
    answer is several days old, and a distance over three days is not the same
    quantity as a distance over one. The noise floor and the strata comparison
    therefore use adjacent-day transitions only; the gapped ones still appear
    in per-day views and are counted here so the exclusion is visible.
    """

    #: Transitions whose two days are consecutive.
    adjacent: int
    #: Transitions spanning two or more days.
    multi_day: int
    #: The longest gap seen, in days; 1 when there are none.
    max_days: int
    #: Models with at least one multi-day transition.
    models_with_gaps: int


class Index(Strict):
    """``index.json`` — everything except snapshot text."""

    schema_version: Literal[1] = SCHEMA_VERSION
    generated_at: str
    method: MethodRef
    span: Span
    noise: NoiseStats
    gaps: GapSummary
    timeline: list[TimelinePoint]
    decomposition: Decomposition
    models: list[ModelFingerprint]
    questions: dict[str, QuestionMeta]
    cells: list[InstabilityCell]
    version_events: list[VersionEvent]
    provider_events: list[ProviderEvent]
    price_changes: list[PriceChange]
    snapshot_days: dict[str, list[str]]
    changepoints: list[Changepoint]

    def summary(self) -> Summary:
        """Project the scalar head, for ``/api/v1/summary``."""
        return Summary(
            schema_version=self.schema_version,
            generated_at=self.generated_at,
            method=self.method,
            span=self.span,
            noise=self.noise,
            decomposition=self.decomposition,
            n_models=len(self.models),
            n_questions=len(self.questions),
            n_version_events=len(self.version_events),
            n_provider_events=len(self.provider_events),
        )


# ---------------------------------------------------------------------------
# Snapshots (§5.2)
# ---------------------------------------------------------------------------


class Snapshot(Strict):
    """One archived answer, trimmed for transport."""

    text: str
    truncated: bool
    #: SHA-256 of the *full* answer, not of the trimmed ``text``.
    sha256: str
    canonical_slug: str | None
    serving_host: str | None
    duration_ms: int | None
    word_count: int
    refusal: bool
    #: Every per-answer feature any installed feature method produced: the
    #: marker probes, token counts, the stance distribution, and the answer's
    #: ``map_x`` / ``map_y`` position in its question's embedding plane. A bag
    #: rather than fixed fields, so a new feature method reaches the site
    #: without a contract change. Absent features are absent, not zero.
    features: dict[str, float]


class SnapshotShard(Strict):
    """``snapshots/{question_slug}.json`` — every kept day for one question."""

    question_slug: str
    question_text: str
    #: model_id -> day -> snapshot
    models: dict[str, dict[str, Snapshot]]


# ---------------------------------------------------------------------------
# Manifest (§5.3)
# ---------------------------------------------------------------------------


class InstalledMethod(Strict):
    """A method present in the environment that produced a build."""

    name: str
    kind: str
    version: str
    #: For a model-backed method, the checkpoint that produced its numbers. A
    #: distance under BGE-base and one under BGE-small are not the same measure,
    #: and the build has to say which it was.
    model: str | None


class LedgerHead(Strict):
    """The most recent ledger entry at build time."""

    day: str
    merkle_root: str


class Manifest(Strict):
    """``manifest.json`` — build provenance."""

    schema_version: Literal[1] = SCHEMA_VERSION
    generated_at: str
    git_sha: str
    antilethe_version: str
    methods_installed: list[InstalledMethod]
    #: Pairwise methods this build exported a full index for. The first is
    #: ``index.json``; every one is also at ``methods/<name>.json``, so the site
    #: can show the same decomposition under each measure.
    methods_exported: list[str]
    ledger_head: LedgerHead | None
    row_count: int
    shard_bytes: dict[str, int]


# ---------------------------------------------------------------------------
# API-only shapes
# ---------------------------------------------------------------------------


class Health(Strict):
    """``/health``."""

    status: Literal["ok", "empty"]
    db_days: int
    last_ingest: str | None


class ModelDetail(Strict):
    """``/api/v1/models/{model_id}``."""

    fingerprint: ModelFingerprint
    price_history: list[PriceChange]
    version_events: list[VersionEvent]
    provider_events: list[ProviderEvent]


class SnapshotSeries(Strict):
    """``/api/v1/snapshots/{question_slug}``."""

    question_slug: str
    question_text: str
    models: dict[str, dict[str, Snapshot]]


class DiffToken(Strict):
    """One word-level diff token."""

    op: Literal["equal", "insert", "delete"]
    text: str


class ComparePayload(Strict):
    """``/api/v1/compare`` — two snapshots, their stratum, and a word diff."""

    question_slug: str
    question_text: str
    model_id: str
    day_a: str
    day_b: str
    a: Snapshot | None
    b: Snapshot | None
    stratum: Stratum | None
    distance: float | None
    diff: list[DiffToken]


class Event(Strict):
    """``/api/v1/events`` — a repoint or a host switch, in one shape."""

    kind: Literal["version", "provider"]
    day: str
    model_id: str
    from_value: str | None
    to_value: str | None

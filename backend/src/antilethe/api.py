"""FastAPI app serving the same computed data as the static export.

Every route builds its payload from ``analysis.pipeline``, the module the
exporter uses, so a self-hosted API and the published site report the same
numbers. The dataset is built once per process and cached, because
``build_index`` reads the whole distances table.

The published site does not need this app at all. It exists for local
exploration and for anyone self-hosting.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import ledger
from .analysis import pipeline, registry
from .config import Settings, get_settings
from .diffing import word_diff
from .ingest import store
from .models import (
    ComparePayload,
    Event,
    Health,
    Index,
    InstabilityCell,
    LedgerEntry,
    MerkleProof,
    MethodSpecOut,
    ModelDetail,
    ModelFingerprint,
    PriceChange,
    Question,
    Snapshot,
    SnapshotSeries,
    Stratum,
    Summary,
    TimelinePoint,
)
from .serialize import to_json


def _connection(request: Request) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request.

    Defined at module level on purpose. This module uses postponed annotation
    evaluation, and FastAPI resolves a route's annotations against its module
    globals, so a dependency alias declared inside ``create_app`` would be
    invisible and every ``conn`` parameter would be mistaken for a query
    parameter.
    """
    settings: Settings = request.app.state.settings
    conn = store.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(_connection)]


class DatasetCache:
    """Holds the built dataset for the process lifetime.

    Invalidated by restarting the server, which is also what re-running
    ``analyze`` implies.
    """

    def __init__(self) -> None:
        self._by_method: dict[str, Index] = {}

    def get(self, conn: sqlite3.Connection, method: str, settings: Settings) -> Index:
        """Build or return the cached dataset for one method."""
        if method not in self._by_method:
            self._by_method[method] = pipeline.build_index(conn, method, settings=settings)
        return self._by_method[method]

    def clear(self) -> None:
        """Drop every cached dataset."""
        self._by_method.clear()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. Title and docs path are fixed by the spec."""
    config = settings or get_settings()
    cache = DatasetCache()

    app = FastAPI(
        title="Anti-Lethe API",
        version="1",
        description=(
            "Drift measurements over the Internet Archive's Ask Me Twice archive, "
            "stratified by whether a change came from sampling noise, a change of "
            "inference host, or an actual model rebuild."
        ),
        docs_url="/docs",
    )
    # Read back by the module-level connection dependency.
    app.state.settings = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def dataset(conn: sqlite3.Connection, method: str | None) -> Index:
        """The built dataset, or a 404 explaining what to run."""
        name = method or config.default_method
        try:
            registry.spec(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return cache.get(conn, name, config)
        except pipeline.NoDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def raw(model: object) -> Response:
        """Serialise through the shared serialiser, not FastAPI's encoder.

        This is what makes a route byte-identical to the matching slice of
        ``index.json``: one serialiser, one float rendering, one key order.
        """
        return Response(content=to_json(model), media_type="application/json")  # type: ignore[arg-type]

    # -- meta ---------------------------------------------------------------

    @app.get("/health", response_model=Health)
    def health(conn: Conn) -> Response:
        """Liveness plus how much archive is present."""
        days = store.stored_days(conn)
        return raw(
            Health(
                status="ok" if days else "empty",
                db_days=len(days),
                last_ingest=store.last_ingest(conn),
            )
        )

    @app.get("/api/v1/methods", response_model=list[MethodSpecOut])
    def methods() -> Response:
        """Every registered method and whether it is installed here."""
        installed = {s.name for s in registry.available()}
        payload = [
            MethodSpecOut(
                name=s.name,
                kind=s.kind,
                version=s.version,
                requires=list(s.requires),
                description=s.description,
                available=s.name in installed,
            )
            for s in registry.all_specs()
        ]
        return Response(
            content="[" + ",".join(to_json(p) for p in payload) + "]",
            media_type="application/json",
        )

    # -- dataset ------------------------------------------------------------

    @app.get("/api/v1/summary", response_model=Summary)
    def summary(conn: Conn, method: str | None = None) -> Response:
        """The scalar head of the dataset."""
        return raw(dataset(conn, method).summary())

    @app.get("/api/v1/index", response_model=Index)
    def full_index(conn: Conn, method: str | None = None) -> Response:
        """The whole dataset, byte-identical to ``index.json``.

        This is what the frontend reads when ``PUBLIC_API_BASE`` is set, so that
        pointing the site at a self-hosted API is one switch rather than a
        second data-loading path.
        """
        return raw(dataset(conn, method))

    @app.get("/api/v1/manifest")
    def manifest(conn: Conn) -> Response:
        """Build provenance, byte-identical to ``manifest.json``."""
        return raw(pipeline.build_manifest(conn, {}))

    @app.get("/api/v1/timeline", response_model=list[TimelinePoint])
    def timeline(
        conn: Conn,
        method: str | None = None,
        model: str | None = None,
        question: str | None = None,
    ) -> Response:
        """Per-day stratified means, optionally narrowed to a model or question.

        With no filter this is exactly ``index.json``'s ``timeline``. With a
        filter it is recomputed from the distances table for that subset.
        """
        if model is None and question is None:
            points = dataset(conn, method).timeline
        else:
            points = _filtered_timeline(conn, method or config.default_method, model, question)
        return _json_list(points)

    @app.get("/api/v1/models", response_model=list[ModelFingerprint])
    def models(conn: Conn, method: str | None = None) -> Response:
        """Every model's fingerprint."""
        return _json_list(dataset(conn, method).models)

    @app.get("/api/v1/models/{model_id:path}", response_model=ModelDetail)
    def model_detail(model_id: str, conn: Conn, method: str | None = None) -> Response:
        """One model's fingerprint, price history and events."""
        index = dataset(conn, method)
        fingerprint = next((m for m in index.models if m.model_id == model_id), None)
        if fingerprint is None:
            raise HTTPException(status_code=404, detail=f"unknown model {model_id!r}")
        return raw(
            ModelDetail(
                fingerprint=fingerprint,
                price_history=[p for p in index.price_changes if p.model_id == model_id],
                version_events=[e for e in index.version_events if e.model_id == model_id],
                provider_events=[e for e in index.provider_events if e.model_id == model_id],
            )
        )

    @app.get("/api/v1/questions", response_model=list[Question])
    def questions(conn: Conn) -> Response:
        """The curated question set."""
        return _json_list(store.questions(conn))

    @app.get("/api/v1/cells", response_model=list[InstabilityCell])
    def cells(conn: Conn, method: str | None = None) -> Response:
        """Per (question, model) instability over STABLE transitions only."""
        return _json_list(dataset(conn, method).cells)

    @app.get("/api/v1/events", response_model=list[Event])
    def events(
        conn: Conn,
        kind: Annotated[Literal["version", "provider"] | None, Query()] = None,
        method: str | None = None,
    ) -> Response:
        """Repoints and host switches in one shape."""
        index = dataset(conn, method)
        out: list[Event] = []
        if kind in (None, "version"):
            out.extend(
                Event(
                    kind="version",
                    day=e.day,
                    model_id=e.model_id,
                    from_value=e.from_canonical,
                    to_value=e.to_canonical,
                )
                for e in index.version_events
            )
        if kind in (None, "provider"):
            out.extend(
                Event(
                    kind="provider",
                    day=e.day,
                    model_id=e.model_id,
                    from_value=e.from_host,
                    to_value=e.to_host,
                )
                for e in index.provider_events
            )
        out.sort(key=lambda e: (e.day, e.model_id, e.kind))
        return _json_list(out)

    @app.get("/api/v1/prices", response_model=list[PriceChange])
    def prices(conn: Conn, method: str | None = None) -> Response:
        """Days on which a listed price changed."""
        return _json_list(dataset(conn, method).price_changes)

    # -- snapshots ----------------------------------------------------------

    @app.get("/api/v1/snapshots/{question_slug}", response_model=SnapshotSeries)
    def snapshots(
        question_slug: str, conn: Conn, model: str | None = None, method: str | None = None
    ) -> Response:
        """Archived answers for one question, on the days the export keeps."""
        index = dataset(conn, method)
        keep = index.snapshot_days.get(question_slug)
        if keep is None:
            raise HTTPException(status_code=404, detail=f"unknown question {question_slug!r}")
        shard = pipeline.build_shard(conn, question_slug, keep, settings=config)
        models_out = shard.models if model is None else {model: shard.models.get(model, {})}
        return raw(
            SnapshotSeries(
                question_slug=shard.question_slug,
                question_text=shard.question_text,
                models=models_out,
            )
        )

    @app.get("/api/v1/compare", response_model=ComparePayload)
    def compare(
        conn: Conn,
        question: Annotated[str, Query()],
        model: Annotated[str, Query()],
        a: Annotated[str, Query()],
        b: Annotated[str, Query()],
        method: str | None = None,
    ) -> Response:
        """Two archived answers, their stratum, and a word-level diff."""
        name = method or config.default_method
        snap_a = _snapshot_for(conn, question, model, a, config)
        snap_b = _snapshot_for(conn, question, model, b, config)

        row = conn.execute(
            "SELECT stratum, value FROM distances WHERE method = ? AND question_slug = ?"
            " AND model_id = ? AND day = ? AND prev_day = ?",
            (name, question, model, b, a),
        ).fetchone()
        stratum: Stratum | None = None
        distance: float | None = None
        if row is not None:
            stratum = Stratum(str(row[0]))
            distance = float(row[1])
        elif snap_a is not None and snap_b is not None:
            # Not a stored transition (the two days are not adjacent in the
            # series), so classify the pair directly rather than reporting none.
            from .analysis.stratify import classify

            stratum = classify(
                snap_a.canonical_slug,
                snap_b.canonical_slug,
                snap_a.serving_host,
                snap_b.serving_host,
            )

        text_row = conn.execute("SELECT text FROM questions WHERE slug = ?", (question,)).fetchone()
        return raw(
            ComparePayload(
                question_slug=question,
                question_text=str(text_row[0]) if text_row else "",
                model_id=model,
                day_a=a,
                day_b=b,
                a=snap_a,
                b=snap_b,
                stratum=stratum,
                distance=distance,
                diff=word_diff(
                    snap_a.text if snap_a else "",
                    snap_b.text if snap_b else "",
                ),
            )
        )

    # -- ledger -------------------------------------------------------------

    @app.get("/api/v1/ledger/{day}")
    def ledger_day(day: str, conn: Conn, sha256: str | None = None) -> Response:
        """One day's ledger entry, with an inclusion proof when a hash is given."""
        row = conn.execute(
            "SELECT day, row_count, merkle_root, prev_root, fetched_at FROM ledger WHERE day = ?",
            (day,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no ledger entry for {day}")
        entry = LedgerEntry(
            day=str(row[0]),
            row_count=int(row[1]),
            merkle_root=str(row[2]),
            prev_root=None if row[3] is None else str(row[3]),
            fetched_at=str(row[4]),
        )
        proof: MerkleProof | None = None
        if sha256:
            proof = ledger.proof_for_response(conn, day, sha256)
            if proof is None:
                raise HTTPException(
                    status_code=404, detail=f"{sha256} is not in the day {day} tree"
                )
        body = (
            '{"entry":' + to_json(entry) + ',"proof":' + (to_json(proof) if proof else "null") + "}"
        )
        return Response(content=body, media_type="application/json")

    return app


def _json_list(items: Sequence[BaseModel]) -> Response:
    """Serialise a sequence of contract models through the shared serialiser."""
    return Response(
        content="[" + ",".join(to_json(i) for i in items) + "]",
        media_type="application/json",
    )


def _snapshot_for(
    conn: sqlite3.Connection, question: str, model: str, day: str, config: Settings
) -> Snapshot | None:
    """One archived answer as a snapshot, or ``None`` when absent."""
    shard = pipeline.build_shard(conn, question, [day], settings=config)
    return shard.models.get(model, {}).get(day)


def _filtered_timeline(
    conn: sqlite3.Connection, method: str, model: str | None, question: str | None
) -> list[TimelinePoint]:
    """Recompute the timeline for a model and/or question subset."""
    clauses = ["method = ?"]
    params: list[str] = [method]
    if model:
        clauses.append("model_id = ?")
        params.append(model)
    if question:
        clauses.append("question_slug = ?")
        params.append(question)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT day, stratum, AVG(value), COUNT(*) FROM distances WHERE {where}"
        " GROUP BY day, stratum ORDER BY day",
        params,
    ).fetchall()

    from .models import q

    per_day: dict[str, dict[str, tuple[float, int]]] = {}
    for row in rows:
        per_day.setdefault(str(row[0]), {})[str(row[1])] = (float(row[2]), int(row[3]))

    out: list[TimelinePoint] = []
    for day in sorted(per_day):
        strata = per_day[day]
        stable = strata.get(str(Stratum.STABLE))
        provider = strata.get(str(Stratum.PROVIDER))
        version = strata.get(str(Stratum.VERSION))
        out.append(
            TimelinePoint(
                day=day,
                stable=q(stable[0]) if stable else None,
                provider=q(provider[0]) if provider else None,
                version=q(version[0]) if version else None,
                n_stable=stable[1] if stable else 0,
                n_provider=provider[1] if provider else 0,
                n_version=version[1] if version else 0,
            )
        )
    return out


@lru_cache(maxsize=1)
def app_singleton() -> FastAPI:
    """Module-level app for ``uvicorn antilethe.api:app``."""
    return create_app()


app = app_singleton()

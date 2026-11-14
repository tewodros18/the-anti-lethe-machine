"""Shared test fixtures.

The synthetic archive these fixtures build is the only fabricated data in the
project. It lives under ``tests/`` and nothing in ``src/`` can import it. The
data itself is built by ``sample_archive.py``; this module only wires it into
pytest fixtures.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from antilethe.analysis import pipeline
from antilethe.config import Settings
from antilethe.ingest import store
from antilethe.models import ModelRow, Question, RawResponse
from sample_archive import DAYS, sample_day

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_payload() -> dict[str, Any]:
    """The static fixture file."""
    return json.loads((FIXTURES / "amt_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway database."""
    return Settings(
        db_path=tmp_path / "archive.db",
        amt_base_url="https://amt.invalid/services/amt/api/v1",
        # The fixture archive is small; the production 30-sample floor would
        # null every statistic and make the aggregates untestable.
        min_noise_n=3,
        rate_limit_per_min=100000,
    )


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    """An empty archive with the schema applied."""
    connection = store.connect(settings.db_path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def ingested(conn: sqlite3.Connection, sample_payload: dict[str, Any]) -> sqlite3.Connection:
    """An archive holding the full synthetic window, not yet analysed."""
    from antilethe import ledger

    questions = [Question.from_api(r) for r in sample_payload["questions"]["results"]]
    store.upsert_questions(conn, questions, DAYS[0])
    store.upsert_models(
        conn, [ModelRow.from_api(r, DAYS[0]) for r in sample_payload["models"]["results"]]
    )

    for day in DAYS:
        rows = [RawResponse.from_api(r) for r in sample_day(day)]
        store.upsert_responses(conn, rows)
        ledger.append_day(conn, day, ledger.day_leaves(conn, day))
        store.finish_day(conn, day, len(rows))
    return conn


@pytest.fixture
def populated(ingested: sqlite3.Connection, settings: Settings) -> sqlite3.Connection:
    """An archive that has been ingested and analysed."""
    pipeline.analyze(ingested, ["cosine_bow", "markers"], settings=settings)
    return ingested

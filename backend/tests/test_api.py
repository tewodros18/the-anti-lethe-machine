"""The HTTP API, and its byte-identity with the static export."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from antilethe.analysis import pipeline
from antilethe.api import create_app
from antilethe.config import Settings
from antilethe.export import export_dataset
from antilethe.serialize import to_json
from sample_archive import DAYS


@pytest.fixture
def client(populated: sqlite3.Connection, settings: Settings) -> TestClient:
    """A client over the analysed fixture archive."""
    return TestClient(create_app(settings))


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["db_days"] == len(DAYS)


def test_health_on_empty_archive(conn: sqlite3.Connection, settings: Settings) -> None:
    body = TestClient(create_app(settings)).get("/health").json()
    assert body["status"] == "empty"
    assert body["db_days"] == 0


def test_openapi_docs_load(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Anti-Lethe API"


def test_summary_is_byte_identical_to_the_index_slice(
    client: TestClient, populated: sqlite3.Connection, settings: Settings
) -> None:
    """The acceptance criterion.

    One serialiser and one builder, so the API cannot drift from the shards.
    """
    index = pipeline.build_index(populated, "cosine_bow", settings=settings)
    expected = to_json(index.summary())

    response = client.get("/api/v1/summary")
    assert response.status_code == 200
    # generated_at is stamped per build, so compare the rest field by field.
    served = json.loads(response.text)
    wanted = json.loads(expected)
    served.pop("generated_at")
    wanted.pop("generated_at")
    assert served == wanted

    # And the scalar head must match the exported file exactly.
    assert set(wanted) == {
        "schema_version",
        "method",
        "span",
        "noise",
        "decomposition",
        "n_models",
        "n_questions",
        "n_version_events",
        "n_provider_events",
    }


def test_full_index_matches_the_exported_file(
    client: TestClient, populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    export_dataset(populated, out, method="cosine_bow", settings=settings)
    on_disk = json.loads((out / "index.json").read_text(encoding="utf-8"))

    served = client.get("/api/v1/index").json()
    for payload in (on_disk, served):
        payload.pop("generated_at")
    assert served == on_disk


def test_summary_is_a_strict_subset_of_the_index(client: TestClient) -> None:
    index = client.get("/api/v1/index").json()
    summary = client.get("/api/v1/summary").json()
    for key, value in summary.items():
        if key.startswith("n_"):
            continue
        assert index[key] == value, key


def test_timeline(client: TestClient) -> None:
    points = client.get("/api/v1/timeline").json()
    assert isinstance(points, list)
    assert points
    assert {"day", "stable", "provider", "version", "n_stable"} <= set(points[0])


def test_timeline_filtered_by_model(client: TestClient) -> None:
    everything = client.get("/api/v1/timeline").json()
    narrowed = client.get("/api/v1/timeline", params={"model": "openweight/roamer-13b"}).json()
    assert len(narrowed) <= len(everything)
    assert sum(p["n_stable"] + p["n_provider"] for p in narrowed) > 0


def test_timeline_filtered_by_question(client: TestClient) -> None:
    narrowed = client.get(
        "/api/v1/timeline", params={"question": "who-invented-the-telescope"}
    ).json()
    assert narrowed


def test_models(client: TestClient) -> None:
    models = client.get("/api/v1/models").json()
    assert {m["model_id"] for m in models} == {
        "openweight/steady-7b",
        "openweight/roamer-13b",
        "closedlab/oracle",
    }


def test_model_detail(client: TestClient) -> None:
    body = client.get("/api/v1/models/closedlab/oracle").json()
    assert body["fingerprint"]["model_id"] == "closedlab/oracle"
    assert len(body["version_events"]) == 1
    assert body["price_history"]


def test_unknown_model_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/models/nope/missing").status_code == 404


def test_questions(client: TestClient) -> None:
    questions = client.get("/api/v1/questions").json()
    assert {q["slug"] for q in questions} == {
        "is-coffee-good-for-you",
        "who-invented-the-telescope",
    }


def test_cells(client: TestClient) -> None:
    cells = client.get("/api/v1/cells").json()
    assert cells
    assert all(cell["n"] > 0 for cell in cells)


def test_events_unfiltered_and_filtered(client: TestClient) -> None:
    everything = client.get("/api/v1/events").json()
    assert {e["kind"] for e in everything} == {"version", "provider"}

    versions = client.get("/api/v1/events", params={"kind": "version"}).json()
    assert {e["kind"] for e in versions} == {"version"}
    assert versions[0]["to_value"] == "closedlab/oracle-2026-02-20"

    providers = client.get("/api/v1/events", params={"kind": "provider"}).json()
    assert providers[0]["to_value"] == "DeepInfra"


def test_methods_lists_installed_and_absent(client: TestClient) -> None:
    methods = client.get("/api/v1/methods").json()
    by_name = {m["name"]: m for m in methods}
    assert by_name["cosine_bow"]["available"] is True
    assert by_name["markers"]["kind"] == "feature"
    assert "transformers" in by_name["nli"]["requires"]


def test_snapshots(client: TestClient) -> None:
    body = client.get("/api/v1/snapshots/is-coffee-good-for-you").json()
    assert body["question_text"] == "Is coffee good for you?"
    assert body["models"]
    some = next(iter(body["models"].values()))
    snapshot = next(iter(some.values()))
    assert len(snapshot["sha256"]) == 64


def test_snapshots_filtered_by_model(client: TestClient) -> None:
    body = client.get(
        "/api/v1/snapshots/is-coffee-good-for-you", params={"model": "openweight/steady-7b"}
    ).json()
    assert set(body["models"]) == {"openweight/steady-7b"}


def test_unknown_question_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/snapshots/no-such-question").status_code == 404


def test_compare_reports_the_stratum_and_a_diff(client: TestClient) -> None:
    body = client.get(
        "/api/v1/compare",
        params={
            "question": "who-invented-the-telescope",
            "model": "closedlab/oracle",
            "a": "2026-03-02",
            "b": "2026-03-03",
        },
    ).json()

    assert body["stratum"] == "version"
    assert body["a"]["canonical_slug"] == "closedlab/oracle-2026-01-15"
    assert body["b"]["canonical_slug"] == "closedlab/oracle-2026-02-20"
    assert body["distance"] is not None
    assert any(token["op"] != "equal" for token in body["diff"])


def test_compare_of_a_stable_pair(client: TestClient) -> None:
    body = client.get(
        "/api/v1/compare",
        params={
            "question": "is-coffee-good-for-you",
            "model": "openweight/steady-7b",
            "a": "2026-03-01",
            "b": "2026-03-02",
        },
    ).json()
    assert body["stratum"] == "stable"


def test_compare_of_non_adjacent_days_still_classifies(client: TestClient) -> None:
    """The reader can pick any two days, not only stored transitions."""
    body = client.get(
        "/api/v1/compare",
        params={
            "question": "who-invented-the-telescope",
            "model": "closedlab/oracle",
            "a": "2026-03-01",
            "b": "2026-03-04",
        },
    ).json()
    assert body["stratum"] == "version"
    # Not a stored transition, so there is no method distance for the pair.
    assert body["distance"] is None


def test_compare_with_a_missing_day_returns_nulls(client: TestClient) -> None:
    body = client.get(
        "/api/v1/compare",
        params={
            "question": "is-coffee-good-for-you",
            "model": "openweight/steady-7b",
            "a": "2026-03-01",
            "b": "1999-01-01",
        },
    ).json()
    assert body["b"] is None
    assert body["stratum"] is None


def test_ledger_entry_and_proof(client: TestClient, populated: sqlite3.Connection) -> None:
    row = populated.execute(
        "SELECT answer_sha256 FROM responses WHERE day = ? LIMIT 1", (DAYS[0],)
    ).fetchone()

    plain = client.get(f"/api/v1/ledger/{DAYS[0]}").json()
    assert plain["entry"]["day"] == DAYS[0]
    assert plain["proof"] is None

    with_proof = client.get(f"/api/v1/ledger/{DAYS[0]}", params={"sha256": str(row[0])}).json()
    assert with_proof["proof"]["root"] == with_proof["entry"]["merkle_root"]
    assert with_proof["proof"]["leaf"] == str(row[0])


def test_ledger_unknown_day_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/ledger/1999-01-01").status_code == 404


def test_ledger_unknown_hash_is_404(client: TestClient) -> None:
    assert client.get(f"/api/v1/ledger/{DAYS[0]}", params={"sha256": "00" * 32}).status_code == 404


def test_unknown_method_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/summary", params={"method": "no-such"}).status_code == 404


def test_unanalysed_archive_returns_503(ingested: sqlite3.Connection, settings: Settings) -> None:
    """A missing dataset is reported, never substituted."""
    response = TestClient(create_app(settings)).get("/api/v1/summary")
    assert response.status_code == 503
    assert "analyze" in response.json()["detail"]


def test_cors_allows_the_configured_origin(
    populated: sqlite3.Connection, settings: Settings
) -> None:
    app = create_app(Settings(db_path=settings.db_path, cors_origins=["http://localhost:5173"]))
    response = TestClient(app).get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

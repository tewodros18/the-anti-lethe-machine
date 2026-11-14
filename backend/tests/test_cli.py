"""The command line. Every failure path must exit non-zero."""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import respx
from typer.testing import CliRunner

from antilethe.cli import app
from sample_archive import DAYS, sample_day

BASE = "https://amt.invalid/services/amt/api/v1"

runner = CliRunner()


def _env(db: Path) -> dict[str, str]:
    """Point the CLI at a throwaway archive and a mocked upstream."""
    return {
        "ANTILETHE_DB_PATH": str(db),
        "ANTILETHE_AMT_BASE_URL": BASE,
        "ANTILETHE_RATE_LIMIT_PER_MIN": "100000",
        "ANTILETHE_MIN_NOISE_N": "3",
    }


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_methods_lists_installed_and_missing() -> None:
    result = runner.invoke(app, ["methods"])
    assert result.exit_code == 0
    assert "cosine_bow" in result.stdout
    assert "markers" in result.stdout
    # The optional methods are listed either way, with their status.
    assert "nli" in result.stdout


def test_analyze_without_data_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze"], env=_env(tmp_path / "a.db"))
    assert result.exit_code == 1


def test_export_without_data_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["export", "--out", str(tmp_path / "out")], env=_env(tmp_path / "a.db")
    )
    assert result.exit_code == 1


def test_verify_without_a_ledger_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["verify"], env=_env(tmp_path / "a.db"))
    assert result.exit_code == 1


def test_bad_date_exits_non_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ingest", "--since", "not-a-date"], env=_env(tmp_path / "a.db"))
    assert result.exit_code == 1


def test_analyze_with_a_missing_extra_exits_non_zero(
    populated: sqlite3.Connection, settings: Any
) -> None:
    from antilethe.analysis import registry

    name = next(
        (n for n in ("embedding", "nli") if registry.missing_requirements(registry.spec(n))),
        None,
    )
    if name is None:  # pragma: no cover - both extras installed
        return

    result = runner.invoke(
        app,
        ["analyze", "--methods", name],
        env={
            "ANTILETHE_DB_PATH": str(settings.db_path),
            "ANTILETHE_MIN_NOISE_N": "3",
        },
    )
    assert result.exit_code == 1


def test_verify_detects_tampering(populated: sqlite3.Connection, settings: Any) -> None:
    """The acceptance criterion, through the CLI."""
    env = {"ANTILETHE_DB_PATH": str(settings.db_path)}

    clean = runner.invoke(app, ["verify"], env=env)
    assert clean.exit_code == 0
    assert "intact" in clean.stdout

    populated.execute(
        "UPDATE responses SET answer_text = 'rewritten'"
        " WHERE id = (SELECT id FROM responses LIMIT 1)"
    )
    populated.commit()

    broken = runner.invoke(app, ["verify"], env=env)
    assert broken.exit_code == 1


@respx.mock
def test_full_pipeline_through_the_cli(tmp_path: Path, sample_payload: dict[str, Any]) -> None:
    """ingest -> analyze -> verify -> export, as the workflow runs it."""
    respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(200, json=sample_payload["questions"])
    )
    respx.get(url__startswith=f"{BASE}/models/recent/").mock(
        return_value=httpx.Response(200, json=sample_payload["models"])
    )

    def export(request: httpx.Request) -> httpx.Response:
        day = request.url.params["day"]
        if day not in DAYS:
            return httpx.Response(200, content=gzip.compress(b""))
        body = "\n".join(json.dumps(row) for row in sample_day(day))
        return httpx.Response(200, content=gzip.compress(body.encode("utf-8")))

    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(side_effect=export)
    respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )

    db = tmp_path / "archive.db"
    env = _env(db)

    ingest = runner.invoke(app, ["ingest", "--since", DAYS[0], "--until", DAYS[-1]], env=env)
    assert ingest.exit_code == 0, ingest.stdout
    assert "rows added" in ingest.stdout

    # Re-running adds nothing.
    again = runner.invoke(app, ["ingest", "--since", DAYS[0], "--until", DAYS[-1]], env=env)
    assert again.exit_code == 0
    assert "0 rows added" in again.stdout.replace(",", "")

    analyze = runner.invoke(app, ["analyze"], env=env)
    assert analyze.exit_code == 0, analyze.stdout
    assert "cosine_bow" in analyze.stdout

    verify = runner.invoke(app, ["verify"], env=env)
    assert verify.exit_code == 0, verify.stdout

    out = tmp_path / "data"
    export_result = runner.invoke(app, ["export", "--out", str(out)], env=env)
    assert export_result.exit_code == 0, export_result.stdout
    assert (out / "index.json").exists()
    assert (out / "manifest.json").exists()
    assert list((out / "snapshots").glob("*.json"))

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == 1
    assert index["models"]

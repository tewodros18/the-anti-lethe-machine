"""The data contract, enforced in both directions.

The spec requires that ``models.py`` and ``frontend/src/lib/data/types.ts``
match field-for-field. Prose cannot enforce that, so this module does:

* the exported JSON is validated against a JSON Schema generated from the
  pydantic models, and
* the TypeScript interfaces are parsed and their field names compared with the
  pydantic models' field names, in both directions.

A field added to one side and not the other fails here rather than silently
producing a dataset the frontend misreads.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from antilethe.config import Settings
from antilethe.export import export_dataset
from antilethe.models import (
    Changepoint,
    Decomposition,
    GapSummary,
    Index,
    InstabilityCell,
    Manifest,
    ModelFingerprint,
    NoiseStats,
    PriceChange,
    ProviderEvent,
    Snapshot,
    SnapshotShard,
    Span,
    StratumStat,
    TimelinePoint,
    VersionEvent,
    WithinStat,
)

TYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "data" / "types.ts"

#: pydantic model -> the TypeScript interface that mirrors it.
PAIRS: list[tuple[type[BaseModel], str]] = [
    (Index, "Index"),
    (Span, "Span"),
    (GapSummary, "GapSummary"),
    (NoiseStats, "NoiseStats"),
    (TimelinePoint, "TimelinePoint"),
    (StratumStat, "StratumStat"),
    (Decomposition, "Decomposition"),
    (ModelFingerprint, "ModelFingerprint"),
    (InstabilityCell, "InstabilityCell"),
    (VersionEvent, "VersionEvent"),
    (ProviderEvent, "ProviderEvent"),
    (PriceChange, "PriceChange"),
    (Snapshot, "Snapshot"),
    (SnapshotShard, "SnapshotShard"),
    (Manifest, "Manifest"),
    (Changepoint, "Changepoint"),
    (WithinStat, "WithinStat"),
]


def _interfaces() -> dict[str, set[str]]:
    """Field names of every ``export interface`` in types.ts.

    Comments are stripped first so a field name mentioned in prose is not
    mistaken for a declaration.
    """
    source = TYPES_TS.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)

    out: dict[str, set[str]] = {}
    for match in re.finditer(r"export interface (\w+)\s*\{(.*?)\n\}", source, re.DOTALL):
        name = match.group(1)
        fields = set(re.findall(r"^\s*(\w+)\??\s*:", match.group(2), re.MULTILINE))
        out[name] = fields
    return out


def test_types_ts_is_readable() -> None:
    assert TYPES_TS.exists(), f"missing {TYPES_TS}"
    assert _interfaces(), "no interfaces parsed out of types.ts"


@pytest.mark.parametrize(("model", "interface"), PAIRS, ids=[p[1] for p in PAIRS])
def test_pydantic_and_typescript_agree(model: type[BaseModel], interface: str) -> None:
    """Field-for-field, in both directions."""
    interfaces = _interfaces()
    assert interface in interfaces, f"types.ts has no interface {interface}"

    python_fields = set(model.model_fields)
    ts_fields = interfaces[interface]

    missing_in_ts = python_fields - ts_fields
    missing_in_python = ts_fields - python_fields

    assert not missing_in_ts, f"{interface} is missing {sorted(missing_in_ts)}"
    assert not missing_in_python, f"{model.__name__} is missing {sorted(missing_in_python)}"


def _validator(model: type[BaseModel]) -> Draft202012Validator:
    """A JSON Schema validator generated from a pydantic model."""
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    return Draft202012Validator(schema)


def test_exported_index_validates_against_the_generated_schema(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    export_dataset(populated, out, method="cosine_bow", settings=settings)

    payload = json.loads((out / "index.json").read_text(encoding="utf-8"))
    errors = sorted(_validator(Index).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, [f"{list(e.path)}: {e.message}" for e in errors[:5]]


def test_exported_manifest_validates(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    export_dataset(populated, out, method="cosine_bow", settings=settings)

    payload = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    errors = list(_validator(Manifest).iter_errors(payload))
    assert not errors, [e.message for e in errors[:5]]


def test_exported_shards_validate(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    report = export_dataset(populated, out, method="cosine_bow", settings=settings)
    assert report.shards > 0

    validator = _validator(SnapshotShard)
    for path in (out / "snapshots").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(payload))
        assert not errors, f"{path.name}: {[e.message for e in errors[:3]]}"


def test_export_writes_the_expected_files(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    report = export_dataset(populated, out, method="cosine_bow", settings=settings)

    assert (out / "index.json").exists()
    assert (out / "manifest.json").exists()
    assert (out / "snapshots").is_dir()
    # One shard per question that has analysable transitions.
    assert report.shards == len(list((out / "snapshots").glob("*.json")))
    assert report.total_bytes > 0


def test_export_can_skip_snapshots(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    out = tmp_path / "data"
    report = export_dataset(
        populated, out, method="cosine_bow", shard_snapshots=False, settings=settings
    )
    assert report.shards == 0
    assert not (out / "snapshots").exists()


def test_exported_index_round_trips_through_the_model(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    """Validation is strict: an unexpected field would be rejected."""
    from antilethe.export.static_site import read_index

    out = tmp_path / "data"
    export_dataset(populated, out, method="cosine_bow", settings=settings)
    index = read_index(out)
    assert index.schema_version == 1
    assert index.models


def test_nulls_survive_the_round_trip(
    populated: sqlite3.Connection, tmp_path: Path, settings: Settings
) -> None:
    """A null must stay a null in the JSON, not become 0."""
    out = tmp_path / "data"
    export_dataset(populated, out, method="cosine_bow", settings=settings)
    payload = json.loads((out / "index.json").read_text(encoding="utf-8"))

    steady = next(m for m in payload["models"] if m["model_id"] == "openweight/steady-7b")
    assert steady["d_provider"] is None
    assert steady["d_version"] is None

    for point in payload["timeline"]:
        if point["n_version"] == 0:
            assert point["version"] is None

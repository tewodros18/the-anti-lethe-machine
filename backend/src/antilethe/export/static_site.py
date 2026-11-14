"""Write the JSON shards that the published site reads.

This module does no aggregation of its own. It calls the same
``analysis.pipeline`` functions the API routes call and serialises the result,
so the static dataset and a self-hosted API cannot drift apart.

Several pairwise methods can be exported at once. ``index.json`` is the first;
every one, the first included, also lands at ``methods/<name>.json`` with the
identical shape, so the site can switch the whole register between measures.
The snapshot shards are written once: which days are kept depends on the
strata, which depend on the build and host strings, not on any distance.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..analysis import pipeline
from ..config import Settings, get_settings
from ..models import Index, Manifest
from ..serialize import to_json

#: Written so GitHub Pages serves ``_``-prefixed SvelteKit assets untouched.
NOJEKYLL = ".nojekyll"


@dataclass
class ExportReport:
    """What one export wrote."""

    out_dir: Path
    index_bytes: int
    manifest_bytes: int
    shards: int
    methods: list[str] = field(default_factory=list)
    shard_bytes: dict[str, int] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        """Every byte written, for the CLI summary."""
        return self.index_bytes + self.manifest_bytes + sum(self.shard_bytes.values())


def _write(path: Path, payload: str) -> int:
    """Write UTF-8 text and return its byte length."""
    data = payload.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def export_dataset(
    conn: sqlite3.Connection,
    out_dir: Path | str,
    *,
    method: str | None = None,
    methods: Sequence[str] | None = None,
    shard_snapshots: bool = True,
    settings: Settings | None = None,
) -> ExportReport:
    """Write ``index.json``, ``manifest.json``, per-method indexes and shards.

    ``methods`` names every pairwise method to export, first one primary.
    ``method`` is the single-method form and is kept for callers that only
    ever wanted one.
    """
    config = settings or get_settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    names = list(methods) if methods else [method or config.default_method]
    primary = names[0]

    index: Index = pipeline.build_index(conn, primary, settings=config)
    index_bytes = _write(out / "index.json", to_json(index))

    shard_bytes: dict[str, int] = {}
    # Every exported method, the primary included, gets its own file so the
    # site has one place to look when switching measures.
    for name in names:
        built = index if name == primary else pipeline.build_index(conn, name, settings=config)
        shard_bytes[f"methods/{name}.json"] = _write(
            out / "methods" / f"{name}.json", to_json(built)
        )

    shard_count = 0
    snapshots_dir = out / "snapshots"
    if shard_snapshots:
        for shard in pipeline.iter_shards(conn, index, settings=config):
            written = _write(
                snapshots_dir / f"{shard.question_slug}.json",
                to_json(shard),
            )
            shard_bytes[f"snapshots/{shard.question_slug}.json"] = written
            shard_count += 1
    shard_bytes["index.json"] = index_bytes

    manifest: Manifest = pipeline.build_manifest(
        conn, shard_bytes, generated_at=index.generated_at, methods_exported=names
    )
    manifest_bytes = _write(out / "manifest.json", to_json(manifest))

    # The dataset lives inside the SvelteKit `static/` tree, which is copied
    # verbatim into the build. Keeping a .nojekyll here is harmless and makes
    # the directory safe to publish on its own.
    nojekyll = out / NOJEKYLL
    if not nojekyll.exists():
        nojekyll.write_bytes(b"")

    return ExportReport(
        out_dir=out,
        index_bytes=index_bytes,
        manifest_bytes=manifest_bytes,
        shards=shard_count,
        methods=names,
        shard_bytes=shard_bytes,
    )


def read_index(out_dir: Path | str) -> Index:
    """Read back an exported ``index.json``, validating it against the contract."""
    payload = json.loads((Path(out_dir) / "index.json").read_text(encoding="utf-8"))
    return Index.model_validate(payload)

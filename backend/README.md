# `antilethe` — backend

The pipeline behind [Anti-Lethe](../README.md). Reads the Internet Archive's
*Ask Me Twice* archive, classifies every change in an archived answer by its
cause, and writes a static JSON dataset.

```
antilethe ingest    # AMT API  -> SQLite (append-only)
antilethe analyze   # SQLite   -> distances + features
antilethe export    # tables   -> frontend/static/data/*.json
antilethe verify    # recompute every ledger root from stored rows
antilethe serve     # the same computed data over HTTP
antilethe methods   # what is installed
```

## Install

Use a virtual environment; `uv` is the quickest route.

```bash
uv venv --python 3.12              # from the repository root
uv pip install -e 'backend[dev]'   # pipeline + test tooling
uv pip install -e 'backend[all]'   # adds the embedding and nli methods
```

Then activate it: `.venv\Scripts\activate` on Windows,
`source .venv/bin/activate` elsewhere.

`uv run` works from the repository root, but **not from this directory**: this
`pyproject.toml` makes `backend/` its own uv project, so `uv run` here would
create a second virtual environment. Activate instead.

## Layout

| Path | What lives there |
|---|---|
| `config.py` | every env-driven setting; nothing reads `os.environ` directly |
| `models.py` | the data contract, mirrored by `frontend/src/lib/data/types.ts` |
| `serialize.py` | the one JSON serialiser, so export and API agree byte-for-byte |
| `ledger.py` | SHA-256 Merkle chain over fetched days |
| `ingest/amt_client.py` | async reader for the AMT API |
| `ingest/store.py` | SQLite schema and idempotent writes |
| `ingest/runner.py` | the day loop: progress, idempotency, ledger |
| `analysis/registry.py` | the method registry — the extensibility surface, including the `prepare` hook |
| `analysis/stratify.py` | stable / provider / version classification |
| `analysis/pipeline.py` | `analyze` (expensive, persists) and `build_index` (cheap) |
| `analysis/bootstrap.py` | percentile-bootstrap intervals for the headline ratios |
| `analysis/changepoints.py` | binary segmentation, L1 cost, per-model level shifts |
| `analysis/methods/` | one file per drift method; four need nothing installed |
| `export/static_site.py` | writes the JSON shards |
| `api.py` | FastAPI app over the same `build_index` |

## Why `analyze` and `build_index` are separate

`analyze` compares text, so it is the expensive half and it persists its output
into the `distances` and `features` tables, keyed by method name *and* version.
`build_index` reads those tables and assembles the dataset.

Both the static exporter and every API route call `build_index`. That is what
makes `/api/v1/summary` byte-identical to the matching slice of `index.json`
rather than two implementations that happen to agree today.

## Adding a method

See [the root README](../README.md#adding-an-analysis-method). One file in
`analysis/methods/`, one decorator, one line in `methods/__init__.py`.

## Tests

With the venv activated, from this directory:

```bash
pytest                            # ≥80% coverage enforced in pyproject.toml
mypy --strict src
ruff check . && ruff format --check .
```

`mypy` must run from `backend/` so it picks up this `pyproject.toml`, which
declares the optional extras' modules as having no type stubs. Running it from
the repository root reports the optional methods' imports as missing.

Fabricated data exists only under `tests/fixtures/` and is never importable
from application code.

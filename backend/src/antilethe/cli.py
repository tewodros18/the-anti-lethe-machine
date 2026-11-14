"""The ``antilethe`` command line.

Every command exits non-zero on failure. There is no mode in which a broken
upstream, an empty archive or a broken ledger produces a dataset anyway.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .analysis import pipeline, registry
from .config import get_settings
from .export import export_dataset
from .ingest import AMTError, store
from .ingest.runner import ingest_questions, ingest_range
from .ledger import verify_chain

app = typer.Typer(
    name="antilethe",
    help="A public drift register for AI model behaviour.",
    no_args_is_help=True,
    add_completion=False,
)


def _echo(message: str) -> None:
    """Write a progress line to stdout."""
    typer.echo(message)


def _fail(message: str) -> None:
    """Write an error to stderr and exit non-zero."""
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.callback()
def main() -> None:
    """Anti-Lethe pipeline."""


@app.command()
def version() -> None:
    """Print the installed version."""
    _echo(__version__)


@app.command()
def ingest(
    since: Annotated[str | None, typer.Option(help="First day, YYYY-MM-DD.")] = None,
    until: Annotated[str | None, typer.Option(help="Last day, YYYY-MM-DD.")] = None,
    force: Annotated[bool, typer.Option(help="Re-fetch days already marked ok.")] = False,
    concurrency: Annotated[int | None, typer.Option(help="Parallel requests.")] = None,
    questions: Annotated[
        str | None,
        typer.Option(
            help=(
                "Comma-separated question slugs. Fetches those questions' full history"
                " instead of whole days: far cheaper under upstream's bandwidth limit,"
                " but builds a deliberately partial archive."
            )
        ),
    ] = None,
    db: Annotated[Path | None, typer.Option(help="Archive path.")] = None,
) -> None:
    """Fetch archived answers into SQLite. Idempotent."""
    settings = get_settings()
    if concurrency is not None:
        settings.concurrency = concurrency
    if db is not None:
        settings.db_path = db

    try:
        start = date.fromisoformat(since) if since else None
        end = date.fromisoformat(until) if until else None
    except ValueError as exc:
        _fail(f"bad date: {exc}")
        return

    slugs = [s.strip() for s in questions.split(",") if s.strip()] if questions else None

    with store.open_store(settings.db_path) as conn:
        try:
            if slugs:
                report = asyncio.run(
                    ingest_questions(conn, slugs, force=force, settings=settings, progress=_echo)
                )
                unit = "series"
            else:
                report = asyncio.run(
                    ingest_range(
                        conn,
                        since=start,
                        until=end,
                        force=force,
                        settings=settings,
                        progress=_echo,
                    )
                )
                unit = "days"
        except AMTError as exc:
            _fail(f"ingest failed: {exc}")
            return

        _echo(
            f"\n{report.fetched} {unit} fetched, {report.skipped} skipped, "
            f"{report.failed} failed, {report.added} rows added, "
            f"{store.row_count(conn)} rows total"
        )
        if report.failed:
            _fail(f"{report.failed} {unit} could not be fetched")


@app.command()
def analyze(
    methods: Annotated[str | None, typer.Option(help="Comma-separated method names.")] = None,
    rebuild: Annotated[bool, typer.Option(help="Discard and recompute.")] = False,
    db: Annotated[Path | None, typer.Option(help="Archive path.")] = None,
) -> None:
    """Compute drift metrics over the stored archive."""
    settings = get_settings()
    if db is not None:
        settings.db_path = db
    names = [n.strip() for n in methods.split(",") if n.strip()] if methods else None

    with store.open_store(settings.db_path) as conn:
        try:
            reports = pipeline.analyze(
                conn, names, rebuild=rebuild, settings=settings, progress=_echo
            )
        except (
            pipeline.NoDataError,
            registry.MissingDependencyError,
            registry.UnknownMethodError,
        ) as exc:
            _fail(str(exc))
            return
        _echo(f"\n{len(reports)} method(s) analysed")


@app.command()
def export(
    out: Annotated[Path, typer.Option(help="Output directory for the JSON shards.")],
    methods: Annotated[
        str | None,
        typer.Option(
            help=(
                "Comma-separated pairwise methods to export. The first becomes index.json;"
                " each also lands at methods/<name>.json so the site can switch between them."
            )
        ),
    ] = None,
    shard_snapshots: Annotated[bool, typer.Option("--shard-snapshots/--no-shard-snapshots")] = True,
    db: Annotated[Path | None, typer.Option(help="Archive path.")] = None,
) -> None:
    """Write the static JSON dataset."""
    settings = get_settings()
    if db is not None:
        settings.db_path = db
    names = [n.strip() for n in methods.split(",") if n.strip()] if methods else None

    with store.open_store(settings.db_path) as conn:
        try:
            report = export_dataset(
                conn,
                out,
                methods=names,
                shard_snapshots=shard_snapshots,
                settings=settings,
            )
        except (pipeline.NoDataError, registry.UnknownMethodError) as exc:
            _fail(str(exc))
            return

    _echo(
        f"wrote {report.out_dir}\n"
        f"  index.json      {report.index_bytes:>9,} bytes  ({report.methods[0]})\n"
        f"  methods/        {len(report.methods):>9,} indexes ({', '.join(report.methods)})\n"
        f"  manifest.json   {report.manifest_bytes:>9,} bytes\n"
        f"  snapshots/      {report.shards:>9,} shards\n"
        f"  total           {report.total_bytes:>9,} bytes"
    )


@app.command()
def verify(
    day: Annotated[str | None, typer.Option(help="Check one day only.")] = None,
    db: Annotated[Path | None, typer.Option(help="Archive path.")] = None,
) -> None:
    """Recompute every ledger root from stored rows."""
    settings = get_settings()
    if db is not None:
        settings.db_path = db

    with store.open_store(settings.db_path) as conn:
        report = verify_chain(conn, day)

    if report.days_checked == 0:
        _fail("no ledger entries to verify; run `antilethe ingest` first")
        return

    if report.ok:
        head = report.head
        _echo(
            f"ledger intact: {report.days_checked} days verified"
            + (f", head {head.day} {head.merkle_root[:16]}..." if head else "")
        )
        return

    for item in report.breaks:
        typer.secho(f"{item.day}  {item.kind}: {item.detail}", fg=typer.colors.RED, err=True)
    _fail(f"ledger broken: {len(report.breaks)} problem(s) across {report.days_checked} days")


@app.command()
def methods() -> None:
    """List registered methods and whether their dependencies are installed."""
    installed = {s.name for s in registry.available()}
    for spec in registry.all_specs():
        mark = "ok     " if spec.name in installed else "missing"
        requires = ", ".join(spec.requires) or "-"
        _echo(f"{mark} {spec.name:<12} {spec.kind:<8} v{spec.version:<8} requires: {requires}")
        if spec.description:
            _echo(f"          {spec.description}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Port.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes.")] = False,
) -> None:
    """Run the FastAPI app."""
    import uvicorn

    uvicorn.run("antilethe.api:app", host=host, port=port, reload=reload)


def run() -> None:
    """Entry point wrapper that turns unexpected errors into exit code 1."""
    try:
        app()
    except AMTError as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover
    run()

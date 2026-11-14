"""SQLite schema and idempotent writes.

The archive is append-only: a day already fetched is never rewritten, only
skipped. ``INSERT OR IGNORE`` on ``responses.id`` makes re-ingesting a day a
no-op, which is what lets the scheduled workflow run without coordination.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from ..models import ModelRow, Question, RawResponse

#: A day counts as complete at or above this fraction of the fullest day's rows.
#: Upstream drops a small number of generations most days, so requiring an exact
#: match would report a well-covered archive as having no complete days at all.
COMPLETE_DAY_TOLERANCE = 0.99

SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
  id             TEXT PRIMARY KEY,
  day            TEXT NOT NULL,
  question_slug  TEXT NOT NULL,
  model_id       TEXT NOT NULL,
  canonical_slug TEXT,
  serving_host   TEXT,          -- turns[0].provider
  region         TEXT,
  answer_text    TEXT NOT NULL,
  answer_sha256  TEXT NOT NULL,
  tokens         INTEGER,
  reasoning_frac REAL,
  cost           REAL,
  duration_ms    INTEGER,
  error_type     TEXT,
  created_at     TEXT,
  fetched_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resp_day   ON responses(day);
CREATE INDEX IF NOT EXISTS ix_resp_pair  ON responses(question_slug, model_id, day);
CREATE INDEX IF NOT EXISTS ix_resp_model ON responses(model_id, day);

CREATE TABLE IF NOT EXISTS questions (
  slug TEXT PRIMARY KEY, text TEXT NOT NULL, tags TEXT, enabled INTEGER,
  first_seen TEXT, last_seen TEXT
);

CREATE TABLE IF NOT EXISTS model_catalog (
  model_id TEXT NOT NULL, day TEXT NOT NULL, canonical_slug TEXT,
  name TEXT, provider TEXT, context_length INTEGER,
  prompt_price REAL, completion_price REAL, selected INTEGER,
  PRIMARY KEY (model_id, day)
);

CREATE TABLE IF NOT EXISTS ledger (
  day TEXT PRIMARY KEY, row_count INTEGER NOT NULL,
  merkle_root TEXT NOT NULL, prev_root TEXT, fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_log (
  day TEXT PRIMARY KEY, status TEXT NOT NULL, rows INTEGER,
  started_at TEXT, finished_at TEXT, error TEXT
);

-- Computed by `antilethe analyze`. Keyed by method and version so a dataset
-- built with cosine_bow can never be silently mixed with one built with nli.
CREATE TABLE IF NOT EXISTS distances (
  method         TEXT NOT NULL,
  method_version TEXT NOT NULL,
  day            TEXT NOT NULL,
  prev_day       TEXT NOT NULL,
  question_slug  TEXT NOT NULL,
  model_id       TEXT NOT NULL,
  stratum        TEXT NOT NULL,
  from_canonical TEXT, to_canonical TEXT,
  from_host      TEXT, to_host      TEXT,
  value          REAL NOT NULL,
  PRIMARY KEY (method, method_version, question_slug, model_id, day)
);
CREATE INDEX IF NOT EXISTS ix_dist_lookup ON distances(method, stratum, day);
CREATE INDEX IF NOT EXISTS ix_dist_model  ON distances(method, model_id);

CREATE TABLE IF NOT EXISTS features (
  method         TEXT NOT NULL,
  method_version TEXT NOT NULL,
  response_id    TEXT NOT NULL,
  key            TEXT NOT NULL,
  value          REAL,
  PRIMARY KEY (method, method_version, response_id, key)
);
CREATE INDEX IF NOT EXISTS ix_feat_key ON features(method, key);

CREATE TABLE IF NOT EXISTS analysis_runs (
  method TEXT PRIMARY KEY, method_version TEXT NOT NULL, kind TEXT NOT NULL,
  finished_at TEXT NOT NULL, n_rows INTEGER NOT NULL
);

-- Cached result of amt_client.discover_range, so the exponential walk-back is
-- paid once rather than on every ingest.
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the archive, creating it and its schema if absent."""
    path = Path(db_path)
    if path.parent != Path():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@contextmanager
def open_store(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Context-managed connection."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def upsert_responses(conn: sqlite3.Connection, rows: Iterable[RawResponse]) -> int:
    """Insert answers, ignoring any ``id`` already stored.

    Returns the number of rows actually added, so a re-ingest reports zero.
    """
    fetched_at = datetime.now(UTC).isoformat()
    payload = [
        (
            r.id,
            r.day,
            r.question_slug,
            r.model_id,
            r.canonical_slug,
            r.serving_host,
            r.region,
            r.answer_text,
            r.answer_sha256,
            r.tokens,
            r.reasoning_frac,
            r.cost,
            r.duration_ms,
            r.error_type,
            r.created_at,
            fetched_at,
        )
        for r in rows
    ]
    if not payload:
        return 0
    before = _count(conn, "responses")
    conn.executemany(
        "INSERT OR IGNORE INTO responses (id, day, question_slug, model_id, canonical_slug,"
        " serving_host, region, answer_text, answer_sha256, tokens, reasoning_frac, cost,"
        " duration_ms, error_type, created_at, fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return _count(conn, "responses") - before


def upsert_questions(conn: sqlite3.Connection, questions: Iterable[Question], day: str) -> int:
    """Record the question set, widening each slug's first/last seen window."""
    rows = list(questions)
    for qrow in rows:
        conn.execute(
            "INSERT INTO questions (slug, text, tags, enabled, first_seen, last_seen)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET"
            "   text=excluded.text, tags=excluded.tags, enabled=excluded.enabled,"
            "   first_seen=MIN(questions.first_seen, excluded.first_seen),"
            "   last_seen=MAX(questions.last_seen, excluded.last_seen)",
            (qrow.slug, qrow.text, "\t".join(qrow.tags), int(qrow.enabled), day, day),
        )
    conn.commit()
    return len(rows)


def upsert_models(conn: sqlite3.Connection, models: Iterable[ModelRow]) -> int:
    """Record the model catalogue for one day."""
    payload = [
        (
            m.model_id,
            m.day,
            m.canonical_slug,
            m.name,
            m.vendor,
            m.context_length,
            m.prompt_price,
            m.completion_price,
            int(m.selected),
        )
        for m in models
    ]
    if not payload:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO model_catalog (model_id, day, canonical_slug, name, provider,"
        " context_length, prompt_price, completion_price, selected) VALUES (?,?,?,?,?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return len(payload)


def start_day(conn: sqlite3.Connection, day: date | str) -> None:
    """Mark a day in progress."""
    key = _key(day)
    conn.execute(
        "INSERT INTO ingest_log (day, status, rows, started_at, finished_at, error)"
        " VALUES (?, 'running', NULL, ?, NULL, NULL)"
        " ON CONFLICT(day) DO UPDATE SET status='running', started_at=excluded.started_at,"
        " finished_at=NULL, error=NULL",
        (key, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def finish_day(conn: sqlite3.Connection, day: date | str, rows: int) -> None:
    """Mark a day successfully ingested."""
    conn.execute(
        "UPDATE ingest_log SET status='ok', rows=?, finished_at=?, error=NULL WHERE day=?",
        (rows, datetime.now(UTC).isoformat(), _key(day)),
    )
    conn.commit()


def fail_day(conn: sqlite3.Connection, day: date | str, error: str) -> None:
    """Record a failed day so the next run retries it."""
    conn.execute(
        "UPDATE ingest_log SET status='error', finished_at=?, error=? WHERE day=?",
        (datetime.now(UTC).isoformat(), error[:2000], _key(day)),
    )
    conn.commit()


def day_is_done(conn: sqlite3.Connection, day: date | str) -> bool:
    """True when a day is already marked ``ok``; ``--force`` bypasses this."""
    row = conn.execute("SELECT status FROM ingest_log WHERE day = ?", (_key(day),)).fetchone()
    return bool(row and row[0] == "ok")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Store a small cached value."""
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES (?,?,?)",
        (key, value, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Read a cached value."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def stored_days(conn: sqlite3.Connection) -> list[str]:
    """Every day with at least one stored answer."""
    return [str(r[0]) for r in conn.execute("SELECT DISTINCT day FROM responses ORDER BY day")]


def known_days(
    conn: sqlite3.Connection, question_slugs: Iterable[str]
) -> dict[tuple[str, str], set[str]]:
    """Days already stored for every (question, model) series of the given questions."""
    slugs = list(question_slugs)
    if not slugs:
        return {}
    marks = ",".join("?" for _ in slugs)
    out: dict[tuple[str, str], set[str]] = {}
    for row in conn.execute(
        f"SELECT question_slug, model_id, day FROM responses WHERE question_slug IN ({marks})",
        tuple(slugs),
    ):
        out.setdefault((str(row[0]), str(row[1])), set()).add(str(row[2]))
    return out


def row_count(conn: sqlite3.Connection) -> int:
    """Total archived answers."""
    return _count(conn, "responses")


def last_ingest(conn: sqlite3.Connection) -> str | None:
    """Timestamp of the most recent successful ingest."""
    row = conn.execute(
        "SELECT finished_at FROM ingest_log WHERE status='ok' ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def complete_day_count(conn: sqlite3.Connection) -> int:
    """Days whose row count equals the modal row count across all days.

    A "complete" day is one whose row count is within ``COMPLETE_DAY_TOLERANCE``
    of the fullest day in the archive. The fullest day is the best available
    estimate of the full question x model grid, so a day measured against it is
    either essentially fully covered or it is not.

    Measuring against the *modal* count instead would be wrong for a partial
    archive: ingesting a few question series deeply makes the typical day hold
    only those questions, and every such day would then be reported as complete
    when in truth almost none of the grid was captured. Partial days still
    contribute transitions; they are just not counted as complete, so the span
    is never overstated.
    """
    counts = [int(r[0]) for r in conn.execute("SELECT COUNT(*) FROM responses GROUP BY day")]
    if not counts:
        return 0
    fullest = max(counts)
    threshold = fullest * COMPLETE_DAY_TOLERANCE
    return sum(1 for c in counts if c >= threshold)


def questions(conn: sqlite3.Connection) -> list[Question]:
    """Stored question set."""
    rows = conn.execute(
        "SELECT slug, text, tags, enabled, first_seen, last_seen FROM questions ORDER BY slug"
    ).fetchall()
    return [
        Question(
            slug=str(r[0]),
            text=str(r[1]),
            tags=[t for t in str(r[2] or "").split("\t") if t],
            enabled=bool(r[3]),
            first_seen=None if r[4] is None else str(r[4]),
            last_seen=None if r[5] is None else str(r[5]),
        )
        for r in rows
    ]


def _count(conn: sqlite3.Connection, table: str) -> int:
    """Row count for a known table name."""
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _key(day: date | str) -> str:
    """Normalise a day to ``YYYY-MM-DD``."""
    return day.isoformat() if isinstance(day, date) else day

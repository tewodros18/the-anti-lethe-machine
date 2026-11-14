"""A hash chain over fetched days.

This ledger proves that a record has not been altered since it was fetched. It does
not and cannot prove that a given model produced it. Provenance rests on the
Internet Archive's operation of the upstream archive, not on cryptography.

Construction: the day's ``answer_sha256`` values are sorted, then reduced
pairwise into a Merkle root. Each day stores the previous day's root, so
rewriting history requires rewriting every later day too.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal

from .models import ChainBreak, ChainReport, LedgerEntry, MerkleProof

Side = Literal["left", "right"]

#: Root of a day with no rows. Distinct from any real root.
EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


def _pair(left: str, right: str) -> str:
    """Hash two hex digests into their parent digest."""
    return hashlib.sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def _levels(leaves: list[str]) -> list[list[str]]:
    """Build every level of the tree, leaves first, root last.

    An odd node is paired with itself, the standard duplicate-last convention.
    """
    if not leaves:
        return [[EMPTY_ROOT]]
    levels = [sorted(leaves)]
    while len(levels[-1]) > 1:
        current = levels[-1]
        nxt: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            nxt.append(_pair(left, right))
        levels.append(nxt)
    return levels


def merkle_root(leaves: list[str]) -> str:
    """Merkle root over ``leaves``, which are sorted first so order cannot matter."""
    return _levels(leaves)[-1][0]


def merkle_proof(leaves: list[str], index: int) -> list[tuple[Side, str]]:
    """Inclusion proof for ``leaves[index]``, as ``(sibling_side, hash)`` pairs.

    ``index`` refers to the position in the caller's list; the proof is built
    against the sorted ordering that :func:`merkle_root` uses.
    """
    if not leaves:
        raise IndexError("no leaves to prove")
    if not 0 <= index < len(leaves):
        raise IndexError(f"index {index} out of range for {len(leaves)} leaves")
    target = leaves[index]
    levels = _levels(leaves)
    position = levels[0].index(target)
    proof: list[tuple[Side, str]] = []
    for level in levels[:-1]:
        if position % 2 == 0:
            sibling = level[position + 1] if position + 1 < len(level) else level[position]
            proof.append(("right", sibling))
        else:
            proof.append(("left", level[position - 1]))
        position //= 2
    return proof


def verify_proof(leaf: str, proof: list[tuple[Side, str]], root: str) -> bool:
    """Recompute a root from a leaf and its proof, and compare."""
    current = leaf
    for side, sibling in proof:
        current = _pair(sibling, current) if side == "left" else _pair(current, sibling)
    return current == root


def day_leaves(conn: sqlite3.Connection, day: date | str) -> list[str]:
    """Every answer hash stored for ``day``, in the tree's sorted order."""
    key = day.isoformat() if isinstance(day, date) else day
    rows = conn.execute(
        "SELECT answer_sha256 FROM responses WHERE day = ? ORDER BY answer_sha256", (key,)
    ).fetchall()
    return [str(r[0]) for r in rows]


def recomputed_day_leaves(
    conn: sqlite3.Connection, day: date | str
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Re-hash every stored answer for ``day`` from its text.

    Verification must not trust the stored ``answer_sha256``: an edit to
    ``answer_text`` that left the hash column alone would otherwise rebuild the
    same root and pass. The leaves returned here are hashed from the text as it
    is in the database right now.

    Returns the recomputed leaves plus ``(id, stored, recomputed)`` for every row
    whose stored hash no longer matches its text.
    """
    key = day.isoformat() if isinstance(day, date) else day
    rows = conn.execute(
        "SELECT id, answer_text, answer_sha256 FROM responses WHERE day = ?", (key,)
    ).fetchall()

    leaves: list[str] = []
    mismatches: list[tuple[str, str, str]] = []
    for row in rows:
        stored = str(row[2])
        actual = hashlib.sha256(str(row[1]).encode("utf-8")).hexdigest()
        leaves.append(actual)
        if actual != stored:
            mismatches.append((str(row[0]), stored, actual))
    return sorted(leaves), mismatches


def _previous_root(conn: sqlite3.Connection, day: str) -> str | None:
    """Root of the most recent ledger day strictly before ``day``."""
    row = conn.execute(
        "SELECT merkle_root FROM ledger WHERE day < ? ORDER BY day DESC LIMIT 1", (day,)
    ).fetchone()
    return str(row[0]) if row else None


def append_day(conn: sqlite3.Connection, day: date | str, leaves: list[str]) -> LedgerEntry:
    """Record one day's root, chained to the previous day.

    Idempotent: a day already present is returned unchanged rather than
    appended twice, which is what makes re-ingesting a day safe.
    """
    key = day.isoformat() if isinstance(day, date) else day
    existing = conn.execute(
        "SELECT day, row_count, merkle_root, prev_root, fetched_at FROM ledger WHERE day = ?",
        (key,),
    ).fetchone()
    if existing is not None:
        return LedgerEntry(
            day=str(existing[0]),
            row_count=int(existing[1]),
            merkle_root=str(existing[2]),
            prev_root=_opt(existing[3]),
            fetched_at=str(existing[4]),
        )

    entry = LedgerEntry(
        day=key,
        row_count=len(leaves),
        merkle_root=merkle_root(leaves),
        prev_root=_previous_root(conn, key),
        fetched_at=datetime.now(UTC).isoformat(),
    )
    conn.execute(
        "INSERT INTO ledger (day, row_count, merkle_root, prev_root, fetched_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (entry.day, entry.row_count, entry.merkle_root, entry.prev_root, entry.fetched_at),
    )
    conn.commit()
    return entry


def reroot_days(conn: sqlite3.Connection, days: Iterable[date | str]) -> int:
    """Rebuild the stored root for days whose row set has grown.

    A day's root covers the rows stored for that day. Ingesting by question
    series adds rows to days that may already have an entry, which is an
    append, not an alteration: the rows already there are untouched. The root
    has to be rebuilt to describe the new set, otherwise ``verify`` would report
    a mismatch for data that was never tampered with.

    This only ever runs during ingest, and only for days ingest just wrote to.
    ``verify`` afterwards still detects any edit to a stored answer, because it
    re-hashes every answer from its text.

    Returns the number of entries rebuilt.
    """
    changed = 0
    for day in days:
        key = day.isoformat() if isinstance(day, date) else day
        existing = conn.execute(
            "SELECT merkle_root, row_count FROM ledger WHERE day = ?", (key,)
        ).fetchone()
        leaves = day_leaves(conn, key)
        if existing is None:
            append_day(conn, key, leaves)
            changed += 1
            continue
        root = merkle_root(leaves)
        if str(existing[0]) != root or int(existing[1]) != len(leaves):
            conn.execute(
                "UPDATE ledger SET merkle_root = ?, row_count = ?, fetched_at = ? WHERE day = ?",
                (root, len(leaves), datetime.now(UTC).isoformat(), key),
            )
            changed += 1
    if changed:
        conn.commit()
    return changed


def relink(conn: sqlite3.Connection) -> int:
    """Recompute every day's ``prev_root`` in ascending day order.

    ``append_day`` links each day to whatever preceded it at insert time, which
    is correct only when days arrive in order. Ingest fetches days in parallel
    and can also backfill an earlier range later, so the chain is relinked once
    at the end of a run. Roots themselves are order-independent, so only the
    links need rewriting.

    Returns the number of links changed.
    """
    rows = conn.execute("SELECT day, merkle_root, prev_root FROM ledger ORDER BY day").fetchall()
    changed = 0
    previous: str | None = None
    for raw in rows:
        day = str(raw[0])
        root = str(raw[1])
        stored_prev = _opt(raw[2])
        if stored_prev != previous:
            conn.execute("UPDATE ledger SET prev_root = ? WHERE day = ?", (previous, day))
            changed += 1
        previous = root
    if changed:
        conn.commit()
    return changed


def unrooted_days(conn: sqlite3.Connection) -> list[str]:
    """Days holding archived rows that no ledger entry covers.

    An interrupted ingest can leave these behind. They matter because the
    ledger's claim is about every record it has fetched, and a day with no root
    is simply not covered by that claim. Reporting zero problems while such days
    exist would overstate what has been verified.
    """
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT r.day FROM responses r"
            " LEFT JOIN ledger l ON l.day = r.day"
            " WHERE l.day IS NULL ORDER BY r.day"
        )
    ]


def verify_chain(conn: sqlite3.Connection, day: date | str | None = None) -> ChainReport:
    """Recompute every stored root from the rows now in the database.

    Any edit to ``responses.answer_text`` changes its hash, which changes the
    day's root, which this reports as a ``root_mismatch``. Days with rows but no
    root at all are reported as ``unrooted_day``, so a partially ingested archive
    never passes as fully verified.
    """
    if day is not None:
        key = day.isoformat() if isinstance(day, date) else day
        rows = conn.execute(
            "SELECT day, row_count, merkle_root, prev_root, fetched_at FROM ledger"
            " WHERE day = ? ORDER BY day",
            (key,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT day, row_count, merkle_root, prev_root, fetched_at FROM ledger ORDER BY day"
        ).fetchall()

    breaks: list[ChainBreak] = []
    head: LedgerEntry | None = None
    previous_root: str | None = None

    for raw in rows:
        entry = LedgerEntry(
            day=str(raw[0]),
            row_count=int(raw[1]),
            merkle_root=str(raw[2]),
            prev_root=_opt(raw[3]),
            fetched_at=str(raw[4]),
        )
        head = entry
        # Hashes are recomputed from the answer text, so editing the text and
        # leaving the hash column untouched is still caught.
        leaves, hash_mismatches = recomputed_day_leaves(conn, entry.day)
        for row_id, stored, actual in hash_mismatches:
            breaks.append(
                ChainBreak(
                    day=entry.day,
                    kind="hash_mismatch",
                    detail=f"row {row_id}: stored hash {stored[:16]}... but text hashes to"
                    f" {actual[:16]}...",
                )
            )

        if len(leaves) != entry.row_count:
            breaks.append(
                ChainBreak(
                    day=entry.day,
                    kind="missing_rows",
                    detail=f"ledger recorded {entry.row_count} rows, found {len(leaves)}",
                )
            )
        recomputed = merkle_root(leaves)
        if recomputed != entry.merkle_root:
            breaks.append(
                ChainBreak(
                    day=entry.day,
                    kind="root_mismatch",
                    detail=f"stored {entry.merkle_root[:16]}..., recomputed {recomputed[:16]}...",
                )
            )
        # Only meaningful when walking the whole chain in order.
        if day is None and entry.prev_root != previous_root:
            breaks.append(
                ChainBreak(
                    day=entry.day,
                    kind="prev_mismatch",
                    detail=f"prev_root {entry.prev_root} does not match preceding root"
                    f" {previous_root}",
                )
            )
        previous_root = entry.merkle_root

    # Only meaningful for a whole-chain check: a single-day check is not a claim
    # about the rest of the archive.
    if day is None:
        unrooted = unrooted_days(conn)
        for missing in unrooted:
            breaks.append(
                ChainBreak(
                    day=missing,
                    kind="unrooted_day",
                    detail="day holds archived rows but no ledger entry covers them;"
                    " finish the interrupted ingest to root it",
                )
            )

    return ChainReport(days_checked=len(rows), ok=not breaks, breaks=breaks, head=head)


def proof_for_response(
    conn: sqlite3.Connection, day: date | str, answer_sha256: str
) -> MerkleProof | None:
    """Inclusion proof for one stored answer under its day's root."""
    key = day.isoformat() if isinstance(day, date) else day
    leaves = day_leaves(conn, key)
    if answer_sha256 not in leaves:
        return None
    index = leaves.index(answer_sha256)
    return MerkleProof(
        leaf=answer_sha256,
        path=merkle_proof(leaves, index),
        root=merkle_root(leaves),
        day=key,
    )


def _opt(value: object) -> str | None:
    """``None``-preserving string coercion for sqlite columns."""
    return None if value is None else str(value)

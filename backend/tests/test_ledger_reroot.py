"""Re-rooting a day whose row set grew, and the tamper guarantee that survives it.

Ingesting by question series adds rows to days that may already have a ledger
entry. That is an append, not an alteration, so the day's root is rebuilt. These
tests pin down the distinction: appending is allowed and re-rooted, editing an
existing answer is still caught.
"""

from __future__ import annotations

import sqlite3

from antilethe import ledger
from antilethe.models import sha256_hex


def _insert(conn: sqlite3.Connection, row_id: str, day: str, text: str) -> None:
    conn.execute(
        "INSERT INTO responses (id, day, question_slug, model_id, answer_text, answer_sha256,"
        " fetched_at) VALUES (?,?,?,?,?,?,'now')",
        (row_id, day, "q", "m", text, sha256_hex(text)),
    )
    conn.commit()


def test_appending_rows_then_rerooting_keeps_the_chain_valid(
    conn: sqlite3.Connection,
) -> None:
    _insert(conn, "a", "2026-03-01", "first answer")
    first = ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))
    assert ledger.verify_chain(conn).ok
    assert first.row_count == 1

    # A later question-series ingest adds another answer to the same day.
    _insert(conn, "b", "2026-03-01", "second answer")
    assert not ledger.verify_chain(conn).ok  # stale root, as expected

    changed = ledger.reroot_days(conn, ["2026-03-01"])
    assert changed == 1

    report = ledger.verify_chain(conn)
    assert report.ok, report.breaks
    row = conn.execute("SELECT row_count FROM ledger WHERE day='2026-03-01'").fetchone()
    assert int(row[0]) == 2


def test_reroot_creates_an_entry_for_a_day_that_had_none(
    conn: sqlite3.Connection,
) -> None:
    _insert(conn, "a", "2026-03-02", "only answer")
    assert ledger.reroot_days(conn, ["2026-03-02"]) == 1
    assert ledger.verify_chain(conn).days_checked == 1
    assert ledger.verify_chain(conn).ok


def test_reroot_is_a_no_op_when_nothing_changed(conn: sqlite3.Connection) -> None:
    _insert(conn, "a", "2026-03-01", "an answer")
    ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))
    assert ledger.reroot_days(conn, ["2026-03-01"]) == 0


def test_rerooting_does_not_hide_an_edit_to_an_existing_answer(
    conn: sqlite3.Connection,
) -> None:
    """The guarantee that must survive re-rooting.

    Re-rooting rebuilds the root from the text as it now stands, so it would
    happily bless an edit. What it cannot hide is that the stored per-row hash no
    longer matches its text, which is why verification re-hashes every answer.
    """
    _insert(conn, "a", "2026-03-01", "original answer")
    ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))

    conn.execute("UPDATE responses SET answer_text = 'edited answer' WHERE id = 'a'")
    conn.commit()

    ledger.reroot_days(conn, ["2026-03-01"])

    report = ledger.verify_chain(conn)
    assert not report.ok
    assert any(b.kind == "hash_mismatch" for b in report.breaks)


def test_reroot_then_relink_across_several_days(conn: sqlite3.Connection) -> None:
    for i, day in enumerate(["2026-03-01", "2026-03-02", "2026-03-03"]):
        _insert(conn, f"r{i}", day, f"answer {i}")
    assert ledger.reroot_days(conn, ["2026-03-02", "2026-03-01", "2026-03-03"]) == 3
    ledger.relink(conn)

    report = ledger.verify_chain(conn)
    assert report.ok, report.breaks
    assert report.days_checked == 3


def test_rows_with_no_ledger_entry_are_reported(conn: sqlite3.Connection) -> None:
    """An interrupted ingest must not pass as fully verified.

    The ledger's claim covers the records it rooted. A day holding rows that no
    entry covers is outside that claim, so reporting zero problems would
    overstate what was checked.
    """
    _insert(conn, "a", "2026-03-01", "rooted answer")
    ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))
    assert ledger.verify_chain(conn).ok

    # A later day's rows land but the run is interrupted before rooting them.
    _insert(conn, "b", "2026-03-02", "unrooted answer")

    assert ledger.unrooted_days(conn) == ["2026-03-02"]
    report = ledger.verify_chain(conn)
    assert not report.ok
    assert [b.kind for b in report.breaks] == ["unrooted_day"]
    assert report.breaks[0].day == "2026-03-02"

    # Rooting it resolves the finding.
    ledger.reroot_days(conn, ["2026-03-02"])
    ledger.relink(conn)
    assert ledger.verify_chain(conn).ok
    assert ledger.unrooted_days(conn) == []


def test_single_day_check_makes_no_claim_about_other_days(
    conn: sqlite3.Connection,
) -> None:
    """`verify --day` is a claim about that day only."""
    _insert(conn, "a", "2026-03-01", "rooted answer")
    ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))
    _insert(conn, "b", "2026-03-02", "unrooted answer")

    assert ledger.verify_chain(conn, "2026-03-01").ok
    assert not ledger.verify_chain(conn).ok

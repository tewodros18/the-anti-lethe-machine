"""Merkle tree, inclusion proofs, and tamper detection."""

from __future__ import annotations

import hashlib
import sqlite3
from itertools import pairwise

from antilethe import ledger
from antilethe.models import sha256_hex


def _leaf(text: str) -> str:
    return sha256_hex(text)


def test_empty_tree_has_a_distinct_root() -> None:
    assert ledger.merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_single_leaf_root_is_that_leaf() -> None:
    leaf = _leaf("one")
    assert ledger.merkle_root([leaf]) == leaf


def test_root_is_order_independent() -> None:
    """Leaves are sorted first, so fetch order cannot change a day's root."""
    leaves = [_leaf("a"), _leaf("b"), _leaf("c")]
    assert ledger.merkle_root(leaves) == ledger.merkle_root(list(reversed(leaves)))


def test_root_changes_when_a_leaf_changes() -> None:
    before = ledger.merkle_root([_leaf("a"), _leaf("b")])
    after = ledger.merkle_root([_leaf("a"), _leaf("b-edited")])
    assert before != after


def test_proof_verifies_for_every_leaf() -> None:
    for size in (1, 2, 3, 4, 5, 8, 9, 17):
        leaves = [_leaf(f"row-{i}") for i in range(size)]
        root = ledger.merkle_root(leaves)
        for index in range(size):
            proof = ledger.merkle_proof(leaves, index)
            assert ledger.verify_proof(leaves[index], proof, root), f"size={size} index={index}"


def test_proof_fails_for_a_leaf_not_in_the_tree() -> None:
    leaves = [_leaf(f"row-{i}") for i in range(5)]
    root = ledger.merkle_root(leaves)
    proof = ledger.merkle_proof(leaves, 2)
    assert not ledger.verify_proof(_leaf("not-in-tree"), proof, root)


def test_append_day_is_idempotent(conn: sqlite3.Connection) -> None:
    """Re-ingesting a day must not append a second ledger entry."""
    conn.execute(
        "INSERT INTO responses (id, day, question_slug, model_id, answer_text, answer_sha256,"
        " fetched_at) VALUES ('1','2026-03-01','q','m','text',?,'now')",
        (_leaf("text"),),
    )
    conn.commit()

    first = ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))
    second = ledger.append_day(conn, "2026-03-01", ledger.day_leaves(conn, "2026-03-01"))

    assert first.merkle_root == second.merkle_root
    assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 1


def test_chain_links_each_day_to_the_previous(populated: sqlite3.Connection) -> None:
    report = ledger.verify_chain(populated)
    assert report.ok, report.breaks
    assert report.days_checked == 4

    rows = populated.execute(
        "SELECT day, merkle_root, prev_root FROM ledger ORDER BY day"
    ).fetchall()
    assert rows[0][2] is None
    for earlier, later in pairwise(rows):
        assert later[2] == earlier[1]


def test_tampering_with_a_row_breaks_the_chain(populated: sqlite3.Connection) -> None:
    """The acceptance criterion: an edited answer must be detected."""
    assert ledger.verify_chain(populated).ok

    populated.execute(
        "UPDATE responses SET answer_text = 'quietly rewritten'"
        " WHERE id = (SELECT id FROM responses WHERE day = '2026-03-02' LIMIT 1)"
    )
    populated.commit()

    report = ledger.verify_chain(populated)
    assert not report.ok
    kinds = {b.kind for b in report.breaks}
    # Editing the text without touching the hash column must still be caught:
    # verification re-hashes the text rather than trusting the stored digest.
    assert "hash_mismatch" in kinds
    assert "root_mismatch" in kinds


def test_tampering_with_the_hash_column_is_detected(populated: sqlite3.Connection) -> None:
    """Rewriting the digest to match edited text does not help either."""
    row = populated.execute("SELECT id FROM responses WHERE day = '2026-03-02' LIMIT 1").fetchone()
    new_text = "quietly rewritten"
    populated.execute(
        "UPDATE responses SET answer_text = ?, answer_sha256 = ? WHERE id = ?",
        (new_text, sha256_hex(new_text), str(row[0])),
    )
    populated.commit()

    report = ledger.verify_chain(populated)
    assert not report.ok
    # The row is now self-consistent, but the day's root no longer matches the
    # one recorded when the day was fetched.
    assert any(b.kind == "root_mismatch" for b in report.breaks)


def test_deleting_a_row_is_detected(populated: sqlite3.Connection) -> None:
    populated.execute(
        "DELETE FROM responses WHERE id = (SELECT id FROM responses WHERE day='2026-03-03' LIMIT 1)"
    )
    populated.commit()

    report = ledger.verify_chain(populated)
    assert not report.ok
    kinds = {b.kind for b in report.breaks}
    assert "missing_rows" in kinds or "root_mismatch" in kinds


def test_relink_repairs_out_of_order_insertion(conn: sqlite3.Connection) -> None:
    """Days fetched in parallel can commit out of order; relink fixes the links."""
    for day in ("2026-03-02", "2026-03-01", "2026-03-03"):
        conn.execute(
            "INSERT INTO responses (id, day, question_slug, model_id, answer_text, answer_sha256,"
            " fetched_at) VALUES (?,?,?,?,?,?,'now')",
            (f"id-{day}", day, "q", "m", f"text-{day}", _leaf(f"text-{day}")),
        )
        conn.commit()
        ledger.append_day(conn, day, ledger.day_leaves(conn, day))

    # Inserting 2026-03-01 second left the chain inconsistent.
    before = ledger.verify_chain(conn)
    assert not before.ok

    changed = ledger.relink(conn)
    assert changed > 0
    assert ledger.verify_chain(conn).ok


def test_proof_for_response_round_trips(populated: sqlite3.Connection) -> None:
    row = populated.execute(
        "SELECT day, answer_sha256 FROM responses WHERE day='2026-03-01' LIMIT 1"
    ).fetchone()
    proof = ledger.proof_for_response(populated, str(row[0]), str(row[1]))
    assert proof is not None
    assert ledger.verify_proof(proof.leaf, proof.path, proof.root)


def test_proof_for_unknown_hash_is_none(populated: sqlite3.Connection) -> None:
    assert ledger.proof_for_response(populated, "2026-03-01", _leaf("absent")) is None


def test_verify_chain_on_empty_ledger(conn: sqlite3.Connection) -> None:
    report = ledger.verify_chain(conn)
    assert report.days_checked == 0
    assert report.ok
    assert report.head is None

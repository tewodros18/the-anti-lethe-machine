"""Word-level diff for the compare view.

Uses ``difflib.SequenceMatcher`` over whitespace-delimited tokens. Kept in its
own module because the frontend has a mirrored implementation for the static
build, and the two are checked against each other in the test suite.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from .models import DiffToken

#: The three operations a diff token can carry.
DiffOp = Literal["equal", "insert", "delete"]

#: Tokens keep their trailing whitespace so the diff can be rendered without
#: guessing where spaces belonged.
_TOKEN_RE = re.compile(r"\S+\s*")


def tokenize(text: str) -> list[str]:
    """Split text into whitespace-preserving word tokens."""
    return _TOKEN_RE.findall(text)


def word_diff(before: str, after: str) -> list[DiffToken]:
    """Diff two texts at word granularity.

    Adjacent operations of the same kind are merged, so the output is a short
    run-length list rather than one token per word.
    """
    left = tokenize(before)
    right = tokenize(after)
    matcher = SequenceMatcher(a=left, b=right, autojunk=False)

    out: list[DiffToken] = []

    def push(op: DiffOp, text: str) -> None:
        if not text:
            return
        if out and out[-1].op == op:
            out[-1] = DiffToken(op=out[-1].op, text=out[-1].text + text)
        else:
            out.append(DiffToken(op=op, text=text))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            push("equal", "".join(left[i1:i2]))
        elif tag == "delete":
            push("delete", "".join(left[i1:i2]))
        elif tag == "insert":
            push("insert", "".join(right[j1:j2]))
        else:  # replace -> a delete followed by an insert
            push("delete", "".join(left[i1:i2]))
            push("insert", "".join(right[j1:j2]))
    return out

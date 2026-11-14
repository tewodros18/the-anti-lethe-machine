"""Answer length in tokens. Optional extra: ``tiktoken``.

Word counts are a poor length measure for model output: code, URLs, tables
and non-English text all break the "a word is a run of letters" assumption,
and they are exactly the content that changes when a serving stack changes.

The tokenizer used is ``cl100k_base``, deliberately *not* each model's own.
Lengths are only comparable across 39 models if they are measured in the same
unit, and a fixed public tokenizer is that unit. The number is therefore "how
long is this answer, in a standard tokenizer", not "how many tokens did the
model bill for"; the archive's own ``tokens`` column holds the latter.

``chars_per_token`` is a cheap proxy for *what kind* of text an answer is:
prose sits near four, code and tables lower, and a sudden drop with no change
in word count is a formatting shift that word counts cannot see.

Keys: ``token_count``, ``chars_per_token``.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from ..registry import feature

#: A fixed public encoding, the same for every model, so lengths are comparable.
ENCODING = "cl100k_base"

_lock = threading.Lock()
_encoder: Any = None


def _load() -> Any:
    global _encoder
    with _lock:
        if _encoder is None:
            import tiktoken

            _encoder = tiktoken.get_encoding(ENCODING)
        return _encoder


@feature(
    "tokens",
    version="1.0.0",
    requires=("tiktoken",),
    description="Length in cl100k_base tokens and characters per token, comparable across models.",
)
def tokens(text: str, meta: Mapping[str, object]) -> dict[str, float]:
    """Token count under a fixed encoding, and characters per token."""
    del meta
    if not text:
        return {"token_count": 0.0, "chars_per_token": 0.0}
    # Special tokens in model output are text, not control codes, and must count.
    count = len(_load().encode(text, disallowed_special=()))
    return {
        "token_count": float(count),
        "chars_per_token": len(text) / count if count else 0.0,
    }

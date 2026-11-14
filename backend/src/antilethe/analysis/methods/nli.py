"""Entailment / contradiction. Optional extra: ``transformers`` + ``torch``.

This is the method that actually detects reversals. ``cosine_bow`` scores
"X is safe" against "X is not safe" as nearly identical, and an embedding
distance barely separates them either. A natural language inference model is
trained on exactly that distinction, so a repoint or a host switch that flips
an answer's position shows up here as a high contradiction probability and
nowhere else in this project.

The score is the larger of ``P(contradiction)`` in the two orderings. NLI is
directional, "yesterday's answer as premise, today's as hypothesis" is not the
same question as the reverse, and a reversal can be asymmetric: a hedged "it
depends" may not contradict a firm "yes", while the firm "yes" does contradict
the "it depends". Taking the maximum reports a reversal if either reading
finds one.

The checkpoint is set in ``config.nli_model``. The default is trained on ANLI
as well as MNLI, which is what makes it hold up on adversarially negated and
hedged rewordings, the kind drift actually produces.
"""

from __future__ import annotations

import threading
from typing import Any

from ...config import get_settings
from ..registry import pairwise

#: Hypotheses are short; this cap only matters for the premises, which are
#: answers. The real limit is ``config.nli_max_chars``; see :func:`_cap`.
MAX_CHARS = 4000


def _cap() -> int:
    """Characters of each premise the model reads, from settings."""
    return max(200, min(MAX_CHARS, get_settings().nli_max_chars))


_lock = threading.Lock()
_loaded: tuple[Any, Any, Any, dict[str, int]] | None = None


def _load() -> tuple[Any, Any, Any, dict[str, int]]:
    """The tokenizer, model, torch module, and label-name -> index map.

    Label order differs between NLI checkpoints, so it is read from the
    model's own ``id2label`` rather than assumed.
    """
    global _loaded
    with _lock:
        if _loaded is None:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            name = get_settings().nli_model
            tokenizer = AutoTokenizer.from_pretrained(name)
            model = AutoModelForSequenceClassification.from_pretrained(name)
            model.eval()
            # A GPU is used when the installed torch can see one. Inference
            # stays in float32 on either device, so a distance computed on a
            # GPU is the same number as one computed on a CPU.
            if torch.cuda.is_available():
                model.to("cuda")
            labels = {str(label).lower(): int(i) for i, label in model.config.id2label.items()}
            _loaded = (tokenizer, model, torch, labels)
        return _loaded


def _index_for(labels: dict[str, int], needle: str) -> int:
    """The index of the label containing ``needle``, e.g. ``"contradict"``."""
    for label, index in labels.items():
        if needle in label:
            return index
    raise RuntimeError(f"model has no label containing {needle!r}; found {sorted(labels)}")


def label_probs(pairs: list[tuple[str, str]], needle: str) -> list[float]:
    """``P(label)`` for each (premise, hypothesis) pair, batched.

    ``needle`` selects the label by substring (``"contradict"``, ``"entail"``),
    so the same code serves checkpoints that spell their labels differently.
    """
    if not pairs:
        return []
    tokenizer, model, torch, labels = _load()
    index = _index_for(labels, needle)
    device = next(model.parameters()).device
    batch_size = max(1, get_settings().nli_batch_size)
    out: list[float] = []
    for start in range(0, len(pairs), batch_size):
        chunk = pairs[start : start + batch_size]
        cap = _cap()
        encoded = tokenizer(
            [p[:cap] for p, _ in chunk],
            [h[:cap] for _, h in chunk],
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=512,
        )
        encoded = {key: tensor.to(device) for key, tensor in encoded.items()}
        with torch.no_grad():
            logits = model(**encoded).logits
        probabilities = torch.softmax(logits, dim=-1)[:, index]
        out.extend(float(p) for p in probabilities.cpu().tolist())
    return out


@pairwise(
    "nli",
    version="2.0.0",
    requires=("transformers", "torch"),
    description=("P(contradiction), max over both orderings. The method that detects reversals."),
)
def nli(prev_text: str, next_text: str) -> float:
    """Probability that either answer contradicts the other."""
    if not prev_text and not next_text:
        return 0.0
    if not prev_text or not next_text:
        return 1.0
    forward, backward = label_probs([(prev_text, next_text), (next_text, prev_text)], "contradict")
    return float(min(1.0, max(0.0, max(forward, backward))))

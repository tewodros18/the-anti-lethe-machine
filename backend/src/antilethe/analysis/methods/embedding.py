"""Sentence-embedding distance, and a 2-D map of each question's answer space.
Optional extra: ``sentence-transformers``.

Two methods share one encoder and one cache.

``embedding`` (pairwise)
    Cosine distance between normalised sentence embeddings. Sees paraphrase
    that word frequencies miss: "largely safe" and "generally poses little
    risk" land close together here and far apart under ``cosine_bow``. It
    still cannot reliably separate a reversal from a rewording: negation moves
    an embedding far less than it moves the meaning, which is what ``nli`` is
    for.

``embedding_map`` (feature)
    The first two principal components of every answer to one question,
    computed over that question's whole series. Each answer gets an ``(x, y)``
    and the site draws a model's answers as a path through the plane, so a
    reader can see a model wander, settle, or jump, and see whether the jump
    lines up with a host switch. The axes are a property of the question, not
    comparable across questions, and the projection keeps whatever fraction of
    the variance two components can hold, which is reported per question as
    ``map_var``.

Both use the ``prepare`` hook to encode a whole series in batched passes.
Without it the pairwise method would encode each text twice, once as the
"next" of one transition and once as the "prev" of the following, two at a
time, which is the slowest way to drive a transformer.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from ...config import get_settings
from ..registry import feature, pairwise

#: Cached vectors are dropped wholesale past this many entries. A single
#: question's series is a few thousand texts; a whole archive is hundreds of
#: thousands, and holding every vector would cost more memory than the model.
_CACHE_CAP = 20_000

#: Minimum answers a question needs before a projection means anything.
_MIN_FOR_MAP = 3

_lock = threading.Lock()
_model: Any = None
_vectors: dict[str, list[float]] = {}
_map: dict[str, tuple[float, float, float]] = {}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_model() -> Any:
    """Load and memoise the encoder."""
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(get_settings().embedding_model)
        return _model


def _remember(digest: str, vector: list[float]) -> None:
    if len(_vectors) >= _CACHE_CAP:
        _vectors.clear()
    _vectors[digest] = vector


def _encode(texts: list[str]) -> list[list[float]]:
    """Encode texts in batches, L2-normalised so a dot product is a cosine."""
    model = _load_model()
    matrix = model.encode(
        texts,
        batch_size=get_settings().embedding_batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [[float(x) for x in row] for row in matrix]


def prepare(texts: Sequence[str]) -> None:
    """Encode every text in a series that is not already cached, in batches."""
    pending: dict[str, str] = {}
    for text in texts:
        if not text:
            continue
        digest = _digest(text)
        if digest not in _vectors and digest not in pending:
            pending[digest] = text
    if not pending:
        return
    digests = list(pending)
    for digest, vector in zip(digests, _encode([pending[d] for d in digests]), strict=True):
        _remember(digest, vector)


def _vector(text: str) -> list[float]:
    """A text's vector, from the cache or, if ``prepare`` was skipped, encoded now."""
    digest = _digest(text)
    cached = _vectors.get(digest)
    if cached is None:
        cached = _encode([text])[0]
        _remember(digest, cached)
    return cached


@pairwise(
    "embedding",
    version="2.0.0",
    requires=("sentence-transformers",),
    description=(
        "Cosine distance between sentence embeddings (BGE). Sees paraphrase; weak on negation."
    ),
    prepare=prepare,
)
def embedding(prev_text: str, next_text: str) -> float:
    """Cosine distance between the two texts' normalised embeddings."""
    if not prev_text and not next_text:
        return 0.0
    if not prev_text or not next_text:
        return 1.0
    left = _vector(prev_text)
    right = _vector(next_text)
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return float(min(1.0, max(0.0, 1.0 - dot)))


def prepare_map(texts: Sequence[str]) -> None:
    """Project one series' vectors onto their first two principal components.

    Centred PCA by singular value decomposition. The sign of each component is
    fixed so that its largest-magnitude loading is positive, which makes the
    projection deterministic across runs: SVD alone is free to flip a
    component, and a map that mirrors itself between builds would be read as
    the models having moved.
    """
    import numpy as np

    prepare(texts)
    digests: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        digest = _digest(text)
        if digest in seen or digest not in _vectors:
            continue
        seen.add(digest)
        digests.append(digest)
    if len(digests) < _MIN_FOR_MAP:
        return

    matrix = np.asarray([_vectors[d] for d in digests], dtype=np.float64)
    centred = matrix - matrix.mean(axis=0, keepdims=True)
    _, singular, components = np.linalg.svd(centred, full_matrices=False)
    axes = components[:2]
    for i in range(axes.shape[0]):
        peak = int(np.argmax(np.abs(axes[i])))
        if axes[i, peak] < 0:
            axes[i] = -axes[i]
    scores = centred @ axes.T
    total = float((singular**2).sum())
    explained = float((singular[:2] ** 2).sum() / total) if total > 0 else 0.0

    if len(_map) >= _CACHE_CAP:
        _map.clear()
    for digest, (x, y) in zip(digests, scores.tolist(), strict=True):
        _map[digest] = (float(x), float(y), explained)


@feature(
    "embedding_map",
    version="1.0.0",
    requires=("sentence-transformers",),
    description=(
        "First two principal components of a question's answer embeddings:"
        " a map of where each answer sits, per question."
    ),
    prepare=prepare_map,
)
def embedding_map(text: str, meta: Mapping[str, object]) -> dict[str, float]:
    """``map_x``, ``map_y`` and the variance the plane keeps, or nothing.

    Empty when the series was too small to project or ``prepare_map`` did not
    run: there is no honest single-point projection to fall back to.
    """
    del meta
    if not text:
        return {}
    found = _map.get(_digest(text))
    if found is None:
        return {}
    x, y, explained = found
    return {"map_x": x, "map_y": y, "map_var": explained}

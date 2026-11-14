"""One JSON serialisation, used by both the exporter and the API.

Acceptance criterion: ``/api/v1/summary`` must be byte-identical to the
corresponding slice of ``index.json``. That holds only if a single function
decides key order, separators and float formatting, so this is it.

``model_dump_json`` is used rather than ``json.dumps`` because it preserves
field declaration order and renders floats identically across platforms.
Rounding already happened in ``models.q`` at construction time.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def to_jsonable(model: BaseModel) -> Any:
    """Convert a contract model to plain Python types."""
    return model.model_dump(mode="json")


def to_json(model: BaseModel) -> str:
    """Serialise a contract model deterministically."""
    return model.model_dump_json()


def to_bytes(model: BaseModel) -> bytes:
    """UTF-8 bytes of :func:`to_json`."""
    return to_json(model).encode("utf-8")


__all__ = ["to_bytes", "to_json", "to_jsonable"]

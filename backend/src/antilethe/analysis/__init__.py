"""Analysis: stratification, the method registry, and the aggregation pipeline.

Importing this package imports every method module, so the registry is fully
populated by the time anything asks it what is available.
"""

from __future__ import annotations

from . import methods as methods
from .registry import MethodSpec, available, get, spec

__all__ = ["MethodSpec", "available", "get", "spec"]

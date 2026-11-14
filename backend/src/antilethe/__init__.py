"""Anti-Lethe: a public drift register for AI model behaviour.

Reads the Internet Archive's Ask Me Twice archive and reports how archived
answers changed, stratified by *why* they changed: sampling noise, a change of
inference host, or an actual rebuild of the model.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"

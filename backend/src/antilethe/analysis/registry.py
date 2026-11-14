"""The extensibility surface.

Adding a drift method is one new file in ``methods/`` carrying one decorator.
Nothing else in the codebase changes: the pipeline, the exporter, the API and
the method page all read this registry.

Two kinds exist.

``pairwise``
    ``f(prev_text, next_text) -> float`` in ``[0, 1]``, where 0 means identical.
    Run over every consecutive-day transition in a (question, model) series.

``feature``
    ``f(text, meta) -> dict[str, float]`` of per-response measurements. Run over
    every stored answer; aggregated into the model fingerprints.

A method whose optional dependency is absent is excluded from
:func:`available` and never breaks a run. Asking for it explicitly is a hard
error that names the extra to install.

Either kind may also register a ``prepare`` hook: ``prepare(texts)`` is called
once per question with every answer text in that series before the method is
applied to any of them. A method backed by a neural model uses it to encode the
whole series in one batched pass instead of two texts at a time, and a method
that needs the whole series at once (a projection of the answer space) can only
exist because of it. Methods without one are unaffected.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeVar

MethodKind = Literal["pairwise", "feature"]

PairwiseFn = Callable[[str, str], float]
FeatureFn = Callable[[str, Mapping[str, object]], dict[str, float]]
PrepareFn = Callable[[Sequence[str]], None]
AnyFn = PairwiseFn | FeatureFn
F = TypeVar("F", bound=AnyFn)


@dataclass(frozen=True)
class MethodSpec:
    """Identity of one registered method.

    ``version`` is stamped onto every aggregate the method produces, so a
    dataset built with one method can never be silently compared with another.
    """

    name: str
    kind: MethodKind
    version: str
    requires: tuple[str, ...] = ()
    description: str = ""


@dataclass
class _Entry:
    """A spec, its implementation, and its optional per-series preparation."""

    spec: MethodSpec
    fn: AnyFn
    prepare: PrepareFn | None = None


_REGISTRY: dict[str, _Entry] = {}


class MissingDependencyError(RuntimeError):
    """A method was requested whose optional dependency is not installed."""


class UnknownMethodError(KeyError):
    """A method name that was never registered."""


def _module_name(requirement: str) -> str:
    """Import name for a pip requirement (``sentence-transformers`` -> ``sentence_transformers``).

    Only the distribution name is considered; version specifiers are stripped.
    """
    base = requirement.split("[")[0]
    for separator in (">=", "<=", "==", "~=", ">", "<", "!="):
        base = base.split(separator)[0]
    return base.strip().replace("-", "_")


def _importable(requirement: str) -> bool:
    """True when a requirement's top-level module can be located."""
    try:
        return importlib.util.find_spec(_module_name(requirement)) is not None
    except (ImportError, ValueError):
        return False


def missing_requirements(spec: MethodSpec) -> list[str]:
    """Which of a method's requirements are absent."""
    return [r for r in spec.requires if not _importable(r)]


def _register(spec: MethodSpec, fn: AnyFn, prepare: PrepareFn | None) -> None:
    """Add a method, rejecting duplicate names."""
    if spec.name in _REGISTRY:
        raise ValueError(f"method {spec.name!r} is already registered")
    _REGISTRY[spec.name] = _Entry(spec=spec, fn=fn, prepare=prepare)


def pairwise(
    name: str,
    *,
    version: str,
    requires: tuple[str, ...] = (),
    description: str = "",
    prepare: PrepareFn | None = None,
) -> Callable[[F], F]:
    """Register ``f(prev_text, next_text) -> float`` in [0,1], 0 = identical."""

    def decorate(fn: F) -> F:
        _register(
            MethodSpec(
                name=name,
                kind="pairwise",
                version=version,
                requires=tuple(requires),
                description=description,
            ),
            fn,
            prepare,
        )
        return fn

    return decorate


def feature(
    name: str,
    *,
    version: str,
    requires: tuple[str, ...] = (),
    description: str = "",
    prepare: PrepareFn | None = None,
) -> Callable[[F], F]:
    """Register ``f(text, meta) -> dict[str, float]`` of per-response features."""

    def decorate(fn: F) -> F:
        _register(
            MethodSpec(
                name=name,
                kind="feature",
                version=version,
                requires=tuple(requires),
                description=description,
            ),
            fn,
            prepare,
        )
        return fn

    return decorate


def get_prepare(name: str) -> PrepareFn | None:
    """A method's per-series preparation hook, if it registered one."""
    spec(name)
    return _REGISTRY[name].prepare


def all_specs() -> list[MethodSpec]:
    """Every registered method, installable or not."""
    return [entry.spec for entry in sorted(_REGISTRY.values(), key=lambda e: e.spec.name)]


def available() -> list[MethodSpec]:
    """Only methods whose requirements import cleanly."""
    return [spec for spec in all_specs() if not missing_requirements(spec)]


def spec(name: str) -> MethodSpec:
    """One method's spec."""
    entry = _REGISTRY.get(name)
    if entry is None:
        raise UnknownMethodError(
            f"unknown method {name!r}; registered: {', '.join(s.name for s in all_specs())}"
        )
    return entry.spec


def get(name: str) -> AnyFn:
    """One method's callable.

    Raises :class:`MissingDependencyError` naming the extra when an optional
    dependency is absent, rather than failing later inside the method.
    """
    found = spec(name)
    missing = missing_requirements(found)
    if missing:
        extra = _extra_for(name)
        raise MissingDependencyError(
            f"method {name!r} needs {', '.join(missing)}, which is not installed. "
            f"Install it with: pip install -e 'backend[{extra}]'"
        )
    return _REGISTRY[name].fn


def get_pairwise(name: str) -> PairwiseFn:
    """A pairwise method, type-checked."""
    found = spec(name)
    if found.kind != "pairwise":
        raise UnknownMethodError(f"method {name!r} is a {found.kind} method, not pairwise")
    fn = get(name)
    return fn  # type: ignore[return-value]


def get_feature(name: str) -> FeatureFn:
    """A feature method, type-checked."""
    found = spec(name)
    if found.kind != "feature":
        raise UnknownMethodError(f"method {name!r} is a {found.kind} method, not a feature method")
    fn = get(name)
    return fn  # type: ignore[return-value]


#: Which pip extra provides each optional method.
_EXTRAS: dict[str, str] = {
    "embedding": "embedding",
    "embedding_map": "embedding",
    "nli": "nli",
    "stance_nli": "nli",
    "tokens": "tokens",
}


def _extra_for(name: str) -> str:
    """The pip extra that installs a method's dependencies."""
    return _EXTRAS.get(name, "all")


@dataclass
class _ResetToken:
    """Saved registry contents, for tests that register throwaway methods."""

    saved: dict[str, _Entry] = field(default_factory=dict)


def _snapshot() -> _ResetToken:
    """Copy the registry (used by the test suite)."""
    return _ResetToken(saved=dict(_REGISTRY))


def _restore(token: _ResetToken) -> None:
    """Restore a copied registry (used by the test suite)."""
    _REGISTRY.clear()
    _REGISTRY.update(token.saved)

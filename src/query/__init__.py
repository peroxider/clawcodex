"""Query package — lazy proxy to avoid init cycles across the
src/ ↔ clawcodex_ext/ facade split.

The package re-exports symbols from sibling submodules. When those
siblings themselves transitively import from this package (which
they do, e.g. ``from src.query.query import ...`` inside
``clawcodex_ext.query.engine``), an eager ``from .X import Y`` here
triggers a circular import during module load. The lazy proxy
defers the real submodule imports until the first attribute access,
which is after the importing module has finished its top-level
definitions.
"""
from __future__ import annotations

__all__ = [
    "QueryConfig",
    "QueryEngine",
    "QueryEngineConfig",
    "QueryParams",
    "QueryState",
    "StreamEvent",
    "Terminal",
    "Transition",
    "build_query_config",
    "query",
]


def __getattr__(name: str):
    if name in {"QueryConfig", "build_query_config"}:
        from . import config as _mod
        return getattr(_mod, name)
    if name in {"QueryEngine", "QueryEngineConfig"}:
        from . import engine as _mod
        return getattr(_mod, name)
    if name in {"QueryParams", "StreamEvent", "query"}:
        from . import query as _mod
        return getattr(_mod, name)
    if name in {"QueryState", "Terminal", "Transition"}:
        from . import transitions as _mod
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

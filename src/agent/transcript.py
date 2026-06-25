"""Facade — agent/transcript.py has been moved to clawcodex_ext (lazy proxy).

The full transcript implementation (including the absorbed
``nested_session_path_resolver`` / ``init`` previously split out as
``clawcodex_ext.transcript.nested_path``) now lives in
:mod:`clawcodex_ext.agent.transcript`. This module re-exports it
verbatim via module-level ``__getattr__`` so existing
``from src.agent.transcript import ...`` callers keep working.

Uses lazy proxy to defer the ext import until the symbol is actually
accessed, avoiding circular import chains when parent ``__init__.py``
files eagerly import submodules during package initialization.
"""

from __future__ import annotations

__all__ = [
    'TranscriptWriter',
    'TranscriptReader',
    'get_agent_transcript_path',
    'get_main_transcript_path',
    'ensure_transcript_dir',
    'register_transcript_path_resolver',
    'nested_session_path_resolver',
    'init',
]


def __getattr__(name: str):
    """Lazy proxy — import from clawcodex_ext.agent.transcript on first access."""
    import clawcodex_ext.agent.transcript as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val  # cache for subsequent access
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

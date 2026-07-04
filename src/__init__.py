"""Claw Codex - Claude Code Python Implementation.

Module-level names ``__version__`` and ``BaseProvider`` are resolved lazily
via :func:`__getattr__` to defer the import of ``clawcodex_ext`` (which
pulls in ~100 submodules and adds ~3.5 s to cold-start).  Accessing
``from src import __version__`` or ``BaseProvider`` triggers the underlying
import on first use — callers that never touch these symbols (e.g. CLI
``--help``) pay zero overhead.
"""

from __future__ import annotations

import sys as _sys

__author__ = 'Claw Codex Team'

from .config import load_config, get_provider_config


def __getattr__(name: str):
    """Lazy-resolve ``__version__`` and ``BaseProvider``."""
    if name == '__version__':
        try:
            from clawcodex_ext._version import __version__ as _ver
            return _ver
        except ImportError:
            try:
                from importlib.metadata import version as _pkg_ver
                return _pkg_ver("clawcodex-dev-mind")
            except Exception:
                return '0.0.0-dev'
    if name == 'BaseProvider':
        try:  # pragma: no cover
            from .providers.base import BaseProvider as _bp
            return _bp
        except Exception:  # pragma: no cover
            return None
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return list(__all__)


__all__ = [
    '__version__',
    '__author__',
    'load_config',
    'get_provider_config',
    'BaseProvider',
]

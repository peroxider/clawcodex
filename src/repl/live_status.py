"""Facade — repl/live_status.py has been moved to clawcodex_ext (lazy proxy).

Mirrors the ``src/services/session_storage.py`` facade pattern. Public
importers continue to write ``from src.repl.live_status import
LiveStatus``; the proxy resolves the symbol from
``clawcodex_ext.repl.live_status`` on first access and caches it into
this module's globals.

Test mocks that previously targeted ``src.repl.live_status.<X>`` need
to be retargeted to ``clawcodex_ext.repl.live_status.<X>`` where the
implementation actually lives — ``mock.patch`` reads ``__dict__``
directly and would otherwise miss proxy-cached symbols that haven't
been imported yet.
"""

from __future__ import annotations

__all__ = ["LiveStatus"]


def __getattr__(name: str):
    import clawcodex_ext.repl.live_status as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

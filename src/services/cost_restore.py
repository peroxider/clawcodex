"""Facade — services/cost_restore.py has been moved to clawcodex_ext (lazy proxy).

Mirrors the ``src/services/session_storage.py`` facade pattern. Public
importers continue to write ``from src.services.cost_restore import
restore_cost_state_for_session``; the proxy resolves the symbol from
``clawcodex_ext.services.cost_restore`` on first access and caches it
into this module's globals.

Test mocks that previously targeted ``src.services.cost_restore.<X>``
need to be retargeted to ``clawcodex_ext.services.cost_restore.<X>``
where the implementation actually lives — ``mock.patch`` reads
``__dict__`` directly and would otherwise miss proxy-cached symbols
that haven't been imported yet.
"""

from __future__ import annotations

__all__ = ['restore_cost_state_for_session']


def __getattr__(name: str):
    import clawcodex_ext.services.cost_restore as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

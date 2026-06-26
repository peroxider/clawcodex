"""Facade — services/session_storage.py has been moved to clawcodex_ext (lazy proxy).

Mirrors the ``src/command_system/input_processing.py`` pattern. Public
importers continue to write ``from src.services.session_storage import
SessionStorage`` and friends; the proxy resolves the symbol from
``clawcodex_ext.services.session_storage`` on first access and caches it
into this module's globals.

Test mocks that previously targeted ``src.services.session_storage.<X>``
need to be retargeted to ``clawcodex_ext.services.session_storage.<X>``
where the implementation actually lives — ``mock.patch`` reads
``__dict__`` directly and would otherwise miss proxy-cached symbols
that haven't been imported yet.
"""

from __future__ import annotations

__all__ = [
    'SessionStorage',
    'SessionMetadata',
    'register_session_file',
    'get_cached_session_dirs',
    'clear_session_cache',
    'SESSIONS_DIR',
    'CONTENT_DIR_NAME',
    'LARGE_CONTENT_THRESHOLD',
    'DEFAULT_RETENTION_DAYS',
    'MAX_FLUSH_BATCH',
    'MAX_CACHED_SESSION_FILES',
]


def __getattr__(name: str):
    import clawcodex_ext.services.session_storage as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

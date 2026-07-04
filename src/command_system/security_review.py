"""Facade — command_system/security_review.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    'SECURITY_REVIEW_COMMAND',
]


def __getattr__(name: str):
    import clawcodex_ext.command_system.security_review as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

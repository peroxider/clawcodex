"""Facade — services/session_migrate.py has been moved to clawcodex_ext.

The full F-49 P5-H session format migration tool now lives in
:mod:`clawcodex_ext.services.session_migrate`. This module re-exports
the public surface (``migrate_session``, ``migrate_all``,
``handle_session_migrate_cli``, ``MigrationResult``, ``MigrationSummary``)
so existing ``from src.services.session_migrate import ...`` callers keep
working without modification.
"""

from clawcodex_ext.services.session_migrate import (  # noqa: F401
    MigrationResult,
    MigrationSummary,
    migrate_session,
    migrate_all,
    handle_session_migrate_cli,
)

__all__ = [
    'MigrationResult',
    'MigrationSummary',
    'migrate_session',
    'migrate_all',
    'handle_session_migrate_cli',
]

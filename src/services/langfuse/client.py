"""Facade — src/services/langfuse/client.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.langfuse.client`. This module re-exports the public surface so
existing ``from src.services.langfuse.client import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.langfuse.client import (  # noqa: F401
    LangfuseConfig,
    init_langfuse,
    get_langfuse_client,
    is_langfuse_available,
    reset_langfuse_client,
)

__all__ = [
    'LangfuseConfig',
    'init_langfuse',
    'get_langfuse_client',
    'is_langfuse_available',
    'reset_langfuse_client',
]

"""Facade — src/services/langfuse/sink.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.langfuse.sink`. This module re-exports the public surface so
existing ``from src.services.langfuse.sink import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.langfuse.sink import (  # noqa: F401
    LangfuseSink,
)

__all__ = ['LangfuseSink']

"""Facade — repl/agent_mention_completer.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.utils.agent_mention_completer`. This module re-exports
the public surface so legacy callers using
``from src.repl.agent_mention_completer import AgentMentionCompleter``
keep working without modification.
"""

from clawcodex_ext.utils.agent_mention_completer import (  # noqa: F401
    AgentMentionCompleter,
)

__all__ = ["AgentMentionCompleter"]
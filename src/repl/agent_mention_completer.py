"""Back-compat re-export shim.

The implementation has moved to :mod:`src.utils.agent_mention_completer`.
This shim preserves the legacy import path for the duration of one release
cycle.
"""

from __future__ import annotations

from src.utils.agent_mention_completer import (
    AgentMentionCompleter,
)

__all__ = [
    "AgentMentionCompleter",
]

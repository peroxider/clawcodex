"""SDK context registry stub — provides per-(session, agent) execution contexts.

This module is a downstream extension point.  The minimal implementation here
satisfies the import surface used by ``clawcodex_ext.agent.tool_authoring``
without introducing a full context isolation layer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ContextKey:
    session_id: str
    agent_id: str


class _DummyContext:
    """No-op context that simply runs the callable."""

    def run(self, fn: Callable[[], Any]) -> Any:
        return fn()


class _ContextRegistry:
    _dummy = _DummyContext()
    _locks: dict[ContextKey, threading.RLock] = {}
    _lock = threading.Lock()

    def context_key(self, *, session_id: str, agent_id: str) -> ContextKey:
        return ContextKey(session_id=session_id, agent_id=agent_id)

    def get_context(self, key: ContextKey) -> _DummyContext:
        return self._dummy

    def lock_for(self, key: ContextKey) -> threading.RLock:
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]


_CONTEXT_REGISTRY = _ContextRegistry()


def get_sdk_context_registry() -> _ContextRegistry:
    return _CONTEXT_REGISTRY


__all__ = ["ContextKey", "get_sdk_context_registry"]

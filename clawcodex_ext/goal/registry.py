"""Process-wide registry of :class:`GoalState` keyed by ``session_id``.

The registry holds the in-memory cache that drives auto-continuation
and the UI pill. Persistence is handled by
:mod:`clawcodex_ext.goal.storage`; this module only manages the
mapping and the lock that keeps it consistent under concurrent
reads/writes from the REPL turn loop, the controller hook, and the
model-side tool.

Lock discipline
---------------

* The instance carries a single ``RLock`` (``_lock``) so a method
  that calls another method (e.g. :meth:`update`) does not deadlock
  itself.
* Mutations acquire the lock for write. The public
  :meth:`get` / :meth:`snapshot` use ``RLock`` so multiple readers
  can run concurrently.
* The :meth:`update` helper accepts a *pure* mutator function
  ``(state) -> GoalState`` and runs it inside the lock — this is
  the intended primitive for read-modify-write flows like
  ``update_tokens`` and ``record_blocker``.
"""

from __future__ import annotations

import threading
from typing import Callable, Iterable, Optional

from .types import GoalState


class GoalStateRegistry:
    """In-memory ``session_id -> GoalState`` map."""

    def __init__(self) -> None:
        self._states: dict[str, GoalState] = {}
        self._lock = threading.RLock()

    # ---- read ----

    def get(self, session_id: Optional[str]) -> Optional[GoalState]:
        """Return the live :class:`GoalState` for ``session_id``, or
        ``None`` when no goal is set.

        The returned reference is to the *stored* object — callers
        must treat it as read-only. Use :meth:`update` for any
        mutation.
        """
        if not session_id:
            return None
        with self._lock:
            return self._states.get(session_id)

    def has(self, session_id: Optional[str]) -> bool:
        """``True`` when ``session_id`` has a registered goal."""
        if not session_id:
            return False
        with self._lock:
            return session_id in self._states

    def snapshot(self) -> dict[str, GoalState]:
        """Return a shallow copy of all stored states.

        The values are still references to the live objects; use
        :meth:`GoalState.to_dict` to serialise if a value escape is
        intended.
        """
        with self._lock:
            return dict(self._states)

    def iter_states(self) -> Iterable[tuple[str, GoalState]]:
        """Yield ``(session_id, state)`` pairs under the lock."""
        with self._lock:
            yield from list(self._states.items())

    # ---- write ----

    def set(self, session_id: str, state: Optional[GoalState]) -> None:
        """Insert or replace the goal for ``session_id``.

        Passing ``None`` is equivalent to :meth:`clear`.
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            if state is None:
                self._states.pop(session_id, None)
            else:
                self._states[session_id] = state

    def clear(self, session_id: str) -> None:
        """Drop any goal for ``session_id``. No-op if absent."""
        if not session_id:
            return
        with self._lock:
            self._states.pop(session_id, None)

    def update(
        self,
        session_id: str,
        fn: Callable[[Optional[GoalState]], Optional[GoalState]],
    ) -> Optional[GoalState]:
        """Apply ``fn`` to the current state and store the result.

        ``fn`` receives ``None`` when no goal exists yet and may
        return ``None`` to remove the goal. The function is invoked
        inside the registry lock so concurrent updates serialise;
        keep ``fn`` short and pure (no I/O).
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        with self._lock:
            current = self._states.get(session_id)
            new_state = fn(current)
            if new_state is None:
                self._states.pop(session_id, None)
            else:
                self._states[session_id] = new_state
            return new_state

    # ---- diagnostics ----

    def __len__(self) -> int:
        with self._lock:
            return len(self._states)


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------


_REGISTRY: Optional[GoalStateRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_goal_registry() -> GoalStateRegistry:
    """Return the process-wide :class:`GoalStateRegistry`.

    Lazily constructed on first access. The same instance is shared
    by :mod:`clawcodex_ext.goal.controller`,
    :mod:`clawcodex_ext.goal.command`, and
    :mod:`clawcodex_ext.goal.tool`, so the in-memory cache stays
    consistent across surfaces.

    Tools that need access through ``ToolContext`` get the same
    instance via the ``goal_state_registry`` field added in
    :mod:`src.tool_system.context`.
    """
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = GoalStateRegistry()
    return _REGISTRY


def reset_goal_registry_for_tests() -> None:
    """Drop the singleton so a fresh registry is built on next access.

    Test-only helper — production code should never need this.
    """
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


__all__ = [
    "GoalStateRegistry",
    "get_goal_registry",
    "reset_goal_registry_for_tests",
]

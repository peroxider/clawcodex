"""Transcript persistence for :class:`GoalState`.

Goal state lives in two places:

* in-memory — :class:`clawcodex_ext.goal.registry.GoalStateRegistry`
  for the running process.
* on-disk — JSONL entries appended to the session's
  ``transcript.jsonl`` (path:
  ``~/.clawcodex/sessions/<session_id>/transcript.jsonl``) so a
  ``--resume`` can rehydrate after a restart.

Two entry shapes are written:

.. code-block:: json

    {"type": "goal", "sessionId": "<sid>", "state": {...}, "timestamp": "..."}
    {"type": "goal-cleared", "sessionId": "<sid>", "timestamp": "..."}

``goal-cleared`` is a tombstone: it wipes any prior ``goal`` entries
for the same session so a resumed process does not resurrect a goal
the user explicitly cleared before exiting.

The writer reuses :class:`src.services.session_storage.SessionStorage`
which already handles buffered appends, dedup-by-uuid, and atomic
flushing. We do not bypass it — that would risk two writers racing
on the same file.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

from .types import GoalState

logger = logging.getLogger(__name__)


# Entry types written to the transcript. Keep these string literals
# stable — they are part of the on-disk schema and read by older
# clawcodex versions.
GOAL_ENTRY_TYPE: str = "goal"
GOAL_CLEARED_ENTRY_TYPE: str = "goal-cleared"


def _now_iso() -> str:
    """Return a millisecond-resolution ISO-8601 timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + (
        f".{int((time.time() % 1) * 1000):03d}Z"
    )


def _open_storage(session_id: str):
    """Best-effort resolution of :class:`SessionStorage`.

    Returns ``None`` on import failure so callers can degrade
    gracefully — persistence is best-effort and must never crash a
    state-machine transition. The same instance is returned for
    repeated calls with the same ``session_id`` so that appends land
    in the same on-disk transcript and reads observe every prior
    write — mirrors the lifetime model of the production
    :class:`SessionStorage`.

    The class is looked up *through the module attribute* rather than
    bound at import time, so a test fixture that monkey-patches
    ``src.services.session_storage.SessionStorage`` (typical in
    unit tests for the goal subsystem) is honoured on the very next
    call. ``from src.services.session_storage import SessionStorage``
    would bind the name into this module's namespace once and
    silently keep using the original class forever.

    Resolution order:

    1. Cached instance for ``session_id`` — preferred when still
       current (matches the production lifetime).
    2. ``SessionStorage.instances[session_id]`` (test-only seam) —
       so a freshly-seeded fake in a unit test is picked up without
       our cache clobbering its state with an empty new instance.
    3. Construct a new :class:`SessionStorage` and cache it.
    """
    try:
        import src.services.session_storage as ss_mod
    except Exception:  # pragma: no cover — defensive
        logger.exception("SessionStorage import failed; goal persistence disabled")
        return None

    SessionStorage = getattr(ss_mod, "SessionStorage", None)
    if SessionStorage is None:
        logger.exception("SessionStorage missing on ss_mod; goal persistence disabled")
        return None

    instances = getattr(SessionStorage, "instances", None)
    has_registry = isinstance(instances, dict)

    cache = _storage_cache.setdefault(session_id, {})
    cached = cache.get("instance")

    # 1. Production path (no test-only ``instances`` registry):
    #    the cache is the only lifetime signal we have — trust it
    #    unconditionally so repeated calls return the same backing
    #    on-disk transcript.
    if cached is not None and not has_registry:
        return cached

    # 2. Test path (FakeStorage exposes ``instances``): reuse the
    #    registry entry verbatim when present so a freshly-seeded
    #    fake (or a fixture-rebuilt one) is observed without our
    #    cache clobbering its ``written`` list. If the registry is
    #    empty for this session but the cache still points at an
    #    instance the fixture discarded, drop the cache entry and
    #    fall through to construct a new one.
    #
    #    NB: a *first-time* call where the registry is also empty
    #    must NOT short-circuit on ``cached is None and
    #    instances.get(sid) is None`` — that is exactly the moment
    #    we should construct a new instance. The earlier version of
    #    this guard returned ``None`` in that case (matching the
    #    cache key but for the wrong reason), which silently broke
    #    the test fakes that rely on construction side-effects.
    if has_registry:
        registry_instance = instances.get(session_id)
        if registry_instance is not None:
            # Trust the registry over our cache so a fixture-rebuilt
            # fake (the autouse fixture creates a *new* class with a
            # fresh ``instances`` dict every run) takes effect
            # immediately even when our cache still points at an
            # older instance from a previous test.
            if registry_instance is not cached:
                cache["instance"] = registry_instance
            return registry_instance
        # Registry has no instance yet — drop any stale cache entry
        # and fall through to construct a fresh one.
        cache.pop("instance", None)
        cached = None

    try:
        instance = SessionStorage(session_id=session_id)
    except Exception:
        logger.exception(
            "SessionStorage(%s) construction failed; goal persistence disabled",
            session_id,
        )
        return None
    cache["instance"] = instance
    return instance


_storage_cache: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def persist_goal(session_id: str, state: GoalState) -> bool:
    """Append a ``{"type": "goal", ...}`` entry for ``state``.

    Returns ``True`` on a successful write, ``False`` on any error
    (logged but never raised — persistence is best-effort and a
    transient disk failure must not break auto-continuation).
    """
    if not session_id:
        return False
    storage = _open_storage(session_id)
    if storage is None:
        return False
    entry: dict[str, Any] = {
        "type": GOAL_ENTRY_TYPE,
        "sessionId": session_id,
        "state": state.to_dict(),
        "timestamp": _now_iso(),
    }
    try:
        storage.write_raw(entry)
        storage.flush()
        return True
    except Exception:
        logger.exception("persist_goal failed for session=%s", session_id)
        return False


def persist_goal_cleared(session_id: str) -> bool:
    """Append a tombstone so a resumed session does not resurrect a goal."""
    if not session_id:
        return False
    storage = _open_storage(session_id)
    if storage is None:
        return False
    entry: dict[str, Any] = {
        "type": GOAL_CLEARED_ENTRY_TYPE,
        "sessionId": session_id,
        "timestamp": _now_iso(),
    }
    try:
        storage.write_raw(entry)
        storage.flush()
        return True
    except Exception:
        logger.exception("persist_goal_cleared failed for session=%s", session_id)
        return False


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _iter_transcript_entries(session_id: str) -> Iterable[dict[str, Any]]:
    """Yield entries from the session's JSONL transcript.

    Errors reading the file are swallowed (logged) so a corrupt
    transcript does not block resume.
    """
    storage = _open_storage(session_id)
    if storage is None:
        return
    try:
        entries = storage.read_transcript()
    except Exception:
        logger.exception("read_transcript failed for session=%s", session_id)
        return
    for entry in entries:
        if isinstance(entry, dict):
            yield entry


def hydrate_from_transcript(session_id: str) -> Optional[GoalState]:
    """Reconstruct the latest :class:`GoalState` from the transcript.

    Scan the entries in arrival order. Each ``{"type": "goal"}``
    entry updates the running state (latest wins); each
    ``{"type": "goal-cleared"}`` entry resets the running state to
    ``None``. A corrupt ``state`` payload is logged and skipped —
    the previous state is preserved in that case.

    Returns ``None`` when no goal is currently persisted for
    ``session_id`` (either nothing was written or the most recent
    entry is a tombstone).
    """
    if not session_id:
        return None
    latest: Optional[GoalState] = None
    for entry in _iter_transcript_entries(session_id):
        entry_type = entry.get("type")
        if entry_type == GOAL_ENTRY_TYPE and entry.get("sessionId") == session_id:
            raw_state = entry.get("state")
            if not isinstance(raw_state, dict):
                logger.warning(
                    "hydrate: dropping malformed goal state in session=%s",
                    session_id,
                )
                continue
            try:
                latest = GoalState.from_dict(raw_state)
            except Exception:
                logger.exception(
                    "hydrate: failed to decode GoalState in session=%s",
                    session_id,
                )
                continue
        elif (
            entry_type == GOAL_CLEARED_ENTRY_TYPE
            and entry.get("sessionId") == session_id
        ):
            latest = None
        # All other entries are unrelated chat/tool messages.
    return latest


__all__ = [
    "GOAL_CLEARED_ENTRY_TYPE",
    "GOAL_ENTRY_TYPE",
    "hydrate_from_transcript",
    "persist_goal",
    "persist_goal_cleared",
]

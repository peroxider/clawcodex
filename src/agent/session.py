"""Session management with persistence.

The session ID is authoritative-from-bootstrap: ``Session.create`` reads
``get_session_id()`` rather than generating its own. This fixes the
strftime-collision bug (sessions started in the same second would have
overlapped IDs) and unifies session identity across the codebase — the
bootstrap singleton is the single source of truth, exactly per Chapter 3.

``Session.load(sid)`` continues to read from disk by ID; the resume path
should call ``switch_session(SessionId(sid))`` first (or via a wrapping
helper) to update the bootstrap singleton, then call ``Session.load(sid)``
to reconstruct the per-conversation Persistence record.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from src.bootstrap.state import (
    get_model_usage,
    get_session_id,
    get_start_time,
    get_total_api_duration,
    get_total_api_duration_without_retries,
    get_total_cost_usd,
    get_total_lines_added,
    get_total_lines_removed,
    get_total_tool_duration,
)

from .conversation import Conversation


@dataclass
class Session:
    """Session manager with persistence."""
    session_id: str
    provider: str
    model: str
    conversation: Conversation = field(default_factory=Conversation)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def save(self):
        """Save session to disk including a cost block.

        Ch03 round-2 (R2.1): the ``cost`` key matches the schema read by
        ``src/services/cost_restore.py:restore_cost_state_for_session``
        so a save → load round-trip restores bootstrap counters
        (`total_cost_usd`, durations, lines added/removed, per-model
        usage). Previously this method emitted no cost block; the
        restore reader hit defaults of 0 unconditionally.

        Also persists conversation messages via :class:`SessionStorage`
        (JSONL transcript) so ``--resume`` can attach a
        :class:`TailFollower` to watch for lines written by a
        backgrounded agent.
        """
        session_dir = Path.home() / ".clawcodex" / "sessions" / self.session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        session_file = session_dir / "session.json"

        cost_block = _snapshot_cost_block()

        session_data = {
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "conversation": self.conversation.to_dict(),
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "cost": cost_block,
        }

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

        self.updated_at = datetime.now().isoformat()

        # Also persist via SessionStorage (JSONL transcript) so
        # TailFollower can observe new lines during --resume.
        # Implementation lives in extensions/agent/session_persist.py
        # so the upstream Session stays free of orchestrator-specific
        # persistence concerns.
        try:
            from extensions.agent.session_persist import save_to_session_storage
            save_to_session_storage(self)
        except ImportError:
            pass

    def save_transcript(self):
        """Lightweight per-turn save: JSONL transcript only.

        Skips the full JSON snapshot (``self.save()`` writes that) so
        each call costs O(new messages) rather than O(conversation size).
        The full snapshot with cost block is written once at session exit
        via ``save()``.

        ``--resume`` can reconstruct the conversation from the JSONL
        transcript alone (via ``SessionStorage.read_messages()``), so
        intermediate snapshots are unnecessary for correctness.
        """
        try:
            from extensions.agent.session_persist import save_to_session_storage
            save_to_session_storage(self)
        except ImportError:
            pass

    @classmethod
    def load(cls, session_id: str) -> Optional['Session']:
        """Load session from disk.

        F-49 P5-B/P5-D: primary source is ``session.json`` (fast path).
        When ``session.json`` does not exist (orchestrator/cron sessions
        that only write JSONL), falls back to scanning ``transcript.jsonl``:
        - metadata.json -> ``model`` / ``created_at``.
        - Message lines -> ``conversation.messages``.
        """
        session_dir = Path.home() / ".clawcodex" / "sessions" / session_id
        session_file = session_dir / "session.json"

        # Fast path: .json snapshot exists.
        if session_file.exists():
            with open(session_file, 'r') as f:
                data = json.load(f)
            return cls(
                session_id=data["session_id"],
                provider=data["provider"],
                model=data["model"],
                conversation=Conversation.from_dict(data["conversation"]),
                created_at=data["created_at"],
                updated_at=data["updated_at"]
            )

        # F-49 P5-D: fallback --- read metadata and messages from JSONL
        # transcript.  This lets orchestrator/cron sessions load via the
        # standard ``Session.load()`` path without the explicit
        # ``load_from_session_storage`` call in ``resume()``.
        transcript_path = session_dir / "transcript.jsonl"
        metadata_path = session_dir / "metadata.json"
        if not transcript_path.exists():
            return None

        # Read metadata for model/created_at
        provider = ""
        model = ""
        created_at = ""
        updated_at = ""
        if metadata_path.exists():
            try:
                md = json.loads(metadata_path.read_text())
                model = md.get("model", "")
                created_at = str(md.get("start_time", ""))
                updated_at = str(md.get("last_updated", ""))
            except (OSError, json.JSONDecodeError):
                pass

        # Read messages from transcript
        from src.types.messages import message_from_dict
        from src.services.session_storage import SessionStorage

        storage = SessionStorage(session_id=session_id)
        entries = storage.read_transcript()
        messages = []
        for entry in entries:
            if (
                entry.get("role") == "system"
                and entry.get("content") == "__background_complete__"
            ):
                continue
            try:
                messages.append(message_from_dict(entry))
            except Exception:
                pass

        return cls(
            session_id=session_id,
            provider=provider,
            model=model,
            conversation=Conversation(messages=messages),
            created_at=created_at,
            updated_at=updated_at,
        )

    @classmethod
    def create(cls, provider: str, model: str) -> 'Session':
        """Create a new session using the bootstrap singleton's session ID.

        Previously this generated its own strftime-based ID, producing
        collisions when two sessions started in the same second and
        diverging from the rest of the codebase. Now reads
        ``get_session_id()`` — a UUID-based ID generated at bootstrap
        import time — so every consumer that talks about "the current
        session" agrees on the identifier.
        """
        return cls(
            session_id=get_session_id(),
            provider=provider,
            model=model,
        )

    @classmethod
    def resume(cls, session_id: str) -> Optional['Session']:
        """Resume a session: update bootstrap identity, restore cost,
        reconstruct the per-conversation record from disk.

        Ch03 round-2 (R2.2): single entry point that keeps the three
        operations in lockstep (CC-34 single-setter discipline at the
        resume layer). Callers (REPL ``/resume``, headless / SDK)
        should use this rather than calling ``Session.load`` plus
        ``switch_session`` plus ``restore_cost_state_for_session``
        independently.

        Order matters: ``switch_session`` fires BEFORE
        ``restore_cost_state_for_session`` so any subscriber that reads
        ``get_session_id()`` during the cost restore sees the loaded id.

        F-49 Phase 0.2: also accepts sessions stored in the
        :class:`SessionStorage` directory format
        (``~/.clawcodex/sessions/<sid>/transcript.jsonl`` + ``metadata.json``).
        This is the on-disk shape the orchestrator's
        :class:`AgentRunner` writes — the headless run is keyed by
        ``run_id`` and persists there so ``clawcodex --resume <run_id>``
        works for orchestrator sessions without a second flat-file
        write. Provider is left as ``""`` because SessionStorage does
        not record it; the resume target's provider should be
        supplied by the caller (REPL config, env, etc.).
        """
        from src.bootstrap.state import SessionId, switch_session
        from src.services.cost_restore import restore_cost_state_for_session

        loaded = cls.load(session_id)
        if loaded is None:
            # F-49 P5-D: Session.load() now falls back to reading
            # from transcript.jsonl when session.json does not
            # exist (load() returns a fully populated Session with
            # messages).  The old load_from_session_storage fallback
            # has been removed.
            return None
        # F-49 Phase 0.4.1 / P5-D: safety net --- if messages are still empty
        # (should no longer happen now that Session.load() reads JSONL
        # directly), back-fill from the SessionStorage transcript.  Kept
        # as a defensive double-check for backward compatibility.
        if not loaded.conversation.messages:
            try:
                from src.services.session_storage import SessionStorage
                from src.types.messages import message_from_dict

                storage = SessionStorage(session_id=session_id)
                entries = storage.read_transcript()
                if entries:
                    messages = []
                    for entry in entries:
                        # Skip background-completion markers
                        if (
                            entry.get("role") == "system"
                            and entry.get("content") == "__background_complete__"
                        ):
                            continue
                        try:
                            messages.append(message_from_dict(entry))
                        except Exception:
                            pass
                    if messages:
                        loaded.conversation.messages = messages
            except Exception:
                pass  # Best-effort; don't fail resume
        # F-9: hydrate the long-running ``/goal`` state machine from
        # the JSONL transcript. The goal state is persisted as
        # ``{"type": "goal", ...}`` / ``{"type": "goal-cleared", ...}``
        # entries by ``clawcodex_ext/goal/storage.py``; without this
        # hydration a resumed session would have no idea an active
        # goal was in flight, and ``/goal status`` would falsely
        # report "no active goal". Hydration runs after the transcript
        # backfill so the registry observes the same on-disk shape the
        # model previously wrote.
        try:
            from clawcodex_ext.goal.registry import get_goal_registry
            get_goal_registry().hydrate_from_transcript(session_id)
        except Exception:
            pass  # Best-effort; resume must not fail on missing goal state
        switch_session(SessionId(session_id))
        restore_cost_state_for_session(session_id)
        return loaded




def _snapshot_cost_block() -> dict:
    """Build the cost block written by ``Session.save``.

    Shape matches the reader at
    ``src/services/cost_restore.py:restore_cost_state_for_session``.
    Module-private; tests can call via the public ``Session.save``.
    """
    return {
        "total_cost_usd": get_total_cost_usd(),
        "total_api_duration": get_total_api_duration(),
        "total_api_duration_without_retries":
            get_total_api_duration_without_retries(),
        "total_tool_duration": get_total_tool_duration(),
        "total_lines_added": get_total_lines_added(),
        "total_lines_removed": get_total_lines_removed(),
        # last_duration = elapsed since start_time. cost_restore uses
        # this to back-date the new session's start_time so post-resume
        # duration accumulators continue from where they left off.
        "last_duration": time.time() - get_start_time(),
        "model_usage": {
            model: {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_creation_input_tokens": u.cache_creation_input_tokens,
                "cache_read_input_tokens": u.cache_read_input_tokens,
                "cost_usd": u.cost_usd,
            }
            for model, u in get_model_usage().items()
        },
    }

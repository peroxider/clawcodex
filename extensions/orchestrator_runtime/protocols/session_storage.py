"""Orchestrator Runtime — SessionStorage Protocol（Phase 1）。

声明 agent session 持久化与跨重启恢复契约。Phase 3-4 在 ClawcodexBackend
中包装 ``clawcodex_ext.services.session_storage.SessionStorage``。

完整契约见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §4.3。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionMeta(Protocol):
    """Structural metadata for a persisted session."""

    session_id: str
    workspace: Path
    created_at: str  # ISO-8601


@runtime_checkable
class ConversationLike(Protocol):
    """Structural type for a serializable conversation.

    Compatible with ``clawcodex_ext.agent.conversation.Conversation``:
    ``messages``, ``provider``, ``model`` are accessible as attributes.
    """

    messages: list[Any]
    provider: str | None
    model: str | None


class SessionStorage(Protocol):
    """Persist + recover agent sessions across orchestrator restarts."""

    def save(self, session_id: str, conversation: ConversationLike) -> None:
        ...

    def load(self, session_id: str) -> ConversationLike | None:
        ...

    def list_sessions(
        self,
        workspace: Path | None = None,
    ) -> list[SessionMeta]:
        ...

    def session_dir(self) -> Path:
        """Return the canonical sessions directory (e.g. ``~/.codex/sessions/``)."""
        ...


__all__ = ["ConversationLike", "SessionMeta", "SessionStorage"]

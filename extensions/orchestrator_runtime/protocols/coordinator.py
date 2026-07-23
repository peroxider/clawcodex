"""Orchestrator Runtime — Coordinator Context Provider Protocol（Phase 1）。

Multi-agent 协同模式 (modes/coordinator.py) 通过 ``CoordinatorContextProvider``
进入 / 离开协调上下文。本 Protocol 让 Phase 3-4 替换
``clawcodex_ext.coordinator.mode.coordinator_mode_context`` 兼容。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class CoordinatorContextProvider(Protocol):
    """Bridge over ``clawcodex_ext.coordinator.mode.coordinator_mode_context``.

    Phase 3+ uses this Protocol to decouple orchestrator from clawcodex
    coordinator implementation. Today the ``extensions/orchestrator/`` code
    uses ``coordinator_mode_context`` directly; Phase 3 routes via this
    Protocol.
    """

    def is_active(self) -> bool:
        ...

    def enter(self, enabled: bool) -> AbstractContextManager[None]:
        """Returns a context manager; entering with ``enabled=True`` flips
        the coordinator-mode gate for the lifetime of the block.

        Mirrors the upstream ``coordinator_mode_context(enabled)`` semantics.
        """
        ...


__all__ = ["CoordinatorContextProvider"]

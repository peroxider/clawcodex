"""Orchestrator Runtime — DiagnosticsProbe Protocol（Phase 1）。

Orchestrator 心跳循环调用 ``DiagnosticsProbe.heartbeat()`` 检测
进程冻结 / 死锁。Phase 2 落地 ``FreezeDetector`` 默认实现
(从 ``clawcodex_ext.diagnostics.freeze_detector`` 复制)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

HeartbeatState = Literal["alive", "frozen", "stalled"]


@dataclass(slots=True)
class HeartbeatStatus:
    """Result of one ``heartbeat()`` snapshot.

    Attributes:
        state: ``alive`` / ``frozen`` / ``stalled``
        last_tick_age: seconds since the last tick the watcher observed
        detail: optional free-form context (free-form string)
    """

    state: HeartbeatState
    last_tick_age: float
    detail: str = ""


@runtime_checkable
class DiagnosticsProbe(Protocol):
    """Called by orchestrator heartbeat loop."""

    def heartbeat(self) -> HeartbeatStatus:
        ...


__all__ = ["DiagnosticsProbe", "HeartbeatState", "HeartbeatStatus"]

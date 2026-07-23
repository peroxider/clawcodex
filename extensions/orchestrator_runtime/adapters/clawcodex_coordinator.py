"""ClawcodexCoordinatorProvider — concrete ``CoordinatorContextProvider`` adapter.

薄包装 ``clawcodex_ext.coordinator.mode.coordinator_mode_context`` /
``is_coordinator_mode``，让 agent_runner 的 L882/L967 不再直连上游。

设计
====

* ``enter()`` 返回上游的 contextmanager；同步其退出语义。
* ``is_active()`` 转发上游 ``is_coordinator_mode()``。
* 不持任何 state —— 每次调用都查上游（与原行为一致）。
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from extensions.orchestrator_runtime.protocols.coordinator import (
    CoordinatorContextProvider,
)

if TYPE_CHECKING:
    pass


class ClawcodexCoordinatorProvider(CoordinatorContextProvider):
    """Forward to ``clawcodex_ext.coordinator.mode``."""

    def is_active(self) -> bool:
        from clawcodex_ext.coordinator.mode import is_coordinator_mode

        return bool(is_coordinator_mode())

    def enter(self) -> AbstractContextManager[None]:
        from clawcodex_ext.coordinator.mode import coordinator_mode_context

        # ``coordinator_mode_context(enabled)`` takes a bool argument; the
        # Protocol contract says ``enter()`` returns a context manager that
        # "enters coordinator mode". We default-enable on entry.
        return coordinator_mode_context(True)  # type: ignore[return-value]


__all__ = ["ClawcodexCoordinatorProvider"]
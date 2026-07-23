"""Orchestrator-local bootstrap-state Protocol (Phase 3).

AgentRunner 在 ``_save_json_snapshot`` 内调用 ``clawcodex_ext.bootstrap.state``
的 8 个 getter（cost / timing / lines）来重建 resume snapshot 的 cost_block。

Phase 3 把这 8 个 getter 包成 Protocol（``BootstrapState``），让
``_save_json_snapshot`` 走 ``self._bootstrap_state.get_total_cost_usd()`` 而非
直连 ``clawcodex_ext``。

设计
====

* **不 import ``clawcodex_ext.*``** —— Protocol 模块严格保持反向耦合约束。
* 默认实现见 :mod:`extensions.orchestrator_runtime.adapters.clawcodex_bootstrap_state`。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BootstrapState(Protocol):
    """Facade over ``clawcodex_ext.bootstrap.state`` cost/timing getters.

    Default impl (``ClawcodexBootstrapState``) forwards every call to the
    upstream module; tests can substitute a stub to control session-level
    accumulators.
    """

    def get_total_cost_usd(self) -> float: ...

    def get_total_api_duration(self) -> int: ...

    def get_total_api_duration_without_retries(self) -> int: ...

    def get_total_tool_duration(self) -> int: ...

    def get_total_lines_added(self) -> int: ...

    def get_total_lines_removed(self) -> int: ...

    def get_start_time(self) -> int | None: ...

    def get_model_usage(self) -> dict[str, Any]: ...


__all__ = ["BootstrapState"]
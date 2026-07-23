"""ClawcodexBootstrapState — concrete ``BootstrapState`` Protocol adapter.

薄包装 ``clawcodex_ext.bootstrap.state`` 的 8 个 cost/timing getter，让
agent_runner 的 ``_save_json_snapshot`` (L340-349) 不再直连上游。

设计
====

* 8 个 getter 一对一转发；不持 state、不缓存 —— 与上游语义一致。
* Lazy import：构造时才引上游（适配器允许引用 upstream）。
"""
from __future__ import annotations

from typing import Any

from extensions.orchestrator_runtime.utils.bootstrap_state import BootstrapState


class ClawcodexBootstrapState(BootstrapState):
    """Forward every getter to ``clawcodex_ext.bootstrap.state``."""

    def get_total_cost_usd(self) -> float:
        from clawcodex_ext.bootstrap.state import get_total_cost_usd

        return float(get_total_cost_usd())

    def get_total_api_duration(self) -> int:
        from clawcodex_ext.bootstrap.state import get_total_api_duration

        return int(get_total_api_duration())

    def get_total_api_duration_without_retries(self) -> int:
        from clawcodex_ext.bootstrap.state import (
            get_total_api_duration_without_retries,
        )

        return int(get_total_api_duration_without_retries())

    def get_total_tool_duration(self) -> int:
        from clawcodex_ext.bootstrap.state import get_total_tool_duration

        return int(get_total_tool_duration())

    def get_total_lines_added(self) -> int:
        from clawcodex_ext.bootstrap.state import get_total_lines_added

        return int(get_total_lines_added())

    def get_total_lines_removed(self) -> int:
        from clawcodex_ext.bootstrap.state import get_total_lines_removed

        return int(get_total_lines_removed())

    def get_start_time(self) -> int | None:
        from clawcodex_ext.bootstrap.state import get_start_time

        return get_start_time()

    def get_model_usage(self) -> dict[str, Any]:
        from clawcodex_ext.bootstrap.state import get_model_usage

        return dict(get_model_usage())


__all__ = ["ClawcodexBootstrapState"]
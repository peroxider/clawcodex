"""Orchestrator 解耦运行时子模块（仓内孵化层）。

完整设计见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md``。
本次提交仅落地 §10.2 子集（Phase 0 + Phase 1 + Phase 2），后续 Phase 3-6
在仓内渐进推进。

发布形态：仓内子模块（单仓 monorepo 模式），不发布独立 PyPI 包。
入口策略：当 ``ORCHESTRATOR_USE_RUNTIME=1`` 时启用委托路径（Phase 2 完成
后激活），否则显式走 ``extensions.orchestrator`` 旧实现。
"""

from __future__ import annotations

__version__ = "0.1.0a0"

# Phase 0 仅为标识；Phase 2 完成前 ``ORCHESTRATOR_USE_RUNTIME`` 默认被忽略。
# 见 ``extensions.orchestrator_runtime.adapters.clawcodex_compat``。

__all__ = ["__version__"]

"""Orchestrator Runtime — 适配层（Phase 2 + Phase 3）。

Phase 2: ``clawcodex_compat`` 透明转发层，让 ``extensions.orchestrator/``
内部 import 从 ``clawcodex_ext.*`` 切换到本模块而行为不变。

Phase 3: 新增 4 个 default Protocol adapter + 1 个 BootstrapState adapter，
供 ``AgentRunner`` / ``OrchestratorGatewayClient`` 通过 kw 参数注入：

* :class:`ClawcodexAgentRuntime` — 包装 ``extensions.api.query.QueryRunner``
* :class:`ClawcodexSessionStorage` — 包装 ``clawcodex_ext.services.session_storage``
* :class:`ClawcodexCoordinatorProvider` — 包装 ``clawcodex_ext.coordinator.mode``
* :class:`ClawcodexImChannel` — 包装 ``OrchestratorGatewayClient``
* :class:`ClawcodexBootstrapState` — 包装 ``clawcodex_ext.bootstrap.state``

工厂函数
========

``build_default_*()`` 返回单例缓存的默认实现 —— ``AgentRunner.__init__``
可以无脑调用 ``build_default_agent_runtime()``，测试时替换为 stub。
"""
from __future__ import annotations

from extensions.orchestrator_runtime.adapters.clawcodex_agent_runtime import (
    ClawcodexAgentRuntime,
)
from extensions.orchestrator_runtime.adapters.clawcodex_bootstrap_state import (
    ClawcodexBootstrapState,
)
from extensions.orchestrator_runtime.adapters.clawcodex_coordinator import (
    ClawcodexCoordinatorProvider,
)
from extensions.orchestrator_runtime.adapters.clawcodex_im_channel import (
    ClawcodexImChannel,
)
from extensions.orchestrator_runtime.adapters.clawcodex_session_storage import (
    ClawcodexSessionStorage,
)

# ─── Singletons (lazy via module-level globals; tests can ``del`` to reset) ──

_agent_runtime_singleton: ClawcodexAgentRuntime | None = None
_session_storage_singleton: ClawcodexSessionStorage | None = None
_coordinator_singleton: ClawcodexCoordinatorProvider | None = None
_bootstrap_state_singleton: ClawcodexBootstrapState | None = None


def build_default_agent_runtime() -> ClawcodexAgentRuntime:
    """Return a cached default ``AgentRuntime`` adapter."""
    global _agent_runtime_singleton
    if _agent_runtime_singleton is None:
        _agent_runtime_singleton = ClawcodexAgentRuntime()
    return _agent_runtime_singleton


def build_default_session_storage() -> ClawcodexSessionStorage:
    """Return a cached default ``SessionStorage`` adapter."""
    global _session_storage_singleton
    if _session_storage_singleton is None:
        _session_storage_singleton = ClawcodexSessionStorage()
    return _session_storage_singleton


def build_default_coordinator_provider() -> ClawcodexCoordinatorProvider:
    """Return a cached default ``CoordinatorContextProvider`` adapter."""
    global _coordinator_singleton
    if _coordinator_singleton is None:
        _coordinator_singleton = ClawcodexCoordinatorProvider()
    return _coordinator_singleton


def build_default_bootstrap_state() -> ClawcodexBootstrapState:
    """Return a cached default ``BootstrapState`` adapter."""
    global _bootstrap_state_singleton
    if _bootstrap_state_singleton is None:
        _bootstrap_state_singleton = ClawcodexBootstrapState()
    return _bootstrap_state_singleton


def reset_adapters_for_tests() -> None:
    """Drop all singletons so the next ``build_default_*()`` recreates them.

    Tests that want to swap a default implementation should call this after
    patching the underlying module attribute.
    """
    global _agent_runtime_singleton
    global _session_storage_singleton
    global _coordinator_singleton
    global _bootstrap_state_singleton
    _agent_runtime_singleton = None
    _session_storage_singleton = None
    _coordinator_singleton = None
    _bootstrap_state_singleton = None


__all__ = [
    "ClawcodexAgentRuntime",
    "ClawcodexBootstrapState",
    "ClawcodexCoordinatorProvider",
    "ClawcodexImChannel",
    "ClawcodexSessionStorage",
    "build_default_agent_runtime",
    "build_default_bootstrap_state",
    "build_default_coordinator_provider",
    "build_default_session_storage",
    "reset_adapters_for_tests",
]
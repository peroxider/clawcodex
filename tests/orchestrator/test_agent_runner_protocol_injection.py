"""Phase 3: AgentRunner Protocol injection unit tests.

Covers the three new kw-only constructor parameters
(``agent_runtime``, ``session_storage``, ``coordinator_provider``)
and the lazy default-resolution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from extensions.orchestrator.agent_runner import AgentRunner
from extensions.orchestrator.config.schema import AgentConfig, SandboxConfig, WorkspaceConfig


@dataclass(frozen=True)
class StubAgentRuntime:
    """Test-only runtime satisfying the AgentRuntime Protocol structurally."""

    marker: str = "stub-runtime"

    async def stream(self, **kwargs: Any) -> Any:
        return AsyncMock()

    async def resume(self, **kwargs: Any) -> Any:
        return AsyncMock()


@dataclass(frozen=True)
class StubSessionStorage:
    """Test-only session storage satisfying the SessionStorage Protocol."""

    marker: str = "stub-storage"

    def save(self, session_id: str, conversation: Any) -> None:
        return None

    def load(self, session_id: str) -> Any | None:
        return None

    def list_sessions(self, workspace: Path | None = None) -> list[Any]:
        return []

    def session_dir(self) -> Path:
        return Path("/tmp/stub-sessions")


@dataclass(frozen=True)
class StubCoordinator:
    """Test-only coordinator context provider."""

    marker: str = "stub-coordinator"
    _active: bool = False

    def is_active(self) -> bool:
        return self._active

    def enter(self, enabled: bool = True) -> Any:
        class _CM:
            def __enter__(self) -> "_CM":
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

        return _CM()


@pytest.fixture
def runner_configs() -> tuple[AgentConfig, SandboxConfig, WorkspaceConfig]:
    return AgentConfig(), SandboxConfig(), WorkspaceConfig()


def test_default_construction_does_not_activate_protocols(
    runner_configs: tuple[AgentConfig, SandboxConfig, WorkspaceConfig],
) -> None:
    """Legacy callers that omit all 3 kw args get _protocols_active=False."""
    agent_cfg, sandbox_cfg, workspace_cfg = runner_configs
    runner = AgentRunner(agent_cfg, sandbox_cfg, workspace_cfg)

    assert runner._protocols_active is False
    assert runner._agent_runtime is None
    assert runner._session_storage is None
    assert runner._coordinator is None


def test_injected_protocols_are_stored_without_default_resolution(
    runner_configs: tuple[AgentConfig, SandboxConfig, WorkspaceConfig],
) -> None:
    """If any kw arg is provided, _resolve_protocols() remains a no-op."""
    agent_cfg, sandbox_cfg, workspace_cfg = runner_configs
    runtime = StubAgentRuntime()
    storage = StubSessionStorage()
    coordinator = StubCoordinator()

    runner = AgentRunner(
        agent_cfg,
        sandbox_cfg,
        workspace_cfg,
        agent_runtime=runtime,
        session_storage=storage,
        coordinator_provider=coordinator,
    )

    assert runner._protocols_active is True
    assert runner._agent_runtime is runtime
    assert runner._session_storage is storage
    assert runner._coordinator is coordinator

    # Calling _resolve_protocols() must not swap in default adapters.
    runner._resolve_protocols()
    assert runner._agent_runtime is runtime
    assert runner._session_storage is storage
    assert runner._coordinator is coordinator


def test_lazy_default_resolution_builds_adapters(
    runner_configs: tuple[AgentConfig, SandboxConfig, WorkspaceConfig],
) -> None:
    """A default-constructed runner resolves Clawcodex adapters on demand."""
    agent_cfg, sandbox_cfg, workspace_cfg = runner_configs
    runner = AgentRunner(agent_cfg, sandbox_cfg, workspace_cfg)

    runner._resolve_protocols()

    assert runner._protocols_active is True
    assert runner._agent_runtime is not None
    assert runner._session_storage is not None
    assert runner._coordinator is not None
    # Default implementations come from Clawcodex factories.
    assert type(runner._agent_runtime).__name__ == "ClawcodexAgentRuntime"
    assert type(runner._session_storage).__name__ == "ClawcodexSessionStorage"
    assert type(runner._coordinator).__name__ == "ClawcodexCoordinatorProvider"
    assert type(runner._bootstrap_state).__name__ == "ClawcodexBootstrapState"


def test_partial_injection_still_activates_protocols(
    runner_configs: tuple[AgentConfig, SandboxConfig, WorkspaceConfig],
) -> None:
    """Partial injection is allowed: provided params are stored, and defaults
    are skipped for the whole protocol group (all-or-nothing resolution)."""
    agent_cfg, sandbox_cfg, workspace_cfg = runner_configs
    runtime = StubAgentRuntime()
    runner = AgentRunner(
        agent_cfg,
        sandbox_cfg,
        workspace_cfg,
        agent_runtime=runtime,
    )

    assert runner._protocols_active is True
    assert runner._agent_runtime is runtime
    # Remaining protocols stay None because at least one protocol was
    # injected; _resolve_protocols() becomes a no-op.
    assert runner._session_storage is None
    assert runner._coordinator is None

    runner._resolve_protocols()
    # All-or-nothing: injected runtime is preserved, missing ones remain None.
    assert runner._agent_runtime is runtime
    assert runner._session_storage is None
    assert runner._coordinator is None

"""capabilities — Layer 2: ClawCodex-specific Protocol definitions.

This package defines the interface contracts (Protocol classes) that form the
boundary between Layer 1 (upstream compat) and Layer 3 (features).

Design rules:
  - Use typing.Protocol for structural subtyping
  - No ABC inheritance (informal interfaces only)
  - No implementation — only method signatures with NotImplementedError
  - No imports from src.upstream (Layer 2 cannot depend on Layer 1)

Phase 1 status: stub Protocol files with NotImplementedError.
Actual implementation is Phase 2/3 work.

See: docs/UPSTREAM_SYNC_DESIGN-decoupling.md Section 4.2
"""

from .agent_protocol import AgentLoopProtocol, AgentLoopResultProtocol
from .dashboard_entry import (
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSink,
    DashboardSource,
    filter_entries,
    normalize_source_name,
)
from .tool_protocol import (
    ToolContextProtocol,
    ToolPermissionContextProtocol,
    ToolProtocol,
    ToolRegistryProtocol,
    ToolSystemProtocol,
)
from .context_protocol import ContextBuilderProtocol
from .provider_protocol import LLMProviderProtocol
from .event_protocol import ToolEventProtocol
from .headless_protocol import HeadlessOptionsProtocol, HeadlessRunnerProtocol
from .headless_runner import HeadlessSessionOptions, run_headless_session
from .adapter_protocol import (  # noqa: F401
    AdapterInfo,
    AdapterProtocol,
    AdapterRegistry,
    dependency_available,
    env_switch,
    is_provider_adapter,
)

__all__ = [
    "AdapterInfo",
    "AdapterProtocol",
    "AdapterRegistry",
    "AgentLoopProtocol",
    "AgentLoopResultProtocol",
    "ContextBuilderProtocol",
    "DASHBOARD_STATUSES",
    "DashboardEntry",
    "DashboardSink",
    "DashboardSource",
    "HeadlessOptionsProtocol",
    "HeadlessRunnerProtocol",
    "HeadlessSessionOptions",
    "LLMProviderProtocol",
    "ToolContextProtocol",
    "ToolEventProtocol",
    "ToolPermissionContextProtocol",
    "ToolProtocol",
    "ToolRegistryProtocol",
    "ToolSystemProtocol",
    "dependency_available",
    "env_switch",
    "filter_entries",
    "is_provider_adapter",
    "normalize_source_name",
    "run_headless_session",
]

"""Capabilities bridge — re-exports from extensions.capabilities.

This module exists so adapter modules in ``clawcodex_ext/`` can import
from a stable path without depending directly on ``extensions/``
internal structure.  All definitions live in
``extensions/capabilities/``.
"""

from extensions.capabilities.adapter_protocol import (  # noqa: F401
    AdapterInfo,
    AdapterProtocol,
    AdapterRegistry,
    dependency_available,
    env_switch,
    is_provider_adapter,
)
from extensions.capabilities.agent_protocol import (  # noqa: F401
    AgentLoopProtocol,
)
from extensions.capabilities.context_protocol import (  # noqa: F401
    ContextBuilderProtocol,
)
from extensions.capabilities.event_protocol import (  # noqa: F401
    ToolEventProtocol,
)
from extensions.capabilities.headless_protocol import (  # noqa: F401
    HeadlessOptionsProtocol,
    HeadlessRunnerProtocol,
)
from extensions.capabilities.headless_runner import (  # noqa: F401
    HeadlessSessionOptions,
    run_headless_session,
)
from extensions.capabilities.provider_protocol import (  # noqa: F401
    LLMProviderProtocol,
)
from extensions.capabilities.tool_protocol import (  # noqa: F401
    ToolSystemProtocol,
)

__all__ = [
    "AdapterInfo",
    "AdapterProtocol",
    "AdapterRegistry",
    "AgentLoopProtocol",
    "ContextBuilderProtocol",
    "HeadlessOptionsProtocol",
    "HeadlessRunnerProtocol",
    "HeadlessSessionOptions",
    "LLMProviderProtocol",
    "ToolEventProtocol",
    "ToolSystemProtocol",
    "dependency_available",
    "env_switch",
    "is_provider_adapter",
    "run_headless_session",
]

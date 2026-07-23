"""clawcodex 兼容 shim — orchestrator 内部 import 切换目标（Phase 2）。

把 ``extensions/orchestrator/{git_sync,orchestrator,agent_runner,
im_gateway_client,prompt_builder}.py`` 中对 ``clawcodex_ext.*`` 的
import 改为从本模块 re-export，**不改任何函数体**。

设计动机
========

原始 orchestrator 与 13 处 ``from clawcodex_ext.*`` 紧耦合（详见
``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §2）。一次性改 import 路径
容易触发回归；本层在仓内提供「透明转发」，让调用方几乎无感切换：

    # 之前
    from clawcodex_ext.utils.git import get_file_status

    # Phase 2 后
    from extensions.orchestrator_runtime.adapters.clawcodex_compat import (
        get_file_status,
    )

行为不变，因为本模块把 ``clawcodex_ext.*`` 的同一对象 re-export。

Phase 3 之后，``extensions/orchestrator/{git_sync,orchestrator}`` 内部
改走 Protocol-based ``GitBackend``，本层将被删除。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# C8 — git subprocess wrapper & dataclasses
# ---------------------------------------------------------------------------
from clawcodex_ext.utils.git import (  # noqa: F401 — re-export
    FileStatus,
    _run_git,
    get_current_branch,
    get_default_branch,
    get_file_status,
    get_repo_root,
)

# ---------------------------------------------------------------------------
# C7 — LLM API errors
# ---------------------------------------------------------------------------
from clawcodex_ext.services.api.errors import (  # noqa: F401 — re-export
    RateLimitError,
    is_rate_limit_error,
)

# ---------------------------------------------------------------------------
# C5 — Channel capability markers
# ---------------------------------------------------------------------------
from clawcodex_ext.services.channels.capabilities import (  # noqa: F401
    CardUpdateCapability,
    ChannelCapability,
)

# ---------------------------------------------------------------------------
# C2 — Tool execution context
# ---------------------------------------------------------------------------
from clawcodex_ext.tool_system.context import ToolContext  # noqa: F401

# ---------------------------------------------------------------------------
# C5 — IM gateway message models
# ---------------------------------------------------------------------------
from clawcodex_ext.services.im_gateway.models import (  # noqa: F401
    InboundMessage,
    MessageSemantics,
)

# ---------------------------------------------------------------------------
# C5 — Message semantics (CommandRouter + ControlBridge)
# ---------------------------------------------------------------------------
from clawcodex_ext.messaging.semantics import (  # noqa: F401
    CommandRouter,
    ControlBridge,
)

# ---------------------------------------------------------------------------
# C1 — Agent definition guidelines (prompt template hint)
# ---------------------------------------------------------------------------
from clawcodex_ext.agent.agent_definitions import task_v2_guidelines  # noqa: F401


__all__ = [
    "CardUpdateCapability",
    "ChannelCapability",
    "CommandRouter",
    "ControlBridge",
    "FileStatus",
    "InboundMessage",
    "MessageSemantics",
    "RateLimitError",
    "ToolContext",
    "_run_git",
    "get_current_branch",
    "get_default_branch",
    "get_file_status",
    "get_repo_root",
    "is_rate_limit_error",
    "task_v2_guidelines",
]

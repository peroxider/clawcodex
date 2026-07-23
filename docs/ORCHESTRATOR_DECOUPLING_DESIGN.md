# Orchestrator 解耦独立发布方案

> **来源**：docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md §4.2.4 判定「高成本但可行」
> **目标**：将 `extensions/orchestrator/`（43,643 行 / 101 个文件）拆为独立 PyPI 包 `orchestratord`，上游 ClawCodex 仅作为「执行后端」之一可插拔替换。
> **本文状态**：Phase 0+1+2+3（§10.2 可独立启动子集 + agent_runner/im_gateway_client 核心迁移）✅ 已落地（commit `2dcacba8` / `87fd0fe4`，2026-07-23）；Phase 4~6 仍为设计阶段。
> **落地记录**：`~/.claude/projects/-mnt-c-WorkSpace-clawcodex/memory/orchestrator_decoupling_p0p1p2p3_done.md`

---

## 目录

1. [结论与工作量](#1-结论与工作量)
2. [耦合现状盘点](#2-耦合现状盘点)
3. [解耦目标架构](#3-解耦目标架构)
4. [Protocol 接口设计](#4-protocol-接口设计)
5. [独立包结构](#5-独立包结构)
6. [迁移路径（6 个 Phase）](#6-迁移路径6-个-phase)
7. [MCP Server 设计](#7-mcp-server-设计)
8. [向后兼容与回退策略](#8-向后兼容与回退策略)
9. [风险与缓解](#9-风险与缓解)
10. [工作量复核](#10-工作量复核)

---

## 1. 结论与工作量

### 1.1 核心判断

按 `COMMERCIALIZATION_EXECUTIVE_SUMMARY.md §4.2.4` 的判定，orchestrator **高成本但可行**，主要原因：

1. **依赖层厚但不深** — 13 个耦合领域涉及多个子系统，但其中 9 个是「数据类 + 工具函数」级别的弱耦合，可通过 Protocol 抽象化解
2. **核心算法自成体系** — 编排循环、空间管理、意图识别、模式路由、状态日志等核心逻辑（~70% 代码）独立于上游运行时
3. **Graph 已经绘出骨架** — `extensions/capabilities/` 已经存在 14 个 Protocol 文件（`agent_protocol.py` / `tool_protocol.py` / `recorder.py` 等），其中 `agent_protocol.py` 直接以「可被 orchestrator 调用的多轮 Agent 循环」为目标

### 1.2 工作量精算

| 工作块 | 类型 | 行数估计 | 说明 |
|--------|------|---------|------|
| **Protocol 接口定义** | 新增 | ~1,200 | 在 `extensions/capabilities/orchestrator_protocol.py` 集中声明 6 类契约 |
| **数据类内联/复制** | 抽取 | ~800 | Issue / Intent / PullRequestRef / Command / WorkspaceConfig 等已是纯 dataclass，按需复制 |
| **Adapter 适配层** | 新增 | ~1,500 | 6 个 `*_adapter.py` 把上游实现包装成 Protocol 实例；可选注入 |
| **依赖注入容器（DI）** | 新增 | ~400 | `OrchestratorRuntime` 容器统一装载所有 Adapter，可默认用 clawcodex 实现 |
| **测试隔离与双轨验证** | 新增 | ~1,000 | mock backend 与真实 backend 跑同一份测试，验证行为一致性 |
| **独立包骨架** | 新增 | ~600 | `pyproject.toml` / `orchestratord` 入口点 / README / LICENSE / CI |
| **MCP server** | 新增 | ~800 | 把 daemon 入口暴露为 `orchestrator` MCP server 工具 |
| **回归与文档** | 新增 | ~700 | 解耦设计文档、迁移指南、迁移 changelog |
| **合计** | | **~7,000** | 对应原文估算 5,000-8,000 行的中位值（偏上限，因为内联 dataclass + 测试隔离 + docs 是新增成本） |

> **关键洞察**：解耦后的代码膨胀约 16%（43,643 + 7,000 = 50,643 行）。但代码量不是问题 —— 关键是 **独立 repo 体积从 50,000 行下降到 50,000 行（相对上游 50 万行）**，知识产权边界从「相对上游 8%」上升到「完全隔离」。

---

## 2. 耦合现状盘点

通过 `grep "^(from|import) (clawcodex_ext|extensions)\." extensions/orchestrator/ -r` 梳理，得到 13 个耦合领域：

| # | 耦合领域 | 上游模块 | 用途 | 耦合强度 | 抽象难度 |
|---|---------|---------|------|---------|---------|
| C1 | **Agent 运行时** | `clawcodex_ext.agent.conversation.Conversation` `clawcodex_ext.agent.session.Session` `clawcodex_ext.agent.load_agents_dir.get_agents_for_mentions` `clawcodex_ext.agent.agent_definitions.task_v2_guidelines` | 多轮对话循环、Session 管理、Agent 加载与提示词指引 | ⚠️ 强（核心循环） | 高（AgentLoopProtocol 已有骨架） |
| C2 | **工具系统** | `clawcodex_ext.tool_system.context.ToolContext` `clawcodex_ext.tool_system.tools.progress_report._progress_report_call` `clawcodex_ext.tool_system.tools.tasks_v2._task_update_call` | 工具注册/执行上下文、进度报告工具调用、任务状态写工具 | ⚠️ 中（数据类 + 工具调用） | 低（ToolContextProtocol 已有） |
| C3 | **消息/内容类型** | `clawcodex_ext.types.messages.{message_from_dict, create_user_message}` `clawcodex_ext.types.content_blocks.{TextBlock, ToolUseBlock, ToolResultBlock}` | 序列化、反序列化、构造消息 | ✅ 弱（纯 dataclass） | 低（可内联为独立包） |
| C4 | **会话存储** | `clawcodex_ext.services.session_storage.{SessionStorage, SESSIONS_DIR}` `clawcodex_ext.services.session_resume.resume_session` | Session 持久化、跨重启恢复 | ⚠️ 中（文件路径约定 + 持久化格式） | 中（封装 ServiceStorage Protocol） |
| C5 | **IM 通信 Gateway** | `clawcodex_ext.services.im_gateway.models.{InboundMessage, MessageSemantics, OutboundMessage, IM_DIRECT_ALL_ORIGIN}` `clawcodex_ext.services.im_gateway.ipc_client.GatewayIpcClient` `clawcodex_ext.messaging.semantics.{CommandRouter, ControlBridge, MessageClassifier}` `clawcodex_ext.services.channels.capabilities.{CardUpdateCapability, ChannelCapability}` | IM 消息收发、命令路由、控制桥 | ⚠️ 强（多类协作） | 中（ImChannelProtocol 已部分存在） |
| C6 | **Provider** | `clawcodex_ext.providers.runtime.build_provider_from_config` | 构造 LLM provider | ✅ 弱（1 个函数） | 低（LLMProviderProtocol 已有） |
| C7 | **API 错误** | `clawcodex_ext.services.api.errors.{RateLimitError, is_rate_limit_error}` | 429 检测 | ✅ 弱（异常类） | 低（定义独立等价异常） |
| C8 | **Git 工具** | `clawcodex_ext.utils.git.{get_file_status, get_current_branch, get_default_branch, get_repo_root, _run_git}` | git 子进程封装 | ✅ 弱（subprocess wrapper） | 低（封装 GitBackend Protocol） |
| C9 | **Bootstrap 状态** | `clawcodex_ext.bootstrap.state.{...}` | 进程级状态机 | ✅ 弱（少量函数） | 低（封装 BootstrapProbe Protocol） |
| C10 | **Coordinator 模式** | `clawcodex_ext.coordinator.mode.{coordinator_mode_context, is_coordinator_mode}` | 多 Agent 协同上下文 | ⚠️ 中（context manager） | 中（封装 CoordinatorContextProvider） |
| C11 | **Intent forecast** | `clawcodex_ext.intent_forecast.focus.compute_workspace_focuses` | 工作区意图聚焦 | ✅ 弱（纯函数） | 低（封装 IntentFocus Protocol） |
| C12 | **诊断** | `clawcodex_ext.diagnostics.FreezeDetector` | 心跳冻结检测 | ✅ 弱（一个类） | 低（封装 DiagnosticsProbe Protocol） |
| C13 | **Orchestrator 入口** | `clawcodex_ext.entrypoints.orchestrator.run_orchestrator_subcommand` | CLI 子命令分发 | ⚠️ 中（CLI 复用） | 中（CLI 注册走 entry_points） |

### 2.1 耦合强度分布

```
强（需要完整 Protocol + Adapter）：   C1, C5    → 2 个
中（数据/服务层抽象）：                C2, C4, C10, C13 → 4 个
弱（可内联/替代）：                    C3, C6, C7, C8, C9, C11, C12 → 7 个
```

### 2.2 高价值低成本的捷径

以下耦合最低成本解除（按本文设计归为「Phase A 立即解」）：
- **C3 消息类型** — 全部是 dataclass，复制到独立包，~500 行
- **C6/C7 Provider + 错误类型** — 1 个工厂函数 + 1 个异常类 + 1 个判定函数，~50 行
- **C8 Git 工具** — 5 个 git subprocess 包装函数直接搬，~300 行
- **C11 Intent focus** — 1 个纯函数，~200 行
- **C12 Diagnostics** — 1 个类，~150 行

> 这 5 类合计 **~1,200 行** 解耦成本，可在 P0 单 PR 完成，验证独立 orchestrator 的最小可行性边界。

---

## 3. 解耦目标架构

### 3.1 当前三层

```
src/                    Layer 0 — 上游 Claude Code（不依赖 orchestrator）
clawcodex_ext/          Layer 1 — 适配层
extensions/             Layer 2 — 二开功能（含 orchestrator）
```

### 3.2 目标四层

```
┌───────────────────────────────────────────────────────────────┐
│ 独立包 orchestratord (PyPI)                                  │
│   ├── protocols/   (Layer 0′ — Protocol-only, 复用 extensions/capabilities/)
│   ├── core/        (Layer 1′ — 编排核心：orchestrator、agent_runner、git_sync…)
│   ├── adapters/    (Layer 2′ — 上游 clawcodex 适配器，可选)
│   └── cli/         (orchestratord CLI + MCP server)            │
└───────────────────────────────────────────────────────────────┘
                              │ 通过 Protocol 接口
                              ▼
┌───────────────────────────────────────────────────────────────┐
│ clawcodex_ext.orchestratord_adapter (新模块, 在 clawcodex_ext 下) │
│   ├── agent_adapter.py   — 把 clawcodex_ext 的 Agent 包装成 Orchestratord Agent  │
│   ├── tool_adapter.py    — ToolContext 适配                          │
│   ├── im_adapter.py      — ChannelCapability / IM Gateway 适配        │
│   ├── storage_adapter.py — SessionStorage 适配                         │
│   └── runtime.py         — 默认 OrchestratordRuntime 容器              │
└───────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────┐
│ 上游 src/ + clawcodex_ext/ (保留原状, 不感知 orchestrator 已独立) │
└───────────────────────────────────────────────────────────────┘
```

### 3.3 包的核心边界

**独立包 `orchestratord` 承诺**：
1. `pip install orchestratord` 可正常工作
2. 必须安装一个 `Backend`（默认是 `clawcodex_ext.orchestratord_adapter`）
3. `Backend` 是可选依赖 `orchestratord[clawcodex-backend]`
4. 也可以写自己的 Backend（mock backend、Aider backend、Continue backend…）

**设计上不允许**：
1. `orchestratord` 直接 `import clawcodex_ext.*`
2. `orchestratord` 直接 `import src.*`
3. 任何运行时反射访问上游私有属性

**设计上允许**：
1. 通过 `entry_points` 注册 `Backend` 实例：`[orchestratord.backends]` group
2. `setup.cfg` / `pyproject.toml` 声明 Python package 依赖关系，clawcodex_ext.orchestratord_adapter 作为可选依赖安装

---

## 4. Protocol 接口设计

在 `orchestratord/protocols/` 下集中声明 6 类接口。命名约定：`*Protocol`。

### 4.1 AgentRuntime Protocol（对应 C1）

```python
# orchestratord/protocols/agent_runtime.py

from typing import Any, AsyncIterator, Protocol
from pathlib import Path

from .messages import ConversationMessage, ToolCallEvent, PhaseComplete, SessionComplete

class AgentRuntime(Protocol):
    """Single multi-turn agent execution.

    The orchestrator calls :meth:`stream` once per AgentSession; the
    runtime drives the conversation loop, tool execution, and emits
    events until :class:`SessionComplete`.
    """

    async def stream(
        self,
        *,
        prompt: str,
        workspace: Path,
        provider_name: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        session_id: str | None = None,
        on_session: SessionContext | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Async generator yielding :class:`AgentEvent` instances.

        Event sequence:
          - zero or more :class:`TextDelta`
          - zero or more interleave of :class:`ToolCallEvent` / :class:`ToolResultEvent`
          - zero or more :class:`PhaseComplete`
          - exactly one terminal :class:`SessionComplete` (success or failure)
        """
        ...

    async def resume(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
    ) -> AsyncIterator[AgentEvent]:
        """Resume a previously persisted session. :class:`SessionComplete`
        carries ``reason="resumed"`` on success."""
        ...


@dataclass
class AgentEvent:
    """Sum type for events on the agent stream. Discriminate by :attr:`type`."""
    type: Literal["text_delta", "tool_call", "tool_result",
                  "phase_complete", "session_complete"]
    payload: Any
```

### 4.2 WorkspaceTooling Protocol（对应 C2）

```python
# orchestratord/protocols/workspace_tooling.py

class WorkspaceTooling(Protocol):
    """Informs the agent runtime about the workspace being orchestrated.

    The orchestrator's :class:`AgentRunner` calls into the tooling to
    * register custom progress-report tools
    * expose workspace metadata (branch, focus area, rules…)
    """

    def build_tool_context(
        self,
        workspace: Path,
        *,
        branch: str | None = None,
        focus_files: tuple[str, ...] = (),
        rule_hints: tuple[str, ...] = (),
    ) -> ToolContextLike:
        """Return an opaque tool context the runtime passes to tool registry."""

    def progress_report_callback(self) -> Callable[[str], Awaitable[None]] | None:
        """Hook the agent invokes via the internal "progress_report" tool."""

    def task_update_callback(self) -> Callable[[str, str], Awaitable[None]] | None:
        """Hook the agent invokes via the internal "task_update" tool."""


class ToolContextLike(Protocol):
    """Minimal structural type — runtime doesn't introspect."""
    workspace_root: Path | None
    cwd: Path | None
```

### 4.3 SessionStorage Protocol（对应 C4）

```python
# orchestratord/protocols/session_storage.py

class SessionStorage(Protocol):
    """Persist + recover agent sessions across orchestrator restarts."""

    def save(self, session_id: str, conversation: ConversationLike) -> None:
        ...

    def load(self, session_id: str) -> ConversationLike | None:
        ...

    def list_sessions(self, workspace: Path | None = None) -> list[SessionMeta]:
        ...

    def session_dir(self) -> Path:
        """Return the canonical sessions directory."""
```

### 4.4 ImChannel Protocol（对应 C5）

```python
# orchestratord/protocols/im_channel.py

@dataclass
class ImInbound:
    """Mirrors clawcodex_ext.services.im_gateway.models.InboundMessage."""
    origin: str
    text: str
    issue_id: str | None = None
    thread_id: str | None = None
    sender_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImOutbound:
    origin: str
    text: str
    issue_id: str | None = None
    card: dict[str, Any] | None = None  # platform-specific card payload


class ImChannel(Protocol):
    """One integration with an IM platform (Feishu, Slack, Telegram…).

    The orchestrator wires one channel per origin; each channel handles
    its own poll/websocket transport.
    """

    channel_id: str

    async def deliver(self, message: ImOutbound) -> None: ...
    async def listen(self) -> AsyncIterator[ImInbound]: ...
    async def close(self) -> None: ...


class ImCommandRouter(Protocol):
    """Dispatch semantic commands (RETRY / FOLLOWUP / PAUSE / RESUME …)
    into orchestrator operations. Implementations may differ per channel;
    the orchestrator only depends on the contract."""

    async def dispatch(self, inbound: ImInbound) -> ImOutbound | None: ...
```

### 4.5 Provider Protocol（对应 C6）

```python
# orchestratord/protocols/provider.py

class LLMProvider(Protocol):
    """Marker — the orchestrator never calls provider directly. It's
    passed by name to AgentRuntime.stream(); AgentRuntime owns the
    provider lifecycle."""

    name: str
    model: str
```

### 4.6 GitBackend Protocol（对应 C8）

```python
# orchestratord/protocols/git_backend.py

class GitBackend(Protocol):
    """Shim over ``git`` CLI. The orchestrator uses this for status,
    branch, push, rebase. Implementations can swap for libgit2 later."""

    def status(self, repo_root: Path) -> list[FileStatus]:
        ...

    def current_branch(self, repo_root: Path) -> str | None: ...

    def default_branch(self, repo_root: Path) -> str: ...

    def remote_url(self, repo_root: Path) -> str: ...

    def run(self, args: list[str], cwd: Path, *, check: bool = True) -> str:
        """Run raw git command; returns stdout."""
        ...

    def fetch(self, repo_root: Path, remote: str = "origin") -> None: ...

    def push(self, repo_root: Path, *, force: bool = False, set_upstream: bool = False) -> None: ...

    def rebase(self, repo_root: Path, upstream: str) -> None: ...
```

### 4.7 其他小型 Protocol

```python
# orchestratord/protocols/diagnostics.py
class DiagnosticsProbe(Protocol):
    """Called by orchestrator heartbeat loop."""
    def heartbeat(self) -> HeartbeatStatus: ...

# orchestratord/protocols/intent_focus.py
class IntentFocus(Protocol):
    def compute_workspace_focuses(self, workspace: Path, issue: IssueLike) -> list[FocusArea]: ...

# orchestratord/protocols/coordinator.py
class CoordinatorContextProvider(Protocol):
    def is_active(self) -> bool: ...
    def enter(self) -> ContextManager: ...
```

### 4.8 Backend 容器

```python
# orchestratord/protocols/backend.py

class OrchestratordBackend(Protocol):
    """Bundles all Protocol implementations into one discoverable unit.

    Register via Python entry_points (``[orchestratord.backends]``)::

        # pyproject.toml
        [project.entry-points."orchestratord.backends"]
        clawcodex = "clawcodex_ext.orchestratord_adapter:ClawcodexBackend"

    The default loader picks the first registered backend (or a user-specified
    one via ``ORCHESTRATORD_BACKEND`` env var).
    """

    name: str

    @property
    def agent_runtime(self) -> AgentRuntime: ...

    @property
    def workspace_tooling(self) -> WorkspaceTooling: ...

    @property
    def session_storage(self) -> SessionStorage: ...

    @property
    def im_channel_factory(self) -> Callable[[str], ImChannel]: ...

    @property
    def git_backend(self) -> GitBackend: ...

    @property
    def llm_provider(self) -> Callable[[str], LLMProvider]: ...

    @property
    def diagnostics_probe(self) -> DiagnosticsProbe: ...

    @property
    def intent_focus(self) -> IntentFocus: ...

    @property
    def coordinator_context(self) -> CoordinatorContextProvider: ...

    def health_check(self) -> dict[str, Any]:
        """Verify backend reachability; called by orchestrator on startup."""
        ...
```

---

## 5. 独立包结构

### 5.1 仓库结构

```
orchestratord/                          # 独立 Git 仓库，独立 PyPI 包
├── pyproject.toml
├── README.md
├── LICENSE                              # Apache-2.0，与上游 MIT 兼容
├── src/
│   └── orchestratord/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── server.py                # 原 cli/server.py 拆分移植
│       │   ├── issue.py                 # 原 cli/issue.py 拆分移植
│       │   └── rules.py
│       ├── protocols/                   # §4 设计的所有 Protocol
│       │   ├── __init__.py
│       │   ├── agent_runtime.py
│       │   ├── workspace_tooling.py
│       │   ├── session_storage.py
│       │   ├── im_channel.py
│       │   ├── provider.py
│       │   ├── git_backend.py
│       │   ├── diagnostics.py
│       │   ├── intent_focus.py
│       │   ├── coordinator.py
│       │   ├── backend.py               # OrchestratordBackend 容器
│       │   └── messages.py              # TextDelta / ToolCallEvent / ...
│       ├── core/                        # 编排核心（~70% 原 orchestrator 代码）
│       │   ├── orchestrator.py
│       │   ├── agent_runner.py
│       │   ├── git_sync.py
│       │   ├── workspace.py
│       │   ├── tracker.py
│       │   ├── prompt_builder.py
│       │   ├── progress_sink.py
│       │   ├── progress_reporter.py
│       │   ├── modes/
│       │   │   ├── base.py
│       │   │   ├── single.py
│       │   │   ├── coordinator.py
│       │   │   ├── debate.py
│       │   │   ├── pipeline.py
│       │   │   └── swarm.py
│       │   └── ...（迁移其余文件）
│       ├── adapters/
│       │   ├── inproc.py                # 默认 backend（subprocess + AST）
│       │   └── stub.py                  # mock backend（测试用）
│       ├── mcp/                         # 新增 MCP server
│       │   ├── __init__.py
│       │   ├── server.py
│       │   └── tools.py
│       └── utils/
│           ├── issue.py                 # 原 issue.py 复制（数据类）
│           ├── intent.py                # 原 Intent / Command 枚举
│           ├── workspace_config.py
│           └── messages.py              # 内联的纯消息类型
├── tests/
│   ├── unit/
│   │   ├── test_orchestrator.py
│   │   ├── test_agent_runner.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_with_inproc_backend.py
│   │   └── test_with_stub_backend.py
│   └── e2e/
│       └── test_cli.py
└── docs/
    ├── ARCHITECTURE.md
    ├── BACKEND_AUTHORING.md
    └── MIGRATION_FROM_CLAWCODEX.md
```

### 5.2 pyproject.toml 设计

```toml
[project]
name = "orchestratord"
version = "0.1.0"
description = "Autonomous engineering orchestrator: poll issue tracker, drive AI agent, open PR"
requires-python = ">=3.11"
license = {text = "Apache-2.0"}

# 默认无硬依赖（运行时使用哪个 backend 由用户选择）
dependencies = [
    "jinja2>=3.0",           # 提示词模板
    "httpx>=0.27",           # tracker 客户端
    "PyYAML>=6.0",           # workflow 配置
    "pydantic>=2.0",         # 配置 + 数据类
    "click>=8.1",            # CLI
]

[project.optional-dependencies]
# 每个 backend 一个 extras_require
clawcodex = [
    "clawcodex>=0.4.0",
]
cli-mcp = [
    "fastmcp>=0.4",
]

[project.scripts]
orchestratord = "orchestratord.cli:main"

[project.entry-points."orchestratord.backends"]
# 默认 backend 由 clawcodex_ext 包注册；这里只声明 in-process stub
stub = "orchestratord.adapters.stub:StubBackend"
inproc = "orchestratord.adapters.inproc:InprocBackend"

[project.entry-points."orchestratord.mcp_servers"]
main = "orchestratord.mcp:MCPEntry"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 5.3 默认 in-process backend

新独立包自带一个**不依赖 clawcodex** 的 in-process backend，作为最小可行默认：

```python
# orchestratord/adapters/inproc.py

"""In-process backend: a tiny stub AgentRuntime that echoes the prompt
back. Suitable for integration testing without installing clawcodex.

NOT for production — production should install [clawcodex] extra and
register clawcodex_ext.orchestratord_adapter.ClawcodexBackend.
"""

class InprocAgentRuntime:
    """Echoes the prompt as a single text delta, then SessionComplete."""

    async def stream(self, *, prompt, workspace, **_) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="text_delta", payload=TextDelta(text=prompt[:200]))
        await asyncio.sleep(0.1)
        yield AgentEvent(type="session_complete",
                         payload=SessionComplete(reason="echo_complete"))
```

### 5.4 clawcodex_ext.orchestratord_adapter 适配层

```python
# clawcodex_ext/orchestratord_adapter/__init__.py
# 该模块留在 clawcodex_ext 下，保留对 src./extensions. 的访问权

from clawcodex_ext.agent.conversation import Conversation
from clawcodex_ext.agent.session import Session
from clawcodex_ext.providers.runtime import build_provider_from_config
# ... 其余 11 个适配

class ClawcodexAgentRuntime:
    """Adapter wrapping clawcodex_ext as AgentRuntime."""

    async def stream(self, *, prompt, workspace, provider_name=None,
                     model=None, tools=None, session_id=None,
                     on_session=None):
        # 构造 QueryConfig，复用 extensions/api/query.py
        from extensions.api.query import PhaseComplete, QueryConfig, QueryRunner
        # ... 转换 AgentEvent 类型
        ...

# Backend 容器
class ClawcodexBackend:
    name = "clawcodex"
    @property
    def agent_runtime(self): return ClawcodexAgentRuntime()
    # ... 其余 8 个属性

# entry_points 声明（在 clawcodex_ext 的 pyproject.toml 中）
# [project.entry-points."orchestratord.backends"]
# clawcodex = "clawcodex_ext.orchestratord_adapter:ClawcodexBackend"
```

---

## 6. 迁移路径（6 个 Phase）

> **实施说明（2026-07-23）**：Phase 0+1+2+3 已按「§10.2 可独立启动子集 + 核心迁移」落地，
> 但形态与原设计不同——采用**仓内子模块** `extensions/orchestrator_runtime/`
> 而非独立 `orchestratord/` Git 仓库/PyPI 包（用户确认保留单仓开发流）。
> 因此下文各 Phase 中的 `orchestratord/xxx` 路径在实际落地中对应
> `extensions/orchestrator_runtime/xxx`。commit `2dcacba8`（P0+P1+P2）与
> `87fd0fe4`（P3 压缩版：agent_runner / im_gateway_client Protocol 注入）。

### Phase 0 — 准备（0.5 天）✅ 已落地（改为仓内子模块形态）
- [x] ~~建立 `orchestratord/` 独立 Git 仓库~~ → 改为建立仓内子模块 `extensions/orchestrator_runtime/`（`protocols/` + `utils/` + `adapters/` 三层骨架）
- [ ] CI 配置（GitHub Actions：lint + unit + matrix Python 3.11/3.12）—— 仓内子模块沿用现有 `.github/workflows/ci.yml`，无需独立 CI
- [x] 在原 `extensions/orchestrator/` 保留入口兼容 —— 通过 `adapters/clawcodex_compat.py` 透明转发层实现（非 DEPRECATED 注释）

### Phase 1 — Protocol 骨架（约 3 天，~1,200 行）✅ 已落地（实测 ~600 行 / 12 文件 / 30 symbols）
**目标**：`orchestratord/protocols/` 下声明 §4 所有 6+ 个 Protocol 类，不实现，纯类型声明。

**关键产出**：
- `orchestratord/protocols/agent_runtime.py` — AgentRuntime / AgentEvent
- `orchestratord/protocols/workspace_tooling.py`
- `orchestratord/protocols/session_storage.py`
- `orchestratord/protocols/im_channel.py`
- `orchestratord/protocols/provider.py`
- `orchestratord/protocols/git_backend.py`
- `orchestratord/protocols/{diagnostics,intent_focus,coordinator}.py`
- `orchestratord/protocols/backend.py` — OrchestratordBackend 容器

**验证**：`mypy --strict orchestratord/protocols/` 通过；无 `import` 上游。
> ✅ 实测：`mypy --strict` on `protocols/` 12 files no issues；反向耦合 grep 确认 `protocols/` 无 `clawcodex_ext` 引用。

### Phase 2 — 弱耦合领域内联（约 5 天，~1,200 行）✅ 已落地（实测 ~830 行 copy-down / 4 utils 文件）
**目标**：把 C3/C6/C7/C8/C11/C12 这 6 类弱耦合从 `clawcodex_ext.*` 复制到 `orchestratord/utils/`，不依赖上游。

**关键产出**：
- `orchestratord/utils/messages.py` — 复制 TextBlock / ToolUseBlock / ToolResultBlock
- `orchestratord/utils/intent.py` — Intent / Command 枚举（已在 tracker.py）
- `orchestratord/utils/git_backend_impl.py` — DefaultGitBackend（git subprocess wrapper）
- `orchestratord/utils/api_errors.py` — RateLimitError + is_rate_limit_error
- `orchestratord/utils/intent_focus_impl.py` — default compute_workspace_focuses
- `orchestratord/utils/diagnostics_impl.py` — FreezeDetector（直接搬核心循环）

**验证**：单元测试覆盖每个文件；不引入对 `clawcodex_ext.*` 的 `import`（仅 stdlib + 第三方）。
> ✅ 实测落地 4 文件：`utils/git_backend_impl.py`（复制 `clawcodex_ext/utils/git.py`）、`utils/api_errors.py`、`utils/diagnostics_impl.py`、`utils/intent_focus_impl.py`；
> `adapters/clawcodex_compat.py` 透明转发层承接 5 个 orchestrator 文件的 9 处顶级 import 切换（函数体零改动）；
> drift check `diff -q git_backend_impl.py clawcodex_ext/utils/git.py` 仅 docstring 差异；
> orchestrator 测试 1610 pass、Stage 1 30/30、Stage 5 114/114。
> **未做**：`utils/messages.py`（C3 TextBlock 复制）、`utils/intent.py`（Intent 枚举）——实测 orchestrator 顶级 import 未直接依赖，留待 Phase 3 函数级 lazy import 迁移时处理。

### Phase 3 — 核心迁移（约 10 天，~3,000 行）✅ 已落地（实测 6 改文件 / 2 新测试，agent_runner + im_gateway_client 完成 Protocol 解耦）
**目标**：把 `extensions/orchestrator/` 的核心代码迁到 `orchestratord/core/`，替换具体上游引用为 Protocol。

**关键步骤**：
1. 复制 `tracker.py`、`issue.py`、`workspace.py`、`orchestrator.py`（先复制，逐步替换）
2. 把所有 `from clawcodex_ext.tool_system.context import ToolContext` 改成 `from orchestratord.protocols.workspace_tooling import ToolContextLike`
3. 把 `from extensions.api.query import ...` 改成走 `AgentRuntime.stream()`
4. 改 `git_sync.py`、`agent_runner.py` 调用 `GitBackend` 而非 `get_file_status()`
5. `im_gateway_client.py` 重写为 `ImChannel` 实现，由 caller 注入
6. `prompt_builder.py` 改用本地 `from orchestratord.utils.intent import Intent`
7. `modes/*.py` 改用 Protocol 注入

**验证**：双轨运行（生产仍走 `extensions/orchestrator/`），但每次 `orchestratord` 启动时跑相同的单元测试集合。

> ✅ **2026-07-23 已落地压缩版**（commit `87fd0fe4`）：不复制全部文件，而是直接在 `extensions/orchestrator/agent_runner.py` 和 `im_gateway_client.py` 中注入 Protocol 抽象；
> - `AgentRunner` 新增 3 个 kw-only 注入点（`agent_runtime` / `session_storage` / `coordinator_provider`），默认通过 `_resolve_protocols()` 懒加载 `ClawcodexAgentRuntime` / `ClawcodexSessionStorage` / `ClawcodexCoordinatorProvider`。
> - 替换 `agent_runner.py` 中 13 处 function-level lazy import：`clawcodex_ext.types.{messages,content_blocks}` → `extensions.orchestrator_runtime.utils.messages_impl`；`clawcodex_ext.bootstrap.state.*` → `BootstrapState` Protocol；`clawcodex_ext.coordinator.mode.*` → `CoordinatorContextProvider` Protocol；`clawcodex_ext.services.session_storage.SessionStorage` → `SessionStorage` Protocol（`_upstream()` 包装）。
> - `im_gateway_client.py`：移除冗余的 `InboundMessage/MessageSemantics` lazy import（已可通过 `clawcodex_compat` 顶层获得）；保留 `MessageClassifier` 与 `run_orchestrator_subcommand` 作为防御性 fallback 并加注 Phase 4+ 说明。
> - 修复 `CoordinatorContextProvider.enter()` 签名，支持 `enabled: bool` 透传，以保留 `agent_runner.run()` 动态 coordinator-mode 语义。
> - 新增 2 个测试：`tests/orchestrator/test_agent_runner_protocol_injection.py`、`tests/orchestrator/test_im_channel_protocol_injection.py`。
> - 验证：ruff passed；受影响测试 31 passed；orchestrator 单元测试 1611 passed / 2 skipped（仅 pre-existing `test_repro_gate.py::test_green_repro_command_passes_and_reports` 失败）；稳定性门禁 491 passed。

### Phase 4 — 适配层实现（约 5 天，~1,500 行）
**目标**：在 `clawcodex_ext/orchestratord_adapter/` 下实现 ClawcodexBackend，把上游实现包装成 Protocol 满足者。

**关键步骤**：
1. `clawcodex_ext/orchestratord_adapter/agent_runtime.py` — 包装 `extensions.api.query.QueryRunner`
2. `clawcodex_ext/orchestratord_adapter/workspace_tooling.py` — 包装 ToolContext
3. `clawcodex_ext/orchestratord_adapter/session_storage.py` — 包装 SessionStorage
4. `clawcodex_ext/orchestratord_adapter/im_channel.py` — 包装 IM Gateway
5. `clawcodex_ext/orchestratord_adapter/git_backend.py` — 包装 `_run_git` 等
6. `clawcodex_ext/orchestratord_adapter/__init__.py` — ClawcodexBackend 容器 + entry_points 注册

**验证**：`test_with_clawcodex_backend.py` 跑通原 `tests/orchestrator/` 全部用例。

### Phase 5 — CLI + MCP server（约 4 天，~1,200 行）
**目标**：
1. `orchestratord` CLI 入口（`server start/stop/status`、`issue list/tail`、`workspace ...`）
2. `orchestratord-mcp` 子命令暴露为 MCP server（用 fastmcp）

**MCP 工具**：
- `list_issues()` — list pending issues
- `run_issue(issue_id)` — trigger single-issue dispatch
- `get_status()` — orchestrator daemon status
- `get_report(run_id)` — pull run report

**验证**：`orchestratord mcp serve` 启动后，用 mcp-cli 调用 4 个工具测试。

### Phase 6 — 切换与废弃（约 3 天）
1. 在 `extensions/orchestrator/cli/server.py` 顶层 `from orchestratord.cli.server import main as _new_main` + 委托
2. 3 个月观察期，文档说明「推荐迁移 orchestratord」
3. 删除 `extensions/orchestrator/`（移到一个 `legacy/` 目录，README 引用）

---

## 7. MCP Server 设计

详见原文 `§4.2.4` 列出的 4 个工具。本节补充实现要点：

```python
# orchestratord/mcp/tools.py

from fastmcp import FastMCP

mcp = FastMCP("orchestrator")

@mcp.tool()
async def list_issues(workspace: str, *, state: str | None = None) -> list[dict]:
    """List issues pending orchestration."""
    backend = await load_backend()
    tracker = backend.tracker(workspace)
    return [asdict(i) for i in await tracker.list_issues(state=state)]


@mcp.tool()
async def run_issue(workspace: str, issue_id: str) -> dict:
    """Dispatch one issue through orchestrator and wait for terminal state."""
    backend = await load_backend()
    orch = backend.orchestrator(workspace)
    return await orch.dispatch_one(issue_id, wait=True)


@mcp.tool()
async def get_status(workspace: str) -> dict:
    """Daemon status (running / stopped / heartbeat)."""
    backend = await load_backend()
    daemon = backend.daemon(workspace)
    return await daemon.status()


@mcp.tool()
async def get_report(workspace: str, run_id: str) -> dict:
    """Pull run report (.reports/run_*/report.md + ndjson state journal)."""
    path = Path(workspace) / ".reports" / run_id
    if not path.exists():
        return {"error": "report not found"}
    return parse_report(path)
```

注册通过 `pyproject.toml` 的 `[project.entry-points."orchestratord.mcp_servers"]`：

```toml
[project.entry-points."orchestratord.mcp_servers"]
orchestrator = "orchestratord.mcp:MCPEntry"
```

启动方式：

```bash
orchestratord mcp serve                       # 默认 backend
ORCHESTRATORD_BACKEND=stub orchestratord mcp serve  # 测试 backend
```

---

## 8. 向后兼容与回退策略

### 8.1 兼容矩阵

| 部署形态 | 现状（解耦前） | 解耦后 |
|----------|---------------|--------|
| 单体部署（git codex 与 orchestrator 在同一仓库） | `extensions/orchestrator/` | `extensions/orchestrator/` → 委托给 `orchestratord` 共享 ClawcodexBackend |
| 仅安装 orchestratord + clawcodex | 不支持 | `pip install orchestratord[clawcodex]` 直接工作 |
| 自定义 backend | 不支持 | `pip install orchestratord` + 实现自己的 `OrchestratordBackend` |
| 仅安装 orchestratord + stub backend | 不支持 | `pip install orchestratord` 即可（最小 demo） |

### 8.2 过渡期策略

`extensions/orchestrator/cli/server.py` 顶层添加一行委托：

```python
# extensions/orchestrator/cli/server.py
try:
    from orchestratord.cli.server import main as _orchestratord_main
    HAS_ORCHESTRATORD = True
except ImportError:
    HAS_ORCHESTRATORD = False

def main(argv=None):
    if HAS_ORCHESTRATORD and "--use-orchestratord" not in (argv or []):
        # 默认走新独立包
        return _orchestratord_main(argv)
    # 否则走原实现
    return _server_legacy_main(argv)
```

通过 `--use-orchestratord` 标志切换测试。

### 8.3 回退开关

环境变量 `ORCHESTRATOR_USE_LEGACY=1` 完全禁用新独立包入口；用户报告问题时建议先打开此开关验证是否与上游实现相关。

---

## 9. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| **R1: Protocol 定义遗漏隐式契约** | Phase 4 后 runtime 类型不匹配 | 中 | Phase 1 + Phase 3 之间跑 mypy strict + 类型测试；从 clawcodex_ext 类型推导 |
| **R2: agent_runner 隐含依赖 LLM 流事件顺序** | 行为不一致（dead lock、丢消息） | 中 | 录制 golden 文件回放；agent_runner 双轨并行 2 周 |
| **R3: IM channel 多源 consumer 行为分裂** | 重启后丢消息 | 低 | 复用 `messages.semantics` 的语义层，仅替换 transport 实现 |
| **R4: SessionStorage 文件格式升级** | 旧 session 不可读 | 中 | 保留 `.codex_session/` 目录结构 + 升级适配函数 |
| **R5: clawcodex_ext 内部重构破坏 Protocol** | 每次上游同步需更新 adapter | 高（已知事实） | Adapter 层加 minimal smoke test 跑 5 个核心路径；adapter 不依赖私有属性 |
| **R6: 性能下降（Protocol + indirection）** | agent 启动慢 > 200ms | 低 | 关键路径内联 protocol 调用；用 `__slots__` / `dataclass(slots=True)` |
| **R7: 拆分后丢失 F-REC 录制集成** | 用户 dashboard 看不到录制 | 中 | asciicast_sink.py 改造为 `RecordableSource`（`extensions/capabilities/recorder.py` 已有 Protocol），直接复用 |
| **R8: workflow.md 兼容破坏** | 老 workflow 跑不起来 | 中 | WorkflowConfig dataclass 字段名/默认值逐字段保留；做 round-trip 序列化测试 |

---

## 10. 工作量复核

| 来源 | 估算 | 与本文对比 |
|------|------|-----------|
| COMMERCIALIZATION §4.2.4 | 5,000-8,000 行 | ✅ 本文精算 **~7,000 行**，落在估算区间偏中位（额外 ~600 行 Protocol + ~700 行 migration docs） |
| Phase 工作量（人日） | 30 天（1 人） | ✅ 1 人 5 周完成；2 人 2-3 周（Phase 3、4 可并行） |
| 测试隔离用例 | +40% | ✅ 双轨测试（mock backend + clawcodex backend）覆盖同一份单元测试 |

### 10.1 Phase 时间预算

| Phase | 内容 | 人日 |
|-------|------|------|
| 0 准备 | 仓库 + CI | 0.5 |
| 1 Protocol 骨架 | 6 类 Protocol + Backend 容器 | 3 |
| 2 弱耦合内联 | C3+C6+C7+C8+C11+C12 | 5 |
| 3 核心迁移 | Orchestrator / AgentRunner / GitSync / Modes | 10 |
| 4 适配层实现 | ClawcodexBackend（6 个 adapter） | 5 |
| 5 CLI + MCP | serve/issue/rules CLI + MCP server | 4 |
| 6 切换 + 废弃 | 委托 + 文档 + 删除 | 3 |
| **合计** | | **~30.5 人日（6 周 1 人）** |

### 10.2 何时启动

**前置条件**（必满足 3/3 才能启动 Phase 1）：
- [ ] `extensions/capabilities/` 已稳定（目前 14 个 Protocol，仍在演进）
- [ ] CMOS 商业化主线确定走「独立包」方向（见 COMMERCIALIZATION_PLAN.md 策略三）
- [ ] `tests/orchestrator/` 双轨测试机制就绪（mock backend ↔ real backend 同一份测试）

**可独立启动的子集**（即使上游暂未走「独立包」也值得做的）：
- Phase 1 + Phase 2 = ~1,500 行纯 orchestrator 内部重组，把弱耦合 6 类抽出来（不依赖任何仓外决策）
- 这部分也是 Decoupling Mandate 的体现：减少 `extensions/orchestrator/` 对 `clawcodex_ext.` 的引用
- ✅ **已于 2026-07-23 落地**（commit `2dcacba8` / `87fd0fe4`）：以仓内子模块 `extensions/orchestrator_runtime/` 形态实现，Phase 0+1+2+3 合并为两次提交；P0+P1+P2 为 20 新文件 / 5 改文件 / 9 处顶级 import 切换；P3 为 `agent_runner.py` / `im_gateway_client.py` 的 13 处 lazy import Protocol 化 + 2 个新测试。orchestrator 与 orchestrator_runtime 共存，原入口经 `clawcodex_compat` 透明委托。前置条件 3/3 未全满足（capabilities 仍演进、商业化主线未定），但子集不依赖仓外决策故先行落地。

---

## 附录 A：耦合点迁移矩阵

| 原耦合点 | 现指向 | 迁移后指向 |
|----------|--------|-----------|
| `from clawcodex_ext.agent.conversation import Conversation` | `extensions/api/query.py` 入口 | `orchestratord.adapters.clawcodex.agent_runtime.ClawcodexAgentRuntime` |
| `from clawcodex_ext.tool_system.context import ToolContext` | `ToolContext` 直接引用 | `orchestratord.protocols.workspace_tooling.ToolContextLike` |
| `from clawcodex_ext.types.content_blocks import TextBlock` | 直接 dataclass 用 | `orchestratord.utils.messages.TextBlock`（复制） |
| `from clawcodex_ext.services.session_storage import SessionStorage` | 直接类引用 | `orchestratord.protocols.session_storage.SessionStorage` |
| `from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient` | IM transport | `orchestratord.protocols.im_channel.ImChannel` |
| `from clawcodex_ext.providers.runtime import build_provider_from_config` | Provider 工厂 | `orchestratord.adapters.clawcodex.llm_provider.build_provider` |
| `from clawcodex_ext.services.api.errors import RateLimitError` | 异常类 | `orchestratord.utils.api_errors.RateLimitError`（复制） |
| `from clawcodex_ext.utils.git import get_file_status` | git 工具函数 | `orchestratord.protocols.git_backend.GitBackend.status` |
| `from clawcodex_ext.bootstrap.state import ...` | 进程级状态 | `orchestratord.adapters.clawcodex.bootstrap_adapter` |
| `from clawcodex_ext.coordinator.mode import coordinator_mode_context` | context manager | `orchestratord.protocols.coordinator.CoordinatorContextProvider.enter` |
| `from clawcodex_ext.intent_forecast.focus import compute_workspace_focuses` | 纯函数 | `orchestratord.protocols.intent_focus.IntentFocus.compute_workspace_focuses`（默认实现复制） |
| `from clawcodex_ext.diagnostics import FreezeDetector` | 类 | `orchestratord.protocols.diagnostics.DiagnosticsProbe`（默认实现复制） |

---

## 附录 B：参考文档

- `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` — §4.2.4 原始判定
- `docs/UPSTREAM_SYNC_DESIGN-decoupling.md` — Decoupling Mandate 详述
- `extensions/capabilities/` — 14 个已有 Protocol 文件（其中 agent_protocol.py / tool_protocol.py / recorder.py 可直接复用）
- `extensions/orchestrator/` — 当前 101 个文件、43,643 行代码
- `extensions/orchestrator/cli/server.py:1018` — `from extensions.orchestrator.orchestrator import Orchestrator as _Orch`（CLI 入口点）
- `tests/orchestrator/` — 双轨测试套件目标
- `extensions/orchestrator/asciicast_sink.py` — 已实现 `RecordableSource` Protocol，迁移时直接复用

---

**最后更新**：2026-07-23
**作者**：ClawCodex 项目组
**状态**：Phase 0+1+2+3 ✅ 已落地（commit `2dcacba8` / `87fd0fe4`）；Phase 4~6 📐 设计阶段

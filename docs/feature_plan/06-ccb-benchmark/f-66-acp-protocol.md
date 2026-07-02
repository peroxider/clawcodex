# F-66: ACP 协议支持

> 状态: 📋 规划中(P66-A 框架设计,新增 P66-E/P66-F Trae 支持)
> 章节: docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md
> 最后更新: 2026-07-02

## §1 设计规划

### 1.1 目标

对标 CCB ACP（Agent Client Protocol），支持 Zed/Cursor 等 IDE 集成协议，实现会话恢复、Skills 桥接等功能。

### 1.2 背景

ACP（Agent Client Protocol）是 Anthropic 与 Zed/Cursor 等 IDE 合作推出的 Agent-IDE 通信协议。CCB 通过 `@agentclientprotocol/sdk` 原生支持 ACP。clawcodex 目前无对应实现。

字节跳动推出的 **Trae** 产品矩阵是国内 AI IDE 的代表(国内版 Trae CN,企业版支持 IDE/插件/CLI 三形态;另有开源的 Trae Agent CLI),但其协议支持情况与 Zed/Cursor 存在差异 — Trae IDE 当前**仅原生支持 MCP**(通过内置 `byted-solo.builtin-mcp` 扩展 + 火山引擎 MCP 市场),**ACP 支持尚未实现**(见 [trae-agent Issue #344](https://github.com/bytedance/trae-agent/issues/344) 仍为 open 状态)。因此对 Trae 的集成需采用与 Zed/Cursor 不同的双轨路线(MCP 反向 + CLI 包装),详见 §1.9 / §1.10。

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P66-A | ACP SDK 基础协议实现 | 实现 ACP 协议核心：session/skill/tool 通信 | 📋 | 3-5天 |
| P66-B | Zed IDE 集成接入 | 通过 ACP 协议桥接到 Zed AI 插件 | 📋 | 2-3天 |
| P66-C | Cursor IDE 集成接入 | 通过 ACP 协议桥接到 Cursor | 📋 | 2-3天 |
| P66-D | 会话恢复与 Skills 桥接 | ACP session resume + skill 桥接 | 📋 | 2-3天 |
| P66-E | Trae IDE 集成(MCP 反向) | Trae IDE 通过 MCP 主动调用 clawcodex 编排器/SOP/Skills | 🆕 P0 | 1-2天 |
| P66-F | Trae Agent CLI 包装(ACP 适配) | 把 `trae-cli run` 包装为伪 ACP server,统一协议层 | 🆕 P1 | 2-3天 |

### 1.4 核心数据模型

```python
# 消息类型枚举
class ACPMessageType(Enum):
    SESSION_CREATE = "session/create"
    SESSION_RESUME = "session/resume"
    SESSION_END = "session/end"
    MESSAGE_SEND = "message/send"
    MESSAGE_STREAM = "message/stream"
    TOOL_CALL = "tool/call"
    TOOL_RESULT = "tool/result"
    SKILL_INVOKE = "skill/invoke"
    SKILL_RESULT = "skill/result"
    ERROR = "error"

@dataclass
class ACPMessage:
    """ACP 协议消息体（JSON-RPC over WebSocket/stdio）。"""
    type: ACPMessageType
    id: str = ""
    session_id: str = ""
    role: ACPMessageRole = ACPMessageRole.USER
    content: str | dict | None = None
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class ACPSession:
    id: str
    created_at: str
    messages: list[ACPMessage] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    workspace_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 1.5 核心接口

```python
class ACPTransport(ABC):
    """ACP 传输层抽象（stdio / WebSocket / TCP）。"""
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def send(self, msg: ACPMessage) -> None: ...
    @abstractmethod
    async def receive(self) -> ACPMessage | None: ...
    @abstractmethod
    async def close(self) -> None: ...

class ACPServer(ABC):
    """ACP 协议服务端（接收 IDE 发起的会话请求）。"""
    @abstractmethod
    async def handle_session(self, transport: ACPTransport) -> None: ...
    @abstractmethod
    async def create_session(self, workspace_path: str) -> ACPSession: ...
    @abstractmethod
    async def resume_session(self, session_id: str) -> ACPSession | None: ...
    @abstractmethod
    async def process_message(self, msg: ACPMessage) -> AsyncIterator[ACPMessage]: ...
    @abstractmethod
    async def invoke_skill(self, skill_name: str, params: dict) -> dict: ...
```

### 1.6 传输实现

**Stdio 传输**（Zed/Cursor 插件使用）:
```python
class StdioACPTransport(ACPTransport):
    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        self._writer = sys.stdout
        self._reader = reader
```

**WebSocket 传输**（远程 IDE 插件使用）:
```python
class WsACPTransport(ACPTransport):
    async def connect(self, url: str) -> None:
        session = ClientSession()
        self._ws = await session.ws_connect(url)
    async def send(self, msg: ACPMessage) -> None:
        await self._ws.send_json(dataclasses.asdict(msg, default=str))
```

### 1.7 Tool 集成

```python
def build_acp_tools(server: ACPServer) -> list[Tool]:
    return [
        Tool(name="acp_list_sessions", description="列出所有活跃 ACP 会话", ...),
        Tool(name="acp_invoke_skill", description="通过 ACP 协议调用 Skill", ...),
    ]
```

### 1.8 依赖

- `aiohttp`（WebSocket 服务端/客户端）
- 可选：Zed / Cursor IDE 插件 SDK
- 可选(P66-F):`trae-agent`（字节开源,MIT 协议,`uv tool install trae-agent` 或克隆 `https://github.com/bytedance/trae-agent` 到 extensions/trae/vendor/）
- 可选(P66-E):`mcp`（Python MCP SDK,`pip install mcp`,Trae 内置 MCP 客户端可直连）

## §1.9 P66-E: Trae IDE 集成(MCP 反向模式)

### 1.9.1 目标

让 Trae IDE 用户**在 Trae 对话框内直接调用 clawcodex 的下游能力**(Orchestrator、SOP Compiler、Skills 桥接等),无需离开 IDE。

### 1.9.2 设计动机

字节 Trae IDE 短期内(2026 H2)实现 ACP 的可能性较低(见 [trae-agent #344](https://github.com/bytedance/trae-agent/issues/344))。但其**已原生支持 MCP**(`byted-solo.builtin-mcp` 扩展 + 火山引擎 MCP 市场直连),故采用"MCP 反向"路线 — 由 clawcodex 暴露 stdio MCP server,让 Trae 主动连接,等同把 clawcodex 当作一个 MCP 工具市场。

### 1.9.3 落点(Layer 2 解耦)

`extensions/trae/mcp_bridge.py` — 镜像 `extensions/orchestrator/` 的协议风格,不污染 `src/` 或 `clawcodex_ext/`。

```python
# extensions/trae/mcp_bridge.py
from mcp.server import Server
from mcp.types import Tool, TextContent
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.sop_converter.compiler import SOPCompiler

class TraeMcpBridge:
    """MCP server bridge — 让 Trae IDE 通过 MCP 协议调用 clawcodex 能力。

    Trae IDE 用户在 builtin-mcp 配置中添加本 server 路径即可使用,
    无需任何 Trae 插件改造。
    """

    def __init__(self, orchestrator: Orchestrator, sop_compiler: SOPCompiler):
        self._server = Server("clawcodex-trae-bridge")
        self._orchestrator = orchestrator
        self._sop = sop_compiler
        self._register_tools()

    def _register_tools(self) -> None:
        @self._server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="clawcodex_orchestrator_run_issue",
                    description=(
                        "从当前 Trae workspace 派生 git workspace,"
                        "运行 clawcodex agent 处理 issue,自动推 PR。"
                        "等价于 `clawcodex-dev orchestrator server start` 的单次触发。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "issue_url": {"type": "string", "description": "GitHub/Gitee/GitCode/Linear issue URL"},
                            "workflow_path": {"type": "string", "description": "可选 SOP workflow.md 路径"},
                        },
                        "required": ["issue_url"],
                    },
                ),
                Tool(
                    name="clawcodex_sop_compile",
                    description="将 workflow.md 编译为多 agent 协调系统并写入 .sop/ 目录",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "workflow_md_path": {"type": "string"},
                            "output_dir": {"type": "string", "default": ".sop/"},
                        },
                        "required": ["workflow_md_path"],
                    },
                ),
                Tool(
                    name="clawcodex_skill_invoke",
                    description="调用已注册的 Skill(透传到 F-66 P66-D 的 skill 桥接层)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string"},
                            "params": {"type": "object", "default": {}},
                        },
                        "required": ["skill_name"],
                    },
                ),
                Tool(
                    name="clawcodex_stability_gate",
                    description="在当前 workspace 跑一次稳定性门禁,返回 Stage 1-6 通过/失败摘要",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]

        @self._server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name == "clawcodex_orchestrator_run_issue":
                run_id = await self._orchestrator.enqueue_issue(
                    issue_url=arguments["issue_url"],
                    workflow_path=arguments.get("workflow_path"),
                )
                return [TextContent(type="text", text=f"queued run_id={run_id}")]
            elif name == "clawcodex_sop_compile":
                manifest = self._sop.compile(arguments["workflow_md_path"], arguments.get("output_dir", ".sop/"))
                return [TextContent(type="text", text=f"compiled {len(manifest.agents)} agents → {manifest.output_dir}")]
            elif name == "clawcodex_skill_invoke":
                result = await self._invoke_skill(arguments["skill_name"], arguments.get("params", {}))
                return [TextContent(type="text", text=result)]
            elif name == "clawcodex_stability_gate":
                summary = self._run_stability_gate()
                return [TextContent(type="text", text=summary)]
            raise ValueError(f"unknown tool: {name}")

    async def run_stdio(self) -> None:
        """通过 stdio 暴露 MCP server,供 Trae IDE builtin-mcp 调用。"""
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(read_stream, write_stream, self._server.create_initialization_options())
```

### 1.9.4 Trae IDE 侧接入文档(对最终用户)

```jsonc
// Trae IDE → 设置 → AI → MCP Servers → 添加
{
  "name": "clawcodex",
  "command": "python",
  "args": ["-m", "extensions.trae.mcp_bridge"],
  "env": {
    "CLAWCODEX_WORKSPACE": "${workspaceFolder}",
    "CLAWCODEX_REPORTS_DIR": "${workspaceFolder}/.reports/"
  }
}
```

接入后,在 Trae 对话框直接说:"用 clawcodex 跑 issue #42",AI 会自动调用 `clawcodex_orchestrator_run_issue` 工具。

### 1.9.5 验收标准

- [ ] `extensions/trae/mcp_bridge.py` 可独立启动 `python -m extensions.trae.mcp_bridge`,响应 MCP `tools/list` 返回 4 个工具
- [ ] 单元测试:用 `mcp.client.session` 模拟 Trae builtin-mcp 客户端,验证 `call_tool` 四个分支
- [ ] E2E:在本地 Trae CN(已装)配置 server 路径,在 Trae 对话框中触发 `clawcodex_stability_gate`,返回的稳定性摘要与 `pytest tests/stability_gate/ -q` 一致
- [ ] 协议合规:`mcp inspector` 校验 schema 合法

### 1.9.6 风险与约束

| 风险 | 缓解 |
|------|------|
| Trae builtin-mcp schema 校验严格,自定义 tool 名带 `clawcodex_` 前缀被拒 | 与 Trae 团队确认命名规则,准备 fallback 短名(若拒,改名 `cc_orch_run` 等) |
| Orchestrator 单实例 `ProgressReporter` 非线程安全,长任务阻塞 MCP 响应 | 把 `enqueue_issue` 改为 fire-and-forget,只返回 run_id,实际进度通过文件系统 polling(`.reports/{run_id}.ndjson`)让 Trae 拉取 |
| 长任务跑几小时,Trae 对话框 timeout | 默认设 30s 短 timeout 给 MCP 响应,长任务完全异步化 |

## §1.10 P66-F: Trae Agent CLI 包装(ACP 适配模式)

### 1.10.1 目标

将字节开源的 `trae-agent`(`trae-cli`)包装为**伪 ACP server**,让 clawcodex 内部按 P66-A 设计的统一 `ACPTransport / ACPServer` 接口即可调用 Trae Agent 能力(代码编辑、命令执行、Trajectory 记录),无需为 Trae 单独写一套协议。

### 1.10.2 设计动机

`trae-agent` 截至 2026-07 仍是纯 CLI 工具(无 stdio JSON-RPC 服务,无 ACP 实现,见 #344)。但其 `trae-cli run` 子命令的输入/输出/中间轨迹已经接近 ACP 协议的事件流 — 因此可以用一个薄适配层把 CLI 调用的进程 + trajectory JSONL 文件,投影为 ACP 消息流。

### 1.10.3 落点(Layer 2 解耦)

`extensions/trae/acp_cli_adapter.py`,通过 `extensions/capabilities/` 中的 `ACPTransportProtocol`(P66-A 定义)接入。

```python
# extensions/trae/acp_cli_adapter.py
import asyncio
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from extensions.capabilities.acp_protocol import (
    ACPMessage, ACPMessageType, ACPTransport, ACPServer,
)

@dataclass
class TraeCliConfig:
    """trae-cli 启动配置(可从 trae_config.yaml 反序列化得到)。"""
    trae_cli_path: str = "trae-cli"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"
    mcp_servers: list[dict] = field(default_factory=list)
    extra_flags: list[str] = field(default_factory=list)


class TraeCliACPAdapter(ACPTransport, ACPServer):
    """把 trae-cli 包装为伪 ACP server。

    内部映射:
      session/create  → trae-cli run "<task>" --working-dir <ws> --trajectory-file <jsonl>
      message/stream  → tail <jsonl> 逐行解析为 ACP 消息
      session/end     → subprocess.terminate() + 清理 trajectory 文件
      session/resume  → trae-cli interactive 模式(用 saved trajectory 续接)
    """

    def __init__(self, config: TraeCliConfig, workspace: str):
        self._cfg = config
        self._workspace = workspace
        self._procs: dict[str, subprocess.Popen] = {}
        self._trajectories: dict[str, Path] = {}

    # ===== ACPServer 接口 =====

    async def create_session(self, workspace_path: str) -> str:
        sid = str(uuid.uuid4())
        traj_dir = Path(workspace_path) / ".trae/trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        self._trajectories[sid] = traj_dir / f"{sid}.jsonl"
        return sid

    async def resume_session(self, session_id: str) -> bool:
        traj = self._trajectories.get(session_id)
        if not traj or not traj.exists():
            return False
        # 用 interactive 模式续接,trajectory 作为 context
        cmd = [self._cfg.trae_cli_path, "interactive",
               "--resume-trajectory", str(traj),
               "--working-dir", self._workspace]
        return await self._spawn(session_id, cmd, env=self._env())

    async def process_message(self, session_id: str, task: str) -> AsyncIterator[ACPMessage]:
        """对应 ACP message/stream:启动 trae-cli run,逐行 tail trajectory。"""
        if session_id not in self._procs:
            cmd = self._build_run_cmd(session_id, task)
            await self._spawn(session_id, cmd, env=self._env())
        async for evt in self._tail_trajectory(session_id):
            yield self._trajectory_to_acp(session_id, evt)

    async def end_session(self, session_id: str) -> None:
        proc = self._procs.pop(session_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ===== 内部实现 =====

    def _build_run_cmd(self, sid: str, task: str) -> list[str]:
        traj = self._trajectories[sid]
        return [
            self._cfg.trae_cli_path, "run", task,
            "--working-dir", self._workspace,
            "--trajectory-file", str(traj),
            "--provider", self._cfg.provider,
            "--model", self._cfg.model,
            *self._cfg.extra_flags,
        ]

    async def _spawn(self, sid: str, cmd: list[str], env: dict) -> bool:
        self._procs[sid] = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        return True

    async def _tail_trajectory(self, sid: str) -> AsyncIterator[dict]:
        """tail -F trajectory jsonl,逐行 yield dict。"""
        traj = self._trajectories[sid]
        proc = self._procs[sid]
        # 等待 trajectory 文件出现
        for _ in range(50):
            if traj.exists():
                break
            await asyncio.sleep(0.1)
        if not traj.exists():
            return
        with traj.open("r", encoding="utf-8") as f:
            while proc.poll() is None:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _trajectory_to_acp(self, sid: str, evt: dict) -> ACPMessage:
        """trajectory 事件 → ACP 消息映射。"""
        step = evt.get("step", "unknown")
        tool = evt.get("tool_name")
        content = evt.get("content", "")
        if tool:
            return ACPMessage(
                type=ACPMessageType.TOOL_CALL,
                id=evt.get("id", str(uuid.uuid4())),
                session_id=sid,
                tool_calls=[{"name": tool, "arguments": evt.get("tool_input", {})}],
                content=content,
            )
        return ACPMessage(
            type=ACPMessageType.MESSAGE_STREAM,
            id=evt.get("id", str(uuid.uuid4())),
            session_id=sid,
            content=content,
            metadata={"step": step, "model": evt.get("model")},
        )

    def _env(self) -> dict:
        import os
        env = os.environ.copy()
        env["TRAE_PROVIDER"] = self._cfg.provider
        env["TRAE_MODEL"] = self._cfg.model
        if self._cfg.mcp_servers:
            env["TRAE_MCP_SERVERS"] = json.dumps(self._cfg.mcp_servers)
        return env
```

### 1.10.4 ACP 消息 → trae-cli 调用映射表

| ACP 消息 | trae-cli 子命令 | 关键参数 | 异步语义 |
|---------|----------------|----------|----------|
| `session/create` | (无 CLI 调用,只生成 session_id + trajectory 路径) | — | 同步返回 sid |
| `session/resume` | `trae-cli interactive --resume-trajectory <jsonl>` | resume-trajectory | 后台进程 |
| `message/send` (首次) | `trae-cli run "<task>"` | working-dir, trajectory-file, provider, model | 后台进程,tail jsonl |
| `message/stream` | (无 CLI 调用,只 tail jsonl) | — | 异步迭代器 |
| `tool/call` (clawcodex 主动) | (trae-cli 内置,无需外部触发) | — | — |
| `session/end` | `subprocess.terminate()` | — | 同步清理 |

### 1.10.5 trae_config.yaml 互操作

Trae Agent 自身的 `trae_config.yaml` 可与 clawcodex 配置系统桥接:

```yaml
# trae_config.yaml(由 clawcodex config 转换而来)
provider:
  anthropic:
    api_key: ${env:ANTHROPIC_API_KEY}
    base_url: ${env:ANTHROPIC_BASE_URL:-https://api.anthropic.com}
model:
  default: claude-sonnet-4-6
mcp_servers:
  - name: clawcodex
    command: python
    args: ["-m", "extensions.trae.mcp_bridge"]   # ← P66-E 暴露的 MCP server
```

注意 **P66-E 与 P66-F 互为正反**:P66-F 启动的 trae-cli 进程可挂载 P66-E 暴露的 MCP server,形成双向闭环(clawcodex 既能通过 ACP 调 Trae Agent,Trae Agent 也能通过 MCP 反向调 clawcodex)。

### 1.10.6 验收标准

- [ ] `extensions/trae/acp_cli_adapter.py` 单元测试覆盖 create/resume/process/end 四个生命周期方法
- [ ] Mock subprocess.Popen,验证 `_build_run_cmd` 生成的命令行符合 trae-agent v0.x 接口
- [ ] E2E:用真 `trae-cli`(本地 `uv tool install trae-agent` 或克隆仓库)跑一个简单任务,验证 trajectory JSONL 事件被正确投影为 ACP MESSAGE_STREAM / TOOL_CALL 消息
- [ ] 进程清理:`end_session` 后 `ps aux | grep trae-cli` 无残留

### 1.10.7 风险与约束

| 风险 | 缓解 |
|------|------|
| trae-agent 接口/flag 变化(项目处于早期) | 锁版本,`pyproject.toml` 中 `trae-agent @ git+https://github.com/bytedance/trae-agent@v0.3.0`;接口变化时集中改 `_build_run_cmd` 一处 |
| Trajectory JSONL 格式未稳定,字段名变更 | 映射层 `_trajectory_to_acp` 加 `try/except KeyError` 降级为 `MESSAGE_STREAM` 通用消息,不抛错 |
| 字节后续在 trae-agent 实现原生 ACP server | 适配器实现 `ACPTransport` Protocol,可平滑替换 backend;P66-F 退化为薄薄一层 `TraeNativeACPAdapter` |
| Windows 下 subprocess 启动 trae-cli 需 WSL 或 .exe 入口 | 文档明确支持的安装方式;Mac/Linux 优先,Windows 标注 experimental |

## §1.11 优先级与里程碑

按依赖关系与价值,推荐实施顺序:

```
P0  P66-E (MCP 反向)     ← 1-2 天  不依赖 trae-agent,落地最快
    │  └─ 立即解锁 Trae IDE 用户使用 clawcodex 编排能力
    │
P1  P66-F (CLI 包装)     ← 2-3 天  依赖 trae-agent 安装,与 P66-E 互为正反
    │  └─ 统一协议层,后续 trae-agent 原生支持 ACP 时可零成本切换
    │
P2  P66-A (ACP 框架)     ← 3-5 天  P66-F 的实现会反向推动 P66-A 收敛
    │  └─ 框架稳定后,P66-B/C 接入 Zed/Cursor
    │
P3  P66-B / P66-C / P66-D ← 2-3 天 ×3  Zed/Cursor/Skills 桥接
```

**里程碑(M)**:

- **M1 (本周)**: P66-E 落地,Trae CN 本地 E2E 跑通
- **M2 (下周)**: P66-F 落地,trajectory 事件流验证
- **M3 (下下周)**: P66-A 框架收敛(借助 P66-F 的实现经验)
- **M4**: P66-B/C/D 依次接入

**回滚策略**:
- P66-E / P66-F 均落 `extensions/trae/`,完全在 Layer 2 — 删目录即可回滚,不影响 `src/` 与 `clawcodex_ext/`
- trae-agent 通过可选依赖引入,`pyproject.toml` `[tool.uv.sources]` 中标记 `optional = true`,不安装时 P66-F 不可用但其他子特性正常

**为什么先做 P66-E**:
1. Trae 短期无 ACP,等不起
2. MCP 是字节主推方向,沟通成本最低
3. P66-E 落地后,Trae 团队可以更直观评估 clawcodex,反哺 ACP 支持

## §2 进度跟踪

| 子特性 | 状态 | 备注 |
|--------|------|------|
| P66-A ACP SDK 基础协议实现 | 📋 规划中 | 框架设计,需待 P66-F 实现经验收敛 |
| P66-B Zed IDE 集成 | 📋 规划中 | 依赖 P66-A |
| P66-C Cursor IDE 集成 | 📋 规划中 | 依赖 P66-A |
| P66-D 会话恢复 + Skills 桥接 | 📋 规划中 | 依赖 P66-A |
| P66-E Trae IDE 集成(MCP 反向) | 🆕 P0,本周启动 | 详见 §1.9 |
| P66-F Trae Agent CLI 包装(ACP 适配) | 🆕 P1,本周启动 | 详见 §1.10 |

**当前阶段**:等待 P66-E 落地(预计 1-2 天),以此作为 P66-F 设计的真实反馈。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建(从四源融合) | 四文档合并 |
| 2026-06-24 | 补全详细设计(数据模型+接口+传输实现) | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-02 | 新增 P66-E / P66-F 两个子特性(支持字节 Trae 产品矩阵) | Trae IDE 仅支持 MCP 而非 ACP,需双轨路线;Trae Agent 暂未实现 ACP(见 trae-agent #344)。设计为 MCP 反向 + CLI 包装两条独立路径,均落地 `extensions/trae/` 完全解耦 |
| 2026-07-02 | 补充 §1.9 P66-E / §1.10 P66-F / §1.11 优先级与里程碑 | 明确 P0→P1→P2→P3 实施顺序、M1-M4 里程碑、回滚策略 |

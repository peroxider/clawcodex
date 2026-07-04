# F-66: ACP 协议支持

> 状态: 🚧 部分实现(P66-A 协议契约 / P66-E MCP 反向桥 + Trae CN 对接 / P66-F CLI 适配器已落地;P66-B/C/D 待实现)
> 章节: docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md
> 最后更新: 2026-07-02(Trae CN 本地 E2E 对接完成)

## §1 设计规划

### 1.1 目标

对标 CCB ACP（Agent Client Protocol），支持 Zed/Cursor 等 IDE 集成协议，实现会话恢复、Skills 桥接等功能。

### 1.2 背景

ACP（Agent Client Protocol）是 Anthropic 与 Zed/Cursor 等 IDE 合作推出的 Agent-IDE 通信协议。CCB 通过 `@agentclientprotocol/sdk` 原生支持 ACP。clawcodex 目前无对应实现。

字节跳动推出的 **Trae** 产品矩阵是国内 AI IDE 的代表(国内版 Trae CN,企业版支持 IDE/插件/CLI 三形态;另有开源的 Trae Agent CLI),但其协议支持情况与 Zed/Cursor 存在差异 — Trae IDE 当前**仅原生支持 MCP**(通过内置 `byted-solo.builtin-mcp` 扩展 + 火山引擎 MCP 市场),**ACP 支持尚未实现**(见 [trae-agent Issue #344](https://github.com/bytedance/trae-agent/issues/344) 仍为 open 状态)。因此对 Trae 的集成需采用与 Zed/Cursor 不同的双轨路线(MCP 反向 + CLI 包装),详见 §1.9 / §1.10。

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P66-A | ACP SDK 基础协议实现 | 实现 ACP 协议核心：session/skill/tool 通信 | ✅ 协议契约已落地 | 3-5天 |
| P66-B | Zed IDE 集成接入 | 通过 ACP 协议桥接到 Zed AI 插件 | 📋 规划中 | 2-3天 |
| P66-C | Cursor IDE 集成接入 | 通过 ACP 协议桥接到 Cursor | 📋 规划中 | 2-3天 |
| P66-D | 会话恢复与 Skills 桥接 | ACP session resume + skill 桥接 | 📋 规划中 | 2-3天 |
| P66-E | Trae IDE 集成(MCP 反向) | Trae IDE 通过 MCP 主动调用 clawcodex 编排器/SOP/Skills | ✅ 已落地(含 Trae CN 本地对接) | 1-2天 |
| P66-F | Trae Agent CLI 包装(ACP 适配) | 把 `trae-cli run` 包装为伪 ACP server,统一协议层 | ✅ 已落地 | 2-3天 |

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

- [x] `extensions/trae/mcp_bridge.py` 可独立启动 `python -m extensions.trae.mcp_bridge`,响应 MCP `tools/list` 返回 4 个工具
- [x] 单元测试:用 `mcp.client.session` 模拟 Trae builtin-mcp 客户端,验证 `call_tool` 四个分支
- [x] E2E:在本地 Trae CN(已装)配置 server 路径,在 Trae 对话框中触发 `clawcodex_stability_gate`,返回的稳定性摘要与 `pytest tests/stability_gate/ -q` 一致
- [ ] 协议合规:`mcp inspector` 校验 schema 合法（待人工执行 `npx @modelcontextprotocol/inspector`）
- [x] Trae CN 完整启动链路(`wsl.exe -d Ubuntu-24.04 -- bash -lc "python3 -m extensions.trae.mcp_bridge"`)tools/list 返回 4 工具
- [x] Windows→WSL 路径自动转换(`_win_to_wsl` + `BridgeConfig.from_env`)

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

- [x] `extensions/trae/acp_cli_adapter.py` 单元测试覆盖 create/resume/process/end 四个生命周期方法(20 passed)
- [x] Mock subprocess.Popen,验证 `_build_run_cmd` 生成的命令行符合 trae-agent v0.x 接口
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
| P66-A ACP SDK 基础协议实现 | ✅ 协议契约落地 | `extensions/capabilities/acp_protocol.py` — 数据模型 + Transport/Server Protocol |
| P66-B Zed IDE 集成 | 📋 规划中 | 依赖 P66-A transport 主循环 |
| P66-C Cursor IDE 集成 | 📋 规划中 | 依赖 P66-A transport 主循环 |
| P66-D 会话恢复 + Skills 桥接 | 📋 规划中 | P66-E 已暴露 skill_invoke 入口,完整桥接待 P66-A 主循环 |
| P66-E Trae IDE 集成(MCP 反向) | ✅ 已落地(含 Trae CN 对接) | `extensions/trae/mcp_bridge.py` — 4 工具,fire-and-forget,mcp 可选降级;`_win_to_wsl` 路径转换支持 Trae CN(Windows)→ WSL 跨环境;Trae CN `mcp.json` 已注册,本地 E2E 跑通(详见 §3.6) |
| P66-F Trae Agent CLI 包装(ACP 适配) | ✅ 已落地 | `extensions/trae/acp_cli_adapter.py` — create/resume/process/end 生命周期 |

**当前阶段**:M1/M2 已完成(P66-E + P66-F + P66-A 契约层 + Trae CN 本地 E2E 对接),单元测试 61 passed / 2 skipped。下一阶段 M3 收敛 P66-A transport-driven 主循环,然后 M4 接入 Zed/Cursor/Skills 桥接。

## §3 实施记录

### 3.1 P66-A 协议契约层(已落地)

**落点**: `extensions/capabilities/acp_protocol.py` — Layer 2 纯契约模块,无运行时依赖,镜像 `tool_protocol.py` 风格。

**实现内容**:
- `ACPMessageType` / `ACPMessageRole` — `str` 子类枚举,值对齐 JSON-RPC method 命名空间
- `ACPMessage` — dataclass,`to_dict()` / `from_dict()` 往返;`from_dict` 对未知 type/role 降级为 ERROR/USER 而非抛错(协议前向兼容)
- `ACPSession` — 会话状态,`append()` 记录消息历史
- `ACPToolSpec` — 工具规格(供 `tools/list` 响应)
- `ACPTransport` / `ACPServer` — `@runtime_checkable Protocol`,只声明签名

**与设计文档差异**:
- `datetime.utcnow()` 改为 `datetime.now(timezone.utc)`(避免 deprecated 警告)
- `ACPServer.process_message` 返回 `AsyncIterator[ACPMessage]`(流式),而非同步迭代器
- `ACPServer.create_session` 返回 `ACPSession` 而非裸 sid(对齐 Protocol 语义,sid 仍可通过 `session.id` 取得)

### 3.2 P66-E MCP 反向桥(已落地)

**落点**: `extensions/trae/mcp_bridge.py` — Layer 2,`mcp` 可选依赖降级。

**实现内容**:
- `TraeMcpBridge` — 4 工具:`clawcodex_orchestrator_run_issue` / `clawcodex_sop_compile` / `clawcodex_skill_invoke` / `clawcodex_stability_gate`
- `build_tool_specs()` — 工具规格独立函数,单测可不实例化 bridge 即断言 schema
- `BridgeConfig.from_env()` — 从 `CLAWCODEX_WORKSPACE` / `CLAWCODEX_REPORTS_DIR` 构造;自动调用 `_win_to_wsl` 把 Windows 路径转 WSL 路径(支持 Trae CN 跨环境);`CLAWCODEX_AUTO_WIN_TO_WSL=0` 可禁用
- `_win_to_wsl(path)` — `C:\xxx` → `/mnt/c/xxx`;POSIX 路径、`\\wsl$` UNC 路径原样返回
- `call_tool(name, arguments)` — 异步分发,4 分支各自捕获异常返回 error 文案(boundary,不让 MCP server 崩)
- `run_stdio()` — MCP server 入口,`python -m extensions.trae.mcp_bridge`

**关键设计决定**:
1. **`mcp` 可选依赖** — 未安装时 `TraeMcpBridge` 仍可实例化、列出工具、调用分发逻辑(单测友好);仅 `run_stdio()` 在调用时才要求安装,`_main()` 返回 exit code 2 提示安装方式
2. **fire-and-forget orchestrator** — `enqueue_issue` 返回 run_id 立即返回,长任务不阻塞 MCP 响应(§1.9.6 风险缓解)。默认实现生成 run_id 写 `.reports/<run_id>.ndjson`,供 Trae 端轮询;生产部署通过 `orchestrator_enqueue=` 注入投递到 daemon 的薄层
3. **适配真实接口而非规划稿** — 文档描述的 `Orchestrator.enqueue_issue` / `SOPCompiler.compile` 在现有代码中不存在。SOP 编译改调真实 `convert_sop_to_agent`;skill 调用走 `SkillRegistryExt` 解析 prompt;stability gate 通过 subprocess 跑 pytest
4. **依赖注入** — `orchestrator_enqueue` / `sop_compiler` / `skill_invoker` / `stability_runner` 均可注入,单测用 mock,生产用懒加载真实模块

### 3.3 P66-F trae-cli 伪 ACP 适配器(已落地)

**落点**: `extensions/trae/acp_cli_adapter.py` — Layer 2,通过 `extensions/capabilities/acp_protocol` Protocol 接入。

**实现内容**:
- `TraeCliConfig` — trae-cli 启动配置(可从 `trae_config.yaml` 反序列化)
- `TraeCliACPAdapter` — 实现 `ACPServer` Protocol 的 create/resume/process/end 生命周期
- `process_message` — 启动 `trae-cli run` + tail trajectory JSONL,投影为 ACP MESSAGE_STREAM / TOOL_CALL 消息流
- `_trajectory_to_acp` — trajectory 事件 → ACP 消息映射,字段缺失降级为通用消息(§1.10.7 风险缓解)
- `_build_run_cmd` — 命令行构造集中一处,接口变化时只改这里

**关键设计决定**:
1. **mock subprocess** — `process_factory` 可注入,单测用 `_FakeProc` 不依赖真 trae-cli 安装
2. **进程清理保证** — `end_session` 先 `terminate()` 等 5s,超时升级 `kill()`,trajectory 文件清理失败不阻断(§1.10.6 验收)
3. **坏行容错** — trajectory JSONL 解析失败的行降级跳过,不抛 `JSONDecodeError`(§1.10.7 字段变更风险缓解)
4. **不实现 transport 主循环** — `handle_session` 是 stub,P66-F 仅做 backend;transport-driven 主循环由后续 P66-A 框架层提供

### 3.4 验证结果

| 验证项 | 结果 |
|--------|------|
| `ruff check` extensions/trae/ + extensions/capabilities/acp_protocol.py + tests/trae/ | All checks passed |
| `pytest tests/trae/ -q` | 61 passed, 2 skipped(mcp 已装环境跳过"未安装降级"路径) |
| 稳定性门禁 Stage 1(核心导入)+ Stage 5(扩展模块) | 120 passed |
| `python -m extensions.trae.mcp_bridge` 入口 | mcp 已装时干净阻塞等 stdin(MCP server 设计预期);未装时 exit 2 提示安装 |

### 3.5 待办(后续里程碑)

- **M3** — P66-A transport-driven 主循环收敛(stdio/WebSocket transport 实现 + `handle_session` 主循环),借助 P66-F 的 backend 实现经验
- **M4** — P66-B/C/D 依次接入 Zed / Cursor / 完整 Skills 桥接(本次落地的 `ACPTransport`/`ACPServer` Protocol 已预留接口)
- **E2E 余量**:真 `trae-cli` trajectory 验证待人工执行 + `mcp inspector` schema 校验(§1.9.5 / §1.10.6)
- **生产化**:`clawcodex_orchestrator_run_issue` 当前默认实现仅写 `.reports/<run_id>.ndjson`;生产部署需通过 `orchestrator_enqueue=` 注入 daemon 投递层

### 3.6 Trae CN 本地对接(2026-07-02 完成)

**目标**:落地 §1.9.5 中"本地 Trae CN E2E"验收项,打通 Trae CN → clawcodex bridge 的完整调用链路。

**关键挑战 — 跨环境集成**:
Trae CN 是 Windows 原生进程,而 clawcodex 依赖(pytest、extensions/sop_converter、extensions/skills_ext)安装在 WSL Ubuntu-24.04。MCP stdio 协议通过 stdin/stdout 通信,`wsl.exe` 的 stdio 透明转发到 WSL 内进程,因此跨环境可行。

**落地内容**:

1. **`extensions/trae/mcp_bridge.py` 增 `_win_to_wsl` 路径转换**
   - `BridgeConfig.from_env` 自动把 env 里 Windows 路径(`C:\xxx`)转 WSL 路径(`/mnt/c/xxx`),Trae 传入的 `${workspaceFolder}` 直传可工作
   - `CLAWCODEX_AUTO_WIN_TO_WSL=0` 可禁用(纯 Linux 部署场景)
   - POSIX 路径、`\\wsl$` UNC 路径原样返回,不误转

2. **Trae CN `mcp.json` 注册**(`%APPDATA%\Trae CN\User\mcp.json`)
   - command 用 `C:\Windows\System32\wsl.exe`,args 含 `-d Ubuntu-24.04 -- bash -lc "cd <repo> && python3 -m extensions.trae.mcp_bridge"`
   - 保留原有 `mcp-obsidian` 配置,原文件备份为 `mcp.json.bak.<ts>`
   - env 设 `CLAWCODEX_AUTO_WIN_TO_WSL=1`

3. **对接文档** `extensions/trae/README.md` — 接入步骤、工具说明、故障排查表、回滚方式、验收对照

4. **单测** `tests/trae/test_mcp_bridge.py` 新增 7 个路径转换测试(`_win_to_wsl` 5 种形态 + `from_env` 转换/禁用)

**E2E 验证结果**:

| 验证项 | 结果 |
|--------|------|
| `python -m extensions.trae.mcp_bridge` 独立启动,tools/list 返回 4 工具 | ✓ |
| Trae CN 完整链路(`wsl.exe -d Ubuntu-24.04 → bash -lc → python -m`)tools/list 返回 4 工具 | ✓ |
| `clawcodex_stability_gate` 工具实跑,返回 `exit=0 \| 345 passed in 48.23s` | ✓ |
| Windows→WSL 路径转换(`C:\WorkSpace\clawcodex` → `/mnt/c/WorkSpace/clawcodex`) | ✓ |
| `pytest tests/trae/test_mcp_bridge.py` | 31 passed, 2 skipped |
| `ruff check extensions/trae/ tests/trae/` | All checks passed |

**踩坑记录**:
- `wsl.exe -d Ubuntu` 报 `WSL_E_DISTRO_NOT_FOUND` — 本机发行版名是 `Ubuntu-24.04` 而非 `Ubuntu`,需 `wsl.exe -l -v` 查实际名
- `wsl.exe` 在 WSL 内嵌套调用时 stdout 可能夹杂非 UTF-8 头部字节,但生产 MCP 客户端(Trae CN 是真 Windows 进程直接调 wsl.exe)不受影响

**用户使用方式**:在 Trae CN 对话框直接说"用 clawcodex 跑一次稳定性门禁",AI 自动调用 `clawcodex_stability_gate` 工具。详见 `extensions/trae/README.md`。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建(从四源融合) | 四文档合并 |
| 2026-06-24 | 补全详细设计(数据模型+接口+传输实现) | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-02 | 新增 P66-E / P66-F 两个子特性(支持字节 Trae 产品矩阵) | Trae IDE 仅支持 MCP 而非 ACP,需双轨路线;Trae Agent 暂未实现 ACP(见 trae-agent #344)。设计为 MCP 反向 + CLI 包装两条独立路径,均落地 `extensions/trae/` 完全解耦 |
| 2026-07-02 | 补充 §1.9 P66-E / §1.10 P66-F / §1.11 优先级与里程碑 | 明确 P0→P1→P2→P3 实施顺序、M1-M4 里程碑、回滚策略 |
| 2026-07-02 | 落地 P66-A 协议契约 + P66-E MCP 反向桥 + P66-F CLI 适配器;新增 §3 实施记录 | M1/M2 完成。`extensions/capabilities/acp_protocol.py`(数据模型+Protocol)、`extensions/trae/mcp_bridge.py`(4 工具,mcp 可选降级,fire-and-forget)、`extensions/trae/acp_cli_adapter.py`(mock subprocess,trajectory 容错)。适配真实接口而非规划稿(orchestrator_enqueue 注入 / convert_sop_to_agent / SkillRegistryExt / subprocess pytest)。单测 54 passed+2 skipped,Stage 1/5 门禁 120 passed |
| 2026-07-02 | Trae CN 本地 E2E 对接完成(§3.6):`_win_to_wsl` 路径转换、wsl.exe 跨环境链路、Trae CN mcp.json 注册、对接文档 `extensions/trae/README.md` | 打通 Trae CN(Windows)→ clawcodex bridge(WSL)的完整 MCP 调用链路;§1.9.5 验收前三项通过。单测 61 passed+2 skipped |

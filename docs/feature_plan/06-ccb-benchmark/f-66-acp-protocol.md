# F-66: ACP 协议支持

> 状态: 📋 规划中
> 章节: docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB ACP（Agent Client Protocol），支持 Zed/Cursor 等 IDE 集成协议，实现会话恢复、Skills 桥接等功能。

### 1.2 背景

ACP（Agent Client Protocol）是 Anthropic 与 Zed/Cursor 等 IDE 合作推出的 Agent-IDE 通信协议。CCB 通过 `@agentclientprotocol/sdk` 原生支持 ACP。clawcodex 目前无对应实现。

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P66-A | ACP SDK 基础协议实现 | 实现 ACP 协议核心：session/skill/tool 通信 | 📋 | 3-5天 |
| P66-B | Zed IDE 集成接入 | 通过 ACP 协议桥接到 Zed AI 插件 | 📋 | 2-3天 |
| P66-C | Cursor IDE 集成接入 | 通过 ACP 协议桥接到 Cursor | 📋 | 2-3天 |
| P66-D | 会话恢复与 Skills 桥接 | ACP session resume + skill 桥接 | 📋 | 2-3天 |

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

## §2 进度跟踪

尚未开始实现。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（数据模型+接口+传输实现） | 对齐 FEATURE_PLAN.legacy.md |

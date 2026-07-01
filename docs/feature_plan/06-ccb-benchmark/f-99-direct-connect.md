# F-99: DIRECT_CONNECT 直连模式

> 状态: 🔄 进行中(已有 `src/server/{direct_connect_manager,direct_connect_session,session_manager,session_index,lockfile,url_scheme,types}.py` 基础;目标在 `clawcodex_ext/services/direct_connect/` 之上做产品化)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-99-direct-connect.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-99: DIRECT_CONNECT 直连模式`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-99 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

`src/server/` 基础完整,但**缺产品化闭环**:

- 已有 `direct_connect_manager.py`(`DirectConnectSessionManager` WS 客户端生命周期:connect / send_message / respond_to_permission_request / send_interrupt / disconnect);
- 已有 `direct_connect_session.py`(`create_direct_connect_session()` HTTP POST `/sessions`);
- 已有 `session_manager.py`(server-side STARTING/RUNNING/DETACHED/STOPPING/STOPPED 状态机);
- 已有 `session_index.py`(`~/.claude/server-sessions.json` atomic write + flock);
- 已有 `lockfile.py`(`~/.claude/server.lock` POSIX flock);
- 已有 `url_scheme.py`(`cc://` / `cc+unix://` 解析)+ `types.py`。

完全缺失:

- 显式 `clawcodex server start/stop/status` daemon CLI;
- `attach/detach/resume` CLI 命令族(`claude --attach/--detach`、`sessions ls/attach/detach`);
- `--resume` 与 detached session 的产品化桥接;
- lockfile Windows no-op 行为是 P0 阻塞(WSL/Windows 11);
- TUI 显示"当前 server / detached session 数";
- 权限请求 TUI 弹窗路径统一 + 跨 await/WS 的统一 audit logger。

### 0.2 对标

- CCB `DIRECT_CONNECT` 完整 attach / detach / resume 生命周期;
- CCB `cc://` / `cc+unix://` 一键打开本地 daemon;
- CCB session index + lockfile 一致性恢复(missing session / 断线 / 锁泄漏);
- CCB 与 BG_SESSIONS(detached ↔ background 语义统一)+ Remote Control 同进程协同。

### 0.3 解耦落地路径(在 `clawcodex_ext/services/direct_connect/` 之上产品化,不动 `src/server/`)

- `models.py` — `ServerState` / `ServerStatus` / `AttachOptions` / `DetachOptions`;
- `server_process.py:ServerProcess` — 子进程 / supervise / restart / port pick;
- `consistency.py` — session index + lockfile init / merge / GC / orphan cleanup;
- `clawcodex_ext/cli/server_commands.py` — `clawcodex server start/stop/status` + `sessions ls/attach/detach/resume`;
- `url_handler.py` — `cc://` / `cc+unix://` 解析 + 自动 connect;
- 与 F-94 BG_SESSIONS(session_id 命名空间共享)/ F-82 Remote Control(单进程双 mode)协同;
- TUI footer / statusline server 状态 + 权限请求统一弹窗。

### 0.4 依赖

- 现有 `src/server/{direct_connect_manager,direct_connect_session,session_manager,session_index,lockfile,url_scheme,types}.py`;
- F-94 BG_SESSIONS(detached ↔ background 语义,`source=direct_connect` 区分);
- F-82 Remote Control(同进程 server + control client);
- F-125 Headless multi-turn(`--resume` 与 detached session 的冲突处理);
- F-98 SSH_REMOTE(远端 session 命名空间)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `DIRECT_CONNECT` 能力,把 ClawCodex 当前位于 `src/server/` 的“长进程会话管理 + 直连 WS / UDS 客户端”整合为面向用户的**直连模式产品**:用户既能启停 detached 会话,也能 attach 到已有的 server、resume 到 detached session、或通过 `cc://` / `cc+unix://` 一键打开本地 daemon。

F-99 的核心目标不是重写 WS 客户端(已存在),而是**补齐**:

- 完整的 `ServerProcess`(server-side life cycle + restart policy);
- 透明的 attach / detach / resume CLI;
- session index 与 lockfile 一致性恢复;
- 与 F-94 BG_SESSIONS 协同(detached ↔ background 的语义统一);
- 与 F-82 Remote Control 协同(同一进程同时承担 server + remote client);
- TUI 入口(footer / palette 显示可 attach 的 server 状态);
- 失败恢复(missing session、断线、锁文件泄漏)的产品级处理。

### 1.2 背景

现有实现基线(在 `src/server/` 下,不属于 clawcodex_ext,但已被解耦 import):

1. `direct_connect_manager.py`:`DirectConnectCallbacks` + `DirectConnectSessionManager`,负责 WS 客户端的生命周期:
   - `connect()` / `send_message()` / `respond_to_permission_request()` / `send_interrupt()` / `disconnect()`
   - 消息路由:control_request(can_use_tool) → 权限回调;其他 SDK 消息 → on_message
   - 过滤类型:`control_response` / `keep_alive` / `control_cancel_request` / `streamlined_*` / `post_turn_summary`
2. `direct_connect_session.py`:`DirectConnectConfig` + `create_direct_connect_session()`:HTTP POST `/sessions` → 返回 `(server_url, session_id, ws_url, auth_token)`
3. `session_manager.py`:server-side session 管理(STARTING / RUNNING / DETACHED / STOPPING / STOPPED 状态机)
4. `session_index.py`:`~/.claude/server-sessions.json` 持久化 + atomic write + flock
5. `lockfile.py`:`~/.claude/server.lock` POSIX flock,防止多 server 实例抢端口
6. `url_scheme.py`:`cc://host:port/session?k=v` 与 `cc+unix:///path/session?k=v` 解析
7. `types.py`:`ServerConfig` / `SessionState` / `SessionInfo` / `SessionIndexEntry` / `validate_connect_response`

主要缺口:

- **server 进程入口**未整合:没有显式的 `clawcodex server start / stop / status` CLI(可参考 `src/server/server.py` 但需要确认是否足以成为 daemon 形态);
- **attach/detach CLI** 缺失:`claude --attach <id>`、`claude --detach <id>`、`claude sessions list/attach/detach` 命令族薄弱;
- **resume 语义**:`server-sessions.json` 持久化有,但 `clawcodex --resume` 与 detached session 的桥接未产品化(已在 [F-125 Headless multi-turn](./f-125-headless-multi-turn.md) 讨论 `--resume` 与 detached session 的冲突);
- **lockfile 生命周期**:`ServerLockfile.acquire()` 当前的 no-op Windows 行为是 P0 阻塞(WSL/Windows 11 用户);
- **TUI 状态可见性**:TUI 没有显示“当前 server / detached session 数”;
- **权限请求 UX**:`on_permission_request` 回调交给上层,但 TUI 中弹窗路径未统一;
- **审计**:F-99 跨多个 await + WS,缺少统一的 audit logger;
- **跨平台**:macOS 与 Linux 严格按 POSIX;Windows 用户被劝退(文档明示不支持)但 WSL 上跑是否仍被支持需明确。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P99-A | 数据模型:`ServerState` / `ServerStatus` / `AttachOptions` / `DetachOptions` | 1 天 |
| P99-B | `ServerProcess` 入口(子进程 / supervise / restart / port pick)| 1.5 天 |
| P99-C | Session index + lockfile 一致性:init / merge / GC / orphan cleanup | 1.5 天 |
| P99-D | 直连 CLI 接入:`clawcodex server start/stop/status` / `clawcodex sessions ls/attach/detach/resume` | 2 天 |
| P99-E | URL scheme 处理(`cc://` / `cc+unix://`):解析 + 自动 connect | 0.5 天 |
| P99-F | 与 F-94 BG_SESSIONS 双向语义统一:session_id 命名空间 / status 共享 | 1 天 |
| P99-G | 与 F-82 Remote Control 同进程共存:单进程 server-mode + control-server-mode | 1.5 天 |
| P99-H | 权限请求 UX:TUI 统一弹窗 / 拒绝日志 / 默认决策 | 1 天 |
| P99-I | TUI footer / statusline 显示 server / session 状态 | 0.5 天 |
| P99-J | 单元 + 集成测试(无 ws server 走 in-process mock)+ 安全测试 | 2 天 |

**估算工时**:1 周。

### 1.4 架构设计

```
Client
  ├─ TUI / REPL / Headless
  ├─ Launch: clawcodex server start
  └─ Connect: clawcodex sessions attach <id> | clawcodex cc://...
             │
             ▼
clawcodex_ext/services/direct_connect/
  ├─ CliCommands (P99-D)
  ├─ ServerProcess (P99-B)
  ├─ SessionAttachService (P99-D/F)
  ├─ UrlSchemeAdapter (P99-E)
  └─ Audit / Logging (P99-J)
             │
             ▼
src/server/  (已存在,核心层)
  ├─ direct_connect_manager.py
  ├─ direct_connect_session.py
  ├─ session_manager.py
  ├─ session_index.py
  ├─ lockfile.py
  ├─ url_scheme.py
  └─ server.py
```

#### 包结构

```
clawcodex_ext/services/direct_connect/
├── __init__.py
├── server_process.py              # P99-B: 子进程 + 重启策略
├── server_health.py               # P99-C: lockfile / index 一致性
├── attach_service.py              # P99-D/F: attach / detach / resume 高层 API
├── cli.py                         # P99-D: clawcodex server / sessions 命令族
├── url_scheme_adapter.py          # P99-E: cc:// / cc+unix:// 处理
├── audit.py                       # P99-J: 统一审计日志
└── permissions.py                 # P99-H: 权限请求与默认决策

clawcodex_ext/command_system/
└── direct_connect_commands.py     # P99-D: /server, /sessions 命令族

clawcodex_ext/tui/
└── direct_connect_panel.py        # P99-I: footer + TUI 状态条

extensions/capabilities/
└── direct_connect_protocol.py     # P99-D: ServerHandle / SessionHandle Protocol

tests/clawcodex_ext/services/direct_connect/
├── test_server_process.py
├── test_attach_service.py
├── test_session_index_gc.py
├── test_url_scheme_adapter.py
├── test_direct_connect_cli.py
└── test_permissions.py
```

### 1.5 核心数据模型

```python
ServerState = Literal["stopped", "starting", "ready", "detached", "stopping", "error"]


@dataclass(frozen=True)
class ServerSpec:
    mode: Literal["tcp", "unix"] = "tcp"
    host: str = "127.0.0.1"
    port: int = 0                              # 0 = pick free port
    unix_socket: str | None = None
    workspace: str | None = None
    auth_token: str | None = None              # None → 自动生成
    idle_timeout_ms: int = 0                   # 0 = never expire
    max_sessions: int | None = None
    dangerously_skip_permissions: bool = False


@dataclass(frozen=True)
class ServerStatus:
    state: ServerState
    pid: int | None = None
    listening_on: str | None = None            # e.g. "tcp://127.0.0.1:7300"
    sessions_running: int = 0
    sessions_detached: int = 0
    lockfile_path: Path | None = None
    started_at: str | None = None
    last_active_at: str | None = None
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class SessionHandle:
    server_url: str
    session_id: str
    work_dir: str
    transcript_session_id: str | None
    permission_mode: str | None
    state: str                                  # from SessionState
    created_at: str
    last_active_at: str


@dataclass(frozen=True)
class AttachOptions:
    server_url: str
    session_id: str
    auth_token: str | None = None
    follow: bool = True
    permissions: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "default"


@dataclass(frozen=True)
class DirectConnectConfig:
    enabled: bool = False
    auto_start: bool = True                     # 缺省由 cli 启 server
    default_server: ServerSpec = field(default_factory=ServerSpec)
    url_scheme_handlers: tuple[str, ...] = ("cc", "cc+unix")
    permission_default: Literal["ask", "allow-tool-specific", "bypass"] = "ask"
    audit_log_path: Path = Path("~/.clawcodex/direct_connect/audit.jsonl")
    max_audit_entries: int = 2000
```

> 注:`ServerSpec` 已通过 `src/server/types.py:ServerConfig` 提供 foundation(默认 800 行级);F-99 包装`ServerConfig` 为 `ServerSpec`(语义化 spec)并补上 `state` / `pid` 等观察字段。

### 1.6 核心接口

```python
class ServerProcess:
    """server 子进程生命周期与重启策略。"""

    def __init__(self, *, spec: ServerSpec, lockfile_path: Path) -> None: ...

    async def start(self, *, wait_ready_timeout_s: float = 10.0) -> ServerStatus: ...

    async def stop(self, *, force: bool = False, grace_period_s: float = 5.0) -> ServerStatus: ...

    async def status(self) -> ServerStatus: ...

    async def wait_ready(self, *, timeout_s: float = 10.0) -> None: ...

    async def restart(self) -> ServerStatus: ...


class AttachService:
    """attach / detach / resume 高层 API。"""

    def __init__(self, *, server_manager: ServerProcess, session_index: SessionIndex) -> None: ...

    async def list(self) -> list[SessionHandle]: ...

    async def attach(self, opts: AttachOptions) -> SessionHandle: ...

    async def detach(self, session_id: str, *, reason: str | None = None) -> SessionHandle: ...

    async def resume(self, transcript_session_id: str) -> SessionHandle: ...

    async def start_new(self, *, work_dir: str, permissions: str | None = None) -> SessionHandle: ...

    async def kill(self, session_id: str, *, force: bool = False) -> bool: ...


class UrlSchemeAdapter:
    """解析 cc:// 与 cc+unix:// 并触发对应 attach。"""

    def parse(self, raw: str) -> CCAddress: ...

    async def handle(self, raw: str, *, attach_service: AttachService) -> SessionHandle: ...


class DirectConnectAuditLog:
    """统一 append-only 审计。"""

    def __init__(self, *, path: Path, max_entries: int) -> None: ...

    def append(self, event: DirectConnectAuditEvent) -> None: ...

    def list(self, *, limit: int = 50) -> list[DirectConnectAuditEvent]: ...
```

### 1.7 状态机与生命周期 + ServerProcess 行为

#### ServerProcess 状态机

```
stopped ──start()──▶ starting ──ready callback──▶ ready
                          │                       │
                          │ start fail            │ auto_stop / idle timeout
                          ▼                       ▼
                        error                  stopping
                                                  │
                                                  ▼
                                                stopped
```

#### 子进程 / port 选择 / Windows 兼容

- 通过 `subprocess.Popen(["clawcodex", "server", "run", ...])` 启子进程,PID 写入 `~/.claude/server.lock` 旁路;
- 父进程与子进程用 stdio 简短同步:子进程 ready 后打印一行 NDJSON(`{"event":"ready","listen":"tcp://127.0.0.1:7300"}`),父进程解析后 `wait_ready` 通过;
- 子进程 SIGTERM 后 grace `grace_period_s`(默认 5s),在 grace 内优雅停 server;超时 SIGKILL;
- 重启策略:`ServerSpec.restart_policy`:`always` / `on-failure` / `never`;默认 `on-failure`,最多 5 次退避后停;
- 若 `port=0`,通过 stdlib `socket.socket(); bind((host, 0))` 探测空闲 port,赋给子进程 `CLAWCODEX_SERVER_PORT` 环境变量;
- 避免与 lockfile 持有者冲突(`os.open` / `flock` 校验);
- `lockfile.flock` 当前在 Windows 是 no-op;F-99 中改为**msvcrt.locking** 或 PID sentinel,两者任选一;Windows 用户需 WSL,因此 lockfile 在原生 Windows 不写,引导 WSL。

#### Session 状态机 + 持久化

```
STARTING ──worker proc started──▶ RUNNING ──user detach──▶ DETACHED
                                       │
                                       └──user stop / idle reap──▶ STOPPING ──▶ STOPPED
```

`DETACHED` 状态与 F-94 BG_SESSIONS 的 `paused` 语义映射:server-side session 仍持有 transcript,可 attach / resume / re-attach。

- 服务端每次状态迁移都先写 in-memory → 再 publish to `~/.claude/server-sessions.json`(atomic write + fcntl flock),失败时不抑制状态但只 WARN,等下一次 migration 重试;
- 客户端在 attach 时读 `~/.claude/server-sessions.json`,拿到 `transcript_session_id`,可以走 `claude --resume {tid}` 转到本地进程(参考 [F-125](./f-125-headless-multi-turn.md) 已有的 `--resume` 语义)。

### 1.8 直连 CLI / UrlSchemeAdapter

#### 直连 CLI 命令族

```
clawcodex server start [--port N] [--unix /path] [--max-sessions N] [--no-auth] [--background]
clawcodex server stop [--force]
clawcodex server status [--json]
clawcodex server logs [--tail 50]

clawcodex sessions list                # 列出 server-side sessions
clawcodex sessions attach <id>         # attach 到 DETACHED / RUNNING session
clawcodex sessions detach <id>         # 当前 foreground session 转入 DETACHED
clawcodex sessions resume <tid>        # 按 transcript session_id 拉起新 worker
clawcodex sessions kill <id> [--force]

clawcodex cc://host:port/session-id    # URL 形式触发 attach(可注册为 OS scheme handler)
clawcodex cc+unix:///path/to/sock/session-id
```

实现要点:

- `clawcodex server start` 默认 detach 到后台(`--background`),在 `/var/log/clawcodex-server.log` 写入日志;
- `clawcodex sessions attach` 启动独立 TUI / REPL 子进程,转 SDK 消息流到本地显示;
- URL scheme 注册不在 F-99 主线(各 OS handler 安装步骤单独文档化)。

#### UrlSchemeAdapter

- 重新 export `CCAddress` / `parse_cc_url`(`src.server.url_scheme`),F-99 包装成 `handle(raw, attach_service=...)`;
- `handle()` 若 `cc://` → 解析到 host:port + session_id → 通过 `attach_service.attach()` 走 TCP;
- `cc+unix://` → 同上但走 Unix socket;
- 解析失败抛 `UrlSchemeParseError`;
- 同进程触发时直接复用 `server_manager` 提供的 in-process test client(测试用)。

### 1.9 F-94 / F-82 协同 + 权限 UX + TUI 集成

#### 与 F-94 BG_SESSIONS 协同

BG_SESSIONS 主要面向 **本地后台会话**(fork/subprocess);DIRECT_CONNECT 主要面向 **server-detached 会话**。两者协同:

| 场景 | 触发 | 行为 |
|------|------|------|
| 用户在 TUI 中按 `Ctrl+B` | 当前 TUI session background | F-94 BG_SESSIONS 接管(本机) |
| 用户通过 `cc://` attach 到 server session | 客户端 attach | F-99 DIRECT_CONNECT 接管(远端) |
| BG session on remote | `launch_background_runner(ssh_profile=...)` | F-98 + F-94 双重,server 列为 `DETACHED` |
| `server sessions list` | 列出 server-detached | 与 `bg list` 共用 `~/.clawcodex/bg_sessions/index.json` 或独立 `server-sessions.json`,两者通过 `session_id` 互引 |

实现:`bg_session_registry.scan()` 把 `~/.claude/server-sessions.json` 中仍 `RUNNING` / `DETACHED` 的 session 视为 BG_SESSIONS 的特殊来源,以 `source=direct_connect` 标记。

#### 与 F-82 Remote Control 协同

Remote Control 提供 Web/RCS 控制接口;DIRECT_CONNECT 提供 CLI / TUI 控制接口。二者**不应当同时占用同一 800 端口**:

- DIRECT_CONNECT 启动时,如检测到 Remote Control server 已在监听,自动选用对方未占用的端口(默认 800 vs 7300);
- 也支持 `server start --port 800 --share-with=remote-control`,人为合并(限制:仅 unix socket 可共享);
- 同一进程可以 dual-role:`server start --mode tcp --port 7300 --remote-control`,业务逻辑上 Remote Control = Direct Connect 的 GUI 皮,两者共享 session_manager。

#### 权限请求 UX

`on_permission_request(can_use_tool, request_id)` 收到 `can_use_tool` 时,TUI 弹窗;F-99 提供:

- 默认 `permission_default="ask"`:弹窗,展示工具名、参数摘要、`updatedInput` 提示;
- `permission_default="allow-tool-specific"`:基于工具名 + 参数 pattern 自适应(写入 `policy.json`);
- `permission_default="bypass"`:全部 allow,只在 audit 写一条。

`DirectConnectAuditLog.append()` 包含:`session_id` / `tool_name` / `input_hash` / `decision` / `decision_source` / `responded_at` / `actor`。

#### TUI 集成

- footer:`[direct-connect] tcp://127.0.0.1:7300 | sessions: 2 running, 1 detached` (只在 server-mode 显示);
- `/server` 命令:显示当前 server status + sessions summary;
- `/sessions` 命令族:列出 / attach / detach / resume;
- detached session 列表 + command palette:支持 `Ctrl+Shift+D` 弹出 detach picker;
- notification:子进程 detached 完成后,REPL 给出 1 行提示 + 可一键 attach。

### 1.10 安全、失败与权限边界(合并本节要点)

#### 安全与权限

| 类别 | 规则 |
|------|------|
| 默认 `auth_token=None` → 自动生成 `secrets.token_urlsafe(32)` | 写入 `~/.claude/server.json`,权限 0600 |
| `--no-auth` | 仅当 `host=127.0.0.1` 或 unix socket 才允许,且 console warning |
| `--unix /path` | socket 权限 0700,所有跨进程探活仅通过该 socket |
| `--dangerously-skip-permissions` | 启动时显式二次确认,console red-warning,audit 写明 |
| URL scheme(外部触发) | `cc://` 默认要求 `--allow-url-scheme` 才注册;Parse 时显式拒绝 token leak |
| 锁文件 | POSIX flock;Windows 不支持 → 引导 WSL,且不让 stdlib 静默吞 |
| Audit log | `~/.clawcodex/direct_connect/audit.jsonl`,append-only,retained `max_audit_entries` |

#### 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `ServerAlreadyRunningError` | start 时另一 server 抢 lock | 显示当前 server status,提示 attach 或 stop |
| `ServerStartTimeout` | 子进程未 ready 超时 | kill 子进程 + 报告日志 tail |
| `ServerStartFailure` | 子进程 exit 非 0 | 输出 stderr tail,保留 lockfile 释放 |
| `SessionNotFound` | 指定 session_id 不在 index | 列出 server 内尚存 sessions,支持 fuzzy 匹配 |
| `SessionAttachError` | WS connect 失败 / token 错 | 重新拉一次 server status,失败时 dump server logs tail |
| `SessionPermissionDenied` | 权限路径不合法 | 引导用户重启 server with token |
| `UrlSchemeParseError` | URL 解析失败 | 显示 example + 重试 |
| `LockfileStaleError` | 旧 lockfile + 旧 PID 死掉但 file 残存 | 比对 PID 存活性,如死则抢锁并清理 |
| `ServerVersionMismatch` | server version < client version 协议字段 | refuse 连接,提示升级 |

### 1.11 验收标准

1. `clawcodex server start --port 0 --background` 后,`server status` 返回 `ready` + 探测到的 port;
2. `clawcodex server stop` 在 grace 内优雅退出;`--force` 立即 SIGKILL;
3. `start` 期间 lockfile 被另一进程持有时报 `ServerAlreadyRunningError`,输出已有 server status;
4. `start` crash 后 lockfile 不残留(POSIX flock 自动释放 + sentinel PID 死则清理);
5. `sessions list` 显示所有 `RUNNING` + `DETACHED` session,`attach <id>` 后转 foreground SDK 流;
6. `cc://127.0.0.1:7300/abc123?token=...` 经 `UrlSchemeAdapter.handle()` 自动 attach;
7. `cc+unix:///tmp/cx.sock/abc123` 走 unix socket 直连;
8. detached session 后续 `resume` 拉到 `~/.claude/transcripts/<tid>.jsonl`;
9. `detach` / `attach` 行为被 audit log 记录,结构化字段完整;
10. TUI footer 在 server-mode 显示 server 状态;
11. 与 F-94 BG_SESSIONS 共享 session_id 命名空间,不冲突;
12. Windows 原生 lockfile 行为明确:WSL 上支持,原生 Windows 引导 WSL;
13. 单元 / 集成测试覆盖 `ServerProcess` / `AttachService` / `UrlSchemeAdapter` / 审计 / lockfile / 异常分支。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 梳理现有 `src/server/*` API,定义 `ServerSpec` / `ServerStatus` / `SessionHandle` 模型 | P99-A | 1 天 |
| 2 | 实现 `ServerProcess` 子进程 + restart + ready wait | P99-B | 1.5 天 |
| 3 | 实现 `SessionIndex` consistency GC + lockfile cleanup | P99-C | 1.5 天 |
| 4 | 实现 `AttachService` 高级 API + 与 src.server.session_manager 桥接 | P99-D/F | 1 天 |
| 5 | 增加 CLI:`clawcodex server start/stop/status/logs` + `sessions list/attach/detach/resume/kill` | P99-D | 1 天 |
| 6 | 实现 `UrlSchemeAdapter`(包装 src.server.url_scheme)| P99-E | 0.5 天 |
| 7 | 与 F-94 BG_SESSIONS 协同:状态聚合 + session_id 命名空间 | P99-F | 1 天 |
| 8 | 与 F-82 Remote Control 共存模式 + 同进程 dual-role | P99-G | 1.5 天 |
| 9 | 权限请求 UX + DirectConnectAuditLog | P99-H | 1 天 |
| 10 | TUI footer + /server + /sessions 命令面板 | P99-I | 0.5 天 |
| 11 | 补齐单元/集成/安全测试 | P99-J | 2 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| lockfile 在 Windows 静默失败 | 🟠 | 检测 OS,引导 WSL + 警告 |
| 子进程崩溃导致 server 卡在 starting | 🟠 | ready callback 加 timeout;超时强制 stop + 清理 |
| session-sessions.json 损坏 | 🟠 | atomic write + flush;启动时尝试恢复,失败则备份 + 重建 |
| 多 server 实例同时启动 | 🟡 | flock 保证单一 server;每个 server 仅绑单一 lock |
| `cc://` 被恶意 OS handler 触发 | 🔴 | token 必须经 user 同意提供;`--allow-url-scheme` 才允许;Parse 失败显式提示 |
| `--dangerously-skip-permissions` 错用 | 🟠 | 启动时二次确认 + audit 永久记录 + UI 红色横幅 |
| 与 F-82 端口冲突 | 🟡 | 自动避让 + `--share-with` 显式合并 |
| `~/.claude/server.lock` 兼容旧版本 | 🟡 | 新 lockfile 写新格式时,旧版本识别失败则保留并提示 |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-94 BG_SESSIONS** | 共享 session_id 命名空间;BG session ↔ DIRECT_CONNECT detached 双向 |
| **F-82 Remote Control** | 同进程 dual-role,与 RCS 共用 session_manager |
| **F-125 Headless multi-turn + --resume** | `sessions resume <tid>` 走 `--resume` 路径,把 detached transcript 转 foreground |
| **F-85 Pipe IPC** | DIRECT_CONNECT 可被内部 pipe IPC 触发(`server start` 等价 pipe 协议) |
| **F-89 Proactive** | Proactive tick 可在 detached session 上发提醒任务 |
| **F-96 Cache Break Detection** | 直连模式下 cache sample 用 session_id 同时挂到 BG session 维度 |
| **F-100 Dreaming** | Dreaming 任务可以在 detached session 上跑,低打扰 |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-94 BG_SESSIONS](./f-94-bg-sessions.md), [F-82 Remote Control](./f-82-remote-control.md), [F-125 Headless Multi-turn](./f-125-headless-multi-turn.md)

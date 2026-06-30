# F-83: 远程 Triggers(AGENT_TRIGGERS_REMOTE)

> 状态: 🟡 本地 cron 调度已成熟(`clawcodex_ext/cron_system/` 11 模块);远程 REST 同步 + `/triggers` 命令 + SSH/RCS 执行器待补
> 章节: `docs/feature_plan/06-ccb-benchmark/f-83-triggers.md`
> 最后更新: 2026-06-30
> 缺口来源: [gap-analysis-2026q2.md §3.2](./gap-analysis-2026q2.md#f-83-远程-triggersagent_triggers_remote)

## §1 设计规划

### 1.1 目标

对标 CCB `AGENT_TRIGGERS_REMOTE`(`/triggers create|list|delete` 命令 + 远程 trigger REST API),在 ClawCodex 已落地的本地 cron 调度引擎(`clawcodex_ext/cron_system/`)之上,补齐"远程触发"能力,使得:

1. **跨机器同步** —— 一台机器上注册的 trigger 可被多台机器的 ClawCodex 实例拉取并执行;
2. **REST API 入口** —— 通过 FastAPI 暴露 `POST /triggers` / `GET /triggers` / `DELETE /triggers/{id}`,兼容 curl / SDK / 上游 AGENT_TRIGGERS_REMOTE 协议;
3. **执行器双模式** —— SSH 到远程 worker(临时调试)或经 F-82 RCS HTTP/SSE 调用(生产);
4. **本地/远程桥接** —— 本地 `CronScheduler` 在每次 tick 时除了查本地 `scheduled_tasks.json`,也查远程 trigger 注册表(去重合并),实现"远程 trigger 触发本地 Agent"。

### 1.2 背景

**已完成基础设施**(`clawcodex_ext/cron_system/`,共 11 模块,已落地 F-22 全集):

| 模块 | 角色 | 关键导出 |
|------|------|----------|
| `models.py` | `CronTask` 数据类 + `CronFields` + `CronJitterConfig` + jitter 上下界(防御性 MAX_* 常量) + `is_cron_disabled()`(读 `CLAWCODEX_DISABLE_CRON`) | `CronTask` / `CronJitterConfig` |
| `parser.py` | cron 表达式解析(5 字段 min/hour/dom/month/dow + `*` / `,` / `-` / `/`) | `parse_cron_expression()` |
| `tasks.py` | 文件持久化 `~/.clawcodex/cron/scheduled_tasks.json`(atomic rename + 兼容 legacy `.claude/scheduled_tasks.json`) | `read_cron_tasks` / `write_cron_tasks` |
| `runs.py` | 每次 fire 的 `CronRun` 记录 + 队列化创建 + 终态化收尾 | `CronRun` / `create_queued_run_for_task` / `finalize_cron_run` |
| `lock.py` | 跨进程互斥锁,避免多实例重复触发 | `CronTaskLock` / `acquire_cron_storage_lock` |
| `scheduler.py` | 调度主循环(`CronScheduler.check_once()`),polling + jitter + G1 kill switch + G2 live config reload + G7 event hooks | `CronScheduler` |
| `tools.py` | AI 可调 4 个内置工具(`CronCreate/Delete/List/RunTool`)+ 路径白名单 + prompt 模板 | `CronCreateTool` / `CronDeleteTool` / `CronListTool` / `CronRunTool` |
| `runtime.py` | `attach_cron_runtime(ctx)` 把 tools + scheduler + outbox 事件(`CronMissedEvent`/`CronPromptEvent`)挂到 session | `replace_cron_tools` |
| `schedule.py` | 计算下一次触发时间(支持 jitter) | `next_fire_time()` |
| `notifications.py` | 错过任务通知生成(用于 missed-task events) | `build_missed_task_notification` |
| `status.py` | 调度器状态查询(下一次 tick、运行中 task 数) | `SchedulerStatus` |

**现状评估**:

- `CronTask` 模型字段齐全(id/cron/prompt/durable/recurring/timeout_ms/...),完全可被远程 trigger 直接复用为存储 schema,只新增 `remote: bool / endpoint: str / last_synced_at: str` 3 个可选字段即可;
- 文件锁 + atomic rename 已保证本地多进程并发安全,远程注册表复用同样的锁策略;
- `attach_cron_runtime` 提供 G1/G2/G7 钩子,F-83 远程桥接可挂载到 `on_fire_event` + `on_missed_event`,不破坏现有生命周期;
- `croniter` 等三方库未引入,parser 是自研(简单 5 字段),远程同步后 cron 表达式仍由本地 parser 校验,无需传输 cron 解析状态;
- 远程执行能力已有: `extensions/remote_api/` 提供 Hermes/OpenAI 兼容 HTTP + SSE + Bearer auth,可直接复用作为 RCS endpoint;
- FastAPI 已在 CCB 依赖中(F-82 RCS 已用),新增触发器端点零额外依赖;
- `httpx` 已在 clawcodex_ext 依赖中(F-71 P71-M `RemoteTriggerTool` 已规划依赖 httpx)。

**缺口**(用户面向层):

1. **REST API 服务**: FastAPI app + 4 个端点(`POST /triggers` 创建,`GET /triggers` 列表,`DELETE /triggers/{id}` 删除,`GET /triggers/{id}` 单项查询) **完全缺失**;
2. **远程注册表**: `~/.clawcodex/triggers.json` 持久化(JSON + 文件锁,与 `scheduled_tasks.json` 同风格) **完全缺失**;
3. **`/triggers` 命令族**: `create / list / show / delete / sync / run-now` 子命令 **完全缺失**;
4. **远程执行器**: SSH executor(`asyncssh`)+ RCS executor(经 `extensions/remote_api/`)双实现 + 协议抽象层 **完全缺失**;
5. **本地-远程桥接**: `clawcodex_ext/cron_system/remote_bridge.py` 在每次 tick 时拉取远程 trigger + 合并到本地 firing set **完全缺失**;
6. **同步协议**: `GET /v1/triggers/sync?since=<timestamp>` 增量同步接口 + 客户端去重合并 **未实现**;
7. **鉴权**: Bearer token + endpoint allowlist + per-token scope(`read` / `write` / `admin`) **完全缺失**;
8. **Feature Gate**: `AGENT_TRIGGERS_REMOTE` 注册到 F-68,默认关闭 **缺失**;
9. **`RemoteTriggerTool`**(F-71 P71-M): AI 可调,封装"远程 trigger 创建 + 同步 + 触发" **完全缺失**;
10. **审计日志**: 远程 trigger 触发记录(Prompt / output / latency / error)持久化到 NDJSON **缺失**;
11. **WSL/SSH agent forwarding**: SSH 模式下 key forwarding(避免远程 worker 又 SSH 跳板) **缺失**;
12. **冲突解决**: 同一 trigger 在多 worker 同时到点的去重 + 单 worker 抢占 **未实现**;
13. **cron 漂移检测**: 远程 worker 本地时钟偏移 > 30s 时告警 + 强制使用远程 `next_fire_time` **缺失**;
14. **测试基础设施**: mock RCS server + mock SSH server + 集成测试套件 **完全缺失**。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P83-A | FastAPI REST 端点(`extensions/triggers/api.py`):CRUD + `/sync` 增量同步 + Bearer 鉴权 + scope 检查 | 📋 | 5-7 天 |
| P83-B | 远程 Trigger 注册表(`registry.py`):`~/.clawcodex/triggers.json` + 文件锁 + atomic rename + scope 检查 | 📋 | 3-5 天 |
| P83-C | 执行器抽象(`extensions/triggers/executors/base.py`)+ SSH executor(`asyncssh`) + RCS executor(经 `extensions/remote_api/`) | 📋 | 5-7 天 |
| P83-D | 本地-远程桥接(`clawcodex_ext/cron_system/remote_bridge.py`):每次 tick 拉取远程 + 合并去重 + 抢占锁 | 📋 | 3-5 天 |
| P83-E | `/triggers` 命令族(`command_system/triggers_command.py`):7 子命令(create/list/show/delete/sync/run-now/help) | 📋 | 3-5 天 |
| P83-F | `RemoteTriggerTool`(`tool_system/tools/remote_trigger.py`):AI 可调,封装创建 / 同步 / 触发 + httpx | 📋 | 3-5 天 |
| P83-G | 鉴权层(`extensions/triggers/auth.py`):Bearer token 校验 + endpoint allowlist + per-token scope(`read` / `write` / `admin`) | 📋 | 2-3 天 |
| P83-H | Feature Gate(`clawcodex_ext/feature_gate/registry.py`):`AGENT_TRIGGERS_REMOTE` 注册 + 默认关闭 + 关闭时静默 | 📋 | 1 天 |
| P83-I | 审计日志(`extensions/triggers/audit.py`):NDJSON 持久化(`~/.clawcodex/triggers/audit/<date>.ndjson`)+ 远程 trigger 触发事件 | 📋 | 2-3 天 |
| P83-J | 冲突解决与单 worker 抢占(`registry.py` 扩展):lock token + TTL 30s + stale detection | 📋 | 2-3 天 |
| P83-K | cron 漂移检测(`bridge.py` 扩展):NTP drift 30s 阈值 + 告警 + 使用远程 `next_fire_time` | 📋 | 1-2 天 |
| P83-L | 单元 + 集成 + E2E 测试:mock FastAPI server + mock asyncssh server + 真实 RCS server 烟雾测试 | 📋 | 5-7 天 |
| P83-M | SSH agent forwarding(`extensions/triggers/executors/ssh.py` 扩展):key forwarding + ProxyJump 支持 | 📋 | 1-2 天 |

**估算总工时**: 8-10 周(单人)。

### 1.4 架构设计

#### 1.4.1 三种部署模式

```
模式 A — 中心化 Server(生产)
┌─────────────────────────────────────────────────────────────────┐
│ 中心化 Triggers Server(FastAPI)                                  │
│                                                                 │
│   POST /v1/triggers  ──►  registry.json (atomic write + lock)   │
│   GET  /v1/triggers  ──►  注册表查询(since timestamp 增量)      │
│   DEL  /v1/triggers/{id} ──►  软删除 + tombstone                │
│   GET  /v1/triggers/sync ──► 完整 dump + delta                  │
│                                                                 │
│   持久化: ~/.clawcodex/triggers.json (Server)                   │
│   审计:   ~/.clawcodex/triggers/audit/<YYYY-MM-DD>.ndjson       │
└─────────────────────────────────────────────────────────────────┘
              ▲   同步触发列表           ▼  HTTP/SSE 触发执行
┌─────────┐  │                  ┌─────────────────┐
│ worker-1│  │                  │  worker-N       │
│ cron +  │──┘                  │  cron +         │
│ remote_ │  ─── POST execute ─►│  remote_        │
│ bridge  │                     │  bridge         │
└─────────┘                     └─────────────────┘

模式 B — 嵌入式(单机 / 临时调试)
   本地 ClawCodex 进程内同时启动 FastAPI server 与 scheduler,
   通过 UDS / localhost 通信,registry 走本地文件。
   适用:开发环境、单用户单机、CI 烟雾测试。

模式 C — 直连(Swarm,无中心 server)
   worker 间通过 F-85 Pipe IPC + LAN_PIPES 共享 trigger 列表,
   触发走 UDS,无需 FastAPI。
   适用:F-85 已落地的多机协作场景,F-83 提供 trigger 协议,
   底层 transport 由 F-85 提供。
```

#### 1.4.2 端到端调用链

```
用户 CLI / 远端 trigger
       │
       ▼
┌──────────────────┐
│ /triggers create │  ──► TriggersCommand.handle_create(args)
│   <cron> <prompt>│      │
│   --remote URL   │      │
└──────────────────┘      │
                          ▼
                  ┌──────────────────┐
                  │ TriggersClient   │ (httpx + Bearer token)
                  │ POST /v1/triggers│
                  └──────────────────┘
                          │
                          ▼
                  ┌──────────────────────────────┐
                  │ FastAPI: POST /v1/triggers   │
                  │   1. auth.verify(scope=write)│
                  │   2. payload validate        │
                  │   3. registry.insert(id, ...)│
                  │   4. audit.write(create)     │
                  │   5. return TriggerResponse   │
                  └──────────────────────────────┘
                          │
                          ▼
                  ┌──────────────────────────────┐
                  │ Registry(~/.clawcodex/       │
                  │   triggers.json + flock)     │
                  └──────────────────────────────┘

worker tick
       │
       ▼
┌──────────────────────────────────────────┐
│ CronScheduler.check_once()               │
│   1. find_due_tasks(本地 scheduled_tasks)│
│   2. remote_bridge.sync() ──► 拉远端     │
│      GET /v1/triggers/sync?since=<ts>    │
│   3. 合并: 本地 due ∪ 远端 due (去重)   │
│   4. 对每个 due task:                    │
│      a. remote_bridge.acquire_lock(id)    │
│      b. executor.execute(task) ─► SSH/RCS│
│      c. audit.write(executed)            │
│      d. release_lock(id)                  │
└──────────────────────────────────────────┘
```

#### 1.4.3 包结构(全部解耦,不动 `src/`)

```
extensions/triggers/                            ← 全新 Layer 2 子系统
├── __init__.py                                # 公共导出
├── server.py                                  # P83-A: FastAPI app 工厂 + lifespan
├── api.py                                     # P83-A: 4 端点 + sync 端点 + auth dependency
├── registry.py                                # P83-B/J: 注册表(文件锁 + atomic rename + lock token)
├── models.py                                  # TriggerPayload / TriggerResponse / Scope / TriggerDelta
├── auth.py                                    # P83-G: Bearer token + allowlist + scope 检查
├── audit.py                                   # P83-I: NDJSON 审计 + 滚动
├── executors/
│   ├── __init__.py
│   ├── base.py                                # P83-C: Executor Protocol + 执行结果
│   ├── ssh.py                                 # P83-C/M: asyncssh + agent forwarding
│   ├── rcs.py                                 # P83-C: 经 extensions/remote_api/ HTTP/SSE
│   └── local.py                               # P83-C: 直接本地子进程(调试模式)
├── drift.py                                   # P83-K: NTP drift 检测
├── config.py                                  # ServerConfig dataclass(Bearer / port / workers)
├── errors.py                                  # 自定义异常
└── constants.py                               # LOCK_TTL_SECONDS / MAX_TRIGGER_PROMPT_CHARS 等

clawcodex_ext/cron_system/                      ← 现有原语层(扩展)
├── ...(已有 11 模块)
└── remote_bridge.py                           # P83-D/K: 拉远端 + 合并 + 抢占 + drift

clawcodex_ext/command_system/
├── triggers_command.py                        # P83-E: /triggers 7 子命令
└── input_processing.py                        # 已有,扩展关键字检测

clawcodex_ext/tool_system/tools/
└── remote_trigger.py                          # P83-F: RemoteTriggerTool(AI 可调)

clawcodex_ext/clients/
└── triggers_client.py                         # P83-E: TriggersClient(httpx + Bearer,供 CLI/工具共用)

clawcodex_ext/feature_gate/registry.py         # P83-H: 注册 AGENT_TRIGGERS_REMOTE(默认 off)
```

#### 1.4.4 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| FastAPI Server | 全新子系统 → `extensions/triggers/`(Layer 2) | 不依赖上游具体 HTTP 框架 |
| 注册表 + 同步协议 | 同上 `extensions/triggers/registry.py` | 与 cron_system 本地存储分离 |
| 执行器抽象 | `extensions/capabilities/executor_protocol.py`(待新建) + `extensions/triggers/executors/` | Layer 2 → Layer 1 解耦,支持 mock |
| 桥接到本地 cron | `clawcodex_ext/cron_system/remote_bridge.py`(钩子注入) | 不修改 `CronScheduler.check_once()` 内部 |
| `/triggers` 命令 | `clawcodex_ext/command_system/triggers_command.py` + `builtins.py::get_builtin_commands` 列表追加 | 沿用 F-71/F-87 风格 |
| `RemoteTriggerTool` | `clawcodex_ext/tool_system/tools/remote_trigger.py` + `tool_registry.register()` | F-71 P71-M 落地 |
| 鉴权 | `extensions/triggers/auth.py`,只依赖 FastAPI 的 `Depends` 机制 | 不引入新框架 |
| Feature Flag | F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `AGENT_TRIGGERS_REMOTE` | 默认 off,避免误开远程执行 |
| 与 F-82 协同 | 远端 endpoint 可指向 `extensions/remote_api/` 任何 worker,共用 Bearer auth | 复用 F-82 基础设施 |
| 与 F-85 协同 | Swarm 模式(模式 C)复用 F-85 Pipe IPC 作为 transport,trigger 协议独立 | F-83 协议层与传输层分离 |

### 1.5 核心数据模型

#### 1.5.1 Trigger 模型(P83-B)

```python
# extensions/triggers/models.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

class TriggerScope(str, Enum):
    READ = "read"               # 列出 / 查询
    WRITE = "write"             # 创建 / 更新 / 删除
    EXECUTE = "execute"         # 触发执行(仅 cron worker)
    ADMIN = "admin"             # 全权 + 鉴权管理

class TriggerKind(str, Enum):
    RECURRING = "recurring"     # cron 表达式
    ONE_SHOT = "one_shot"       # 单次 ISO 8601 时间
    INTERVAL = "interval"       # 每 N 秒

@dataclass(frozen=True)
class TriggerPayload:
    """用户提交的 trigger 定义。"""
    id: str                                  # ^[A-Za-z0-9._-]{1,64}$
    cron: str | None                         # cron 表达式(RECURRING 必填)
    fire_at: str | None                      # ISO 8601(ONE_SHOT 必填)
    interval_seconds: int | None             # INTERVAL 必填
    prompt: str                              # ≤ 30,000 chars,模型输入
    model: str | None = None                 # 覆盖默认 Provider.model
    max_runtime_ms: int = 300_000            # 单次执行超时
    recurring_max_age_ms: int | None = None   # 同 CronJitterConfig
    jitter_config: dict | None = None        # 覆盖默认
    allowed_endpoints: tuple[str, ...] = ()  # 限定执行的 worker endpoint
    metadata: dict[str, str] = field(default_factory=dict)
    # 远程触发独有
    remote: bool = False                     # True = 远程 trigger;False = 本地 cron
    endpoint: str | None = None              # 远端 worker URL(EXECUTE scope 限定)
    last_synced_at: str | None = None        # 客户端最近一次同步时间

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> TriggerPayload: ...
```

#### 1.5.2 注册表条目(P83-B + P83-J)

```python
@dataclass(frozen=True)
class RegisteredTrigger:
    payload: TriggerPayload
    created_at: str                          # ISO 8601
    updated_at: str
    created_by: str                          # token id
    deleted: bool = False                    # 软删除 tombstone
    # P83-J: 抢占锁
    held_by: str | None = None               # 当前持有 worker instance id
    held_until: str | None = None            # ISO 8601 + 30s TTL
    sync_revision: int = 0                   # 每次写入 +1,客户端增量同步用
```

#### 1.5.3 同步增量(P83-A `/sync` 端点)

```python
@dataclass(frozen=True)
class TriggerDelta:
    """增量同步响应。"""
    since: str                               # 客户端传入的时间戳
    server_time: str
    upserts: list[RegisteredTrigger] = ()    # 新增 / 更新
    tombstones: tuple[str, ...] = ()         # 软删除 id 列表
    full_dump: bool = False                  # 若 since 太旧,触发完整 dump
```

#### 1.5.4 执行结果(P83-C)

```python
@dataclass(frozen=True)
class ExecuteResult:
    trigger_id: str
    worker_endpoint: str
    started_at: str
    finished_at: str
    status: Literal["success", "timeout", "error", "cancelled"]
    output: str = ""
    error: str = ""
    exit_code: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
```

#### 1.5.5 CronTask 兼容扩展(本地)

F-83 不修改 `CronTask` 现有字段,而是新增 `TriggerPayload.from_cron_task(task)` / `CronTask.from_trigger_payload(payload)` 双向转换器,保证远程 trigger 拉取后能合并到本地 `CronScheduler` 的 `due_tasks` 集合。

### 1.6 核心接口

#### 1.6.1 REST API 契约(P83-A)

```python
# extensions/triggers/api.py

from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/v1/triggers", tags=["triggers"])

# ---- POST /v1/triggers(创建 / 更新)----
@router.post("", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    payload: TriggerPayload,
    token: TokenInfo = Depends(require_scope(TriggerScope.WRITE)),
) -> TriggerResponse:
    """Upsert by id. 同一 id + WRITE scope 自动 update。"""

# ---- GET /v1/triggers(列表)----
@router.get("", response_model=list[TriggerResponse])
async def list_triggers(
    status: Literal["active", "deleted", "all"] = "active",
    since: str | None = None,
    limit: int = Query(default=100, le=1000),
    token: TokenInfo = Depends(require_scope(TriggerScope.READ)),
) -> list[TriggerResponse]: ...

# ---- GET /v1/triggers/{id}----
@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(...) -> TriggerResponse: ...

# ---- DELETE /v1/triggers/{id}----
@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(...) -> None:
    """软删除,写 tombstone,30 天后 GC。"""

# ---- GET /v1/triggers/sync(增量同步,worker 用)----
@router.get("/sync", response_model=TriggerDelta)
async def sync_triggers(
    since: str,
    worker_id: str,
    token: TokenInfo = Depends(require_scope(TriggerScope.EXECUTE)),
) -> TriggerDelta: ...

# ---- POST /v1/triggers/{id}/execute(手动 / 远端触发)----
@router.post("/{trigger_id}/execute", response_model=ExecuteResult)
async def execute_trigger(...) -> ExecuteResult: ...

# ---- GET /v1/health(健康检查)----
@router.get("/health")
async def health() -> dict: ...
```

#### 1.6.2 注册表(P83-B + P83-J)

```python
# extensions/triggers/registry.py

class TriggersRegistry:
    """远程 trigger 注册表,持久化到 ~/.clawcodex/triggers.json。"""

    def __init__(self, path: Path, *, lock_path: Path | None = None) -> None: ...

    # CRUD
    def upsert(self, payload: TriggerPayload, *, actor: str) -> RegisteredTrigger: ...
    def get(self, trigger_id: str) -> RegisteredTrigger | None: ...
    def list(self, *, include_deleted: bool = False) -> list[RegisteredTrigger]: ...
    def soft_delete(self, trigger_id: str, *, actor: str) -> bool: ...

    # 增量同步
    def delta_since(self, since: str, *, worker_id: str) -> TriggerDelta: ...

    # 抢占锁(P83-J)
    def acquire_lock(self, trigger_id: str, *, worker_id: str, ttl_seconds: int = 30) -> bool: ...
    def release_lock(self, trigger_id: str, *, worker_id: str) -> bool: ...
    def detect_stale_locks(self) -> list[str]: ...   # 返回过期锁的 trigger id

    # 维护
    def gc_tombstones(self, *, older_than_days: int = 30) -> int: ...
```

#### 1.6.3 执行器协议(P83-C)

```python
# extensions/triggers/executors/base.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class TriggerExecutor(Protocol):
    """执行 trigger 的抽象协议。"""

    kind: Literal["ssh", "rcs", "local"]

    async def execute(
        self,
        payload: TriggerPayload,
        *,
        timeout_seconds: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecuteResult: ...

    async def health_check(self) -> bool: ...

    async def close(self) -> None: ...


# extensions/triggers/executors/ssh.py
class SSHTriggerExecutor:
    """经 asyncssh 在远程 worker 上执行 trigger。

    支持:
      - username/password / 私钥(可指定路径)
      - agent forwarding (SSH_AUTH_SOCK 透传)
      - ProxyJump 跳板
      - keepalive 30s
      - timeout 强杀(SIGTERM → SIGKILL)
    """

    def __init__(
        self,
        *,
        host: str,
        user: str,
        key_path: Path | None = None,
        password: str | None = None,
        port: int = 22,
        forward_agent: bool = False,
        proxy_jump: str | None = None,
    ) -> None: ...


# extensions/triggers/executors/rcs.py
class RCSTriggerExecutor:
    """经 extensions/remote_api/(F-82) HTTP/SSE 调用远端 worker。

    端点:POST /v1/agent/run → SSE → ExecuteResult
    """

    def __init__(
        self,
        *,
        endpoint: str,                       # http://host:port
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None: ...
```

#### 1.6.4 客户端(P83-E + P83-F 共用)

```python
# clawcodex_ext/clients/triggers_client.py

import httpx

class TriggersClient:
    """CLI / Tool 共用的 trigger REST 客户端。"""

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        timeout: float = 10.0,
        retries: int = 2,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def upsert(self, payload: TriggerPayload) -> RegisteredTrigger: ...
    async def list(self, *, status: str = "active") -> list[RegisteredTrigger]: ...
    async def get(self, trigger_id: str) -> RegisteredTrigger | None: ...
    async def delete(self, trigger_id: str) -> bool: ...
    async def execute(self, trigger_id: str) -> ExecuteResult: ...
    async def sync(self, since: str, *, worker_id: str) -> TriggerDelta: ...

    async def close(self) -> None: ...
```

#### 1.6.5 本地-远程桥接(P83-D + P83-K)

```python
# clawcodex_ext/cron_system/remote_bridge.py

class RemoteTriggerBridge:
    """每次 CronScheduler.check_once() 时调用,把远程 trigger 合并到本地 due 集合。"""

    def __init__(
        self,
        *,
        registry_path: Path,                # 本地 ~/.clawcodex/triggers.json 镜像
        remote_endpoint: str | None = None,
        remote_token: str | None = None,
        worker_id: str,
        sync_interval_seconds: float = 30.0,
        drift_threshold_seconds: int = 30,
    ) -> None: ...

    async def sync_once(self) -> int:
        """拉取远程 delta + 写入本地镜像。返回新增 / 更新数。"""

    def merge_into(self, local_due: list[CronTask]) -> list[CronTask]:
        """合并本地 due 与本地镜像中的远程 trigger,去重(按 id)。"""

    def check_drift(self) -> int | None:
        """返回与 server 的时间漂移(秒);None = 未同步。"""

    async def on_fire(self, task: CronTask) -> ExecuteResult:
        """触发执行;优先用 remote_executor(SSH / RCS),本地 trigger 用本地子进程。"""
```

#### 1.6.6 `/triggers` 命令族(P83-E)

```python
# clawcodex_ext/command_system/triggers_command.py

TRIGGERS_COMMAND = Command(
    name="triggers",
    type=CommandType.LOCAL,
    description="Manage remote & local Agent triggers",
    arguments=[
        CommandArgument(name="subcommand", required=False, choices=[
            "create", "list", "show", "delete", "sync", "run-now", "help",
        ]),
        CommandArgument(name="args", required=False, variadic=True),
    ],
    handler=handle_triggers_command,
)
```

子命令契约(节选):

| 子命令 | 语法 | 说明 |
|--------|------|------|
| `create` | `/triggers create <cron> <prompt...> [--remote URL] [--model M] [--max-runtime-ms N]` | 提交 trigger;默认本地,`--remote` 走远端 server |
| `list` | `/triggers list [--remote URL] [--status active\|all]` | 列出 trigger(id / cron / endpoint / next_fire / last_status) |
| `show` | `/triggers show <id> [--remote URL]` | 完整字段 + 最近 5 次执行结果 |
| `delete` | `/triggers delete <id> [--remote URL]` | 软删除 |
| `sync` | `/triggers sync [--remote URL] [--interval N]` | 触发一次增量同步;`--interval` 进入周期同步模式 |
| `run-now` | `/triggers run-now <id> [--remote URL]` | 立即触发执行(不影响 cron schedule) |
| `help` | `/triggers help [subcommand]` | 打印子命令帮助 |

#### 1.6.7 `RemoteTriggerTool`(P83-F,F-71 P71-M)

```python
# clawcodex_ext/tool_system/tools/remote_trigger.py

class RemoteTriggerTool(Tool):
    """AI 可调:在远程 server 上管理 / 触发 trigger。"""

    name = "remote_trigger"
    description = "Create / list / execute remote Agent triggers via REST API."

    async def run(
        self,
        *,
        action: Literal["create", "list", "show", "delete", "execute"],
        trigger_id: str | None = None,
        cron: str | None = None,
        prompt: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        max_runtime_ms: int | None = None,
        tool_context: ToolContext,
    ) -> dict:
        """根据 action 分发到 TriggersClient;空操作走 list。"""
```

### 1.7 安全模型

| 层级 | 机制 | 触发条件 |
|------|------|----------|
| L1 网络层 | HTTPS(生产推荐)/ UDS(本地) | 远端 server 必须支持 TLS 1.3;本地模式走 UDS |
| L1 网络层 | Endpoint allowlist | `~/.clawcodex/triggers/allowlist.json` 显式列出允许的远端 endpoint;不匹配 → 403 |
| L2 鉴权层 | Bearer token | `Authorization: Bearer <token>` 缺失或错误 → 401 |
| L2 鉴权层 | Per-token scope | `read` / `write` / `execute` / `admin`;不匹配 → 403 |
| L2 鉴权层 | Token 轮转 | 30 天自动失效 + 强制轮转 |
| L3 内容层 | Prompt 黑名单 | `rm -rf /`, `mkfs`, `dd if=`, `DROP TABLE`, `kill -9`, `> /dev/sd*` |
| L3 内容层 | PII 扫描 | 检测到 email / 身份证 / 信用卡 → 拒绝并告警 |
| L3 内容层 | Prompt 长度上限 | ≤ 30,000 chars(`_TEXT_MAX` 常量) |
| L3 执行层 | SSH key 权限 | 私钥文件必须 600;否则启动时抛错 |
| L3 执行层 | RCS endpoint 完整性校验 | TLS 证书校验(默认 reject_invalid=True) |
| L3 执行层 | 超时强杀 | `max_runtime_ms` 超时 → SIGTERM → 5s 后 SIGKILL |
| L3 执行层 | 抢占锁 TTL | `held_until` 30s;超时视为 stale,下个 worker 接管 |
| L4 Feature Gate | `AGENT_TRIGGERS_REMOTE=off` | 默认关闭;开启前需用户显式 `/config feature agt_remote=true` |

### 1.8 失败模式与错误分类

| 错误类型 | 触发场景 | 处理策略 |
|----------|----------|----------|
| `AuthError` | 401 / 403(无 token / scope 不足) | 提示检查 `CCR_TOKEN` + `CCR_SCOPE` |
| `EndpointNotAllowedError` | target endpoint 不在 allowlist | 提示用户编辑 `~/.clawcodex/triggers/allowlist.json` |
| `RateLimitError` | server 429 | 退避 60s + 自动重试一次 |
| `TriggerNotFoundError` | get / delete / execute 不存在的 id | 列出当前可用的 id 前 5 个 |
| `LockHeldError` | 抢占锁失败(其他 worker 持有) | 跳过本轮 tick;下一轮重试 |
| `ExecuteTimeoutError` | 远端执行超过 `max_runtime_ms` | 终止 + 写入 audit + 标记 trigger 为 paused |
| `SSHAuthError` | SSH 连接认证失败 | 提示检查 key / agent forwarding |
| `RCSUnavailableError` | 远端 RCS 5xx / unreachable | 退避 30s + 标记 worker 为 OFFLINE(健康检查) |
| `DriftExceededError` | 时钟漂移 > 30s | 告警 + 使用 server `next_fire_time` 校正本地 |
| `StaleLockError` | 抢占锁 TTL 超时但 holder 还活着 | 自动 takeover + 告警原 holder |
| `PromptRejectedError` | 黑名单 / PII / 超长 | 拒绝 trigger 创建,提示用户修改 |

### 1.9 测试策略

| 层级 | 框架 | 覆盖范围 |
|------|------|----------|
| 单元 | pytest | `TriggersRegistry` CRUD + atomic rename + 抢占锁 TTL + drift 计算 |
| 单元 | pytest | `TriggerExecutor` Protocol 三实现 + mock transport |
| 单元 | pytest | `RemoteTriggerBridge.merge_into` 去重合并 |
| 单元 | pytest | `find_ultraplan_trigger_positions` 已存在(沿用 F-87);F-83 新增 `/triggers` 关键字检测 |
| 集成 | pytest + httpx | mock FastAPI server(用 `fastapi.testclient.TestClient`)跑 7 端点 |
| 集成 | pytest + asyncssh | mock SSH server(`asyncssh.create_server`)跑 SSH executor |
| 集成 | pytest + aiohttp | mock RCS server 跑 RCS executor |
| E2E | pytest + 本地 FastAPI + subprocess | 起真实本地 server,worker cron tick 拉 sync → 触发执行 |
| 安全 | 静态 | `grep -E "shell=True" extensions/triggers/` 必须为空 |
| 安全 | 静态 | Prompt 黑名单回归:100 条 fixture(已知危险命令 / PII)必须全部命中 |
| CI | GitHub Actions matrix | `ubuntu-latest` + `macos-latest` + `windows-latest`(WSL)三平台 dry_run |

### 1.10 兼容性矩阵

| 部署模式 | Server | Transport | 鉴权 | 适用场景 |
|----------|--------|-----------|------|----------|
| 嵌入式 | 本地 FastAPI on UDS | UDS | 文件权限(700) | 单机开发 / CI |
| 中心化 | HTTPS + Bearer | HTTPS | Bearer + scope | 团队生产 |
| 中心化 + mTLS | HTTPS + Bearer + client cert | HTTPS | Bearer + scope + mTLS | 高安全要求 |
| Swarm | 无 server,F-85 LAN_PIPES | Pipe IPC | F-85 信任域 | 多机 LAN |
| SSH 远程 | 经 SSH executor 跳板 | SSH + agent forwarding | SSH key | 临时调试 / 无 server 部署 |

## §2 落地步骤

> 顺序原则:先注册表(P83-B)→ REST 端点(P83-A)→ 鉴权(P83-G)→ 客户端(P83-E/F)→ 命令族(P83-E)→ 工具(P83-F)→ 执行器(P83-C/M)→ 桥接(P83-D/K)→ Feature Gate(P83-H)→ 审计(P83-I)→ 测试(P83-L)。

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | `extensions/triggers/models.py` + `registry.py`(JSON + flock + atomic rename + 抢占锁) | P83-B/J | 3-5 天 |
| 2 | `extensions/triggers/server.py` + `api.py` 7 端点 + lifespan + 测试 client | P83-A | 5-7 天 |
| 3 | `extensions/triggers/auth.py`(Bearer + allowlist + scope 检查)+ FastAPI `Depends` 依赖 | P83-G | 2-3 天 |
| 4 | `clawcodex_ext/clients/triggers_client.py`(httpx + 重试 + 错误分类) | P83-E/F | 2-3 天 |
| 5 | `command_system/triggers_command.py` 7 子命令 + `builtins.py` 注册 | P83-E | 3-5 天 |
| 6 | `tool_system/tools/remote_trigger.py` + `tool_registry.register()` | P83-F | 3-5 天 |
| 7 | `extensions/triggers/executors/{base,ssh,rcs,local}.py` + Protocol | P83-C/M | 5-7 天 |
| 8 | `clawcodex_ext/cron_system/remote_bridge.py` 钩子注入 + drift 检测 + 抢占 | P83-D/K | 3-5 天 |
| 9 | `extensions/triggers/audit.py` NDJSON + 轮转 + 钩子 | P83-I | 2-3 天 |
| 10 | F-68 注册 `AGENT_TRIGGERS_REMOTE` + 默认 off + 配置入口 | P83-H | 1 天 |
| 11 | 单元 + 集成 + E2E + 安全回归测试 | P83-L | 5-7 天 |
| 12 | README + 部署指南(Caddy / nginx 反代 + mTLS 教程 + 防火墙模板) | P83-备 | 1-2 天 |

**累计工时**:8-10 周(单人)。

## §3 风险与缓解

| 风险 | 等级 | 缓解措施 |
|------|:----:|----------|
| 远端 server 泄露用户 prompt(含敏感信息) | 🔴 | TLS 1.3 强制 + mTLS 可选 + 端到端加密(可选);审计每日巡检 |
| SSH 私钥泄露(明文存 config) | 🔴 | 私钥路径仅存路径 + 强制 600 权限 + `keyring` 加密存储可选;password 不存盘 |
| 远程 trigger 被恶意 worker 抢占 | 🟠 | 抢占锁 TTL 30s + worker ID 校验 + token 绑定 scope |
| cron 表达式漂移导致重复触发 / 漏触发 | 🟠 | NTP drift 检测 + 使用 server `next_fire_time` 校正 + 抢占锁去重 |
| FastAPI server 暴露端口被扫描攻击 | 🟠 | 默认仅监听 localhost / UDS;外部访问需 Caddy 反代 + 防火墙 |
| Bearer token 硬编码进 git | 🔴 | 文档强制从 env / `~/.netrc` / `keyring` 读;CI 用 `CCR_TOKEN` env;pre-commit 扫 secret |
| RemoteTriggerTool 被滥用为 prompt injection 通道 | 🟠 | 黑名单 + PII 扫描 + scope 限制;LLM 生成的 trigger 创建请求需经用户 confirm |
| 时区不一致导致 cron 表达式误算 | 🟠 | 全部 trigger 强制存 UTC;前端按用户时区展示;漂移检测 |
| mTLS 证书过期 / 吊销 | 🟡 | 启动时校验 + 30 天前告警;健康检查包含证书有效期 |
| 大量 trigger 同步导致 worker 抖动 | 🟡 | 分页 + since 增量 + 30s 同步节流;触发合并去重 |
| `executor.execute` 误用 `shell=True` | 🔴 | 静态检查 `grep -E "shell=True"` 必须为空 |
| 远端 worker 时区与本地不同 | 🟡 | `next_fire_time` 始终使用 UTC ISO 8601;前端渲染时区转换 |

## §4 与其他特性的关系

| 依赖 / 协同 | 说明 |
|-------------|------|
| **F-22 Cron** | F-83 复用 `clawcodex_ext/cron_system/` 11 模块;`remote_bridge.py` 通过钩子扩展 `CronScheduler`,不改其内部 |
| **F-68 Feature Gate** | 注册 `AGENT_TRIGGERS_REMOTE`,默认 off;开启前需用户显式确认 |
| **F-71 P71-M RemoteTriggerTool** | F-83 提供后端 + 协议,F-71 提供 AI 可调入口 |
| **F-82 RCS** | `RCSTriggerExecutor` 直接复用 `extensions/remote_api/` 的 HTTP + SSE;Bearer auth 共享 |
| **F-84 Daemon** | 远端 server 可作为 Daemon Worker(`trigger-server`);本地 worker 可作为 `trigger-worker` |
| **F-85 Pipe IPC** | Swarm 模式(模式 C)复用 `pipe_ipc/transport.py` 作为 trigger 同步 transport |
| **F-87 Ultraplan** | `/ultraplan` 创建的 Plan 可转为 trigger(`@every 5m run plan:<id>`),由 F-83 远程触发 |
| **F-88 Monitor** | 长跑 trigger 可挂到 MonitorPanel 实时观察 |
| **F-89 Proactive** | Proactive Tick 可查询 trigger 列表 + 报告即将触发项 |
| **F-95 Templates** | trigger 模板(refactor / nightly-test / release-check)可由 Templates 注入 |
| **上游 CCB** | 跟踪 CCB `src/commands/triggers.tsx` 的演进 + AGENT_TRIGGERS_REMOTE 协议 |

## §5 验收标准

1. **REST 7 端点全部可用**: `POST/GET/DELETE /v1/triggers`、`GET /v1/triggers/{id}`、`GET /v1/triggers/sync`、`POST /v1/triggers/{id}/execute`、`GET /v1/health`,FastAPI TestClient 全绿;
2. **注册表原子性**: 100 并发 upsert 写入后,JSON 文件 schema 合法,无丢失条目;
3. **抢占锁去重**: 模拟两个 worker 抢同一 trigger,30s 内仅一个 worker 持锁;锁过期后第二个 worker 接管;
4. **增量同步正确性**: 写入 N 条 trigger → 客户端 `since=t0` 拉 sync → 收到 N 条;客户端 `since=t1` 拉 sync(t1 > t0)→ 收到 0 条;
5. **SSH executor 真实执行**: mock SSH server 接收到 `clawcodex-dev trigger run <id>` 命令并返回 exit 0,本地 audit 记录 exit_code;
6. **RCS executor 端到端**: mock RCS server 接收到 POST + SSE 流式回传,本地 ExecuteResult 包含 status=success + output;
7. **命令族完整**: `/triggers create|list|show|delete|sync|run-now|help` 7 子命令全部可用,`--help` 输出符合 `CommandArgument` schema;
8. **`RemoteTriggerTool` 注册**: `tool_registry.list_tools()` 包含 `remote_trigger`,AI 可调用创建 / 列出 / 执行;
9. **Feature Gate**: `AGENT_TRIGGERS_REMOTE=off` 时 `/triggers create --remote` 拒绝并提示开启;env 开启后正常;
10. **审计日志**: 跑一次完整触发后,`~/.clawcodex/triggers/audit/<date>.ndjson` 包含创建 / 执行条目,JSONL 格式正确;
11. **静态安全**: `grep -rE "shell=True" extensions/triggers/` 为空;Prompt 黑名单 100 fixture 100% 命中;
12. **漂移检测**: mock server 时钟 +30s,本地 drift 报告 30,trigger 触发时间校正为 server `next_fire_time`;
13. **测试覆盖**: 单元测试覆盖率 ≥ 85%(cron_system 已 100%,F-83 新增模块不低于同水平);
14. **回归兼容**: cron_system 现有 11 模块 + `tools.py` 4 工具接口 100% 兼容,F-22 现有测试 0 修改通过;
15. **文档完整**: README 提供部署指南(本地嵌入式 / 中心化 HTTPS / Swarm 三模式)+ Bearer token 生成 + mTLS 教程 + 防火墙规则模板。

## §6 后续展望(P84+)

- **P83-N trigger DAG**: 多 trigger 串联(`triggerA.success → triggerB.fire`),实现工作流式调度;
- **P83-O trigger Marketplace**: 用户发布 / 订阅预制 trigger 模板(refactor / nightly-test / release-check);
- **P83-P trigger 回放**: 历史 audit log 可在 TUI 中按时间线回放 + 失败原因聚类;
- **P83-Q Web UI**: 中心化 server 提供 `/admin` Web 页面(FastAPI + Jinja2)用于触发器管理;
- **P83-R 智能调度**: 根据 worker 健康状态 / 负载动态分派 trigger(类似 Kubernetes scheduler);
- **P83-S cross-region replication**: 中心化 server 跨地域同步(`RAFT` 协议),提供 99.99% 可用性。

---

**关联文档**:

- 缺口分析: [gap-analysis-2026q2.md §3.2](./gap-analysis-2026q2.md#f-83-远程-triggersagent_triggers_remote)
- README 索引: [README.md#f-83-远程-triggersagent_triggers_remote](#f-83)
- 现实现代码: `clawcodex_ext/cron_system/`(11 模块) + `extensions/remote_api/`(F-82 RCS) + `clawcodex_ext/tool_system/tools/cron.py`(已注册的 4 个 cron 工具)
- 对标上游: CCB `src/commands/triggers.tsx` + AGENT_TRIGGERS_REMOTE 协议
- 协同特性: F-22 Cron / F-68 Feature Gate / F-71 P71-M / F-82 RCS / F-84 Daemon / F-85 Pipe / F-87 Ultraplan / F-88 Monitor / F-89 Proactive / F-95 Templates
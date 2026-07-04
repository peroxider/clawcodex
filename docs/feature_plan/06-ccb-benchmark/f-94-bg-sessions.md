# F-94: BG_SESSIONS 后台会话

> 状态: 🚧 实现中(P94-A~F+H 已落地;P94-G Team/SendMessage 集成待 F-93 协同;完成事件主动推送待后续)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-94-bg-sessions.md`
> 最后更新: 2026-07-02
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-94: BG_SESSIONS 后台会话统一管理`,已分解到本文档 §0)

## 落地清单(2026-07-02)

| 子特性 | 文件 | 状态 |
|:----:|------|:----:|
| P94-A 数据模型 | `clawcodex_ext/tasks/bg_session.py` | ✅ |
| P94-B 全局 registry | `clawcodex_ext/tasks/bg_session_registry.py` | ✅ |
| P94-C 生命周期控制 | `clawcodex_ext/tasks/bg_session_manager.py` | ✅ |
| P94-D 多信号 orphan 检测 | `clawcodex_ext/tasks/bg_session_health.py` | ✅ |
| P94-E1 BgSessionTool | `clawcodex_ext/tool_system/tools/bg_session.py` | ✅ |
| P94-E2 /bg 命令族 | `clawcodex_ext/command_system/bg_commands.py` | ✅ |
| P94-F UI 显示适配器 | `clawcodex_ext/repl/bg_sessions_panel.py` | ✅ |
| P94-B/C launch 协调 | `clawcodex_ext/tasks/bg_session_hook.py` + `clawcodex_ext/__init__.py` 猴补丁 | ✅ |
| P94-G Team/SendMessage 集成 | — | ⏳ 待 F-93 |
| P94-H 单元测试 | `tests/clawcodex_ext/tasks/test_bg_session.py`(35 用例) | ✅ |

接入点:
- `extensions/tool_system_ext/registration.py` — BgSessionTool 注册到 EXTENSION_TOOLS
- `clawcodex_ext/command_system/builtins.py:register_builtin_commands` — /bg 命令注册
- `clawcodex_ext/__init__.py:ensure_eager_extensions_installed` — launch_background_runner 包装钩子

验收标准 §1.11 全部 10 项由 `tests/clawcodex_ext/tasks/test_bg_session.py` 覆盖。

---

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-94 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

充分的基础设施已具备,但**零散后台能力未整合**:

- 已有 `clawcodex_ext/agent/background_runner.py:launch_background_runner`(fork / subprocess / Windows `PYTHONUTF8=1` fallback)+ `.background-runner.json` marker 写入 `~/.clawcodex/sessions/<id>/` + `_run_agent_headless()` 子进程循环 + PID 存活检查;
- 已有 `clawcodex_ext/agent/background_state.py:background_signal` 单例;
- 已有 `clawcodex_ext/tasks_core.py:TaskType`(local_bash / local_agent / remote_agent / in_process_teammate / local_workflow / monitor_mcp / dream)与 `TaskStatus`(pending / running / completed / failed / killed);
- 已有 `clawcodex_ext/task_registry.py:RuntimeTaskRegistry`(RLock + sync-only `update()` mutator 约束);
- 已有 `ResumeAgent` / `TaskOutput` / `TaskStop` 给 BG session 输出/停止语义;

完全缺失:

- 全局 `~/.clawcodex/bg_sessions/index.json` 索引(per-session `.background-runner.json` 是单 session marker,不是全局 index);
- 按 workspace / team / user 列出后台会话;
- foreground ↔ background 统一状态机;
- 多信号 orphan 检测(PID + marker + transcript mtime + lock);
- 跨进程 discover;
- 面向 Agent 的 `BgSessionTool` 与面向用户的 `/bg` 命令族;
- TUI footer 显示当前 workspace 的 running BG sessions 数。

### 0.2 对标

- CCB `BG_SESSIONS` 全局 index + 多信号 orphan 检测;
- CCB `/bg list|inspect|attach|stop|cleanup` 完整命令族;
- CCB session 自动转 background / 跨进程 discover / 状态合并 / UI footer;
- CCB 拒绝跨 workspace 默认 attach,需 `--all` 显式开启;
- CCB `bg_sessions=off` 时全局 index 不写,仅保留 per-session marker 行为。

### 0.3 解耦落地路径(`clawcodex_ext/tasks/bg_session.py` 目标,不动现有 `background_runner`)

- `models.py` — `BgSession` / `BgSessionEvent` / `BgSessionConfig`;
- `registry.py:BgSessionRegistry` — 扫描 `~/.clawcodex/sessions/*` + 重建 index;
- `manager.py:BgSessionManager` — list / inspect / attach / resume / stop / cleanup / background_current_session;
- `health.py:bg_session_health` — PID+marker+transcript mtime 多信号 orphan 检测;
- `bg_session_events.py` — event log + notification helpers;
- `clawcodex_ext/tool_system/tools/bg_session.py` — `BgSessionTool` 给 Agent;
- `clawcodex_ext/command_system/bg_commands.py` — `/bg` 命令族;
- `clawcodex_ext/tui/bg_sessions_panel.py` — TUI footer 显示后台 session 数;
- 与 `launch_background_runner()` 协调,marker 写完顺手 upsert 到 index。

### 0.4 依赖

- 现有 `background_runner.py` / `background_state.py` / `tasks_core.py` / `task_registry.py` / `ResumeAgent`;
- F-99 DIRECT_CONNECT(共享 session_id 命名空间,通过 `source=bg_session` 区分);
- F-98 SSH_REMOTE(远端 BG session marker 通过 sftp 拉取);
- F-82 Remote Control(可选 dashboard 集成);
- F-93 TeamMem(后台 agent 恢复时读取 TeamMem,避免丢失团队上下文)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `BG_SESSIONS` 能力,把 ClawCodex 当前零散的后台 agent / background runner / task registry 能力整合为统一的“后台会话”系统。用户或上层 Agent 可以把一个会话放入后台继续执行,随后列出、检查、附加、恢复、终止或清理这些后台会话,并在 TUI / REPL / headless / Team 模式下获得一致的状态语义。

F-94 重点解决“后台任务”和“可恢复会话”之间的产品层断裂:现有代码能 fork/headless 运行并写 marker,但缺少统一 registry、跨进程 discover、session 状态模型、CLI/Tool API 与 orphan cleanup。

### 1.2 背景

现有实现基线:

1. `clawcodex_ext/agent/background_runner.py` 已支持 `launch_background_runner()`、`.background-runner.json` marker、PID 存活检查、`wait_for_background_runner()` 与 cleanup;
2. `clawcodex_ext/agent/background_state.py` 保留 process-level background signal 状态;
3. `clawcodex_ext/tasks_core.py` 已定义 `TaskType` / `TaskStatus` 与 `RuntimeTaskRegistry` 基础;
4. `src/tasks/local_agent.py` 与 `clawcodex_ext/agent/resume_agent.py` 已提供 local agent 恢复/消息注入能力;
5. `TaskOutput` / `TaskStop` / task notification 已提供后台 task 的输出读取与停止语义;
6. TUI/REPL 已有 background escape 与 task list UI 相关原语。

缺口在于:

- `.background-runner.json` 是 per-session marker,不是全局可查询的 BG session index;
- 只能“知道某 session 是否有 runner”,不能按 workspace/team/user 列出所有后台会话;
- foreground ↔ background 切换缺少统一状态机;
- 后台会话死亡、孤儿进程、marker stale、transcript 停止增长等异常缺少统一 repair/cleanup;
- 缺少面向 Agent 的 `BgSessionTool` 与面向用户的 `/bg` 命令族。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P94-A | 数据模型(`BgSession`, `BgSessionStatus`, `BgSessionEvent`) | 1 天 |
| P94-B | 全局 registry(`BgSessionRegistry`):扫描 `~/.clawcodex/sessions/*` + index.json | 2 天 |
| P94-C | 生命周期控制(`BgSessionManager`):background/list/attach/resume/stop/cleanup | 2 天 |
| P94-D | 健康检查与 orphan cleanup:PID、marker、transcript mtime、lock | 1 天 |
| P94-E | Tool/CLI 接入:`BgSessionTool` + `/bg` 命令族 | 1 天 |
| P94-F | UI 集成:TUI footer/status/task list 显示后台会话 | 1 天 |
| P94-G | Team/SendMessage 集成:后台 session 可接收队列消息 | 1 天 |
| P94-H | 单元 + 集成测试 | 2 天 |

**估算总工时**:1 周。

### 1.4 架构设计

```
Foreground session
  ├─ TUI Ctrl+B / REPL command / Agent tool
  └─ launch_background_runner(session, ...)
             │
             ▼
Background runner process
  ├─ writes transcript JSONL
  ├─ updates .background-runner.json
  └─ emits completion marker
             │
             ▼
BgSessionRegistry
  ├─ scans ~/.clawcodex/sessions/*/.background-runner.json
  ├─ merges runtime task registry state
  ├─ validates PID / transcript / lock
  └─ persists ~/.clawcodex/bg_sessions/index.json
             │
             ▼
BgSessionManager
  ├─ list/status/attach/resume/stop/cleanup
  ├─ task notifications
  ├─ CLI/TUI integration
  └─ Team/Agent message routing
```

#### 包结构

```
clawcodex_ext/tasks/
├── bg_session.py                  # P94-A/B/C: models + registry + manager
├── bg_session_health.py           # P94-D: stale/orphan detection
└── bg_session_events.py           # event log + notification helpers

clawcodex_ext/tool_system/tools/
└── bg_session.py                  # P94-E: BgSessionTool

clawcodex_ext/command_system/
└── bg_commands.py                 # P94-E: /bg command family

clawcodex_ext/repl/
└── bg_sessions_panel.py           # P94-F: REPL/TUI display adapter

tests/clawcodex_ext/tasks/
├── test_bg_session_registry.py
├── test_bg_session_manager.py
├── test_bg_session_health.py
└── test_bg_session_tool.py
```

### 1.5 核心数据模型

```python
BgSessionStatus = Literal[
    "starting",
    "running",
    "paused",
    "completed",
    "failed",
    "stopped",
    "orphaned",
    "unknown",
]


@dataclass(frozen=True)
class BgSession:
    id: str                                # session_id 或 stable bg id
    session_id: str
    workspace_root: Path
    status: BgSessionStatus
    pid: int | None = None
    task_id: str | None = None
    team_id: str | None = None
    agent_name: str | None = None
    description: str = ""
    transcript_path: Path | None = None
    marker_path: Path | None = None
    output_file: Path | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    last_activity_at: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class BgSessionEvent:
    id: str
    bg_session_id: str
    event_type: Literal[
        "created", "backgrounded", "attached", "resumed", "stopped",
        "completed", "failed", "orphaned", "cleaned"
    ]
    actor: str
    message: str
    created_at: str


@dataclass(frozen=True)
class BgSessionConfig:
    enabled: bool = False
    index_path: Path = Path("~/.clawcodex/bg_sessions/index.json")
    stale_after_seconds: int = 600
    max_sessions: int = 200
    cleanup_completed_after_seconds: int = 86_400
    allow_agent_attach: bool = True
```

### 1.6 核心接口

```python
class BgSessionRegistry:
    """跨进程后台会话索引。"""

    def __init__(self, *, config: BgSessionConfig) -> None: ...

    def scan(self) -> list[BgSession]:
        """扫描 sessions 目录并重建 registry view。"""

    def list(self, *, workspace_root: Path | None = None) -> list[BgSession]: ...

    def get(self, bg_session_id: str) -> BgSession | None: ...

    def upsert(self, session: BgSession) -> None: ...

    def remove(self, bg_session_id: str) -> bool: ...

    def save(self) -> Path: ...


class BgSessionManager:
    """统一后台会话生命周期控制。"""

    def __init__(
        self,
        *,
        registry: BgSessionRegistry,
        runtime_tasks: RuntimeTaskRegistry | None = None,
    ) -> None: ...

    def background_current_session(self, ctx: BackgroundContext) -> BgSession: ...

    def list_sessions(self, *, include_completed: bool = False) -> list[BgSession]: ...

    def inspect(self, bg_session_id: str) -> BgSession: ...

    def attach(self, bg_session_id: str, *, follow: bool = True) -> BgSession: ...

    def stop(self, bg_session_id: str, *, force: bool = False) -> BgSession: ...

    def cleanup(self, *, include_failed: bool = False) -> list[BgSessionEvent]: ...
```

### 1.7 状态机

```
starting
  ├─ runner marker written + pid alive ─────▶ running
  ├─ launch failed ─────────────────────────▶ failed
  └─ marker stale before pid visible ───────▶ unknown

running
  ├─ user attach/resume ────────────────────▶ paused/attached foreground view
  ├─ completion marker ─────────────────────▶ completed
  ├─ child exit non-zero / error marker ────▶ failed
  ├─ pid gone but no completion marker ─────▶ orphaned
  └─ user stop ─────────────────────────────▶ stopped

orphaned
  ├─ transcript indicates completion ───────▶ completed
  ├─ cleanup removes marker ────────────────▶ stopped
  └─ user attach with transcript only ──────▶ paused
```

状态判断优先级:

1. 显式 marker `status=completed|failed` 优先;
2. `status=running` 时检查 PID 是否存活;
3. PID 不存活时检查 transcript 是否有 completion marker;
4. transcript mtime 长时间不变但 PID 存活时标记 stale warning,不立即失败;
5. 任何不确定状态都应返回 `unknown` 或 `orphaned`,不得静默删除。

### 1.8 Tool / CLI 行为

#### BgSessionTool

| action | 输入 | 输出 |
|--------|------|------|
| `list` | `include_completed`, `workspace_only` | sessions summary |
| `inspect` | `bg_session_id` | status + pid + transcript + last activity |
| `attach` | `bg_session_id`, `follow` | attach metadata / transcript tail |
| `stop` | `bg_session_id`, `force` | stopped session status |
| `cleanup` | `include_failed` | cleanup event list |

#### `/bg` 命令族

```
/bg list
/bg inspect <session-id>
/bg attach <session-id>
/bg stop <session-id>
/bg cleanup
/bg logs <session-id> --tail 100
```

UI 规则:

- TUI footer 显示当前 workspace 的 running BG sessions 数量;
- task list 中把 background shell、local agent 与 BG session 分组显示;
- completion notification 应包含 `session_id` 与恢复命令;
- attach 前如果会切换当前 foreground conversation,需要明确提示用户。

### 1.9 安全与权限

| 场景 | 规则 |
|------|------|
| `BG_SESSIONS=off` | 不创建全局 index,仅保留现有 marker 行为 |
| attach 其他 workspace session | 默认拒绝;需要显式 `--all` 或配置允许 |
| stop/kill session | 先尝试 graceful SIGTERM / task kill,force 才 SIGKILL |
| stale marker | 不自动删除,先标记 orphaned,cleanup 才移除 |
| transcript path | 必须限制在 `~/.clawcodex/sessions/<id>/` 下 |
| Team session | 只有 team lead 或 session owner 可 stop;member 可 inspect 自己可见的 session |

### 1.10 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `BgSessionsDisabledError` | feature flag off | Tool 返回 disabled + fallback 到 TaskList |
| `BgSessionNotFoundError` | session id 不存在 | 返回可用 session 列表摘要 |
| `BgSessionAlreadyRunningError` | 同一 session 重复 background | 返回现有 pid/session |
| `BgSessionAttachError` | transcript 缺失或格式损坏 | 提示 inspect/log 路径,不清理 |
| `BgSessionPermissionError` | 跨 workspace/team 越权 | 拒绝并记录 audit |
| `BgSessionOrphanedError` | pid gone + no completion marker | 标记 orphaned,允许 cleanup |
| `BgSessionStopError` | kill 失败 | 保留 running/orphaned 状态和错误原因 |

### 1.11 验收标准

1. `BG_SESSIONS=off` 时不写 `~/.clawcodex/bg_sessions/index.json`;
2. 一个 session background 后,`/bg list` 能列出 session_id、pid、workspace、status;
3. 后台 runner 完成后,status 从 `running` 变为 `completed`;
4. PID 消失但无 completion marker 时,status 变为 `orphaned`,不会被静默删除;
5. `/bg attach <id>` 能 tail transcript 并给出恢复路径;
6. `/bg stop <id>` 先 graceful stop,失败时需要用户显式 force;
7. 跨 workspace attach 默认拒绝;
8. 100 个历史 session scan < 100ms;
9. 单元测试覆盖 registry scan、状态机、orphan cleanup、权限拒绝、stop 行为;
10. index.json 损坏时通过 `~/.clawcodex/sessions/*` 重建 + audit 记录恢复过程。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 定义 `BgSession` 数据模型与状态机 | P94-A | 1 天 |
| 2 | 实现 `BgSessionRegistry.scan()` 读取 marker/transcript | P94-B | 1.5 天 |
| 3 | 实现 `BgSessionManager` list/inspect/attach/stop/cleanup | P94-C/D | 2 天 |
| 4 | 接入现有 `launch_background_runner()` 写全局 index | P94-B/C | 1 天 |
| 5 | 增加 `BgSessionTool` 与 `/bg` 命令族 | P94-E | 1 天 |
| 6 | 增加 TUI/REPL 状态展示与 completion notification | P94-F | 1 天 |
| 7 | 接入 Team 权限与 SendMessage 队列提示 | P94-G | 0.5 天 |
| 8 | 补齐测试与 fixture | P94-H | 2 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| stale marker 导致误判 running | 🟠 | PID + transcript marker + mtime 多信号判定 |
| 错杀非 ClawCodex 进程 | 🔴 | PID 校验 command/session marker,force 需显式确认 |
| 跨 workspace 泄漏 transcript | 🔴 | workspace scope 校验 + path containment |
| Windows fork 行为差异 | 🟡 | subprocess runner 已有 fallback,F-94 只依赖 marker 协议 |
| index 与真实 session 目录不一致 | 🟡 | `scan()` 为事实源,index 仅缓存 |
| 与 TaskList 语义重复 | 🟡 | TaskList 管运行时 task,BG_SESSIONS 管可恢复会话 |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-89 Proactive** | proactive tick 可检查 BG session completion,但不能自动 attach |
| **F-93 TeamMem** | 后台 session 恢复时可注入 team memory 相关上下文 |
| **F-85 Pipe IPC** | 后续可通过 UDS/LAN 向后台 session 发送控制消息 |
| **F-82 Remote Control** | 远程控制可查看/attach 远端 BG session |
| **F-98 SSH_REMOTE** | SSH remote 下 BG session registry 需要远端路径 adapter |
| **TaskOutput/TaskStop** | 保持兼容;BG session tool 可复用 task output/stop 能力 |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-93 TeamMem](./f-93-team-memory.md)

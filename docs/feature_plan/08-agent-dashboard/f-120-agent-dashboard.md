# F-120: Agent Dashboard — 跨系统任务进度统一看板

> 状态: 🚧 进行中 (Phase 1-4 完成)
> 章节: `docs/feature_plan/08-agent-dashboard/f-120-agent-dashboard.md`
> 最后更新: 2026-07-09

## §1 概述

### 1.1 目标

构建一个**跨系统、只读聚合**的 Agent Dashboard，让用户、Agent（模型）、Operator 都能通过统一的视图查看当前所有 agent loop 相关的任务执行进度。

**核心定位**：数据聚合层 + 契约接口，**不做独立渲染**。渲染由已有消费端（TUI `/dashboard` 命令、Visualizer Web UI、Model Tools）各自完成。

### 1.2 解决的问题

当前各子系统的进度数据**彼此隔离**：

| 子系统 | 状态存储 | 能否被模型读取 | 能否被用户查看 |
|--------|---------|---------------|---------------|
| `/goal` 目标 | `GoalStateRegistry` | ✅ Goal("get") | ✅ /goal status |
| Agent Tasks (Task* 工具) | `ToolContext.tasks` | ✅ TaskList | ❌ 无用户命令，仅 transcript 可见 |
| Orchestrator 流水线 | `StatusDashboard` / `IssueRegistry` | ❌ 无工具 | ✅ `issue tail` + Web 看板 |
| SOP Converter 工作流 | 内部状态 | ❌ 无工具 | ❌ 无统一入口 |

Agent Dashboard 在它们之上建立一个**统一的只读聚合窗口**，不替代各自的数据管理机制。

### 1.3 与现有 Dashboard 的关系

| 已有组件 | 关系 |
|---------|------|
| **Orchestrator StatusDashboard** (`extensions/orchestrator/status_dashboard.py`) | 既是**数据源**（暴露 pipeline 状态给 Dashboard），也是**消费者**（可选读取 Dashboard 丰富终端显示）。保持其作为专门运维视图的定位不变 |
| **Visualizer** (`extensions/visualizer/`) | **主要 Web 渲染出口**。Dashboard 提供数据 + API 路由，Visualizer 新增 tab 页面 |
| **Agent Dashboard（新）** | **不做独立渲染**。核心是一个存储 + 数据源注册机制 + Protocol 契约，由消费端决定如何展示 |

```
                   ┌─── 终端 TUI  ──┐
                   │ /dashboard     │
                   │ StatusDsh (ext)│
                   └──────┬─────────┘
                          │ 拉取
                    ┌─────▼──────────┐
 ┌──────────┐       │  Agent        │      ┌──────────────┐
 │GoalState │──────►│  Dashboard    │─────►│ Model Tools  │
 │Registry  │ pull   │  Store        │ serve │ DashboardGet │
 └──────────┘       │  (聚合+NDJSON) │      │ DashbrdList  │
                    │                │      └──────────────┘
 ┌──────────┐       │  数据契约:     │
 │ToolCtx   │──────►│  Dashboard     │      ┌──────────────┐
 │.tasks    │ pull   │  Entry 统一    │─────►│ Visualizer   │
 └──────────┘       │  模型          │ push  │ (Web UI 新tab)│
                    └──────▲─────────┘      └──────────────┘
 ┌──────────┐              │
 │Orchestr  │──────────────┘
 │.status   │  pull (可选)
 └──────────┘
```

## §2 数据模型

### 2.1 DashboardEntry（统一条目类型）

```python
# extensions/capabilities/dashboard_entry.py

@dataclass
class DashboardEntry:
    """一条看板条目。统一所有子系统的进度数据形状。"""

    id: str                                    # 全局唯一 ID
    source: str                                # "goal" | "task" | "orchestrator" | "sop"
    source_session_id: Optional[str]           # session_id（按 session 聚合时使用）
    title: str                                 # 条目标题
    status: str                                # pending / in_progress / completed / failed / blocked
    progress_pct: Optional[float]              # 0.0 ~ 1.0，null 表示未知
    detail: str                                # 详情/摘要文本
    parent_id: Optional[str]                   # 层级关系（树形渲染用）
    order: int                                 # 排序权重
    tags: list[str]                            # 自定义标签 e.g. ["high-priority", "blocked"]
    owner: Optional[str]                       # 负责人标识
    updated_at_ms: int                         # 最后更新时间
```

### 2.2 DashboardSource（数据源契约）

```python
# extensions/capabilities/dashboard_source.py

class DashboardSource(Protocol):
    """每个子系统实现此 Protocol 向 DashboardStore 提供条目。"""

    @property
    def source_name(self) -> str: ...
    """唯一标识，如 "goal" / "task" / "orchestrator" / "sop" """

    def pull(self, **filters) -> list[DashboardEntry]:
        """返回当前所有条目的快照。filters 可选（按 session_id / status 筛选）。"""

    @property
    def cache_ttl_ms(self) -> int:
        """缓存有效期毫秒。高频数据（tasks）可设短 TTL，低频数据（sop）可设长 TTL。"""
        return 5000  # 默认 5s
```

### 2.3 DashboardStore（聚合存储）

```python
# extensions/agent_dashboard/store.py

class DashboardStore:
    """聚合存储。不负责渲染，只负责聚合和投递。"""

    def register_source(self, source: DashboardSource) -> None: ...
    def unregister_source(self, source_name: str) -> None: ...

    def snapshot(self, *, filters: Optional[dict] = None) -> list[DashboardEntry]:
        """从所有注册的数据源拉取最新状态，合并后返回。结果自带缓存。"""

    def get_by_source(self, source: str, **filters) -> list[DashboardEntry]:
        """按 source 过滤。消费者只取自己关心的分区。"""

    def get_by_id(self, entry_id: str) -> Optional[DashboardEntry]: ...

    def subscribe(self, sink: Callable[[list[DashboardEntry]], None]) -> None:
        """注册消费者回调（Visualizer WebSocket、TUI 渲染器等）。
        每次 snapshot 变动时自动推送给所有 sink。"""
```

持久化：按 source 分文件写入 `~/.clawcodex/dashboard/` 目录 NDJSON，每条记录包含全量 `DashboardEntry` + timestamp。

## §3 数据源适配

### 3.1 GoalSource

读取 `GoalStateRegistry`，将每个 session 的活跃 `GoalState` 转换为一条 `DashboardEntry`。

- source = `"goal"`
- status 直接映射 `GoalStatus` 枚举
- progress_pct = `tokens_used / token_budget`（当 budget 存在时）
- 不包含子目标/里程碑（此特性规划中不涉及）

```python
class GoalDashboardSource:
    source_name = "goal"

    def pull(self) -> list[DashboardEntry]:
        registry = get_goal_registry()
        entries = []
        for sid, state in registry.iter_states():
            entries.append(DashboardEntry(
                id=f"goal:{sid}",
                source="goal",
                source_session_id=sid,
                title=state.objective,
                status=state.status.value,
                progress_pct=(
                    state.tokens_used / state.token_budget
                    if state.token_budget else None
                ),
                detail=format_status_for_display(state),
                updated_at_ms=state.updated_at_ms,
            ))
        return entries
```

### 3.2 TasksSource

读取 `ToolContext.tasks`，将每个 task dict 转换为 `DashboardEntry`。需要从 ToolContext 或 session 获取上下文。

- source = `"task"`
- status 直接映射 task.status
- parent_id 利用 task 中的 `goal_id` 等关联字段（可选，在调度阶段无需实现）

```python
class TasksDashboardSource:
    source_name = "task"

    def pull(self, tool_context: ToolContext) -> list[DashboardEntry]:
        return [
            DashboardEntry(
                id=f"task:{tid}",
                source="task",
                title=t.get("subject", ""),
                status=t.get("status", "pending"),
                detail=t.get("description", ""),
                tags=list(t.get("tags", [])),
                owner=t.get("owner"),
                updated_at_ms=t.get("updated_at_ms", 0),
            )
            for tid, t in (tool_context.tasks or {}).items()
        ]
```

### 3.3 OrchestratorSource

读取 `StatusDashboard.state()` + `IssueRegistry`，将 orchestrator 的 issue 处理状态转换为 `DashboardEntry`。

- source = `"orchestrator"`
- 可选对接，默认不启用（需要 orchestrator 组件存在）
- 运行中 session → `in_progress`，已完成 → `completed`，失败 → `failed`

### 3.4 SOPSource

读取 SOP Converter 当前阶段执行状态，转换为 `DashboardEntry`。

- source = `"sop"`
- 可选对接，默认不启用
- 每个阶段一条，`parent_id` 表达阶段间的顺序关系

### 3.5 注册中心

```python
# extensions/agent_dashboard/source_registry.py

_SOURCES: dict[str, DashboardSource] = {}

def register_dashboard_source(source: DashboardSource) -> None: ...
def unregister_dashboard_source(name: str) -> None: ...
def get_registered_sources() -> dict[str, DashboardSource]: ...
```

## §4 消费端

### 4.1 终端 TUI — `/dashboard` 斜杠命令

**输入**：`/dashboard`（当前摘要）、`/dashboard goal`（只查看 goal 分区）、`/dashboard task`（只查看 task 分区）

**输出**（Rich markup + 分区布局）：

- 顶部摘要栏：source 统计计数
- 分区区块，每个 source 一个，用分隔线隔开
- 树形缩进表达层级关系
- 图标：`✓ ◼ ◻ ✕ ◆ ⏳ 🔄`
- 交互（仅 TTY 模式）：上下滚动、按 source/status 过滤、展开/折叠、刷新

**实现位置**：新增 `clawcodex_ext/command_system/dashboard_command.py`，风格复用 `_render_task_snapshot()` 的 Rich markup 模式。

### 4.2 Web UI — Visualizer 看板 Tab

**新增路由**：`/api/dashboard/snapshot`（JSON 输出）、`/ws/dashboard/live`（WebSocket 实时推流）

**新增页面**：`visualizer/templates/agent_dashboard_tab.html`

- 统计卡片（按 source/status 聚合的计数）
- 分 source 展示的折叠面板
- 搜索/过滤栏
- 自动刷新（3s 轮询或 WebSocket 推流）

### 4.3 Agent 侧 — Model Tools

```python
DashboardGet = build_tool(
    name="DashboardGet",
    input_schema={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["goal", "task", "orchestrator", "sop", "all"],
                "default": "all",
            },
            "entry_id": {"type": "string"},
        },
        "required": ["entry_id"],
    },
    # 返回单条 DashboardEntry
)

DashboardList = build_tool(
    name="DashboardList",
    input_schema={
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["goal", "task", "orchestrator", "sop", "all"],
                "default": "all",
            },
            "status": {"type": "string"},
        },
    },
    # 返回 list[DashboardEntry]
)
```

**只读** — Agent 可通过 Dashboard 观察全局进度，但不能通过 Dashboard 写入。Agent 仍然使用 `Task*` / `Goal` 工具进行写入操作。

### 4.4 工具分工对比

| 场景 | 使用工具 |
|------|---------|
| Agent 创建子任务 | `TaskCreate`（写） |
| Agent 更新任务状态 | `TaskUpdate`（写） |
| Agent 查看自己手头的任务 | `TaskList`（读自己的） |
| Agent 查看全局进度（goal/orch/SOP） | `DashboardList("all")`（读全系统） |
| Agent 查看某个具体条目详情 | `DashboardGet(entry_id)`（读单条） |

## §5 实现阶段

### Phase 1 — Protocol 和数据模型

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `extensions/capabilities/dashboard_entry.py` | `DashboardEntry` dataclass + `DashboardSource` Protocol | ~80 |
| `extensions/capabilities/__init__.py` | 导出新 Protocol | ~5 |

无运行时代码，纯接口定义。

### Phase 2 — 聚合存储 + Goal/Tasks 数据源

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `extensions/agent_dashboard/__init__.py` | 包入口 | ~10 |
| `extensions/agent_dashboard/store.py` | `DashboardStore`（聚合 + NDJSON 归档 + 缓存 + sink 注册） | ~180 |
| `extensions/agent_dashboard/source_registry.py` | 数据源注册中心 | ~40 |
| `extensions/agent_dashboard/sources/__init__.py` | 数据源包入口 | ~10 |
| `extensions/agent_dashboard/sources/goal_source.py` | `GoalDashboardSource` | ~60 |
| `extensions/agent_dashboard/sources/tasks_source.py` | `TasksDashboardSource` | ~50 |

此时 `/goal` 和 Agent Tasks 的进度已自动出现在 DashboardStore 中。

### Phase 3 — 终端渲染

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `clawcodex_ext/command_system/dashboard_command.py` | `/dashboard` 斜杠命令 + Rich 渲染 | ~250 |

`/dashboard` 可用，TUI 模式支持交互操作。

### Phase 4 — Agent 侧工具

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `extensions/agent_dashboard/tools/dashboard_get.py` | `DashboardGet` 工具 | ~80 |
| `extensions/agent_dashboard/tools/dashboard_list.py` | `DashboardList` 工具 | ~100 |

模型可通过工具读取 Dashboard。

### Phase 5 — Web 渲染（可选）

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `extensions/visualizer/server.py` | 新增 `/api/dashboard/*` 路由 | ~50 |
| `extensions/visualizer/ws.py` | 新增 `DashboardLiveTail` WebSocket | ~80 |
| `extensions/visualizer/templates/agent_dashboard_tab.html` | 看板页面模板 | ~200 |

### Phase 6 — Orchestrator/SOP 数据源（可选）

| 文件 | 内容 | 预计行数 |
|------|------|---------|
| `extensions/agent_dashboard/sources/orchestrator_source.py` | `OrchestratorDashboardSource` | ~60 |
| `extensions/agent_dashboard/sources/sop_source.py` | `SOPDashboardSource` | ~60 |

## §6 设计决定

### D1. 只读聚合，不写回源头

Dashboard 对所有消费者（包括 Agent）**只读**。任何写入操作（创建任务、更新状态、修改目标）仍然走各自子系统的既有入口（`TaskCreate`、`Goal("update")`、`/goal`）。这避免了写冲突和双向反馈环。

### D2. 不做独立渲染

Agent Dashboard 不包含自有的 Web 服务器、模板引擎、终端循环。全部渲染由现存的消费端（`StatusDashboard`、`Visualizer`、`REPL`）完成。Dashboard 只提供数据。

### D3. Orchestrator StatusDashboard 保持独立

`StatusDashboard` 保留其作为专门运维视图的定位。它可以选择性地作为数据源之一暴露给 Agent Dashboard，也可选地作为消费者读取 Dashboard 来丰富自己的终端行显示，但不是强制绑定。

### D4. NDJSON 持久化

`~/.clawcodex/dashboard/` 目录下按 source 分文件写入 NDJSON，便于 Visualizer 文件系统读取和历史追溯。写入采用 O_APPEND + 异步 flush，不阻塞拉取循环。

### D5. 缓存与 TTL

每个数据源声明自己的 `cache_ttl_ms`，`DashboardStore.snapshot()` 按 TTL 判断是否需要重新 pull。高频数据（tasks，~轮次级更新）短 TTL，低频数据（sop 阶段，~分钟级更新）长 TTL。

### D6. 不包含子目标/里程碑

本特性规划不涉及 `/goal` 的子目标分解或里程碑管理。`GoalDashboardSource` 只暴露 `GoalState` 顶层信息。子目标/里程碑是独立于 Dashboard 的功能特性，如有需要应另行规划。

## §7 验收标准

- [x] Phase 1: `DashboardEntry` + `DashboardSource` Protocol 定义完成
- [x] Phase 2: `DashboardStore` 启动后自动从 `GoalService` 和 `ToolContext.tasks` 拉取数据
- [x] Phase 2: NDJSON 归档写入正常
- [x] Phase 3: `/dashboard` 命令在 REPL 中可执行，显示分区视图
- [x] Phase 3: 命令支持 source 过滤（`/dashboard goal`、`--status S`、`--id ID`）
- [x] Phase 4: Agent 可通过 `DashboardList("all")` 读取跨系统聚合数据
- [x] Phase 4: Agent 不可通过 Dashboard 写入（验证 is_read_only）
- [ ] Phase 3: TTY 模式下支持上下滚动（后续 TUI 子类化 `DashboardCommand`）
- [ ] Phase 5（可选）: Visualizer 新增 Agent Dashboard tab
- [ ] Phase 6（可选）: Orchestrator 和 SOP 数据源注册后自动出现在看板
- [x] 所有新增测试通过（98 个测试，回归无新增失败）

## §8 依赖与协同

| 依赖 | 关系 |
|------|------|
| `clawcodex_ext/goal/` — `GoalStateRegistry` | Goal 数据源拉取目标 |
| `clawcodex_ext/tool_system/context.py` — `ToolContext.tasks` | Tasks 数据源拉取任务 |
| `extensions/orchestrator/status_dashboard.py`（可选） | Orchestrator 数据源 |
| `extensions/sop_converter/`（可选） | SOP 数据源 |
| `extensions/visualizer/`（可选） | Web 渲染出口 |
| `clawcodex_ext/repl/core.py` — `_render_task_snapshot` | 终端渲染风格参考 |
| 不依赖 | 不和 `TodoWrite`、`Task*` 工具做代码层面的双向绑定。Dashboard 只读 tasks，不写入 |

## §9 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-29 | 初始创建 | 基于架构讨论结论落地 |
| 2026-07-09 | Phase 1-4 实现 + 98 个测试通过 | `DashboardEntry`/`DashboardSource` Protocol、`DashboardStore`、`GoalDashboardSource`/`TasksDashboardSource`、`/dashboard` 斜杠命令、`DashboardList`/`DashboardGet` model tools |

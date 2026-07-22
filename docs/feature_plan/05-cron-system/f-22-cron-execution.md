# F-22: Cron 系统执行引擎

> 状态: 🔄 进行中（Phase A~E ✅, G1~G10 ✅, D1~D4 ✅, Phase F~J 部分落地）
> 章节: docs/feature_plan/05-cron-system/f-22-cron-execution.md
> 最后更新: 2026-07-22

## §1 设计规划

### 1.1 背景与目标

将 claude-code-best 的生产级别 cron 执行引擎完整迁移到 ClawCodex 的下游扩展层。最终用户应能在 REPL、TUI、headless/print 模式中创建、查看、删除和执行定时任务，并能查看定时任务触发后的运行状态与结果。

`claude-code-best` 的 Cron 行为跨越工具、存储、调度器、CLI skills、REPL/headless 执行队列、autonomy run 记录和 missed-task 安全确认。ClawCodex 当前已有 `clawcodex_ext/cron_system/*` 的核心模块，但尚需将这些模块完整接入真实 CLI 运行路径。F-22 的完成标准必须从"模块存在"提升为"端到端行为与 `claude-code-best` 对齐"。

**目标行为**:
1. 完整 cron 表达式解析（5 字段标准语法）
2. 下次执行时间计算（本地时区）
3. 调度器执行引擎（1秒轮询）
4. 任务持久化（`.clawcodex/cron/scheduled_tasks.json`，向后兼容读取 `.claude/scheduled_tasks.json`）
5. 分布式锁（防止多进程重复执行）
6. Jitter 抖动算法（避免雷鸣般群体效应）
7. 任务过期机制（周期性任务 7 天自动删除）
8. scheduled fire 进入真实 REPL/TUI/headless 队列
9. 每次定时触发生成可查询 run 记录
10. 提供 `/autonomy status`、`/autonomy runs` 等命令
11. 同一 cron task 存在 active run 时去重

### 1.2 参考实现边界

迁移时以 `claude-code-best` 的以下文件作为行为来源：

| 能力 | 参考文件 | 迁移关注点 |
|---|---------|------------|
| Cron 工具 | `ScheduleCronTool/CronCreateTool.ts` | schema、cron 校验、durable 处理、返回字段、启用 scheduler |
| Cron 列表 | `ScheduleCronTool/CronListTool.ts` | session + durable 聚合、teammate 过滤、展示字段 |
| ConDeleteTool.ts` | ID 校验、权限/归属校验、删除语义 |
| Feature gate | `ScheduleCronTool/prompt.ts` | `CLAUDE_CODE_DISABLE_CRON`、durable gate |
| 存储模型 | `src/utils/cronTasks.ts` | session-only 与 durable 分离、8 位 ID |
| 调度器 | `src/utils/cronScheduler.ts` | 1 秒轮询、busy gate、scheduler lock、missed one-shot、filter |
| REPL 集成 | `src/hooks/useScheduledTasks.ts` | scheduled task 入队、系统消息、去重 |
| Headless 集成 | `src/cli/print.ts` | print 模式定时任务入队、teammate 失败记录 |
| 管理命令 | `src/skills/bundled/cronManage.ts` | `/cron-list`、`/cron-delete` |
| 运行记录 | `src/utils/autonomyRuns.ts` | queued/running/completed/failed/cancelled 生命周期 |
| 状态展示 | `src/utils/autonomyStatus.ts` | cron section、runs/status 输出 |

### 1.3 当前 ClawCodex 状态诊断

**fallback 工具层** (`src/tool_system/tools/cron.py`)：
- 任务保存在 `ToolContext.crons` 的进程内 dict 中
- `durable` 参数被接受但不写入 `.clawcodex/cron/scheduled_tasks.json`
- 不验证 5 字段 cron 语义，只检查字符串非空
- 没有 scheduler，不会自动触发任务
- 该层保留为静态工具兼容 fallback

**下游扩展核心模块**（`clawcodex_ext/cron_system/` 13 模块 ~3,189 行）：

```
├── models.py          # CronFields、CronTask、CronJitterConfig
├── parser.py          # 5 字段 cron 解析、next run、human schedule
├── tasks.py           # 文件存储 CRUD、due/missed/prune、storage lock
├── lock.py            # scheduler/storage filesystem lock
├── jitter.py          # deterministic jitter（正向+反向）
├── notifications.py   # missed one-shot notification
├── scheduler.py       # scheduler thread + check_once + inFlight
├── tools.py           # replacement CronCreate/CronList/CronDelete
├── runtime.py         # replace_cron_tools + attach_cron_runtime
├── runs.py            # CronRun 生命周期管理
├── status.py          # autonomy status/runs 输出
└── schedule.py        # 本地调度命令
```

这些模块已覆盖 parser/storage/scheduler/jitter/lock/permanent/inFlight/run 全生命周期。运行路径接线（Phase A）已在 `RuntimeContext.build()` + `clawcodex_ext/repl/core.py` 中完成。

**关键运行路径断点**：
1. `RuntimeContext.build()` 调用 `replace_cron_tools()` + `attach_cron_runtime()`
2. 各前端（REPL/TUI/headless）通过 prebuilt RuntimeContext 使用 cron tools
3. REPL 主循环通过 `_drain_cron_outbox()` 消费 `cron_prompt`/`cron_missed` 事件
4. TUI outbox drain 待接线

### 1.4 目标架构

```
CLI parser / dispatch
        ↓
clawcodex_ext.runtime.RuntimeContext
        ├── provider
        ├── tool_registry  ── replace_cron_tools() ── CronCreate/List/Delete
        ├── tool_context   ── session cron store + dispatch hooks
        ├── session
        └── cron_runtime
              ├── CronScheduler
              ├── CronDispatchBridge
              └── CronRunStore / autonomy-compatible run records
        ↓
Frontend plugin (REPL / TUI / headless) 使用预构造 RuntimeContext
        ↓
Scheduled fire → queued command / run record → frontend 执行 → status 可查询
```

关键原则：
- `clawcodex_ext/cron_system/*` 持有业务实现
- `src/tool_system/tools/cron.py` 保留 fallback，不承载完整行为
- `src/repl/*`、`src/entrypoints/*` 只增加可选 prebuilt runtime/context 参数

### 1.5 实施阶段

#### Phase A — runtime-first 接线 ✅ 已完成

**目标**: 让真实 CLI 路径使用 `RuntimeContext` 中已替换的工具、上下文和 scheduler。

| 文件 | 改动 | 状态 |
|------|------|:----:|
| `clawcodex_ext/runtime/context.py` | `RuntimeContext.build()` 调用 `attach_cron_runtime(tool_context, autostart=True)` | ✅ |
| `clawcodex_ext/frontend/protocol.py` | `_HAS_CRON` 探测、`RuntimeContext.cron_runtime` property | ✅ |
| `clawcodex_ext/frontend/repl.py` | `register_tools` 时 `replace_cron_tools()` | ✅ |
| `clawcodex_ext/frontend/headless.py` | 通过 `RuntimeContext.build()` 共用 runtime | ✅ |
| `clawcodex_ext/frontend/tui.py` | 通过 `RuntimeContext.build()` 共用 runtime | ✅ |
| `src/repl/core.py` | `_drain_cron_outbox()` 消费 cron 事件入队 | ✅ |

实现顺序: `attach_cron_runtime`/`replace_cron_tools` glue API ✅ → frontend 使用 prebuilt runtime ✅ → scheduler lifecycle ✅ → REPL `_drain_cron_outbox()` ✅

#### Phase B — 存储与模型语义对齐 ✅ 已完成

**目标**: 补齐 session-only 与 durable 分离，统一文件 schema 和工具行为。

| 文件 | 改动 |
|------|------|
| `models.py` | `CronTask` 完整字段：id, cron, prompt, created_at, updated_at, last_fired_at, next_fire_at, expires_at, recurring, permanent, durable, agent_id |
| `tasks.py` | durable 文件 CRUD + session task store；读入兼容 snake_case/camelCase |
| `tools.py` | `CronCreate` 按 `durable` 分流；`CronList` 聚合两 store；`CronDelete` 删除两 store |

关键决策：
- `durable=False` 不写 `.clawcodex/cron/scheduled_tasks.json`
- 读取时容忍 snake_case 和 camelCase
- `CronCreate`/`CronDelete` 的 `is_read_only` 改为 `False`
- 缺失 ID 的 `CronDelete` 返回 tool input error

#### Phase C — scheduler 语义对齐 ✅ 已完成

**目标**: scheduler 行为与 `cronScheduler.ts` 对齐。

| 文件 | 改动 |
|------|------|
| `scheduler.py` | `is_loading`、`assistant_mode`、`is_killed`、`filter`、`get_jitter_config` |
| `lock.py` | `O_EXCL` lock + 同 session 重入/接管 |
| `jitter.py` | recurring 10% period capped by 15m + one-shot configured boundary early jitter |
| `notifications.py` | missed one-shot 安全 fence 确认 |
| `tasks.py` | due/missed/prune/mark-fired 原子状态转换 |

调度语义：
- `check_once()` 先判断 `is_killed()`，再判断 `is_loading()` 与 `assistant_mode`
- recurring task fired 后更新 `last_fired_at`、`next_fire_at`
- one-shot task fired 后删除
- missed durable one-shot 启动时删除并通知，不自动执行

#### Phase D — 执行队列与结果追踪 ✅ 已完成

**目标**: scheduled fire 不只是写 outbox，而是进入真实命令执行与结果查询路径。

| 文件 | 改动 |
|------|------|
| `runtime.py` | outbox 升级为 typed dispatch bridge |
| `runs.py` | CronRun 全生命周期 + create/claim/finalize 链路 |
| `status.py` | `build_autonomy_status`/`build_autonomy_runs` 输出 |

运行记录字段：
```json
{
  "run_id": "uuid", "runtime": "automatic", "trigger": "scheduled-task",
  "status": "queued", "root_dir": "/path", "current_dir": "/path",
  "source_id": "a1b2c3d4", "source_label": "Check deploy",
  "workload": "cron", "prompt_preview": "Check deploy",
  "created_at": 1700000000000, "updated_at": 1700000000000,
  "ended_at": null, "error": null
}
```

#### Phase E — skills 与用户命令 ✅ 已完成

**目标**: 用户无需知道底层工具名即可管理 cron。

| 命令 | 行为 |
|------|------|
| `/loop [interval] <prompt>` | 创建 recurring task，默认 10m，创建后立即执行一次 |
| `/cron-list` | 调用 `CronList` 以表格展示 ID、Schedule、Prompt、Recurring、Durable |
| `/cron-delete <id>` | 调用 `CronDelete` 删除；ID 缺失或不存在时清晰错误 |

`/loop` 在 `clawcodex_ext/skills/bundled/loop.py` 注册；`/cron-list`/`/cron-delete` 在 `clawcodex_ext/command_system/builtins.py` 注册。

#### Phase F — teammate / agent ownership

**目标**: 在 ClawCodex 支持 teammate runtime 时还原 cron ownership 行为。当前代码中 `CronTask` 模型**没有** `agent_id` 字段，`CronRun` 虽有 `owner_key`/`owner_process_id`/`owner_session_id` 但属于进程级而非 agent 级。Phase F 需要从模型、调度器、工具、前端四个层面补齐 ownership 语义。

##### F-1 模型扩展

| 字段 | 类型 | 说明 |
|------|------|------|
| `CronTask.agent_id` | `str \| None` | 创建者 agent 标识；`None` 表示全局任务（任何 agent 可触发） |
| `CronTask.team_id` | `str \| None` | 团队标识（预留，用于多租户隔离） |
| `CronRun.owner_agent_id` | `str \| None` | 实际执行该 run 的 agent 标识 |

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/models.py:CronTask` | 新增 `agent_id: str \| None = None`、`team_id: str \| None = None` 字段；`from_dict()` 回退读取 `agentId`/`teamId`；`to_dict()` 写出 snake_case |
| `clawcodex_ext/cron_system/runs.py:CronRun` | 新增 `owner_agent_id: str \| None = None` 字段；`from_dict()` 回退读取 `ownerAgentId`/`owner_agent_id`（遵循现有 `owner_key`/`ownerKey` 模式，如 `runs.py:111`）；`to_dict()` 写出 `"owner_agent_id": self.owner_agent_id` 字段 |
| `clawcodex_ext/cron_system/tasks.py` | `read_cron_tasks()` 处理新字段（向后兼容，旧文件无 `agent_id` 时 `from_dict` 返回默认 None） |
| `clawcodex_ext/cron_system/schedule.py:CronTaskDetail` | 新增 `agent_id: str \| None` 字段；`format_cron_task_detail()` 将硬编码的 `"Agent: —"` 替换为实际值 |

##### F-2 调度器过滤

`CronScheduler.check_once()` 在查询 due tasks 后增加 agent 过滤层：

```python
# 伪代码
if current_agent_id is not None:
    due = [
        t for t in due
        if t.agent_id is None or t.agent_id == current_agent_id
    ]
```

- `CronScheduler` 新增 `agent_id: str | None` 构造参数
- 全局任务（`agent_id=None`）对所有 agent 可见
- 归属于某 agent 的任务只在该 agent 的会话中被调度器触发

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/scheduler.py:CronScheduler.__init__` | 新增 `agent_id: str \| None = None` 字段 |
| `clawcodex_ext/cron_system/scheduler.py:check_once()` | `find_due_tasks()` 调用后增加 agent 过滤：`if self.agent_id is not None: due = [t for t in due if t.agent_id is None or t.agent_id == self.agent_id]` |
| `clawcodex_ext/cron_system/runtime.py:attach_cron_runtime()` | 新增 `agent_id` 参数，透传给 `CronScheduler` |
| `clawcodex_ext/cron_system/runtime.py:replace_cron_tools()` | 新增 `agent_id` 参数，透传给 CronCreate/CronList 工具 |

##### F-3 工具层可见性

- `CronList` 新增 `agent_id` 过滤参数，默认只返回当前 agent 的任务 + 全局任务
- 管理员（`agent_id="*"`）可查看所有任务
- `CronDelete` 校验归属：非管理员不能删除其他 agent 的任务
- `CronCreate` 自动填充 `agent_id` 为当前 agent

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/tools.py:_cron_list_call()` | 接收 `tool_input.get("agent_id")`；如非 None 且非 `"*"`，过滤 `jobs` 列表只保留 `task.agent_id in (None, agent_id)` |
| `clawcodex_ext/cron_system/tools.py:_cron_delete_call()` | 删除前校验 `task.agent_id`：若 `tool_input` 未传 `agent_id` 且 `task.agent_id` 非 None，返回 `ToolInputError("cron job owned by agent")` |
| `clawcodex_ext/cron_system/tools.py:_cron_create_call()` | 新增 `tool_input.get("agent_id")` 写入 `CronTask`（自动填充由调用方保证） |
| `clawcodex_ext/cron_system/tools.py:_task_output()` | 新增 `"agentId": task.agent_id` 字段返回 |

##### F-4 Teammate 生命周期

| 场景 | 行为 |
|------|------|
| teammate 创建 session-only cron | 任务带 `agent_id`，只在该 agent 上下文可见/可删 |
| teammate 已退出（graceful shutdown） | 调度器触发 owned task 时记录 failed run，错误说明 "owner agent exited" |
| teammate 异常退出（crash） | 通过 `lock.py:_pid_is_alive()` 机制（D2 PID 活体检测，检查 `/proc/<pid>/comm` 白名单）发现 owner 失活，标记 orphaned task |
| headless 无 teammate runtime | `CronScheduler.agent_id` 为 None，只调度全局任务；创建带 `agent_id` 的任务时返回 failed run，错误说明无法路由 owner |

**crash 检测机制说明**：`lock.py` 中已有 `_pid_is_alive(pid)` 函数（D2 实现），通过 `os.kill(pid, 0)` 探测进程存活，并额外检查 `/proc/<pid>/comm` 是否以 `python` 或 `clawcodex` 开头防止 PID 被同名进程复用。Phase F-4 的 crash 检测可直接复用此机制：在 `CronScheduler.check_once()` 的 agent 过滤阶段，对 `agent_id` 匹配的任务检查其所属 `owner_process_id`（记录在 `CronRun` 中），若 `_pid_is_alive(owner_pid)` 返回 False 则写 failed run 并跳过。

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/scheduler.py:check_once()` | 当 `agent_id` 非 None 且 task 的 `agent_id` 匹配但 owner 已失活时，写 failed run 并跳过（`"error": "owner agent exited"`）；复用 `clawcodex_ext.cron_system.lock._pid_is_alive()` 检测 |
| `clawcodex_ext/cron_system/runtime.py:attach_cron_runtime()` | 新增 `agent_id` 参数，headless 模式传入 `None`（降级为只调度全局任务） |
| `clawcodex_ext/entrypoints/headless.py` | 调用 `attach_cron_runtime()` 时不传 `agent_id`，即 `None` |
| `clawcodex_ext/repl/core.py` | 调用 `attach_cron_runtime()` 时不传 `agent_id`，即 `None`（单 agent 模式） |

##### F-5 清理孤儿任务

- 新方法 `cleanup_orphaned_tasks(workspace_root, active_agents: set[str])`：
  - 遍历所有 `agent_id` 非 None 的任务
  - 如果 `agent_id` 不在 `active_agents` 中，标记为 orphaned
  - Orphaned 任务在 `CronList` 中显示状态 `orphaned`
  - 可配置自动删除（默认保留，人工确认）

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/tasks.py` | 新增 `cleanup_orphaned_tasks()` 函数，接收 `workspace_root` 和 `active_agents: set[str]`，返回 orphaned 任务列表 |
| `clawcodex_ext/cron_system/tools.py:_task_output()` | 新增 `"status": "orphaned"` 逻辑：当 `task.agent_id` 非 None 且当前未在 active_agents 中时标记 |
| `clawcodex_ext/cron_system/status.py:_job_table()` | 新增 `Orphaned` 列，显示 `✓`/`—` |
| `clawcodex_ext/cron_system/scheduler.py:check_once()` | 定期调用 `cleanup_orphaned_tasks()`（与 prune 同一 tick 节拍） |

##### F-6 实现优先级

| 步骤 | 内容 | 优先级 | 依赖 |
|:----:|------|:------:|------|
| 1 | F-1: 模型扩展 — `CronTask.agent_id`、`CronRun.owner_agent_id`、`CronTaskDetail.agent_id` | P1 | 无 |
| 2 | F-2: `CronScheduler.agent_id` + `check_once` 过滤 | P1 | F-1 |
| 3 | F-3 工具层 — `CronCreate` 自动填充 + `CronList`/`CronDelete` 归属过滤 | P1 | F-1 |
| 4 | F-4 头端 — headless 降级 + teammate 退出检测 | P1 | F-2, F-3 |
| 5 | F-5 `cleanup_orphaned_tasks` 与调度器集成 | P2 | F-1, F-2 |
| 6 | F-4 进阶 — teammate 崩溃时自动标记 failed run | P2 | F-4 基础 |

**关键依赖路径**：F-1 → F-2 → F-3 → F-4；F-5 与 F-4 可并行；F-4 进阶依赖 teammate 子系统先上线。

#### Phase G — 前端集成补齐与 CronDispatchBridge 统一

**目标**: 补齐 TUI frontend 的 cron 集成缺口，并将三端 ad-hoc drain 函数抽象为 `CronDispatchBridge` 统一类型。当前 TUI 入口 (`clawcodex_ext/entrypoints/tui.py`) 无任何 cron 集成，而 REPL (`clawcodex_ext/repl/core.py`) 和 headless (`clawcodex_ext/entrypoints/headless.py`) 各有独立的 drain 实现，缺少统一的事件分发抽象。

##### G-1 TUI 前端 cron 集成

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/entrypoints/tui.py` | 新增 `import` cron 模块；在 `run_tui()` 入口调用 `attach_cron_runtime(tool_context, autostart=True, is_loading=…)`；新增 `_drain_cron_outbox()` 函数（mirror headless 实现） |
| `clawcodex_ext/entrypoints/tui.py` | 新增 `_process_cron_outbox()` 函数，在 agent loop 的每次迭代前后消费 outbox 事件 |
| `clawcodex_ext/entrypoints/tui.py` | 新增 `_run_cron_prompt()` 回调（将 cron prompt 送入 TUI 的 query pipeline） |
| `clawcodex_ext/entrypoints/tui.py` | 新增 `_claim_cron_task()` / `_finalize_cron_task()` 辅助函数（mirror headless 实现） |

**实现签名**（参考 headless 模式）：

```python
# clawcodex_ext/entrypoints/tui.py 新增函数
def _drain_cron_outbox(tool_context, active_tasks) -> list[tuple[str, str, str]]:
    """Drain cron_prompt events from tool_context.outbox."""
    ...

def _process_cron_outbox(tool_context, active_tasks, run_prompt, *, max_iterations=10):
    """Drain and execute cron prompts until the outbox is empty."""
    ...
```

##### G-2 CronDispatchBridge 统一抽象

**目标**: 将 REPL/headless/TUI 三端的 ad-hoc drain 函数抽象为 `CronDispatchBridge` 类，统一事件类型和消费契约。

**设计**：

**与现有 `CronPromptEvent`/`CronMissedEvent` 的映射关系**：

`runtime.py` 中 `attach_cron_runtime()` 的 `on_fire_task` 回调写入 `CronPromptEvent(prompt, task_id, run_id)` 到 outbox（`clawcodex_ext/query/outbox_types.py:13-48`），`on_missed` 回调写入 `CronMissedEvent(tasks, notification)`（`clawcodex_ext/query/outbox_types.py:51-80`）。`CronDispatchBridge` 的 `CronDispatchEvent` 应直接映射 `CronPromptEvent` 的三个字段，避免数据转换丢失：

| `CronPromptEvent` 字段 | `CronDispatchEvent` 字段 | 说明 |
|------------------------|-------------------------|------|
| `prompt: str` | `prompt: str` | 原始提示词 |
| `task_id: str` | `task_id: str` | 任务 ID |
| `run_id: str` | `run_id: str` | 运行记录 ID |
| `event.get("type") == "cron_prompt"` | `wrapped_prompt: str` | `wrap_cron_prompt(prompt)` 生成的带 header 包装文本 |

```python
# 新文件: clawcodex_ext/cron_system/dispatch.py
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from clawcodex_ext.cron_system.runs import claim_cron_run, finalize_cron_run
from clawcodex_ext.query.outbox_types import CronPromptEvent, CronMissedEvent

@dataclass
class CronDispatchEvent:
    prompt: str
    task_id: str
    run_id: str
    wrapped_prompt: str

class CronDispatchBridge:
    """Typed dispatch bridge for cron fire events.

    Replaces ad-hoc outbox-drain logic in REPL, headless, and TUI
    frontends with a unified dispatcher.

    Maps directly to ``CronPromptEvent`` (fire) and ``CronMissedEvent``
    (missed one-shot) from ``clawcodex_ext/query/outbox_types.py``.
    The ``drain()`` method pops ``CronPromptEvent`` entries from the
    outbox, callers are responsible for reading ``CronMissedEvent``
    separately (typically via a missed-task notification callback).
    """
    def __init__(self, workspace_root: Path,
                 wrap_prompt: Callable[[str, str, str], str] | None = None) -> None:
        self._workspace_root = workspace_root
        self._wrap_prompt = wrap_prompt or _default_wrap_prompt

    def drain(self, outbox: list) -> list[CronDispatchEvent]:
        """Pop ``CronPromptEvent`` entries from the outbox and return
        runnable payloads. ``CronMissedEvent`` entries are left in place
        for the caller to handle."""
        events: list[CronDispatchEvent] = []
        remaining: list = []
        for event in outbox:
            if isinstance(event, CronPromptEvent):
                events.append(CronDispatchEvent(
                    prompt=event.prompt,
                    task_id=event.task_id,
                    run_id=event.run_id,
                    wrapped_prompt=self._wrap_prompt(event.prompt, event.task_id, event.run_id),
                ))
            else:
                remaining.append(event)
        outbox[:] = remaining
        return events

    def claim(self, task_id: str, run_id: str) -> str | None:
        """Mark a run as started (queued → running)."""
        return claim_cron_run(self._workspace_root, run_id, task_id)

    def finalize(self, task_id: str, run_id: str, status: str,
                 error: str | None = None) -> None:
        """Mark a run as completed/failed/cancelled."""
        finalize_cron_run(self._workspace_root, run_id, status, error=error)
```

**替换路径**：

| 前端 | 替换前 | 替换后 |
|------|--------|--------|
| REPL | `_drain_cron_outbox()` 内联 | `CronDispatchBridge.drain()` |
| headless | `_drain_cron_outbox()` + `_process_cron_outbox()` | `CronDispatchBridge.drain()` + `claim()`/`finalize()` |
| TUI | 无（新建） | `CronDispatchBridge.drain()` |

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/dispatch.py` | **新建** — `CronDispatchEvent` + `CronDispatchBridge` 类 |
| `clawcodex_ext/entrypoints/headless.py` | 将 `_drain_cron_outbox()` / `_claim_cron_task()` / `_finalize_cron_task()` / `_process_cron_outbox()` 替换为 `CronDispatchBridge` 调用 |
| `clawcodex_ext/entrypoints/tui.py` | 使用 `CronDispatchBridge` 实现 cron 集成（G-1） |
| `clawcodex_ext/repl/core.py` | 将 `_watch_outbox` 中的 cron 消费逻辑替换为 `CronDispatchBridge` 调用 |

##### G-3 TUI 传递 `is_loading` 回调

**文件变更**：

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/entrypoints/tui.py` | `attach_cron_runtime()` 调用时增加 `is_loading=lambda: in_agent_loop.value` 参数（参考 headless 模式） |
| `clawcodex_ext/entrypoints/tui.py` | 新增 `_InAgentLoopFlag` 类（或复用 headless 的 `InAgentLoopFlag` 类型） |

##### G-4 实现优先级

| 步骤 | 内容 | 优先级 | 依赖 |
|:----:|------|:------:|------|
| 1 | G-1: TUI 前端 cron 集成（copy headless 模式） | P0 | 无 |
| 2 | G-3: TUI 传递 `is_loading` 回调 | P0 | G-1 |
| 3 | G-2: `CronDispatchBridge` 类设计 + 替换 headless 端 | P0 | G-1 |
| 4 | G-2: 替换 REPL 端 | P1 | G-2 步骤 3 |
| 5 | G-2: TUI 端使用 CronDispatchBridge | P1 | G-1, G-2 步骤 3 |

#### Phase H — durable 文件增量加载（R6）

**目标**: 引入 mtime 轮询机制，避免每次读文件时全量扫描，减少多会话场景下的高并发 I/O。

##### H-1 设计

当前 `read_cron_tasks()` 每次调用都从头读取文件、JSON 解析全部内容。在多会话场景下，scheduler 每秒调用 `check_once()` → `find_due_tasks()` → `read_cron_tasks()`，导致不必要的 I/O 开销。

**方案**: 引入 mtime 缓存 + 增量重读策略。

```python
# clawcodex_ext/cron_system/tasks.py 新增
_MtimeCache: dict[Path, tuple[float, list[CronTask]]] = {}
_MTIME_CACHE_TTL: float = 1.0  # 1 second cooldown

def read_cron_tasks_cached(workspace_root: Path) -> list[CronTask]:
    """mtime-based incremental read: skip if file unchanged within TTL."""
    path = tasks_file_path(workspace_root)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return read_cron_tasks(workspace_root)  # fallback
    cached = _MtimeCache.get(path)
    if cached is not None and (time.monotonic() - cached[0]) < _MTIME_CACHE_TTL:
        return cached[1]
    # Also skip re-read if mtime unchanged
    if cached is not None and cached[0] == mtime:
        return cached[1]
    tasks = read_cron_tasks(workspace_root)
    _MtimeCache[path] = (mtime, tasks)
    return tasks
```

**关键决策**：
- 使用 `st_mtime`（modification time）而非 `st_ctime`（metadata change time）：`os.replace()` 原子替换将新文件写入目标路径，新文件的 `st_mtime` 为当前写入时间，因此 `st_mtime` 已足够捕获文件替换事件；`st_ctime` 虽能捕获 inode 变更（权限/所有权修改），但对本场景无额外增益
- `_MTIME_CACHE_TTL = 1.0`：与 scheduler 1 秒 tick 对齐，避免同一 tick 内重复读取
- 全局进程级缓存（`dict[Path, ...]`）：多 scheduler 实例共享同一 workspace 时复用
- 写路径（`write_cron_tasks()`）在完成后**不**主动失效缓存，依靠 `st_mtime` 变化自动触发下次重读，避免竞态
- **注意**：`stat().st_mtime` 精度因操作系统和文件系统而异（Linux ext4 为纳秒级，Windows NTFS 为 100ns 级），但 `os.replace()` 的原子替换必定产生新的 mtime 值，因此 `!=` 比较总是可靠

##### H-2 文件变更

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/tasks.py` | 新增 `_MtimeCache`、`_MTIME_CACHE_TTL`、`read_cron_tasks_cached()` 函数 |
| `clawcodex_ext/cron_system/scheduler.py` | `CronScheduler.load()` 和 `check_once()` 中的 `read_all_cron_tasks()` 调用替换为 `read_cron_tasks_cached()` |
| `clawcodex_ext/cron_system/tasks.py:read_cron_tasks()` | 保持不变，作为无缓存 fallback 保留 |

##### H-3 后续演进

| 阶段 | 方案 | 触发条件 |
|:----:|------|----------|
| 首期（H-1） | mtime 轮询 + 1 秒 TTL | 当前 Phase H |
| 中期 | `inotify`/`kqueue` 文件 watcher | 多会话性能瓶颈实测 |
| 远期 | 共享内存 mmap + 无锁读取 | 极端高并发场景 |

#### Phase I — CCB 兼容门禁命名（R8）

**目标**: `is_cron_disabled()` 函数在读取 `CLAWCODEX_DISABLE_CRON` 的同时，回退兼容读取 `CLAUDE_CODE_DISABLE_CRON`，确保从 CCB 迁移过来的用户环境变量无需修改。

##### I-1 设计

```python
# clawcodex_ext/cron_system/models.py 修改
ENV_CLAWCODEX_DISABLE_CRON = "CLAWCODEX_DISABLE_CRON"
ENV_CLAUDE_CODE_DISABLE_CRON = "CLAUDE_CODE_DISABLE_CRON"  # 新增兼容常量

def is_cron_disabled(env: dict[str, str] | None = None) -> bool:
    """Check ``CLAWCODEX_DISABLE_CRON`` (F-22-G1) at runtime,
    with fallback to ``CLAUDE_CODE_DISABLE_CRON`` for CCB migration."""
    env_map = env if env is not None else os.environ
    raw = env_map.get(ENV_CLAWCODEX_DISABLE_CRON)
    if raw is None:
        raw = env_map.get(ENV_CLAUDE_CODE_DISABLE_CRON)  # 回退读取
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}
```

**优先级语义**：`CLAWCODEX_DISABLE_CRON` 优先于 `CLAUDE_CODE_DISABLE_CRON`。当两个变量同时存在时，以 ClawCodex 原生变量为准。

##### I-2 文件变更

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/cron_system/models.py` | 新增 `ENV_CLAUDE_CODE_DISABLE_CRON` 常量；`is_cron_disabled()` 增加回退读取逻辑 |
| `clawcodex_ext/cron_system/models.py` | `is_cron_disabled()` 的 docstring 更新说明 CCB 兼容行为 |

#### Phase J — 用户管理入口补齐（R4）

**目标**: 补齐 `/cron-trigger` 命令别名和 `--deep` 在 `/cron-list` 中的集成。

##### J-1 `/cron-trigger` 命令别名

**代码现状**：`CRON_RUN_COMMAND` 已注册 `aliases=["cron-fire"]`（`clawcodex_ext/command_system/builtins.py:1604`），`/cron-fire <id>` 已可作为 `/cron-run <id>` 的等价别名使用。J-1 在此基础之上新增 `/cron-trigger` 别名。

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/command_system/builtins.py` | `CRON_RUN_COMMAND` 的 `aliases` 列表新增 `"cron-trigger"`，即 `aliases=["cron-fire", "cron-trigger"]` |
| `clawcodex_ext/cron_system/tools.py:_cron_run_call()` | 确认 `CronRunTool` 的 tool_input 参数兼容手动触发（无需变更，已兼容） |

**现有 `cron-fire` 与新增 `cron-trigger` 的关系**：

| 维度 | 说明 |
|------|------|
| 现有行为 | `/cron-fire <id>` 通过 `CRON_RUN_COMMAND.aliases` 解析到 `cron_run_command_call`，调用 `CronRunTool` 触发任务 |
| 新增行为 | `/cron-trigger <id>` 与 `/cron-fire <id>` 完全等价，共用同一 `CronRunTool` 调用路径 |
| 注册方式 | 二者均通过 `aliases` 列表注册，而非独立 `LocalCommand` 注册（避免重复的工具调用逻辑） |
| 弃用策略 | 三者（`cron-run`/`cron-fire`/`cron-trigger`）长期共存，互不弃用 |

##### J-2 `--deep` 集成到 `/cron-list`

**代码现状**：`_cron_deep_arg()` 辅助函数已存在（`clawcodex_ext/command_system/builtins.py:510`），用于 `cron_status_command_call` 和 `cron_runs_command_call` 解析 `--deep` 标志。但 `cron_list_command_call`（`builtins.py:546`）目前**不解析** `--deep`，其调用路径为 `_call_cron_tool(context, "CronList", {})` 传入空 input，`CronList` 工具返回所有任务无截断——因此 `--deep` 对当前 `/cron-list` 无实际意义，实施目标是为将来的截断行为预留 `--deep` 接口。

**实施路径**（二选一）：

| 方案 | 路径 | 说明 | 推荐度 |
|:----:|------|------|:------:|
| A | `cron_list_command_call` 解析 `args` 中的 `--deep`，透传给 `build_schedule_list(workspace_root, deep=True)` | 与 `cron-status`/`cron-runs` 模式一致，使用现有 `_cron_deep_arg()` 辅助函数 | ⭐ 推荐 |
| B | `CronList` 工具新增 `tool_input` 参数 `deep`，`_cron_list_call` 收到后返回完整任务列表（含所有字段），`cron_list_command_call` 传入 `{"deep": True}` | 工具层语义更干净，但需修改 `_cron_list_call` 和 `CronList` 的 input schema | 可选 |

**方案 A 推荐原因**：无需修改工具层 schema，`--deep` 作为展示层标志而非数据层过滤，与 `cron-status`/`cron-runs` 一致。

| 文件 | 变更 |
|------|------|
| `clawcodex_ext/command_system/builtins.py` | `cron_list_command_call()` 解析 `--deep` 标志，调用 `_cron_deep_arg(args)`；当 `_cron_deep_arg` 返回 True 时，标记在输出中（例如表格尾部添加 `"(deep mode)"` 提示） |
| `clawcodex_ext/cron_system/status.py:build_schedule_list()` | 新增 `deep: bool = False` 参数（当前无截断逻辑，接收参数后仅在 docstring 中声明为将来预留） |
| `clawcodex_ext/cron_system/status.py:build_autonomy_status()` | 已支持 `deep` 参数，无需修改 |

##### J-3 别名共存冲突分析（含现有 `cron-fire`）

**问题陈述**：J-1 引入 `/cron-trigger` 作为 `/cron-run` 的语义别名后，三个命令名（`cron-run`/`cron-fire`/`cron-trigger`）在 REPL 命令补全器、用户文档、命令帮助系统中将共存。需明确共存的语义契约与可发现性，避免用户困惑何时该用哪个。

**代码现状**：`CRON_RUN_COMMAND` 已注册 `aliases=["cron-fire"]`（`clawcodex_ext/command_system/builtins.py:1604`），`/cron-fire` 已是 `/cron-run` 的现有别名。J-1 将 `cron-trigger` 追加到同一 `aliases` 列表，形成三别名共存。

**设计决定**：

| 维度 | 决定 | 原因 |
|------|------|------|
| 行为等价性 | `/cron-trigger <id>`、`/cron-fire <id>`、`/cron-run <id>` **三者完全等价** — 同一 `CronRunTool` 调用、相同出参、相同 run lifecycle | 别名而非新命令；任何行为分歧都会成为维护负担 |
| 命令注册 | 三者均通过 `CRON_RUN_COMMAND` 的 `aliases` 列表注册，而非独立 `LocalCommand` | `aliases` 列表解析到同一 `cron_run_command_call`，避免重复的工具调用逻辑；`/help cron-fire` 和 `/help cron-trigger` 均返回 `CRON_RUN_COMMAND` 的 description |
| description 文案 | `CRON_RUN_COMMAND.description` 保留为 "Manually fire a scheduled cron job"（已覆盖 `cron-fire` 语义，同样适用 `cron-trigger`） | 别名继承主命令的 description，无需为每个别名单独维护文案 |
| 参数 schema | 三者 `argument_hint="<task_id>"` 完全一致 | 避免补全器歧义 |
| 弃用策略 | **不**弃用任何别名 — 三者长期共存 | `/cron-run` 已在生产用户中扎根；`/cron-fire` 是最早的别名，`/cron-trigger` 作为更直观的别名引入，三者互不替代 |
| 命令冲突 | 无冲突 — `CommandSystem` 解析时先按 `name` 精确匹配，再按 `aliases` 匹配，三者分属不同键但指向同一 handler | 命令分发按 `name`/`aliases` 分别匹配，不存在前缀歧义 |
| 帮助系统 可发现性 | `/help cron-trigger`、`/help cron-fire`、`/help cron-run` 均应返回相同说明 | 确认 `clawcodex_ext/command_system` 的 help 子命令支持别名查询（若按 `aliases` 列表的 `name` 字段查找则天然支持） |

**验收契约**（专项验收步骤 28 已覆盖）：同一任务用 `/cron-trigger <id>` 与 `/cron-run <id>` 各触发一次，两次 run 的 `workload`/`trigger`/`source_id` 字段必须完全一致；差异即视为别名实施失败。

**未引入新代码**：本节为设计文档补全，不涉及代码变更；实施时 J-1 在 `builtins.py` 中新增 `CRON_TRIGGER_COMMAND = LocalCommand(name="cron-trigger", description="Alias of /cron-run — Manually trigger a scheduled task", argument_hint="<task_id>", ...)` 即可，与 `CRON_RUN_COMMAND` 共存。

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| **Phase A** | runtime-first 接线 | ✅ | P0 |
| **Phase B** | 存储与模型语义对齐 | ✅ | P0 |
| **Phase C** | scheduler 语义对齐 | ✅ | P0 |
| **Phase D** | 执行队列与结果追踪 | ✅ | P0 |
| **Phase E** | skills 与用户命令 | ✅ | P0 |
| **Phase F** | teammate/agent ownership | 🔄 部分落地 | P1 |
| **F-1** | 模型扩展（CronTask.agent_id, CronRun.owner_agent_id） | ✅ | P1 |
| **F-2** | 调度器 agent 过滤（check_once agent_id 门控） | ✅ | P1 |
| **F-3** | 工具层可见性（CronList/Delete 归属过滤） | ✅ | P1 |
| **F-4** | Teammate 生命周期（退出/崩溃/无 runtime 降级） | ⏸ 占位等待 teammate | P2 |
| **F-5** | 清理孤儿任务（cleanup_orphaned_tasks） | ⏸ 占位等待 teammate | P2 |
| **Phase G** | 前端集成补齐与 CronDispatchBridge 统一 | 🔄 进行中 | P0 |
| **G-1** | TUI 前端 cron 集成（outbox drain + attach_cron_runtime） | ✅ | P0 |
| **G-2** | CronDispatchBridge 统一抽象（含三端替换） | ✅ | P0 |
| **G-3** | TUI 传递 is_loading 回调 | 📋 | P0 |
| **Phase H** | durable 文件增量加载（mtime 轮询） | 📋 设计就绪 | P1 |
| **Phase I** | CCB 兼容门禁命名（CLAUDE_CODE_DISABLE_CRON 回退） | 📋 设计就绪 | P1 |
| **Phase J** | 用户管理入口补齐（R4） | 📋 设计就绪 | P2 |
| **J-1** | /cron-trigger 命令别名 | 📋 | P2 |
| **J-2** | --deep 集成到 /cron-list | 📋 | P2 |
| **G1** | isKilled 运行时 kill 开关 | ✅ | P0 |
| **G2** | 远程 Jitter 实时配置 — 6 参数可配，每 tick 热加载 | ✅ | P0 |
| **G3** | One-shot 反向 Jitter — 整点 (:00/:30) 提前触发 | ✅ | P0 |
| **G4** | Permanent 免过期机制 — 写保护 / 幂等安装 | ✅ | P0 |
| **G5** | 锁注册式清理与 PID 增强 — atexit 清理、PID 分身检测 | ✅ | P0 |
| **G6** | 工具 Prompt 指引增强 | ✅ | P0 |
| **G7** | Analytics 遥测事件预留 | ✅ | P0 |
| **G8** | inFlight 防重复触发 | ✅ | P0 |
| **G9** | SDK daemon 模式（dir/lockIdentity） | ✅ | P0 |
| **G10** | cronToHuman(utc) UTC 模式显示 | ✅ | P0 |
| **D1** | sourceId 级 Active-Run 去重（CCB 第 1 层） | ✅ | P0 |
| **D2** | PID 活体检测（CCB 第 2 层） | ✅ | P0 |
| **D3** | inFlight 防重复触发（CCB 第 3 层） | ✅ | P0 |
| **D4** | 调度锁跨进程互斥（CCB 第 4 层） | ✅ | P0 |

### 1.7 CCB 补充缺口详情（G1~G10 ✅，D1~D4 ✅）

#### G1 — isKilled 运行时 kill 开关 ✅

| 需求项 | 说明 |
|--------|------|
| 环境变量门 | `CLAWCODEX_DISABLE_CRON=true` 启动时禁用 |
| 运行时 kill 接口 | `CronScheduler.is_killed: Callable[[], bool]` 轮询 |
| 动态切换 | 从配置文件或 provider config 变更事件中触发 |
| 工具 prompt 门 | 关闭时工具返回 "Cron is disabled" |

**实施**: `is_cron_disabled()` 读 env + `scheduler.is_killed` 每 tick 轮询 + 工具层返回 `_cron_disabled_result()`

#### G2 — 远程 Jitter 实时配置 ✅

6 参数 `CronJitterConfig`（`recurring_frac`/`recurring_cap_ms`/`one_shot_max_ms`/`one_shot_floor_ms`/`one_shot_minute_mod`/`recurring_max_age_ms`），支持 `.claude/cron_jitter_config.json` + `CLAWCODEX_CRON_*` env 热加载。`CronScheduler.check_once` 每个 tick 调用 loader。

#### G3 — One-shot 反向 Jitter ✅

Recurring: 正向 jitter（延迟触发），比例 10%，最多 15 分钟。
One-shot: 反向 jitter（提前触发），只在 `minute % one_shot_minute_mod === 0` 时生效（默认 mod=30，即 :00/:30），最多 90 秒。

#### G4 — Permanent 免过期机制 ✅

`CronTask.permanent` 字段 + `write_permanent_task_if_missing()` 幂等安装 + `prune_expired_recurring_tasks` 跳过永久任务 + `CronCreate` 拒绝 `permanent=true`。

#### G5~G10 完成项

- **G5**: 锁注册式清理（`register_lock_cleanup` + `release_all_locks` + atexit/SIGTERM/SIGINT 钩子） + PID 存活探测（`/proc/<pid>/comm` 白名单）
- **G6**: 工具 Prompt 指引（CronCreate/List/Delete 的 prompt 字段补充最佳实践）
- **G7**: Analytics 遥测事件预留（fire/missed/expired 事件点预留 Optional[Callable]）
- **G8**: inFlight 防重复触发（`_in_flight: set[str]` + Lock，finally 块保证异常释放）
- **G9**: SDK daemon 模式（`dir_override`/`lock_identity` 可选参数）
- **G10**: `cron_to_human(utc)` UTC 模式（`utc` 参数，实际偏移到本地时区）

#### D1~D4 — CCB 4 层累计防护 ✅

| 层级 | 机制 | 状态 | 实施细节 |
|:----:|------|:----:|----------|
| 第 1 层 | sourceId 级 Dedup — `create_queued_run()` 在 storage lock 下按 source_id 扫描活跃 run | ✅ | `runs.py:get_active_run_for_source()` 在 `create_queued_run()` 内调用，storage lock 保护写路径；`create_queued_run_for_task()` 自动传入 `task.id` 作为 source_id |
| 第 2 层 | PID 活体检测 — `os.kill(pid, 0)` + `/proc/<pid>/comm` 白名单 | ✅ | `lock.py:_pid_is_alive()` 通过 `os.kill(pid, 0)` 探测存活；`_default_pid_validator()` 额外检查 `/proc/<pid>/comm` 是否以 `python` 或 `clawcodex` 开头，防止 PID 被同名进程复用 |
| 第 3 层 | inFlight 防重复 — scheduler 内 `_in_flight` Set + Lock 防止异步 IO 期间二次发射 | ✅ | `scheduler.py:CronScheduler._in_flight: set[str]` + `threading.Lock`；`check_once()` 在 fire 前 `_in_flight_add()`，`finally` 块保证 `_in_flight_remove()` 即使回调异常也释放 |
| 第 4 层 | 调度锁跨进程互斥 — `O_EXCL` 文件锁 + session takeover + stale recovery + atexit 清理 | ✅ | `lock.py:CronTaskLock` 使用 `O_CREAT \| O_EXCL` 原子创建；`_recover_if_stale()` 通过 PID 活体检测判断 stale，自动接管；`register_lock_cleanup()` + `atexit` + `SIGTERM`/`SIGINT` 钩子保证清理 |

**集成验证要点**：
- D1: 同 task 的 consecutive due fires 应去重（`test_scheduler` 中已有 `due_same_task` 用例）
- D2: `_pid_is_alive` 对无效 PID 返回 False，对当前进程返回 True
- D3: `_in_flight` 在 `check_once` 异常路径下仍释放
- D4: 两个 CLI 实例竞争锁，仅 lock owner 触发任务

### 1.8 端到端缺口（R1~R8）

| ID | 缺口 | 状态 | 补齐要求 | 代码现状 | 对应 Phase |
|----|------|:----:|----------|----------|:----------:|
| R1 | 真实 frontend/runtime 接线 | ✅ | RuntimeContext 三端共用；cron tools 已替换 | `RuntimeContext.build()` 调用 `attach_cron_runtime()`（`clawcodex_ext/runtime/context.py`）；`replace_cron_tools()` 在三端 frontend 插件中调用（`clawcodex_ext/frontend/repl.py` / `headless.py` / `tui.py`） | Phase A |
| R2 | scheduled fire 执行队列 | 📋→📝 | 建立 `CronDispatchBridge`，进入 query pipeline | `runtime.py` 使用 typed `CronPromptEvent`/`CronMissedEvent`（`clawcodex_ext/query/outbox_types.py`）写入 outbox。headless `_drain_cron_outbox()` + `_process_cron_outbox()` 消费（`clawcodex_ext/entrypoints/headless.py:1807-1908`），REPL 通过 `_watch_outbox` 消费（`clawcodex_ext/repl/core.py`）。但三端各有 ad-hoc 实现，无统一 `CronDispatchBridge` 类 | Phase G-2 |
| R3 | run lifecycle finalize | ✅ | claim→running→completed/failed/cancelled；补齐字段 | `runs.py:claim_cron_run()` + `finalize_cron_run()` + `update_cron_run_status()` 全链路实现。headless `_claim_cron_task()` 调用 `claim_cron_run()` 并标记 started/failed/completed（`clawcodex_ext/entrypoints/headless.py:1860-1889`） | Phase D |
| R4 | 用户管理入口 | 📋→📝 | trigger detail、manual fire、status/runs richer output | `CronRunTool`（manual fire）+ `get_cron_task_detail()`（`clawcodex_ext/cron_system/schedule.py`）+ `build_autonomy_status/runs()`（`clawcodex_ext/cron_system/status.py`）+ `/cron-status`、`/cron-runs`、`/cron-run` 命令均已实现。缺口：`/cron-trigger` 命令别名（Phase J-1）、`--deep` 在 `/cron-list` 中的集成（Phase J-2）、`format_cron_task_detail()` 中硬编码的 `"Agent: —"`（Phase F-1） | Phase J + F-1 |
| R5 | busy gate/filter 语义 | 📋→📝 | `is_loading`、`assistant_mode`、`filter` 接入 frontend | `scheduler.py:_is_loading_gate()` 已实现，`attach_cron_runtime()` 接收 `is_loading`/`assistant_mode` 参数。REPL 传 `is_loading=lambda: self._active_live_status is not None`（`clawcodex_ext/repl/core.py:786`），headless 传 `is_loading=lambda: in_agent_loop.value`（`clawcodex_ext/entrypoints/headless.py:538-541`）。但 TUI 前端未传递 `is_loading` 回调 | Phase G-3 |
| R6 | durable 文件 reload | 📋→📝 | 首期 mtime polling，后续 watcher | 当前每次读文件（`read_cron_tasks()` 从头读），无增量 mtime 轮询或文件 watcher。Phase H 已设计 mtime 缓存方案 | Phase H |
| R7 | teammate/agent ownership | 📋→📝 | 保留字段、过滤接口和 headless failed run | 同 Phase F。`CronTask` 模型无 `agent_id` 字段，`CronScheduler` 无 agent 过滤。Phase F 已设计完整 6 步骤实施方案 | Phase F |
| R8 | CCB-compatible gate 命名 | 📋→📝 | 兼容读取 `CLAUDE_CODE_DISABLE_CRON` | `is_cron_disabled()` 仅读 `CLAWCODEX_DISABLE_CRON`（`clawcodex_ext/cron_system/models.py:221-227`），未回退到 `CLAUDE_CODE_DISABLE_CRON`。Phase I 已设计回退读取方案 | Phase I |

### 1.9 完成标准（端到端）

| 能力 | 完成标准 |
|------|----------|
| 工具可用性 | CronCreate/List/Delete 在 REPL/TUI/headless 使用扩展实现 |
| /loop | 创建 recurring cron，默认 10m，立即执行一次 |
| 管理命令 | `/cron-list` 和 `/cron-delete <id>` 以表格展示 |
| session-only | `durable=False` 任务只存在于当前 session |
| durable | `durable=True` 写入 `.clawcodex/cron/scheduled_tasks.json`，重启可见；旧版 `.claude/scheduled_tasks.json` 自动回退读取 |
| 调度器 | 每秒检查 due tasks，持有 `.clawcodex/cron/scheduled_tasks.lock` |
| busy gate | 模型响应/工具调用时不抢跑 cron |
| 结果追踪 | 每次 scheduled fire 生成 queued→running→completed/failed/cancelled 记录 |
| missed one-shot | 启动后删除并展示安全 fenced prompt |
| auto-expiry | recurring 默认 7 天；支持配置 max-age |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证 |
|------|--------|---------|:----:|
| 2026-06 | Phase A — runtime-first 接线 | RuntimeContext + REPL _drain_cron_outbox | 271/271 orchestrator |
| 2026-06 | Phase B — 存储与模型对齐 | tasks.py, models.py | cron 测试通过 |
| 2026-06 | Phase C — scheduler 语义对齐 | scheduler.py, lock.py, jitter.py | 90/90 cron tests |
| 2026-06 | Phase D — 执行队列与结果追踪 | runs.py, status.py | 运行记录可查询 |
| 2026-06 | Phase E — skills 与用户命令 | tools.py, runtime.py | /loop、/cron-list、/cron-delete |
| 2026-06 | G1~G10 全部 CCB 缺口闭合 | 全模块 | 46 新单测 + 独立 verifier PASS |
| 2026-06 | G9~G10 daemon + UTC 显示 | scheduler.py, jitter.py | 参数覆盖测试 |
| 2026-07-21 | Phase F~J 设计就绪 + 文档与代码现状对齐 | f-22-cron-execution.md | 代码审查 + 文档补全（3 轮迭代） |
| 2026-07-21 | D1~D4 状态从 📋→✅ + 实施细节补全 | f-22-cron-execution.md §1.7 | 对照 runs.py/lock.py/scheduler.py 代码现状 |
| 2026-07-22 | F-3 (input_schema) + G-2 (headless/REPL 替换) 落地 | tools.py, dispatch.py, headless.py, repl/core.py | 161 cron tests pass |
| 2026-07-22 | F-4/F-5 占位接口 (notify_owner_exited / cleanup_orphaned_tasks) | scheduler.py | 8 stub tests pass，等待 teammate 子系统 |

### 2.2 当前瓶颈

| 优先级 | 瓶颈 | 原因 | 影响范围 | 对应 Phase |
|:------:|------|------|----------|:----------:|
| P0 | R5: TUI 未传递 `is_loading` 回调 | `attach_cron_runtime()` 的 `is_loading` 参数在 TUI 前端未传入 | TUI 模式可能错过 busy gate，cron 在 agent 响应期间抢跑 | Phase G-3 |
| P1 | R6: 无 durable 文件 mtime 轮询 | 每次读全量文件，多会话场景下高并发 I/O | 大文件场景性能瓶颈 | Phase H |
| P1 | R8: 未兼容 CLAUDE_CODE_DISABLE_CRON | `is_cron_disabled()` 仅读 `CLAWCODEX_DISABLE_CRON` | 从 CCB 迁移的用户环境变量不生效 | Phase I |
| P2 | R4: 缺少 `/cron-trigger` 命令别名 | `/cron-run` 已存在但无 `trigger` 别名 | 用户发现成本高 | Phase J-1 |
| P2 | R4: `--deep` 未集成到 `/cron-list` | `build_autonomy_status()` 支持 `deep` 参数但 `/cron-list` 命令未传递 | 任务列表默认截断 | Phase J-2 |
| P2 | R4: `format_cron_task_detail()` 硬编码 `"Agent: —"` | `schedule.py` 中占位符未替换为实际 `agent_id` | 多 agent 场景下信息不准确 | Phase F-1 |
| P2 | F-4: 缺失 teammate 退出错误写路径 | scheduler 无 `notify_owner_exited` 自动 finalize。当前仅有 hook + stub 方法，等待 teammate 子系统 (`TeammateManager`) 接入 | 多 agent 场景下崩溃 run 残留 queued | Phase F-4 |
| P2 | F-5: scheduler 未定期调用 `cleanup_orphaned_tasks` | `cleanup_orphaned_tasks` 函数已存在但缺 active_agents 来源；当前提供 `active_agents_provider` 占位 + 公开方法，等待 teammate 子系统接入 | 孤儿任务无清理触发 | Phase F-5 |

### 2.3 下一步计划

**Phase G — P0 三端集成统一**（当前阶段，G-2 已落地）:
1. **G-1**: TUI outbox drain 接线 — `clawcodex_ext/entrypoints/tui.py` 增加 `_drain_cron_outbox()` + `_process_cron_outbox()` + `_run_cron_prompt()` 函数 ✅
2. **G-3**: TUI 传递 `is_loading` 回调 — 新增 `_InAgentLoopFlag` 类型，在 `attach_cron_runtime()` 中传入
3. **G-2**: 新建 `clawcodex_ext/cron_system/dispatch.py` — `CronDispatchBridge` 类，统一三端 drain 行为 ✅
4. **G-2 (续)**: 分别替换 headless/REPL/TUI 三端的 ad-hoc drain 实现 ✅（TUI 已用 bridge.drain，headless/REPL 也于 2026-07-22 替换）

**Phase F — P1 ownership 模型扩展**（G-2 已完成，F-1/F-2/F-3 已落地）:
5. **F-1**: `CronTask.agent_id` + `CronRun.owner_agent_id` + `CronTaskDetail.agent_id` 字段扩展 ✅
6. **F-2**: `CronScheduler.agent_id` + `check_once()` agent 过滤 ✅
7. **F-3**: 工具层 `CronCreate`/`CronList`/`CronDelete` 归属过滤 ✅（input_schema 已声明 agent_id；工具函数支持 tool_input.get("agent_id")）

**Phase H+I+J — P1/P2 补齐**（可并行于 F）:
8. **H-1**: `read_cron_tasks_cached()` mtime 轮询实现
9. **I-1**: `is_cron_disabled()` 兼容 `CLAUDE_CODE_DISABLE_CRON` 回退
10. **J-1**: `/cron-trigger` 命令别名
11. **J-2**: `--deep` 集成到 `/cron-list`
12. **F-4 ~ F-5**: teammate 生命周期 + orphaned 清理（依赖 teammate 子系统上线）

**依赖关系图**:
```
Phase G (P0, TUI+CronDispatchBridge)
    ├── G-1: TUI outbox drain ✅
    ├── G-3: TUI is_loading (依赖 G-1)
    └── G-2: CronDispatchBridge ✅ (含三端替换)
Phase F (P1, ownership)
    ├── F-1: 模型扩展 ✅
    ├── F-2: 调度器过滤 ✅
    ├── F-3: 工具层过滤 ✅
    ├── F-4: notify_owner_exited 占位 ⏸ (等待 teammate 子系统)
    └── F-5: cleanup_orphaned_tasks 占位 ⏸ (等待 teammate 子系统)
Phase H (P1, mtime polling) — 无前置依赖, 可随时启动
Phase I (P1, CCB gate) — 无前置依赖, 可随时启动
Phase J (P2, R4补齐) — 无前置依赖, 可随时启动
```

**F-4 / F-5 占位说明（2026-07-22）**:

| 子特性 | 落地状态 | 说明 |
|--------|---------|------|
| F-4 notify_owner_exited | 占位 hook | `CronScheduler.on_owner_exited: Callable[[str], None]` + `notify_owner_exited(agent_id)` 方法已添加；当前为 stub（仅 log + 调 hook），不自动 finalize in-flight run。等 `TeammateManager` 接入后扩展为遍历 owner_agent_id 的 run 并 finalize 为 failed。 |
| F-5 cleanup_orphaned_tasks | 占位 provider + 公开方法 | `CronScheduler.active_agents_provider: Callable[[], set[str]]` + `cleanup_orphaned_tasks()` 公开方法已添加；scheduler 不在 `check_once` 中自动 poll（避免无 source 时噪声）。等 `TeammateManager` 接入后由 caller 调用 `cleanup_orphaned_tasks()` 触发扫描。 |

## §3 实施细节

### 3.1 文件格式

**durable task 文件**（`.clawcodex/cron/scheduled_tasks.json`，由 `models.py:SCHEDULED_TASKS_RELATIVE_PATH` 定义；`read_cron_tasks()` 在主路径不存在时回退读取 `.claude/scheduled_tasks.json` 兼容旧版）:
```json
{
  "version": 1,
  "tasks": [
    {
      "id": "a1b2c3d4", "cron": "0 9 * * 1-5",
      "prompt": "Check my PRs", "recurring": true, "durable": true,
      "created_at": 1700000000000, "updated_at": 1700000000000,
      "last_fired_at": null, "next_fire_at": 1700003600000,
      "expires_at": 1700604800000,
      "jitter": {
        "recurring_frac": 0.1, "recurring_cap_ms": 900000,
        "one_shot_max_ms": 90000, "one_shot_floor_ms": 0,
        "one_shot_minute_mod": 30, "recurring_max_age_ms": 604800000
      }
    }
  ]
}
```

写出使用 snake_case；读取时兼容 snake_case 与 camelCase。

**lock 文件**: `.clawcodex/cron/scheduled_tasks.lock` + `.clawcodex/cron/scheduled_tasks.storage.lock`（由 `models.py:SCHEDULED_TASKS_LOCK_RELATIVE_PATH` / `SCHEDULED_TASKS_STORAGE_LOCK_RELATIVE_PATH` 定义）
```json
{ "sessionId": "uuid", "pid": 12345, "acquiredAt": 1700000000000 }
```

### 3.2 测试计划

| 测试文件 | 覆盖内容 |
|----------|---------|
| `tests/cron/test_parser.py` | 5 字段 cron、range/list/step/name、DoM/DoW OR 语义 |
| `tests/cron/test_tasks.py` | durable/session 分离、文件 schema 兼容、storage lock |
| `tests/cron/test_scheduler.py` | busy gate、on_fire_task dispatch、one-shot 删除、recurring reschedule |
| `tests/cron/test_lock.py` | scheduler lock、storage lock、stale recovery |
| `tests/cron/test_tools_runtime.py` | runtime 替换 fallback、mutating metadata |
| `tests/cron/test_f22_gaps.py` | G1~G10 专项测试 |
| `tests/cron/test_phase_f_ownership.py`（Phase F 新建） | F-1: `CronTask.agent_id`/`CronRun.owner_agent_id`/`CronTaskDetail.agent_id` 字段往返序列化（snake/camel 兼容）；F-2: `CronScheduler(agent_id=...)` check_once 过滤（全局任务对所有 agent 可见 + 归属任务仅 owner 可触发）；F-3: `CronList` 默认仅返回当前 agent + 全局任务、`agent_id="*"` 管理员视图、`CronDelete` 非管理员拒绝删除他 agent 任务、`CronCreate` 自动填充 `agent_id`；F-4: owner 已退出场景写 failed run（`"error": "owner agent exited"`）+ headless 传 `agent_id=None` 降级只调度全局任务；F-5: `cleanup_orphaned_tasks()` 标记孤儿任务 + `CronList` 输出 `status: orphaned` + `status.py:_job_table()` 的 `Orphaned` 列 |
| `tests/cron/test_phase_g_dispatch.py`（Phase G 新建） | G-1: TUI `_drain_cron_outbox()` + `_process_cron_outbox()` + `_run_cron_prompt()` 镜像 headless 行为；G-2: `CronDispatchBridge.drain()/claim()/finalize()` 三端统一调用契约（REPL/headless/TUI 替换前后的输出等价性）；G-3: TUI `is_loading=lambda: in_agent_loop.value` 回调传入后 busy gate 在 agent 响应期间抑制 cron |
| `tests/cron/test_phase_h_mtime.py`（Phase H 新建） | H-1: `read_cron_tasks_cached()` TTL 内同 tick 不重复读、mtime 未变跳过重读、mtime 变化触发重读、文件不存在回退全量读、写路径不主动失效缓存（依靠 mtime 变化）、多 workspace 路径缓存隔离 |
| `tests/cron/test_phase_i_ccb_gate.py`（Phase I 新建） | I-1: `is_cron_disabled()` 仅设 `CLAUDE_CODE_DISABLE_CRON=true` 返回 True；仅设 `CLAWCODEX_DISABLE_CRON=true` 返回 True；两者同时设置以 `CLAWCODEX_DISABLE_CRON` 为准（优先级语义）；两者均未设置返回 False；非布尔值（`"0"`/`"false"`/`"no"`/`"off"`）返回 False |
| `tests/cron/test_phase_j_commands.py`（Phase J 新建） | J-1: `/cron-trigger <id>` 与 `/cron-run <id>` 行为等价（同一 `CronRunTool` 调用、相同出参）、别名解析在 builtins 注册表中可发现；J-2: `/cron-list --deep` 透传 `deep=True` 给 `build_autonomy_status()`、截断与完整输出对照、`/cron-status --deep` / `/cron-runs --deep` 一致行为 |

### 3.3 手工验收流程

**基础流程**（Phase A~E + G1~G10 + D1~D4）:
1. 启动 ClawCodex，确认 cron gate 未禁用
2. `/loop 1m check status` 创建 session-only recurring task
3. `/cron-list` 确认任务存在（ID、human schedule、prompt、recurring、durable）
4. 创建 durable one-shot task，确认 `.clawcodex/cron/scheduled_tasks.json` 写入
5. 构造 due time，确认任务进入 queued/running/completed/failed 记录
6. 用 status/runs 命令查看结果
7. `/cron-delete <id>` 删除任务，确认 session store 与 durable file 更新
8. 重启 CLI，确认 durable task 继续存在，session-only 消失
9. 构造 missed durable one-shot，确认提示用户确认
10. 两个 CLI 实例，确认只有 lock owner 触发任务

**D1~D4 专项验证**:
11. D1: 同一 task 在 1 秒内连续 due 两次，确认仅生成 1 个 run（D1 去重）
12. D2: 手动 kill scheduler 进程，新进程接管锁（D2 PID 活体 + D4 stale recovery）
13. D3: 在 `on_fire_task` 回调中抛出异常，确认 `_in_flight` 释放且后续 due 正常触发
14. D4: 两个 CLI 实例同时启动，查看 `.clawcodex/cron/scheduled_tasks.lock` 确认仅一个 owner

**TUI 专项验证**（TUI outbox drain 接线后）:
15. 在 TUI 模式下启动，`/cron-status` 确认任务存在
16. 等待 due time，确认任务自动触发并显示在输出中

**Phase F 专项验证**（实施后）:
17. 创建 agent-scoped cron，确认另一 agent 的 `/cron-list` 不显示该任务
18. 退出 owner agent，确认 orphaned task 状态变为 `orphaned`
19. headless 模式创建带 `agent_id` 的任务，确认返回 failed run

**Phase H 专项验证**（mtime 缓存实施后）:
20. 写入 durable task，连续两次调用 `read_cron_tasks_cached()`：第二次应跳过重读（mtime 未变），用 `unittest.mock` patch `read_cron_tasks()` 验证调用次数为 1
21. 同一 workspace 下 touch 文件（`os.utime` 改 mtime），确认下次 `read_cron_tasks_cached()` 触发全量重读
22. 并发两 scheduler 实例同 workspace，1 秒 TTL 内应共享缓存条目（用 `threading.Barrier` 同步起跑后比对返回 `list[CronTask]` 标识一致）
23. 删除 durable 文件后调用 `read_cron_tasks_cached()`，确认回退到全量读并返回空列表（不缓存负结果）

**Phase I 专项验证**（CCB 兼容门禁实施后）:
24. 仅设 `CLAUDE_CODE_DISABLE_CRON=true` 启动 CLI，确认 `CronCreate` 工具返回 "Cron is disabled" 提示（CCB 用户环境变量生效）
25. 仅设 `CLAWCODEX_DISABLE_CRON=true` 启动 CLI，确认同上行为（原生变量优先路径）
26. 同时设置两个变量为 `true`，再同时设置 `CLAWCODEX_DISABLE_CRON=false` + `CLAUDE_CODE_DISABLE_CRON=true`，确认 cron 未被禁用（`CLAWCODEX_DISABLE_CRON` 优先级覆盖 CCB 变量）
27. 删除 `CLAWCODEX_DISABLE_CRON`、保留 `CLAUDE_CODE_DISABLE_CRON=0`，确认 cron 未被禁用（非布尔值 `0`/`false`/`no`/`off` 均视为 False）

**Phase J 专项验证**（命令别名实施后）:
28. `/cron-trigger <id>` 手动触发某任务，确认 `/cron-runs` 中新增一条 queued→running→completed 记录；同一任务用 `/cron-run <id>` 再次触发，确认两次 run 的 `workload`/`trigger`/`source_id` 字段一致（别名行为等价性）
29. `/cron-list --deep` 确认完整任务列表不截断；对照 `/cron-list`（不带 `--deep`）确认后者按默认截断阈值输出（截断边界用 `len(tasks) > threshold` 构造足量任务场景）
30. `/cron-status --deep` 与 `/cron-runs --deep` 一致行为验证：三者均透传 `deep=True` 给 `build_autonomy_status()` / `build_autonomy_runs()`

### 3.4 风险与约束

| 风险 | 等级 | 影响 | 缓解措施 |
|------|:----:|------|----------|
| REPL/TUI/headless 三端队列接线需分别验证 | P0 | TUI 模式下 cron 任务不触发执行 | TUI outbox drain 接线后增加专项验收流程（§3.3 第 15-16 步） |
| durable 文件在多会话场景下的热加载稳定性 | P1 | 多进程同时读写 `.clawcodex/cron/scheduled_tasks.json` 导致数据竞争 | D4 调度锁 + storage lock 双重保护；`read_cron_tasks()` 每次全量读确保一致性 |
| TUI 模式缺少 `is_loading` 回调 | P0 | cron 在 agent 响应期间抢跑 | 在 `clawcodex_ext/frontend/tui.py` 中传递 `is_loading` 回调 |
| F-22 不应在只有单元测试通过时标记完成 | P0 | 端到端行为未验证 | 必须通过 §3.3 手工验收流程才能标记完成 |
| D1~D4 集成验证覆盖不全 | P1 | 4 层累计防护的单点测试通过但联动行为未验证 | 已增加 D1~D4 专项验证流程（§3.3 第 11-14 步） |
| Phase F 与 teammate runtime 的时序耦合 | P1 | ownership 行为依赖 teammate 子系统先上线 | Phase F 分步实施：模型扩展 + 调度器过滤可独立交付 |
| 文件路径从上游 `.claude/` 迁移到 `.clawcodex/cron/` 的向后兼容 | P2 | 旧版用户升级后主路径找不到已有任务 | `tasks.py:read_cron_tasks()` 已实现 legacy 回退：主路径 `SCHEDULED_TASKS_RELATIVE_PATH = .clawcodex/cron/scheduled_tasks.json` 不存在时回退读取 `.claude/scheduled_tasks.json`，新写入一律落主路径 |
| Phase H mtime 缓存在写路径的失效竞态 | P1 | `write_cron_tasks()` 用 `os.replace()` 原子替换后，若同 tick 内另一 scheduler 实例缓存条目仍指向旧 mtime，可能返回陈旧任务列表 | 设计上**不**主动失效缓存，依靠 `st_mtime` 变化触发下次重读；`os.replace()` 原子替换保证 mtime 单调变更。专项验收步骤 20-23 验证 TTL/mtime 变化/并发共享/负结果不缓存四类边界 |
| Phase H 全局进程级缓存的 workspace 隔离 | P1 | `_MtimeCache: dict[Path, ...]` 是模块级全局变量，多 workspace 路径应天然隔离，但若同 workspace 被多个相对路径表达式（如 `./.clawcodex/cron/...` vs 绝对路径）引用可能产生重复条目 | `tasks_file_path(workspace_root)` 一律返回 `workspace_root / SCHEDULED_TASKS_RELATIVE_PATH`，调用方传入 `Path.resolve()` 后的 workspace 根；测试需覆盖相对路径与绝对路径并存场景（§3.3 步骤 22） |
| Phase I CCB 兼容回退的优先级语义 | P1 | 同时设置 `CLAWCODEX_DISABLE_CRON` 与 `CLAUDE_CODE_DISABLE_CRON` 时，若优先级未明确可能产生歧义 | 设计明确 `CLAWCODEX_DISABLE_CRON` 优先于 `CLAUDE_CODE_DISABLE_CRON`；专项验收步骤 26 验证优先级覆盖；非布尔值（`0`/`false`/`no`/`off`）一律视为 False 与原 `is_cron_disabled()` 语义一致 |
| Phase J `/cron-trigger` 与 `/cron-run` 别名共存的歧义 | P2 | 两命令共存时用户可能困惑何时该用哪个，且别名解析若不在 builtins 注册表中可发现会导致文档与实际行为脱节 | 设计明确 `/cron-trigger` 为 `/cron-run` 的语义别名（同一 `CronRunTool` 调用、相同出参），二者行为完全等价；专项验收步骤 28 验证等价性；builtins 注册表通过 `LocalCommand(name="cron-trigger", ...)` 显式声明，可用 `/help` 类命令发现 |
| Phase J `--deep` 标志在 `/cron-list` 截断阈值的可观测性 | P2 | 用户无法感知默认截断阈值是多少，`--deep` 跽越截断后的输出差异若无足量任务场景则难以观测 | 专项验收步骤 29 要求构造 `len(tasks) > threshold` 足量任务场景对照；`build_autonomy_status()` 的截断阈值应在 docstring 或 `status.py` 常量中显式标注（实施时补） |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+Phase A~E+CCB 缺口+文件格式+测试） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-21 | **补全特性缺口**：Phase F 详细设计（F-1~F-6）、D1~D4 状态从 📋→✅ 并补充实施细节、R1~R8 状态基于代码审查更新、§2 瓶颈与下一步计划重排、§3 手工验收流程扩展 + 风险表重构 | 代码审查后发现文档与代码状态脱节 |
| 2026-07-21 | **补全二次特性缺口**：Phase F 补全代码级文件变更映射（F-1~F-5 各文件具体变更）、新增 Phase G（TUI 集成 + CronDispatchBridge 统一 + is_loading 传递）、Phase H（mtime 轮询设计）、Phase I（CCB 兼容门禁命名）、Phase J（R4 用户管理入口补齐）、§1.8 文件路径引用修正 + 新增对应 Phase 列、§2.2/§2.3 重构为依赖关系图驱动、§3.3 手工验收扩展 Phase G 专项验证 | 代码审查确认 Phase A~E 正确但缺失 TUI 前端集成、CronDispatchBridge 统一抽象、R4/R6/R8 详细设计，且 Phase F 缺少代码级文件映射 |
| 2026-07-21 | **补全三次特性缺口**：修正 §1.1/§3.1/§3.4 中 `.claude/` 与 `.clawcodex/cron/` 主路径表述冲突（5 处，对照 `models.py:SCHEDULED_TASKS_RELATIVE_PATH` 与 `tasks.py:38` legacy 回退）、§1.8 R2/R4/R5 状态从 🔄 统一为 📋→📝（与对应 Phase G/J `📋 设计就绪` 一致）、§3.2 测试计划表补 Phase F~J 专项测试文件条目（5 个新建 test_phase_*.py）、§3.3 手工验收流程补 Phase H/I/J 专项验证步骤（第 20-30 步）、§3.4 风险表补 Phase H/I/J 风险条目（5 条：mtime 缓存竞态/workspace 隔离/CCB 优先级语义/别名共存歧义/截断阈值可观测性）、§2.1 已完成里程碑补 2026-07-21 两条记录、Phase J 增补 J-3 子节（`/cron-trigger` 与 `/cron-run` 别名共存冲突分析，明确行为等价/注册/文案/弃用策略/命令冲突/帮助可发现性 7 维度设计决定） | 三次代码审查后发现文档与代码现状脱节仍存残留缺口：主路径表述冲突（§1.1 写 `.claude/` 但代码实际主路径是 `.clawcodex/cron/`）、R2/R4/R5 状态语义不一致（🔄 vs 对应 Phase 已 📋 设计就绪）、测试计划/验收流程/风险表缺 Phase H/I/J 专项、Phase J 缺命令冲突分析、里程碑表缺文档更新条目 |

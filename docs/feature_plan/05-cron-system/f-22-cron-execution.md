# F-22: Cron 系统执行引擎

> 状态: 🔄 进行中（Phase A~E ✅, Phase F 待开始）
> 章节: docs/feature_plan/05-cron-system/f-22-cron-execution.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 背景与目标

将 claude-code-best 的生产级别 cron 执行引擎完整迁移到 ClawCodex 的下游扩展层。最终用户应能在 REPL、TUI、headless/print 模式中创建、查看、删除和执行定时任务，并能查看定时任务触发后的运行状态与结果。

`claude-code-best` 的 Cron 行为跨越工具、存储、调度器、CLI skills、REPL/headless 执行队列、autonomy run 记录和 missed-task 安全确认。ClawCodex 当前已有 `clawcodex_ext/cron_system/*` 的核心模块，但尚需将这些模块完整接入真实 CLI 运行路径。F-22 的完成标准必须从"模块存在"提升为"端到端行为与 `claude-code-best` 对齐"。

**目标行为**:
1. 完整 cron 表达式解析（5 字段标准语法）
2. 下次执行时间计算（本地时区）
3. 调度器执行引擎（1秒轮询）
4. 任务持久化（`.claude/scheduled_tasks.json`）
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
|------|---------|------------|
| Cron 工具 | `ScheduleCronTool/CronCreateTool.ts` | schema、cron 校验、durable 处理、返回字段、启用 scheduler |
| Cron 列表 | `ScheduleCronTool/CronListTool.ts` | session + durable 聚合、teammate 过滤、展示字段 |
| Cron 删除 | `ScheduleCronTool/CronDeleteTool.ts` | ID 校验、权限/归属校验、删除语义 |
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
- `durable` 参数被接受但不写入 `.claude/scheduled_tasks.json`
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
- `durable=False` 不写 `.claude/scheduled_tasks.json`
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

##### F-3 工具层可见性

- `CronList` 新增 `agent_id` 过滤参数，默认只返回当前 agent 的任务 + 全局任务
- 管理员（`agent_id="*"`）可查看所有任务
- `CronDelete` 校验归属：非管理员不能删除其他 agent 的任务
- `CronCreate` 自动填充 `agent_id` 为当前 agent

##### F-4 Teammate 生命周期

| 场景 | 行为 |
|------|------|
| teammate 创建 session-only cron | 任务带 `agent_id`，只在该 agent 上下文可见/可删 |
| teammate 已退出（graceful shutdown） | 调度器触发 owned task 时记录 failed run，错误说明 "owner agent exited" |
| teammate 异常退出（crash） | 通过 stale lock 恢复机制发现 owner 失活，标记 orphaned task |
| headless 无 teammate runtime | `CronScheduler.agent_id` 为 None，只调度全局任务；创建带 `agent_id` 的任务时返回 failed run，错误说明无法路由 owner |

##### F-5 清理孤儿任务

- 新方法 `cleanup_orphaned_tasks(workspace_root, active_agents: set[str])`：
  - 遍历所有 `agent_id` 非 None 的任务
  - 如果 `agent_id` 不在 `active_agents` 中，标记为 orphaned
  - Orphaned 任务在 `CronList` 中显示状态 `orphaned`
  - 可配置自动删除（默认保留，人工确认）

##### F-6 实现优先级

| 步骤 | 内容 | 优先级 |
|:----:|------|:------:|
| 1 | `CronTask.agent_id` 字段 + `from_dict`/`to_dict` 兼容 | P1 |
| 2 | `CronScheduler.agent_id` + `check_once` 过滤 | P1 |
| 3 | `CronCreate` 自动填充 `agent_id` | P1 |
| 4 | `CronList`/`CronDelete` 归属过滤 | P1 |
| 5 | headless 无 teammate 降级行为 | P1 |
| 6 | `cleanup_orphaned_tasks` 与调度器集成 | P2 |
| 7 | Teammate 退出/崩溃时自动标记 failed run | P2 |

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| **Phase A** | runtime-first 接线 | ✅ | P0 |
| **Phase B** | 存储与模型语义对齐 | ✅ | P0 |
| **Phase C** | scheduler 语义对齐 | ✅ | P0 |
| **Phase D** | 执行队列与结果追踪 | ✅ | P0 |
| **Phase E** | skills 与用户命令 | ✅ | P0 |
| **Phase F** | teammate/agent ownership | 📋 | P1 |
| **F-1** | 模型扩展（CronTask.agent_id, CronRun.owner_agent_id） | 📋 | P1 |
| **F-2** | 调度器 agent 过滤（check_once agent_id 门控） | 📋 | P1 |
| **F-3** | 工具层可见性（CronList/Delete 归属过滤） | 📋 | P1 |
| **F-4** | Teammate 生命周期（退出/崩溃/无 runtime 降级） | 📋 | P1 |
| **F-5** | 清理孤儿任务（cleanup_orphaned_tasks） | 📋 | P2 |
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

| ID | 缺口 | 状态 | 补齐要求 | 代码现状 |
|----|------|:----:|----------|----------|
| R1 | 真实 frontend/runtime 接线 | ✅ | REPL `_drain_cron_outbox()` 已消费 outbox | `clawcodex_ext/repl/core.py:_drain_cron_outbox()` + `clawcodex_ext/entrypoints/headless.py:_process_cron_outbox()` 均已实现 |
| R2 | scheduled fire 执行队列 | 🔄 | 建立 `CronDispatchBridge`，进入 query pipeline | headless 有 `_drain_cron_outbox()` + `_process_cron_outbox()` 函数，REPL 有 `_drain_cron_outbox()`。但无正式 `CronDispatchBridge` 类，outbox 事件类型为原始 dict 而非 typed event |
| R3 | run lifecycle finalize | ✅ | claim→running→completed/failed/cancelled；补齐字段 | `runs.py:claim_cron_run()` + `finalize_cron_run()` + `update_cron_run_status()` 全链路实现。headless `_claim_cron_task()` 调用 `claim_cron_run()` 并标记 started/failed/completed |
| R4 | 用户管理入口 | 🔄 | trigger detail、manual fire、status/runs richer output | `CronRunTool`（manual fire）+ `get_cron_task_detail()` + `build_autonomy_status/runs()` + `/cron-status`、`/cron-runs`、`/cron-run` 命令均已实现。缺口：`/cron-trigger` 命令别名、`--deep` 在 `/cron-list` 中的集成 |
| R5 | busy gate/filter 语义 | 🔄 | `is_loading`、`assistant_mode`、`filter` 接入 frontend | `scheduler.py:_is_loading_gate()` 已实现，`attach_cron_runtime()` 接收 `is_loading`/`assistant_mode` 参数。但 TUI 前端未传递 `is_loading` 回调 |
| R6 | durable 文件 reload | 📋 | 首期 mtime polling，后续 watcher | 当前每次读文件（`read_cron_tasks()` 从头读），无增量 mtime 轮询或文件 watcher |
| R7 | teammate/agent ownership | 📋 | 保留字段、过滤接口和 headless failed run | 同 Phase F。`CronTask` 模型无 `agent_id` 字段，`CronScheduler` 无 agent 过滤 |
| R8 | CCB-compatible gate 命名 | 📋 | 兼容读取 `CLAUDE_CODE_DISABLE_CRON` | 当前仅读 `CLAWCODEX_DISABLE_CRON`，未回退到 `CLAUDE_CODE_DISABLE_CRON` |

### 1.9 完成标准（端到端）

| 能力 | 完成标准 |
|------|----------|
| 工具可用性 | CronCreate/List/Delete 在 REPL/TUI/headless 使用扩展实现 |
| /loop | 创建 recurring cron，默认 10m，立即执行一次 |
| 管理命令 | `/cron-list` 和 `/cron-delete <id>` 以表格展示 |
| session-only | `durable=False` 任务只存在于当前 session |
| durable | `durable=True` 写入 `.claude/scheduled_tasks.json`，重启可见 |
| 调度器 | 每秒检查 due tasks，持有 `.claude/scheduled_tasks.lock` |
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

### 2.2 当前瓶颈

| 优先级 | 瓶颈 | 原因 | 影响范围 |
|:------:|------|------|----------|
| P0 | TUI outbox drain 未接线 | TUI 前端 (`clawcodex_ext/frontend/tui.py`) 无 cron outbox 消费逻辑 | TUI 模式下 cron 任务不会触发执行 |
| P0 | R2: 无正式 CronDispatchBridge | headless 和 REPL 各有 ad-hoc drain 函数，但无 typed dispatch 类 | 事件类型不统一，新前端需重复实现 drain 逻辑 |
| P0 | R5: TUI 未传递 `is_loading` 回调 | `attach_cron_runtime()` 的 `is_loading` 参数在 TUI 前端未传入 | TUI 模式可能错过 busy gate，cron 在 agent 响应期间抢跑 |
| P1 | Phase F: teammate/agent ownership | `CronTask` 无 `agent_id` 字段，`CronScheduler` 无 agent 过滤 | 多 agent 场景下任务归属混乱 |
| P1 | R6: 无 durable 文件 mtime 轮询 | 每次读全量文件，多会话场景下高并发 I/O | 大文件场景性能瓶颈 |
| P1 | R8: 未兼容 CLAUDE_CODE_DISABLE_CRON | 仅读 `CLAWCODEX_DISABLE_CRON` | 从 CCB 迁移的用户环境变量不生效 |
| P2 | R4: 缺少 `/cron-trigger` 命令别名 | `/cron-run` 已存在但无 `trigger` 别名 | 用户发现成本高 |
| P2 | R4: `--deep` 未集成到 `/cron-list` | `build_autonomy_status()` 支持 `deep` 参数但 `/cron-list` 命令未传递 | 任务列表默认截断 |

### 2.3 下一步计划

1. **P0**: TUI outbox drain 接线 — `clawcodex_ext/frontend/tui.py` 增加 `_drain_cron_outbox()` 类似 headless/REPL
2. **P0**: CronDispatchBridge 正式化 — 将 ad-hoc drain 函数抽象为 typed dispatch 类，统一 REPL/headless/TUI 三端行为
3. **P0**: TUI 传递 `is_loading` 回调 — 防止 cron 在 agent 响应期间抢跑
4. **P1**: Phase F 实施步骤 1-2 — `CronTask.agent_id` 字段 + `CronScheduler` agent 过滤
5. **P1**: R6 durable 文件 mtime 轮询 — 减少全量读取 I/O
6. **P1**: R8 兼容 `CLAUDE_CODE_DISABLE_CRON` — 环境变量回退读取
7. **P2**: Phase F 步骤 3-4 — 工具层归属过滤
8. **P2**: R4 补齐 — `/cron-trigger` 别名、`--deep` 集成到 `/cron-list`

## §3 实施细节

### 3.1 文件格式

**durable task 文件**（`.claude/scheduled_tasks.json`）:
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

**lock 文件**: `.claude/scheduled_tasks.lock` + `.claude/scheduled_tasks.storage.lock`
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

### 3.4 风险与约束

| 风险 | 等级 | 影响 | 缓解措施 |
|------|:----:|------|----------|
| REPL/TUI/headless 三端队列接线需分别验证 | P0 | TUI 模式下 cron 任务不触发执行 | TUI outbox drain 接线后增加专项验收流程（§3.3 第 15-16 步） |
| durable 文件在多会话场景下的热加载稳定性 | P1 | 多进程同时读写 `.clawcodex/cron/scheduled_tasks.json` 导致数据竞争 | D4 调度锁 + storage lock 双重保护；`read_cron_tasks()` 每次全量读确保一致性 |
| TUI 模式缺少 `is_loading` 回调 | P0 | cron 在 agent 响应期间抢跑 | 在 `clawcodex_ext/frontend/tui.py` 中传递 `is_loading` 回调 |
| F-22 不应在只有单元测试通过时标记完成 | P0 | 端到端行为未验证 | 必须通过 §3.3 手工验收流程才能标记完成 |
| D1~D4 集成验证覆盖不全 | P1 | 4 层累计防护的单点测试通过但联动行为未验证 | 已增加 D1~D4 专项验证流程（§3.3 第 11-14 步） |
| Phase F 与 teammate runtime 的时序耦合 | P1 | ownership 行为依赖 teammate 子系统先上线 | Phase F 分步实施：模型扩展 + 调度器过滤可独立交付 |
| 文件路径从 `.claude/` 迁移到 `.clawcodex/cron/` 的向后兼容 | P2 | 旧版用户升级后无法找到已有任务 | `read_cron_tasks()` 应回退读取 `.claude/scheduled_tasks.json` |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+Phase A~E+CCB 缺口+文件格式+测试） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-21 | **补全特性缺口**：Phase F 详细设计（F-1~F-6）、D1~D4 状态从 📋→✅ 并补充实施细节、R1~R8 状态基于代码审查更新、§2 瓶颈与下一步计划重排、§3 手工验收流程扩展 + 风险表重构 | 代码审查后发现文档与代码状态脱节 |

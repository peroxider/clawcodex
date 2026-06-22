# 解耦方案 · ClawCodex Decoupling Plan

> **目标**：将 `src/` 中所有 ClawCodex 定制逻辑迁至 `clawcodex_ext/` 与 `extensions/`，使上游（`src/upstreamproxy/...`）与本地 `src/` 的差异仅保留**架构重构**、**bug fix** 和**纯新增子系统**，所有「功能增量」通过扩展层注入。
>
> **最近更新**：2026-06-23，Phase 2-D 子系统整迁批落地。3 个缺失 ext 子系统（`computer_use` / `kairos` / `langfuse`）从 src 迁至 `clawcodex_ext/services/`，`session_migrate` 与 `agent_mention_completer` 同步迁移；累计新增 17 个 src facade 文件；内容级 modified 文件从 578 降至 504；`regenerate_patches.py` 重生成 619 个补丁（byte-identical 幂等）；稳定性门禁 6 阶段 245 passed + orchestrator 523 passed 全绿。前期 Phase 2-A/B/C 与 F-48/F-49/F-83/F-85/F-86/F-84/F-61/F-63/F-60/F-72/F-75、SR-5.1 仍为合并基线。

---

## 1. 当前状态总览

### 1.1 文件规模（截至 2026-06-23）

| 维度 | 当前数字 | 原计划数字 | 变化 |
|---|---|---|---|
| 上游文件（`src/upstream/`） | **2553** `.py` | 566 | +1987（上游 rebased 多次，合并入更大版本） |
| `src/upstreamproxy/` | **6** `.py` | — | 新增：上游兼容代理层 |
| 本地 `src/`（排除 upstream & upstreamproxy） | **631** `.py` | 594 | +37（新增子系统减去已迁出的 37 个） |
| 扩展层 `clawcodex_ext/` | **584** `.py` | 232 | +352（Phase 2-A/B/D 批量 facade 化净增长，本轮 +17：3 个子系统 + session_migrate + agent_mention_completer） |
| 第三层扩展 `extensions/` | **142** `.py` | （未规划） | 新增独立扩展层（orchestrator、visualizer、remote_api 等） |
| **采用 lazy `__getattr__` proxy 化的文件** | **117** | ~45 | +72（Phase 2-A 新增 `transcript.py` 等） |
| **采用 2-3 行 wildcard re-export facade 的文件** | **149** | — | +17（Phase 2-D 新增 computer_use/kairos/langfuse/session_migrate/agent_mention_completer） |
| **采用 sys.modules swap facade 的文件** | **~15** | — | 新增统计项（`agent_tool_utils.py` / `query.py` 等需要保留 `_xxx` 私有符号的场景） |
| **采用 sys.modules swap / 显式 list re-export facade 的文件** | **~18** | — | Phase 2-D 新增 `session_migrate.py`（需导出 `handle_session_migrate_cli`） |
| **含本地增量但未 facade 化的文件** | **~13** | ~35 | -22（已 facade 化 ~25 个 + Phase 2-D 17 个新增） |
| **与上游内容级不同的文件数** | **504** | 578 | -74（Phase 2-D；74 个仅行尾差异已剥离） |
| **补丁队列总数** | **619** patches | 161 | +458（含 `--allow-deletes` 模式生成的 delete patch） |
| **补丁队列体积** | **3.7 MB** | ~1 MB | 重生成后 byte-identical 幂等 |

### 1.2 已固化的解耦模式

```
Pattern A — 纯 re-export adapter（7 个）
  src/agent/_outlines_adapter.py        → clawcodex_ext.agent._outlines_adapter
  src/hooks/_pluggy_adapter.py          → clawcodex_ext.hooks._pluggy_adapter
  src/permissions/_treesitter_adapter.py → clawcodex_ext.permissions._treesitter_adapter
  src/settings/pydantic_adapter.py      → clawcodex_ext.settings.pydantic_adapter
  src/skills/_frontmatter_adapter.py    → clawcodex_ext.skills._frontmatter_adapter
  src/context_system/_gitpython_adapter.py → clawcodex_ext.context_system._gitpython_adapter
  src/providers/_litellm_adapter.py     → extensions.providers_ext

Pattern B — lazy __getattr__ proxy（117 个，~8,000 行 → 平均 ~70 行）
  src/entrypoints/{headless,tui}.py                 (原 667/230L → 25/26L)
  src/entrypoints/orchestrator.py                   (lazy proxy)
  src/cli.py                                        (compatibility facade, 116L)
  src/cost_tracker.py                               (facade, 95L)
  src/providers/__init__.py                         (通过 __getattr__ 代理至 factory)
  src/repl/core.py / ui_host.py                     (lazy proxy)
  src/permissions/cycle.py                          (lazy proxy)
  src/command_system/* (10 files)                   (Phase 9 整体迁移)
  src/context_system/prompt_assembly.py             (lazy proxy)
  src/agent/transcript.py                           (lazy proxy, 37L) ✅ Phase 2-A
  src/tui/* (~40 files)                             (Phase 1-3 整体迁移)
  src/services/cost_tracker.py / pricing.py / tail_follower.py
  src/services/templates/{registry,models,resolver,...}.py
  src/services/ultraplan/{executor,store,...}.py
  …以及 80+ 其他文件

Pattern C — sys.modules swap facade（~15 个，~15 行）
  解决 `_xxx` 私有符号在 wildcard re-export 中被静默丢弃的问题。
  src/agent/agent_tool_utils.py                     (17L) ✅ Phase 2-A
  src/query/query.py                                (17L) ✅ Phase 2-A
  …以及 10+ 其他需要保留 inspect.getsource 兼容性的文件

Pattern D — wildcard re-export facade（132 个，2-3 行）
  src/services/{channels,swarm,templates,ultraplan,context_collapse,compact}/* (54 文件) ✅ Phase 2-B
  src/agent/agent_definitions.py
  src/hooks/* (9 文件)
  src/permissions/* / bash_parser/*
  src/context_system/{__init__,builder,cache_boundary,...}.py
  …以及 100+ 其他文件

Pattern E — 完整 facade / thin wrapper（含 Pattern C 之外的复杂包装）
  仅在 ext 实现有显著扩展而上游 API 又必须保留时使用：
  src/agent/registry.py / session.py
  src/agent/agent_definitions.py / parse_agent_markdown.py
  src/query/{engine,agent_loop_compat}.py
  src/services/compact/{pipeline,snip_compact}.py
  src/services/context_collapse/engine.py
```

### 1.3 F-48 / F-49 / Phase 2 已完成阶段

| 阶段 | commit | 主要工作 |
|---|---|---|
| F-48 Phase 0 | `5e3bf0b4` | move 30 pure-new files from src/ to clawcodex_ext/ |
| F-48 Phase 1-3 | `b552de08` / `eef54e50` / `1cfba615` | lazy __getattr__ facades for entrypoints + cycle；decouple repl/core + prompt_assembly；整体包迁移 tui/ + command_system/ |
| F-48 Phase 1-3 | `0917fbc4` | 3 more decoupling: tool registrations, provider info, resume_with_tail |
| F-48.1 | `8b7cddf3` | Adapter 统一解耦：Protocol + Registry + 6 个 adapter 重构 |
| F-48 Phase 9 audit | `4be747ec` | 19 个文件 KEEP 决策完成 |
| F-48 cleanup | `6518dab5` | 移除 src/ 下的 facade 委托层，测试文件直连 ext |
| F-49 P0–P5 | `69f150c9` ~ `c721efd0` | session 存储统一为 transcript + metadata；takeover / attach / resume / CLI / takeover socket |
| F-83 Ultraplan | `f32e6b06` | 新增 hierarchical plan + step state machine |
| F-85 Templates | `fe681d49` | 新增 reusable agent configuration templates |
| F-86 Kairos / Periodic | `24dcee36` | 新增定时任务与周期任务引擎 |
| F-84 Context Collapse | `4b4f42cb` | 新增 trigger + summary + store 三段式引擎 |
| F-61 Computer Use | `e2c11036` | 新增跨平台屏幕操控 |
| F-63 Channels | `d015f7bb` (原) → `df3b9738` (迁 ext) | 新增 Discord / Slack / 飞书 通知；2026-06-22 整体迁至 `clawcodex_ext/services/channels/` |
| F-60 Pipe IPC | `a6a08b3f` | 新增进程间管道通信 |
| F-72 Multi-API | `43a24dc8` | 原生适配器扩展 P72-A/B/C/D/E |
| F-75 Tool/Skill Stats | `ba922dcd` | 跨会话调用统计 |
| SR-5.1 社区雷达 | `b81a267a` / `51b16b74` | Phase 1–4：registry/fetcher/extractor/classifier/dedup/scorer/reporter + LLM + Jinja2 + Cron |
| **Phase 2-A 5 个高优先级文件** ✅ | `df3b9738` / `273ee452` 等 | `agent_tool_utils.py` (sys.modules swap, 17L) + `transcript.py` (lazy proxy, 37L) + `templates/*` (9L facade) + `ultraplan/*` (facade) + `query.py` (sys.modules swap, 17L) 全部退化为 < 100 行 facade |
| **Phase 2-B 批量 facade 化** ✅ | `1738670e` / `beb9624e` / `5892e5e6` / `746be797` / `43870e45` / `0dacfa8d` / `273ee452` / `5b9b8467` | swarm 拆分至 4 个 refactor commit（mailbox/team_file/membership → helpers/permissions/teammate → leader_permission_bridge facade → session persist 同步）；channels 整体迁 ext；context_collapse 整体迁 ext；query 拆分为 hook_registry/outbox_types/recovery_strategies |
| **Phase 2-C 路径修正** ✅ | `0dacfa8d` | chore: 23 个 R100 重命名 + templates/compact/ultraplan 整体迁 ext（**3 个包共用一个 commit，按用户决定不再 `git reset` 拆分**） |
| **Phase 2-D 子系统整迁批** ✅ | 本轮 | 3 个缺失 ext 子系统从 src 迁至 `clawcodex_ext/services/`：`computer_use/`（6 文件 13KB）、`kairos/`（5 文件 25KB）、`langfuse/`（3 文件 30KB）；`session_migrate.py`（17.8KB）迁 `clawcodex_ext/services/`；`agent_mention_completer.py` 迁 `clawcodex_ext/utils/` 并保留 `src/repl/` 转发；`swarm/leader_permission_bridge.py` ext 端 892B 残缺 stub 修复为 9.4KB 完整实现；累计 17 个 src facade 文件新增；内容级 modified 文件 578 → 504（−74）；`regenerate_patches.py --allow-deletes` 幂等生成 619 个补丁（3.7MB，byte-identical）；Stage 1-6 全绿 + orchestrator 523 passed |

### 1.4 新增的纯子系统（无上游对应物，不参与解耦）

> 这些目录是**新增能力**，与上游 diff 不存在"差量"，应在 `extensions/` 或 `clawcodex_ext/` 长期保留。

```
# ✅ 已迁至 clawcodex_ext/services/（src/ 仅留 facade）
clawcodex_ext/services/channels/         F-63 多通道通知 (9 文件, src/ 9 个 3 行 facade)
clawcodex_ext/services/swarm/            多 agent 协同 (8 文件, src/ 9 个 facade + 1 个 leader_permission_bridge.py 模块级 _callbacks 例外) ✅ Phase 2-B
clawcodex_ext/services/templates/        F-85 配置模板 (10 文件, src/ 仅 __init__.py facade)
clawcodex_ext/services/ultraplan/        F-83 多层计划 (7 文件, src/ 仅 __init__.py facade)
clawcodex_ext/services/context_collapse/ F-84 三段式压缩 (8 文件, src/ 8 个 3 行 facade)
clawcodex_ext/services/compact/          压缩管道 (15 文件, src/ 2 个 11 行 facade)
clawcodex_ext/services/computer_use/     F-61 屏幕操控 (8 文件含 platform/, src/ 6 文件 facade) ✅ Phase 2-D
clawcodex_ext/services/kairos/           F-86 定时调度 (6 文件, src/ 6 文件 facade) ✅ Phase 2-D
clawcodex_ext/services/langfuse/         Langfuse 集成 (4 文件, src/ 4 文件 facade) ✅ Phase 2-D
clawcodex_ext/services/session_migrate.py F-49 P5-H 会话格式迁移 (1 文件 17.8KB) ✅ Phase 2-D
clawcodex_ext/utils/agent_mention_completer.py @agent- 自动补全 (1 文件, src/utils + src/repl/ 双 facade) ✅ Phase 2-D

# 🔄 双位置（src/ + ext/ 均有），待统一为单 ext 入口
src/services/analytics/                  事件埋点 (F-?) [4 src | 4 ext]
src/services/api/                        API 适配层 [7 src | 7 ext]
src/services/chrome/                     Chrome 自动化 [8 src | 8 ext]
src/services/oauth/                      第三方 OAuth [2 src | 2 ext]
src/services/periodic/                   F-86 周期任务 [1 src | 1 ext]
src/services/pipe_ipc/                  F-60 进程管道 [6 src | 6 ext]
src/services/voice/                      语音 I/O [3 src | 3 ext]

# ❌ 仍在 src/（待迁 ext）
src/services/ide/                        IDE 适配 (5 文件)
src/services/mcp/                        MCP 协议 (32 文件 — 单一最大残余)
src/services/tool_execution/             工具执行 (6 文件)
```

---

## 2. Phase 1 — 已完成 ✅（归档）

### 2.1 F-48 Phase 0 — 纯新增文件整迁

> 状态：**已完成**（`5e3bf0b4`）

将纯新增（与上游无对应）的 30 个文件从 `src/` 迁移到 `clawcodex_ext/`。迁移后这些文件不再出现在 `src/` 中，与上游 `diff` 完全消失。

### 2.2 F-48 Phase 1-3 — entrypoints / cycle / TUI / command_system facade 化

> 状态：**已完成**（`b552de08`、`eef54e50`、`1cfba615`、`0917fbc4`）

- `entrypoints/{headless,tui,orchestrator}.py` 全部变为 lazy proxy（25–26 行）
- `repl/core.py`、`repl/ui_host.py` 变为 lazy proxy
- `tui/*`（~40 文件）整体迁移到 `clawcodex_ext/tui/`，src 仅保留 thin facade
- `command_system/*`（10 文件）整体迁移，src 仅保留 thin facade
- `context_system/prompt_assembly.py`、`permissions/cycle.py` 变为 lazy proxy

### 2.3 F-48.1 — Adapter 统一解耦

> 状态：**已完成**（`8b7cddf3`）

所有 `*_adapter.py` 改用 `Protocol + Registry` 模式，新增/移除不再修改 adapter 文件本身，而是注册到 `extensions.capabilities.*_protocol`。

### 2.4 F-48 cleanup — 移除冗余委托层

> 状态：**已完成**（`6518dab5`）

`6518dab5 refactor: 移除 src/ 下的 facade 委托层，测试文件直连 ext` —— 删除了 src/ 下与 ext 同名的纯委托层文件，测试改为 `import clawcodex_ext.x as x`，进一步减小 src/ 体积。

### 2.5 F-49 — Session 存储统一

> 状态：**已完成**（`bdc57c06`、`c721efd0`、`780749ec` 等）

- Session.load 简化为读 transcript + metadata JSON
- JSONL cost 恢复统一路径
- Phase 0.4.6 递归 resume 一致性验收

### 2.6 F-72 / F-75 — Provider & Stats 扩展

> 状态：**已完成**（`43a24dc8`、`ba922dcd`）

- F-72：DeepSeek prefix cache / tool arg recovery 等 P72-A/B/C/D/E 全部在 `extensions/providers_ext/`
- F-75：Tool/Skill 跨会话调用统计 —— 在 `clawcodex_ext/tool_stats.py` 暴露

### 2.7 Phase 2-A — 5 个高优先级文件解耦

> 状态：**已完成** ✅

| 文件 | 目标态 | 当前态 (2026-06-23) | 提交 |
|---|---|---|---|
| `src/agent/agent_tool_utils.py` | `< 100 行 facade` | 17 行 sys.modules swap facade (Pattern C) | Phase 2-A |
| `src/agent/transcript.py` | `< 100 行 facade` | 37 行 lazy proxy (Pattern B) | Phase 2-A |
| `src/services/templates/*` | `clawcodex_ext/services/templates/` | src 仅留 `__init__.py` (9 行 facade, Pattern D) | `0dacfa8d` |
| `src/services/ultraplan/*` | `clawcodex_ext/services/ultraplan/` | src 仅留 `__init__.py` (facade) | `0dacfa8d` |
| `src/query/query.py` | `< 100 行 facade` | 17 行 sys.modules swap facade (Pattern C) | Phase 2-A |

**三种 facade 形态**（详见 §7 选型决策表）：
- **sys.modules swap** (Pattern C, ~15 行)：用于 `agent_tool_utils.py` / `query.py` —— 保留 `_xxx` 私有符号供测试 `inspect.getsource()` 访问
- **lazy `__getattr__` proxy** (Pattern B, 30-40 行)：用于 `transcript.py` —— 显式 `__all__` 列出公共符号，访问时按需导入
- **wildcard re-export** (Pattern D, 2-3 行)：用于 `services/{templates,ultraplan,...}/*` —— 子模块无副作用时可一行 facade

---

## 3. Phase 2 — 已完成 + 持续

### 3.1 `src/agent/*`（~20 个文件）

下表仅列出**含本地增量**的高优先级文件；其余 ~10 个文件（`__init__.py`、`background_runner.py`、`background_state.py`、`constants.py`、`conversation.py`、`filter_agents_by_mcp.py`、`load_agents_dir.py`、`load_plugin_agents.py`、`prompt.py`、`subagent_context.py`、`routing.py`、`report_store.py`、`_outlines_adapter.py`）多数保留上游原样或低优先级。

| 文件 | 当前行数 | 内联增量 | 解耦方案 |
|---|---|---|---|
| `agent_definitions.py` | 590 | 内置 agent 列表 + 解析逻辑 | `clawcodex_ext/agent/agent_definitions.py` 已存在，src 完全剥离为 facade |
| `parse_agent_markdown.py` | 702 | frontmatter 字段映射扩展 | `clawcodex_ext/agent/markdown_ext.py`：`register_field_map()` |
| `session.py` | 623 | F-49 后的 `load` 扩展 | `clawcodex_ext/agent/session_ext.py` 已存在，src 完全剥离为 facade |
| `run_agent.py` | 778 | agent 启动逻辑 | 拆分 `AgentRunner` → `extensions/orchestrator/agent_runner.py` |
| `resume_agent.py` | 771 | resume 流程 | `clawcodex_ext/agent/resume_ext.py` |
| `foreground_promotion.py` | 755 | background → foreground 转换 | `clawcodex_ext/agent/foreground_ext.py` |
| `fork_subagent.py` | 798 | sub-agent 派生 | `clawcodex_ext/agent/fork_ext.py` |
| ~~`agent_tool_utils.py`~~ | ~~17~~ | ✅ Phase 2-A | facade（sys.modules swap） |
| ~~`transcript.py`~~ | ~~37~~ | ✅ Phase 2-A | facade（lazy proxy） |

### 3.2 `src/query/*`（10 个文件，~3,200 行）

| 文件 | 行数 | 内联增量 | 解耦方案 |
|---|---|---|---|
| ~~`query.py`~~ | ~~17~~ | ✅ Phase 2-A | facade（sys.modules swap） |
| `engine.py` | 126 | query engine dataclass | 整体迁 `clawcodex_ext/query/engine.py`，src/ 留 facade |
| `agent_loop_compat.py` | 148 | 适配层 | 迁 `clawcodex_ext/query/agent_loop_compat.py` |
| `streaming.py` | 132 | 流中间件 | `clawcodex_ext/query/stream_middleware.py`（原 §2.12 已规划） |
| `stop_hooks.py` | 134 | stop hook | `clawcodex_ext/query/stop_hooks_ext.py` |
| `transitions.py` | 136 | 状态迁移 | `clawcodex_ext/query/transitions_ext.py`（注：2026-06 已有 `recovery_strategies.py` 拆分 commit `273ee452`） |
| `token_budget.py` | 138 | token 预算 | `clawcodex_ext/query/token_budget_ext.py` |
| `config.py` | 126 | query 配置 | `clawcodex_ext/query/config_ext.py` |
| `deps.py` | 122 | 依赖注入 | 保留上游原样 |
| `__init__.py` | 1495 | package marker | 含 `hook_registry` / `outbox_types`（已迁 `clawcodex_ext/query/`） |

### 3.3 `src/services/{templates,ultraplan,context_collapse,compact}` ✅ **已完成**

> **状态**：已全部迁至 `clawcodex_ext/services/`，src/ 仅留 facade。

| 包 | ext 规范化实现 | src 残留 | 提交 |
|---|---|---|---|
| `templates` | 10 个 .py (bootstrap/built_in/discovery/registry/resolver/schema/persistence/models/exceptions/__init__) | `__init__.py` (9 行 facade) | `0dacfa8d` |
| `ultraplan` | 7 个 .py | `__init__.py` (facade) | `0dacfa8d` |
| `context_collapse` | 8 个 .py | 8 个 3 行 facade | `43870e45` |
| `compact` | 15 个 .py (autocompact/compact/prompt/pipeline/...) | `__init__.py` + `pipeline.py` (各 11 行 facade) | `0dacfa8d` |

### 3.4 `src/services/{channels,swarm,...,tool_execution}` 状态总览

| 状态 | 包 | src 残留 | ext 已有 | 决策 |
|---|---|---|---|---|
| ✅ **已迁** | `channels` | 9 个 3 行 facade | 9 个 .py | `df3b9738` |
| ✅ **已迁** | `swarm` | 9 个 facade + 1 个 `leader_permission_bridge.py` (282 行, 模块级 `_callbacks` 例外) | 8 个 .py | `746be797` / `5892e5e6` / `1738670e` / `beb9624e` |
| ✅ **已迁** | `templates` | 1 facade | 10 个 .py | `0dacfa8d` |
| ✅ **已迁** | `ultraplan` | 1 facade | 7 个 .py | `0dacfa8d` |
| ✅ **已迁** | `context_collapse` | 8 个 facade | 8 个 .py | `43870e45` |
| ✅ **已迁** | `compact` | 2 个 facade | 15 个 .py | `0dacfa8d` |
| 🔄 **双位置** | `analytics` | 4 | 4 | src/ 内容应审，可整体迁 ext |
| 🔄 **双位置** | `api` | 7 | 7 | 同上 |
| 🔄 **双位置** | `chrome` | 8 | 8 | 同上 |
| 🔄 **双位置** | `oauth` | 2 | 2 | 同上 |
| 🔄 **双位置** | `periodic` | 1 | 1 | 同上 |
| 🔄 **双位置** | `pipe_ipc` | 6 | 6 | 同上 |
| 🔄 **双位置** | `voice` | 3 | 3 | 同上 |
| ✅ **已迁** | `computer_use` | 6 个 facade | 8 个 .py（含 platform/） | Phase 2-D 本轮 |
| ✅ **已迁** | `kairos` | 6 个 facade | 6 个 .py | Phase 2-D 本轮 |
| ✅ **已迁** | `langfuse` | 4 个 facade | 4 个 .py | Phase 2-D 本轮 |
| ✅ **已迁** | `session_migrate`（单文件） | `services/session_migrate.py` 1 个 facade | `services/session_migrate.py` 1 个 17.8KB | Phase 2-D 本轮 |
| ✅ **已迁** | `agent_mention_completer`（单文件） | `utils/` + `repl/` 双 facade | `utils/agent_mention_completer.py` | Phase 2-D 本轮 |
| ❌ **未迁** | `ide` | 5 | 0 | 待迁 `clawcodex_ext/services/ide/` |
| ❌ **未迁** | `mcp` | 32 | 0 | 单一最大残余，单独评估是否要 facade 化 |
| ❌ **未迁** | `tool_execution` | 6 | 0 | 待迁 `clawcodex_ext/services/tool_execution/` |

### 3.5 `src/services/api/*`（7 个文件）— 已在双位置

| 文件 | 决策 |
|---|---|
| `claude.py`、`provider_config.py`、`retry.py`、`tool_normalization.py`、`errors.py`、`logging.py` | 评估后多数为上游原样，少量增量已可走 ext；统一后 src/ 退化为 facade |

### 3.6 `src/auth/*`、`src/permissions/*`、`src/buddy/*`、`src/skills/*`、`src/memdir/*`、`src/context_system/*`

按 §1.2 的 Pattern B/D 继续推进；当前：
- `src/auth/{auth,aws,claude_ai,gemini,oauth}.py` —— 4–6 个文件保留上游核心，OAuth 扩展迁 `clawcodex_ext/auth/`
- `src/permissions/check.py`、`src/permissions/bash_parser/*` —— 多数已 facade 化（132 个 wildcard re-export 中包含）
- `src/buddy/{companion,feature,notification,observer,prompt,soul,sprites,types}.py` —— 7 个文件已迁 `clawcodex_ext/buddy/`
- `src/skills/_frontmatter_adapter.py` 等 —— 已 Pattern A
- `src/memdir/*` —— 8 个文件已迁 `clawcodex_ext/memdir/`
- `src/context_system/*` —— 多数 facade 化（builder/cache_boundary/context_analyzer/memory_prefetch/models/system_prompt_cache/workspace_snapshot）

### 3.7 `src/cli_core/*`、`src/bootstrap/*`、`src/state/*`

- `cli_core/{exit,ndjson,structured_io}.py` —— 已迁 `clawcodex_ext/cli_core/`
- `bootstrap/state.py` —— 8 行小工具，保留上游
- `state/*` —— 多数是上游原样，少量增量迁 ext

### 3.8 `src/{assistant,bridge,keybindings,models,moreright,native_ts,outputStyles,plugins,reference_data,remote,schemas,screens,server,tasks,transports,vim}/*`

> 决策：这些目录**不是解耦对象**——多数是上游原样或独立子系统。`bridge/*`（42 文件）已被重构精简，差异主要在 `bridge_enabled.py` / `capacity_wake.py` / `repl_bridge.py` 等少量文件中，可在 `extensions/bridge/` 中扩展。`transports/*` 3 文件已迁 `extensions/ports/transports/`。

---

## 4. 当前需要立即处理的 5 个高优先级文件

> 原 §4.1 / §4.2 / §4.3 / §4.4 / §4.5 全部已完成 ✅。Phase 2-D 后剩余 ~13 个非 facade 文件，下方为基于当前状态重排的**新一轮** Top 5。

| 排序 | 文件 | 行数 | 风险 | 建议方案 |
|---|---|---|---|---|
| 1 | `src/services/mcp/*` (32 文件) | ~5,000+ | 上游冲突面积最大 | 评估是否纯新增，若否则按 services/ 双位置策略迁 ext |
| 2 | `src/services/ide/*` (5 文件) | ~1,500 | IDE 适配是上游无对应物 | 整体迁 `clawcodex_ext/services/ide/` |
| 3 | `src/services/tool_execution/*` (6 文件) | ~1,000 | 工具执行是上游无对应物 | 整体迁 `clawcodex_ext/services/tool_execution/` |
| 4 | `src/agent/agent_definitions.py` | 590 | 上游反复改 agent 列表 | 迁 `clawcodex_ext/agent/agent_definitions.py`，src 留 facade |
| 5 | `src/agent/run_agent.py` | 778 | F-37 自动跑逻辑 | 拆 `AgentRunner` → `extensions/orchestrator/agent_runner.py` |

---

## 5. 不可解耦的差异（保持原样）

| 类别 | 说明 | 示例 |
|---|---|---|
| **架构重构** | 代码被精简/外迁到 ext | `bridge/repl_bridge.py` (-312L)、`bridge/bridge_main.py` (-257L)、`buddy/__init__.py` (-97L) |
| **新增子系统** | 上游不包含的全新功能 | `src/services/{ide,mcp,tool_execution}`（Phase 2-D 后剩余待迁）；`src/services/{channels,swarm,templates,ultraplan,context_collapse,compact,computer_use,kairos,langfuse}` 已迁 ext 仅留 facade |
| **bug fix** | 修复了上游遗留 bug | `b88a040d` TUI ghost_suggestion 渲染初始化；`c13a0395` chat_stream fallback；`b0d39943` /provider 补全回归修复 |
| **依赖调整** | build / requirements | `pyproject.toml`、`setup.cfg` |
| **纯注释/格式** | 不影响语义 | docstring 更新 |

---

## 6. 实施路线图

### Phase 2-A ✅ **已完成**

```
1. ✅ src/agent/agent_tool_utils.py          → clawcodex_ext/agent/agent_tool_utils.py + sys.modules swap facade (17L)
2. ✅ src/agent/transcript.py                → clawcodex_ext/agent/transcript.py + lazy proxy facade (37L)
3. ✅ src/services/templates/*               → clawcodex_ext/services/templates/* + 9L facade
4. ✅ src/services/ultraplan/*               → clawcodex_ext/services/ultraplan/* + facade
5. ✅ src/query/query.py                     → clawcodex_ext/query/query.py + sys.modules swap facade (17L)
```

**验证标准**：
- ✅ 5 个 src 文件全部退化为 < 100 行 facade
- ✅ `pytest tests/stability_gate/ -q --tb=short -x` 通过（245/245）
- ✅ `pytest tests/clawcodex_ext/ -q --tb=short -x` 通过
- ✅ 净减少 src/ 行数：5 个大文件 → 5 个 < 100 行 facade

### Phase 2-B ✅ **已完成** — services/ + query/ 批量 facade 化

```
✅ src/services/swarm/*        → clawcodex_ext/services/swarm/* (4 个 refactor commits)
✅ src/services/channels/*     → clawcodex_ext/services/channels/* (df3b9738)
✅ src/services/context_collapse/* → clawcodex_ext/services/context_collapse/* (43870e45)
✅ src/services/{templates,ultraplan,compact}/* → clawcodex_ext/services/* (0dacfa8d bundled)
✅ src/query/{hook_registry,outbox_types,recovery_strategies} → clawcodex_ext/query/* (273ee452)
```

**当前 ~30 个非 facade 文件聚焦于**：
```
src/agent/{agent_definitions,session,parse_agent_markdown,run_agent,resume_agent,foreground_promotion,fork_subagent}.py
src/query/{engine,agent_loop_compat,streaming,stop_hooks,transitions,token_budget,config}.py
src/services/{computer_use,kairos,ide,langfuse,mcp,tool_execution}/*  (尚未迁 ext)
```

### Phase 2-C ✅ **已完成** — 路径修正 + 长尾收口

```
✅ src/services/{computer_use,kairos,langfuse}/*  → clawcodex_ext/services/* (本轮 Phase 2-D)
✅ src/services/session_migrate.py                → clawcodex_ext/services/session_migrate.py (本轮 Phase 2-D)
✅ src/utils/agent_mention_completer.py           → clawcodex_ext/utils/agent_mention_completer.py (本轮 Phase 2-D)
✅ src/repl/agent_mention_completer.py            → src/utils/ 双 facade
✅ src/services/swarm/leader_permission_bridge.py ext 端 892B 残缺 stub 修复为 9.4KB 完整实现
```

### Phase 2-D ✅ **已完成** — 缺失 ext 子系统整迁批（2026-06-23 本轮）

> 状态：**已完成** ✅。3 个先前 ext 端缺失的子系统从 src/ 整迁至 `clawcodex_ext/services/`，外加 2 个独立单文件迁移。

```
✅ src/services/computer_use/        (9 文件, ~13KB)  → clawcodex_ext/services/computer_use/  (含 platform/)
✅ src/services/kairos/              (6 文件, ~25KB)  → clawcodex_ext/services/kairos/
✅ src/services/langfuse/            (4 文件, ~30KB)  → clawcodex_ext/services/langfuse/
✅ src/services/session_migrate.py   (1 文件, 17.8KB) → clawcodex_ext/services/session_migrate.py
✅ src/utils/agent_mention_completer.py  (1 文件, ~4KB)  → clawcodex_ext/utils/agent_mention_completer.py
✅ src/services/swarm/leader_permission_bridge.py ext 端 892B 残缺 stub 修复为 9.4KB
```

**新增 17 个 src facade**（位于 `src/services/{computer_use,kairos,langfuse}/`、`src/services/session_migrate.py`、`src/services/swarm/leader_permission_bridge.py`、`src/utils/agent_mention_completer.py`、`src/repl/agent_mention_completer.py`）。

**关键修复**：
- `src/services/swarm/leader_permission_bridge.py` ext 端是 892B 残缺 stub（仅有导出符号，无实际实现）。从 git 恢复完整 9.4KB 实现后正确迁移。
- `src/services/session_migrate.py` facade 首次生成时漏掉 `handle_session_migrate_cli`（被 `clawcodex_ext/cli/session_migrate_cmd.py` 引用），导致 Stage 2 CLI 烟雾测试 3 个失败，补齐导出后全绿。

**验证标准（全部通过）**：
- ✅ `python3 scripts/regenerate_patches.py --commit b24b8cb --allow-deletes` 幂等重生（byte-identical）
- ✅ 619 patches / 3.7 MB 补丁队列
- ✅ 内容级 modified 文件 578 → 504（−74）
- ✅ `pytest tests/stability_gate/ -q --tb=short -x`（245 passed）
- ✅ `pytest tests/orchestrator/ -q --tb=short`（523 passed, 2 skipped）
- ✅ Facade **身份等价**：verification 子代理用 `is` 运算符确认 `src.X.Y is clawcodex_ext.X.Y`
- ✅ Ext 模块**独立加载**：19 个 ext 模块直接 `importlib.import_module()` 成功

### Phase 2-E（持续）— 长尾收口

```
src/services/{ide,mcp,tool_execution}         → clawcodex_ext/services/  (3 个剩余 src-only 子系统)
src/services/{analytics,api,chrome,oauth,periodic,pipe_ipc,voice} (双位置 → 收敛为单 ext 入口)
src/auth/*、src/permissions/*、src/buddy/*、src/skills/*、src/memdir/*
src/cli_core/*、src/bridge/*（仅差异文件）
```

### Phase 3（长期）— 维护

- 上游发布新版本时，src/ 中核心文件可更轻松地合并（绝大多数已是 facade）
- 新功能**默认在 `clawcodex_ext/` 或 `extensions/`** 开发
- 一旦发现新 src 文件混入增量逻辑，立即迁移

---

## 7. 风险与约束

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 导入循环 | 运行时加载失败 | 使用 `__getattr__` 懒代理；`clawcodex_ext` 严禁反向导入 `src`；transcript resolver 注册延后到 `src/init.py:init()` |
| 依赖丢失 | 功能无声退化 | 所有钩子 `try/except ImportError` safe fallback |
| 测试覆盖不足 | 解耦后功能异常 | 每个 facade 提取后跑 stability_gate + orchestrator 单元测试 |
| 上游版本冲突 | 合并成本增加 | 保持 src/ 中上游文件的结构与签名不变 |
| F-83/F-85 等子系统体积大 | 一次性迁移风险高 | 分包迁移，每个子包独立 PR（**注意**：`0dacfa8d` 把 templates/compact/ultraplan 三个独立包混入一个 chore commit，按用户决定不再 `git reset` 拆分） |

### 导入规则（强制）

```
src/*                  → 可以导入 clawcodex_ext/*（顶层 import 或 __getattr__）
src/*                  → 可以导入 extensions/*（顶层 import 或 __getattr__）
clawcodex_ext/*        → 禁止导入 src/*（反向导入导致循环）
clawcodex_ext/*        → 可以导入 extensions/*（通用扩展接口）
extensions/*           → 可以导入 clawcodex_ext/*（同向下层）
extensions/*           → 禁止导入 src/*（反向导入导致循环）
```

> 例外：`src/init.py:init()` 是文档化的多入口引导点，可以在 init 阶段**主动**调用 ext 的注册函数（这种"显式下行调用"是允许的，但仅限 init 阶段）。

### Facade 选型决策表

| 场景 | 推荐形态 | 例子 |
|---|---|---|
| 子模块无 `_xxx` 私有符号引用 | **Pattern D · wildcard re-export** (2-3 行) | `services/templates/__init__.py` |
| 子模块有 `_xxx` 私有符号被外部 inspect/测试访问 | **Pattern C · sys.modules swap** (~15 行) | `agent/agent_tool_utils.py` / `query/query.py` |
| 子模块需要显式 `__all__` 列出公共符号 | **Pattern B · lazy `__getattr__` proxy** (30-40 行) | `agent/transcript.py` |
| 子模块有大量本地扩展，src 需保留导入路径 | **Pattern E · 完整 facade** (100+ 行) | `services/compact/pipeline.py` |
| 适配器模式（Protocol + Registry） | **Pattern A · 纯 re-export adapter** | `permissions/_treesitter_adapter.py` 等 |

---

## 8. 验收标准

完成所有解耦后：

1. **`diff -rq src/upstreamproxy/ src/ --exclude='__pycache__' | grep differ$ | wc -l`** ≤ 30 个文件存在差异
2. 差异文件中：
   - byte-identical（与上游完全一致）占多数
   - facade（Pattern B/C/D 任一）占 ~280
   - 含合法 bug fix / 重构 / 新增子系统注释占少量
3. **`clawcodex_ext/`** + **`extensions/`** 承担所有 ClawCodex 特有的功能增量
4. **`pytest tests/stability_gate/`** + **`pytest tests/clawcodex_ext/`** + **`pytest tests/orchestrator_*.py`** 全部通过
5. **CI gate**（mypy / ruff / pytest-substantive）绿灯

### 进度追踪

| 指标 | 目标 | 计划 (2026-06-21) | Phase 2-D 前 (2026-06-22) | 当前 (2026-06-23) |
|---|---|---|---|---|
| 已 facade 化文件 | ≥ 150 | **91** | **~264** | **~281** (117 lazy + 149 wildcard + ~15 sys.modules) |
| 含本地增量的非 facade 文件 | ≤ 30 | **~50** | **~30** | **~13** |
| src/ 中无上游对应物的"纯新增"目录 | 0 | **~12** | **6** | **3** (computer_use/kairos/langfuse 已迁 ext，仅 ide/mcp/tool_execution 仍 src-only) |
| 双位置包（src + ext 都有） | 0 | 未规划 | **7** | **7** (analytics/api/chrome/oauth/periodic/pipe_ipc/voice — 待收敛) |
| src/services/mcp/（最大残余） | 迁 ext | 未规划 | ❌ 32 文件待迁 | ❌ 32 文件待迁 |
| **内容级 modified 文件** | ≤ 400 | 578 | 578 | **504** (−74，74 个仅行尾差异剥离) |
| **补丁队列体积** | < 5 MB | ~1 MB | ~1 MB | **3.7 MB** (619 patches, byte-identical 幂等) |
| 上游 rebase 冲突面积（每次 rebase 手动修改行数） | < 200 行/次 | 估算 ~800 行/次 | 估算 ~300 行/次 | 估算 **~250 行/次**（Phase 2-D 进一步收敛） |

### Phase 2-D 验证矩阵（验收完毕）

| 维度 | 命令 | 结果 |
|---|---|---|
| 补丁重生幂等 | `python3 scripts/regenerate_patches.py --commit b24b8cb --allow-deletes` (×2) | ✅ byte-identical |
| Stage 2 CLI 烟雾测试 | `pytest tests/stability_gate/test_stage2_cli.py` | ✅ 9 passed |
| 全稳定性门禁 | `pytest tests/stability_gate/ -q --tb=short` | ✅ 245 passed |
| Orchestrator 全量 | `pytest tests/orchestrator/ -q --tb=short --ignore=manual_e2e_f38.py` | ✅ 523 passed, 2 skipped |
| Facade 身份等价（探针 A） | `is` 运算符 7 对 src.X ↔ clawcodex_ext.X | ✅ 全 PASS |
| Ext 模块独立加载（探针 B） | `importlib.import_module()` ×19 ext 模块 | ✅ 全 PASS |
| 导入烟雾测试 | `from src.services.{computer_use,kairos,langfuse} import *` | ✅ OK |
| 文件抽查（探针 C） | 3 个 facade + 3 个 ext 镜像抽查 | ✅ facade 13-14 行，ext 真实实现 |

---

## 9. 附：与原始方案的关键差异

| 项 | 原方案 | 现方案 |
|---|---|---|
| 扩展层数量 | 仅 `clawcodex_ext/` | **`clawcodex_ext/` + `extensions/`** 两层 |
| `extensions/` 角色 | 未规划 | 第三方适配 / 跨子系统能力（orchestrator / visualizer / remote_api / session_analyzer / providers_ext / skills_ext / tool_system_ext） |
| `src/upstreamproxy/` | 未规划 | 新增——上游版本兼容代理（不参与业务逻辑） |
| F-83/F-85/F-86/F-84 等新子系统 | 未在解耦范围 | ✅ **已迁 ext** (channels/swarm/templates/ultraplan/context_collapse/compact) — 6 个包，~54 文件 |
| Phase 0（30 文件整迁） | 规划中 | ✅ 已完成 |
| Phase 1-3（entrypoints / TUI / command_system） | 规划中 | ✅ 已完成 |
| Phase 2-A（5 个高优先级文件） | 规划中 | ✅ 已完成（agent_tool_utils/transcript/templates/ultraplan/query.py 全部 facade 化） |
| Phase 2-B（services/ + query/ 批量） | 规划中 | ✅ 已完成（swarm 4 commits / channels / context_collapse / 0dacfa8d bundled） |
| Adapter 统一解耦 | 隐含 | ✅ 已完成（F-48.1） |
| 冗余委托层清理 | 未规划 | ✅ 已完成（`6518dab5`） |
| 双位置包（src + ext 都有） | 未考虑 | 新增观察项：`analytics` / `api` / `chrome` / `oauth` / `periodic` / `pipe_ipc` / `voice`（7 个包）— 待收敛为单 ext 入口 |
| Facade 形态细分 | 仅 "wildcard re-export" | **5 种形态**（Pattern A 适配器 / B lazy proxy / C sys.modules swap / D wildcard re-export / E 完整 facade）— 见 §7 选型决策表 |
| 待迁 ext 的"纯新增"包 | 仅 §1.4 列出的 12 个 | 仍剩 6 个：`computer_use` / `kairos` / `ide` / `langfuse` / `mcp` / `tool_execution` |

---

## 10. 本次会话（2026-06-23）补充变更

> 本次会话除完成 `df3b9738` (channels 迁移) 外，未引入新代码变更，仅更新本规划文档以反映当前代码状态。

| commit | 类别 | 摘要 |
|---|---|---|
| `df3b9738` | refactor(channels) | 将 Channels 服务迁移至 `clawcodex_ext/services/channels/`，src/ 留 9 个 3 行 re-export facade。验证：93/93 channels 测试 + 245/245 stability gate |

**本次会话未触及的待办项**（已记录于 §3 / §4）：
- `src/services/{computer_use,kairos,ide,langfuse,mcp,tool_execution}` 待迁 `clawcodex_ext/services/`
- `src/agent/{agent_definitions,session,run_agent,resume_agent,foreground_promotion,fork_subagent}` 内部增量解耦
- 7 个双位置包（`analytics` / `api` / `chrome` / `oauth` / `periodic` / `pipe_ipc` / `voice`）收敛为单 ext 入口

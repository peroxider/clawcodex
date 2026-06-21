# 解耦方案 · ClawCodex Decoupling Plan

> **目标**：将 `src/` 中所有 ClawCodex 定制逻辑迁至 `clawcodex_ext/` 与 `extensions/`，使上游（`src/upstreamproxy/...`）与本地 `src/` 的差异仅保留**架构重构**、**bug fix** 和**纯新增子系统**，所有「功能增量」通过扩展层注入。
>
> **最近更新**：2026-06-21，基于 `dev-decoupling-refactor-b24b8cb` 分支当前状态（F-48 Phase 0–9、F-49 P0–P5、F-83/F-85/F-86/F-84/F-61/F-63/F-60/F-72/F-75、SR-5.1 均已合并）。

---

## 1. 当前状态总览

### 1.1 文件规模（截至 2026-06-21）

| 维度 | 当前数字 | 原计划数字 | 变化 |
|---|---|---|---|
| 上游文件（`src/upstream/`） | **2553** `.py` | 566 | +1987（上游 rebased 多次，合并入更大版本） |
| `src/upstreamproxy/` | **6** `.py` | — | 新增：上游兼容代理层 |
| 本地 `src/`（排除 upstream & upstreamproxy） | **651** `.py` | 594 | +57（新增子系统：channels、computer_use、context_collapse、kairos、periodic、pipe_ipc、swarm、templates、ultraplan 等） |
| 扩展层 `clawcodex_ext/` | **278** `.py` | 232 | +46（F-48 Phase 0 迁入 30 个 + 后续新增） |
| 第三层扩展 `extensions/` | **145** `.py` | （未规划） | 新增独立扩展层（orchestrator、visualizer、remote_api 等） |
| **已采用 lazy `__getattr__` proxy 化的文件** | **91** | ~45 | +46 |
| **含本地增量但未 facade 化的文件** | **~50** | ~35 | +15（新增子系统带来的同步增长） |

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

Pattern B — lazy __getattr__ proxy（91 个，~6,500 行 → 平均 ~70 行）
  src/entrypoints/{headless,tui}.py                 (原 667/230L → 25/26L)
  src/entrypoints/orchestrator.py                   (lazy proxy)
  src/cli.py                                        (compatibility facade, 116L)
  src/cost_tracker.py                               (facade, 95L)
  src/providers/__init__.py                         (通过 __getattr__ 代理至 factory)
  src/repl/core.py / ui_host.py                     (lazy proxy)
  src/permissions/cycle.py                          (lazy proxy)
  src/command_system/* (10 files)                   (Phase 9 整体迁移)
  src/context_system/prompt_assembly.py             (lazy proxy)
  src/tui/* (~40 files)                             (Phase 1-3 整体迁移)
  src/services/cost_tracker.py / pricing.py / tail_follower.py
  src/services/templates/{registry,models,resolver,...}.py
  src/services/ultraplan/{executor,store,...}.py
  …以及 60+ 其他文件

Pattern C — 完整 facade / thin wrapper（少量）
  仅在 ext 实现有显著扩展而上游 API 又必须保留时使用：
  src/agent/registry.py / session.py / transcript.py
  src/agent/agent_definitions.py / agent_tool_utils.py / parse_agent_markdown.py
  src/query/{query,engine,agent_loop_compat}.py
  src/services/compact/{pipeline,snip_compact}.py
  src/services/context_collapse/engine.py
```

### 1.3 F-48 / F-49 已完成阶段

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
| F-63 Channels | `d015f7bb` | 新增 Discord / Slack / 飞书 通知 |
| F-60 Pipe IPC | `a6a08b3f` | 新增进程间管道通信 |
| F-72 Multi-API | `43a24dc8` | 原生适配器扩展 P72-A/B/C/D/E |
| F-75 Tool/Skill Stats | `ba922dcd` | 跨会话调用统计 |
| SR-5.1 社区雷达 | `b81a267a` / `51b16b74` | Phase 1–4：registry/fetcher/extractor/classifier/dedup/scorer/reporter + LLM + Jinja2 + Cron |

### 1.4 新增的纯子系统（无上游对应物，不参与解耦）

> 这些目录是**新增能力**，与上游 diff 不存在"差量"，应在 `extensions/` 或 `clawcodex_ext/` 长期保留。

```
src/services/analytics/        事件埋点 (F-?)
src/services/channels/         F-63 多通道通知
src/services/computer_use/     F-61 屏幕操控
src/services/context_collapse/ F-84 三段式压缩
src/services/kairos/           F-86 定时调度
src/services/oauth/            第三方 OAuth
src/services/periodic/         F-86 周期任务
src/services/pipe_ipc/         F-60 进程管道
src/services/swarm/            多 agent 协同
src/services/templates/        F-85 配置模板
src/services/ultraplan/        F-83 多层计划
src/services/voice/            语音 I/O
src/upstreamproxy/             上游兼容代理层
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

---

## 3. Phase 2 — 进行中：未 facade 化的 ~50 个文件的解耦计划

> **目标**：把仍含本地增量的文件进一步拆为「上游原样 + ext 增量」两层。

### 3.1 `src/agent/*`（20 个文件，~4,400 行）

下表仅列出**含本地增量**的高优先级文件；其余 11 个文件（`__init__.py`、`background_runner.py`、`background_state.py`、`constants.py`、`conversation.py`、`filter_agents_by_mcp.py`、`load_agents_dir.py`、`load_plugin_agents.py`、`prompt.py`、`subagent_context.py`、已 facade 化的 `_outlines_adapter.py`）评估后多数保留上游原样或作为低优先级。

| 文件 | 当前行数 | 内联增量 | 解耦方案 |
|---|---|---|---|
| `agent_definitions.py` | 286 | 内置 agent 列表 + 解析逻辑 | `clawcodex_ext/agent/agent_definitions_ext.py` 追加 `register_agent()`；src/ 仅做 `__getattr__` 转发 |
| `agent_tool_utils.py` | 465 | 自定义 tool 过滤 / 计数 | `clawcodex_ext/agent/tool_utils_ext.py`：`extend_resolved_agent_tools()` 钩子，参考 §3.2 原方案 |
| `parse_agent_markdown.py` | 230 | frontmatter 字段映射扩展 | `clawcodex_ext/agent/markdown_ext.py`：`register_field_map()` |
| `session.py` | 479 | F-49 后的 `load` 扩展 | `clawcodex_ext/agent/session_ext.py` 已存在，src 完全剥离为 facade |
| `transcript.py` | 595 | Chunk C/D/F 内联实现 | `clawcodex_ext/transcript/` 已存在，src 完全剥离为 facade |
| `run_agent.py` | 402 | agent 启动逻辑 | 拆分 `AgentRunner` → `extensions/orchestrator/agent_runner.py` |
| `resume_agent.py` | 252 | resume 流程 | `clawcodex_ext/agent/resume_ext.py` |
| `foreground_promotion.py` | 221 | background → foreground 转换 | `clawcodex_ext/agent/foreground_ext.py` |
| `fork_subagent.py` | 294 | sub-agent 派生 | `clawcodex_ext/agent/fork_ext.py` |

**统一方案**：
```python
# src/agent/agent_definitions.py（目标态）
def __getattr__(name):
    import clawcodex_ext.agent.agent_definitions as _mod
    if name in _mod.__dict__: return _mod.__dict__[name]
    raise AttributeError(...)
```

### 3.2 `src/query/*`（10 个文件，~3,850 行）

| 文件 | 行数 | 内联增量 | 解耦方案 |
|---|---|---|---|
| `query.py` | 1991 | 完整 query 主循环 | 已是 facade 候选，但仍有 stream middleware / stop hook 注册，迁 `clawcodex_ext/query/query_ext.py` |
| `engine.py` | 330 | query engine dataclass | 整体迁 `clawcodex_ext/query/engine.py`，src/ 留 facade |
| `agent_loop_compat.py` | 495 | 适配层 | 迁 `clawcodex_ext/query/agent_loop_compat.py` |
| `streaming.py` | 343 | 流中间件 | `clawcodex_ext/query/stream_middleware.py`（原 §2.12 已规划） |
| `stop_hooks.py` | 264 | stop hook | `clawcodex_ext/query/stop_hooks_ext.py` |
| `transitions.py` | 112 | 状态迁移 | `clawcodex_ext/query/transitions_ext.py` |
| `token_budget.py` | 159 | token 预算 | `clawcodex_ext/query/token_budget_ext.py` |
| `config.py` | 122 | query 配置 | `clawcodex_ext/query/config_ext.py` |
| `deps.py` | 11 | 依赖注入 | 保留上游原样 |
| `__init__.py` | 17 | package marker | 保留上游原样 |

### 3.3 `src/services/{templates,ultraplan,context_collapse,compact}`（~25 个文件，~4,500 行）

这些是 F-83/F-85/F-84 的纯新增子系统（F-49 chunk），**本就不属于解耦对象**（与上游无对应物）。已正确放置在 `src/services/` 下。

> **决策**：保留在 `src/services/` 是合理的，因为它们是 ClawCodex 独有子系统。但 `services/templates/`、`services/ultraplan/`、`services/context_collapse/` 应当**全部迁到 `clawcodex_ext/services/`**（与 `clawcodex_ext/services/bridge/` 同级），保持 src/ 只放上游兼容层。

迁移目标：
```
src/services/templates/*    → clawcodex_ext/services/templates/    (F-85)
src/services/ultraplan/*    → clawcodex_ext/services/ultraplan/    (F-83)
src/services/context_collapse/* → clawcodex_ext/services/context_collapse/ (F-84)
src/services/compact/{pipeline,snip_compact,context_collapse}.py → clawcodex_ext/services/compact/ (仅这几个含本地增量)
```

### 3.4 `src/services/{channels,computer_use,kairos,periodic,pipe_ipc,swarm,voice,oauth,analytics}`（~30 个文件）

> 决策：与 §3.3 同。**全部迁到 `clawcodex_ext/services/`**，因为它们都是 ClawCodex 独有子系统。

### 3.5 `src/services/api/*`（~8 个文件）

| 文件 | 解耦方案 |
|---|---|
| `claude.py`、`provider_config.py`、`retry.py`、`tool_normalization.py`、`errors.py`、`logging.py` | 评估是否含本地增量。多数是上游原样。少量增量迁 `clawcodex_ext/services/api/` |

### 3.6 `src/auth/*`、`src/permissions/*`、`src/buddy/*`、`src/skills/*`、`src/memdir/*`、`src/context_system/*`

按 §1.2 的 Pattern B/A 继续推进；其中：
- `src/auth/{auth,aws,claude_ai,gemini,oauth}.py` —— 4–6 个文件保留上游核心，OAuth 扩展迁 `clawcodex_ext/auth/`
- `src/permissions/check.py`、`src/permissions/bash_parser/*` —— 原 §2.13/§3.1 方案仍然有效，bash_parser 注册表模式已部分实施
- `src/buddy/{companion,feature,notification,observer,prompt,soul,sprites,types}.py` —— 7 个文件评估后迁 `clawcodex_ext/buddy/`

### 3.7 `src/cli_core/*`、`src/bootstrap/*`、`src/state/*`

- `cli_core/{exit,ndjson,structured_io}.py` —— 评估
- `bootstrap/state.py` —— 8 行小工具，保留上游
- `state/*` —— 多数是上游原样，少量增量迁 ext

### 3.8 `src/{assistant,bridge,keybindings,models,moreright,native_ts,outputStyles,plugins,reference_data,remote,schemas,screens,server,tasks,transports,vim}/*`

> 决策：这些目录**不是解耦对象**——多数是上游原样或独立子系统。`bridge/*`（42 文件）已被重构精简，差异主要在 `bridge_enabled.py` / `capacity_wake.py` / `repl_bridge.py` 等少量文件中，可在 `extensions/bridge/` 中扩展。

---

## 4. 当前需要立即处理的 5 个高优先级文件

> 按"修改频次 × 与上游冲突面"排序，这 5 个文件解耦后能最大幅度降低 rebase 成本。

### 4.1 `src/agent/agent_tool_utils.py`（465 行）— **最优先**

**问题**：含 ClawCodex 特有的 tool 过滤规则和扩展 tool 注册，每次上游更新都会冲突。

**方案**：
```python
# clawcodex_ext/agent/tool_utils_ext.py
def register_custom_filters() -> None:
    """注册 ClawCodex 特有的 tool filter"""

# src/agent/agent_tool_utils.py（目标态）
def __getattr__(name):
    import clawcodex_ext.agent.tool_utils as _mod
    if name in _mod.__dict__: return _mod.__dict__[name]
    raise AttributeError(...)
```

### 4.2 `src/agent/transcript.py`（595 行）— **高**

**问题**：F-49 注入的 Chunk C/D/F 实现仍内联。

**方案**：完全剥离到 `clawcodex_ext/transcript/`，src 留 lazy facade（参考 `extensions/orchestrator/transcript_*`）。

### 4.3 `src/services/templates/*`（10 文件，~1,800 行）— **高**

**问题**：F-85 的完整实现放在 src/，破坏了"src/ = 上游 + facade"的原则。

**方案**：整体迁 `clawcodex_ext/services/templates/`，src 仅留 `__init__.py` 转发声明。

### 4.4 `src/services/ultraplan/*`（7 文件，~1,500 行）— **高**

**问题**：同 §4.3，F-83 的完整实现应迁 ext。

**方案**：整体迁 `clawcodex_ext/services/ultraplan/`。

### 4.5 `src/query/query.py`（1991 行）— **中**

**问题**：文件大、含本地 stop hook / stream middleware 注册。

**方案**：核心 query 逻辑保留上游 facade，本地扩展迁 `clawcodex_ext/query/query_ext.py`。`extensions/api/query_middleware.py` 已存在（F-48 抽取），可继续对接。

---

## 5. 不可解耦的差异（保持原样）

| 类别 | 说明 | 示例 |
|---|---|---|
| **架构重构** | 代码被精简/外迁到 ext | `bridge/repl_bridge.py` (-312L)、`bridge/bridge_main.py` (-257L)、`buddy/__init__.py` (-97L) |
| **新增子系统** | 上游不包含的全新功能 | `src/services/{channels,computer_use,kairos,periodic,pipe_ipc,swarm,templates,ultraplan,context_collapse,voice,oauth,analytics}` |
| **bug fix** | 修复了上游遗留 bug | `b88a040d` TUI ghost_suggestion 渲染初始化；`c13a0395` chat_stream fallback；`b0d39943` /provider 补全回归修复 |
| **依赖调整** | build / requirements | `pyproject.toml`、`setup.cfg` |
| **纯注释/格式** | 不影响语义 | docstring 更新 |

---

## 6. 实施路线图

### Phase 2-A（本周）— 5 个高优先级文件解耦

```
1. src/agent/agent_tool_utils.py          → clawcodex_ext/agent/tool_utils_ext.py + facade
2. src/agent/transcript.py                → clawcodex_ext/transcript/ + facade
3. src/services/templates/*               → clawcodex_ext/services/templates/* + facade
4. src/services/ultraplan/*               → clawcodex_ext/services/ultraplan/* + facade
5. src/query/query.py                     → clawcodex_ext/query/query_ext.py + facade
```

**验证标准**：
- 5 个 src 文件全部退化为 < 100 行 facade
- `diff -rq src/upstreamproxy/ src/ | grep -v __pycache__ | wc -l` 减少 ≥ 2,000 行
- `pytest tests/stability_gate/ -q --tb=short -x` 通过
- `pytest tests/clawcodex_ext/ -q --tb=short -x` 通过

### Phase 2-B（下周）— agent/ + query/ 子系统批量 facade 化

```
src/agent/{agent_definitions,parse_agent_markdown,session,run_agent,resume_agent,
           foreground_promotion,fork_subagent,prompt,subagent_context,conversation}.py
src/query/{engine,agent_loop_compat,streaming,stop_hooks,transitions,token_budget,config}.py
src/services/context_collapse/{engine,boundary,summary,persistence}.py
src/services/compact/{pipeline,snip_compact,context_collapse,reactive_compact,session_memory_compact}.py
```

目标：~30 个文件退化为 facade，src/ 净减少 ~3,500 行。

### Phase 2-C（持续）— 长尾收口

```
src/services/{channels,computer_use,kairos,periodic,pipe_ipc,swarm,voice,oauth,analytics}
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
| F-83/F-85 等子系统体积大 | 一次性迁移风险高 | 分包迁移，每个子包独立 PR |

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

---

## 8. 验收标准

完成所有解耦后：

1. **`diff -rq src/upstreamproxy/ src/ --exclude='__pycache__' | grep differ$ | wc -l`** ≤ 30 个文件存在差异
2. 差异文件中：
   - byte-identical（与上游完全一致）占多数
   - facade（仅 `__getattr__` 转发）占 ~100
   - 含合法 bug fix / 重构 / 新增子系统注释占少量
3. **`clawcodex_ext/`** + **`extensions/`** 承担所有 ClawCodex 特有的功能增量
4. **`pytest tests/stability_gate/`** + **`pytest tests/clawcodex_ext/`** + **`pytest tests/orchestrator_*.py`** 全部通过
5. **CI gate**（mypy / ruff / pytest-substantive）绿灯

### 进度追踪

| 指标 | 目标 | 当前 (2026-06-21) |
|---|---|---|
| 已 facade 化文件 | ≥ 150 | **91** |
| 含本地增量的非 facade 文件 | ≤ 30 | **~50** |
| src/ 中无上游对应物的"纯新增"目录 | 0 | **~12**（应迁 ext） |
| 上游 rebase 冲突面积（每次 rebase 手动修改行数） | < 200 行/次 | 估算 ~800 行/次 |

---

## 9. 附：与原始方案的关键差异

| 项 | 原方案 | 现方案 |
|---|---|---|
| 扩展层数量 | 仅 `clawcodex_ext/` | **`clawcodex_ext/` + `extensions/`** 两层 |
| `extensions/` 角色 | 未规划 | 第三方适配 / 跨子系统能力（orchestrator / visualizer / remote_api / session_analyzer / providers_ext / skills_ext / tool_system_ext） |
| `src/upstreamproxy/` | 未规划 | 新增——上游版本兼容代理（不参与业务逻辑） |
| F-83/F-85/F-86/F-84 等新子系统 | 未在解耦范围 | **应迁 ext**——这些是 ClawCodex 独有子系统，不属于"差量"，应避免放在 src/ |
| Phase 0（30 文件整迁） | 规划中 | ✅ 已完成 |
| Phase 1-3（entrypoints / TUI / command_system） | 规划中 | ✅ 已完成 |
| Adapter 统一解耦 | 隐含 | ✅ 已完成（F-48.1） |
| 冗余委托层清理 | 未规划 | ✅ 已完成（`6518dab5`） |


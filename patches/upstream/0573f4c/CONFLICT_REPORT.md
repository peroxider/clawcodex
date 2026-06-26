# 上游同步分析报告：b24b8cb → 0573f4c（特性视角）

**生成时间**：2026-06-26
**目的**：把上游 `0573f4c` 的**新特性**同步进下游，同时保住二开特性；据此决定补丁如何修改。
**一句话结论**：补丁队列（`src/` vs 上游）层面**几乎不用手改**——73/85 个冲突文件的 src/ 侧只是 facade 壳，regen 会自动重建。**真正的特性同步工作 100% 落在 `clawcodex_ext/` 的 73 个镜像副本（其中 69 个还停在旧上游）+ 12 个真 src/ overlay 文件**。

---

## 0. 决策框架（按你的纠正翻转）

同步上游的**目的就是吸收新特性**，所以默认原则不是"保留下游、抵抗上游"，而是：

> **默认全盘接受上游新特性；只有当某文件存在真实二开 overlay 时，才做特性级合并以保住二开那部分。**

这把 §5 里"是否 preserve / 是否重新引入"的纠结一次性解开：
- `deferred_init.py`（上游 31→128 行扩写）→ **接受上游**，不 preserve。
- `settings/permission_validation.py`（上游重新引入）→ **接受上游**，移除下游的 delete patch。
- 12 个上游独改、下游没动的文件 → **全部接受上游新版**。
- 91 个上游新增文件 → **全部吸收**（preserve.list (a) 段继承）。

---

## 1. 上游 0573f4c 带来的特性图谱

从 91 个新增文件 + 97 个语义改文件的 docstring/diff 归纳出 **9 大特性簇**：

| # | 特性簇 | 落点文件 | 接线点（上游改了哪些既有文件） |
|---|--------|---------|--------------------------------|
| **F1** | **Workflow 引擎**（确定性多代理编排，~20 文件全新子系统：budget/journal/scheduler/sandbox/structured/worktree/ultracode…） | `workflow/*`、`tool_system/tools/workflow.py`、`tasks/local_workflow.py` | `command_system/builtins.py`（注册 /workflows）、`command_system/workflows_integration.py`、`tui/screens/workflow_dialog.py`、`tool_system/registry.py`、`tool_system/defaults.py` |
| **F2** | **5 层压缩管线**（tool_result_budget→snip→collapse→autocompact，14 文件） | `services/compact/*` | `query/query.py`、`agent/run_agent.py`、`context_system/*` |
| **F3** | **15 个新斜杠命令**（/copy /diff /doctor /logo /mcp /memory /permissions /release-notes /rename /resume /stickers /tasks /vim /workflows） | `command_system/*_command.py` | `command_system/builtins.py`、`command_system/__init__.py`、`command_system/engine.py`、`command_system/input_processing.py` |
| **F4** | **6 个 bundled skills**（/debug /loop /simplify /stuck /verify-content） | `skills/bundled/*` | `skills/`、`command_system/builtins.py` |
| **F5** | **UI-neutral 服务层组件化**（C2–C9：bash_mode/config_health/fuzzy_match/mcp_approval/memory_append/session_listing/startup_gates/status_line/token_warning/workspace_search） | `services/*.py` + `tui/screens/*` | `entrypoints/{tui,headless}.py`、`repl/core.py`、`tui/app.py`、`tui/commands.py` |
| **F6** | **新 LLM provider**（Z.ai/GLM + 数据驱动 OpenAI-兼容注册表） | `providers/zai_provider.py`、`providers/openai_compatible_specs.py` | `providers/__init__.py`、`providers/base.py`、`providers/openai_compatible.py`、`providers/anthropic_provider.py` |
| **F7** | **query 健壮性**（续写 nudge + 工具失败循环防护） | `query/continuation_nudge.py`、`query/tool_failure_loop_guard.py` | `query/query.py`、`query/agent_loop_compat.py`、`query/stop_hooks.py`、`query/transitions.py` |
| **F8** | **权限增强**（don't-ask-again 启发式 + 规则校验 + 设置路径） | `permissions/{bash_suggestions,settings_paths}.py`、`settings/permission_validation.py` | `permissions/{check,filesystem,handler,trust_boundary,types,updates,setup,__init__}.py` |
| **F9** | **杂项**（secret_store/spinner_verbs/logo_palettes/release_notes/queued_commands/shortcuts_help/task_notifications） | 各新增单文件 | `cli.py`、`repl/{core,live_status,task_notifications}.py`、`tui/widgets/*` |

> 这张表是「补丁怎么改」的索引：要吸收 F1，就盯 `workflow/`（新建，无冲突）+ 它的接线文件（`builtins.py`/`registry.py` 等冲突文件）。

---

## 2. 补丁修改的真相：src/ 侧≈零工作，clawcodex_ext/ 侧才是战场

把 85 个真冲突文件（下游 overlay ∩ 上游语义改）按**二开 overlay 类型**精确分类：

| 类型 | 数量 | src/ 补丁形态 | 特性同步落点 |
|------|-----:|--------------|-------------|
| **A1 facade** | **73** | `src/<f>` 是壳（lazy proxy / sys.modules swap / star-import），补丁=「删上游全文 + 写壳」 | **`clawcodex_ext/<f>` 镜像** |
| **A2 真 src overlay** | **12** | `src/<f>` 内有实质二开 | **`src/<f>` 本体** |

**关键推论（这就是答案）：**

1. **A1 的 73 个 facade，src/ 补丁在新 base 下不需要手工 merge。** 无论上游 0573f4c 把 `builtins.py` 写成什么，facade 补丁都是"删掉它、写壳"。换 base 后上游文件内容变了，被删的行随之变化，但**新增的壳内容不变**——`regenerate_patches.py` 会自动重算出正确的 facade 补丁。所以 src/ 侧零冲突。

2. **真正的特性缺口在 `clawcodex_ext/` 的镜像副本里。** 这 73 个镜像是当年从 **b24b8cb** fork 出来的。实测相似度：**69 个镜像更接近旧上游 b24b8cb，而非 0573f4c**——意味着上游 0573f4c 在这些文件里加的新特性（F1/F3/F5/F7/F8…）**根本没进镜像**。补丁队列完全看不到这个缺口，但特性同步必须逐个把上游 b24b8cb→0573f4c 的 diff 合进 `clawcodex_ext/<f>`。

3. **A2 的 12 个才需要 src/ 侧三方合并**：`config.py`、`bootstrap/state.py`、`cli.py`、`models/{__init__,configs,context}.py`、`settings/{constants,settings}.py`、`providers/{deepseek,openai}_provider.py`、`cost_tracker.py`、`tasks/__init__.py`、`__init__.py`。

---

## 3. clawcodex_ext 镜像同步优先级（特性缺口最大者优先）

facade 镜像 vs 0573f4c 相似度越低 = 上游新特性缺口越大 / 二开改动越深 = 越该优先人工合并：

### 3.1 🔴 缺口极大（相似度 <0.5，11 个）

| 镜像 vs 0573 | clawcodex_ext 镜像 | 涉及特性簇 |
|------:|------|------|
| 0.02 | `providers/__init__.py` | F6（provider 注册表，二开 lazy registry 与上游大改叠加） |
| 0.04 | `tui/screens/resume_conversation.py` | F5 |
| 0.06 | `tui/screens/__init__.py` | F5（新屏注册） |
| 0.10 | `services/cost_restore.py` | F9 |
| 0.27 | `tui/widgets/prompt_input.py` | F5/F9（注：唯一镜像反而更接近 0573，可能已部分跟进） |
| 0.35 | `permissions/trust_boundary.py` | F8（权限大改） |
| 0.37 | `providers/anthropic_provider.py` | F6 |
| 0.38 | `permissions/handler.py` | F8 |
| 0.39 | `tui/messages.py` | F5 |
| 0.40 | `tui/app.py` | F5（生命周期重写 + 新屏挂接） |
| 0.45 | `tui/screens/repl.py` | F5 |

### 3.2 🟠 缺口大（0.5–0.7，约 14 个）

`settings/types.py`(0.46) · `repl/core.py`(0.51, F5/F9 UIHost+task_notifications) · `query/query.py`(0.51, F2/F7) · `tui/widgets/status_line.py`(0.52) · `query/agent_loop_compat.py`(0.54, F7) · `tool_system/defaults.py`(0.55, F1) · `permissions/check.py`(0.55, F8) · `init.py`(0.60) · `command_system/__init__.py`(0.61, F3) · `settings/validation.py` · `agent/transcript.py` · `tui/widgets/header.py` · `tool_system/tools/web_fetch.py`(0.61) · `repl/live_status.py`

### 3.3 🟡 缺口中等（0.7–0.9，约 30 个）
`command_system/builtins.py`(F1/F3/F4 命令注册，命令量大但 diff 局部) · `tui/commands.py` · `tui/state.py` · `tool_system/tools/skill.py`(F4) · `tool_system/tools/web_search.py` · `permissions/updates.py`(F8) · `services/tool_execution/tool_execution.py`(F5) · `entrypoints/{tui,headless}.py`(F5) · …（其余见 /tmp/facade_files.txt）

### 3.4 🟢 缺口小（≥0.9，约 18 个）
`tool_system/tools/{grep,config,glob,read,write}.py` · `permissions/{filesystem,types,setup}.py` · `context_system/git_context.py` · `services/pricing.py` · `hooks/hook_executor.py` · …多为机械同步。

---

## 4. 三类同步动作（最终执行矩阵）

| 动作 | 对象 | 数量 | 具体做法 |
|------|------|-----:|---------|
| **① 纯吸收** | 上游新增文件 | 91 | 进 `patches/upstream/0573f4c/preserve.list` (a) 段，作 base 继承。**F1/F2/F3/F4 子系统几乎全在这里，零冲突直接获得** |
| **② 接受上游** | 上游独改、下游无 overlay | 12 | `src/` 接受 0573f4c 新版（含 `deferred_init.py`）；11 个已在 preserve.list，会随新 base 自动取 0573 内容 |
| **③ 镜像三方合并** | A1 facade 的 clawcodex_ext 副本 | 73（69 需同步） | **核心工作**：对每个 `clawcodex_ext/<f>`，三方合并 `merge(base=b24b8cb/<f>, theirs=0573f4c/<f>, ours=clawcodex_ext/<f>)`，把上游新特性接线并入。按 §3 优先级，先 🔴 11 个 |
| **④ src/ 三方合并** | A2 真 overlay | 12 | `merge(base=b24b8cb, theirs=0573f4c, ours=src/)`，重点 `config.py`（字段命名冲突）、`bootstrap/state.py`、`cli.py`、`providers/{deepseek,openai}_provider.py` |
| **⑤ 格式漂移** | tool_result_persistence.py | 1 | regen 带 `--ignore-format` 自动吸收 |
| **⑥ src 补丁** | A1 的 src/ facade 壳 | 73 | **无需手改**，regen 自动重建 |

---

## 5. 执行顺序

1. **上游快照就位**（已完成：`src/upstream/0573f4c/`）。
2. **动作①②⑤**：写新 `preserve.list`（(a) 段 = 91 新增；(b)/(d)/(g) 段沿用并核对 0573 仍存在的条目；删除 0573 已无的旧条目）；`src/` 接受 12 个独改文件；`deferred_init.py`、`permission_validation.py` 按 §0 接受上游。
3. **动作③（主战场）**：按 §3 优先级，逐个把 0573f4c 的特性合进 `clawcodex_ext/` 镜像。建议每合并一个特性簇（如先 F8 权限族 8 个、再 F6 provider 族、再 F5 TUI 族）就跑一次 stability gate。
4. **动作④**：12 个 A2 文件 src/ 侧合并。
5. **重生成补丁队列**（src/ 侧自动收敛）：
   ```bash
   python3 scripts/regenerate_patches.py \
     --commit 0573f4c \
     --preserve-file patches/upstream/0573f4c/preserve.list \
     --allow-deletes --ignore-format
   ```
6. **验证**：补丁 dry-run + 应用后树 == src/；`pytest tests/stability_gate/ -q -x`；`pytest tests/orchestrator/ --ignore=…manual_e2e_f38.py -q`。

---

## 6. 待人工决策清单

- [ ] 🔴 11 个极大缺口镜像逐个特性合并（§3.1）——风险最高，优先 `providers/__init__.py`、`permissions/{trust_boundary,handler}.py`、`tui/app.py`、`repl/core.py`、`query/query.py`
- [ ] `config.py` 二开字段（LiteLLM/orchestrator）vs 上游新字段命名冲突排查（动作④）
- [ ] `command_system/builtins.py` 镜像：上游 15 新命令 vs 二开命令同名检查（F3）
- [ ] `repl/core.py` 镜像：F9 task_notifications + UIHost（b24b8cb 已移植，0573 又重写）重新对齐
- [ ] `query/query.py` 镜像：F2 compact 管线 + F7 nudge/loop-guard 接线 vs F-48 中间件共存
- [ ] preserve.list 清理：删除 b24b8cb 独有、0573f4c 已不存在的条目

---

## 附录 A：规模数据

| 指标 | 值 |
|------|---:|
| 上游语义修改 / 格式漂移 / 新增 / 删除 | 97 / 1 / 91 / 0 |
| 下游 modified / new / preserved 补丁 | 381 / 86 / 148 |
| 真冲突（下游 overlay ∩ 上游语义改） | 85 |
| └ A1 facade（src/=壳，工作在 clawcodex_ext） | 73（69 镜像需同步） |
| └ A2 真 src overlay | 12 |
| 下游改 ∩ 上游未动（直接套用） | 295 |
| 上游改 ∩ 下游无 overlay（接受上游） | 12 |
| 上游新增（吸收） | 91 |

## 附录 B：机器可读清单（临时，/tmp）
`facade_files.txt`(73) · `real_overlay.txt`(12) · `conflict_sem.txt`(85) · `up_only_sem.txt`(12) · `up_new.txt`(91)

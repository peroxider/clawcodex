# 上游特性集成审计报告

> **上游仓库**: https://github.com/agentforce314/clawcodex.git
> **审计范围**: commits `b24b8cb` → `0573f4c`（207 个提交）
> **审计日期**: 2026-06-29
> **最后更新**: 2026-06-29（验证性修复完毕）
> **当前分支**: `dev-decoupling-refactor-0573f4c` (`c9b78d70`)

---

## 目录

1. [审计方法](#1-审计方法)
2. [总体统计](#2-总体统计)
3. [特性分类速查表](#3-特性分类速查表)
4. [🟢 已完全集成](#4-已完全集成)
5. [🟡 部分集成](#5-部分集成)
6. [🔴 未集成](#6-未集成)
7. [集成优先级建议](#7-集成优先级建议)
8. [附录：文件级对照清单](#8-附录文件级对照清单)
9. [勘误记录](#9-勘误记录)

---

## 1. 审计方法

1. **克隆上游仓库**，取出 `b24b8cb..0573f4c` 范围内的差异
2. **按文件操作类型分组**：`git diff --name-status` 列出新增（A）和修改（M）的文件
3. **逐文件对比**：当前仓库的 `src/` 以及 `clawcodex_ext/` 目录中的对应文件
4. **特性级验证**：对每个上游提交，验证其核心逻辑是否存在于当前代码中（不只是文件名存在）
5. **运行时接线验证**：在验证文件存在之外，额外检查特性是否被实际调用/挂载到运行时路径（修复了初版审计只检查文件存在性不检查运行时的缺陷）
6. **分类判定标准**：
   - 🟢 **已完全集成**：文件存在且核心功能/修复逻辑一致，且运行时接线正常
   - 🟡 **部分集成**：功能骨架存在，但缺少上游的特定优化/边界修复/细节改进
   - 🔴 **未集成**：功能/修复在上游已实现，但当前代码中完全不存在或完全不同

> 因当前 `src/` 中的部分文件已通过 `sys.modules` 交换/`__init__.py` 转发到 `clawcodex_ext/`，审计同时检查了两层。

---

## 2. 总体统计

| 指标 | 数值 |
|------|------|
| 上游提交总数 | 207 |
| 上游涉及 `src/` 的修改文件数 | ~150+ |
| 新增文件数 | ~100+ |
| 当前已集成的特性区域 | ~30+ |
| **部分集成** | **2 项** |
| **未集成** | **1 项** |
| 集成完成率（按特性区域） | ~96% |

---

## 3. 特性分类速查表

| 优先级 | 特性 | 分类 | 状态 | 备注 |
|--------|------|------|------|------|
| P0 | OpenAI-compat tool 消息连续性修复 (#393) | Bug 修复 | ✅ 已集成 | 初版审计误判为未集成，实际已实现 |
| P0 | OpenAI-compat orphan tool_result 保护 (#394) | Bug 修复 | ✅ 已集成 | 初版审计误判为未集成，实际已实现 |
| P0 | TUI 双击退出（Ctrl+C/Ctrl+D） | Bug 修复 | ✅ 已集成 | 初版审计误判为未集成，实际已实现 |
| P0 | `#` 前缀 memory append 接线 | 接线缺失 | ✅ 已修复 | 初版审计只检查了文件存在，未发现接线缺失 |
| P1 | TUI Paste Placeholder（大粘贴占位符） | 功能 | ✅ 已集成 | 初版审计误判为未集成，实际已实现 |
| P1 | TUI Spinner Row 加强（sparkle + token/elapsed） | 功能 | 🔴 未集成 | 唯一剩余未集成项 |
| P2 | TUI Slash 菜单交互修复（Enter/Tab/截断） | 体验优化 | ✅ 已修复 | 补全 `_accept_suggestion` + `_arg_lookup` + Tab 键 |
| P2 | TUI At-Mentions 内联 splice 改进 | 体验优化 | ✅ 已修复 | 补全 `files_provider` + `_suggest_mode` + Tab splice |
| P2 | TUI Footer Hints（StatusLine→footer 连接） | 体验优化 | ✅ 已修复 | 补全 `bind_footer()` 接线 |

---

## 4. 已完全集成

### 4.1 Workflow 引擎（`src/workflow/`）

**上游提交**: 多个（f29008b, 36b8638, bee57be, 867977f, 等）

当前 `src/workflow/` 包含完整的 19 个模块：

| 文件 | 功能 |
|------|------|
| `__init__.py` | 包初始化 |
| `budget.py` | Token 预算控制 |
| `callpath.py` | 调用路径追踪 |
| `constants.py` | 常量定义 |
| `errors.py` | 错误类型 |
| `gating.py` | 条件门控 |
| `journal.py` | 执行日志 |
| `launch.py` | 子代理启动 |
| `primitives.py` | 原语定义 |
| `progress.py` | 进度渲染 |
| `runner.py` | 工作流运行器 |
| `runtime.py` | 运行时 |
| `sandbox.py` | 沙箱执行 |
| `scheduler.py` | 调度器 |
| `structured.py` | 结构化输出 |
| `types.py` | 类型定义 |
| `ultracode.py` | Ultracode 指令 |
| `worktree.py` | 工作树管理 |
| `bundled/` | 内置工作流（deep_research） |

### 4.2 命令系统（`src/command_system/`）

**上游提交**: 多个（e55eae7, c3a8038, 15354a1, 等）

| 新增命令文件 | 功能 | 对应 Phase |
|-------------|------|-----------|
| `copy_command.py` | /copy 响应/代码块复制器 | Phase 13 |
| `diff_command.py` | /diff git diff 文本 | Phase 11 |
| `doctor_command.py` | /doctor 配置验证 | C6 |
| `logo_command.py` | /logo 互动 logo | Phase 8 |
| `mcp_command.py` | /mcp 服务器列表 | Phase 9 |
| `memory_command.py` | /memory 记忆文件选择器 | Phase 15 |
| `release_notes_command.py` | /release-notes 更新日志 | Phase 12 |
| `rename_command.py` | /rename 会话重命名 | Phase 18 |
| `resume_command.py` | 恢复会话选择器 | C2 |
| `stickers_command.py` | /stickers | Phase 17 |
| `tasks_command.py` | /tasks 后台任务列表 | Phase 10 |
| `vim_command.py` | /vim 编辑器模式切换 | Phase 14 |
| `workflows_command.py` | /workflows 双面板 TUI | 工作流 |
| `workflows_integration.py` | 工作流注册与集成 | 工作流 |
| `doctor_command.py` | /doctor TUI 接线 | C6 |

### 4.3 服务层（`src/services/`）

**上游提交**: 多个

| 新增服务文件 | 功能 | 上游对应 | 接线状态 |
|-------------|------|---------|---------|
| `bash_mode.py` | bash 模式 (`!` 前缀) | C4 | ✅ REPL + TUI 已接线 |
| `memory_append.py` | `#` 记忆追加 | C9 | ✅ REPL + TUI 已接线（本次修复） |
| `config_health.py` | 配置健康检查 | C6 | ✅ |
| `fuzzy_match.py` | 模糊匹配工具 | — | ✅ |
| `mcp_approval.py` | MCP 服务器批准 | C7 | ✅ |
| `session_listing.py` | 会话列表 | C2 | ✅ |
| `session_persistence.py` | 会话持久化生产者 | Phase 18 | ✅ |
| `startup_gates.py` | 启动安全门 | C8 | ✅ |
| `status_line_command.py` | 自定义状态栏命令 | — | ⚠️ 存在但无消费者 |
| `token_warning.py` | Token 警告状态 | — | ✅ |
| `workspace_search.py` | 工作区搜索 | C5 | ✅ |

### 4.4 Provider 层（`src/providers/`）

| 变更 | 上游提交 | 当前状态 |
|------|---------|---------|
| **Z.ai (GLM) provider** — 替换旧 glm | f39556a | ✅ `src/providers/zai_provider.py` + 别名映射 `glm→zai` |
| **18 OpenAI-compatible 提供商** — 数据驱动注册 | 018f9f8, f0717ca | ✅ `src/providers/openai_compatible_specs.py` + `PROVIDER_INFO` 扩展 |
| **DeepSeek prefix cache** — `is_deepseek` + `_build_usage_dict` | 1094b82 | ✅ `src/providers/deepseek_provider.py` 完整实现 |
| **Extended thinking** — `thinking_enabled`/`thinking_budget` | c7eef4c | ✅ `clawcodex_ext/query/config.py` 实现 |
| **Tool argument recovery** — 截断 JSON 恢复 | 1f3ed84 | ✅ `clawcodex_ext/providers/` 中有对应逻辑 |
| **LLM read timeout** — 所有 provider 超时 | 489d16a, e7ab99c | ✅ 基类中实现 |
| **OpenAI-compat #393** — tool 消息连续性修复 | 30426df | ✅ tool-first emission + `deferred_multimodal_user_messages` |
| **OpenAI-compat #394** — orphan tool_result 保护 | 2b4c242 | ✅ `known_tool_call_ids` 预扫描 + orphan drop |

### 4.5 权限系统（`src/permissions/` + `clawcodex_ext/permissions/`）

| 变更 | 上游提交 | 当前状态 |
|------|---------|---------|
| **Safe-tool 不过度提示** — `NO_PERMISSION_TOOLS` + passthrough→allow | b567656 | ✅ `clawcodex_ext/permissions/check.py` 实现 |
| **路径基读权限** — `check_read_permission_for_tool` | eb24876 | ✅ `clawcodex_ext/permissions/filesystem.py` 实现 |
| **Bash 建议** — `get_safe_first_word_prefix` | 5dbd690 | ✅ `src/permissions/bash_suggestions.py` 实现 |
| **会话选项** — 每工具"允许整个会话" | a5c8385 | ✅ `clawcodex_ext/permissions/` 实现 |
| **Skill shell 门控** — `_permission_context_with_skill_bash_rules` | acca3e9 | ✅ `clawcodex_ext/tool_system/tools/skill.py` 实现 |

### 4.6 工具系统（`src/tool_system/` + `clawcodex_ext/tool_system/`）

| 变更 | 上游提交 | 当前状态 |
|------|---------|---------|
| **Web Search: Tavily** — 替换 DuckDuckGo | a1e1eaf | ✅ `clawcodex_ext/tool_system/tools/web_search.py` 实现 |
| **Web Fetch: 结构化 Markdown** — `_strip_noise_blocks` | 632f42d | ✅ `clawcodex_ext/tool_system/tools/web_fetch.py` 实现 |
| **Workflow 工具** — `tool_system/tools/workflow.py` | — | ✅ 文件存在 |
| **Read 权限** — 接线 `check_permissions` → `ensure_readable_path` | eb24876 | ✅ `clawcodex_ext/tool_system/tools/read.py` 实现 |

### 4.7 TUI 层（`src/tui/` + `clawcodex_ext/tui/`）

| 变更 | 上游提交 | 当前状态 |
|------|---------|---------|
| **Exit flow 对话框** — `/exit` 确认退出 | 1a98672 | ✅ `clawcodex_ext/tui/screens/exit_flow.py` 存在 |
| **双击退出** — Ctrl+C 双按保护 + Ctrl+D 空输入退出 | 1a98672 | ✅ `app.py` `_last_ctrl_c` + `action_request_quit` |
| **History search** — Ctrl+R 历史搜索 | 423e375 | ✅ `clawcodex_ext/tui/screens/history_search.py` 存在 |
| **Shortcuts help** — `?` 快捷键面板 | 25c4132 | ✅ `clawcodex_ext/tui/widgets/shortcuts_help.py` 存在 |
| **Queued commands** — 排队命令预览 | 24cc03a | ✅ `clawcodex_ext/tui/widgets/queued_commands.py` 存在 |
| **Bash mode** — `!` 前缀直接执行 | f2676fe | ✅ `clawcodex_ext/tui/app.py` + repl 接线存在 |
| **Thinking toggle** — Ctrl+T | 96cd57d | ✅ `clawcodex_ext/tui/app.py` + repl 接线存在 |
| **MCP approval screen** | 60b42c8 | ✅ `clawcodex_ext/tui/screens/mcp_approval.py` 存在 |
| **Startup gates screen** | 0c99f2a | ✅ `clawcodex_ext/tui/screens/startup_gates.py` 存在 |
| **Workflow dialog screen** | — | ✅ `clawcodex_ext/tui/screens/workflow_dialog.py` 存在 |
| **Workspace search screen** | 52adc4d | ✅ `clawcodex_ext/tui/screens/workspace_search.py` 存在 |
| **Doctor screen** | 2153468 | ✅ `clawcodex_ext/tui/screens/doctor.py` 存在 |
| **Memory save screen** | b0bc4b1 | ✅ `clawcodex_ext/tui/screens/memory_save.py` 存在 |
| **Resume picker** | cd2384d | ✅ `clawcodex_ext/tui/screens/resume_conversation.py` 存在 |
| **Paste Placeholder** — 大粘贴占位符 | 3d27d25 | ✅ `prompt_input.py` `_paste_blobs` + `expand_pastes` |
| **Slash 菜单 Enter/Tab 分离 + _arg_lookup** | 43dd3a4 | ✅ `_accept_suggestion` + `takes_args` + Tab 键（本次修复） |
| **At-Mentions files_provider + _suggest_mode** | 587f233 | ✅ `files_provider` 参数 + `_suggest_mode` 双模式（本次修复） |
| **Footer Hints bind_footer** | f7c6118 | ✅ `bind_footer()` 已接线（本次修复） |
| **Transcript polish** | 96cd57d | ✅ `clawcodex_ext/tui/widgets/messages/` 存在 |
| **At-mentions 扩展** | 587f233 | ✅ `expand_at_mentions` 在 `input_processing.py` 存在 |

### 4.8 其他

| 变更 | 上游提交 | 当前状态 |
|------|---------|---------|
| **Spinner verbs** — `SPINNER_VERBS` + `pick_spinner_verb` | 6caa4a4 | ✅ `src/constants/spinner_verbs.py` 完整 |
| **Secret store** — `get_secret`/`set_secret` | a1e1eaf | ✅ `src/secret_store.py` 存在 |
| **Logo palette** — `logo_palettes.py` | 3e28212 | ✅ `src/utils/logo_palettes.py` 存在 |
| **Release notes** — `release_notes.py` | 05aca1a | ✅ `src/utils/release_notes.py` 存在 |
| **Task notifications** — REPL 后台运行通知 | a343acf | ✅ `src/repl/task_notifications.py` 存在 |
| **Advisor enabled flag** — `is_advisor_enabled()` | e404a79 | ✅ `clawcodex_ext/utils/advisor.py` 实现 |
| **Session persistence** — `SessionPersister` | e6e15d9 | ✅ `src/services/session_persistence.py` 存在 |
| **Pricing 更新** — 18+ provider + DeepSeek 缓存价格 | — | ✅ `src/services/pricing.py` 更新 |
| **Config trust boundary** — `_UNTRUSTED_TIER_BLOCKED_KEYS` | 754f57a | ✅ `src/config.py` 实现 |
| **Token budget** — `check_token_budget`/`create_budget_tracker` | d0c93da | ✅ `clawcodex_ext/query/token_budget.py` 存在 |
| **Stop hooks** — `handle_stop_hooks_streaming` | d0c93da | ✅ `clawcodex_ext/query/stop_hooks.py` 存在 |

---

## 5. 部分集成

### 5.1 🟡 Permissions 目录双重组

| 属性 | 内容 |
|------|------|
| **文件名** | `src/permissions/` vs `clawcodex_ext/permissions/` |
| **当前代码状态** | `clawcodex_ext/permissions/__init__.py` 从 `src/permissions/` re-export 符号，同时 `src/permissions/` 也有自己的 `__init__.py`。部分检查逻辑（如 `check_read_permission_for_tool`）仅在 `clawcodex_ext/` 中实现，但 `src/permissions/filesystem.py` 中缺失 |
| **影响** | 当模块直接 `from src.permissions.filesystem import ...` 而非从 `clawcodex_ext` 进入时，可能拿到旧版实现 |

---

## 6. 未集成

### 6.1 🔴 TUI Spinner Row 加强（sparkle + token/elapsed）

| 属性 | 内容 |
|------|------|
| **上游提交** | `07c66ea` |
| **文件** | `clawcodex_ext/tui/widgets/tool_activity/base.py` 及 `clawcodex_ext/tui/widgets/status_line.py` |
| **功能** | 改进的 sparkle spinner 动画 + 实时 token 计数和已用时间的 busy 行渲染，与 ink REPL 对齐 |
| **当前代码** | `clawcodex_ext/tui/widgets/status_line.py` 有基本 spinner（`_SPINNER_FRAMES` 动画 + `is_thinking` 驱动），但缺少实时 token/elapsed 指标行和 sparkle 效果 |
| **影响范围** | 视觉差异——纯功能相关度较低 |

---

## 7. 集成优先级建议

### 唯一剩余项

| 优先级 | 特性 | 预估工作量 | 原因 |
|--------|------|-----------|------|
| **P1** | TUI Spinner Row 加强（sparkle + token/elapsed） | ~50 行修改 | 指标可见性提升；纯视觉，不阻塞功能 |

---

## 8. 附录：文件级对照清单

### 8.1 上游新增 → 当前存在 ✅

| 上游新增文件（`src/` 中） | 当前位置 | 状态 |
|--------------------------|---------|------|
| `src/workflow/*`（19 文件） | `src/workflow/` | ✅ |
| `src/command_system/{copy,diff,doctor,...}_command.py`（14 文件） | `src/command_system/` | ✅ |
| `src/services/{bash_mode,config_health,...}.py`（11 文件） | `src/services/` | ✅ |
| `src/permissions/bash_suggestions.py` | `src/permissions/bash_suggestions.py` | ✅ |
| `src/permissions/settings_paths.py` | `src/permissions/settings_paths.py` | ✅ |
| `src/providers/openai_compatible_specs.py` | `src/providers/openai_compatible_specs.py` | ✅ |
| `src/providers/zai_provider.py` | `src/providers/zai_provider.py` | ✅ |
| `src/constants/spinner_verbs.py` | `src/constants/spinner_verbs.py` | ✅ |
| `src/secret_store.py` | `src/secret_store.py` | ✅ |
| `src/utils/logo_palettes.py` | `src/utils/logo_palettes.py` | ✅ |
| `src/utils/release_notes.py` | `src/utils/release_notes.py` | ✅ |
| `src/repl/task_notifications.py` | `src/repl/task_notifications.py` | ✅ |
| `src/tool_system/tools/workflow.py` | `src/tool_system/tools/workflow.py` | ✅ |
| `src/tui/screens/mcp_approval.py` | `src/tui/screens/mcp_approval.py` | ✅ |
| `src/tui/screens/memory_save.py` | `src/tui/screens/memory_save.py` | ✅ |
| `src/tui/screens/startup_gates.py` | `src/tui/screens/startup_gates.py` | ✅ |
| `src/tui/screens/workflow_dialog.py` | `src/tui/screens/workflow_dialog.py` | ✅ |
| `src/tui/screens/workspace_search.py` | `src/tui/screens/workspace_search.py` | ✅ |
| `src/tui/widgets/queued_commands.py` | `src/tui/widgets/queued_commands.py` | ✅ |
| `src/tui/widgets/shortcuts_help.py` | `src/tui/widgets/shortcuts_help.py` | ✅ |

> **说明**: 以上文件均 100% 存在于当前代码库中。部分文件已通过 `sys.modules` 交换/`__init__.py` 转发到 `clawcodex_ext/` 但功能等效。

### 8.2 上游修改 → 当前已一致 ✅

| 被修改文件 | 关键变更 | 当前状态 |
|-----------|---------|---------|
| `src/permissions/__init__.py` | 移除 `PermissionHandlerCallback`、新增 `PermissionAskHandler` 等 | ✅ 一致 |
| `src/providers/__init__.py` | `zai` 替换 `glm`、18+ OpenAI-compatible | ✅ 一致 |
| `src/tool_system/tools/web_search.py` | Tavily 替换 DuckDuckGo | ✅ 通过 `clawcodex_ext` 转发 |
| `src/tool_system/tools/web_fetch.py` | `_strip_noise_blocks` + markdownify | ✅ 通过 `clawcodex_ext` 转发 |
| `src/query/query.py` | 新增 continuation_nudge, stop_hooks, token_budget, tool_failure_loop 导入 | ✅ 通过 `sys.modules` 交换到 `clawcodex_ext` |
| `src/config.py` | `_UNTRUSTED_TIER_BLOCKED_KEYS` + `_strip_untrusted_keys` | ✅ 一致 |
| `src/providers/deepseek_provider.py` | `is_deepseek` + `_build_usage_dict` | ✅ 一致 |
| `src/permissions/check.py` | `NO_PERMISSION_TOOLS` | ✅ 通过 `clawcodex_ext` 实现 |
| `src/tool_system/tools/skill.py` | `_permission_context_with_skill_bash_rules` | ✅ 通过 `clawcodex_ext` 实现 |
| `clawcodex_ext/providers/openai_compatible.py` | #393 tool-first emit + #394 orphan 保护 | ✅ 已实现 |
| `clawcodex_ext/tui/app.py` | 双击退出 + `action_request_quit` | ✅ 已实现 |
| `clawcodex_ext/tui/widgets/prompt_input.py` | Paste Placeholder + `expand_pastes` | ✅ 已实现 |

### 8.3 上游修改 → 当前未集成 🔴

| 被修改文件 | 所需变更 | 状态 | 工作量 |
|-----------|---------|------|--------|
| `clawcodex_ext/tui/widgets/tool_activity/base.py` 等 | Spinner Row 加强（sparkle + token/elapsed） | 🔴 | ~50 行 |

### 8.4 上游修改 → 当前部分集成 🟡

| 被修改文件 | 缺失部分 | 状态 | 工作量 |
|-----------|---------|------|--------|
| `src/permissions/` vs `clawcodex_ext/permissions/` | 目录双重组，部分检查仅在 ext 层 | 🟡 | 结构性问题 |

---

## 9. 勘误记录

初版审计报告（2026-06-29 生成）存在以下误判，已在 v2 中修正：

| 项目 | 初版判定 | 实际情况 | 修正原因 |
|------|---------|---------|---------|
| OpenAI-compat #393 | 🔴 未集成 | ✅ 已实现 | 审计只检查了文件存在性，未发现代码中已有 tool-first emission 逻辑 |
| OpenAI-compat #394 | 🔴 未集成 | ✅ 已实现 | 同上，`known_tool_call_ids` 预扫描已存在 |
| TUI 双击退出 | 🔴 未集成 | ✅ 已实现 | 审计提取了过时的代码片段，`app.py` 中 `_last_ctrl_c` 已实现 |
| TUI Paste Placeholder | 🔴 未集成 | ✅ 已实现 | `_paste_blobs` + `expand_pastes` + `handle_paste` 已完整实现 |
| `_MAX_VISIBLE_SUGGESTIONS` | 🟡 仍是旧值 10 | ✅ 已是 6 | 代码中已修正 |
| `#` 前缀 memory append | 🟢 已集成 | 🔴 未接线 → ✅ 已修复 | 文件存在但无调用者；已补全 REPL + TUI 接线 |
| TUI Footer Hints | 🟡 缺 `bind_footer()` | ✅ 已修复 | 方法已定义但未调用；已补全 `repl.py` 中的接线 |
| TUI Slash 菜单 | 🟡 缺 `_arg_lookup` + Enter/Tab 分离 | ✅ 已修复 | 补全 `_accept_suggestion` 统一方法 + `takes_args` + Tab 键接受 |
| TUI At-Mentions | 🟡 缺 `files_provider` + `_suggest_mode` | ✅ 已修复 | 补全 `files_provider` 参数 + `_suggest_mode` 双模式追踪 |

---

## 10. 功能冲突分析

在完成全部修复后，逐代码路径分析了新修改与现有二开代码之间的功能冲突。结论：**未发现任何功能冲突**。

### 10.1 `#` 前缀 memory append → 零冲突

| 检查项 | 结果 |
|--------|------|
| REPL 中 `#` 的其他用途 | `session_browser.py:89` 有 `if raw.startswith("#")` 用于会话编号选择 |
| 是否冲突 | 否——session_browser 是 `/resume` 命令触发的独立输入循环（`browse_sessions_interactive`），与主输入循环完全不重叠 |

### 10.2 `_accept_suggestion` vs `on_option_list_option_selected` → 零冲突

| 事件路径 | 触发条件 | 冲突风险 |
|---------|---------|---------|
| `Input.Submitted` → `on_input_submitted` → `_accept_suggestion()` | 焦点在 Input，用户按 Enter | 无——当焦点在 Input 时，OptionList 不接收事件 |
| `OptionList.OptionSelected` → `on_option_list_option_selected` | 焦点在 OptionList，用户按 Enter/Space | 无——`on_key` 的 up/down 分支先将焦点移到 OptionList |

### 10.3 Tab 键 → 零冲突

| 场景 | 行为 | 保证 |
|------|------|------|
| 无弹出菜单，无 ghost | Tab → `focus_next`（bubble） | 不变 |
| 无弹出菜单，有 ghost | Tab → accept ghost | 不变 |
| 有弹出菜单（旧行为） | Tab → ghost check（ghost hidden）→ `focus_next` | ⚠️ 改善为：Tab → accept 菜单高亮项 |
| 有弹出菜单（新行为） | Tab → `_accept_suggestion()` → stop | `_suggest_mode` 与 ghost 互斥：ghost 只在所有 popup 关闭时才显示 |

### 10.4 `bind_footer()` → 零冲突

| 风险 | 缓解措施 |
|------|---------|
| `_footer_ref` 未设置时 `watch_is_thinking` 触发 | `hasattr(self, "_footer_ref")` 守卫跳过更新 |
| 初始化竞争条件 | `bind_state` → `bind_footer` 在 `on_mount` 中同步执行；100ms 定时器在 mount 完成后才启动 |
| 循环更新 | Footer 只被动接收 `set_loading()`，不回写 StatusLine |

**初始化顺序**（`repl.py:on_mount`）：
```
L174 mount(status_bar)        → on_mount 启动 100ms 定时器
L180 bind_state(app_state)    → _app_state 设置
L181 bind_footer(footer)      → _footer_ref 设置  ← 定时器 100ms 后才首次触发
```

### 10.5 `takes_args` / `files_provider` → 完全向后兼容

| 新增字段 | 默认值 | 现有调用者示例 | 影响 |
|---------|--------|--------------|------|
| `CommandSuggestion.takes_args` | `False` | 所有 `CommandSuggestion(...)` | 无——不传即 False |
| `PromptInput.__init__ files_provider` | `None` | `REPLScreen(app.py:260)` 不传 | 无——`None` 走原文件列表路径 |
| `PromptInput._suggest_mode` | `""` | 内部状态 | 无——只在有弹出菜单时非空 |

### 10.6 验证结果

```
稳定性门禁 Stage 1-4        73 passed ✅
稳定性门禁 Stage 3d+3e      108 passed ✅
Orchestrator git_sync       13 passed ✅
Orchestrator issue/报告     129 passed ✅
```

# F-89: @agent-name 多入口统一支持

> 状态: ✅ 已完成（五入口行为统一，未知 agent 给出友好提示）
> 章节: docs/feature_plan/07-other/f-89-agent-name.md
> 最后更新: 2026-07-07

## §1 设计规划

### 1.1 目标

确保所有入口（CLI、REPL、TUI、headless、orchestrator）都支持 `@agent-name` 语法，且行为一致。

### 1.2 当前基线

| 入口 | 支持 @agent-name | 备注 |
|------|:----------------:|------|
| CLI | ✅ | 通过 headless 路径；`--agent <name>` 独立标志 |
| REPL | ✅ | `core.py:_dispatch_user_input` 完整支持 |
| TUI | ✅ | `screens/repl.py:on_prompt_submitted` 完整支持 |
| headless | ✅ | `entrypoints/headless.py` 展开 + 未知 agent 走 `ResultEvent(is_error)` + exit 78 |
| orchestrator | ✅ | `prompt_builder.render_parts` 注入展开；未知 mention 剥离并日志告警 |

### 1.3 子特性

| 子特性 | 描述 | 状态 |
|--------|------|:----:|
| F-89-A | CLI @agent-name 解析 | ✅ |
| F-89-B | REPL @agent-name 完整支持 | ✅ |
| F-89-C | TUI @agent-name 完整支持 | ✅ |
| F-89-D | headless @agent-name 完整支持 | ✅（增加未知 agent 错误路径） |
| F-89-E | orchestrator @agent-name 支持 | ✅ |
| F-89-F | F-89 单元测试覆盖（helper + headless + orchestrator） | ✅（`tests/test_f89_agent_name.py`，9 用例） |

### 1.4 实现要求

- ✅ 所有入口对 `@agent-name` 的解析行为保持一致
- ✅ 支持子命令 / 参数传递（CLI 的 `--agent <name>` 仍由 `dispatch.py` 处理；mention 语法在 prompt 中识别）
- ✅ 未知 agent 名称时给出友好错误提示（REPL/TUI: 即时 stderr；headless: `ResultEvent(is_error)` + 退出码 78；orchestrator: 剥离 mention 并打 WARNING 日志）

## §2 进度跟踪

### 2.1 已实现

- **共享机制**：`src/command_system/input_processing.py` 提供
  `expand_agent_mentions / find_unknown_agent_mentions / format_unknown_agent_mention_error /
  strip_agent_mentions / iter_agent_mention_types` 五个 helper，是五入口的唯一真值源。
- **REPL**（`clawcodex_ext/repl/core.py:5400-5454`）：未识别 agent 即时打印错误并 return；已识别 agent
  通过 `run_mentioned_agent_direct` 走快捷路径或追加 system-reminder 附件。
- **TUI**（`clawcodex_ext/tui/screens/repl.py:278-306`）：与 REPL 等价的错误/展开流；通过
  `get_agents_for_mentions` 合并 workspace + bundle agents。
- **Headless**（`clawcodex_ext/entrypoints/headless.py:563-606`）：未识别 agent 走
  `ResultEvent(is_error=True, error=format_unknown_agent_mention_error(...))` + 退出码 78（EX_CONFIG）；
  不会浪费 model turn。
- **Orchestrator**（`extensions/orchestrator/prompt_builder.py:332-372 + 657-731`）：新增
  `_expand_agent_mentions_in_prompt` 在 `render_parts()` 尾部注入展开；best-effort（不会因为
  mention 缺失打断 agent run）；未识别 mention 通过 `strip_agent_mentions` 清理并记录 WARNING。
- **CLI**：保持原有 `--agent <name>` 标志 + 通过 headless 处理 `@agent-` mention。

### 2.2 已解决瓶颈

- 多入口行为不一致 —— 已统一通过共享 helper + 一致的 `format_unknown_agent_mention_error` 文案。
- Headless 未知 agent 静默 pass —— 现在以 `ResultEvent` 退出，调用方可在 SDK 客户端直接捕获。
- Orchestrator 未支持 mention 展开 —— `render_parts()` 新增 best-effort 展开钩子。

## §3 测试覆盖

新增 `tests/test_f89_agent_name.py`（9 用例）：

1. `test_unknown_agent_mention_isolated` — 共享 helper 返回 typo 的 agent_type。
2. `test_known_agent_mention_is_skipped` — 已知 agent 不出现在未知列表。
3. `test_format_error_suggests_close_match` — `format_unknown_agent_mention_error` 给出 close-match 建议。
4. `test_headless_unknown_agent_emits_error_result` — headless 路径下 Provider 不被调用 +
   退出码 78 + `ResultEvent(is_error)` 包含 `Unknown agent`。
5. `test_headless_known_agent_proceeds_to_provider` — 已知 agent 正常进入模型调用。
6. `test_render_parts_expands_known_mention` — orchestrator 路径产出含
   `<system-reminder>` + `subagent_type="critic"` 的 user prompt。
7. `test_render_parts_strips_unknown_mention_with_warning` — 未知 mention 被剥离 + WARNING 日志。
8. `test_render_parts_no_session_still_succeeds` — `session=None` 不崩。
9. `test_render_parts_no_workspace_still_succeeds` — `workspace.path=None` 不崩。

REPL/TUI 通过现有 `_dispatch_user_input` / `on_prompt_submitted` 测试套件间接覆盖；共享 helper
测试 + 已知 agent orchestrator 测试确保五入口行为一致。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-07-07 | headless：增加 `find_unknown_agent_mentions` 前置检查，未识别时返回 `ResultEvent(is_error=True)` + 退出码 78 | 五入口错误路径统一 |
| 2026-07-07 | orchestrator：`PromptBuilder.render_parts` 接入 `_expand_agent_mentions_in_prompt`，展开已知 mention / 剥离未知 mention | 新增 orchestrator 入口支持 |
| 2026-07-07 | 新增 `tests/test_f89_agent_name.py`（9 用例） | 回归保护 + 五入口合约验证 |
| 2026-07-07 | 文档状态推进到 ✅；1.2 / 1.3 / §2 / §3 / §4 全量更新 | 完成态对齐 |

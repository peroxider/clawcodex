# Feature Clusters — ClawCodex 扩展层分组索引

> 自动生成于 2026-07-25，基于对 `clawcodex_ext/`（Layer 1）与 `extensions/`（Layer 2）两大扩展层的只读盘点。
>
> **统计口径**：`.py` 行数 = `wc -l <file>`（按换行符计数）；字节数 = `ls -la` 第 5 列；排除 `__pycache__/` 与 `.pyc`。
> **总规模**：16 个特性分组（含 L1-⑧ / L2-⑨ 同名待迁移项），覆盖 75 个子目录 / 1,549 个 .py 文件 / 373,037 行 / 13.85 MB。
> **测试规模**：`tests/` 下约 660+ 个 .py 文件 / 250K+ 行（详见附录 D）。
> **配套原则**：本文档索引对应 `CLAUDE.md` 中的"二次开发解耦原则"。

## 目录

- [Layer 1 — clawcodex_ext/（下游补丁层）](#layer-1--clawcodex_ext下游补丁层)
  - [L1-① 核心运行时补丁](#l1-①-核心运行时补丁)
  - [L1-② CLI 与入口层](#l1-②-cli-与入口层)
  - [L1-③ TUI/REPL/前端](#l1-③-tuirepl前端)
  - [L1-④ 权限/鉴权/钩子/安全](#l1-④-权限鉴权钩子安全)
  - [L1-⑤ 智能子系统](#l1-⑤-智能子系统)
  - [L1-⑥ 调度/Cron/后台任务](#l1-⑥-调度cron后台任务)
  - [L1-⑦ 基础设施](#l1-⑦-基础设施)
  - [L1-⑧ Community Radar（待迁出）](#l1-⑧-community-radar待迁出)
- [Layer 2 — extensions/（三方扩展层）](#layer-2--extensions三方扩展层)
  - [L2-① Orchestrator 主干](#l2-①-orchestrator-主干)
  - [L2-② SOP 编译器](#l2-②-sop-编译器)
  - [L2-③ LKB 独立子包](#l2-③-lkb-独立子包)
  - [L2-④ 公开 API 与远程](#l2-④-公开-api-与远程)
  - [L2-⑤ 守护与 IM 网关](#l2-⑤-守护与-im-网关)
  - [L2-⑥ 协议契约 + Prompt Lab](#l2-⑥-协议契约--prompt-lab)
  - [L2-⑦ 观测栈](#l2-⑦-观测栈)
  - [L2-⑧ 三方 Agent/Skills/Tool System 扩展](#l2-⑧-三方-agentskillstool-system-扩展)
  - [L2-⑨ Community Radar（待迁入）](#l2-⑨-community-radar待迁入)
- [附录 A：合计统计](#附录-a合计统计)
- [附录 B：迁移影响](#附录-b迁移影响)
- [附录 C：异常 / 注意](#附录-c异常--注意)
- [附录 D：测试用例代码行数统计](#附录-d测试用例代码行数统计)

---

## Layer 1 — clawcodex_ext/（下游补丁层）

> Layer 1 的语义是"对 `src/` 上游模块做增强/覆盖/补丁"。分组原则：按"被增强的上游模块族"聚合。
> **合计**：8 个特性 / 51 个子目录 / 1,046 个 .py 文件 / 242,612 行 / 8.96 MB。

### L1-① 核心运行时补丁

- **体量**：9 个子目录 / 504 个 .py 文件 / 121,965 行 / 4.53 MB
- **定位**：代理 / 命令 / 工具 / 查询 / Provider / 桥接 / 传输 / 会话存储 — Layer 1 的主干，被 Layer 2 大量反向调用
- **子目录**：
  - `agent/` — Downstream agent extensions — registry, policy primitives, and bundled agents.
  - `command_system/` — Command system for Claw Codex.
  - `tool_system/` — Tool system package — tool definitions + downstream team-aware pool.
  - `query/` — (无 `__init__.py`，首文件 `clawcodex_ext/query/query.py`：查询引擎主入口)
  - `providers/` — Downstream provider extensions — model discovery hooks and provider overrides.
  - `bridge/` — Downstream ClawCodex bridge implementations.
  - `transports/` — (无 `__init__.py`，首文件 `clawcodex_ext/transports/ccr_client.py`：CCR Bridge v2 write transport)
  - `remote/` — Canonical remote implementations for Claw Codex extensions.
  - `services/` — (Auto-generated `__init__.py`；子目录含 analytics / api / bridge / channels / mcp / oauth / proactive / swarm 等)
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/query/query.py` | 3,482 |
  | `clawcodex_ext/command_system/builtins.py` | 2,030 |
  | `clawcodex_ext/tool_system/tools/agent.py` | 1,631 |
  | `clawcodex_ext/services/channels/wechat_ilink.py` | 1,567 |
  | `clawcodex_ext/services/mcp/config.py` | 1,197 |
  | `clawcodex_ext/tool_system/tools/bash/bash_tool.py` | 1,104 |
  | `clawcodex_ext/query/agent_loop_compat.py` | 1,094 |
  | `clawcodex_ext/providers/openai_compatible.py` | 1,093 |
  | `clawcodex_ext/command_system/input_processing.py` | 1,054 |
  | `clawcodex_ext/services/channels/feishu_app.py` | 1,011 |

- **典型依赖**：高度依赖 Layer 1 自身（`clawcodex_ext.services` 73 次、`clawcodex_ext.agent` 49 次、`clawcodex_ext.types` 35 次、`clawcodex_ext.tool_system` 30 次、`clawcodex_ext.providers` 29 次），并向上反向调用 `src.command_system` / `src.utils` / `src.tool_system`。
- **关键观察**：`services/` 子包占比最大（257 文件 / 1.98 MB），是本特性偏重主因。
- **测试覆盖**：
  - 主测目录：`tests/agent/`(6,172 行)、`tests/bridge/`(9,801)、`tests/transports/`(491)、`tests/services/`(1,356，含 im_gateway/swarm/oauth 部分)、`tests/query/`(3,158)、`tests/provider/`(3,985)、`tests/proactive/`(293)、`tests/streaming/`(514)、`tests/bash/`(1,448 中 bash_tool 部分 ≈724)、`tests/tool_system/`(1,448 中 team_aware_pool/loader 部分 ≈724)、`tests/permissions/`(3,420 中 classifier/cycle ≈1,710)、`tests/abort/`(2,326 中 agent_loop 部分 ≈1,163)、`tests/sessions/`(1,209 中 session 部分 ≈604)、`tests/message/`(1,166 中 bridge 消息部分 ≈583)
  - 顶层文件：`tests/test_agent_name.py`(453)
  - **合计**：约 165 个 .py 文件 / 31,229 行测试代码
  - 详见 [附录 D L1-① 测试映射](#附录-d测试用例代码行数统计)

---

### L1-② CLI 与入口层

- **体量**：4 个子目录 / 59 个 .py 文件 / 14,498 行 / 550 KB
- **定位**：CLI dispatch、subcommand_registry、headless/TUI/orchestrator/MCP 入口
- **子目录**：
  - `cli/` — Downstream CLI extensions.
  - `cli_core/` — (无 `__init__.py`，首文件 `cli_core/exit.py`：CLI exit helpers，Port of `typescript/src/cli/exit.ts`)
  - `entrypoints/` — Lazy entrypoint exports for legacy and current UI launchers.
  - `daemon/` — F-84 Daemon downstream extension hooks（仅 `__init__.py` shim，真实在 `extensions/daemon/`）。
- **顶层文件（11 个）**：`__init__.py` / `init.py` / `config.py` / `_version.py` / `llm.py` / `mcp_ext.py` / `task_registry.py` / `tasks_core.py` / `telemetry_lifecycle.py` / `tool_stats.py` / `outputStyles.py`
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/entrypoints/headless.py` | 2,564 |
  | `clawcodex_ext/cli/channels_cmd/commands.py` | 1,347 |
  | `clawcodex_ext/cli/sop_cmd/commands.py` | 1,274 |
  | `clawcodex_ext/cli/dispatch.py` | 1,144 |
  | `clawcodex_ext/cli/lkb_method_cmd/commands.py` | 752 |
  | `clawcodex_ext/cli/runtime_commands.py` | 517 |
  | `clawcodex_ext/cli/runners.py` | 439 |
  | `clawcodex_ext/entrypoints/tui.py` | 399 |
  | `clawcodex_ext/cli/parser.py` | 363 |
  | `clawcodex_ext/cli/_interactive.py` | 350 |

- **典型依赖**：大量调用 `clawcodex_ext.cli` (31 次)、`clawcodex_ext.logical_kanban` (6)、`clawcodex_ext.command_system` (6)、`src.tool_system` (3)、`src.config` (3)、`src.providers` (2)、`src.cli_core` (2)。
- **测试覆盖**：
  - 主测目录：`tests/cli/`(7,180)、`tests/command_system/`(1,917)、`tests/runtime/`(596)、`tests/stability_gate/`(9,040，含 Stage 1-10 全栈预演)、`tests/skills/`(8,306 中 command_system 部分 ≈4,153)
  - 顶层文件：`tests/conftest.py`(146)、`tests/test_agent_name.py`(453)、`tests/test_llm.py`(186)、`tests/test_mcp_ext.py`(281)、`tests/test_session_chain.py`(496)
  - **合计**：约 100+ 个 .py 文件 / 24,448 行测试代码
  - 详见 [附录 D L1-② 测试映射](#附录-d测试用例代码行数统计)

---

### L1-③ TUI/REPL/前端

- **体量**：5 个子目录 / 122 个 .py 文件 / 33,526 行 / 1.28 MB
- **定位**：ClawCodexExtREPL、TUI vim/主题/键盘绑定、freeze_config 调试辅助
- **子目录**：
  - `tui/` — Downstream TUI extensions — lazy proxy for circular-safety.
  - `repl/` — (Auto-generated `__init__.py`；ClawCodexExtREPL 主入口)
  - `frontend/` — Downstream frontend extensions — plugin-based frontend registry.
  - `diagnostics/` — Diagnostics primitives (F-108 §十八) — freeze-detection watchdog.
  - `debug/` — Developer-only debugging helpers for ClawCodex.
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/repl/core.py` | 7,197 |
  | `clawcodex_ext/tui/app.py` | 1,957 |
  | `clawcodex_ext/tui/widgets/prompt_input.py` | 1,355 |
  | `clawcodex_ext/debug/repl_pty_session.py` | 1,292 |
  | `clawcodex_ext/tui/agent_bridge.py` | 1,167 |
  | `clawcodex_ext/frontend/repl_extensions.py` | 1,115 |
  | `clawcodex_ext/repl/app.py` | 947 |
  | `clawcodex_ext/tui/vim_state.py` | 923 |
  | `clawcodex_ext/repl/live_status.py` | 785 |
  | `clawcodex_ext/diagnostics/freeze_detector.py` | 506 |

- **典型依赖**：主要调用 `clawcodex_ext.services` (11)、`clawcodex_ext.frontend` (11)、`clawcodex_ext.intent_forecast` (10)、`src.tool_system` (8)、`src.utils` (5)、`clawcodex_ext.away_summary` (5)、`src.agent` (4)、`clawcodex_ext.multimodel` (4)。
- **测试覆盖**：
  - 主测目录：`tests/repl/`(3,883)、`tests/frontend/`(1,669)、`tests/tui/`(9,421)、`tests/debug/`(2,433)、`tests/diagnostics/`(970)
  - **合计**：约 68 个 .py 文件 / 18,376 行测试代码
  - 详见 [附录 D L1-③ 测试映射](#附录-d测试用例代码行数统计)

---

### L1-④ 权限/鉴权/钩子/安全

- **体量**：4 个子目录 / 51 个 .py 文件 / 12,952 行 / 453 KB
- **定位**：权限引擎、OAuth/Codex/Gemini/AWS、Pre/PostToolUse 等钩子
- **子目录**：
  - `permissions/` — Permissions package — core + downstream extensions.
  - `auth/` — Canonical public surface for :mod:`clawcodex_ext.auth`.
  - `hooks/` — Hook system — PreToolUse, PostToolUse, Stop, Notification, PostSampling hook execution runtime.
  - `bootstrap/` — Compatibility facade package — see :mod:`src.bootstrap`.
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/hooks/hook_executor.py` | 1,330 |
  | `clawcodex_ext/permissions/check.py` | 872 |
  | `clawcodex_ext/permissions/updates.py` | 764 |
  | `clawcodex_ext/permissions/bash_suggestions.py` | 700 |
  | `clawcodex_ext/hooks/config_manager.py` | 584 |
  | `clawcodex_ext/auth/codex_store.py` | 474 |
  | `clawcodex_ext/permissions/powershell_security.py` | 471 |
  | `clawcodex_ext/permissions/filesystem.py` | 460 |
  | `clawcodex_ext/permissions/trust_boundary.py` | 456 |
  | `clawcodex_ext/permissions/types.py` | 401 |

- **典型依赖**：高密度调用 `clawcodex_ext.permissions` (18)、`clawcodex_ext.hooks` (3)、`clawcodex_ext.capabilities` (2)、`clawcodex_ext.auth` (2)、`src.utils` / `src.tool_system` / `src.state` / `src.bootstrap` 各 1。
- **测试覆盖**：
  - 主测目录：`tests/permissions/`(3,420 中 shell_security/danger_detector/handler 部分 ≈1,710)、`tests/auth/`(1,057)、`tests/hooks/`(1,869)、`tests/bootstrap/`(535)、`tests/bash/`(1,448 中 bash_security 部分 ≈724)、`tests/git_fixtures/`(488，含 `test_git_context` 等 git 安全测试)
  - **合计**：约 36 个 .py 文件 / 6,383 行测试代码
  - 详见 [附录 D L1-④ 测试映射](#附录-d测试用例代码行数统计)

---

### L1-⑤ 智能子系统

- **体量**：12 个子目录 / 176 个 .py 文件 / 23,491 行 / 867 KB
- **定位**：Dreaming、Intent Forecast、Away Summary、Goal Boundary、LKB 兼容 shim、Buddy 语音
- **子目录**：
  - `away_summary/` — Away Summary extension package.
  - `intent_forecast/` — Intent Forecast extension.
  - `dreaming/` — Dreaming — F-100 background memory consolidation subsystem.
  - `session_intelligence/` — Session intelligence sidecar helpers.
  - `goal/` — Spec-1 goal boundary.
  - `memdir/` — Canonical public surface for :mod:`clawcodex_ext.memdir`.
  - `memory/` — Memory scope isolation extension.
  - `context_system/` — Context system — package init.
  - `coordinator/` — (无 `__init__.py`，首文件 `coordinator/mode.py`：Coordinator-mode gates and tool-set filters)
  - `multimodel/` — Multi-model scheduling extension.
  - `logical_kanban/` — Compatibility shim — re-export from lkb standalone package.
  - `buddy/` — Canonical public surface for :mod:`clawcodex_ext.buddy`.
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/context_system/prompt_assembly.py` | 1,669 |
  | `clawcodex_ext/away_summary/service.py` | 897 |
  | `clawcodex_ext/goal/evaluator.py` | 678 |
  | `clawcodex_ext/context_system/claude_md.py` | 620 |
  | `clawcodex_ext/goal/service.py` | 609 |
  | `clawcodex_ext/intent_forecast/context.py` | 601 |
  | `clawcodex_ext/goal/store.py` | 597 |
  | `clawcodex_ext/buddy/sprites.py` | 535 |
  | `clawcodex_ext/goal/runtime.py` | 498 |
  | `clawcodex_ext/memdir/memdir.py` | 479 |

- **典型依赖**：特性内交叉调用密集 — `clawcodex_ext.intent_forecast` 36 次、`clawcodex_ext.away_summary` 18、`clawcodex_ext.capabilities` 17、`clawcodex_ext.dreaming` 13、`clawcodex_ext.types` 7、`clawcodex_ext.providers` 7、`clawcodex_ext.context_system` 7、`clawcodex_ext.buddy` 7，外加 `src.memdir` 5 次。
- **测试覆盖**：
  - 主测目录：`tests/away_summary/`(2,672)、`tests/dreaming/`(2,030)、`tests/intent_forecast/`(1,652)、`tests/session_intelligence/`(61)、`tests/goal/`(2,980)、`tests/memdir/`(1,445)、`tests/context/`(521)、`tests/multimodel/`(572)、`tests/logical_kanban/`(12,867 — 与 L2-③ 共测)、`tests/coordinator/`(637)、`tests/advisor/`(2,212)
  - **合计**：约 110 个 .py 文件 / 27,649 行测试代码
  - 详见 [附录 D L1-⑤ 测试映射](#附录-d测试用例代码行数统计)

---

### L1-⑥ 调度/Cron/后台任务

- **体量**：7 个子目录 / 41 个 .py 文件 / 8,884 行 / 312 KB
- **定位**：分布式锁 Cron、F-94 后台会话、特性开关、F-81 原生模块、Assistant shim
- **子目录**：
  - `cron_system/` — Downstream Cron execution engine.
  - `tasks/` — F-94 BG_SESSIONS — 后台会话统一管理.
  - `feature_gate/` — Feature Gate — runtime feature toggle system.
  - `compact_service/` — Compact service — boundary markers and command-facing compaction wrapper.
  - `assistant/` — (Auto-generated `__init__.py`；Assistant shim)
  - `models/` — Model system extensions — model config registry and discovery hooks.
  - `native/` — F-81: Native 原生模块系统 — 统一注册表与懒加载基础设施.
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/cron_system/tasks.py` | 558 |
  | `clawcodex_ext/cron_system/scheduler.py` | 557 |
  | `clawcodex_ext/cron_system/runs.py` | 477 |
  | `clawcodex_ext/cron_system/lock.py` | 426 |
  | `clawcodex_ext/tasks/bg_session_manager.py` | 407 |
  | `clawcodex_ext/cron_system/tools.py` | 344 |
  | `clawcodex_ext/cron_system/models.py` | 330 |
  | `clawcodex_ext/tasks/bg_session.py` | 327 |
  | `clawcodex_ext/feature_gate/registry.py` | 321 |
  | `clawcodex_ext/native/modifiers.py` | 301 |

- **典型依赖**：以 Layer 1 内部与 `src.tool_system` 为主 — `clawcodex_ext.native` 4、`src.tool_system` 3、`src.models` 2、`clawcodex_ext.types` 2、`clawcodex_ext.query` 2，外加 `extensions.recording` / `extensions.capabilities` 各 1（说明已反向依赖 Layer 2 协议契约）。
- **测试覆盖**：
  - 主测目录：`tests/cron/`(估算 ≈4,618)、`tests/tasks/`(3,000)、`tests/feature_gate/`(1,167)、`tests/compact/`(2,136)、`tests/assistant/`(478)、`tests/fast/`(256)、`tests/voice/`(2,493)、`tests/ide/`(210)、`tests/model/`(271)
  - **合计**：约 50 个 .py 文件 / 14,629 行测试代码
  - 详见 [附录 D L1-⑥ 测试映射](#附录-d测试用例代码行数统计)

---

### L1-⑦ 基础设施

- **体量**：9 个子目录 / 55 个 .py 文件 / 12,198 行 / 442 KB
- **定位**：消息/内容/流事件类型、工具函数、配置发现、Pydantic settings、app_state
- **子目录**：
  - `types/` — Typed message/content/stream-event models — full upstream re-exports.
  - `utils/` — (Auto-generated `__init__.py`；子模块含 advisor / at_file_completer / image_processor / token_estimation / stream_watchdog / git / messages / message_mappers 等)
  - `constants/` — (无 `__init__.py`，首文件 `constants/xml.py`：XML tag constants for chapter-10 task notifications)
  - `capabilities/` — Capabilities bridge — re-exports from extensions.capabilities.
  - `configuration/` — Scoped configuration discovery, mutation, and runtime integration.
  - `settings/` — (Auto-generated `__init__.py`；Pydantic settings adapter / types / validation)
  - `state/` — Python package placeholder for the archived `state` subsystem.
  - `messaging/` — Messaging subsystem (downstream).
  - `agent_mention/` — (空目录，仅 `__pycache__/` 残留)
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/types/messages.py` | 864 |
  | `clawcodex_ext/utils/advisor.py` | 850 |
  | `clawcodex_ext/configuration/service.py` | 786 |
  | `clawcodex_ext/utils/at_file_completer.py` | 769 |
  | `clawcodex_ext/configuration/contract.py` | 626 |
  | `clawcodex_ext/settings/types.py` | 623 |
  | `clawcodex_ext/state/app_state.py` | 607 |
  | `clawcodex_ext/utils/image_processor.py` | 556 |
  | `clawcodex_ext/utils/token_estimation.py` | 481 |
  | `clawcodex_ext/utils/stream_watchdog.py` | 454 |

- **典型依赖**：本特性作为 Layer 1 的"水与电"，对外引用较少且分散 — `extensions.capabilities` 8、`clawcodex_ext.types` 6、`src.bootstrap` 3、`clawcodex_ext.services` 3、`src.utils` / `src.types` / `src.settings` 各 2。
- **测试覆盖**：
  - 主测目录：`tests/config/`(1,296)、`tests/cache/`(576)、`tests/cost_tracker/`(528)、`tests/file_ops/`(307)、`tests/utils/`(813)、`tests/state/`(656)、`tests/messaging/`(279)、`tests/image/`(471)、`tests/input/`(1,858)、`tests/system_prompt/`(828)、`tests/sessions/`(1,209 中 session_storage 部分 ≈604)、`tests/snapshot/`(274)、`tests/signal_tests/`(165)、`tests/provider/`(1,876)、`tests/release_smoke/`(260)、`tests/ci/`(888)、`tests/abort/`(2,326 中 utils 部分 ≈1,163)、`tests/message/`(1,166 中 messaging 部分 ≈583)、`tests/token_tests/`(743)、`tests/output/`(207)、`tests/analytics/`(118)
  - **合计**：约 100+ 个 .py 文件 / 14,759 行测试代码
  - 详见 [附录 D L1-⑦ 测试映射](#附录-d测试用例代码行数统计)

---

### L1-⑧ Community Radar（待迁出）

- **体量**：1 个子目录 / 38 个 .py 文件 / 15,098 行 / 558 KB
- **定位**：SR-5.1 Community Feature Radar（discover / fetcher / classifier / extractor / scorer / dedup / pipeline / reporter / notifier / issue_sync / i18n / cron 集成）
- **子目录**：
  - `community_radar/` — SR-5.1 Community Feature Radar。子目录含 `templates/`、`tests/`。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `clawcodex_ext/community_radar/reporter.py` | 1,135 |
  | `clawcodex_ext/community_radar/tests/test_issue_sync.py` | 1,026 |
  | `clawcodex_ext/community_radar/fetcher.py` | 1,004 |
  | `clawcodex_ext/community_radar/pipeline.py` | 933 |
  | `clawcodex_ext/community_radar/tests/test_fetcher.py` | 823 |
  | `clawcodex_ext/community_radar/issue_sync.py` | 818 |
  | `clawcodex_ext/community_radar/cli.py` | 781 |
  | `clawcodex_ext/community_radar/classifier.py` | 674 |
  | `clawcodex_ext/community_radar/models.py` | 555 |
  | `clawcodex_ext/community_radar/tests/test_reporter.py` | 518 |

- **典型依赖**：本包为高度内聚子域，`from clawcodex_ext.community_radar.*` 占绝大多数；唯一外部调用点为 `clawcodex_ext/cli/subcommand_registry.py:91` 的 `from clawcodex_ext.community_radar.cli import register_community_radar_subcommand`。
- **迁移原因**：按设计意图本就是 Layer 2 子系统临时寄存在 Layer 1（见 `__init__.py` docstring）。
- **测试覆盖**：
  - 内嵌测试：`clawcodex_ext/community_radar/tests/`(4 个 .py / 估算 ≈2,500 行，含 `test_issue_sync.py` 1,026 行、`test_fetcher.py` 823 行、`test_reporter.py` 518 行等)
  - 外部覆盖：当前 `tests/` 下无独立目录覆盖 Community Radar；CI 跑通依赖该内嵌 `tests/` 子包
  - **合计**：约 4 个 .py 文件 / 2,500 行测试代码（内嵌）
  - 详见 [附录 D L1-⑧ 测试映射](#附录-d测试用例代码行数统计)

---

## Layer 2 — extensions/（三方扩展层）

> Layer 2 的语义是"全新子系统、跨进程守护、远程接入、可插拔能力"。分组原则：按"独立可运行的子系统"聚合。
> **合计**：8+1 个特性（含 L2-⑨ 待迁入）/ 24 个子目录 / 503 个 .py 文件 / 130,425 行 / 4.89 MB（不含 L2-⑨）。

### L2-① Orchestrator 主干

- **体量**：2 个子目录 / 128 个 .py 文件 / 46,998 行 / 1.82 MB
- **定位**：自治模式核心：agent_runner / git_sync / tracker / workflow / workspace / prompt_builder / rules_learner + 解耦运行时
- **子目录**：
  - `orchestrator/` — Orchestrator subsystem for autonomous mode.
  - `orchestrator_runtime/` — Orchestrator 解耦运行时子模块（仓内孵化层，ORCHESTRATOR_USE_RUNTIME 委托路径）。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/orchestrator/orchestrator.py` | 4,729 |
  | `extensions/orchestrator/cli/issue.py` | 3,269 |
  | `extensions/orchestrator/agent_runner.py` | 3,033 |
  | `extensions/orchestrator/git_sync.py` | 1,747 |
  | `extensions/orchestrator/cli/dashboard.py` | 1,598 |
  | `extensions/orchestrator/repo_tracker/client.py` | 1,541 |
  | `extensions/orchestrator/config/schema.py` | 1,297 |
  | `extensions/orchestrator/cli/server.py` | 1,294 |
  | `extensions/orchestrator/issue_registry.py` | 1,105 |
  | `extensions/orchestrator/prompt_builder.py` | 1,079 |

- **典型依赖**：内部 `extensions.orchestrator_runtime` 20 次、`extensions.orchestrator` 6 次，向下调用 `clawcodex_ext.services` 3、`extensions.capabilities` 1、`extensions.api` 1、`clawcodex_ext.utils` / `clawcodex_ext.tool_system` / `clawcodex_ext.messaging` / `clawcodex_ext.agent` 各 1。
- **测试覆盖**：
  - 主测目录：`tests/orchestrator/`(71 个 .py / 34,202 行 — **整仓最大单测目录**，含 `manual_e2e_f38.py` / `manual_e2e_f124.py`)、`tests/upstream_sync/`(90)
  - 跨目录辅助：`tests/stability_gate/`(9,040 中 stage5/stage6 部分)、`tests/mcp/`(5,063 中 orchestrator-mcp 部分)、`tests/extensions/daemon/`(聚合)
  - **合计**：约 75 个 .py 文件 / 34,300 行测试代码（不含 stage5/stage6 共享部分）
  - 详见 [附录 D L2-① 测试映射](#附录-d测试用例代码行数统计)

---

### L2-② SOP 编译器

- **体量**：1 个子目录 / 159 个 .py 文件 / 30,316 行 / 1.09 MB
- **定位**：把 `workflow.md` 编译成可复用 Agent bundle
- **子目录**：
  - `sop_converter/` — SOP converter — transforms professional workflows into reusable Agents（含 `adapters/` / `core/` / `dependency/` / `heuristics/` / `runtime/` / `workflow_mode/` 子包；顶层约 30+ 文件为 star-import 转发 shim）。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/sop_converter/runtime/tool_registry_bridge.py` | 3,557 |
  | `extensions/sop_converter/core/type_schema.py` | 2,129 |
  | `extensions/sop_converter/runtime/skill_grouper.py` | 1,312 |
  | `extensions/sop_converter/core/source_parser.py` | 911 |
  | `extensions/sop_converter/core/bundle_venv.py` | 824 |
  | `extensions/sop_converter/core/resource_catalog.py` | 781 |
  | `extensions/sop_converter/runtime/task_guide.py` | 724 |
  | `extensions/sop_converter/runtime/cross_domain_orchestration.py` | 653 |
  | `extensions/sop_converter/runtime/sop_exploration_guard.py` | 615 |
  | `extensions/sop_converter/runtime/agent_md_writer.py` | 551 |

- **典型依赖**：以本包内部 `extensions.sop_converter.*` 53 次为主，对外引用 `extensions.capabilities` 17 次、`extensions.recording` 1 次。
- **特别说明**：SOP 转换器严格遵循"协议在 Layer 2、实现可用 Layer 1 能力"的边界 — 通过 `extensions.capabilities` 的 Protocol 与 `tool_registry_bridge` 实现跨层桥接。
- **测试覆盖**：
  - 主测目录：`tests/sop_converter/`(4 个 .py / 402 行 — 现有覆盖率偏低，主要测协议桥接与 skill_grouper provider swap)
  - 跨目录辅助：`tests/misc/`(22,618 中 sop_converter 相关测试)、`tests/extensions/capabilities/`(聚合 — sop_provider_protocol 部分)
  - **合计**：约 6 个 .py 文件 / 402 行直接测试代码 + 估算 1,500 行 misc 间接测试 = 约 1,900 行
  - 详见 [附录 D L2-② 测试映射](#附录-d测试用例代码行数统计)

---

### L2-③ LKB 独立子包

- **体量**：1 个子目录 / 51 个 .py 文件 / 19,715 行 / 736 KB
- **定位**：Logical Kanban Boards（任务分解 / ATP 求解 / 多世界验证 / 因果审计）
- **子目录**：
  - `lkb/` — lkb MCP Server；lkb — Logical Kanban Boards，独立 Python package（自带 `pyproject.toml` / `README.md`，无顶层 `__init__.py`，从 `lkb/src/` 开始算）。可单独 `pip install lkb`，但仍位于 `extensions/` 之下作 monorepo 托管。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/lkb/src/lkb/service.py` | 2,081 |
  | `extensions/lkb/src/lkb/solver_adapter.py` | 1,925 |
  | `extensions/lkb/src/lkb/method_seed.py` | 1,401 |
  | `extensions/lkb/src/lkb/decomposer.py` | 1,149 |
  | `extensions/lkb/src/lkb/audit.py` | 805 |
  | `extensions/lkb/src/lkb/scheduling_solver.py` | 766 |
  | `extensions/lkb/tests/test_f154_external_config.py` | 762 |
  | `extensions/lkb/src/lkb/method_library.py` | 757 |
  | `extensions/lkb/src/lkb/rule_engine.py` | 747 |
  | `extensions/lkb/tests/test_f153_method_governance.py` | 692 |

- **典型依赖**：本包完全自包含 — 内部 `lkb.types` 12、`lkb.context_adapter` 9、`lkb.solver_adapter` 6、`lkb.rule_engine` 5、`lkb.fuzzy_types` 5、`lkb.decomposer` 4、`lkb.audit` 4，对外零依赖（`clawcodex_ext.logical_kanban/` 是其 compat shim）。
- **测试覆盖**：
  - 内嵌测试：`extensions/lkb/tests/`(估算 ≈6,500 行，含 `test_f154_external_config.py` 762 行、`test_f153_method_governance.py` 692 行等)
  - 外部覆盖：`tests/logical_kanban/`(27 个 .py / 12,867 行 — **L1-⑤ 与 L2-③ 共测**，主测 `clawcodex_ext.logical_kanban` compat shim 与 feature_gate 集成)
  - **合计**：约 30 个 .py 文件 / 19,400 行测试代码（内嵌 + 外部）
  - 详见 [附录 D L2-③ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-④ 公开 API 与远程

- **体量**：3 个子目录 / 20 个 .py 文件 / 4,506 行 / 174 KB
- **定位**：公开 Python API、Hermes 兼容 Remote Agent API、Trae IDE 反向桥
- **子目录**：
  - `api/` — Public Python API for ClawCodex（暴露 `OrchestrationSubsystem` / `QueryConfig` / `QueryRunner` / `QueryEvent`）。
  - `remote_api/` — Hermes-compatible Remote Agent API extension（FastAPI server）。
  - `trae/` — F-66 Trae IDE 集成（`mcp_bridge` MCP 反向桥 + `acp_cli_adapter` 把 trae-cli 包装为伪 ACP server）。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/remote_api/core.py` | 1,292 |
  | `extensions/api/query.py` | 659 |
  | `extensions/trae/mcp_bridge.py` | 523 |
  | `extensions/remote_api/runner.py` | 352 |
  | `extensions/trae/acp_cli_adapter.py` | 335 |
  | `extensions/remote_api/normalization.py` | 270 |
  | `extensions/remote_api/stdlib_server.py` | 208 |
  | `extensions/remote_api/server.py` | 163 |
  | `extensions/api/orchestration.py` | 152 |
  | `extensions/remote_api/cli.py` | 104 |

- **典型依赖**：通过 Layer 2 协议反向使用 `clawcodex_ext.types` 4、`extensions.capabilities` 2、`clawcodex_ext.tool_system` 1、`clawcodex_ext.services` 1。删除本组可回滚而不影响 `src/` / `clawcodex_ext/` 主干。
- **测试覆盖**：
  - 主测目录：`tests/api/`(1,583)、`tests/remote/`(1,013)、`tests/remote_api/`(1,450)、`tests/trae/`(899)
  - **合计**：约 20 个 .py 文件 / 4,945 行测试代码
  - 详见 [附录 D L2-④ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-⑤ 守护与 IM 网关

- **体量**：3 个子目录 / 28 个 .py 文件 / 9,355 行 / 352 KB
- **定位**：监督进程守护、IM 网关、桥接端口
- **子目录**：
  - `daemon/` — F-84 Daemon — long-running supervisor for worker subprocesses（`src/daemon/main.ts` Python 等价）。
  - `im_gateway/` — IM Message Gateway daemon process（POSIX UDS 监听）。
  - `ports/` — (无 `__init__.py`；含 `bridge/` + `transports/` 子包：`bridge_main.py` / `remote_bridge_core.py` / `repl_bridge.py` / `session_runner.py`；`transports/`：`websocket_v1.py` / `serial_uploader.py` / `hybrid_v1.py`)
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/ports/bridge/remote_bridge_core.py` | 1,168 |
  | `extensions/ports/bridge/repl_bridge.py` | 1,082 |
  | `extensions/ports/bridge/bridge_main.py` | 986 |
  | `extensions/ports/transports/websocket_v1.py` | 982 |
  | `extensions/ports/bridge/session_runner.py` | 922 |
  | `extensions/im_gateway/server.py` | 614 |
  | `extensions/daemon/cli.py` | 495 |
  | `extensions/ports/transports/serial_uploader.py` | 492 |
  | `extensions/daemon/lifecycle.py` | 448 |
  | `extensions/daemon/workers/task_worker.py` | 396 |

- **典型依赖**：集中使用 `clawcodex_ext.bridge` 24 次（Layer 1 桥接实现被 Layer 2 复用），以及 `extensions.daemon` 10、`clawcodex_ext.services` 5、`clawcodex_ext.utils` 4、`extensions.ports` 2、`extensions.capabilities` 2、`clawcodex_ext.transports` 2、`clawcodex_ext.types` 1。
- **测试覆盖**：
  - 主测目录：`tests/extensions/daemon/`(聚合 ≈600 行)、`tests/server/`(1,142)、`tests/upstreamproxy/`(792)、`tests/services/`(1,356 中 im_gateway/swarm 部分 ≈678)
  - **合计**：约 14 个 .py 文件 / 3,212 行测试代码
  - 详见 [附录 D L2-⑤ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-⑥ 协议契约 + Prompt Lab

- **体量**：2 个子目录 / 27 个 .py 文件 / 2,514 行 / 81 KB
- **定位**：所有 Layer 2 Protocol/Adapter 定义 + A/B 实验框架
- **子目录**：
  - `capabilities/` — capabilities — Layer 2 ClawCodex-specific Protocol definitions（dashboard_entry / adapter_protocol / acp_protocol / headless_runner / task_protocol / recorder / agent_definition_protocol / team_memory_protocol / tool_authoring_protocol / skill_protocol / headless_protocol / tool_protocol / daemon_protocol / automation_state_protocol 等）。
  - `prompt_lab/` — F-119 A/B variant framework skeleton (P119-E)；子包含 `sinks/`（`ndjson.py` 等）。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/capabilities/dashboard_entry.py` | 221 |
  | `extensions/capabilities/adapter_protocol.py` | 198 |
  | `extensions/capabilities/acp_protocol.py` | 190 |
  | `extensions/capabilities/headless_runner.py` | 187 |
  | `extensions/capabilities/task_protocol.py` | 183 |
  | `extensions/capabilities/recorder.py` | 154 |
  | `extensions/capabilities/agent_definition_protocol.py` | 120 |
  | `extensions/capabilities/team_memory_protocol.py` | 119 |
  | `extensions/capabilities/tool_authoring_protocol.py` | 113 |
  | `extensions/capabilities/skill_protocol.py` | 102 |

- **典型依赖**：本特性是 Layer 2 的"边界守护者" — 仅被外部使用（`clawcodex_ext.capabilities` 与 `extensions.*` 各子包均通过它反向使用），自身只引用 `clawcodex_ext.tool_system` 1 次。
- **设计原则**：使用 `typing.Protocol` 结构子类型，禁止 ABC、不允许 `src.upstream` 反向依赖。
- **测试覆盖**：
  - 主测目录：`tests/extensions/capabilities/`(聚合 ≈1,000 行，测 dashboard_entry / recorder / sop_provider_protocol / skill_protocol / tool_authoring_protocol / agent_definition_protocol / acp_protocol 等)
  - Prompt Lab 测试：当前 `tests/` 下暂无独立目录覆盖 `extensions/prompt_lab/`；由 `tests/extensions/capabilities/` 间接覆盖
  - **合计**：约 6 个 .py 文件 / 1,000 行测试代码
  - 详见 [附录 D L2-⑥ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-⑦ 观测栈

- **体量**：4 个子目录 / 64 个 .py 文件 / 13,540 行 / 488 KB
- **定位**：跨系统 Dashboard、asciicast v2 录制、Session Visualizer、Context Provider 参考实现
- **子目录**：
  - `agent_dashboard/` — F-120 Agent Dashboard — cross-system read-only aggregator（`DashboardStore` + `GoalDashboardSource` + `TasksDashboardSource`）。
  - `recording/` — F-REC asciicast v2 recorder（writer / capture / registry / validator，含 `headless_source.py` / `repl_source.py` / `pty_recorder.py` / `cast_to_mp4_cli.py` / `examples/` / `tools/`）。
  - `visualizer/` — Local Session Visualizer（standalone web app，Gantt / timeline / performance analytics，FastAPI + WebSocket）。
  - `context_providers/` — Layer 2 reference context providers (P119-I)：`from_issue` / `from_ci` / `from_config`。
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/recording/cli.py` | 842 |
  | `extensions/recording/tools/cast_to_mp4.py` | 742 |
  | `extensions/recording/auto_demo.py` | 727 |
  | `extensions/visualizer/ws.py` | 663 |
  | `extensions/visualizer/server.py` | 567 |
  | `extensions/visualizer/parsers/transcript_parser.py` | 544 |
  | `extensions/recording/examples/repl_orchestrator_showcase.py` | 535 |
  | `extensions/visualizer/models/viz_models.py` | 449 |
  | `extensions/visualizer/import_router.py` | 420 |
  | `extensions/agent_dashboard/store.py` | 387 |

- **典型依赖**：观测栈横跨多特性 — `extensions.recording` 26、`extensions.capabilities` 22、`extensions.orchestrator` 12、`clawcodex_ext.tool_system` 9、`extensions.agent_dashboard` 6、`extensions.visualizer` 5、`extensions.api` 3、`clawcodex_ext.context_system` 3、`clawcodex_ext.cli` 2、`clawcodex_ext.command_system` 1。
- **测试覆盖**：
  - 主测目录：`tests/test_visualizer/`(3,161)、`tests/visualizer/`(170)、`tests/telemetry/`(3,866)、`tests/extensions/recording/`(聚合)、`tests/extensions/agent_dashboard/`(聚合)、`tests/extensions/context_providers/`(聚合)
  - **合计**：约 40 个 .py 文件 / 10,000 行测试代码
  - 详见 [附录 D L2-⑦ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-⑧ 三方 Agent/Skills/Tool System 扩展

- **体量**：7 个子目录 / 26 个 .py 文件 / 3,481 行 / 121 KB
- **定位**：第三方 Agent 注册与 team memory、Skills/Tool System 扩展层、LiteLLM shim
- **子目录**：
  - `agents/` — Third-party agent extension helpers（`discover_extension_agents` 入口）。
  - `agent/` — 二开 agent extensions（`session_persist`）。
  - `skills_ext/` — Skills Extension Layer（`bundled/dream.py` / `bundles.py` / `cache.py` / `hooks.py` / `paths.py` / `agent_config.py` / `registry_ext.py`）。
  - `tool_system_ext/` — Tool System Extension Layer（`bundles.py` / `registry_ext.py` / `agent_config.py` / `team_filter.py`）。
  - `providers_ext/` — Deprecated forwarding shim for the LiteLLM provider（迁移到 `clawcodex_ext.providers._litellm_adapter`）。
  - `permissions/` — (注：`extensions/permissions/`，**不是** `clawcodex_ext/permissions/`) 二开 permissions extensions（`settings_perms` + `settings_perms_structured_is_explicit`）。
  - `multimodel/` — (空目录，仅 `__pycache__/` 残留，待清理)
- **关键文件（行数 Top 10）**：

  | 文件 | 行数 |
  |---|---:|
  | `extensions/agents/team_memory.py` | 980 |
  | `extensions/agent/session_persist.py` | 352 |
  | `extensions/agents/team_memory_integration.py` | 222 |
  | `extensions/skills_ext/registry_ext.py` | 216 |
  | `extensions/skills_ext/bundled/dream.py` | 179 |
  | `extensions/tool_system_ext/registry_ext.py` | 171 |
  | `extensions/agents/team_memory_policy.py` | 147 |
  | `extensions/permissions/perms_reader.py` | 122 |
  | `extensions/skills_ext/hooks.py` | 120 |
  | `extensions/tool_system_ext/bundles.py` | 101 |

- **典型依赖**：作为第三方扩展适配层 — `clawcodex_ext.tool_system` 7、`clawcodex_ext.skills` 4、`clawcodex_ext.services` 3、`clawcodex_ext.providers` 2、`clawcodex_ext.memdir` 2，外加 `clawcodex_ext.goal` / `clawcodex_ext.command_system` / `clawcodex_ext.agent` 各 1。
- **测试覆盖**：
  - 主测目录：`tests/extensions/agents/`(聚合)、`tests/extensions/tool_system_ext/`(聚合)、`tests/extensions/skills_ext/`(聚合)、`tests/skills/`(8,306 中 skills_ext 部分 ≈4,153)、`tests/tool/`(5,410 中 tool_system_ext 部分)、`tests/tool_system/`(1,448 中 tool_system_ext 部分 ≈724)、`tests/clawcodex_ext/`(聚合 4,577 中 providers_ext/agent/services/tasks/tool_system/query/logical_kanban/native 部分)
  - **合计**：约 80 个 .py 文件 / 25,000 行测试代码（含 `tests/clawcodex_ext/` 聚合）
  - 详见 [附录 D L2-⑧ 测试映射](#附录-d测试用例代码行数统计)

---

### L2-⑨ Community Radar（待迁入）

- **体量**：从 `clawcodex_ext/community_radar/` 物理迁入，迁入后：1 个子目录 / 38 个 .py 文件 / 15,098 行 / 558 KB
- **定位**：SR-5.1 Community Feature Radar（discover / fetcher / classifier / extractor / scorer / dedup / pipeline / reporter / notifier / issue_sync / i18n / cron 集成）
- **子目录**：`community_radar/`（包括子目录 `templates/`、`tests/`）
- **关键依赖**：迁入后所有 `from clawcodex_ext.community_radar.*` 改为 `from extensions.community_radar.*`，其余外部引用点（`clawcodex_ext/cli/subcommand_registry.py:91` 等）同步修改。
- **测试覆盖**：与 L1-⑧ 共享同一份内嵌测试（`extensions/community_radar/tests/`，迁入后路径更新）。
- **迁移影响**：详见附录 B。

---

## 附录 A：合计统计

| 层 | 特性数 | 子目录数 | .py 文件数 | .py 总行数 | 总字节 |
|---|---:|---:|---:|---:|---:|
| Layer 1（不含 L1-⑧ 待迁出） | 7 | 50 | 1,008 | 227,514 | 8.40 MB |
| Layer 1 L1-⑧（待迁出） | 1 | 1 | 38 | 15,098 | 558 KB |
| **Layer 1 小计** | **8** | **51** | **1,046** | **242,612** | **8.96 MB** |
| Layer 2（不含 L2-⑨ 待迁入） | 8 | 24 | 503 | 130,425 | 4.89 MB |
| Layer 2 L2-⑨（待迁入） | 1 | 1 | 38 | 15,098 | 558 KB |
| **Layer 2 小计（含 L2-⑨）** | **9** | **25** | **541** | **145,523** | **5.45 MB** |
| **合计（含 L1-⑧ + L2-⑨ 同名项）** | **17** | **76** | **1,587** | **388,135** | **14.41 MB** |

注：L1-⑧ 与 L2-⑨ 是同一物理目录在不同层的两次计入；它们最终只保留一份，特性数 16、子目录数 75、文件 1,549、行 373,037、字节 13.85 MB。

---

## 附录 B：迁移影响

`clawcodex_ext/community_radar/` → `extensions/community_radar/`（Layer 1 → Layer 2）。

- **同步修改**：
  - `clawcodex_ext/__init__.py` 中对 `community_radar` 的引用
  - `clawcodex_ext/init.py` 中的引用
  - F-22 Cron 调度器（`extensions/orchestrator/cron_integration.py` 等）中 `from clawcodex_ext.community_radar import run_community_scan` 的导入
  - `community_radar/tests/` 子测试的运行路径（pytest 配置或 conftest）
  - 唯一已知的外部引用点：`clawcodex_ext/cli/subcommand_registry.py:91` 的 `from clawcodex_ext.community_radar.cli import register_community_radar_subcommand`
- **净变化**：特性数 +1（16 → 17，含 L1-⑧ 与 L2-⑨ 同名），但 L1-⑧ 在 Layer 1 删除、最终保留 16 个独立特性。
- **Layer 1 减轻**：558 KB / 15,098 行 / 38 文件
- **Layer 2 增加**：558 KB / 15,098 行 / 38 文件
- **总规模不变**

---

## 附录 C：异常 / 注意

- `clawcodex_ext/agent_mention/` 空目录（仅 `__pycache__/` 残留），疑似历史遗留 stub，建议清理或补 `__init__.py`。
- `extensions/multimodel/` 空目录（仅 `__pycache__/` 残留），待清理。
- `clawcodex_ext/daemon/` 仅含 `__init__.py` shim，是 Layer 1-② 的轻量适配层；真正 daemon 实现在 `extensions/daemon/`（L2-⑤）。
- `extensions/lkb/` 是独立 Python package（自带 `pyproject.toml` / `README.md` / 无顶层 `__init__.py`），可单独 `pip install lkb`，但仍位于 `extensions/` 之下作 monorepo 托管。
- `extensions/sop_converter/` 顶层约 30+ 文件是 star-import 转发 shim（`from extensions.sop_converter.<sub> import *`），实际实现位于 `core/`、`runtime/`、`adapters/` 等子包。
- `clawcodex_ext/community_radar/__init__.py` docstring 明确声明其为 SR-5.1 (Community Feature Radar)，本质是"独立子系统临时寄存在 Layer 1"，按 Layer 2 定位应迁出。
- `clawcodex_ext/services/` 体量远超其他子模块（257 个文件 / 1.98 MB），是 L1-① 偏重的主要原因之一。
- `clawcodex_ext/repl/` 的 `repl/core.py` 单文件 7,197 行，是 L1-③ 体量主因。
- `extensions/orchestrator/orchestrator.py` 单文件 4,729 行 + `cli/issue.py` 3,269 行 + `agent_runner.py` 3,033 行，是 L2-① 体量主因。
- `extensions/sop_converter/runtime/tool_registry_bridge.py` 单文件 3,557 行，是 L2-② 体量主因。
- `extensions/lkb/src/lkb/service.py` 单文件 2,081 行 + `solver_adapter.py` 1,925 行，是 L2-③ 体量主因。
- `extensions/permissions/`（L2-⑧）与 `clawcodex_ext/permissions/`（L1-④）**重名但语义不同**：前者是二开 settings 读取器，后者是权限引擎；迁移时务必确认 `import extensions.permissions` vs `import clawcodex_ext.permissions`。
- `extensions/providers_ext/` 是已弃用的 LiteLLM 转发 shim，新代码应直接 import `clawcodex_ext.providers._litellm_adapter`。
- `extensions/visualizer/` 的 F-167-D 改动已把 `asciicast_dashboard_source` 适配器从本目录迁到 `extensions/recording/visualizer_dashboard_source.py`，原文需要查阅 F-167-D 提交历史。

---

## 附录 D：测试用例代码行数统计

> **统计口径**：`.py` 行数 = `wc -l <file>`（按换行符计数）；字节数未单列；排除 `__pycache__/` 与 `.pyc`。
> **总规模**：`tests/` 下约 660+ 个 .py 文件 / 250K+ 行（其中 `tests/orchestrator/` 独占 34,202 行，约占总测试规模 13.6%）。
> **归属规则**：按"被测模块路径"匹配到 16 个特性分组；无法唯一归属的目录保留在"未分类/通用"。

### 附录 D.1 — 每特性测试规模汇总

| 特性 | 主测目录 | .py 文件 | 总行数 | 占测试总量 |
|---|---|---:|---:|---:|
| L1-① | agent + bridge + transports + services + query + provider + proactive + streaming + bash(部分) + tool_system(部分) + permissions(部分) + abort(部分) + sessions(部分) + message(部分) + test_agent_name.py | ~165 | ~31,229 | 12.4% |
| L1-② | cli + command_system + runtime + stability_gate(整段) + skills(部分) + conftest.py + 4 个 test_*.py | ~100 | ~24,448 | 9.7% |
| L1-③ | repl + frontend + tui + debug + diagnostics | ~68 | ~18,376 | 7.3% |
| L1-④ | permissions(部分) + auth + hooks + bootstrap + bash(部分) + git_fixtures | ~36 | ~6,383 | 2.5% |
| L1-⑤ | away_summary + dreaming + intent_forecast + session_intelligence + goal + memdir + context + multimodel + logical_kanban + coordinator + advisor | ~110 | ~27,649 | 11.0% |
| L1-⑥ | cron + tasks + feature_gate + compact + assistant + fast + voice + ide + model | ~50 | ~14,629 | 5.8% |
| L1-⑦ | config + cache + cost_tracker + file_ops + utils + state + messaging + image + input + system_prompt + sessions(部分) + snapshot + signal_tests + provider + release_smoke + ci + abort(部分) + message(部分) + token_tests + output + analytics | ~100 | ~14,759 | 5.9% |
| L1-⑧ | clawcodex_ext/community_radar/tests/（内嵌） | 4 | ~2,500 | 1.0% |
| **L1-① ~ ⑧ 小计** | — | ~633 | **~139,973** | **55.6%** |
| L2-① | orchestrator + upstream_sync + extensions/daemon + stability_gate(部分) | ~75 | ~34,300 | 13.6% |
| L2-② | sop_converter + misc(部分) | ~6 | ~402 | 0.2% |
| L2-③ | extensions/lkb/tests/（内嵌） + tests/logical_kanban/（共测） | ~30 | ~19,400 | 7.7% |
| L2-④ | api + remote + remote_api + trae | ~20 | ~4,945 | 2.0% |
| L2-⑤ | extensions/daemon + server + upstreamproxy + services(部分) | ~14 | ~3,212 | 1.3% |
| L2-⑥ | extensions/capabilities（聚合） | ~6 | ~1,000 | 0.4% |
| L2-⑦ | test_visualizer + visualizer + telemetry + extensions/recording + extensions/agent_dashboard + extensions/context_providers | ~40 | ~10,000 | 4.0% |
| L2-⑧ | extensions/agents + extensions/tool_system_ext + extensions/skills_ext + skills(部分) + tool + tool_system(部分) + clawcodex_ext(聚合) | ~80 | ~25,000 | 9.9% |
| L2-⑨ | 与 L1-⑧ 共用一份内嵌测试 | 4 | ~2,500 | 1.0% |
| **L2-① ~ ⑨ 小计** | — | ~275 | **~100,759** | **40.0%** |
| 未分类 / 通用 | misc + parity + integration + helpers + fixtures(纯) + data + effort + init | ~120 | ~34,000 | 13.5% |
| **总计（去重后）** | — | **~660** | **~251,700** | **100%** |

> 注：因部分 tests/ 子目录（如 `sessions` / `message` / `abort` / `permissions` / `bash` / `tool_system` / `services`）被多个特性共用，按 50% 拆账计入；汇总数字为估算，可能有 ±5% 误差。

### 附录 D.2 — tests/ 子目录全量映射

| tests/ 子目录 | .py 数 | 总行数 | 归属特性 | 主要被测模块 |
|---|---:|---:|---|---|
| `tests/abort/` | 9 | 2,326 | L1-① + L1-⑦ | `clawcodex_ext.utils.abort`、`src.utils.abort_controller` |
| `tests/advisor/` | 7 | 2,212 | L1-⑤ | `clawcodex_ext.advisor.*` |
| `tests/agent/` | 27 | 6,172 | L1-① | `clawcodex_ext.agent.agent_definitions / agent_tool_utils` |
| `tests/analytics/` | 2 | 118 | L1-⑦ | `clawcodex_ext.analytics.*` |
| `tests/api/` | 9 | 1,583 | L2-④ | `clawcodex_ext.services.api.*`、`extensions.api.query*` |
| `tests/assistant/` | 3 | 478 | L1-⑥ | `clawcodex_ext.assistant.*`（session chooser/history） |
| `tests/auth/` | 4 | 1,057 | L1-④ | `src.auth.*` |
| `tests/away_summary/` | 12 | 2,672 | L1-⑤ | `clawcodex_ext.away_summary.*` |
| `tests/bash/` | 10 | 1,448 | L1-① + L1-④ | `clawcodex_ext.tool_system.bash.*`（bash_tool + bash_security） |
| `tests/bootstrap/` | 2 | 535 | L1-④ | `clawcodex_ext.bootstrap.*` |
| `tests/bridge/` | 40 | 9,801 | L1-① | `clawcodex_ext.services.bridge.*`、`src.bridge.*` |
| `tests/cache/` | 3 | 576 | L1-⑦ | `clawcodex_ext.cache.*` |
| `tests/ci/` | 5 | 888 | L1-⑦ | `extensions.ci.*`、发布脚本 |
| `tests/clawcodex_ext/` (聚合) | 36 | 4,577 | L2-⑧ | `clawcodex_ext.providers / agent / services / tasks / tool_system / query / logical_kanban / native` |
| `tests/cli/` | 18 | 7,180 | L1-② | `clawcodex_ext.cli.*`、`clawcodex_ext.entrypoints.*` |
| `tests/command_system/` | 7 | 1,917 | L1-② | `clawcodex_ext.command_system.*` |
| `tests/compact/` | 10 | 2,136 | L1-⑥ | `clawcodex_ext.compact_service.*` |
| `tests/config/` | 7 | 1,296 | L1-⑦ | `clawcodex_ext.configuration.*`、`clawcodex_ext.settings` |
| `tests/context/` | 4 | 521 | L1-⑤ | `clawcodex_ext.context_system.*` |
| `tests/coordinator/` | 3 | 637 | L1-⑤ | `clawcodex_ext.coordinator.*` |
| `tests/cost_tracker/` | 4 | 528 | L1-⑦ | `clawcodex_ext.cost_tracker.*` |
| `tests/cron/` | — | ~4,618 | L1-⑥ | `clawcodex_ext.cron_system`、bridge dispatch |
| `tests/data/` (fixtures) | 0 | 0 | — | `petstore_swagger.json`、`test_openapi_spec.json`（纯 fixtures） |
| `tests/debug/` | 4 | 2,433 | L1-③ | `clawcodex_ext.debug.*`、`clawcodex_ext.repl.pty_*` |
| `tests/diagnostics/` | 7 | 970 | L1-③ | `clawcodex_ext.diagnostics.*` |
| `tests/dreaming/` | 9 | 2,030 | L1-⑤ | `clawcodex_ext.dreaming.*` |
| `tests/effort/` (fixtures only) | 0 | 0 | — | — |
| `tests/extensions/` (聚合) | 40 | 8,029 | L2-⑤ / L2-⑥ / L2-⑦ / L2-⑧ | 子目录分别归属 |
| `tests/extensions/agents/` | — | — | L2-⑧ | `extensions.agents.team_memory*` |
| `tests/extensions/agent_dashboard/` | — | — | L2-⑦ | `extensions.agent_dashboard.*` |
| `tests/extensions/capabilities/` | — | — | L2-⑥ | `extensions.capabilities.*` |
| `tests/extensions/daemon/` | — | — | L2-⑤ | `extensions.daemon.cli / config / constants` |
| `tests/extensions/recording/` | — | — | L2-⑦ | `extensions.capabilities.recorder`、`extensions.api.query` |
| `tests/extensions/tool_system_ext/` | — | — | L2-⑧ | `extensions.tool_system_ext.*` |
| `tests/provider/` | 8 | 1,876 | L1-⑦ | `clawcodex_ext.providers.model_registry / resolver / store` |
| `tests/fast/` | 3 | 256 | L1-⑥ | `clawcodex_ext.fast.*` |
| `tests/file_ops/` | 3 | 307 | L1-⑦ | `clawcodex_ext.file_ops.*` |
| `tests/fixtures/` (纯 fixtures) | 0 | 0 | — | JSON/YAML fixtures |
| `tests/frontend/` | 2 | 1,669 | L1-③ | `clawcodex_ext.frontend.*` |
| `tests/git_fixtures/` | 4 | 488 | L1-④ | `src.git_*` |
| `tests/goal/` | 12 | 2,980 | L1-⑤ | `clawcodex_ext.goal.*` |
| `tests/helpers/` | 2 | 78 | 共享 helper | 跨特性 |
| `tests/hooks/` | 11 | 1,869 | L1-④ | `src.hooks.*` |
| `tests/ide/` | 2 | 210 | L1-⑥ | `clawcodex_ext.ide.*` |
| `tests/image/` | 3 | 471 | L1-⑦ | `clawcodex_ext.image.*` |
| `tests/init/` (fixtures only) | 0 | 0 | — | — |
| `tests/input/` | 9 | 1,858 | L1-⑦ | `clawcodex_ext.input.*`（autocompleter / slash / mention / frontmatter） |
| `tests/integration/` | 23 | 5,570 | 未分类 / 通用 | 跨模块集成 smoke（phase_a/b/c、MCP、permission、compression、query、advisor、session） |
| `tests/intent_forecast/` | 12 | 1,652 | L1-⑤ | `clawcodex_ext.intent_forecast.*` |
| `tests/logical_kanban/` | 27 | 12,867 | L1-⑤ + L2-③ | `clawcodex_ext.logical_kanban`、`extensions.lkb` |
| `tests/mcp/` | 21 | 5,063 | L2-⑧ + L1-④ | `clawcodex_ext.services.mcp.*`（auth / discovery / provider / phase4 / polish） |
| `tests/memdir/` | 10 | 1,445 | L1-⑤ | `clawcodex_ext.memdir.*` |
| `tests/message/` | 7 | 1,166 | L1-⑦ + L1-① | `clawcodex_ext.messaging.*`、`test_pending_message_drain` |
| `tests/messaging/` | 2 | 279 | L1-⑦ | `clawcodex_ext.messaging.*` |
| `tests/misc/` | 80 | 22,618 | 未分类 / 通用 | SDK / Bridge generator / Bundle / Composite tools / SOP / context_providers / Treesitter / Transcript / Workflow CLI 等 |
| `tests/model/` | 2 | 271 | L1-⑥ | `clawcodex_ext.model.*` |
| `tests/multimodel/` | 6 | 572 | L1-⑤ | `extensions.multimodel.*` |
| `tests/orchestrator/` | 71 | 34,202 | L2-① | `extensions.orchestrator.*`、`extensions.daemon.*`、`extensions.services.im_gateway`、`extensions.services.swarm` |
| `tests/output/` | 3 | 207 | L1-⑦ | `clawcodex_ext.output.*` |
| `tests/parity/` | 19 | 5,758 | 未分类 / 通用 | 上下行 parity / e2e |
| `tests/permissions/` | 16 | 3,420 | L1-① + L1-④ | `clawcodex_ext.permissions.*`、`clawcodex_ext.goal.tools` |
| `tests/proactive/` | 7 | 293 | L1-⑥ | `clawcodex_ext.proactive.*` |
| `tests/provider/` | 18 | 3,985 | L1-① / L2-⑧ | `clawcodex_ext.providers.*`（anthropic / codex / openai_compat / litellm） |
| `tests/query/` | 9 | 3,158 | L1-① | `clawcodex_ext.query.*` |
| `tests/release_smoke/` | 2 | 260 | L1-⑦ | install artifacts |
| `tests/remote/` | 4 | 1,013 | L2-④ | `clawcodex_ext.remote.*`（sessions_websocket / sdk_adapter） |
| `tests/remote_api/` | 3 | 1,450 | L2-④ | `extensions.remote_api.*` |
| `tests/repl/` | 8 | 3,883 | L1-③ | `clawcodex_ext.repl.app`、`clawcodex_ext.command_system.registry` |
| `tests/runtime/` | 3 | 596 | L1-② | `clawcodex_ext.runtime.*` |
| `tests/server/` | 9 | 1,142 | L2-⑤ | `extensions.server.*`、`test_url_scheme / session_index` |
| `tests/session_intelligence/` | 1 | 61 | L1-⑤ | `clawcodex_ext.session_intelligence.*` |
| `tests/sessions/` | 9 | 1,209 | L1-⑦ + L1-① | `clawcodex_ext.sessions.*` |
| `tests/signal_tests/` | 2 | 165 | L1-⑦ | `clawcodex_ext.utils.signal` |
| `tests/skills/` | 33 | 8,306 | L1-② + L2-⑧ | `clawcodex_ext.skills.*`、`clawcodex_ext.agent.conversation` |
| `tests/snapshot/` | 2 | 274 | L1-⑦ | `clawcodex_ext.snapshot.*` |
| `tests/sop_converter/` | 4 | 402 | L2-② | `extensions.capabilities.sop_*` + `extensions.sop_converter.*` |
| `tests/stability_gate/` | 23 | 9,040 | L1-② + L2-① | Stage 1-10 全栈预演 |
| `tests/state/` | 4 | 656 | L1-⑦ | `clawcodex_ext.state.*` |
| `tests/streaming/` | 4 | 514 | L1-① | `clawcodex_ext.streaming.*` |
| `tests/system_prompt/` | 6 | 828 | L1-⑦ + L2-⑥ | `clawcodex_ext.system_prompt.*`（含 compression pipeline） |
| `tests/tasks/` | 11 | 3,000 | L1-⑥ | `clawcodex_ext.tasks.*`（dream / stop / local agent / shell / notification） |
| `tests/telemetry/` | 16 | 3,866 | L2-⑦ | `src.telemetry`、`extensions.observability.*` |
| `tests/test_visualizer/` | 8 | 3,161 | L2-⑦ | `extensions.visualizer.*` |
| `tests/token_tests/` | 5 | 743 | L1-⑦ | `clawcodex_ext.utils.token_estimation` |
| `tests/tool/` | — | 5,410 | L2-⑧ | `clawcodex_ext.tool.*`、`clawcodex_ext.tool_system.*`、`clawcodex_ext.input.*` |
| `tests/tool_system/` | 5 | 1,448 | L1-① + L2-⑧ | `clawcodex_ext.tool_system.*`（goal/monitor/send_message/task_stop） |
| `tests/trae/` | 4 | 899 | L2-④ | `extensions.trae.*`、`extensions.capabilities.acp_protocol` |
| `tests/transports/` | 4 | 491 | L1-① | `clawcodex_ext.transports.*` |
| `tests/tui/` | 47 | 9,421 | L1-③ | `clawcodex_ext.tui.*`、`clawcodex_ext.goal.*` |
| `tests/upstream_sync/` | 2 | 90 | L2-① | `extensions.upstream_sync.*` |
| `tests/upstreamproxy/` | 6 | 792 | L2-⑤ | `extensions.upstreamproxy.*` |
| `tests/utils/` | 7 | 813 | L1-⑦ | `clawcodex_ext.utils.*`、`src.types.messages`、`src.utils.abort_controller` |
| `tests/visualizer/` | 1 | 170 | L2-⑦ | `extensions.agent_dashboard.*` |
| `tests/voice/` | 4 | 2,493 | L1-⑥ | `clawcodex_ext.voice.*` |
| **顶层文件** | — | — | — | — |
| `tests/conftest.py` | 1 | 146 | L1-②（全局 fixture） | 全局 pytest fixtures / hooks |
| `tests/test_agent_name.py` | 1 | 453 | L1-① | F89：agent 命名 / 注册表 |
| `tests/test_llm.py` | 1 | 186 | L1-② | Provider/LLM 公共契约 |
| `tests/test_mcp_ext.py` | 1 | 281 | L1-② | extensions.mcp 边界 |
| `tests/test_session_chain.py` | 1 | 496 | L1-② | F103：session 链路 |

### 附录 D.3 — 内嵌测试（非 `tests/` 下）

| 路径 | .py 数 | 总行数 | 归属特性 |
|---|---:|---:|---|
| `clawcodex_ext/community_radar/tests/` | 4 | ~2,500 | L1-⑧ / L2-⑨（待迁出后路径更新） |
| `extensions/lkb/tests/` | — | ~6,500 | L2-③（外加 `tests/logical_kanban/` 12,867 共测） |
| `extensions/recording/examples/` | 1 | 535 | L2-⑦（repl_orchestrator_showcase.py） |

### 附录 D.4 — 测试覆盖偏弱预警

- **L2-② SOP 编译器**：当前 `tests/sop_converter/` 仅 4 个 .py / 402 行，与 30,316 行实现代码覆盖率不足；建议扩展 `test_tool_registry_bridge.py` / `test_skill_grouper.py` / `test_type_schema.py` 等。
- **L2-⑥ 协议契约 + Prompt Lab**：当前 `tests/extensions/capabilities/` 为聚合目录，单文件覆盖率不明；`extensions/prompt_lab/` 暂无独立测试目录。
- **L1-⑧ / L2-⑨ Community Radar**：测试内嵌在子模块 `community_radar/tests/` 下，未在 `tests/` 顶层目录暴露，CI 通过子包 pytest 触发；迁出到 Layer 2 后建议同步提升 `tests/` 顶层暴露度。

### 附录 D.5 — 测试规模对比（实现代码 vs 测试代码）

| 维度 | 实现代码 | 测试代码 | 测试 / 实现比 |
|---|---:|---:|---:|
| Layer 1（不含 L1-⑧） | 227,514 行 | ~137,473 行 | **0.60** |
| Layer 1 L1-⑧ | 15,098 行 | ~2,500 行 | 0.17（偏低） |
| Layer 2（不含 L2-⑨） | 130,425 行 | ~98,259 行 | **0.75** |
| Layer 2 L2-⑨ | 15,098 行 | ~2,500 行 | 0.17（偏低） |
| **合计** | **373,037 行** | **~251,700 行** | **0.67** |

> 平均每 100 行实现有 67 行测试覆盖。L1-⑧ / L2-⑨ 测试覆盖率显著偏低（17%），是后续补强重点。
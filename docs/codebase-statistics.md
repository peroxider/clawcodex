# ClawCodex 下游扩展代码统计报告

**生成日期**: 2026-07-24
**覆盖范围**: `clawcodex_ext/` (Layer 1) + `extensions/` (Layer 2) + `scripts/ci/`
**总代码行数**: 524,315

## 一、汇总总览

| # | 特性 | 源文件数 | 源码行数 | 测试行数 | 合计行数 | 测试占比 |
|---|------|--------:|--------:|--------:|--------:|--------:|
|  1 | Agent 运行时 | 28 | 7,485 | 6,942 | 14,427 | 48.1% |
|  2 | Agent 定义与管理 | 15 | 2,150 | 478 | 2,628 | 18.2% |
|  3 | 工具编写 SDK | 11 | 1,868 | 0 | 1,868 | 0.0% |
|  4 | CLI 与命令系统 | 77 | 20,237 | 13,084 | 33,321 | 39.3% |
|  5 | LLM 提供者 | 32 | 7,493 | 6,232 | 13,725 | 45.4% |
|  6 | 多会话桥接 | 30 | 6,388 | 11,584 | 17,972 | 64.5% |
|  7 | 工具实现层 | 78 | 22,507 | 12,426 | 34,933 | 35.6% |
|  8 | 技能系统 | 31 | 11,797 | 9,160 | 20,957 | 43.7% |
|  9 | 安全·认证·钩子 | 49 | 12,944 | 6,346 | 19,290 | 32.9% |
| 10 | 上下文系统 | 16 | 5,019 | 1,349 | 6,368 | 21.2% |
| 11 | 查询引擎 | 12 | 6,754 | 4,083 | 10,837 | 37.7% |
| 12 | 设置 | 5 | 1,028 | 1,296 | 2,324 | 55.8% |
| 13 | MCP 服务 | 32 | 8,003 | 5,063 | 13,066 | 38.7% |
| 14 | 频道与 IM 集成 | 44 | 10,659 | 11,195 | 21,854 | 51.2% |
| 15 | 基础设施服务 | 205 | 40,462 | 131,777 | 172,239 | 76.5% |
| 16 | 编排器 | 101 | 43,736 | 34,203 | 77,939 | 43.9% |
| 17 | 守护进程与后台 | 19 | 2,957 | 2,000 | 4,957 | 40.3% |
| 18 | 层间契约 | 23 | 2,428 | 177 | 2,605 | 6.8% |
| 19 | 逻辑知识库 (LKB) | 58 | 20,113 | 19,367 | 39,480 | 49.1% |
| 20 | 仪表盘与团队可视性 | 20 | 4,041 | 5,080 | 9,121 | 55.7% |
| 21 | scripts/ci | 10 | 3,516 | 888 | 4,404 | 20.2% |
| | **总计** | | **241,585** | **282,730** | **524,315** | **53.9%** |

### 按合计行数排序

| # | 特性 | 源码 | 测试 | 合计 |
|---|------|-----:|-----:|-----:|
| 15 | 基础设施服务 | 40,462 | 131,777 | 172,239 |
| 16 | 编排器 | 43,736 | 34,203 | 77,939 |
| 19 | 逻辑知识库 (LKB) | 20,113 | 19,367 | 39,480 |
|  7 | 工具实现层 | 22,507 | 12,426 | 34,933 |
|  4 | CLI 与命令系统 | 20,237 | 13,084 | 33,321 |
| 14 | 频道与 IM 集成 | 10,659 | 11,195 | 21,854 |
|  8 | 技能系统 | 11,797 | 9,160 | 20,957 |
|  9 | 安全·认证·钩子 | 12,944 | 6,346 | 19,290 |
|  6 | 多会话桥接 | 6,388 | 11,584 | 17,972 |
|  1 | Agent 运行时 | 7,485 | 6,942 | 14,427 |
|  5 | LLM 提供者 | 7,493 | 6,232 | 13,725 |
| 13 | MCP 服务 | 8,003 | 5,063 | 13,066 |
| 11 | 查询引擎 | 6,754 | 4,083 | 10,837 |
| 20 | 仪表盘与团队可视性 | 4,041 | 5,080 | 9,121 |
| 10 | 上下文系统 | 5,019 | 1,349 | 6,368 |
| 17 | 守护进程与后台 | 2,957 | 2,000 | 4,957 |
| 21 | scripts/ci | 3,516 | 888 | 4,404 |
|  2 | Agent 定义与管理 | 2,150 | 478 | 2,628 |
| 18 | 层间契约 | 2,428 | 177 | 2,605 |
| 12 | 设置 | 1,028 | 1,296 | 2,324 |
|  3 | 工具编写 SDK | 1,868 | 0 | 1,868 |

---
# 二、各特性逐文件清单

## #1 Agent 运行时

**总源码 7,485 行** | **总测试 6,942 行** | **合计 14,427 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   152 | `ext/agent/_outlines_adapter.py` |
|   580 | `ext/agent/agent_tool_utils.py` |
|   158 | `ext/agent/auto_mode_runner.py` |
|   448 | `ext/agent/background_runner.py` |
|    73 | `ext/agent/background_state.py` |
|   544 | `ext/agent/chain_filter.py` |
|   122 | `ext/agent/conversation.py` |
|   221 | `ext/agent/foreground_promotion.py` |
|   294 | `ext/agent/fork_subagent.py` |
|   219 | `ext/agent/forked_agent.py` |
|   241 | `ext/agent/prompt.py` |
|   205 | `ext/agent/read_file_seed.py` |
|   319 | `ext/agent/report_store.py` |
|   252 | `ext/agent/resume_agent.py` |
|   305 | `ext/agent/resume_checks.py` |
|   153 | `ext/agent/routing.py` |
|   461 | `ext/agent/run_agent.py` |
|    79 | `ext/agent/sdk_context_registry.py` |
|    90 | `ext/agent/sdk_instance_registry.py` |
|   503 | `ext/agent/session.py` |
|    72 | `ext/agent/session_ext.py` |
|   241 | `ext/agent/side_question.py` |
|   266 | `ext/agent/sidechain_transcript.py` |
|   290 | `ext/agent/subagent_context.py` |
|   720 | `ext/agent/transcript.py` |
|   117 | `ext/agent/verification.py` |
|     8 | `extensions/agent/__init__.py` |
|   352 | `extensions/agent/session_persist.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/agent/__init__.py` |
|   176 | `tests/agent/test_agent_bubble_propagation.py` |
|   481 | `tests/agent/test_agent_loop.py` |
|   411 | `tests/agent/test_agent_loop_compat.py` |
|   108 | `tests/agent/test_agent_loop_image_size_propagation.py` |
|   258 | `tests/agent/test_agent_permission_inheritance.py` |
|   312 | `tests/agent/test_agent_provider_model_override.py` |
|   143 | `tests/agent/test_agent_smoke_no_live_key.py` |
|   108 | `tests/agent/test_agent_tool_async.py` |
|   102 | `tests/agent/test_agent_tool_coordinator_registry.py` |
|   515 | `tests/agent/test_agent_tool_fork.py` |
|   544 | `tests/agent/test_agent_toolkit_filtering.py` |
|   309 | `tests/agent/test_f88_integration.py` |
|   253 | `tests/agent/test_fork_subagent.py` |
|   277 | `tests/agent/test_load_agents_dir.py` |
|    97 | `tests/agent/test_load_plugin_agents.py` |
|   120 | `tests/agent/test_no_top_level_decoys.py` |
|   150 | `tests/agent/test_parse_agent_markdown.py` |
|   102 | `tests/agent/test_repl_available_agents.py` |
|   283 | `tests/agent/test_report_store.py` |
|   303 | `tests/agent/test_resume_agent.py` |
|   204 | `tests/agent/test_routing.py` |
|   165 | `tests/agent/test_subagent_abort_isolation.py` |
|   339 | `tests/agent/test_subagent_context.py` |
|   146 | `tests/agent/test_subagent_progress_line.py` |
|   192 | `tests/agent/test_sync_agent_runtime_tasks_registration.py` |
|    74 | `tests/agent/test_verification_agent.py` |
|   233 | `tests/clawcodex_ext/agent/tool_authoring/test_bash_timeout.py` |
|    14 | `tests/clawcodex_ext/agent/tool_authoring/test_parse_wrapper_stdout.py` |
|     3 | `tests/clawcodex_ext/agent_tests/__init__.py` |
|    34 | `tests/clawcodex_ext/agent_tests/conftest.py` |
|    59 | `tests/clawcodex_ext/agent_tests/test_agent_policy.py` |
|   184 | `tests/clawcodex_ext/agent_tests/test_agent_registry.py` |
|   167 | `tests/clawcodex_ext/agent_tests/test_load_order.py` |
|    76 | `tests/clawcodex_ext/agent_tests/test_markdown_discovery.py` |

### 源码文件大小分布

- 文件数: 28
- 最小: 8 行
- 最大: 720 行
- 平均: 267 行
- 中位数: 241 行
- 最大 3 文件: `ext/agent/transcript.py` (720行), `ext/agent/agent_tool_utils.py` (580行), `ext/agent/chain_filter.py` (544行)

## #2 Agent 定义与管理

**总源码 2,150 行** | **总测试 478 行** | **合计 2,628 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    14 | `ext/agent/_bundled_agents/__init__.py` |
|    43 | `ext/agent/_bundled_agents/code_reviewer.py` |
|    34 | `ext/agent/_bundled_agents/docs_writer.py` |
|    37 | `ext/agent/_bundled_agents/test_runner.py` |
|   371 | `ext/agent/agent_definitions.py` |
|   137 | `ext/agent/constants.py` |
|    50 | `ext/agent/filter_agents_by_mcp.py` |
|   260 | `ext/agent/load_agents_dir.py` |
|   116 | `ext/agent/load_plugin_agents.py` |
|   120 | `ext/agent/markdown_discovery.py` |
|   243 | `ext/agent/parse_agent_markdown.py` |
|   223 | `ext/agent/policy.py` |
|   237 | `ext/agent/registry.py` |
|    43 | `ext/assistant/session_chooser.py` |
|   222 | `ext/assistant/session_history.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/assistant/__init__.py` |
|    41 | `tests/assistant/test_session_chooser.py` |
|   437 | `tests/assistant/test_session_history.py` |

### 源码文件大小分布

- 文件数: 15
- 最小: 14 行
- 最大: 371 行
- 平均: 143 行
- 中位数: 120 行
- 最大 3 文件: `ext/agent/agent_definitions.py` (371行), `ext/agent/load_agents_dir.py` (260行), `ext/agent/parse_agent_markdown.py` (243行)

## #3 工具编写 SDK

**总源码 1,868 行** | **总测试 0 行** | **合计 1,868 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    70 | `ext/agent/tool_authoring/__init__.py` |
|    35 | `ext/agent/tool_authoring/call_handlers/__init__.py` |
|   402 | `ext/agent/tool_authoring/call_handlers/bash.py` |
|    68 | `ext/agent/tool_authoring/call_handlers/http.py` |
|    38 | `ext/agent/tool_authoring/call_handlers/python.py` |
|   451 | `ext/agent/tool_authoring/call_handlers/sdk_wrapper.py` |
|   380 | `ext/agent/tool_authoring/factory.py` |
|   138 | `ext/agent/tool_authoring/persistence.py` |
|    37 | `ext/agent/tool_authoring/registry_ext.py` |
|    79 | `ext/agent/tool_authoring/spec.py` |
|   170 | `ext/agent/tool_authoring/validators.py` |

### 源码文件大小分布

- 文件数: 11
- 最小: 35 行
- 最大: 451 行
- 平均: 169 行
- 中位数: 79 行
- 最大 3 文件: `ext/agent/tool_authoring/call_handlers/sdk_wrapper.py` (451行), `ext/agent/tool_authoring/call_handlers/bash.py` (402行), `ext/agent/tool_authoring/factory.py` (380行)

## #4 CLI 与命令系统

**总源码 20,237 行** | **总测试 13,084 行** | **合计 33,321 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|     1 | `ext/cli/__init__.py` |
|   350 | `ext/cli/_interactive.py` |
|    53 | `ext/cli/auth_cmd.py` |
|     1 | `ext/cli/channels_cmd/__init__.py` |
| 1,347 | `ext/cli/channels_cmd/commands.py` |
|   261 | `ext/cli/diag_cmd.py` |
| 1,144 | `ext/cli/dispatch.py` |
|     1 | `ext/cli/gateway_cmd/__init__.py` |
|   147 | `ext/cli/gateway_cmd/commands.py` |
|     1 | `ext/cli/lkb_method_cmd/__init__.py` |
|   752 | `ext/cli/lkb_method_cmd/commands.py` |
|    26 | `ext/cli/main.py` |
|     1 | `ext/cli/model_cmd/__init__.py` |
|   281 | `ext/cli/model_cmd/commands.py` |
|    30 | `ext/cli/model_cmd/errors.py` |
|   234 | `ext/cli/model_cmd/registry.py` |
|   129 | `ext/cli/model_cmd/resolver.py` |
|    78 | `ext/cli/model_cmd/store.py` |
|   363 | `ext/cli/parser.py` |
|    88 | `ext/cli/permissions.py` |
|     1 | `ext/cli/provider_cmd/__init__.py` |
|   150 | `ext/cli/provider_cmd/commands.py` |
|    22 | `ext/cli/provider_cmd/errors.py` |
|   439 | `ext/cli/runners.py` |
|   517 | `ext/cli/runtime_commands.py` |
|    47 | `ext/cli/session_migrate_cmd.py` |
|     1 | `ext/cli/sop_cmd/__init__.py` |
| 1,274 | `ext/cli/sop_cmd/commands.py` |
|    96 | `ext/cli/stats_cmd.py` |
|   131 | `ext/cli/subcommand_registry.py` |
|    12 | `ext/cli/telemetry_cmd.py` |
|    44 | `ext/cli/tool_cmd/__init__.py` |
|   317 | `ext/cli/tool_cmd/command.py` |
|   190 | `ext/cli/tool_cmd/core_filter.py` |
|   132 | `ext/cli/tool_cmd/discovery.py` |
|   104 | `ext/cli/tool_cmd/hooks.py` |
|   167 | `ext/cli/tool_cmd/runtime.py` |
|   274 | `ext/cli/tool_cmd/schema_parser.py` |
|    45 | `ext/cli/worktree.py` |
|     0 | `ext/cli_core/__init__.py` |
|    28 | `ext/cli_core/exit.py` |
|    37 | `ext/cli_core/ndjson.py` |
|   203 | `ext/cli_core/structured_io.py` |
|   219 | `ext/command_system/__init__.py` |
|   243 | `ext/command_system/aggregator.py` |
|   120 | `ext/command_system/argument_substitution.py` |
|   300 | `ext/command_system/bg_commands.py` |
|   215 | `ext/command_system/btw_command.py` |
|   279 | `ext/command_system/btw_stats.py` |
|   164 | `ext/command_system/buddy_command.py` |
| 2,030 | `ext/command_system/builtins.py` |
|   352 | `ext/command_system/dashboard_command.py` |
|   433 | `ext/command_system/dialogue_command.py` |
|   242 | `ext/command_system/effort_command.py` |
|   417 | `ext/command_system/engine.py` |
|   264 | `ext/command_system/export_command.py` |
| 1,054 | `ext/command_system/input_processing.py` |
|   292 | `ext/command_system/lkb_command.py` |
|   421 | `ext/command_system/lodestone_commands.py` |
|   208 | `ext/command_system/model_command.py` |
|   133 | `ext/command_system/monitor_command.py` |
|    91 | `ext/command_system/moved_to_plugin.py` |
|    53 | `ext/command_system/output_style_command.py` |
|   138 | `ext/command_system/proactive_command.py` |
|   263 | `ext/command_system/registry.py` |
|    90 | `ext/command_system/safe_commands.py` |
|   251 | `ext/command_system/security_review.py` |
|   123 | `ext/command_system/shell_prompt.py` |
|   210 | `ext/command_system/skills_integration.py` |
|    57 | `ext/command_system/statusline.py` |
|   329 | `ext/command_system/team_memory_commands.py` |
|   321 | `ext/command_system/template_commands.py` |
|   124 | `ext/command_system/theme_command.py` |
|   265 | `ext/command_system/tts_command.py` |
|   522 | `ext/command_system/types.py` |
|   299 | `ext/command_system/ultraplan_command.py` |
|   196 | `ext/command_system/voice_command.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/cli/__init__.py` |
|   338 | `tests/cli/test_claude_md.py` |
|   184 | `tests/cli/test_cli_core.py` |
|   197 | `tests/cli/test_cli_subcommands.py` |
|   243 | `tests/cli/test_cli_tui_smoke.py` |
|    70 | `tests/cli/test_deep_link.py` |
|   189 | `tests/cli/test_downstream_cli_argcomplete.py` |
|   546 | `tests/cli/test_downstream_cli_dispatch.py` |
|    57 | `tests/cli/test_downstream_cli_entrypoint.py` |
|   651 | `tests/cli/test_f53_tool_to_cli.py` |
| 1,492 | `tests/cli/test_headless_cli.py` |
|   810 | `tests/cli/test_headless_resume.py` |
|   543 | `tests/cli/test_headless_resume_phase3.py` |
|   415 | `tests/cli/test_headless_sigint.py` |
|   276 | `tests/cli/test_init.py` |
|   246 | `tests/cli/test_init_prefetch_consumption.py` |
|   182 | `tests/cli/test_interactive.py` |
|   741 | `tests/cli/test_mcp_cli.py` |
|     0 | `tests/command_system/__init__.py` |
|     1 | `tests/command_system/dashboard/__init__.py` |
|   252 | `tests/command_system/dashboard/test_dashboard_command.py` |
|   336 | `tests/command_system/test_builtin_commands.py` |
|   906 | `tests/command_system/test_command_system.py` |
|   422 | `tests/command_system/test_goal_command.py` |
|   105 | `tests/command_system/test_monitor_command.py` |
|    57 | `tests/command_system/test_template_commands.py` |
|    91 | `tests/command_system/test_ultraplan_command.py` |
|     0 | `tests/frontend/__init__.py` |
| 1,669 | `tests/frontend/test_repl_gateway.py` |
|     0 | `tests/input/__init__.py` |
|   501 | `tests/input/test_at_file_completer.py` |
|   316 | `tests/input/test_at_mention_binary_files.py` |
|   338 | `tests/input/test_at_mention_images.py` |
|    79 | `tests/input/test_format.py` |
|   106 | `tests/input/test_frontmatter_adapter.py` |
|   262 | `tests/input/test_input_processing.py` |
|   172 | `tests/input/test_multiline_input.py` |
|    84 | `tests/input/test_slash_completer.py` |
|     0 | `tests/output/__init__.py` |
|    64 | `tests/output/test_output_styles.py` |
|   143 | `tests/output/test_output_styles_frontmatter.py` |

### 源码文件大小分布

- 文件数: 77
- 最小: 0 行
- 最大: 2,030 行
- 平均: 262 行
- 中位数: 190 行
- 最大 3 文件: `ext/command_system/builtins.py` (2030行), `ext/cli/channels_cmd/commands.py` (1347行), `ext/cli/sop_cmd/commands.py` (1274行)

## #5 LLM 提供者

**总源码 7,493 行** | **总测试 6,232 行** | **合计 13,725 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   306 | `ext/providers/__init__.py` |
|   393 | `ext/providers/_litellm_adapter.py` |
|   226 | `ext/providers/_moonshot_schema.py` |
|   262 | `ext/providers/_stream_abort.py` |
|   162 | `ext/providers/_stream_drain.py` |
|   938 | `ext/providers/anthropic_provider.py` |
|   266 | `ext/providers/base.py` |
|   102 | `ext/providers/codex_models.py` |
|   158 | `ext/providers/factory.py` |
|    35 | `ext/providers/hooks.py` |
|   101 | `ext/providers/kimi_coding_provider.py` |
|   182 | `ext/providers/kimi_provider.py` |
|    45 | `ext/providers/media/__init__.py` |
|   274 | `ext/providers/media/base.py` |
|     1 | `ext/providers/media/image/__init__.py` |
|   138 | `ext/providers/media/image/agnes.py` |
|   169 | `ext/providers/media/registry.py` |
|     1 | `ext/providers/media/video/__init__.py` |
|   215 | `ext/providers/media/video/agnes.py` |
|   438 | `ext/providers/minimax_provider.py` |
|   325 | `ext/providers/model_catalog_cache.py` |
|   184 | `ext/providers/native/__init__.py` |
|    93 | `ext/providers/native/base.py` |
|    92 | `ext/providers/native/capabilities.py` |
|   184 | `ext/providers/native/gemini_adapter.py` |
|   219 | `ext/providers/native/grok_adapter.py` |
|   273 | `ext/providers/native/openai_adapter.py` |
|   469 | `ext/providers/openai_codex_provider.py` |
| 1,093 | `ext/providers/openai_compatible.py` |
|     9 | `ext/providers/openai_responses.py` |
|    53 | `ext/providers/patches.py` |
|    87 | `ext/providers/runtime.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     1 | `tests/clawcodex_ext/native/__init__.py` |
|    68 | `tests/clawcodex_ext/native/test_audio.py` |
|   110 | `tests/clawcodex_ext/native/test_image.py` |
|    64 | `tests/clawcodex_ext/native/test_modifiers.py` |
|   139 | `tests/clawcodex_ext/native/test_registry.py` |
|    81 | `tests/clawcodex_ext/native/test_url_handler.py` |
|   210 | `tests/clawcodex_ext/providers/test_f99_provider_registration.py` |
|   134 | `tests/clawcodex_ext/providers/test_kimi_coding_provider.py` |
|   209 | `tests/clawcodex_ext/providers/test_kimi_provider.py` |
|   209 | `tests/clawcodex_ext/providers/test_stream_drain.py` |
|     0 | `tests/model/__init__.py` |
|   271 | `tests/model/test_model_system.py` |
|     0 | `tests/provider/__init__.py` |
|     0 | `tests/provider/native/__init__.py` |
|   122 | `tests/provider/native/test_base.py` |
|    72 | `tests/provider/native/test_capabilities.py` |
|   139 | `tests/provider/native/test_factory.py` |
|   136 | `tests/provider/native/test_gemini_adapter.py` |
|   119 | `tests/provider/native/test_grok_adapter.py` |
|   163 | `tests/provider/native/test_openai_adapter.py` |
|   143 | `tests/provider/test_base_provider_image_validation.py` |
|    99 | `tests/provider/test_codex_model_discovery.py` |
|   148 | `tests/provider/test_codex_provider_runtime.py` |
|   155 | `tests/provider/test_f99_anthropic_read_timeout.py` |
|   368 | `tests/provider/test_litellm_adapter.py` |
|   310 | `tests/provider/test_model_catalog_cache.py` |
|    36 | `tests/provider/test_model_catalog_discovery.py` |
|   415 | `tests/provider/test_openai_codex_provider.py` |
|   432 | `tests/provider/test_openai_compat_abort_signal.py` |
|   308 | `tests/provider/test_openai_compat_document_translation.py` |
|   319 | `tests/provider/test_openai_compat_image_translation.py` |
|   101 | `tests/provider/test_outlines_adapter.py` |
|   237 | `tests/provider/test_provider_abort_signal.py` |
|    78 | `tests/provider/test_provider_config.py` |
|   205 | `tests/provider/test_provider_factory.py` |
|   538 | `tests/provider/test_providers.py` |
|    93 | `tests/provider/test_pydantic_adapter.py` |

### 源码文件大小分布

- 文件数: 32
- 最小: 1 行
- 最大: 1,093 行
- 平均: 234 行
- 中位数: 184 行
- 最大 3 文件: `ext/providers/openai_compatible.py` (1093行), `ext/providers/anthropic_provider.py` (938行), `ext/providers/openai_codex_provider.py` (469行)

## #6 多会话桥接

**总源码 6,388 行** | **总测试 11,584 行** | **合计 17,972 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    10 | `ext/bridge/__init__.py` |
|    81 | `ext/bridge/bounded_uuid_set.py` |
|   692 | `ext/bridge/bridge_api.py` |
|    86 | `ext/bridge/bridge_config.py` |
|   107 | `ext/bridge/bridge_enabled.py` |
|   105 | `ext/bridge/bridge_permission_callbacks.py` |
|   281 | `ext/bridge/bridge_pointer.py` |
|   442 | `ext/bridge/bridge_status_util.py` |
|   123 | `ext/bridge/capacity_wake.py` |
|    58 | `ext/bridge/close_codes.py` |
|   268 | `ext/bridge/code_session_api.py` |
|   185 | `ext/bridge/debug_utils.py` |
|   146 | `ext/bridge/env_less_bridge_config.py` |
|    68 | `ext/bridge/exceptions.py` |
|    98 | `ext/bridge/flush_gate.py` |
|   271 | `ext/bridge/inbound_attachments.py` |
|   143 | `ext/bridge/inbound_messages.py` |
|   395 | `ext/bridge/init_repl_bridge.py` |
|   350 | `ext/bridge/jwt_utils.py` |
|   396 | `ext/bridge/messaging.py` |
|   259 | `ext/bridge/messaging_handlers.py` |
|    56 | `ext/bridge/no_proxy.py` |
|   189 | `ext/bridge/poll_config.py` |
|   101 | `ext/bridge/poll_config_defaults.py` |
|   106 | `ext/bridge/repl_bridge_handle.py` |
|   400 | `ext/bridge/repl_bridge_transport.py` |
|    87 | `ext/bridge/session_id_compat.py` |
|   475 | `ext/bridge/types.py` |
|   156 | `ext/bridge/work_secret.py` |
|   254 | `ext/bridge/worktree.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/bridge/__init__.py` |
|    24 | `tests/bridge/conftest.py` |
|   236 | `tests/bridge/test_async_cancel_canary.py` |
|   111 | `tests/bridge/test_bounded_uuid_set.py` |
|   127 | `tests/bridge/test_bridge.py` |
|   898 | `tests/bridge/test_bridge_api.py` |
|    80 | `tests/bridge/test_bridge_config.py` |
|    55 | `tests/bridge/test_bridge_enabled.py` |
|   987 | `tests/bridge/test_bridge_main.py` |
|    66 | `tests/bridge/test_bridge_permission_callbacks.py` |
|   397 | `tests/bridge/test_bridge_status_util.py` |
|   199 | `tests/bridge/test_capacity_wake.py` |
|    26 | `tests/bridge/test_close_codes.py` |
|   308 | `tests/bridge/test_code_session_api.py` |
|   130 | `tests/bridge/test_debug_utils.py` |
|   150 | `tests/bridge/test_env_less_bridge_config.py` |
|    81 | `tests/bridge/test_flush_gate.py` |
|   280 | `tests/bridge/test_inbound_attachments.py` |
|   166 | `tests/bridge/test_inbound_messages.py` |
|   423 | `tests/bridge/test_init_repl_bridge.py` |
|    62 | `tests/bridge/test_jwt_utils.py` |
|   268 | `tests/bridge/test_messaging_handlers.py` |
|   425 | `tests/bridge/test_messaging_router.py` |
|    62 | `tests/bridge/test_no_proxy.py` |
|    33 | `tests/bridge/test_phase0_deps.py` |
|    33 | `tests/bridge/test_phase0_packages.py` |
|   150 | `tests/bridge/test_poll_config.py` |
|    87 | `tests/bridge/test_poll_config_defaults.py` |
|    93 | `tests/bridge/test_protojson.py` |
| 1,258 | `tests/bridge/test_remote_bridge_core.py` |
|   789 | `tests/bridge/test_repl_bridge.py` |
|    91 | `tests/bridge/test_repl_bridge_handle.py` |
|   219 | `tests/bridge/test_repl_bridge_transport.py` |
|   131 | `tests/bridge/test_sdk_types.py` |
|   115 | `tests/bridge/test_session_id_compat.py` |
|   679 | `tests/bridge/test_session_runner.py` |
|   155 | `tests/bridge/test_token_refresh_scheduler.py` |
|    50 | `tests/bridge/test_trusted_device.py` |
|   189 | `tests/bridge/test_types.py` |
|   168 | `tests/bridge/test_work_secret.py` |
|     0 | `tests/messaging/__init__.py` |
|   279 | `tests/messaging/test_semantics.py` |
|     0 | `tests/remote/__init__.py` |
|   330 | `tests/remote/test_remote_session_manager.py` |
|    90 | `tests/remote/test_sdk_message_adapter.py` |
|   593 | `tests/remote/test_sessions_websocket.py` |
|     0 | `tests/transports/__init__.py` |
|   190 | `tests/transports/test_ccr_client.py` |
|   215 | `tests/transports/test_sse_transport.py` |
|    86 | `tests/transports/test_websocket_v1_task_lifecycle.py` |

### 源码文件大小分布

- 文件数: 30
- 最小: 10 行
- 最大: 692 行
- 平均: 212 行
- 中位数: 156 行
- 最大 3 文件: `ext/bridge/bridge_api.py` (692行), `ext/bridge/types.py` (475行), `ext/bridge/bridge_status_util.py` (442行)

## #7 工具实现层

**总源码 22,507 行** | **总测试 12,426 行** | **合计 34,933 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    67 | `ext/tool_system/__init__.py` |
|   222 | `ext/tool_system/build_tool.py` |
|   519 | `ext/tool_system/context.py` |
|   140 | `ext/tool_system/defaults.py` |
|    95 | `ext/tool_system/diff_utils.py` |
|    17 | `ext/tool_system/errors.py` |
|    75 | `ext/tool_system/loader.py` |
|    30 | `ext/tool_system/protocol.py` |
|   601 | `ext/tool_system/registry.py` |
|   259 | `ext/tool_system/renderers.py` |
|   414 | `ext/tool_system/schema_validation.py` |
|    62 | `ext/tool_system/task_manager.py` |
|    78 | `ext/tool_system/team_aware_pool.py` |
|   422 | `ext/tool_system/tool_search.py` |
|   345 | `ext/tool_system/tool_timeout.py` |
|   183 | `ext/tool_system/tools/__init__.py` |
|   131 | `ext/tool_system/tools/advisor.py` |
| 1,631 | `ext/tool_system/tools/agent.py` |
|   147 | `ext/tool_system/tools/ask_issue_author.py` |
|    97 | `ext/tool_system/tools/ask_user_question.py` |
|     5 | `ext/tool_system/tools/bash/__init__.py` |
|   356 | `ext/tool_system/tools/bash/background.py` |
| 1,104 | `ext/tool_system/tools/bash/bash_tool.py` |
|   138 | `ext/tool_system/tools/bash/command_semantics.py` |
|   102 | `ext/tool_system/tools/bash/destructive_warnings.py` |
|   113 | `ext/tool_system/tools/bash/image_output.py` |
|   146 | `ext/tool_system/tools/bash/prompt.py` |
|   251 | `ext/tool_system/tools/bash/read_only_validation.py` |
|   470 | `ext/tool_system/tools/bash/search_classification.py` |
|    32 | `ext/tool_system/tools/bash/sleep_detection.py` |
|    58 | `ext/tool_system/tools/bash/utils.py` |
|   354 | `ext/tool_system/tools/bg_session.py` |
|    55 | `ext/tool_system/tools/brief.py` |
|    78 | `ext/tool_system/tools/config.py` |
|   251 | `ext/tool_system/tools/create_agent_tool.py` |
|   178 | `ext/tool_system/tools/cron.py` |
|   430 | `ext/tool_system/tools/edit.py` |
|   217 | `ext/tool_system/tools/execute.py` |
|   211 | `ext/tool_system/tools/glob.py` |
|   726 | `ext/tool_system/tools/grep.py` |
|   214 | `ext/tool_system/tools/lodestone.py` |
|    48 | `ext/tool_system/tools/lsp.py` |
|   324 | `ext/tool_system/tools/mcp.py` |
|   266 | `ext/tool_system/tools/mcp_resources.py` |
|   286 | `ext/tool_system/tools/memory.py` |
|    80 | `ext/tool_system/tools/misc.py` |
|   210 | `ext/tool_system/tools/monitor.py` |
|   314 | `ext/tool_system/tools/notebook_edit.py` |
|   460 | `ext/tool_system/tools/plan_mode.py` |
|   269 | `ext/tool_system/tools/progress_report.py` |
|   918 | `ext/tool_system/tools/read.py` |
|   259 | `ext/tool_system/tools/remote_trigger.py` |
|   121 | `ext/tool_system/tools/schedule_wakeup.py` |
|   638 | `ext/tool_system/tools/send_message.py` |
|    92 | `ext/tool_system/tools/send_user_message.py` |
|   640 | `ext/tool_system/tools/skill.py` |
|   263 | `ext/tool_system/tools/skill_search.py` |
|    69 | `ext/tool_system/tools/sleep.py` |
|   279 | `ext/tool_system/tools/snip.py` |
|    34 | `ext/tool_system/tools/structured_output.py` |
|   207 | `ext/tool_system/tools/task_decompose.py` |
|   361 | `ext/tool_system/tools/task_directives.py` |
|   281 | `ext/tool_system/tools/task_inspect.py` |
|   124 | `ext/tool_system/tools/task_stop.py` |
|   963 | `ext/tool_system/tools/tasks_v2.py` |
|   102 | `ext/tool_system/tools/team.py` |
|   379 | `ext/tool_system/tools/team_memory.py` |
|    89 | `ext/tool_system/tools/todo_write.py` |
|   603 | `ext/tool_system/tools/tool_search.py` |
|   782 | `ext/tool_system/tools/tool_search_matching.py` |
|   233 | `ext/tool_system/tools/web_browser.py` |
|   660 | `ext/tool_system/tools/web_fetch.py` |
|   404 | `ext/tool_system/tools/web_search.py` |
|    88 | `ext/tool_system/tools/worktree.py` |
|   345 | `ext/tool_system/tools/write.py` |
|     0 | `ext/tool_system/utils/__init__.py` |
|    29 | `ext/tool_system/utils/path_utils.py` |
|   263 | `ext/tool_system/utils/ripgrep.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/bash/__init__.py` |
|    58 | `tests/bash/test_bash_cwd_execution.py` |
|   216 | `tests/bash/test_bash_image_output.py` |
|   280 | `tests/bash/test_bash_parser.py` |
|    85 | `tests/bash/test_bash_permissions_ext.py` |
|   148 | `tests/bash/test_bash_permissions_full.py` |
|    74 | `tests/bash/test_bash_security.py` |
|   262 | `tests/bash/test_bash_timeout_vs_esc.py` |
|    72 | `tests/bash/test_bash_windows_shell_selection.py` |
|   253 | `tests/bash/test_powershell_f107.py` |
|   505 | `tests/clawcodex_ext/tasks/test_bg_session.py` |
|   101 | `tests/clawcodex_ext/tool_system/test_team_aware_pool.py` |
|   207 | `tests/clawcodex_ext/tool_system/tools/test_tool_stats.py` |
|     0 | `tests/file_ops/__init__.py` |
|   166 | `tests/file_ops/test_file_history.py` |
|   141 | `tests/file_ops/test_file_state_cache.py` |
|   270 | `tests/tasks/test_agent_name_registry.py` |
|   283 | `tests/tasks/test_dream_task.py` |
|   272 | `tests/tasks/test_in_process_teammate.py` |
|   445 | `tests/tasks/test_local_agent_lifecycle.py` |
|   235 | `tests/tasks/test_local_agent_migration.py` |
|   180 | `tests/tasks/test_local_shell_migration.py` |
|   389 | `tests/tasks/test_stop_task.py` |
|   300 | `tests/tasks/test_task_notification.py` |
|   222 | `tests/tasks/test_task_output_polling.py` |
|   244 | `tests/tasks/test_task_registry.py` |
|   160 | `tests/tasks/test_tasks_core.py` |
|     0 | `tests/tool/__init__.py` |
|   193 | `tests/tool/test_claude_code_tool_parity.py` |
|   441 | `tests/tool/test_tool_classifier_input.py` |
|    55 | `tests/tool/test_tool_context_abort_default.py` |
|   242 | `tests/tool/test_tool_execution_integration.py` |
|   107 | `tests/tool/test_tool_hooks.py` |
|    56 | `tests/tool/test_tool_normalization.py` |
|   131 | `tests/tool/test_tool_orchestration.py` |
|   439 | `tests/tool/test_tool_registry_pipeline.py` |
|   599 | `tests/tool/test_tool_result_budget.py` |
|   431 | `tests/tool/test_tool_result_persistence.py` |
|   277 | `tests/tool/test_tool_search.py` |
|   181 | `tests/tool/test_tool_search_layered_retrieval.py` |
|   565 | `tests/tool/test_tool_search_macro_routes.py` |
|   749 | `tests/tool/test_tool_search_matching.py` |
|   944 | `tests/tool/test_tool_system_tools.py` |
|    27 | `tests/tool_system/test_goal_tool.py` |
|   468 | `tests/tool_system/test_goal_tools.py` |
|    81 | `tests/tool_system/test_monitor_tool.py` |
|   576 | `tests/tool_system/test_send_message.py` |
|   296 | `tests/tool_system/test_task_stop.py` |

### 源码文件大小分布

- 文件数: 78
- 最小: 0 行
- 最大: 1,631 行
- 平均: 288 行
- 中位数: 222 行
- 最大 3 文件: `ext/tool_system/tools/agent.py` (1631行), `ext/tool_system/tools/bash/bash_tool.py` (1104行), `ext/tool_system/tools/tasks_v2.py` (963行)

## #8 技能系统

**总源码 11,797 行** | **总测试 9,160 行** | **合计 20,957 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    75 | `ext/skills/__init__.py` |
|   113 | `ext/skills/_frontmatter_adapter.py` |
|    63 | `ext/skills/argument_substitution.py` |
|   116 | `ext/skills/bundled/__init__.py` |
|   150 | `ext/skills/bundled/batch.py` |
|   182 | `ext/skills/bundled/debug.py` |
|   321 | `ext/skills/bundled/loop.py` |
|    83 | `ext/skills/bundled/orchestrator.py` |
|     1 | `ext/skills/bundled/orchestrator_resources/__init__.py` |
|   161 | `ext/skills/bundled/remember.py` |
|    50 | `ext/skills/bundled/resource_loader.py` |
|    87 | `ext/skills/bundled/simplify.py` |
|    66 | `ext/skills/bundled/spec_audit.py` |
|     1 | `ext/skills/bundled/spec_audit_resources/__init__.py` |
| 1,724 | `ext/skills/bundled/spec_audit_resources/scripts/inventory.py` |
| 3,407 | `ext/skills/bundled/spec_audit_resources/scripts/lint_report.py` |
|   630 | `ext/skills/bundled/spec_audit_resources/scripts/prepare_audit.py` |
|    49 | `ext/skills/bundled/stuck.py` |
|   430 | `ext/skills/bundled/update_config.py` |
|   118 | `ext/skills/bundled/verify.py` |
|    57 | `ext/skills/bundled/verify_content.py` |
|   565 | `ext/skills/bundled_skills.py` |
|   288 | `ext/skills/catalog.py` |
|    71 | `ext/skills/create.py` |
|   108 | `ext/skills/frontmatter.py` |
|   975 | `ext/skills/invocation.py` |
| 1,308 | `ext/skills/loader.py` |
|    30 | `ext/skills/mcp_skill_builders.py` |
|   113 | `ext/skills/model.py` |
|   316 | `ext/skills/runtime_substitution.py` |
|   139 | `ext/skills/visibility.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/skills/__init__.py` |
|   260 | `tests/skills/clawcodex-repl-pty-debug/scripts/audit_outer_transcript.py` |
|   147 | `tests/skills/clawcodex-repl-pty-debug/scripts/decider_helpers.py` |
|   290 | `tests/skills/clawcodex-repl-pty-debug/scripts/pty_adaptive_driver.py` |
|   157 | `tests/skills/clawcodex-repl-pty-debug/scripts/pty_jsonl_driver.py` |
|   228 | `tests/skills/test_bundled_registration_lifecycle_contract.py` |
|   149 | `tests/skills/test_bundled_resource_permissions.py` |
|   178 | `tests/skills/test_bundled_runtime_completion.py` |
|   279 | `tests/skills/test_bundled_runtime_security.py` |
|   200 | `tests/skills/test_orchestrator_bundled.py` |
|   138 | `tests/skills/test_remember_bundled.py` |
|   170 | `tests/skills/test_skill_catalog.py` |
|   271 | `tests/skills/test_skill_catalog_lifecycle_contract.py` |
|   268 | `tests/skills/test_skill_fork_agent_integration.py` |
|    91 | `tests/skills/test_skill_fork_scope_lifecycle.py` |
|   268 | `tests/skills/test_skill_invocation_service.py` |
|   241 | `tests/skills/test_skill_invocation_surfaces.py` |
|   168 | `tests/skills/test_skill_loader_legacy_registry.py` |
|   516 | `tests/skills/test_skill_runtime_boundaries.py` |
|   116 | `tests/skills/test_skills_bundled.py` |
|   289 | `tests/skills/test_skills_bundled_catalogue.py` |
|   518 | `tests/skills/test_skills_dedup_and_paths.py` |
|   329 | `tests/skills/test_skills_dedup_paths.py` |
|   357 | `tests/skills/test_skills_e2e.py` |
|   325 | `tests/skills/test_skills_ext_facade.py` |
|   367 | `tests/skills/test_skills_frontmatter_validators.py` |
|   278 | `tests/skills/test_skills_frontmatter_yaml.py` |
|   212 | `tests/skills/test_skills_full.py` |
|   156 | `tests/skills/test_skills_loader_ws8.py` |
|   493 | `tests/skills/test_skills_runtime_substitution.py` |
|   422 | `tests/skills/test_skills_shell_exec.py` |
|   289 | `tests/skills/test_skills_substitutions.py` |
|    83 | `tests/skills/test_skills_system.py` |
|   250 | `tests/skills/test_skills_unified.py` |
|    88 | `tests/skills/test_spec_audit_bundled.py` |
|   329 | `tests/skills/test_update_config_bundled.py` |
|   240 | `tests/skills/test_verify_bundled.py` |

### 源码文件大小分布

- 文件数: 31
- 最小: 1 行
- 最大: 3,407 行
- 平均: 380 行
- 中位数: 116 行
- 最大 3 文件: `ext/skills/bundled/spec_audit_resources/scripts/lint_report.py` (3407行), `ext/skills/bundled/spec_audit_resources/scripts/inventory.py` (1724行), `ext/skills/loader.py` (1308行)

## #9 安全·认证·钩子

**总源码 12,944 行** | **总测试 6,346 行** | **合计 19,290 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    34 | `ext/auth/__init__.py` |
|   152 | `ext/auth/auth.py` |
|    71 | `ext/auth/aws.py` |
|   273 | `ext/auth/claude_ai.py` |
|   328 | `ext/auth/codex_oauth.py` |
|   474 | `ext/auth/codex_store.py` |
|    36 | `ext/auth/gemini.py` |
|   183 | `ext/auth/oauth.py` |
|    68 | `ext/hooks/__init__.py` |
|   251 | `ext/hooks/_pluggy_adapter.py` |
|   584 | `ext/hooks/config_manager.py` |
|   126 | `ext/hooks/exec_agent_hook.py` |
|   107 | `ext/hooks/exec_http_hook.py` |
|    37 | `ext/hooks/exec_prompt_hook.py` |
| 1,330 | `ext/hooks/hook_executor.py` |
|   367 | `ext/hooks/hook_types.py` |
|    86 | `ext/hooks/output_schema.py` |
|    66 | `ext/hooks/post_sampling_hooks.py` |
|   180 | `ext/hooks/registry.py` |
|   291 | `ext/hooks/session_hooks.py` |
|    23 | `ext/hooks/shell_invocation.py` |
|    98 | `ext/hooks/ssrf_guard.py` |
|    37 | `ext/hooks/trust_gate.py` |
|   255 | `ext/permissions/__init__.py` |
|   258 | `ext/permissions/_treesitter_adapter.py` |
|    30 | `ext/permissions/bash_parser/__init__.py` |
|    47 | `ext/permissions/bash_parser/ast_nodes.py` |
|   214 | `ext/permissions/bash_parser/commands.py` |
|   267 | `ext/permissions/bash_parser/parser.py` |
|    31 | `ext/permissions/bash_parser/shell_quote.py` |
|   268 | `ext/permissions/bash_security.py` |
|   700 | `ext/permissions/bash_suggestions.py` |
|   872 | `ext/permissions/check.py` |
|   336 | `ext/permissions/classifier.py` |
|   246 | `ext/permissions/cycle.py` |
|   164 | `ext/permissions/danger_detector.py` |
|    81 | `ext/permissions/dangerous_safety.py` |
|   460 | `ext/permissions/filesystem.py` |
|   323 | `ext/permissions/handler.py` |
|    61 | `ext/permissions/loader.py` |
|   238 | `ext/permissions/modes.py` |
|   471 | `ext/permissions/powershell_security.py` |
|    91 | `ext/permissions/rule_parser.py` |
|   161 | `ext/permissions/rules.py` |
|   294 | `ext/permissions/runtime.py` |
|   253 | `ext/permissions/setup.py` |
|   456 | `ext/permissions/trust_boundary.py` |
|   401 | `ext/permissions/types.py` |
|   764 | `ext/permissions/updates.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|   158 | `tests/auth/test_auth.py` |
|   338 | `tests/auth/test_claude_ai.py` |
|   223 | `tests/auth/test_codex_oauth.py` |
|   338 | `tests/auth/test_codex_store.py` |
|     0 | `tests/hooks/__init__.py` |
|   215 | `tests/hooks/test_hook_config.py` |
|   144 | `tests/hooks/test_hook_config_schema.py` |
|   151 | `tests/hooks/test_hook_env_injection.py` |
|   140 | `tests/hooks/test_hook_event_taxonomy.py` |
|   165 | `tests/hooks/test_hook_executor.py` |
|   222 | `tests/hooks/test_hook_executors.py` |
|   153 | `tests/hooks/test_hook_output_schema.py` |
|   242 | `tests/hooks/test_hook_registry.py` |
|   360 | `tests/hooks/test_hook_shell_selection.py` |
|    77 | `tests/hooks/test_hook_source_deprecation.py` |
|     0 | `tests/permissions/__init__.py` |
|   347 | `tests/permissions/test_auto_mode_llm_classifier.py` |
|   410 | `tests/permissions/test_dangerous_skip_permissions.py` |
|   134 | `tests/permissions/test_filesystem_permissions.py` |
|   203 | `tests/permissions/test_permission_auto_bubble.py` |
|   256 | `tests/permissions/test_permission_check_flow.py` |
|   150 | `tests/permissions/test_permission_classifier.py` |
|   101 | `tests/permissions/test_permission_cycle.py` |
|    61 | `tests/permissions/test_permission_modes.py` |
|   216 | `tests/permissions/test_permission_rules.py` |
|   261 | `tests/permissions/test_permission_settings_schema.py` |
|   160 | `tests/permissions/test_permission_setup.py` |
|   447 | `tests/permissions/test_permission_updates.py` |
|   245 | `tests/permissions/test_permissions.py` |
|   246 | `tests/permissions/test_trust_boundary.py` |
|   183 | `tests/permissions/test_trust_gate.py` |

### 源码文件大小分布

- 文件数: 49
- 最小: 23 行
- 最大: 1,330 行
- 平均: 264 行
- 中位数: 238 行
- 最大 3 文件: `ext/hooks/hook_executor.py` (1330行), `ext/permissions/check.py` (872行), `ext/permissions/updates.py` (764行)

## #10 上下文系统

**总源码 5,019 行** | **总测试 1,349 行** | **合计 6,368 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    68 | `ext/context_system/__init__.py` |
|   260 | `ext/context_system/_gitpython_adapter.py` |
|   117 | `ext/context_system/builder.py` |
|    23 | `ext/context_system/cache_boundary.py` |
|   620 | `ext/context_system/claude_md.py` |
|     9 | `ext/context_system/clawcodex_md.py` |
|   389 | `ext/context_system/context_analyzer.py` |
|   286 | `ext/context_system/git_context.py` |
|    90 | `ext/context_system/memory_prefetch.py` |
|   473 | `ext/context_system/microcompact.py` |
|   196 | `ext/context_system/models.py` |
| 1,669 | `ext/context_system/prompt_assembly.py` |
|   140 | `ext/context_system/prompt_dump.py` |
|   408 | `ext/context_system/section_registry.py` |
|   197 | `ext/context_system/system_prompt_cache.py` |
|    74 | `ext/context_system/workspace_snapshot.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/context/__init__.py` |
|   226 | `tests/context/test_context_analyzer.py` |
|   152 | `tests/context/test_context_collapse.py` |
|   143 | `tests/context/test_context_system.py` |
|     0 | `tests/system_prompt/__init__.py` |
|    72 | `tests/system_prompt/test_clear_system_prompt_sections.py` |
|   308 | `tests/system_prompt/test_compression_pipeline.py` |
|   131 | `tests/system_prompt/test_system_prompt_cache.py` |
|   223 | `tests/system_prompt/test_system_prompt_full.py` |
|    94 | `tests/system_prompt/test_system_prompt_section_factory.py` |

### 源码文件大小分布

- 文件数: 16
- 最小: 9 行
- 最大: 1,669 行
- 平均: 313 行
- 中位数: 197 行
- 最大 3 文件: `ext/context_system/prompt_assembly.py` (1669行), `ext/context_system/claude_md.py` (620行), `ext/context_system/microcompact.py` (473行)

## #11 查询引擎

**总源码 6,754 行** | **总测试 4,083 行** | **合计 10,837 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
| 1,094 | `ext/query/agent_loop_compat.py` |
|   128 | `ext/query/config.py` |
|    11 | `ext/query/deps.py` |
|   393 | `ext/query/engine.py` |
|   123 | `ext/query/hook_registry.py` |
|   154 | `ext/query/outbox_types.py` |
| 3,482 | `ext/query/query.py` |
|   356 | `ext/query/recovery_strategies.py` |
|   390 | `ext/query/stop_hooks.py` |
|   343 | `ext/query/streaming.py` |
|   159 | `ext/query/token_budget.py` |
|   121 | `ext/query/transitions.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|   145 | `tests/clawcodex_ext/query/test_hook_registry.py` |
|    93 | `tests/clawcodex_ext/query/test_outbox_types.py` |
|   173 | `tests/clawcodex_ext/query/test_recovery_strategies.py` |
|     0 | `tests/query/__init__.py` |
|   280 | `tests/query/test_f99_first_completed.py` |
|   686 | `tests/query/test_query_engine.py` |
|   263 | `tests/query/test_query_engine_skill_visibility.py` |
|   696 | `tests/query/test_query_error_recovery.py` |
|   366 | `tests/query/test_query_hook_stopped.py` |
|   472 | `tests/query/test_query_loop.py` |
|   266 | `tests/query/test_query_terminal.py` |
|   129 | `tests/query/test_streaming_query_loop.py` |
|     0 | `tests/streaming/__init__.py` |
|   139 | `tests/streaming/test_streaming_executor.py` |
|   263 | `tests/streaming/test_streaming_executor_interruptible.py` |
|   112 | `tests/streaming/test_streaming_executor_race.py` |

### 源码文件大小分布

- 文件数: 12
- 最小: 11 行
- 最大: 3,482 行
- 平均: 562 行
- 中位数: 343 行
- 最大 3 文件: `ext/query/query.py` (3482行), `ext/query/agent_loop_compat.py` (1094行), `ext/query/engine.py` (393行)

## #12 设置

**总源码 1,028 行** | **总测试 1,296 行** | **合计 2,324 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|     1 | `ext/settings/__init__.py` |
|   201 | `ext/settings/pydantic_adapter.py` |
|     7 | `ext/settings/settings.py` |
|   623 | `ext/settings/types.py` |
|   196 | `ext/settings/validation.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/config/__init__.py` |
|   233 | `tests/config/test_config.py` |
|   199 | `tests/config/test_config_system.py` |
|   215 | `tests/config/test_configuration_contract.py` |
|   280 | `tests/config/test_configuration_service.py` |
|    80 | `tests/config/test_effort.py` |
|   289 | `tests/config/test_settings.py` |

### 源码文件大小分布

- 文件数: 5
- 最小: 1 行
- 最大: 623 行
- 平均: 205 行
- 中位数: 196 行
- 最大 3 文件: `ext/settings/types.py` (623行), `ext/settings/pydantic_adapter.py` (201行), `ext/settings/validation.py` (196行)

## #13 MCP 服务

**总源码 8,003 行** | **总测试 5,063 行** | **合计 13,066 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   228 | `ext/services/mcp/__init__.py` |
|   683 | `ext/services/mcp/auth.py` |
|   274 | `ext/services/mcp/auth_discovery.py` |
|   281 | `ext/services/mcp/auth_provider.py` |
|    86 | `ext/services/mcp/channel_permissions.py` |
|   192 | `ext/services/mcp/claudeai.py` |
|   866 | `ext/services/mcp/client.py` |
| 1,197 | `ext/services/mcp/config.py` |
|   383 | `ext/services/mcp/connection_manager.py` |
|   306 | `ext/services/mcp/doctor.py` |
|   111 | `ext/services/mcp/elicitation.py` |
|    33 | `ext/services/mcp/env_expansion.py` |
|   115 | `ext/services/mcp/errors.py` |
|    96 | `ext/services/mcp/fetch_wrappers.py` |
|   121 | `ext/services/mcp/in_process_transport.py` |
|   170 | `ext/services/mcp/manager.py` |
|    61 | `ext/services/mcp/mcp_string_utils.py` |
|    29 | `ext/services/mcp/normalization.py` |
|   206 | `ext/services/mcp/oauth_callback_server.py` |
|    77 | `ext/services/mcp/oauth_error_normalization.py` |
|   105 | `ext/services/mcp/oauth_port.py` |
|    81 | `ext/services/mcp/oauth_redaction.py` |
|   129 | `ext/services/mcp/official_registry.py` |
|    98 | `ext/services/mcp/output_storage.py` |
|   206 | `ext/services/mcp/output_validation.py` |
|    63 | `ext/services/mcp/telemetry.py` |
|    25 | `ext/services/mcp/text_truncation.py` |
|   400 | `ext/services/mcp/tool_wrapper.py` |
|   459 | `ext/services/mcp/transport.py` |
|   354 | `ext/services/mcp/types.py` |
|   277 | `ext/services/mcp/xaa.py` |
|   291 | `ext/services/mcp/xaa_idp_login.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/mcp/__init__.py` |
|   215 | `tests/mcp/test_mcp_auth.py` |
|   426 | `tests/mcp/test_mcp_client_full.py` |
|   193 | `tests/mcp/test_mcp_config.py` |
|   192 | `tests/mcp/test_mcp_config_full.py` |
|   376 | `tests/mcp/test_mcp_config_validation.py` |
|   477 | `tests/mcp/test_mcp_critic_blockers.py` |
|   629 | `tests/mcp/test_mcp_critic_followups.py` |
|   793 | `tests/mcp/test_mcp_critic_majors.py` |
|   156 | `tests/mcp/test_mcp_doctor.py` |
|    45 | `tests/mcp/test_mcp_env_expansion.py` |
|   168 | `tests/mcp/test_mcp_errors.py` |
|    35 | `tests/mcp/test_mcp_normalization.py` |
|   261 | `tests/mcp/test_mcp_phase4_callback_and_provider.py` |
|   130 | `tests/mcp/test_mcp_phase4_oauth_discovery.py` |
|   192 | `tests/mcp/test_mcp_phase4_oauth_helpers.py` |
|   292 | `tests/mcp/test_mcp_phase_polish_and_runtime.py` |
|    84 | `tests/mcp/test_mcp_string_utils.py` |
|   114 | `tests/mcp/test_mcp_tool_wrapper.py` |
|   166 | `tests/mcp/test_mcp_transport.py` |
|   119 | `tests/mcp/test_mcp_types.py` |

### 源码文件大小分布

- 文件数: 32
- 最小: 25 行
- 最大: 1,197 行
- 平均: 250 行
- 中位数: 192 行
- 最大 3 文件: `ext/services/mcp/config.py` (1197行), `ext/services/mcp/client.py` (866行), `ext/services/mcp/auth.py` (683行)

## #14 频道与 IM 集成

**总源码 10,659 行** | **总测试 11,195 行** | **合计 21,854 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   122 | `ext/services/channels/__init__.py` |
|   147 | `ext/services/channels/base.py` |
|   266 | `ext/services/channels/capabilities.py` |
|    51 | `ext/services/channels/discord.py` |
|    27 | `ext/services/channels/exceptions.py` |
|   104 | `ext/services/channels/feishu.py` |
| 1,011 | `ext/services/channels/feishu_app.py` |
|   249 | `ext/services/channels/feishu_cards.py` |
|    90 | `ext/services/channels/feishu_events.py` |
|   285 | `ext/services/channels/feishu_onboarding.py` |
|   137 | `ext/services/channels/feishu_sdk.py` |
|   173 | `ext/services/channels/feishu_settings.py` |
|   132 | `ext/services/channels/models.py` |
|    90 | `ext/services/channels/null_channel.py` |
|   262 | `ext/services/channels/registry.py` |
|   292 | `ext/services/channels/results.py` |
|   121 | `ext/services/channels/retry.py` |
|    58 | `ext/services/channels/slack.py` |
|   311 | `ext/services/channels/transport.py` |
| 1,567 | `ext/services/channels/wechat_ilink.py` |
|    73 | `ext/services/im_gateway/__init__.py` |
|    55 | `ext/services/im_gateway/audit.py` |
|   191 | `ext/services/im_gateway/binding.py` |
|    48 | `ext/services/im_gateway/capability_gate.py` |
|   448 | `ext/services/im_gateway/config.py` |
|   220 | `ext/services/im_gateway/dispatcher.py` |
|   542 | `ext/services/im_gateway/gateway.py` |
|   353 | `ext/services/im_gateway/ipc_client.py` |
|   259 | `ext/services/im_gateway/ipc_protocol.py` |
|   735 | `ext/services/im_gateway/ipc_server.py` |
|   171 | `ext/services/im_gateway/models.py` |
|   133 | `ext/services/im_gateway/origin_utils.py` |
|   322 | `ext/services/im_gateway/outbound.py` |
|   129 | `ext/services/im_gateway/processing_status.py` |
|    14 | `ext/services/im_gateway/reliability.py` |
|    98 | `ext/services/im_gateway/repl_command_gate.py` |
|    41 | `ext/services/im_gateway/retention.py` |
|    37 | `ext/services/im_gateway/router.py` |
|   369 | `ext/services/im_gateway/store.py` |
|    90 | `ext/services/im_gateway/stub_agent.py` |
|   107 | `ext/services/im_gateway/text.py` |
|    11 | `extensions/im_gateway/__init__.py` |
|   104 | `extensions/im_gateway/host_agent.py` |
|   614 | `extensions/im_gateway/server.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     1 | `tests/services/channels/__init__.py` |
|    44 | `tests/services/channels/conftest.py` |
|   122 | `tests/services/channels/test_contract_capabilities.py` |
|   182 | `tests/services/channels/test_contract_registry.py` |
|   120 | `tests/services/channels/test_contract_results.py` |
|    86 | `tests/services/channels/test_contract_retry.py` |
|   144 | `tests/services/channels/test_discord.py` |
|   182 | `tests/services/channels/test_feishu.py` |
|   817 | `tests/services/channels/test_feishu_app_adapter.py` |
|   130 | `tests/services/channels/test_feishu_app_card_actions.py` |
|    85 | `tests/services/channels/test_feishu_app_events.py` |
|   129 | `tests/services/channels/test_feishu_app_settings.py` |
|    60 | `tests/services/channels/test_feishu_app_shutdown.py` |
|   243 | `tests/services/channels/test_feishu_cards.py` |
|   216 | `tests/services/channels/test_feishu_onboarding.py` |
|    51 | `tests/services/channels/test_feishu_registry.py` |
|    78 | `tests/services/channels/test_feishu_sdk.py` |
|   238 | `tests/services/channels/test_manager.py` |
|   210 | `tests/services/channels/test_models.py` |
|    82 | `tests/services/channels/test_null.py` |
|   143 | `tests/services/channels/test_slack.py` |
|   158 | `tests/services/channels/test_transport.py` |
| 1,198 | `tests/services/channels/test_wechat_ilink.py` |
| 1,389 | `tests/services/im_gateway/test_channels_cmd.py` |
|   288 | `tests/services/im_gateway/test_config.py` |
|   547 | `tests/services/im_gateway/test_connection_notify.py` |
|   255 | `tests/services/im_gateway/test_core.py` |
|   296 | `tests/services/im_gateway/test_dispatcher.py` |
|   512 | `tests/services/im_gateway/test_gateway.py` |
|   395 | `tests/services/im_gateway/test_gateway_cmd.py` |
| 1,026 | `tests/services/im_gateway/test_ipc.py` |
|   129 | `tests/services/im_gateway/test_ipc_protocol.py` |
|   223 | `tests/services/im_gateway/test_ipc_reconnect.py` |
|   301 | `tests/services/im_gateway/test_outbound.py` |
|   179 | `tests/services/im_gateway/test_processing_status.py` |
|   121 | `tests/services/im_gateway/test_reliability_p4.py` |
|   210 | `tests/services/im_gateway/test_repl_command_gate.py` |
|   273 | `tests/services/im_gateway/test_retention.py` |
|   154 | `tests/services/im_gateway/test_semantics_routing.py` |
|   109 | `tests/services/im_gateway/test_stub_agent.py` |
|    69 | `tests/services/im_gateway/test_text.py` |

### 源码文件大小分布

- 文件数: 44
- 最小: 11 行
- 最大: 1,567 行
- 平均: 242 行
- 中位数: 137 行
- 最大 3 文件: `ext/services/channels/wechat_ilink.py` (1567行), `ext/services/channels/feishu_app.py` (1011行), `ext/services/im_gateway/ipc_server.py` (735行)

## #15 基础设施服务

**总源码 40,462 行** | **总测试 131,777 行** | **合计 172,239 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    11 | `ext/away_summary/__init__.py` |
|    95 | `ext/away_summary/command.py` |
|   112 | `ext/away_summary/config.py` |
|   198 | `ext/away_summary/controller.py` |
|   110 | `ext/away_summary/fingerprint.py` |
|    81 | `ext/away_summary/memory.py` |
|    53 | `ext/away_summary/messages.py` |
|   325 | `ext/away_summary/prompt.py` |
|    28 | `ext/away_summary/registration.py` |
|   897 | `ext/away_summary/service.py` |
|     1 | `ext/bootstrap/__init__.py` |
|     7 | `ext/bootstrap/state.py` |
|    30 | `ext/buddy/__init__.py` |
|   222 | `ext/buddy/companion.py` |
|    13 | `ext/buddy/feature.py` |
|    60 | `ext/buddy/notification.py` |
|   113 | `ext/buddy/observer.py` |
|   105 | `ext/buddy/prompt.py` |
|    82 | `ext/buddy/soul.py` |
|   535 | `ext/buddy/sprites.py` |
|   241 | `ext/buddy/types.py` |
|     1 | `ext/services/__init__.py` |
|    25 | `ext/services/analytics/__init__.py` |
|    75 | `ext/services/analytics/events.py` |
|    63 | `ext/services/analytics/metadata.py` |
|    85 | `ext/services/analytics/sink.py` |
|    36 | `ext/services/api/__init__.py` |
|   459 | `ext/services/api/claude.py` |
|   363 | `ext/services/api/errors.py` |
|   105 | `ext/services/api/logging.py` |
|    57 | `ext/services/api/provider_config.py` |
|   161 | `ext/services/api/retry.py` |
|    63 | `ext/services/api/tool_normalization.py` |
|    29 | `ext/services/bridge/__init__.py` |
|    62 | `ext/services/bridge/auth.py` |
|    63 | `ext/services/bridge/session.py` |
|    79 | `ext/services/bridge/transport.py` |
|    68 | `ext/services/chrome/__init__.py` |
|   170 | `ext/services/chrome/base.py` |
|   552 | `ext/services/chrome/factory.py` |
|   542 | `ext/services/chrome/mcp_impl.py` |
|    60 | `ext/services/chrome/models.py` |
|   137 | `ext/services/chrome/null_impl.py` |
|   443 | `ext/services/chrome/playwright_impl.py` |
|   355 | `ext/services/chrome/recording.py` |
|    94 | `ext/services/compact/__init__.py` |
|   342 | `ext/services/compact/autocompact.py` |
|   661 | `ext/services/compact/compact.py` |
|    36 | `ext/services/compact/compact_warning.py` |
|   159 | `ext/services/compact/context_collapse.py` |
|   156 | `ext/services/compact/gating.py` |
|    64 | `ext/services/compact/grouping.py` |
|   416 | `ext/services/compact/pipeline.py` |
|   301 | `ext/services/compact/post_compact_attachments.py` |
|    59 | `ext/services/compact/post_compact_cleanup.py` |
|   410 | `ext/services/compact/prompt.py` |
|   251 | `ext/services/compact/reactive_compact.py` |
|   381 | `ext/services/compact/session_memory_compact.py` |
|    23 | `ext/services/compact/snip_compact.py` |
|   249 | `ext/services/compact/tool_result_budget.py` |
|    73 | `ext/services/computer_use/__init__.py` |
|    91 | `ext/services/computer_use/base.py` |
|    77 | `ext/services/computer_use/dry_run.py` |
|    21 | `ext/services/computer_use/exceptions.py` |
|    46 | `ext/services/computer_use/factory.py` |
|   101 | `ext/services/computer_use/models.py` |
|    78 | `ext/services/computer_use/platform/__init__.py` |
|   446 | `ext/services/computer_use/platform/linux.py` |
|   170 | `ext/services/computer_use/platform/null.py` |
|   133 | `ext/services/context_collapse/__init__.py` |
|   146 | `ext/services/context_collapse/boundary.py` |
|   295 | `ext/services/context_collapse/engine.py` |
|    36 | `ext/services/context_collapse/exceptions.py` |
|   166 | `ext/services/context_collapse/persistence.py` |
|   206 | `ext/services/context_collapse/summary.py` |
|   290 | `ext/services/context_collapse/tokens.py` |
|   250 | `ext/services/context_collapse/trigger.py` |
|   267 | `ext/services/cost_restore.py` |
|   248 | `ext/services/cost_tracker.py` |
|   141 | `ext/services/feature_gate/__init__.py` |
|    31 | `ext/services/ide/__init__.py` |
|   171 | `ext/services/ide/connection.py` |
|    75 | `ext/services/ide/diagnostics.py` |
|    78 | `ext/services/ide/selection.py` |
|    84 | `ext/services/ide/types.py` |
|    66 | `ext/services/kairos/__init__.py` |
|    93 | `ext/services/kairos/brief.py` |
|    88 | `ext/services/kairos/daily_log.py` |
|    25 | `ext/services/kairos/exceptions.py` |
|   214 | `ext/services/kairos/models.py` |
|   241 | `ext/services/kairos/scheduler.py` |
|    71 | `ext/services/langfuse/__init__.py` |
|   170 | `ext/services/langfuse/client.py` |
|   298 | `ext/services/langfuse/exporter.py` |
|   394 | `ext/services/langfuse/sink.py` |
|    49 | `ext/services/lodestone/__init__.py` |
|   143 | `ext/services/lodestone/config.py` |
|   348 | `ext/services/lodestone/fingerprint.py` |
|   378 | `ext/services/lodestone/models.py` |
|   348 | `ext/services/lodestone/parser.py` |
|   439 | `ext/services/lodestone/renderer.py` |
|   221 | `ext/services/lodestone/resolver.py` |
|   225 | `ext/services/lodestone/service.py` |
|   262 | `ext/services/lodestone/targets.py` |
|    24 | `ext/services/monitor/__init__.py` |
|   178 | `ext/services/monitor/controller.py` |
|    37 | `ext/services/monitor/install.py` |
|    31 | `ext/services/monitor/stall_guard.py` |
|   215 | `ext/services/monitor/text_tail.py` |
|    60 | `ext/services/monitor/watch_compat.py` |
|    10 | `ext/services/oauth/__init__.py` |
|    41 | `ext/services/oauth/client.py` |
|   164 | `ext/services/periodic/__init__.py` |
|    22 | `ext/services/pipe_ipc/__init__.py` |
|    39 | `ext/services/pipe_ipc/codec.py` |
|   131 | `ext/services/pipe_ipc/models.py` |
|    64 | `ext/services/pipe_ipc/permissions.py` |
|   103 | `ext/services/pipe_ipc/registry.py` |
|   200 | `ext/services/pipe_ipc/uds.py` |
|   398 | `ext/services/pricing.py` |
|    33 | `ext/services/proactive/__init__.py` |
|    10 | `ext/services/proactive/constants.py` |
|   224 | `ext/services/proactive/controller.py` |
|    76 | `ext/services/proactive/prompts.py` |
|    31 | `ext/services/proactive/state.py` |
|   123 | `ext/services/proactive/tick_emitter.py` |
|   473 | `ext/services/session_migrate.py` |
|   370 | `ext/services/session_resume.py` |
|   654 | `ext/services/session_storage.py` |
|   104 | `ext/services/session_title.py` |
|     0 | `ext/services/skill_search/__init__.py` |
|    55 | `ext/services/skill_search/config.py` |
|   293 | `ext/services/skill_search/document.py` |
|    23 | `ext/services/skill_search/exceptions.py` |
|   572 | `ext/services/skill_search/index.py` |
|   400 | `ext/services/skill_search/searcher.py` |
|   418 | `ext/services/skill_search/tokenizer.py` |
|   180 | `ext/services/skill_search/watcher.py` |
|   111 | `ext/services/swarm/__init__.py` |
|   138 | `ext/services/swarm/agent_name_registry.py` |
|    38 | `ext/services/swarm/helpers.py` |
|   282 | `ext/services/swarm/leader_permission_bridge.py` |
|   299 | `ext/services/swarm/mailbox.py` |
|   459 | `ext/services/swarm/mailbox_poller.py` |
|    73 | `ext/services/swarm/permissions.py` |
|   122 | `ext/services/swarm/team_file.py` |
|    23 | `ext/services/swarm/team_membership.py` |
|   136 | `ext/services/swarm/teammate.py` |
|   133 | `ext/services/tail_follower.py` |
|   176 | `ext/services/templates/__init__.py` |
|   232 | `ext/services/templates/bootstrap.py` |
|   263 | `ext/services/templates/built_in.py` |
|   104 | `ext/services/templates/catalogue.py` |
|    58 | `ext/services/templates/compatibility.py` |
|   168 | `ext/services/templates/discovery.py` |
|    80 | `ext/services/templates/exceptions.py` |
|    43 | `ext/services/templates/generator.py` |
|   577 | `ext/services/templates/models.py` |
|   169 | `ext/services/templates/persistence.py` |
|   253 | `ext/services/templates/registry.py` |
|   203 | `ext/services/templates/renderer.py` |
|   140 | `ext/services/templates/resolver.py` |
|   318 | `ext/services/templates/schema.py` |
|    91 | `ext/services/tool_execution/__init__.py` |
|   349 | `ext/services/tool_execution/orchestrator.py` |
|   540 | `ext/services/tool_execution/streaming_executor.py` |
|   739 | `ext/services/tool_execution/tool_execution.py` |
|   485 | `ext/services/tool_execution/tool_hooks.py` |
|   552 | `ext/services/tool_execution/tool_result_persistence.py` |
|   109 | `ext/services/ultraplan/__init__.py` |
|   208 | `ext/services/ultraplan/adjuster.py` |
|    76 | `ext/services/ultraplan/audit.py` |
|    95 | `ext/services/ultraplan/ccr_session.py` |
|   150 | `ext/services/ultraplan/controller.py` |
|    77 | `ext/services/ultraplan/exceptions.py` |
|   335 | `ext/services/ultraplan/executor.py` |
|    86 | `ext/services/ultraplan/feature_gates.py` |
|   102 | `ext/services/ultraplan/keyword_detector.py` |
|   309 | `ext/services/ultraplan/llm_planner.py` |
|   381 | `ext/services/ultraplan/models.py` |
|    21 | `ext/services/ultraplan/planner_recovery.py` |
|   149 | `ext/services/ultraplan/store.py` |
|   152 | `ext/services/ultraplan/templates.py` |
|   375 | `ext/services/ultraplan/verifier.py` |
|   285 | `ext/services/voice/__init__.py` |
|   376 | `ext/services/voice/anthropic_stt.py` |
|   132 | `ext/services/voice/audio_chunk_queue.py` |
|   158 | `ext/services/voice/audio_out_queue.py` |
|   327 | `ext/services/voice/audio_player.py` |
|   326 | `ext/services/voice/audio_recorder.py` |
|   114 | `ext/services/voice/detection.py` |
|   218 | `ext/services/voice/dialogue.py` |
|   453 | `ext/services/voice/dialogue_session.py` |
|   333 | `ext/services/voice/doubao_stt.py` |
|   215 | `ext/services/voice/gemini_tts.py` |
|   275 | `ext/services/voice/interrupt.py` |
|   549 | `ext/services/voice/minimax_realtime_dialogue.py` |
|   540 | `ext/services/voice/minimax_stt.py` |
|   355 | `ext/services/voice/minimax_tts.py` |
|   198 | `ext/services/voice/openai_tts.py` |
|   184 | `ext/services/voice/provider_registry.py` |
|   375 | `ext/services/voice/push_to_talk.py` |
|    56 | `ext/services/voice/stt.py` |
|   202 | `ext/services/voice/tts.py` |
|   289 | `ext/services/voice/voice_mode_enabled.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/abort/__init__.py` |
|   108 | `tests/abort/test_abort_controller.py` |
|    91 | `tests/abort/test_abort_controller_once.py` |
|   414 | `tests/abort/test_esc_cancel_propagation.py` |
|   402 | `tests/abort/test_esc_reject_message_dispatch.py` |
|   165 | `tests/abort/test_minimax_abort_signal.py` |
|   212 | `tests/abort/test_ripgrep_abort.py` |
|   402 | `tests/abort/test_stream_abort_guard.py` |
|   532 | `tests/abort/test_stream_watchdog.py` |
|     0 | `tests/advisor/__init__.py` |
|   255 | `tests/advisor/test_advisor_chat_response_roundtrip.py` |
|   615 | `tests/advisor/test_advisor_client_side.py` |
|   324 | `tests/advisor/test_advisor_command.py` |
|   386 | `tests/advisor/test_advisor_helpers.py` |
|   186 | `tests/advisor/test_advisor_orphan_pairing.py` |
|   446 | `tests/advisor/test_advisor_request_wiring.py` |
|     0 | `tests/analytics/__init__.py` |
|   118 | `tests/analytics/test_analytics.py` |
|     1 | `tests/away_summary/__init__.py` |
|   345 | `tests/away_summary/test_cache_reuse.py` |
|    33 | `tests/away_summary/test_config.py` |
|   263 | `tests/away_summary/test_controller.py` |
|   510 | `tests/away_summary/test_frontend_wiring.py` |
|   173 | `tests/away_summary/test_memory.py` |
|    72 | `tests/away_summary/test_messages.py` |
|   166 | `tests/away_summary/test_prompt_diff.py` |
|    27 | `tests/away_summary/test_prompt_no_content.py` |
|   214 | `tests/away_summary/test_recap_cache_integration.py` |
|   126 | `tests/away_summary/test_recap_command.py` |
|   742 | `tests/away_summary/test_service.py` |
|     0 | `tests/bootstrap/__init__.py` |
|   535 | `tests/bootstrap/test_bootstrap_state.py` |
|     0 | `tests/cache/__init__.py` |
|   415 | `tests/cache/test_cache_state.py` |
|   161 | `tests/cache/test_cache_warning.py` |
|     1 | `tests/clawcodex_ext/services/__init__.py` |
|     1 | `tests/clawcodex_ext/services/lodestone/__init__.py` |
|   117 | `tests/clawcodex_ext/services/lodestone/test_command.py` |
|    83 | `tests/clawcodex_ext/services/lodestone/test_config.py` |
|   140 | `tests/clawcodex_ext/services/lodestone/test_fingerprint.py` |
|   214 | `tests/clawcodex_ext/services/lodestone/test_models.py` |
|   150 | `tests/clawcodex_ext/services/lodestone/test_parser.py` |
|   155 | `tests/clawcodex_ext/services/lodestone/test_renderer.py` |
|    53 | `tests/clawcodex_ext/services/lodestone/test_resolver.py` |
|    77 | `tests/clawcodex_ext/services/lodestone/test_targets.py` |
|   122 | `tests/clawcodex_ext/services/lodestone/test_tool.py` |
|     0 | `tests/compact/__init__.py` |
|   288 | `tests/compact/test_autocompact.py` |
|   347 | `tests/compact/test_compact.py` |
|   152 | `tests/compact/test_compact_prompt.py` |
|   483 | `tests/compact/test_compact_service.py` |
|   316 | `tests/compact/test_microcompact.py` |
|   258 | `tests/compact/test_post_compact_attachments.py` |
|    78 | `tests/compact/test_post_compact_cleanup.py` |
|   145 | `tests/compact/test_reactive_compact.py` |
|    69 | `tests/compact/test_snip_compact.py` |
|     0 | `tests/coordinator/__init__.py` |
|   487 | `tests/coordinator/test_mode.py` |
|   150 | `tests/coordinator/test_prompt.py` |
|     0 | `tests/cost_tracker/__init__.py` |
|   138 | `tests/cost_tracker/test_cost_tracker.py` |
|   249 | `tests/cost_tracker/test_cost_tracker_facade.py` |
|   141 | `tests/cost_tracker/test_cost_tracker_full.py` |
|   133 | `tests/cron/test_accumulation_guard.py` |
|   196 | `tests/cron/test_concurrent_scheduling.py` |
|   151 | `tests/cron/test_dispatch_bridge.py` |
|   491 | `tests/cron/test_e2e_dual_durable.py` |
|   601 | `tests/cron/test_f22_gaps.py` |
|    58 | `tests/cron/test_frontend_runtime_wiring.py` |
|   426 | `tests/cron/test_headless_runtime.py` |
|    31 | `tests/cron/test_lock.py` |
|   137 | `tests/cron/test_owner_lifecycle.py` |
|    85 | `tests/cron/test_parser.py` |
|   371 | `tests/cron/test_phase_f_ownership.py` |
|   239 | `tests/cron/test_phase_h_mtime.py` |
|    93 | `tests/cron/test_phase_i_ccb_gate.py` |
|   237 | `tests/cron/test_phase_j_commands.py` |
|   102 | `tests/cron/test_repl_run_lifecycle.py` |
|    99 | `tests/cron/test_runs.py` |
|    58 | `tests/cron/test_schedule.py` |
|   515 | `tests/cron/test_scheduler.py` |
|    42 | `tests/cron/test_status.py` |
|   393 | `tests/cron/test_tasks.py` |
|   166 | `tests/cron/test_tools_runtime.py` |
|   209 | `tests/debug/fake_repl_child.py` |
|   139 | `tests/debug/test_agent_debug.py` |
| 1,946 | `tests/debug/test_repl_pty_session.py` |
|   139 | `tests/debug/test_scenario5_permission_classification.py` |
|     0 | `tests/diagnostics/__init__.py` |
|   134 | `tests/diagnostics/test_decoupling_guard.py` |
|   157 | `tests/diagnostics/test_diag_cli.py` |
|   339 | `tests/diagnostics/test_freeze_detection.py` |
|    50 | `tests/diagnostics/test_recovery_strategies.py` |
|    65 | `tests/diagnostics/test_settings_integration.py` |
|   225 | `tests/diagnostics/test_tool_timeout.py` |
|     1 | `tests/dreaming/__init__.py` |
|   265 | `tests/dreaming/test_cron_integration.py` |
|   232 | `tests/dreaming/test_dream_skill.py` |
|   354 | `tests/dreaming/test_e2e_dreaming.py` |
|   241 | `tests/dreaming/test_llm_runner.py` |
|   348 | `tests/dreaming/test_lock.py` |
|    87 | `tests/dreaming/test_prompt.py` |
|   112 | `tests/dreaming/test_runner.py` |
|   390 | `tests/dreaming/test_service.py` |
|     3 | `tests/extensions/recording/__init__.py` |
|   216 | `tests/extensions/recording/test_asciicast_writer.py` |
|   395 | `tests/extensions/recording/test_auto_demo.py` |
|   434 | `tests/extensions/recording/test_cast_to_mp4.py` |
|   109 | `tests/extensions/recording/test_cron_observer.py` |
|   223 | `tests/extensions/recording/test_headless_recording.py` |
|   151 | `tests/extensions/recording/test_integration.py` |
|   180 | `tests/extensions/recording/test_logical_kanban_repl_e2e.py` |
|   820 | `tests/extensions/recording/test_orchestrator_integration.py` |
|   126 | `tests/extensions/recording/test_orchestrator_sink.py` |
|   236 | `tests/extensions/recording/test_pty_mode.py` |
|   130 | `tests/extensions/recording/test_registry.py` |
|   270 | `tests/extensions/recording/test_repl_capture.py` |
|    84 | `tests/extensions/recording/test_repl_capture_e2e.py` |
|   227 | `tests/extensions/recording/test_repl_dashboard_e2e.py` |
|   113 | `tests/extensions/recording/test_sop_projector.py` |
|   107 | `tests/extensions/recording/test_validate_cast.py` |
|   136 | `tests/extensions/recording/test_visualizer_source.py` |
|   156 | `tests/extensions/tool_system_ext/test_team_filter.py` |
|     0 | `tests/provider/__init__.py` |
|   148 | `tests/provider/test_model_registry.py` |
|   123 | `tests/provider/test_model_resolver.py` |
|   138 | `tests/provider/test_model_store.py` |
|   577 | `tests/provider/test_provider_model_commands.py` |
|    80 | `tests/provider/test_repl_routing.py` |
|   452 | `tests/provider/test_runtime_switching.py` |
|   358 | `tests/provider/test_slash_commands.py` |
|     0 | `tests/fast/__init__.py` |
|    81 | `tests/fast/test_fast_mode.py` |
|   175 | `tests/fast/test_fast_path_dispatch.py` |
|     0 | `tests/feature_gate/__init__.py` |
|   217 | `tests/feature_gate/test_cli.py` |
|    87 | `tests/feature_gate/test_cli_integration.py` |
|    94 | `tests/feature_gate/test_config.py` |
|   187 | `tests/feature_gate/test_decorators.py` |
|   136 | `tests/feature_gate/test_facade.py` |
|    83 | `tests/feature_gate/test_package.py` |
|   298 | `tests/feature_gate/test_registry.py` |
|    65 | `tests/feature_gate/test_types.py` |
|    12 | `tests/fixtures/fixture_fwa_project/contracts.py` |
|    12 | `tests/fixtures/fixture_fwa_project/decisions.py` |
|     3 | `tests/fixtures/fixture_fwa_project/gates.py` |
|     6 | `tests/fixtures/fixture_fwa_project/stage_impls/analyze.py` |
|     6 | `tests/fixtures/fixture_fwa_project/stage_impls/generate.py` |
|     6 | `tests/fixtures/fixture_fwa_project/stage_impls/preprocess.py` |
|     9 | `tests/fixtures/fixture_fwa_project/stages.py` |
|     8 | `tests/fixtures/fixture_fwa_project/transitions.py` |
|     8 | `tests/fixtures/fixture_hybrid_project/phases.py` |
|     6 | `tests/fixtures/fixture_hybrid_project/pipeline/ingest.py` |
|    14 | `tests/fixtures/fixture_sdk_project/calculator.py` |
|     0 | `tests/git_fixtures/__init__.py` |
|   183 | `tests/git_fixtures/test_git_context.py` |
|   176 | `tests/git_fixtures/test_git_utilities.py` |
|   129 | `tests/git_fixtures/test_gitpython_adapter.py` |
|     1 | `tests/goal/__init__.py` |
|    84 | `tests/goal/test_goal_accounting.py` |
|   432 | `tests/goal/test_goal_evaluator.py` |
|    48 | `tests/goal/test_goal_files.py` |
|   123 | `tests/goal/test_goal_model.py` |
|    82 | `tests/goal/test_goal_observability.py` |
|   168 | `tests/goal/test_goal_protocol.py` |
| 1,059 | `tests/goal/test_goal_runtime.py` |
|   371 | `tests/goal/test_goal_service.py` |
|    32 | `tests/goal/test_goal_spec1_boundary.py` |
|   133 | `tests/goal/test_goal_steering.py` |
|   447 | `tests/goal/test_goal_store.py` |
|     0 | `tests/helpers/__init__.py` |
|    78 | `tests/helpers/agent_loop.py` |
|     0 | `tests/ide/__init__.py` |
|   210 | `tests/ide/test_ide_connection.py` |
|     0 | `tests/image/__init__.py` |
|   304 | `tests/image/test_image_processor.py` |
|   167 | `tests/image/test_image_validation.py` |
|     0 | `tests/integration/__init__.py` |
|   352 | `tests/integration/test_advisor_smoke.py` |
|   132 | `tests/integration/test_api_integration.py` |
|   362 | `tests/integration/test_compression_integration.py` |
|   159 | `tests/integration/test_compression_integration_full.py` |
|    86 | `tests/integration/test_file_operations.py` |
|   351 | `tests/integration/test_init_integration.py` |
|   346 | `tests/integration/test_integration_permission_system.py` |
|   283 | `tests/integration/test_integration_smoke.py` |
|   646 | `tests/integration/test_integration_tool_queries.py` |
|   346 | `tests/integration/test_mcp_integration.py` |
|   101 | `tests/integration/test_mcp_integration_full.py` |
|   160 | `tests/integration/test_permission_integration.py` |
|   171 | `tests/integration/test_phase_a_integration.py` |
|   123 | `tests/integration/test_phase_c_build.py` |
|    92 | `tests/integration/test_phase_c_compact.py` |
|    83 | `tests/integration/test_phase_c_hooks.py` |
|   138 | `tests/integration/test_phase_c_plugins.py` |
|   279 | `tests/integration/test_query_integration.py` |
|    71 | `tests/integration/test_real_mcp_server.py` |
|   166 | `tests/integration/test_session_integration.py` |
|   907 | `tests/integration/test_ws5_integration.py` |
|   216 | `tests/integration/test_ws9_build.py` |
|    56 | `tests/intent_forecast/test_cli.py` |
|    95 | `tests/intent_forecast/test_command.py` |
|    58 | `tests/intent_forecast/test_config.py` |
|   198 | `tests/intent_forecast/test_context.py` |
|   346 | `tests/intent_forecast/test_controller.py` |
|   121 | `tests/intent_forecast/test_fallback_rules.py` |
|    34 | `tests/intent_forecast/test_focus_aliases.py` |
|    83 | `tests/intent_forecast/test_learning.py` |
|   371 | `tests/intent_forecast/test_service.py` |
|    76 | `tests/intent_forecast/test_session_retrieval.py` |
|    71 | `tests/intent_forecast/test_task_state.py` |
|   143 | `tests/intent_forecast/test_workspace_signals.py` |
|     0 | `tests/memdir/__init__.py` |
|   169 | `tests/memdir/test_memdir_memdir.py` |
|   206 | `tests/memdir/test_memdir_paths.py` |
|   120 | `tests/memdir/test_memdir_prompt_hookup.py` |
|   249 | `tests/memdir/test_memdir_scan_recall.py` |
|   278 | `tests/memdir/test_memdir_team_mem_paths.py` |
|   176 | `tests/memdir/test_memdir_team_mem_prompts.py` |
|    64 | `tests/memdir/test_memdir_types.py` |
|   132 | `tests/memdir/test_memdir_write_carve_out.py` |
|    51 | `tests/memdir/test_memory_prefetch.py` |
|     0 | `tests/message/__init__.py` |
|   219 | `tests/message/test_legacy_notification_backcompat.py` |
|   294 | `tests/message/test_message_cache_breakpoints.py` |
|   116 | `tests/message/test_message_normalization.py` |
|   176 | `tests/message/test_message_types.py` |
|   264 | `tests/message/test_messages_utility.py` |
|    97 | `tests/message/test_pending_message_drain.py` |
|     0 | `tests/misc/__init__.py` |
|   191 | `tests/misc/test_agent_def_generator.py` |
|    46 | `tests/misc/test_agents_for_mentions.py` |
|    73 | `tests/misc/test_arc_extractor.py` |
|    89 | `tests/misc/test_arc_mapper.py` |
|   120 | `tests/misc/test_architecture_stats.py` |
|    62 | `tests/misc/test_artifact_semantics.py` |
|   103 | `tests/misc/test_bridge_generator.py` |
|    77 | `tests/misc/test_bridge_mcp_adapter.py` |
|   361 | `tests/misc/test_build_tool.py` |
|    99 | `tests/misc/test_bundle_discovery.py` |
|   336 | `tests/misc/test_bundle_isolation.py` |
|   118 | `tests/misc/test_bundle_manifest.py` |
|   271 | `tests/misc/test_bundle_venv.py` |
|    73 | `tests/misc/test_bundle_workflow.py` |
|   194 | `tests/misc/test_composite_tools.py` |
|   405 | `tests/misc/test_context_providers.py` |
|   314 | `tests/misc/test_cross_domain_orchestration.py` |
|   132 | `tests/misc/test_deferred_imports.py` |
|   243 | `tests/misc/test_eviction.py` |
|   181 | `tests/misc/test_f52_e2e.py` |
|   100 | `tests/misc/test_grouping.py` |
|   178 | `tests/misc/test_import_alias_resolver.py` |
|   345 | `tests/misc/test_live_status.py` |
|   215 | `tests/misc/test_overview_macro_intent.py` |
|    66 | `tests/misc/test_pdf_extraction.py` |
|   377 | `tests/misc/test_porting_workspace.py` |
|    77 | `tests/misc/test_pos_converter_search_tags.py` |
|   616 | `tests/misc/test_pos_converter_task_guide.py` |
|   223 | `tests/misc/test_prefetch.py` |
|   232 | `tests/misc/test_pricing_status_bar.py` |
|   261 | `tests/misc/test_progress_tracker.py` |
|   646 | `tests/misc/test_prompt_assembly.py` |
|   189 | `tests/misc/test_prompt_dump.py` |
|   330 | `tests/misc/test_resource_type_extensibility.py` |
|    62 | `tests/misc/test_sdk_dependency_resolver.py` |
|   395 | `tests/misc/test_sdk_instance_registry.py` |
|   272 | `tests/misc/test_sdk_overview.py` |
|    42 | `tests/misc/test_sdk_serialization.py` |
|   591 | `tests/misc/test_section_registry.py` |
|   199 | `tests/misc/test_sop_agent_runtime.py` |
|    83 | `tests/misc/test_sop_bundle_skills.py` |
|   255 | `tests/misc/test_sop_composite_runtime.py` |
|   381 | `tests/misc/test_sop_converter_agent_catalog.py` |
|   389 | `tests/misc/test_sop_converter_convert_sop_skill.py` |
|   468 | `tests/misc/test_sop_converter_invoke_existing_agent.py` |
|   524 | `tests/misc/test_sop_converter_lifecycle_e2e.py` |
|   297 | `tests/misc/test_sop_converter_lifecycle_prompts.py` |
|   619 | `tests/misc/test_sop_converter_sdk_parser.py` |
| 2,439 | `tests/misc/test_sop_converter_source_parser.py` |
|   415 | `tests/misc/test_sop_converter_tool_dependencies.py` |
| 2,483 | `tests/misc/test_sop_converter_tool_registry_bridge.py` |
|   113 | `tests/misc/test_sop_converter_tool_state.py` |
|   276 | `tests/misc/test_sop_exploration_guard.py` |
|   174 | `tests/misc/test_sop_lazy_tool_loading.py` |
|   180 | `tests/misc/test_sop_macro_convert_phase4.py` |
|   110 | `tests/misc/test_sop_macro_coverage_validation.py` |
|   204 | `tests/misc/test_sop_phase0_fixes.py` |
|   245 | `tests/misc/test_sop_resource_catalog.py` |
|   203 | `tests/misc/test_sop_routing.py` |
|   198 | `tests/misc/test_sop_startup_agent.py` |
|   112 | `tests/misc/test_sop_tool_retrieval_index.py` |
|    59 | `tests/misc/test_sop_workflow_emitter.py` |
|    80 | `tests/misc/test_source_parser_init_params.py` |
|   128 | `tests/misc/test_ssrf_guard.py` |
|   135 | `tests/misc/test_stage_agent_sop_prompt.py` |
|    48 | `tests/misc/test_stage_capability_mapper.py` |
|   201 | `tests/misc/test_startup_profiler.py` |
|   256 | `tests/misc/test_store.py` |
|   233 | `tests/misc/test_swagger_petstore.py` |
|   302 | `tests/misc/test_tool_dependencies.py` |
|   140 | `tests/misc/test_tool_registry_bridge_property.py` |
|   216 | `tests/misc/test_tool_registry_param_order.py` |
|   359 | `tests/misc/test_transcript.py` |
|   104 | `tests/misc/test_treesitter_adapter.py` |
|   387 | `tests/misc/test_type_schema_pydantic.py` |
|   122 | `tests/misc/test_workflow_cli.py` |
|   151 | `tests/misc/test_workflow_discriminator.py` |
|    53 | `tests/misc/test_workflow_extractor.py` |
|   576 | `tests/misc/test_workflow_tool_authoring.py` |
|    13 | `tests/multimodel/conftest.py` |
|   224 | `tests/multimodel/test_aggregators.py` |
|    65 | `tests/multimodel/test_cli_and_runtime.py` |
|    95 | `tests/multimodel/test_display.py` |
|    26 | `tests/multimodel/test_feature_gate.py` |
|   149 | `tests/multimodel/test_router.py` |
|     1 | `tests/parity/__init__.py` |
|   297 | `tests/parity/test_agent_isolation.py` |
|   522 | `tests/parity/test_behavioral_parity_r2.py` |
|   211 | `tests/parity/test_compression_pipeline_parity.py` |
|   333 | `tests/parity/test_concurrency_model.py` |
|   192 | `tests/parity/test_context_parity.py` |
|   288 | `tests/parity/test_e2e_agent_spawn.py` |
|   203 | `tests/parity/test_e2e_edit_flow.py` |
|   733 | `tests/parity/test_e2e_file_read.py` |
|   240 | `tests/parity/test_e2e_multi_tool.py` |
|   192 | `tests/parity/test_error_recovery_flow.py` |
|   250 | `tests/parity/test_message_type_parity.py` |
|    73 | `tests/parity/test_output_styles_parity.py` |
|   238 | `tests/parity/test_permission_flow_parity.py` |
|   167 | `tests/parity/test_query_state_parity.py` |
|   384 | `tests/parity/test_snapshot_parity_r2.py` |
| 1,043 | `tests/parity/test_structural_parity_r2.py` |
|   183 | `tests/parity/test_tool_execution_order.py` |
|   208 | `tests/parity/test_tool_parity.py` |
|     0 | `tests/plugin/__init__.py` |
|   118 | `tests/plugin/test_pluggy_adapter.py` |
|   156 | `tests/plugin/test_plugin_dependency.py` |
|   442 | `tests/plugin/test_plugin_lifecycle_extended.py` |
|   201 | `tests/plugin/test_plugin_loader.py` |
|   455 | `tests/plugin/test_plugin_loader_extended.py` |
|   357 | `tests/plugin/test_plugin_manager.py` |
|   190 | `tests/plugin/test_plugin_marketplace.py` |
|   216 | `tests/plugin/test_plugin_mcp_lsp.py` |
|   206 | `tests/plugin/test_plugin_pyproject_manifest.py` |
|   222 | `tests/plugin/test_plugin_sandbox.py` |
|   103 | `tests/plugin/test_plugin_validator.py` |
|    93 | `tests/plugin/test_plugins_builtin.py` |
|    43 | `tests/proactive/test_proactive_controller.py` |
|    27 | `tests/proactive/test_prompt_assembly_integration.py` |
|    98 | `tests/proactive/test_prompts_and_command.py` |
|    24 | `tests/proactive/test_query_blocking.py` |
|    26 | `tests/proactive/test_repl_integration.py` |
|    31 | `tests/proactive/test_sleep_and_remote.py` |
|    44 | `tests/proactive/test_tick_emitter.py` |
|    20 | `tests/release_smoke/__init__.py` |
|   240 | `tests/release_smoke/test_install_artifacts.py` |
| 1,187 | `tests/remote_api/test_remote_api.py` |
|    21 | `tests/remote_api/test_remote_api_cli.py` |
|   242 | `tests/remote_api/test_stdlib_server.py` |
|     0 | `tests/repl/__init__.py` |
|    58 | `tests/repl/test_im_command_feedback.py` |
|    16 | `tests/repl/test_legacy_repl_module.py` |
| 3,013 | `tests/repl/test_repl.py` |
|   144 | `tests/repl/test_repl_accept_tab.py` |
|    70 | `tests/repl/test_repl_bundled_skill_commands.py` |
|   318 | `tests/repl/test_repl_commands.py` |
|   264 | `tests/repl/test_turn_buffer_cleanup.py` |
|   176 | `tests/runtime/test_entrypoint_tool_context_binding.py` |
|   365 | `tests/runtime/test_permission_runtime.py` |
|    55 | `tests/runtime/test_tool_context_binding.py` |
|     0 | `tests/server/__init__.py` |
|   292 | `tests/server/test_direct_connect_manager.py` |
|   122 | `tests/server/test_direct_connect_session.py` |
|    54 | `tests/server/test_lockfile.py` |
|   243 | `tests/server/test_server_e2e.py` |
|   141 | `tests/server/test_session_index.py` |
|   148 | `tests/server/test_session_manager.py` |
|    70 | `tests/server/test_types.py` |
|    72 | `tests/server/test_url_scheme.py` |
|     1 | `tests/services/chrome/__init__.py` |
|   146 | `tests/services/chrome/test_base.py` |
|   459 | `tests/services/chrome/test_chrome_tools.py` |
|   335 | `tests/services/chrome/test_factory.py` |
|   485 | `tests/services/chrome/test_mcp_impl.py` |
|    93 | `tests/services/chrome/test_models.py` |
|   130 | `tests/services/chrome/test_null_impl.py` |
|   449 | `tests/services/chrome/test_playwright_impl.py` |
|   330 | `tests/services/chrome/test_recording.py` |
|   218 | `tests/services/compact/test_gating.py` |
|    55 | `tests/services/computer_use/test_base.py` |
|    72 | `tests/services/computer_use/test_dry_run.py` |
|   111 | `tests/services/computer_use/test_factory.py` |
|   297 | `tests/services/computer_use/test_linux.py` |
|    73 | `tests/services/computer_use/test_models.py` |
|   109 | `tests/services/computer_use/test_null.py` |
|   219 | `tests/services/context_collapse/test_boundary.py` |
|   454 | `tests/services/context_collapse/test_engine.py` |
|   254 | `tests/services/context_collapse/test_persistence.py` |
|   266 | `tests/services/context_collapse/test_summary.py` |
|   266 | `tests/services/context_collapse/test_tokens.py` |
|   330 | `tests/services/context_collapse/test_trigger.py` |
|   166 | `tests/services/feature_gate/test_facade.py` |
|     9 | `tests/services/kairos/__init__.py` |
|   131 | `tests/services/kairos/test_brief.py` |
|   179 | `tests/services/kairos/test_daily_log.py` |
|   278 | `tests/services/kairos/test_models.py` |
|   166 | `tests/services/kairos/test_periodic.py` |
|   343 | `tests/services/kairos/test_scheduler.py` |
|     1 | `tests/services/langfuse/__init__.py` |
|   257 | `tests/services/langfuse/test_client.py` |
|   242 | `tests/services/langfuse/test_exporter.py` |
|   363 | `tests/services/langfuse/test_sink.py` |
|    93 | `tests/services/monitor/test_controller.py` |
|    43 | `tests/services/monitor/test_stall_guard.py` |
|   114 | `tests/services/monitor/test_text_tail.py` |
|    48 | `tests/services/monitor/test_watch_compat.py` |
|    38 | `tests/services/pipe_ipc/test_codec.py` |
|   103 | `tests/services/pipe_ipc/test_permissions.py` |
|    59 | `tests/services/pipe_ipc/test_pipe_ipc_models.py` |
|    74 | `tests/services/pipe_ipc/test_registry.py` |
|   154 | `tests/services/pipe_ipc/test_uds.py` |
|     0 | `tests/services/skill_search/__init__.py` |
|   367 | `tests/services/skill_search/test_document.py` |
|   712 | `tests/services/skill_search/test_index.py` |
|   455 | `tests/services/skill_search/test_integration.py` |
|   546 | `tests/services/skill_search/test_searcher.py` |
|   419 | `tests/services/skill_search/test_tokenizer.py` |
|    38 | `tests/services/skill_search/test_tool.py` |
|   457 | `tests/services/skill_search/test_watcher.py` |
|   179 | `tests/services/swarm/test_leader_permission_bridge.py` |
|   271 | `tests/services/swarm/test_mailbox.py` |
|   397 | `tests/services/swarm/test_mailbox_poller.py` |
|   110 | `tests/services/swarm/test_team_file.py` |
|    61 | `tests/services/swarm/test_team_membership.py` |
|     0 | `tests/services/templates/__init__.py` |
|   528 | `tests/services/templates/test_bootstrap.py` |
|   350 | `tests/services/templates/test_built_in.py` |
|    56 | `tests/services/templates/test_catalogue.py` |
|   147 | `tests/services/templates/test_discovery.py` |
|    49 | `tests/services/templates/test_generator.py` |
|   303 | `tests/services/templates/test_models.py` |
|   282 | `tests/services/templates/test_persistence.py` |
|   368 | `tests/services/templates/test_registry.py` |
|   101 | `tests/services/templates/test_renderer.py` |
|   224 | `tests/services/templates/test_resolver.py` |
|   308 | `tests/services/templates/test_schema.py` |
|     1 | `tests/services/ultraplan/__init__.py` |
|   303 | `tests/services/ultraplan/test_adjuster.py` |
|   115 | `tests/services/ultraplan/test_controller_run.py` |
|   323 | `tests/services/ultraplan/test_executor.py` |
|    27 | `tests/services/ultraplan/test_executor_hooks.py` |
|    33 | `tests/services/ultraplan/test_feature_gates.py` |
|    34 | `tests/services/ultraplan/test_keyword_detector.py` |
|   116 | `tests/services/ultraplan/test_llm_planner.py` |
|    62 | `tests/services/ultraplan/test_llm_planner_schema.py` |
|   260 | `tests/services/ultraplan/test_models.py` |
|   250 | `tests/services/ultraplan/test_store.py` |
|    70 | `tests/services/ultraplan/test_templates_audit_rainbow.py` |
|   703 | `tests/services/ultraplan/test_verifier.py` |
|    61 | `tests/session_intelligence/test_summary_queue.py` |
|     0 | `tests/sessions/__init__.py` |
|   162 | `tests/sessions/test_session_cost_persistence.py` |
|   163 | `tests/sessions/test_session_memory_compact.py` |
|   260 | `tests/sessions/test_session_memory_compact_full.py` |
|    73 | `tests/sessions/test_session_migration.py` |
|   176 | `tests/sessions/test_session_resume.py` |
|   112 | `tests/sessions/test_session_start.py` |
|   220 | `tests/sessions/test_session_storage.py` |
|    43 | `tests/sessions/test_session_title.py` |
|     0 | `tests/signal_tests/__init__.py` |
|   165 | `tests/signal_tests/test_signal.py` |
|     0 | `tests/snapshot/__init__.py` |
|   274 | `tests/snapshot/test_snapshot_freezing.py` |
|     1 | `tests/sop_converter/__init__.py` |
|   105 | `tests/sop_converter/test_decoupling.py` |
|   114 | `tests/sop_converter/test_skill_grouper_provider_swap.py` |
|   186 | `tests/sop_converter/test_sop_defaults.py` |
|    15 | `tests/stability_gate/__init__.py` |
|    52 | `tests/stability_gate/_config_helper.py` |
|   111 | `tests/stability_gate/_fake_provider.py` |
|    78 | `tests/stability_gate/conftest.py` |
|    55 | `tests/stability_gate/test_stage10_proactive.py` |
|   241 | `tests/stability_gate/test_stage1_imports.py` |
|   133 | `tests/stability_gate/test_stage2_cli.py` |
|   162 | `tests/stability_gate/test_stage3_repl.py` |
|   295 | `tests/stability_gate/test_stage3b_repl_resilience.py` |
|   151 | `tests/stability_gate/test_stage3c_cli_resilience.py` |
|   735 | `tests/stability_gate/test_stage3d_runtime_commands.py` |
|   254 | `tests/stability_gate/test_stage3e_repl_colors.py` |
| 1,363 | `tests/stability_gate/test_stage3f_btw_command.py` |
|   240 | `tests/stability_gate/test_stage3g_bottom_toolbar.py` |
|   640 | `tests/stability_gate/test_stage3h_repl_tui_launch.py` |
| 1,011 | `tests/stability_gate/test_stage4_agent.py` |
| 1,688 | `tests/stability_gate/test_stage5_extensions.py` |
|   378 | `tests/stability_gate/test_stage6_perf.py` |
|   339 | `tests/stability_gate/test_stage7_daemon.py` |
|   204 | `tests/stability_gate/test_stage7_no_root_shadow.py` |
|   426 | `tests/stability_gate/test_stage7_popup_dispatch.py` |
|   276 | `tests/stability_gate/test_stage8_input_flow.py` |
|   194 | `tests/stability_gate/test_stage9_provider_boundary.py` |
|     0 | `tests/state/__init__.py` |
|   223 | `tests/state/test_app_state.py` |
|   305 | `tests/state/test_foreground_promotion.py` |
|   128 | `tests/state/test_graceful_shutdown.py` |
|   376 | `tests/telemetry/telemetry_issue_e2e_simulation.py` |
|   404 | `tests/telemetry/telemetry_issue_push_errors.py` |
|   289 | `tests/telemetry/telemetry_issue_push_real.py` |
|   238 | `tests/telemetry/test_aggregator.py` |
|   452 | `tests/telemetry/test_analytics_bridge.py` |
|   217 | `tests/telemetry/test_cli_subcommand.py` |
|   304 | `tests/telemetry/test_config.py` |
|    98 | `tests/telemetry/test_dry_run_reporter.py` |
|    84 | `tests/telemetry/test_fingerprint.py` |
|    72 | `tests/telemetry/test_hooks.py` |
|   183 | `tests/telemetry/test_issue_reporter.py` |
|   217 | `tests/telemetry/test_migration.py` |
|   297 | `tests/telemetry/test_privacy_audit.py` |
|   385 | `tests/telemetry/test_recorder.py` |
|   168 | `tests/telemetry/test_redaction.py` |
|    82 | `tests/telemetry/test_storage.py` |
|     0 | `tests/token_tests/__init__.py` |
|   118 | `tests/token_tests/test_token_budget.py` |
|   173 | `tests/token_tests/test_token_estimation.py` |
|   344 | `tests/token_tests/test_token_estimation_cache.py` |
|   108 | `tests/token_tests/test_token_estimation_full.py` |
|     1 | `tests/trae/__init__.py` |
|   393 | `tests/trae/test_acp_cli_adapter.py` |
|   108 | `tests/trae/test_acp_protocol.py` |
|   397 | `tests/trae/test_mcp_bridge.py` |
|     0 | `tests/tui/__init__.py` |
|   228 | `tests/tui/test_a11y.py` |
|   339 | `tests/tui/test_agent_bridge_freeze.py` |
|   146 | `tests/tui/test_app_pilot.py` |
|   298 | `tests/tui/test_ask_user_question.py` |
|    78 | `tests/tui/test_assistant_thinking.py` |
|   212 | `tests/tui/test_declared_cursor.py` |
|   228 | `tests/tui/test_downstream_tui_app.py` |
|   275 | `tests/tui/test_exit_snapshot.py` |
|    56 | `tests/tui/test_forecast_display.py` |
|   178 | `tests/tui/test_frame_metrics.py` |
|   381 | `tests/tui/test_goal_binding.py` |
|    40 | `tests/tui/test_goal_status_line.py` |
|    56 | `tests/tui/test_history_store.py` |
|   185 | `tests/tui/test_hyperlinks.py` |
|    76 | `tests/tui/test_keybindings.py` |
|   216 | `tests/tui/test_markdown_cache.py` |
|    74 | `tests/tui/test_no_reserved_overrides.py` |
|   323 | `tests/tui/test_paste_handling.py` |
|   197 | `tests/tui/test_permission_modal_specialization.py` |
|   481 | `tests/tui/test_phase2_dialogs.py` |
|   397 | `tests/tui/test_phase3_dialogs.py` |
|   134 | `tests/tui/test_phase4_polish.py` |
|   181 | `tests/tui/test_prompt_input_footer.py` |
|   209 | `tests/tui/test_prompt_input_mode_indicator.py` |
|   127 | `tests/tui/test_prompt_input_tab.py` |
|   127 | `tests/tui/test_resume_doctor_screens.py` |
|   107 | `tests/tui/test_select_list.py` |
|   124 | `tests/tui/test_session_preview.py` |
|   140 | `tests/tui/test_should_use_tui.py` |
|    49 | `tests/tui/test_slash_token_parser.py` |
|   363 | `tests/tui/test_streaming_markdown.py` |
|   126 | `tests/tui/test_terminal_chrome.py` |
|    44 | `tests/tui/test_theme_auto.py` |
|   109 | `tests/tui/test_tool_result_hyperlinks.py` |
|   308 | `tests/tui/test_transcript.py` |
|   238 | `tests/tui/test_transcript_search.py` |
|   116 | `tests/tui/test_transcript_thinking_transitions.py` |
|   705 | `tests/tui/test_tui_commands.py` |
|    31 | `tests/tui/test_ultraplan_panel.py` |
|    24 | `tests/tui/test_ultraplan_prompt_highlight.py` |
|    85 | `tests/tui/test_vim_find.py` |
|   327 | `tests/tui/test_vim_multiline.py` |
|   423 | `tests/tui/test_vim_persistent.py` |
|   103 | `tests/tui/test_vim_state.py` |
|   444 | `tests/tui/test_vim_transitions.py` |
|   313 | `tests/tui/test_vim_wave2.py` |
|    56 | `tests/upstream_sync/test_patch_generator_portable_diff.py` |
|    34 | `tests/upstream_sync/test_resolve_conflict_markers.py` |
|     0 | `tests/upstreamproxy/__init__.py` |
|   178 | `tests/upstreamproxy/test_ca_bundle.py` |
|   115 | `tests/upstreamproxy/test_protobuf_codec.py` |
|    45 | `tests/upstreamproxy/test_ptrace_guard.py` |
|   174 | `tests/upstreamproxy/test_relay_e2e.py` |
|   280 | `tests/upstreamproxy/test_upstream_proxy.py` |
|   130 | `tests/utils/test_combined_abort_signal.py` |
|    24 | `tests/utils/test_file_lock.py` |
|    89 | `tests/utils/test_key_format.py` |
|   217 | `tests/utils/test_message_mappers.py` |
|   227 | `tests/utils/test_resume_hint.py` |
|    95 | `tests/utils/test_session_ingress_auth.py` |
|    31 | `tests/utils/test_teleport_api.py` |
|     0 | `tests/voice/__init__.py` |
|   977 | `tests/voice/test_dialogue.py` |
|   858 | `tests/voice/test_minimax_live.py` |
|   658 | `tests/voice/test_voice.py` |

### 源码文件大小分布

- 文件数: 205
- 最小: 0 行
- 最大: 897 行
- 平均: 197 行
- 中位数: 149 行
- 最大 3 文件: `ext/away_summary/service.py` (897行), `ext/services/tool_execution/tool_execution.py` (739行), `ext/services/compact/compact.py` (661行)

## #16 编排器

**总源码 43,736 行** | **总测试 34,203 行** | **合计 77,939 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    36 | `extensions/orchestrator/__init__.py` |
| 3,033 | `extensions/orchestrator/agent_runner.py` |
|   168 | `extensions/orchestrator/approval_policy.py` |
|   118 | `extensions/orchestrator/asciicast_sink.py` |
|   120 | `extensions/orchestrator/channel_sink.py` |
|   547 | `extensions/orchestrator/clarification.py` |
|   480 | `extensions/orchestrator/clarification_queue.py` |
|    22 | `extensions/orchestrator/cli/__init__.py` |
|   546 | `extensions/orchestrator/cli/attach.py` |
| 1,598 | `extensions/orchestrator/cli/dashboard.py` |
| 3,269 | `extensions/orchestrator/cli/issue.py` |
|   179 | `extensions/orchestrator/cli/resume_session.py` |
|   600 | `extensions/orchestrator/cli/rules.py` |
| 1,294 | `extensions/orchestrator/cli/server.py` |
|   310 | `extensions/orchestrator/cli/takeover.py` |
|   445 | `extensions/orchestrator/cli/workflow.py` |
|   514 | `extensions/orchestrator/cli/workspace.py` |
|    29 | `extensions/orchestrator/config/__init__.py` |
| 1,297 | `extensions/orchestrator/config/schema.py` |
|   288 | `extensions/orchestrator/control_socket.py` |
|    29 | `extensions/orchestrator/debug_log.py` |
|   343 | `extensions/orchestrator/event_tailer.py` |
|    21 | `extensions/orchestrator/events/__init__.py` |
|   137 | `extensions/orchestrator/events/emitter.py` |
|   146 | `extensions/orchestrator/events/formatter.py` |
|    54 | `extensions/orchestrator/events/types.py` |
|   389 | `extensions/orchestrator/feishu_activity_sink.py` |
| 1,747 | `extensions/orchestrator/git_sync.py` |
|   430 | `extensions/orchestrator/im_gateway_client.py` |
|    52 | `extensions/orchestrator/issue.py` |
|    16 | `extensions/orchestrator/issue_clarifier/__init__.py` |
|    86 | `extensions/orchestrator/issue_clarifier/cache.py` |
|   265 | `extensions/orchestrator/issue_clarifier/gate.py` |
|   104 | `extensions/orchestrator/issue_clarifier/models.py` |
|    91 | `extensions/orchestrator/issue_clarifier/parser.py` |
|   107 | `extensions/orchestrator/issue_clarifier/prompt.py` |
|   166 | `extensions/orchestrator/issue_clarifier/service.py` |
| 1,105 | `extensions/orchestrator/issue_registry.py` |
|   196 | `extensions/orchestrator/issue_state_cache.py` |
|     7 | `extensions/orchestrator/linear/__init__.py` |
|   259 | `extensions/orchestrator/linear/adapter.py` |
|   306 | `extensions/orchestrator/linear/client.py` |
|     7 | `extensions/orchestrator/linear/issue.py` |
|     5 | `extensions/orchestrator/local_tracker/__init__.py` |
|   415 | `extensions/orchestrator/local_tracker/adapter.py` |
|   240 | `extensions/orchestrator/local_tracker/parser.py` |
|   264 | `extensions/orchestrator/logging_setup.py` |
|   384 | `extensions/orchestrator/mode_router.py` |
|   191 | `extensions/orchestrator/mode_selector.py` |
|    65 | `extensions/orchestrator/modes/__init__.py` |
|    84 | `extensions/orchestrator/modes/base.py` |
|    88 | `extensions/orchestrator/modes/coordinator.py` |
|   950 | `extensions/orchestrator/modes/debate.py` |
|   770 | `extensions/orchestrator/modes/pipeline.py` |
|    37 | `extensions/orchestrator/modes/single.py` |
|   299 | `extensions/orchestrator/modes/swarm.py` |
| 4,729 | `extensions/orchestrator/orchestrator.py` |
|   248 | `extensions/orchestrator/premise_check.py` |
|   121 | `extensions/orchestrator/progress_reporter.py` |
|   362 | `extensions/orchestrator/progress_sink.py` |
| 1,079 | `extensions/orchestrator/prompt_builder.py` |
|     5 | `extensions/orchestrator/repo_tracker/__init__.py` |
|   380 | `extensions/orchestrator/repo_tracker/adapter.py` |
| 1,541 | `extensions/orchestrator/repo_tracker/client.py` |
|   232 | `extensions/orchestrator/report_writer.py` |
|   231 | `extensions/orchestrator/repro_gate.py` |
|   165 | `extensions/orchestrator/review_feedback.py` |
|   902 | `extensions/orchestrator/rules_learner.py` |
|   300 | `extensions/orchestrator/session_viewer.py` |
|   195 | `extensions/orchestrator/state_journal.py` |
|    89 | `extensions/orchestrator/state_journal_sink.py` |
|   489 | `extensions/orchestrator/status_dashboard.py` |
|    18 | `extensions/orchestrator/task_decomposition/__init__.py` |
|   104 | `extensions/orchestrator/task_decomposition/models.py` |
|   485 | `extensions/orchestrator/task_decomposition/planner.py` |
|     1 | `extensions/orchestrator/templates/__init__.py` |
|    81 | `extensions/orchestrator/tool_event_log.py` |
|   818 | `extensions/orchestrator/tracker.py` |
|    96 | `extensions/orchestrator/workflow.py` |
|   109 | `extensions/orchestrator/workflow_engine/__init__.py` |
|   284 | `extensions/orchestrator/workflow_engine/audit.py` |
|   333 | `extensions/orchestrator/workflow_engine/checkpoint.py` |
|    98 | `extensions/orchestrator/workflow_engine/cost.py` |
|   181 | `extensions/orchestrator/workflow_engine/decision_handler.py` |
|   754 | `extensions/orchestrator/workflow_engine/engine.py` |
|    60 | `extensions/orchestrator/workflow_engine/errors.py` |
|   149 | `extensions/orchestrator/workflow_engine/event_bus.py` |
|   199 | `extensions/orchestrator/workflow_engine/gate_handler.py` |
|   201 | `extensions/orchestrator/workflow_engine/gate_rollback.py` |
|   294 | `extensions/orchestrator/workflow_engine/observability.py` |
|   340 | `extensions/orchestrator/workflow_engine/rollback.py` |
|   499 | `extensions/orchestrator/workflow_engine/stage_runner.py` |
|   277 | `extensions/orchestrator/workflow_engine/validators/__init__.py` |
|   131 | `extensions/orchestrator/workflow_engine/validators/custom.py` |
|   280 | `extensions/orchestrator/workflow_engine/validators/llm_judge.py` |
|   166 | `extensions/orchestrator/workflow_engine/workflow_state.py` |
|   474 | `extensions/orchestrator/workflow_orchestrator.py` |
|    79 | `extensions/orchestrator/workflow_store.py` |
|   772 | `extensions/orchestrator/workspace.py` |
|   378 | `extensions/orchestrator/workspace_locator.py` |
|   259 | `extensions/orchestrator/workspace_verify.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/orchestrator/__init__.py` |
|   246 | `tests/orchestrator/manual_e2e_f124.py` |
|   518 | `tests/orchestrator/manual_e2e_f38.py` |
|   166 | `tests/orchestrator/test_agent_runner_protocol_injection.py` |
|   326 | `tests/orchestrator/test_checkpoint_recovery.py` |
|   466 | `tests/orchestrator/test_contract_validator.py` |
|   354 | `tests/orchestrator/test_feishu_activity_sink.py` |
|   127 | `tests/orchestrator/test_im_channel_protocol_injection.py` |
| 1,982 | `tests/orchestrator/test_im_events.py` |
|   829 | `tests/orchestrator/test_issue_clarifier.py` |
|   294 | `tests/orchestrator/test_issue_state_cache.py` |
|   190 | `tests/orchestrator/test_layer_isolation.py` |
|   127 | `tests/orchestrator/test_linear_adapter_clarification.py` |
|   148 | `tests/orchestrator/test_local_tracker_parser.py` |
| 1,354 | `tests/orchestrator/test_orchestrator_agent_runner.py` |
|   132 | `tests/orchestrator/test_orchestrator_agent_runner_debug.py` |
|   187 | `tests/orchestrator/test_orchestrator_agent_watchdog.py` |
|   209 | `tests/orchestrator/test_orchestrator_approval_policy.py` |
|   433 | `tests/orchestrator/test_orchestrator_clarification_queue.py` |
|   275 | `tests/orchestrator/test_orchestrator_concurrency.py` |
|   486 | `tests/orchestrator/test_orchestrator_dashboard.py` |
|   178 | `tests/orchestrator/test_orchestrator_dashboard_run.py` |
|   261 | `tests/orchestrator/test_orchestrator_f120_cli.py` |
|   783 | `tests/orchestrator/test_orchestrator_f120_daemon.py` |
|   165 | `tests/orchestrator/test_orchestrator_f120_intent.py` |
|   255 | `tests/orchestrator/test_orchestrator_f120_rebase_service.py` |
|   189 | `tests/orchestrator/test_orchestrator_f120_registry.py` |
|   175 | `tests/orchestrator/test_orchestrator_f120_tracker.py` |
|    67 | `tests/orchestrator/test_orchestrator_f121_rules_isolation.py` |
|   491 | `tests/orchestrator/test_orchestrator_f39_command.py` |
|   346 | `tests/orchestrator/test_orchestrator_f39_followup.py` |
|   398 | `tests/orchestrator/test_orchestrator_f39_intent.py` |
|   472 | `tests/orchestrator/test_orchestrator_f39_ratelimit.py` |
|   700 | `tests/orchestrator/test_orchestrator_f39_retry.py` |
|   715 | `tests/orchestrator/test_orchestrator_f39_retry_cli.py` |
|   181 | `tests/orchestrator/test_orchestrator_f42_sequential.py` |
|   764 | `tests/orchestrator/test_orchestrator_f45_audit_bypass.py` |
|   686 | `tests/orchestrator/test_orchestrator_f49_attach.py` |
|   523 | `tests/orchestrator/test_orchestrator_f49_control_socket.py` |
|   260 | `tests/orchestrator/test_orchestrator_f49_phase02_resume.py` |
|   498 | `tests/orchestrator/test_orchestrator_f49_resume.py` |
|   827 | `tests/orchestrator/test_orchestrator_f49_takeover.py` |
|   419 | `tests/orchestrator/test_orchestrator_f49_transcript.py` |
|   127 | `tests/orchestrator/test_orchestrator_feedback_cli.py` |
|   697 | `tests/orchestrator/test_orchestrator_git_sync.py` |
|   900 | `tests/orchestrator/test_orchestrator_issue_registry.py` |
|   289 | `tests/orchestrator/test_orchestrator_modes.py` |
|   743 | `tests/orchestrator/test_orchestrator_modes_phase2.py` |
| 1,643 | `tests/orchestrator/test_orchestrator_modes_phase3.py` |
|   581 | `tests/orchestrator/test_orchestrator_progress_sink.py` |
| 1,059 | `tests/orchestrator/test_orchestrator_prompt_builder.py` |
|   577 | `tests/orchestrator/test_orchestrator_report_writer.py` |
|   522 | `tests/orchestrator/test_orchestrator_review_feedback.py` |
|   312 | `tests/orchestrator/test_orchestrator_state_journal.py` |
|   149 | `tests/orchestrator/test_orchestrator_status_snapshot.py` |
| 2,413 | `tests/orchestrator/test_orchestrator_trackers.py` |
|   429 | `tests/orchestrator/test_orchestrator_workflow.py` |
|   404 | `tests/orchestrator/test_orchestrator_workspace_hooks.py` |
|   608 | `tests/orchestrator/test_orchestrator_workspace_locator.py` |
|   298 | `tests/orchestrator/test_orchestrator_workspace_repo_clone.py` |
|   235 | `tests/orchestrator/test_premise_check.py` |
|   218 | `tests/orchestrator/test_regression_guard.py` |
|   380 | `tests/orchestrator/test_repo_tracker_label_filters.py` |
|   314 | `tests/orchestrator/test_repro_gate.py` |
|   218 | `tests/orchestrator/test_rules_cli.py` |
| 1,149 | `tests/orchestrator/test_rules_learner.py` |
|   479 | `tests/orchestrator/test_task_decomposition.py` |
|   316 | `tests/orchestrator/test_workflow_engine_integration.py` |
|   309 | `tests/orchestrator/test_workspace_cli.py` |
|   361 | `tests/orchestrator/test_workspace_preserve.py` |
|   271 | `tests/orchestrator/test_workspace_verify.py` |

### 源码文件大小分布

- 文件数: 101
- 最小: 1 行
- 最大: 4,729 行
- 平均: 433 行
- 中位数: 240 行
- 最大 3 文件: `extensions/orchestrator/orchestrator.py` (4729行), `extensions/orchestrator/cli/issue.py` (3269行), `extensions/orchestrator/agent_runner.py` (3033行)

## #17 守护进程与后台

**总源码 2,957 行** | **总测试 2,000 行** | **合计 4,957 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    20 | `extensions/context_providers/__init__.py` |
|    56 | `extensions/context_providers/from_ci.py` |
|   132 | `extensions/context_providers/from_config.py` |
|    68 | `extensions/context_providers/from_issue.py` |
|   118 | `extensions/daemon/__init__.py` |
|   495 | `extensions/daemon/cli.py` |
|   134 | `extensions/daemon/config.py` |
|    83 | `extensions/daemon/constants.py` |
|    66 | `extensions/daemon/errors.py` |
|   448 | `extensions/daemon/lifecycle.py` |
|   254 | `extensions/daemon/state.py` |
|   239 | `extensions/daemon/supervisor.py` |
|    75 | `extensions/daemon/worker_main.py` |
|   118 | `extensions/daemon/worker_registry.py` |
|    44 | `extensions/daemon/workers/__init__.py` |
|   107 | `extensions/daemon/workers/base.py` |
|    60 | `extensions/daemon/workers/cron.py` |
|    44 | `extensions/daemon/workers/remote_control.py` |
|   396 | `extensions/daemon/workers/task_worker.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     0 | `tests/extensions/daemon/__init__.py` |
|    43 | `tests/extensions/daemon/conftest.py` |
|   208 | `tests/extensions/daemon/test_cli.py` |
|    94 | `tests/extensions/daemon/test_config.py` |
|   696 | `tests/extensions/daemon/test_e2e_supervisor.py` |
|   363 | `tests/extensions/daemon/test_lifecycle.py` |
|   168 | `tests/extensions/daemon/test_state.py` |
|   245 | `tests/extensions/daemon/test_supervisor.py` |
|   183 | `tests/extensions/daemon/test_worker_registry.py` |

### 源码文件大小分布

- 文件数: 19
- 最小: 20 行
- 最大: 495 行
- 平均: 155 行
- 中位数: 107 行
- 最大 3 文件: `extensions/daemon/cli.py` (495行), `extensions/daemon/lifecycle.py` (448行), `extensions/daemon/workers/task_worker.py` (396行)

## #18 层间契约

**总源码 2,428 行** | **总测试 177 行** | **合计 2,605 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|    77 | `ext/capabilities/__init__.py` |
|    68 | `ext/capabilities/multimodel_protocol.py` |
|    83 | `extensions/capabilities/__init__.py` |
|   190 | `extensions/capabilities/acp_protocol.py` |
|   198 | `extensions/capabilities/adapter_protocol.py` |
|   120 | `extensions/capabilities/agent_definition_protocol.py` |
|    60 | `extensions/capabilities/agent_protocol.py` |
|    66 | `extensions/capabilities/automation_state_protocol.py` |
|    29 | `extensions/capabilities/context_protocol.py` |
|    77 | `extensions/capabilities/daemon_protocol.py` |
|   221 | `extensions/capabilities/dashboard_entry.py` |
|    50 | `extensions/capabilities/event_protocol.py` |
|    96 | `extensions/capabilities/headless_protocol.py` |
|   187 | `extensions/capabilities/headless_runner.py` |
|    54 | `extensions/capabilities/permission_protocol.py` |
|    39 | `extensions/capabilities/provider_protocol.py` |
|   155 | `extensions/capabilities/recorder.py` |
|   102 | `extensions/capabilities/skill_protocol.py` |
|    46 | `extensions/capabilities/sop_provider_protocol.py` |
|   183 | `extensions/capabilities/task_protocol.py` |
|   119 | `extensions/capabilities/team_memory_protocol.py` |
|   113 | `extensions/capabilities/tool_authoring_protocol.py` |
|    95 | `extensions/capabilities/tool_protocol.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|   177 | `tests/extensions/capabilities/test_dashboard_entry.py` |

### 源码文件大小分布

- 文件数: 23
- 最小: 29 行
- 最大: 221 行
- 平均: 105 行
- 中位数: 95 行
- 最大 3 文件: `extensions/capabilities/dashboard_entry.py` (221行), `extensions/capabilities/adapter_protocol.py` (198行), `extensions/capabilities/acp_protocol.py` (190行)

## #19 逻辑知识库 (LKB)

**总源码 20,113 行** | **总测试 19,367 行** | **合计 39,480 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   112 | `extensions/lkb/cli/main.py` |
|   219 | `extensions/lkb/mcp/server.py` |
|     1 | `extensions/lkb/mcp/tools/__init__.py` |
|    23 | `extensions/lkb/mcp/tools/audit.py` |
|    15 | `extensions/lkb/mcp/tools/decompose.py` |
|    11 | `extensions/lkb/mcp/tools/explain.py` |
|    14 | `extensions/lkb/mcp/tools/validate.py` |
|   579 | `extensions/lkb/src/lkb/__init__.py` |
|   356 | `extensions/lkb/src/lkb/acceptance_template.py` |
|   292 | `extensions/lkb/src/lkb/acceptance_template_governance.py` |
|   148 | `extensions/lkb/src/lkb/acceptance_template_prompt.py` |
|   122 | `extensions/lkb/src/lkb/acceptance_template_seed.py` |
|   183 | `extensions/lkb/src/lkb/adapters.py` |
|   341 | `extensions/lkb/src/lkb/ambiguity_detector.py` |
|    21 | `extensions/lkb/src/lkb/atp/__init__.py` |
|   269 | `extensions/lkb/src/lkb/atp/base.py` |
|    19 | `extensions/lkb/src/lkb/atp/mace4.py` |
|    10 | `extensions/lkb/src/lkb/atp/prover9.py` |
|    10 | `extensions/lkb/src/lkb/atp/vampire.py` |
|   805 | `extensions/lkb/src/lkb/audit.py` |
|   610 | `extensions/lkb/src/lkb/causal.py` |
|   219 | `extensions/lkb/src/lkb/commit_gate_fuzzy.py` |
|   499 | `extensions/lkb/src/lkb/context_adapter.py` |
| 1,149 | `extensions/lkb/src/lkb/decomposer.py` |
|   255 | `extensions/lkb/src/lkb/explain.py` |
|   446 | `extensions/lkb/src/lkb/external_config.py` |
|   307 | `extensions/lkb/src/lkb/external_config_lint.py` |
|    82 | `extensions/lkb/src/lkb/flags.py` |
|   295 | `extensions/lkb/src/lkb/fuzzy_patterns.py` |
|   290 | `extensions/lkb/src/lkb/fuzzy_types.py` |
|   110 | `extensions/lkb/src/lkb/glossary.py` |
|   149 | `extensions/lkb/src/lkb/ir.py` |
|    38 | `extensions/lkb/src/lkb/ir_hash.py` |
|   105 | `extensions/lkb/src/lkb/ir_renderer.py` |
|   265 | `extensions/lkb/src/lkb/llm_fact_extractor.py` |
|   206 | `extensions/lkb/src/lkb/method_coverage.py` |
|   406 | `extensions/lkb/src/lkb/method_governance.py` |
|   757 | `extensions/lkb/src/lkb/method_library.py` |
|   333 | `extensions/lkb/src/lkb/method_prompt.py` |
|   193 | `extensions/lkb/src/lkb/method_proposer.py` |
| 1,401 | `extensions/lkb/src/lkb/method_seed.py` |
|   218 | `extensions/lkb/src/lkb/metrics.py` |
|    89 | `extensions/lkb/src/lkb/multiworld_validator.py` |
|   143 | `extensions/lkb/src/lkb/ontology_graph.py` |
|   155 | `extensions/lkb/src/lkb/operation_schema.py` |
|   183 | `extensions/lkb/src/lkb/orchestrator.py` |
|    66 | `extensions/lkb/src/lkb/predicate_extractor.py` |
|   747 | `extensions/lkb/src/lkb/rule_engine.py` |
|    45 | `extensions/lkb/src/lkb/runtime.py` |
|   766 | `extensions/lkb/src/lkb/scheduling_solver.py` |
| 2,081 | `extensions/lkb/src/lkb/service.py` |
| 1,925 | `extensions/lkb/src/lkb/solver_adapter.py` |
|   659 | `extensions/lkb/src/lkb/solver_atp.py` |
|   194 | `extensions/lkb/src/lkb/solver_limits.py` |
|   284 | `extensions/lkb/src/lkb/solver_pipeline.py` |
|   408 | `extensions/lkb/src/lkb/truth_maintenance.py` |
|   274 | `extensions/lkb/src/lkb/types.py` |
|   211 | `extensions/lkb/src/lkb/world_generator.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     1 | `extensions/lkb/tests/__init__.py` |
|   444 | `extensions/lkb/tests/test_audit.py` |
|   216 | `extensions/lkb/tests/test_f142_external_atp.py` |
|    83 | `extensions/lkb/tests/test_f151_eval_harness.py` |
|   692 | `extensions/lkb/tests/test_f153_method_governance.py` |
|   762 | `extensions/lkb/tests/test_f154_external_config.py` |
|   315 | `extensions/lkb/tests/test_f155_acceptance_template.py` |
|   452 | `extensions/lkb/tests/test_fuzzy_multiworld.py` |
|   256 | `extensions/lkb/tests/test_rule_engine_layer1.py` |
|   449 | `extensions/lkb/tests/test_solver_layer.py` |
|   666 | `extensions/lkb/tests/test_solver_layer_atp.py` |
|   422 | `extensions/lkb/tests/test_solver_layer_clingo.py` |
|   605 | `extensions/lkb/tests/test_solver_layer_datalog.py` |
|   389 | `extensions/lkb/tests/test_solver_layer_z3.py` |
|   288 | `extensions/lkb/tests/test_truth_maintenance.py` |
|   215 | `extensions/lkb/tests/test_validation_runs.py` |
|   245 | `tests/clawcodex_ext/logical_kanban/test_canonical_ir_glossary.py` |
|   422 | `tests/logical_kanban/eval_f151.py` |
|   503 | `tests/logical_kanban/test_agent_loop_foundation.py` |
|   435 | `tests/logical_kanban/test_audit.py` |
|   913 | `tests/logical_kanban/test_causal_layer.py` |
|   332 | `tests/logical_kanban/test_explain_repair_ui.py` |
|   452 | `tests/logical_kanban/test_f139_security_perf_obs.py` |
|   216 | `tests/logical_kanban/test_f142_external_atp.py` |
|   447 | `tests/logical_kanban/test_f143_llm_facts.py` |
|   394 | `tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py` |
|   379 | `tests/logical_kanban/test_f149_task_decomposition.py` |
|   844 | `tests/logical_kanban/test_f150_method_library.py` |
|    83 | `tests/logical_kanban/test_f151_eval_harness.py` |
|   678 | `tests/logical_kanban/test_f151_method_reuse.py` |
|   974 | `tests/logical_kanban/test_f152_scheduling_solver.py` |
|   692 | `tests/logical_kanban/test_f153_method_governance.py` |
|   762 | `tests/logical_kanban/test_f154_external_config.py` |
|   315 | `tests/logical_kanban/test_f155_acceptance_template.py` |
|   449 | `tests/logical_kanban/test_fuzzy_multiworld.py` |
|   332 | `tests/logical_kanban/test_orchestrator_adoption.py` |
|   253 | `tests/logical_kanban/test_rule_engine_layer1.py` |
|   435 | `tests/logical_kanban/test_solver_layer.py` |
|   666 | `tests/logical_kanban/test_solver_layer_atp.py` |
|   422 | `tests/logical_kanban/test_solver_layer_clingo.py` |
|   605 | `tests/logical_kanban/test_solver_layer_datalog.py` |
|   389 | `tests/logical_kanban/test_solver_layer_z3.py` |
|   274 | `tests/logical_kanban/test_truth_maintenance.py` |
|   201 | `tests/logical_kanban/test_validation_runs.py` |

### 源码文件大小分布

- 文件数: 58
- 最小: 1 行
- 最大: 2,081 行
- 平均: 346 行
- 中位数: 219 行
- 最大 3 文件: `extensions/lkb/src/lkb/service.py` (2081行), `extensions/lkb/src/lkb/solver_adapter.py` (1925行), `extensions/lkb/src/lkb/method_seed.py` (1401行)

## #20 仪表盘与团队可视性

**总源码 4,041 行** | **总测试 5,080 行** | **合计 9,121 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   101 | `extensions/agent_dashboard/__init__.py` |
|   123 | `extensions/agent_dashboard/source_registry.py` |
|    24 | `extensions/agent_dashboard/sources/__init__.py` |
|   221 | `extensions/agent_dashboard/sources/goal_source.py` |
|   242 | `extensions/agent_dashboard/sources/orchestrator_source.py` |
|    71 | `extensions/agent_dashboard/sources/sop_source.py` |
|   188 | `extensions/agent_dashboard/sources/tasks_source.py` |
|   387 | `extensions/agent_dashboard/store.py` |
|    28 | `extensions/agent_dashboard/tools/__init__.py` |
|   138 | `extensions/agent_dashboard/tools/dashboard_get.py` |
|   142 | `extensions/agent_dashboard/tools/dashboard_list.py` |
|    59 | `extensions/agents/__init__.py` |
|   980 | `extensions/agents/team_memory.py` |
|   222 | `extensions/agents/team_memory_integration.py` |
|   147 | `extensions/agents/team_memory_policy.py` |
|    25 | `extensions/api/__init__.py` |
|    29 | `extensions/api/debug_log.py` |
|   152 | `extensions/api/orchestration.py` |
|   659 | `extensions/api/query.py` |
|   103 | `extensions/api/query_middleware.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|     3 | `tests/extensions/agent_dashboard/__init__.py` |
|   207 | `tests/extensions/agent_dashboard/test_orchestrator_source.py` |
|    74 | `tests/extensions/agent_dashboard/test_sop_source.py` |
|   306 | `tests/extensions/agent_dashboard/test_sources.py` |
|   331 | `tests/extensions/agent_dashboard/test_store.py` |
|   227 | `tests/extensions/agent_dashboard/test_tools.py` |
|     0 | `tests/extensions/agents/__init__.py` |
|   185 | `tests/extensions/agents/test_team_memory_index.py` |
|   178 | `tests/extensions/agents/test_team_memory_integration.py` |
|   107 | `tests/extensions/agents/test_team_memory_policy.py` |
|   131 | `tests/extensions/agents/test_team_memory_store.py` |
|     1 | `tests/test_visualizer/__init__.py` |
|   236 | `tests/test_visualizer/test_agent_tree_layout.py` |
|   148 | `tests/test_visualizer/test_operation_categorizer.py` |
|    92 | `tests/test_visualizer/test_orchestrator_link.py` |
| 1,131 | `tests/test_visualizer/test_parsers.py` |
|   920 | `tests/test_visualizer/test_server.py` |
|   299 | `tests/test_visualizer/test_session_lane_adapter.py` |
|   334 | `tests/test_visualizer/test_ws_bar_update.py` |
|   170 | `tests/visualizer/test_dashboard_routes.py` |

### 源码文件大小分布

- 文件数: 20
- 最小: 24 行
- 最大: 980 行
- 平均: 202 行
- 中位数: 142 行
- 最大 3 文件: `extensions/agents/team_memory.py` (980行), `extensions/api/query.py` (659行), `extensions/agent_dashboard/store.py` (387行)

## #21 scripts/ci

**总源码 3,516 行** | **总测试 888 行** | **合计 4,404 行**

### 源文件

| 行数 | 文件路径 |
|-----:|---------|
|   145 | `scripts/ci/bump_version.py` |
|   111 | `scripts/ci/dev_setup.py` |
|   217 | `scripts/ci/docs_check.py` |
|    82 | `scripts/ci/env_loader.py` |
|   218 | `scripts/ci/gitcode_release.py` |
|   987 | `scripts/ci/local_ci.py` |
|   922 | `scripts/ci/local_publish.py` |
|   286 | `scripts/ci/preflight.py` |
|   180 | `scripts/ci/pytest_targets.py` |
|   368 | `scripts/ci/supply_chain_audit.py` |

### 测试文件

| 行数 | 文件路径 |
|-----:|---------|
|    26 | `tests/ci/test_docs_check.py` |
|    69 | `tests/ci/test_gitcode_release.py` |
|   466 | `tests/ci/test_local_ci.py` |
|   262 | `tests/ci/test_local_publish.py` |
|    65 | `tests/ci/test_pytest_targets.py` |

### 源码文件大小分布

- 文件数: 10
- 最小: 82 行
- 最大: 987 行
- 平均: 351 行
- 中位数: 218 行
- 最大 3 文件: `scripts/ci/local_ci.py` (987行), `scripts/ci/local_publish.py` (922行), `scripts/ci/supply_chain_audit.py` (368行)

---
# 三、附录

## A. 文件系统映射说明

| 前缀 | 对应层 |
|------|-------|
| `ext/` | `clawcodex_ext/` (Layer 1 下游补丁层) |
| `extensions/` | `extensions/` (Layer 2 三方扩展层) |
| `tests/` | `tests/` 测试目录 |

## B. 特性分组原则

| 原则 | 说明 |
|------|------|
| 逻辑职责优先 | 按功能领域而非目录边界分组 |
| 上下游分离 | `clawcodex_ext/` 对上游的扩展 vs `extensions/` 全新子系统 |
| 测试跟随特性 | 测试目录按其测试内容归入对应特性 |
| 通用测试归入 #15 | `tests/misc/`、`tests/stability_gate/` 等覆盖多特性的通用测试归入基础设施服务 |

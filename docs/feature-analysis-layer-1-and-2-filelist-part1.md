# 特性群分析：clawcodex_ext 与 extensions — 详细文件清单（clawcodex_ext）

> 生成日期：2026-07-25
> 附属于 `docs/feature-analysis-layer-1-and-2.md`
> 统计口径：`.py` 文件，排除 `__pycache__`、`.egg-info`。
> `▲` = 无 `src/` 镜像但合理驻留的包。`*` = services 含 25+ 子服务。

## clawcodex_ext/ 文件清单

### 【G1】🧠 Agent 运行时生态

**`agent/`**（51 files, 11,003 lines）
```
  agent/__init__.py
  agent/_bundled_agents/__init__.py
  agent/_bundled_agents/code_reviewer.py
  agent/_bundled_agents/docs_writer.py
  agent/_bundled_agents/test_runner.py
  agent/_outlines_adapter.py
  agent/agent_definitions.py
  agent/agent_tool_utils.py
  agent/auto_mode_runner.py
  agent/background_runner.py
  agent/background_state.py
  agent/chain_filter.py
  agent/constants.py
  agent/conversation.py
  agent/filter_agents_by_mcp.py
  agent/foreground_promotion.py
  agent/fork_subagent.py
  agent/forked_agent.py
  agent/load_agents_dir.py
  agent/load_plugin_agents.py
  agent/markdown_discovery.py
  agent/parse_agent_markdown.py
  agent/policy.py
  agent/prompt.py
  agent/read_file_seed.py
  agent/registry.py
  agent/report_store.py
  agent/resume_agent.py
  agent/resume_checks.py
  agent/routing.py
  agent/run_agent.py
  agent/sdk_context_registry.py
  agent/sdk_instance_registry.py
  agent/session.py
  agent/session_ext.py
  agent/side_question.py
  agent/sidechain_transcript.py
  agent/subagent_context.py
  agent/tool_authoring/__init__.py
  agent/tool_authoring/call_handlers/__init__.py
  agent/tool_authoring/call_handlers/bash.py
  agent/tool_authoring/call_handlers/http.py
  agent/tool_authoring/call_handlers/python.py
  agent/tool_authoring/call_handlers/sdk_wrapper.py
  agent/tool_authoring/factory.py
  agent/tool_authoring/persistence.py
  agent/tool_authoring/registry_ext.py
  agent/tool_authoring/spec.py
  agent/tool_authoring/validators.py
  agent/transcript.py
  agent/verification.py
```

**`assistant/`**（2 files, 265 lines）
```
  assistant/session_chooser.py
  assistant/session_history.py
```

**`tasks/`**（9 files, 1,985 lines）
```
  tasks/__init__.py
  tasks/bg_session.py
  tasks/bg_session_health.py
  tasks/bg_session_hook.py
  tasks/bg_session_manager.py
  tasks/bg_session_registry.py
  tasks/dream/__init__.py
  tasks/dream/dream_task.py
  tasks/progress.py
```

**`skills/`**（31 files, 11,797 lines）
```
  skills/__init__.py
  skills/_frontmatter_adapter.py
  skills/argument_substitution.py
  skills/bundled/__init__.py
  skills/bundled/batch.py
  skills/bundled/debug.py
  skills/bundled/loop.py
  skills/bundled/orchestrator.py
  skills/bundled/orchestrator_resources/__init__.py
  skills/bundled/remember.py
  skills/bundled/resource_loader.py
  skills/bundled/simplify.py
  skills/bundled/spec_audit.py
  skills/bundled/spec_audit_resources/__init__.py
  skills/bundled/spec_audit_resources/scripts/inventory.py
  skills/bundled/spec_audit_resources/scripts/lint_report.py
  skills/bundled/spec_audit_resources/scripts/prepare_audit.py
  skills/bundled/stuck.py
  skills/bundled/update_config.py
  skills/bundled/verify.py
  skills/bundled/verify_content.py
  skills/bundled_skills.py
  skills/catalog.py
  skills/create.py
  skills/frontmatter.py
  skills/invocation.py
  skills/loader.py
  skills/mcp_skill_builders.py
  skills/model.py
  skills/runtime_substitution.py
  skills/visibility.py
```

**`hooks/`**（15 files, 3,651 lines）
```
  hooks/__init__.py
  hooks/_pluggy_adapter.py
  hooks/config_manager.py
  hooks/exec_agent_hook.py
  hooks/exec_http_hook.py
  hooks/exec_prompt_hook.py
  hooks/hook_executor.py
  hooks/hook_types.py
  hooks/output_schema.py
  hooks/post_sampling_hooks.py
  hooks/registry.py
  hooks/session_hooks.py
  hooks/shell_invocation.py
  hooks/ssrf_guard.py
  hooks/trust_gate.py
```

**`types/`**（4 files, 1,381 lines）
```
  types/__init__.py
  types/content_blocks.py
  types/messages.py
  types/stream_events.py
```

**`away_summary/`** ▲（10 files, 1,910 lines）
```
  away_summary/__init__.py
  away_summary/command.py
  away_summary/config.py
  away_summary/controller.py
  away_summary/fingerprint.py
  away_summary/memory.py
  away_summary/messages.py
  away_summary/prompt.py
  away_summary/registration.py
  away_summary/service.py
```

**`goal/`** ▲（14 files, 4,366 lines）
```
  goal/__init__.py
  goal/accounting.py
  goal/command.py
  goal/evaluator.py
  goal/files.py
  goal/gate.py
  goal/model.py
  goal/observability.py
  goal/protocol.py
  goal/runtime.py
  goal/service.py
  goal/steering.py
  goal/store.py
  goal/tools.py
```

**`dreaming/`** ▲（8 files, 1,837 lines）
```
  dreaming/__init__.py
  dreaming/config.py
  dreaming/cron_integration.py
  dreaming/lock.py
  dreaming/paths.py
  dreaming/prompt.py
  dreaming/runner.py
  dreaming/service.py
```

---

### 【G2】🖥️ 用户界面层

**`cli/`**（39 files, 9,251 lines）
```
  cli/__init__.py
  cli/_interactive.py
  cli/auth_cmd.py
  cli/channels_cmd/__init__.py
  cli/channels_cmd/commands.py
  cli/diag_cmd.py
  cli/dispatch.py
  cli/gateway_cmd/__init__.py
  cli/gateway_cmd/commands.py
  cli/lkb_method_cmd/__init__.py
  cli/lkb_method_cmd/commands.py
  cli/main.py
  cli/model_cmd/__init__.py
  cli/model_cmd/commands.py
  cli/model_cmd/errors.py
  cli/model_cmd/registry.py
  cli/model_cmd/resolver.py
  cli/model_cmd/store.py
  cli/parser.py
  cli/permissions.py
  cli/provider_cmd/__init__.py
  cli/provider_cmd/commands.py
  cli/provider_cmd/errors.py
  cli/runners.py
  cli/runtime_commands.py
  cli/session_migrate_cmd.py
  cli/sop_cmd/__init__.py
  cli/sop_cmd/commands.py
  cli/stats_cmd.py
  cli/subcommand_registry.py
  cli/telemetry_cmd.py
  cli/tool_cmd/__init__.py
  cli/tool_cmd/command.py
  cli/tool_cmd/core_filter.py
  cli/tool_cmd/discovery.py
  cli/tool_cmd/hooks.py
  cli/tool_cmd/runtime.py
  cli/tool_cmd/schema_parser.py
  cli/worktree.py
```

**`cli_core/`**（4 files, 268 lines）
```
  cli_core/__init__.py
  cli_core/exit.py
  cli_core/ndjson.py
  cli_core/structured_io.py
```

**`command_system/`**（34 files, 10,718 lines）
```
  command_system/__init__.py
  command_system/aggregator.py
  command_system/argument_substitution.py
  command_system/bg_commands.py
  command_system/btw_command.py
  command_system/btw_stats.py
  command_system/buddy_command.py
  command_system/builtins.py
  command_system/dashboard_command.py
  command_system/dialogue_command.py
  command_system/effort_command.py
  command_system/engine.py
  command_system/export_command.py
  command_system/input_processing.py
  command_system/lkb_command.py
  command_system/lodestone_commands.py
  command_system/model_command.py
  command_system/monitor_command.py
  command_system/moved_to_plugin.py
  command_system/output_style_command.py
  command_system/proactive_command.py
  command_system/registry.py
  command_system/safe_commands.py
  command_system/security_review.py
  command_system/shell_prompt.py
  command_system/skills_integration.py
  command_system/statusline.py
  command_system/team_memory_commands.py
  command_system/template_commands.py
  command_system/theme_command.py
  command_system/tts_command.py
  command_system/types.py
  command_system/ultraplan_command.py
  command_system/voice_command.py
```

**`tui/`**（95 files, 19,330 lines）
```
  tui/__init__.py
  tui/a11y.py
  tui/agent_bridge.py
  tui/app.py
  tui/commands.py
  tui/declared_cursor.py
  tui/entrypoint.py
  tui/focus_router.py
  tui/frame_metrics.py
  tui/history_store.py
  tui/hyperlinks.py
  tui/keybindings.py
  tui/markdown_cache.py
  tui/messages.py
  tui/paste.py
  tui/rainbow_highlight.py
  tui/screens/__init__.py
  tui/screens/ask_user_question.py
  tui/screens/cost_threshold.py
  tui/screens/dialog_base.py
  tui/screens/diff_dialog.py
  tui/screens/doctor.py
  tui/screens/effort_picker.py
  tui/screens/exit_flow.py
  tui/screens/forecast_picker.py
  tui/screens/generic_input.py
  tui/screens/generic_select.py
  tui/screens/goal_status.py
  tui/screens/history_search.py
  tui/screens/idle_return.py
  tui/screens/mcp_dialogs.py
  tui/screens/message_selector.py
  tui/screens/model_picker.py
  tui/screens/monitor_panel.py
  tui/screens/permission_modal.py
  tui/screens/permission_mode_picker.py
  tui/screens/repl.py
  tui/screens/resume_conversation.py
  tui/screens/theme_picker.py
  tui/screens/ultraplan_panel.py
  tui/state.py
  tui/template_picker.py
  tui/terminal_chrome.py
  tui/theme.py
  tui/ui_host.py
  tui/vim.py
  tui/vim_buffer.py
  tui/vim_find.py
  tui/vim_operators.py
  tui/vim_persistent.py
  tui/vim_search.py
  tui/vim_state.py
  tui/vim_text_objects.py
  tui/vim_visual.py
  tui/widgets/__init__.py
  tui/widgets/fullscreen_layout.py
  tui/widgets/header.py
  tui/widgets/lkb_proof.py
  tui/widgets/messages/__init__.py
  tui/widgets/messages/assistant_advisor.py
  tui/widgets/messages/assistant_text.py
  tui/widgets/messages/assistant_thinking.py
  tui/widgets/messages/assistant_tool_use.py
  tui/widgets/messages/base.py
  tui/widgets/messages/tool_result.py
  tui/widgets/messages/user_text.py
  tui/widgets/multimodel/__init__.py
  tui/widgets/multimodel/diff_panel.py
  tui/widgets/multimodel/live_panel.py
  tui/widgets/multimodel/progress_bar.py
  tui/widgets/multimodel/result_card.py
  tui/widgets/multimodel/selection_list.py
  tui/widgets/multimodel/summary_panel.py
  tui/widgets/multimodel/tab_bar.py
  tui/widgets/multimodel/tab_panel.py
  tui/widgets/prompt_input.py
  tui/widgets/prompt_input_footer.py
  tui/widgets/prompt_input_mode_indicator.py
  tui/widgets/select_list.py
  tui/widgets/session_preview.py
  tui/widgets/status_line.py
  tui/widgets/structured_diff.py
  tui/widgets/task_list.py
  tui/widgets/tool_activity/__init__.py
  tui/widgets/tool_activity/base.py
  tui/widgets/tool_activity/bash.py
  tui/widgets/tool_activity/default.py
  tui/widgets/tool_activity/edit.py
  tui/widgets/tool_activity/glob.py
  tui/widgets/tool_activity/grep.py
  tui/widgets/tool_activity/read.py
  tui/widgets/tool_activity/task.py
  tui/widgets/tool_activity/write.py
  tui/widgets/transcript_search.py
  tui/widgets/transcript_view.py
```

**`frontend/`**（9 files, 1,844 lines）
```
  frontend/__init__.py
  frontend/headless.py
  frontend/protocol.py
  frontend/registry.py
  frontend/repl.py
  frontend/repl_extensions.py
  frontend/repl_gateway.py
  frontend/tui.py
  frontend/tui_extensions.py
```

**`entrypoints/`**（4 files, 3,108 lines）
```
  entrypoints/__init__.py
  entrypoints/headless.py
  entrypoints/orchestrator.py
  entrypoints/tui.py
```

**`repl/`**（11 files, 10,043 lines）
```
  repl/__init__.py
  repl/app.py
  repl/background_escape.py
  repl/bg_sessions_panel.py
  repl/color_scheme.py
  repl/core.py
  repl/live_status.py
  repl/mentioned_agent.py
  repl/proactive_integration.py
  repl/session_browser.py
  repl/ui_host.py
```

**`runtime/`** ▲（4 files, 651 lines）
```
  runtime/__init__.py
  runtime/context.py
  runtime/observer.py
  runtime/tool_context_binding.py
```

---

### 【G3】🔗 桥接与通信

**`bridge/`**（30 files, 6,388 lines）
```
  bridge/__init__.py
  bridge/bounded_uuid_set.py
  bridge/bridge_api.py
  bridge/bridge_config.py
  bridge/bridge_enabled.py
  bridge/bridge_permission_callbacks.py
  bridge/bridge_pointer.py
  bridge/bridge_status_util.py
  bridge/capacity_wake.py
  bridge/close_codes.py
  bridge/code_session_api.py
  bridge/debug_utils.py
  bridge/env_less_bridge_config.py
  bridge/exceptions.py
  bridge/flush_gate.py
  bridge/inbound_attachments.py
  bridge/inbound_messages.py
  bridge/init_repl_bridge.py
  bridge/jwt_utils.py
  bridge/messaging.py
  bridge/messaging_handlers.py
  bridge/no_proxy.py
  bridge/poll_config.py
  bridge/poll_config_defaults.py
  bridge/repl_bridge_handle.py
  bridge/repl_bridge_transport.py
  bridge/session_id_compat.py
  bridge/types.py
  bridge/work_secret.py
  bridge/worktree.py
```

**`messaging/`**（6 files, 384 lines）
```
  messaging/__init__.py
  messaging/semantics/__init__.py
  messaging/semantics/classifier.py
  messaging/semantics/command_router.py
  messaging/semantics/control_bridge.py
  messaging/semantics/runtime_router.py
```

**`transports/`**（7 files, 1,283 lines）
```
  transports/ccr_client.py
  transports/remote_io.py
  transports/serial_batch_event_uploader.py
  transports/sse_transport.py
  transports/transport_utils.py
  transports/websocket_transport.py
  transports/worker_state_uploader.py
```

**`remote/`**（3 files, 750 lines）
```
  remote/__init__.py
  remote/remote_session_manager.py
  remote/sessions_websocket.py
```

---

### 【G4】🔐 认证、权限与安全

**`auth/`**（8 files, 1,551 lines）
```
  auth/__init__.py
  auth/auth.py
  auth/aws.py
  auth/claude_ai.py
  auth/codex_oauth.py
  auth/codex_store.py
  auth/gemini.py
  auth/oauth.py
```

**`permissions/`**（26 files, 7,742 lines）
```
  permissions/__init__.py
  permissions/_treesitter_adapter.py
  permissions/bash_parser/__init__.py
  permissions/bash_parser/ast_nodes.py
  permissions/bash_parser/commands.py
  permissions/bash_parser/parser.py
  permissions/bash_parser/shell_quote.py
  permissions/bash_security.py
  permissions/bash_suggestions.py
  permissions/check.py
  permissions/classifier.py
  permissions/cycle.py
  permissions/danger_detector.py
  permissions/dangerous_safety.py
  permissions/filesystem.py
  permissions/handler.py
  permissions/loader.py
  permissions/modes.py
  permissions/powershell_security.py
  permissions/rule_parser.py
  permissions/rules.py
  permissions/runtime.py
  permissions/setup.py
  permissions/trust_boundary.py
  permissions/types.py
  permissions/updates.py
```

**`feature_gate/`** ▲（6 files, 1,172 lines）
```
  feature_gate/__init__.py
  feature_gate/cli.py
  feature_gate/config.py
  feature_gate/decorators.py
  feature_gate/registry.py
  feature_gate/types.py
```

**`diagnostics/`** ▲（4 files, 928 lines）
```
  diagnostics/__init__.py
  diagnostics/freeze_config.py
  diagnostics/freeze_detector.py
  diagnostics/recovery.py
```

---

### 【G5】📚 上下文、记忆与知识

**`context_system/`**（16 files, 5,018 lines）
```
  context_system/__init__.py
  context_system/_gitpython_adapter.py
  context_system/builder.py
  context_system/cache_boundary.py
  context_system/claude_md.py
  context_system/clawcodex_md.py
  context_system/context_analyzer.py
  context_system/git_context.py
  context_system/memory_prefetch.py
  context_system/microcompact.py
  context_system/models.py
  context_system/prompt_assembly.py
  context_system/prompt_dump.py
  context_system/section_registry.py
  context_system/system_prompt_cache.py
  context_system/workspace_snapshot.py
```

**`memory/`**（2 files, 132 lines）
```
  memory/__init__.py
  memory/scope_aware_prompt.py
```

**`memdir/`**（9 files, 2,038 lines）
```
  memdir/__init__.py
  memdir/find_relevant_memories.py
  memdir/memdir.py
  memdir/memory_age.py
  memdir/memory_scan.py
  memdir/memory_types.py
  memdir/paths.py
  memdir/team_mem_paths.py
  memdir/team_mem_prompts.py
```

**`constants/`**（1 file, 64 lines）
```
  constants/xml.py
```

**`intent_forecast/`** ▲（17 files, 3,178 lines）
```
  intent_forecast/__init__.py
  intent_forecast/cli.py
  intent_forecast/command.py
  intent_forecast/config.py
  intent_forecast/context.py
  intent_forecast/controller.py
  intent_forecast/fallback.py
  intent_forecast/focus.py
  intent_forecast/learning.py
  intent_forecast/messages.py
  intent_forecast/persistence.py
  intent_forecast/prompt.py
  intent_forecast/registration.py
  intent_forecast/service.py
  intent_forecast/session_retrieval.py
  intent_forecast/settings_io.py
  intent_forecast/task_state.py
```

**`session_intelligence/`** ▲（5 files, 359 lines）
```
  session_intelligence/__init__.py
  session_intelligence/index.py
  session_intelligence/queue.py
  session_intelligence/summarizer.py
  session_intelligence/summary_schema.py
```

---

### 【G6】🏗️ 服务化基础设施

**`services/`** *（257 files, 55,069 lines）
```
  services/__init__.py
  services/analytics/__init__.py
  services/analytics/events.py
  services/analytics/metadata.py
  services/analytics/sink.py
  services/api/__init__.py
  services/api/claude.py
  services/api/errors.py
  services/api/logging.py
  services/api/provider_config.py
  services/api/retry.py
  services/api/tool_normalization.py
  services/bridge/__init__.py
  services/bridge/auth.py
  services/bridge/session.py
  services/bridge/transport.py
  services/channels/__init__.py
  services/channels/base.py
  services/channels/capabilities.py
  services/channels/discord.py
  services/channels/exceptions.py
  services/channels/feishu.py
  services/channels/feishu_app.py
  services/channels/feishu_cards.py
  services/channels/feishu_events.py
  services/channels/feishu_onboarding.py
  services/channels/feishu_sdk.py
  services/channels/feishu_settings.py
  services/channels/models.py
  services/channels/null_channel.py
  services/channels/registry.py
  services/channels/results.py
  services/channels/retry.py
  services/channels/slack.py
  services/channels/transport.py
  services/channels/wechat_ilink.py
  services/chrome/__init__.py
  services/chrome/base.py
  services/chrome/factory.py
  services/chrome/mcp_impl.py
  services/chrome/models.py
  services/chrome/null_impl.py
  services/chrome/playwright_impl.py
  services/chrome/recording.py
  services/compact/__init__.py
  services/compact/autocompact.py
  services/compact/compact.py
  services/compact/compact_warning.py
  services/compact/context_collapse.py
  services/compact/gating.py
  services/compact/grouping.py
  services/compact/pipeline.py
  services/compact/post_compact_attachments.py
  services/compact/post_compact_cleanup.py
  services/compact/prompt.py
  services/compact/reactive_compact.py
  services/compact/session_memory_compact.py
  services/compact/snip_compact.py
  services/compact/tool_result_budget.py
  services/computer_use/__init__.py
  services/computer_use/base.py
  services/computer_use/dry_run.py
  services/computer_use/exceptions.py
  services/computer_use/factory.py
  services/computer_use/models.py
  services/computer_use/platform/__init__.py
  services/computer_use/platform/linux.py
  services/computer_use/platform/null.py
  services/context_collapse/__init__.py
  services/context_collapse/boundary.py
  services/context_collapse/engine.py
  services/context_collapse/exceptions.py
  services/context_collapse/persistence.py
  services/context_collapse/summary.py
  services/context_collapse/tokens.py
  services/context_collapse/trigger.py
  services/cost_restore.py
  services/cost_tracker.py
  services/feature_gate/__init__.py
  services/ide/__init__.py
  services/ide/connection.py
  services/ide/diagnostics.py
  services/ide/selection.py
  services/ide/types.py
  services/im_gateway/__init__.py
  services/im_gateway/audit.py
  services/im_gateway/binding.py
  services/im_gateway/capability_gate.py
  services/im_gateway/config.py
  services/im_gateway/dispatcher.py
  services/im_gateway/gateway.py
  services/im_gateway/ipc_client.py
  services/im_gateway/ipc_protocol.py
  services/im_gateway/ipc_server.py
  services/im_gateway/models.py
  services/im_gateway/origin_utils.py
  services/im_gateway/outbound.py
  services/im_gateway/processing_status.py
  services/im_gateway/reliability.py
  services/im_gateway/repl_command_gate.py
  services/im_gateway/retention.py
  services/im_gateway/router.py
  services/im_gateway/store.py
  services/im_gateway/stub_agent.py
  services/im_gateway/text.py
  services/kairos/__init__.py
  services/kairos/brief.py
  services/kairos/daily_log.py
  services/kairos/exceptions.py
  services/kairos/models.py
  services/kairos/scheduler.py
  services/langfuse/__init__.py
  services/langfuse/client.py
  services/langfuse/exporter.py
  services/langfuse/sink.py
  services/lodestone/__init__.py
  services/lodestone/config.py
  services/lodestone/fingerprint.py
  services/lodestone/models.py
  services/lodestone/parser.py
  services/lodestone/renderer.py
  services/lodestone/resolver.py
  services/lodestone/service.py
  services/lodestone/targets.py
  services/mcp/__init__.py
  services/mcp/auth.py
  services/mcp/auth_discovery.py
  services/mcp/auth_provider.py
  services/mcp/channel_permissions.py
  services/mcp/claudeai.py
  services/mcp/client.py
  services/mcp/config.py
  services/mcp/connection_manager.py
  services/mcp/doctor.py
  services/mcp/elicitation.py
  services/mcp/env_expansion.py
  services/mcp/errors.py
  services/mcp/fetch_wrappers.py
  services/mcp/in_process_transport.py
  services/mcp/manager.py
  services/mcp/mcp_string_utils.py
  services/mcp/normalization.py
  services/mcp/oauth_callback_server.py
  services/mcp/oauth_error_normalization.py
  services/mcp/oauth_port.py
  services/mcp/oauth_redaction.py
  services/mcp/official_registry.py
  services/mcp/output_storage.py
  services/mcp/output_validation.py
  services/mcp/telemetry.py
  services/mcp/text_truncation.py
  services/mcp/tool_wrapper.py
  services/mcp/transport.py
  services/mcp/types.py
  services/mcp/xaa.py
  services/mcp/xaa_idp_login.py
  services/monitor/__init__.py
  services/monitor/controller.py
  services/monitor/install.py
  services/monitor/stall_guard.py
  services/monitor/text_tail.py
  services/monitor/watch_compat.py
  services/oauth/__init__.py
  services/oauth/client.py
  services/periodic/__init__.py
  services/pipe_ipc/__init__.py
  services/pipe_ipc/codec.py
  services/pipe_ipc/models.py
  services/pipe_ipc/permissions.py
  services/pipe_ipc/registry.py
  services/pipe_ipc/uds.py
  services/pricing.py
  services/proactive/__init__.py
  services/proactive/constants.py
  services/proactive/controller.py
  services/proactive/prompts.py
  services/proactive/state.py
  services/proactive/tick_emitter.py
  services/session_migrate.py
  services/session_resume.py
  services/session_storage.py
  services/session_title.py
  services/skill_search/__init__.py
  services/skill_search/config.py
  services/skill_search/document.py
  services/skill_search/exceptions.py
  services/skill_search/index.py
  services/skill_search/searcher.py
  services/skill_search/tokenizer.py
  services/skill_search/watcher.py
  services/swarm/__init__.py
  services/swarm/agent_name_registry.py
  services/swarm/helpers.py
  services/swarm/leader_permission_bridge.py
  services/swarm/mailbox.py
  services/swarm/mailbox_poller.py
  services/swarm/permissions.py
  services/swarm/team_file.py
  services/swarm/team_membership.py
  services/swarm/teammate.py
  services/tail_follower.py
  services/templates/__init__.py
  services/templates/bootstrap.py
  services/templates/built_in.py
  services/templates/catalogue.py
  services/templates/compatibility.py
  services/templates/discovery.py
  services/templates/exceptions.py
  services/templates/generator.py
  services/templates/models.py
  services/templates/persistence.py
  services/templates/registry.py
  services/templates/renderer.py
  services/templates/resolver.py
  services/templates/schema.py
  services/tool_execution/__init__.py
  services/tool_execution/orchestrator.py
  services/tool_execution/streaming_executor.py
  services/tool_execution/tool_execution.py
  services/tool_execution/tool_hooks.py
  services/tool_execution/tool_result_persistence.py
  services/ultraplan/__init__.py
  services/ultraplan/adjuster.py
  services/ultraplan/audit.py
  services/ultraplan/ccr_session.py
  services/ultraplan/controller.py
  services/ultraplan/exceptions.py
  services/ultraplan/executor.py
  services/ultraplan/feature_gates.py
  services/ultraplan/keyword_detector.py
  services/ultraplan/llm_planner.py
  services/ultraplan/models.py
  services/ultraplan/planner_recovery.py
  services/ultraplan/store.py
  services/ultraplan/templates.py
  services/ultraplan/verifier.py
  services/voice/__init__.py
  services/voice/anthropic_stt.py
  services/voice/audio_chunk_queue.py
  services/voice/audio_out_queue.py
  services/voice/audio_player.py
  services/voice/audio_recorder.py
  services/voice/detection.py
  services/voice/dialogue.py
  services/voice/dialogue_session.py
  services/voice/doubao_stt.py
  services/voice/gemini_tts.py
  services/voice/interrupt.py
  services/voice/minimax_realtime_dialogue.py
  services/voice/minimax_stt.py
  services/voice/minimax_tts.py
  services/voice/openai_tts.py
  services/voice/provider_registry.py
  services/voice/push_to_talk.py
  services/voice/stt.py
  services/voice/tts.py
  services/voice/voice_mode_enabled.py
```

**`providers/`**（32 files, 7,493 lines）
```
  providers/__init__.py
  providers/_litellm_adapter.py
  providers/_moonshot_schema.py
  providers/_stream_abort.py
  providers/_stream_drain.py
  providers/anthropic_provider.py
  providers/base.py
  providers/codex_models.py
  providers/factory.py
  providers/hooks.py
  providers/kimi_coding_provider.py
  providers/kimi_provider.py
  providers/media/__init__.py
  providers/media/base.py
  providers/media/image/__init__.py
  providers/media/image/agnes.py
  providers/media/registry.py
  providers/media/video/__init__.py
  providers/media/video/agnes.py
  providers/minimax_provider.py
  providers/model_catalog_cache.py
  providers/native/__init__.py
  providers/native/base.py
  providers/native/capabilities.py
  providers/native/gemini_adapter.py
  providers/native/grok_adapter.py
  providers/native/openai_adapter.py
  providers/openai_codex_provider.py
  providers/openai_compatible.py
  providers/openai_responses.py
  providers/patches.py
  providers/runtime.py
```

**`tool_system/`**（78 files, 22,507 lines）
```
  tool_system/__init__.py
  tool_system/build_tool.py
  tool_system/context.py
  tool_system/defaults.py
  tool_system/diff_utils.py
  tool_system/errors.py
  tool_system/loader.py
  tool_system/protocol.py
  tool_system/registry.py
  tool_system/renderers.py
  tool_system/schema_validation.py
  tool_system/task_manager.py
  tool_system/team_aware_pool.py
  tool_system/tool_search.py
  tool_system/tool_timeout.py
  tool_system/tools/__init__.py
  tool_system/tools/advisor.py
  tool_system/tools/agent.py
  tool_system/tools/ask_issue_author.py
  tool_system/tools/ask_user_question.py
  tool_system/tools/bash/__init__.py
  tool_system/tools/bash/background.py
  tool_system/tools/bash/bash_tool.py
  tool_system/tools/bash/command_semantics.py
  tool_system/tools/bash/destructive_warnings.py
  tool_system/tools/bash/image_output.py
  tool_system/tools/bash/prompt.py
  tool_system/tools/bash/read_only_validation.py
  tool_system/tools/bash/search_classification.py
  tool_system/tools/bash/sleep_detection.py
  tool_system/tools/bash/utils.py
  tool_system/tools/bg_session.py
  tool_system/tools/brief.py
  tool_system/tools/config.py
  tool_system/tools/create_agent_tool.py
  tool_system/tools/cron.py
  tool_system/tools/edit.py
  tool_system/tools/execute.py
  tool_system/tools/glob.py
  tool_system/tools/grep.py
  tool_system/tools/lodestone.py
  tool_system/tools/lsp.py
  tool_system/tools/mcp.py
  tool_system/tools/mcp_resources.py
  tool_system/tools/memory.py
  tool_system/tools/misc.py
  tool_system/tools/monitor.py
  tool_system/tools/notebook_edit.py
  tool_system/tools/plan_mode.py
  tool_system/tools/progress_report.py
  tool_system/tools/read.py
  tool_system/tools/remote_trigger.py
  tool_system/tools/schedule_wakeup.py
  tool_system/tools/send_message.py
  tool_system/tools/send_user_message.py
  tool_system/tools/skill.py
  tool_system/tools/skill_search.py
  tool_system/tools/sleep.py
  tool_system/tools/snip.py
  tool_system/tools/structured_output.py
  tool_system/tools/task_decompose.py
  tool_system/tools/task_directives.py
  tool_system/tools/task_inspect.py
  tool_system/tools/task_stop.py
  tool_system/tools/tasks_v2.py
  tool_system/tools/team.py
  tool_system/tools/team_memory.py
  tool_system/tools/todo_write.py
  tool_system/tools/tool_search.py
  tool_system/tools/tool_search_matching.py
  tool_system/tools/web_browser.py
  tool_system/tools/web_fetch.py
  tool_system/tools/web_search.py
  tool_system/tools/worktree.py
  tool_system/tools/write.py
  tool_system/utils/__init__.py
  tool_system/utils/path_utils.py
  tool_system/utils/ripgrep.py
```

**`utils/`**（30 files, 6,713 lines）
```
  utils/__init__.py
  utils/abort_controller.py
  utils/advisor.py
  utils/agent_mention_completer.py
  utils/at_file_completer.py
  utils/cache_warning.py
  utils/combined_abort_signal.py
  utils/completers.py
  utils/env.py
  utils/export_formats.py
  utils/file_lock.py
  utils/file_state_cache.py
  utils/format.py
  utils/frontmatter_validators.py
  utils/git.py
  utils/image_processor.py
  utils/image_validation.py
  utils/key_format.py
  utils/message_mappers.py
  utils/message_queue_manager.py
  utils/messages.py
  utils/resume_hint.py
  utils/session_ingress_auth.py
  utils/session_watcher.py
  utils/shell_resolver.py
  utils/signal.py
  utils/store.py
  utils/stream_watchdog.py
  utils/task_flags.py
  utils/token_estimation.py
```

**`settings/`**（5 files, 1,028 lines）
```
  settings/__init__.py
  settings/pydantic_adapter.py
  settings/settings.py
  settings/types.py
  settings/validation.py
```

**`query/`**（12 files, 6,754 lines）
```
  query/agent_loop_compat.py
  query/config.py
  query/deps.py
  query/engine.py
  query/hook_registry.py
  query/outbox_types.py
  query/query.py
  query/recovery_strategies.py
  query/stop_hooks.py
  query/streaming.py
  query/token_budget.py
  query/transitions.py
```

**`coordinator/`**（3 files, 746 lines）
```
  coordinator/mode.py
  coordinator/prompt.py
  coordinator/worker_agent.py
```

**`bootstrap/`**（2 files, 8 lines）
```
  bootstrap/__init__.py
  bootstrap/state.py
```

**`compact_service/`** ▲（2 files, 239 lines）
```
  compact_service/__init__.py
  compact_service/messages.py
```

**`cron_system/`** ▲（15 files, 3,886 lines）
```
  cron_system/__init__.py
  cron_system/asciicast_observer.py
  cron_system/dispatch.py
  cron_system/jitter.py
  cron_system/lock.py
  cron_system/models.py
  cron_system/notifications.py
  cron_system/parser.py
  cron_system/runs.py
  cron_system/runtime.py
  cron_system/schedule.py
  cron_system/scheduler.py
  cron_system/status.py
  cron_system/tasks.py
  cron_system/tools.py
```

**`native/`** ▲（5 files, 1,191 lines）
```
  native/__init__.py
  native/audio.py
  native/image.py
  native/modifiers.py
  native/url_handler.py
```

**`multimodel/`** ▲（32 files, 2,340 lines）
```
  multimodel/__init__.py
  multimodel/aggregators/__init__.py
  multimodel/aggregators/base.py
  multimodel/aggregators/first_success.py
  multimodel/aggregators/fusion.py
  multimodel/aggregators/majority_vote.py
  multimodel/aggregators/passthrough.py
  multimodel/aggregators/rank.py
  multimodel/aggregators/scoring.py
  multimodel/cli.py
  multimodel/config.py
  multimodel/display/__init__.py
  multimodel/display/bridge.py
  multimodel/display/diff_display.py
  multimodel/display/keyboard.py
  multimodel/display/protocol.py
  multimodel/display/side_by_side.py
  multimodel/display/summary.py
  multimodel/display/tab_display.py
  multimodel/factory.py
  multimodel/feature.py
  multimodel/preset.py
  multimodel/router.py
  multimodel/runtime_command.py
  multimodel/session_bridge.py
  multimodel/slots.py
  multimodel/strategies/__init__.py
  multimodel/strategies/base.py
  multimodel/strategies/fallback.py
  multimodel/strategies/parallel.py
  multimodel/strategies/routing.py
  multimodel/strategies/voting.py
```

**`models/`** ▲（2 files, 146 lines）
```
  models/__init__.py
  models/configs.py
```

**`buddy/`** ▲（9 files, 1,401 lines）
```
  buddy/__init__.py
  buddy/companion.py
  buddy/feature.py
  buddy/notification.py
  buddy/observer.py
  buddy/prompt.py
  buddy/soul.py
  buddy/sprites.py
  buddy/types.py
```

**`daemon/`** ▲（1 file, 71 lines）
```
  daemon/__init__.py
```

**`orchestrator/`** ▲（4 files, 539 lines）
```
  orchestrator/__init__.py
  orchestrator/_patch_stale_registry.py
  orchestrator/_tests/__init__.py
  orchestrator/_tests/test_stale_registry_patch.py
```

**`configuration/`** ▲（3 files, 1,462 lines）
```
  configuration/__init__.py
  configuration/contract.py
  configuration/service.py
```

**`debug/`** ▲（3 files, 1,381 lines）
```
  debug/__init__.py
  debug/agent_debug.py
  debug/repl_pty_session.py
```

**`state/`** ▲（4 files, 1,021 lines）
```
  state/__init__.py
  state/app_state.py
  state/cache_state.py
  state/session_start.py
```

**`capabilities/`** ▲（2 files, 145 lines）
```
  capabilities/__init__.py
  capabilities/multimodel_protocol.py
```

**`logical_kanban/`** ▲（51 files, 166 lines — shim, 内容来自 `lkb` 包）
```
  logical_kanban/__init__.py
```

**`community_radar/`**（38 files, 15,098 lines — 语义属 Layer2，物理在此）
```
  community_radar/__init__.py
  community_radar/classifier.py
  community_radar/cli.py
  community_radar/config.py
  community_radar/cron_integration.py
  community_radar/deduplicator.py
  community_radar/discover.py
  community_radar/extractor.py
  community_radar/fetcher.py
  community_radar/i18n.py
  community_radar/issue_platforms.py
  community_radar/issue_sync.py
  community_radar/llm_classifier.py
  community_radar/models.py
  community_radar/notifier.py
  community_radar/pipeline.py
  community_radar/registry.py
  community_radar/reporter.py
  community_radar/scorer.py
  community_radar/tests/__init__.py
  community_radar/tests/test_classifier.py
  community_radar/tests/test_cli.py
  community_radar/tests/test_config.py
  community_radar/tests/test_cron_integration.py
  community_radar/tests/test_deduplicator.py
  community_radar/tests/test_extractor.py
  community_radar/tests/test_fetcher.py
  community_radar/tests/test_issue_platforms.py
  community_radar/tests/test_issue_sync.py
  community_radar/tests/test_jinja2_reporter.py
  community_radar/tests/test_llm_classifier.py
  community_radar/tests/test_models.py
  community_radar/tests/test_notifier.py
  community_radar/tests/test_pipeline.py
  community_radar/tests/test_proposals.py
  community_radar/tests/test_registry.py
  community_radar/tests/test_reporter.py
  community_radar/tests/test_scorer.py
```

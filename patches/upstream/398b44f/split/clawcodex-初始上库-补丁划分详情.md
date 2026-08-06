# 补丁文件划分报告

**源目录：** `patches/upstream/398b44f/merged/`
**总文件数：** 583 个补丁文件
**总行数：** 100459 行

## 终划分总览

| 部分 | 行数 | 文件数 | 文件范围 | 代码模块（按路径） |
|------|------|--------|----------|-------------------|
| Part1 | 11691 行 | 54 | `0001.__init___py.patch` … `0054.bridge_poll_config_defaults_py.patch` | `.init...py` … `poll.config.defaults.py` |
| Part2 | 11350 行 | 31 | `0055.bridge_remote_bridge_core_py.patch` … `0085.command_system_export_command_py.patch` | `remote.bridge.core.py` … `system.export.command.py` |
| Part3 | 10755 行 | 43 | `0086.command_system_input_processing_py.patch` … `0128.hooks_exec_prompt_hook_py.patch` | `system.input.processing.py` … `exec.prompt.hook.py` |
| Part4 | 11407 行 | 56 | `0129.hooks_hook_executor_py.patch` … `0184.plugins_dependency_py.patch` | `hook.executor.py` … `dependency.py` |
| Part5 | 11624 行 | 52 | `0185.plugins_loader_py.patch` … `0236.services_mcp_config_py.patch` | `loader.py` … `mcp.config.py` |
| Part6 | 11450 行 | 54 | `0237.services_pricing_py.patch` … `0290.tasks_core_py.patch` | `pricing.py` … `core.py` |
| Part7 | 11534 行 | 45 | `0291.token_estimation_py.patch` … `0335.tool_system_tools_send_user_message_py.patch` | `estimation.py` … `system.tools.send.user.message.py` |
| Part8 | 11518 行 | 47 | `0336.tool_system_tools_skill_py.patch` … `0382.utils_frontmatter_validators_py.patch` | `system.tools.skill.py` … `frontmatter.validators.py` |
| Part9.1 | 4555 行 | 41 | `0383.utils_git_py.patch` … `0423.providers_native_capabilities_py.patch` | `git.py` … `native.capabilities.py` |
| Part9.2 | 4575 行 | 160 | `0424.providers_native_gemini_adapter_py.patch` … `0583.utils_session_watcher_py.patch` | `native.gemini.adapter.py` … `session.watcher.py` |

## 每份文件详情

### Part1 — 11691 行，54 个文件

**范围：** `0001.__init___py.patch` ~ `0054.bridge_poll_config_defaults_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0001.__init___py.patch` | 72 |
| 2 | `0002.agent___init___py.patch` | 123 |
| 3 | `0003.agent_agent_definitions_py.patch` | 306 |
| 4 | `0004.agent_agent_tool_utils_py.patch` | 379 |
| 5 | `0005.agent_constants_py.patch` | 94 |
| 6 | `0006.agent_conversation_py.patch` | 117 |
| 7 | `0007.agent_filter_agents_by_mcp_py.patch` | 65 |
| 8 | `0008.agent_foreground_promotion_py.patch` | 237 |
| 9 | `0009.agent_fork_subagent_py.patch` | 316 |
| 10 | `0010.agent_load_agents_dir_py.patch` | 175 |
| 11 | `0011.agent_load_plugin_agents_py.patch` | 124 |
| 12 | `0012.agent_parse_agent_markdown_py.patch` | 243 |
| 13 | `0013.agent_prompt_py.patch` | 240 |
| 14 | `0014.agent_resume_agent_py.patch` | 265 |
| 15 | `0015.agent_run_agent_py.patch` | 469 |
| 16 | `0016.agent_session_py.patch` | 170 |
| 17 | `0017.agent_subagent_context_py.patch` | 286 |
| 18 | `0018.agent_transcript_py.patch` | 373 |
| 19 | `0019.assistant___init___py.patch` | 25 |
| 20 | `0020.assistant_session_chooser_py.patch` | 46 |
| 21 | `0021.assistant_session_history_py.patch` | 223 |
| 22 | `0022.auth___init___py.patch` | 61 |
| 23 | `0023.auth_auth_py.patch` | 151 |
| 24 | `0024.auth_aws_py.patch` | 73 |
| 25 | `0025.auth_claude_ai_py.patch` | 281 |
| 26 | `0026.auth_gemini_py.patch` | 41 |
| 27 | `0027.auth_oauth_py.patch` | 184 |
| 28 | `0028.bootstrap___init___py.patch` | 14 |
| 29 | `0029.bootstrap_state_py.patch` | 46 |
| 30 | `0030.bridge___init___py.patch` | 156 |
| 31 | `0031.bridge_bounded_uuid_set_py.patch` | 84 |
| 32 | `0032.bridge_bridge_api_py.patch` | 749 |
| 33 | `0033.bridge_bridge_config_py.patch` | 89 |
| 34 | `0034.bridge_bridge_enabled_py.patch` | 110 |
| 35 | `0035.bridge_bridge_main_py.patch` | 1253 |
| 36 | `0036.bridge_bridge_permission_callbacks_py.patch` | 110 |
| 37 | `0037.bridge_bridge_pointer_py.patch` | 268 |
| 38 | `0038.bridge_bridge_status_util_py.patch` | 457 |
| 39 | `0039.bridge_capacity_wake_py.patch` | 123 |
| 40 | `0040.bridge_close_codes_py.patch` | 61 |
| 41 | `0041.bridge_code_session_api_py.patch` | 274 |
| 42 | `0042.bridge_debug_utils_py.patch` | 195 |
| 43 | `0043.bridge_env_less_bridge_config_py.patch` | 151 |
| 44 | `0044.bridge_exceptions_py.patch` | 71 |
| 45 | `0045.bridge_flush_gate_py.patch` | 101 |
| 46 | `0046.bridge_inbound_attachments_py.patch` | 282 |
| 47 | `0047.bridge_inbound_messages_py.patch` | 152 |
| 48 | `0048.bridge_init_repl_bridge_py.patch` | 407 |
| 49 | `0049.bridge_jwt_utils_py.patch` | 357 |
| 50 | `0050.bridge_messaging_py.patch` | 411 |
| 51 | `0051.bridge_messaging_handlers_py.patch` | 270 |
| 52 | `0052.bridge_no_proxy_py.patch` | 59 |
| 53 | `0053.bridge_poll_config_py.patch` | 198 |
| 54 | `0054.bridge_poll_config_defaults_py.patch` | 104 |

### Part2 — 11350 行，31 个文件

**范围：** `0055.bridge_remote_bridge_core_py.patch` ~ `0085.command_system_export_command_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0055.bridge_remote_bridge_core_py.patch` | 1195 |
| 2 | `0056.bridge_repl_bridge_py.patch` | 1404 |
| 3 | `0057.bridge_repl_bridge_handle_py.patch` | 109 |
| 4 | `0058.bridge_repl_bridge_transport_py.patch` | 427 |
| 5 | `0059.bridge_session_id_compat_py.patch` | 90 |
| 6 | `0060.bridge_session_runner_py.patch` | 944 |
| 7 | `0061.bridge_types_py.patch` | 509 |
| 8 | `0062.bridge_work_secret_py.patch` | 165 |
| 9 | `0063.bridge_worktree_py.patch` | 229 |
| 10 | `0064.buddy___init___py.patch` | 144 |
| 11 | `0065.buddy_companion_py.patch` | 270 |
| 12 | `0066.buddy_feature_py.patch` | 24 |
| 13 | `0067.buddy_notification_py.patch` | 68 |
| 14 | `0068.buddy_observer_py.patch` | 147 |
| 15 | `0069.buddy_prompt_py.patch` | 146 |
| 16 | `0070.buddy_soul_py.patch` | 81 |
| 17 | `0071.buddy_sprites_py.patch` | 536 |
| 18 | `0072.buddy_types_py.patch` | 181 |
| 19 | `0073.cli_py.patch` | 1059 |
| 20 | `0074.cli_core___init___py.patch` | 34 |
| 21 | `0075.cli_core_exit_py.patch` | 43 |
| 22 | `0076.cli_core_ndjson_py.patch` | 51 |
| 23 | `0077.cli_core_structured_io_py.patch` | 217 |
| 24 | `0078.command_system___init___py.patch` | 229 |
| 25 | `0079.command_system_aggregator_py.patch` | 282 |
| 26 | `0080.command_system_argument_substitution_py.patch` | 137 |
| 27 | `0081.command_system_buddy_command_py.patch` | 209 |
| 28 | `0082.command_system_builtins_py.patch` | 1489 |
| 29 | `0083.command_system_effort_command_py.patch` | 285 |
| 30 | `0084.command_system_engine_py.patch` | 359 |
| 31 | `0085.command_system_export_command_py.patch` | 287 |

### Part3 — 10755 行，43 个文件

**范围：** `0086.command_system_input_processing_py.patch` ~ `0128.hooks_exec_prompt_hook_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0086.command_system_input_processing_py.patch` | 957 |
| 2 | `0087.command_system_model_command_py.patch` | 206 |
| 3 | `0088.command_system_moved_to_plugin_py.patch` | 105 |
| 4 | `0089.command_system_output_style_command_py.patch` | 69 |
| 5 | `0090.command_system_permissions_command_py.patch` | 27 |
| 6 | `0091.command_system_registry_py.patch` | 220 |
| 7 | `0092.command_system_safe_commands_py.patch` | 87 |
| 8 | `0093.command_system_security_review_py.patch` | 268 |
| 9 | `0094.command_system_shell_prompt_py.patch` | 140 |
| 10 | `0095.command_system_skills_integration_py.patch` | 233 |
| 11 | `0096.command_system_statusline_py.patch` | 75 |
| 12 | `0097.command_system_theme_command_py.patch` | 141 |
| 13 | `0098.command_system_types_py.patch` | 475 |
| 14 | `0099.compact_service_messages_py.patch` | 212 |
| 15 | `0100.compact_service_service_py.patch` | 64 |
| 16 | `0101.components___init___py.patch` | 14 |
| 17 | `0102.config_py.patch` | 582 |
| 18 | `0103.constants_xml_py.patch` | 70 |
| 19 | `0104.context_system___init___py.patch` | 74 |
| 20 | `0105.context_system_builder_py.patch` | 116 |
| 21 | `0106.context_system_cache_boundary_py.patch` | 29 |
| 22 | `0107.context_system_context_analyzer_py.patch` | 396 |
| 23 | `0108.context_system_git_context_py.patch` | 273 |
| 24 | `0109.context_system_memory_prefetch_py.patch` | 97 |
| 25 | `0110.context_system_microcompact_py.patch` | 479 |
| 26 | `0111.context_system_models_py.patch` | 113 |
| 27 | `0112.context_system_prompt_assembly_py.patch` | 1431 |
| 28 | `0113.context_system_system_prompt_cache_py.patch` | 202 |
| 29 | `0114.context_system_workspace_snapshot_py.patch` | 80 |
| 30 | `0115.coordinator_mode_py.patch` | 312 |
| 31 | `0116.coordinator_prompt_py.patch` | 378 |
| 32 | `0117.coordinator_worker_agent_py.patch` | 69 |
| 33 | `0118.cost_tracker_py.patch` | 12 |
| 34 | `0119.entrypoints___init___py.patch` | 29 |
| 35 | `0120.entrypoints_daemon_py.patch` | 14 |
| 36 | `0121.entrypoints_doctor_py.patch` | 46 |
| 37 | `0122.entrypoints_headless_py.patch` | 1012 |
| 38 | `0123.entrypoints_mcp_py.patch` | 713 |
| 39 | `0124.hooks___init___py.patch` | 74 |
| 40 | `0125.hooks_config_manager_py.patch` | 558 |
| 41 | `0126.hooks_exec_agent_hook_py.patch` | 130 |
| 42 | `0127.hooks_exec_http_hook_py.patch` | 130 |
| 43 | `0128.hooks_exec_prompt_hook_py.patch` | 43 |

### Part4 — 11407 行，56 个文件

**范围：** `0129.hooks_hook_executor_py.patch` ~ `0184.plugins_dependency_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0129.hooks_hook_executor_py.patch` | 1244 |
| 2 | `0130.hooks_hook_types_py.patch` | 371 |
| 3 | `0131.hooks_output_schema_py.patch` | 92 |
| 4 | `0132.hooks_post_sampling_hooks_py.patch` | 72 |
| 5 | `0133.hooks_registry_py.patch` | 189 |
| 6 | `0134.hooks_session_hooks_py.patch` | 300 |
| 7 | `0135.hooks_shell_invocation_py.patch` | 103 |
| 8 | `0136.hooks_ssrf_guard_py.patch` | 117 |
| 9 | `0137.hooks_trust_gate_py.patch` | 43 |
| 10 | `0138.init_py.patch` | 238 |
| 11 | `0139.keybindings___init___py.patch` | 14 |
| 12 | `0140.memdir___init___py.patch` | 231 |
| 13 | `0141.memdir_find_relevant_memories_py.patch` | 254 |
| 14 | `0142.memdir_memdir_py.patch` | 377 |
| 15 | `0143.memdir_memory_age_py.patch` | 76 |
| 16 | `0144.memdir_memory_scan_py.patch` | 183 |
| 17 | `0145.memdir_memory_types_py.patch` | 178 |
| 18 | `0146.memdir_paths_py.patch` | 302 |
| 19 | `0147.memdir_team_mem_paths_py.patch` | 318 |
| 20 | `0148.memdir_team_mem_prompts_py.patch` | 220 |
| 21 | `0149.migrations___init___py.patch` | 14 |
| 22 | `0150.models___init___py.patch` | 54 |
| 23 | `0151.models_agent_routing_py.patch` | 30 |
| 24 | `0152.models_aliases_py.patch` | 50 |
| 25 | `0153.models_bedrock_py.patch` | 31 |
| 26 | `0154.models_capabilities_py.patch` | 11 |
| 27 | `0155.models_context_py.patch` | 12 |
| 28 | `0156.models_model_py.patch` | 23 |
| 29 | `0157.models_validation_py.patch` | 27 |
| 30 | `0158.moreright___init___py.patch` | 14 |
| 31 | `0159.native_ts___init___py.patch` | 14 |
| 32 | `0160.outputStyles___init___py.patch` | 14 |
| 33 | `0161.outputStyles_loader_py.patch` | 27 |
| 34 | `0162.outputStyles_styles_py.patch` | 22 |
| 35 | `0163.permissions___init___py.patch` | 199 |
| 36 | `0164.permissions_bash_parser___init___py.patch` | 36 |
| 37 | `0165.permissions_bash_parser_ast_nodes_py.patch` | 53 |
| 38 | `0166.permissions_bash_parser_commands_py.patch` | 220 |
| 39 | `0167.permissions_bash_parser_parser_py.patch` | 275 |
| 40 | `0168.permissions_bash_parser_shell_quote_py.patch` | 36 |
| 41 | `0169.permissions_bash_security_py.patch` | 250 |
| 42 | `0170.permissions_check_py.patch` | 1448 |
| 43 | `0171.permissions_cycle_py.patch` | 74 |
| 44 | `0172.permissions_dangerous_safety_py.patch` | 87 |
| 45 | `0173.permissions_filesystem_py.patch` | 450 |
| 46 | `0174.permissions_handler_py.patch` | 291 |
| 47 | `0175.permissions_loader_py.patch` | 65 |
| 48 | `0176.permissions_modes_py.patch` | 219 |
| 49 | `0177.permissions_rule_parser_py.patch` | 107 |
| 50 | `0178.permissions_rules_py.patch` | 161 |
| 51 | `0179.permissions_setup_py.patch` | 253 |
| 52 | `0180.permissions_trust_boundary_py.patch` | 463 |
| 53 | `0181.permissions_types_py.patch` | 408 |
| 54 | `0182.permissions_updates_py.patch` | 761 |
| 55 | `0183.plugins___init___py.patch` | 222 |
| 56 | `0184.plugins_dependency_py.patch` | 64 |

### Part5 — 11624 行，52 个文件

**范围：** `0185.plugins_loader_py.patch` ~ `0236.services_mcp_config_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0185.plugins_loader_py.patch` | 575 |
| 2 | `0186.plugins_lsp_integration_py.patch` | 45 |
| 3 | `0187.plugins_marketplace_py.patch` | 108 |
| 4 | `0188.plugins_mcp_integration_py.patch` | 57 |
| 5 | `0189.plugins_types_py.patch` | 35 |
| 6 | `0190.plugins_validator_py.patch` | 127 |
| 7 | `0191.prefetch_py.patch` | 125 |
| 8 | `0192.providers___init___py.patch` | 100 |
| 9 | `0193.providers__stream_abort_py.patch` | 249 |
| 10 | `0194.providers_anthropic_provider_py.patch` | 942 |
| 11 | `0195.providers_base_py.patch` | 225 |
| 12 | `0196.providers_deepseek_provider_py.patch` | 58 |
| 13 | `0197.providers_gemini_provider_py.patch` | 386 |
| 14 | `0198.providers_glm_provider_py.patch` | 90 |
| 15 | `0199.providers_minimax_provider_py.patch` | 330 |
| 16 | `0200.providers_openai_compatible_py.patch` | 1042 |
| 17 | `0201.providers_openrouter_provider_py.patch` | 129 |
| 18 | `0202.query___init___py.patch` | 59 |
| 19 | `0203.query_agent_loop_compat_py.patch` | 861 |
| 20 | `0204.query_config_py.patch` | 134 |
| 21 | `0205.query_deps_py.patch` | 17 |
| 22 | `0206.query_engine_py.patch` | 336 |
| 23 | `0207.query_query_py.patch` | 2459 |
| 24 | `0208.query_stop_hooks_py.patch` | 397 |
| 25 | `0209.query_token_budget_py.patch` | 163 |
| 26 | `0210.query_transitions_py.patch` | 122 |
| 27 | `0211.reference_data_subsystems_buddy_json.patch` | 22 |
| 28 | `0212.remote___init___py.patch` | 14 |
| 29 | `0213.remote_remote_session_manager_py.patch` | 302 |
| 30 | `0214.remote_sessions_websocket_py.patch` | 490 |
| 31 | `0215.schemas___init___py.patch` | 14 |
| 32 | `0216.screens___init___py.patch` | 14 |
| 33 | `0217.server___init___py.patch` | 14 |
| 34 | `0218.server_direct_connect_manager_py.patch` | 48 |
| 35 | `0219.server_direct_connect_session_py.patch` | 14 |
| 36 | `0220.server_lockfile_py.patch` | 14 |
| 37 | `0221.server_session_index_py.patch` | 36 |
| 38 | `0222.server_session_manager_py.patch` | 14 |
| 39 | `0223.server_types_py.patch` | 14 |
| 40 | `0224.server_url_scheme_py.patch` | 15 |
| 41 | `0225.services___init___py.patch` | 36 |
| 42 | `0226.services_compact___init___py.patch` | 94 |
| 43 | `0227.services_compact_pipeline_py.patch` | 340 |
| 44 | `0228.services_cost_restore_py.patch` | 207 |
| 45 | `0229.services_cost_tracker_py.patch` | 260 |
| 46 | `0230.services_ide___init___py.patch` | 36 |
| 47 | `0231.services_ide_connection_py.patch` | 175 |
| 48 | `0232.services_ide_diagnostics_py.patch` | 81 |
| 49 | `0233.services_ide_selection_py.patch` | 85 |
| 50 | `0234.services_ide_types_py.patch` | 86 |
| 51 | `0235.services_mcp_auth_py.patch` | 14 |
| 52 | `0236.services_mcp_config_py.patch` | 14 |

### Part6 — 11450 行，54 个文件

**范围：** `0237.services_pricing_py.patch` ~ `0290.tasks_core_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0237.services_pricing_py.patch` | 402 |
| 2 | `0238.services_session_persistence_py.patch` | 21 |
| 3 | `0239.services_session_resume_py.patch` | 234 |
| 4 | `0240.services_session_storage_py.patch` | 389 |
| 5 | `0241.services_session_title_py.patch` | 109 |
| 6 | `0242.services_swarm___init___py.patch` | 29 |
| 7 | `0243.services_swarm_agent_name_registry_py.patch` | 143 |
| 8 | `0244.services_swarm_helpers_py.patch` | 43 |
| 9 | `0245.services_swarm_leader_permission_bridge_py.patch` | 303 |
| 10 | `0246.services_swarm_mailbox_py.patch` | 343 |
| 11 | `0247.services_swarm_mailbox_poller_py.patch` | 426 |
| 12 | `0248.services_swarm_permissions_py.patch` | 77 |
| 13 | `0249.services_swarm_team_file_py.patch` | 174 |
| 14 | `0250.services_swarm_team_membership_py.patch` | 52 |
| 15 | `0251.services_swarm_teammate_py.patch` | 140 |
| 16 | `0252.services_tool_execution___init___py.patch` | 55 |
| 17 | `0253.services_tool_execution_can_use_tool_adapter_py.patch` | 12 |
| 18 | `0254.services_tool_execution_orchestrator_py.patch` | 349 |
| 19 | `0255.services_tool_execution_streaming_executor_py.patch` | 531 |
| 20 | `0256.services_tool_execution_tool_execution_py.patch` | 738 |
| 21 | `0257.services_tool_execution_tool_hooks_py.patch` | 431 |
| 22 | `0258.services_tool_execution_tool_result_persistence_py.patch` | 511 |
| 23 | `0259.settings___init___py.patch` | 49 |
| 24 | `0260.settings_change_detector_py.patch` | 29 |
| 25 | `0261.settings_constants_py.patch` | 40 |
| 26 | `0262.settings_managed_path_py.patch` | 42 |
| 27 | `0263.settings_settings_py.patch` | 21 |
| 28 | `0264.settings_types_py.patch` | 410 |
| 29 | `0265.settings_validation_py.patch` | 158 |
| 30 | `0266.skills___init___py.patch` | 169 |
| 31 | `0267.skills_argument_substitution_py.patch` | 70 |
| 32 | `0268.skills_bundled___init___py.patch` | 100 |
| 33 | `0269.skills_bundled_batch_py.patch` | 159 |
| 34 | `0270.skills_bundled_loop_py.patch` | 286 |
| 35 | `0271.skills_bundled_skills_py.patch` | 235 |
| 36 | `0272.skills_create_py.patch` | 77 |
| 37 | `0273.skills_frontmatter_py.patch` | 114 |
| 38 | `0274.skills_loader_py.patch` | 1242 |
| 39 | `0275.skills_mcp_skill_builders_py.patch` | 33 |
| 40 | `0276.skills_model_py.patch` | 118 |
| 41 | `0277.skills_runtime_substitution_py.patch` | 266 |
| 42 | `0278.state___init___py.patch` | 34 |
| 43 | `0279.state_app_state_py.patch` | 621 |
| 44 | `0280.state_cache_state_py.patch` | 307 |
| 45 | `0281.state_session_start_py.patch` | 108 |
| 46 | `0282.task_registry_py.patch` | 238 |
| 47 | `0283.tasks___init___py.patch` | 55 |
| 48 | `0284.tasks_eviction_py.patch` | 142 |
| 49 | `0285.tasks_in_process_teammate_py.patch` | 160 |
| 50 | `0286.tasks_local_agent_py.patch` | 41 |
| 51 | `0287.tasks_local_shell_py.patch` | 63 |
| 52 | `0288.tasks_progress_py.patch` | 229 |
| 53 | `0289.tasks_stop_task_py.patch` | 141 |
| 54 | `0290.tasks_core_py.patch` | 181 |

### Part7 — 11534 行，45 个文件

**范围：** `0291.token_estimation_py.patch` ~ `0335.tool_system_tools_send_user_message_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0291.token_estimation_py.patch` | 497 |
| 2 | `0292.tool_system___init___py.patch` | 65 |
| 3 | `0293.tool_system_build_tool_py.patch` | 226 |
| 4 | `0294.tool_system_context_py.patch` | 425 |
| 5 | `0295.tool_system_defaults_py.patch` | 41 |
| 6 | `0296.tool_system_diff_utils_py.patch` | 102 |
| 7 | `0297.tool_system_errors_py.patch` | 24 |
| 8 | `0298.tool_system_loader_py.patch` | 77 |
| 9 | `0299.tool_system_protocol_py.patch` | 41 |
| 10 | `0300.tool_system_registry_py.patch` | 405 |
| 11 | `0301.tool_system_renderers_py.patch` | 261 |
| 12 | `0302.tool_system_schema_validation_py.patch` | 366 |
| 13 | `0303.tool_system_task_manager_py.patch` | 69 |
| 14 | `0304.tool_system_tool_search_py.patch` | 373 |
| 15 | `0305.tool_system_tools___init___py.patch` | 153 |
| 16 | `0306.tool_system_tools_advisor_py.patch` | 137 |
| 17 | `0307.tool_system_tools_agent_py.patch` | 1032 |
| 18 | `0308.tool_system_tools_ask_user_question_py.patch` | 99 |
| 19 | `0309.tool_system_tools_bash_background_py.patch` | 371 |
| 20 | `0310.tool_system_tools_bash_bash_tool_py.patch` | 1030 |
| 21 | `0311.tool_system_tools_bash_command_semantics_py.patch` | 96 |
| 22 | `0312.tool_system_tools_bash_destructive_warnings_py.patch` | 64 |
| 23 | `0313.tool_system_tools_bash_image_output_py.patch` | 117 |
| 24 | `0314.tool_system_tools_bash_prompt_py.patch` | 118 |
| 25 | `0315.tool_system_tools_bash_read_only_validation_py.patch` | 62 |
| 26 | `0316.tool_system_tools_bash_search_classification_py.patch` | 166 |
| 27 | `0317.tool_system_tools_bash_sleep_detection_py.patch` | 38 |
| 28 | `0318.tool_system_tools_bash_utils_py.patch` | 63 |
| 29 | `0319.tool_system_tools_brief_py.patch` | 59 |
| 30 | `0320.tool_system_tools_config_py.patch` | 116 |
| 31 | `0321.tool_system_tools_cron_py.patch` | 184 |
| 32 | `0322.tool_system_tools_edit_py.patch` | 418 |
| 33 | `0323.tool_system_tools_glob_py.patch` | 204 |
| 34 | `0324.tool_system_tools_grep_py.patch` | 708 |
| 35 | `0325.tool_system_tools_lsp_py.patch` | 54 |
| 36 | `0326.tool_system_tools_mcp_py.patch` | 230 |
| 37 | `0327.tool_system_tools_mcp_resources_py.patch` | 221 |
| 38 | `0328.tool_system_tools_memory_py.patch` | 292 |
| 39 | `0329.tool_system_tools_misc_py.patch` | 86 |
| 40 | `0330.tool_system_tools_notebook_edit_py.patch` | 314 |
| 41 | `0331.tool_system_tools_plan_mode_py.patch` | 465 |
| 42 | `0332.tool_system_tools_read_py.patch` | 813 |
| 43 | `0333.tool_system_tools_schedule_wakeup_py.patch` | 127 |
| 44 | `0334.tool_system_tools_send_message_py.patch` | 636 |
| 45 | `0335.tool_system_tools_send_user_message_py.patch` | 89 |

### Part8 — 11518 行，47 个文件

**范围：** `0336.tool_system_tools_skill_py.patch` ~ `0382.utils_frontmatter_validators_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0336.tool_system_tools_skill_py.patch` | 548 |
| 2 | `0337.tool_system_tools_sleep_py.patch` | 45 |
| 3 | `0338.tool_system_tools_structured_output_py.patch` | 36 |
| 4 | `0339.tool_system_tools_task_stop_py.patch` | 131 |
| 5 | `0340.tool_system_tools_tasks_v2_py.patch` | 792 |
| 6 | `0341.tool_system_tools_team_py.patch` | 101 |
| 7 | `0342.tool_system_tools_todo_write_py.patch` | 85 |
| 8 | `0343.tool_system_tools_tool_search_py.patch` | 77 |
| 9 | `0344.tool_system_tools_web_fetch_py.patch` | 666 |
| 10 | `0345.tool_system_tools_web_search_py.patch` | 402 |
| 11 | `0346.tool_system_tools_worktree_py.patch` | 92 |
| 12 | `0347.tool_system_tools_write_py.patch` | 351 |
| 13 | `0348.tool_system_utils___init___py.patch` | 7 |
| 14 | `0349.tool_system_utils_path_utils_py.patch` | 35 |
| 15 | `0350.tool_system_utils_ripgrep_py.patch` | 270 |
| 16 | `0351.transports___init___py.patch` | 46 |
| 17 | `0352.transports_ccr_client_py.patch` | 393 |
| 18 | `0353.transports_hybrid_transport_py.patch` | 406 |
| 19 | `0354.transports_remote_io_py.patch` | 325 |
| 20 | `0355.transports_serial_batch_event_uploader_py.patch` | 518 |
| 21 | `0356.transports_sse_transport_py.patch` | 253 |
| 22 | `0357.transports_transport_utils_py.patch` | 143 |
| 23 | `0358.transports_websocket_transport_py.patch` | 976 |
| 24 | `0359.transports_worker_state_uploader_py.patch` | 169 |
| 25 | `0360.types___init___py.patch` | 214 |
| 26 | `0361.types_content_blocks_py.patch` | 242 |
| 27 | `0362.types_messages_py.patch` | 842 |
| 28 | `0363.types_stream_events_py.patch` | 142 |
| 29 | `0364.upstreamproxy___init___py.patch` | 14 |
| 30 | `0365.upstreamproxy_ca_bundle_py.patch` | 33 |
| 31 | `0366.upstreamproxy_relay_py.patch` | 47 |
| 32 | `0367.upstreamproxy_upstream_proxy_py.patch` | 60 |
| 33 | `0368.utils___init___py.patch` | 14 |
| 34 | `0369.utils_abort_controller_py.patch` | 122 |
| 35 | `0370.utils_advisor_py.patch` | 875 |
| 36 | `0371.utils_api_preconnect_py.patch` | 58 |
| 37 | `0372.utils_combined_abort_signal_py.patch` | 148 |
| 38 | `0373.utils_deep_link_py.patch` | 77 |
| 39 | `0374.utils_effort_py.patch` | 76 |
| 40 | `0375.utils_env_py.patch` | 46 |
| 41 | `0376.utils_export_formats_py.patch` | 234 |
| 42 | `0377.utils_export_renderer_py.patch` | 864 |
| 43 | `0378.utils_fast_mode_py.patch` | 46 |
| 44 | `0379.utils_file_history_py.patch` | 85 |
| 45 | `0380.utils_file_state_cache_py.patch` | 119 |
| 46 | `0381.utils_format_py.patch` | 111 |
| 47 | `0382.utils_frontmatter_validators_py.patch` | 182 |

### Part9.1 — 4555 行，41 个文件

**范围：** `0383.utils_git_py.patch` ~ `0423.providers_native_capabilities_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0383.utils_git_py.patch` | 395 |
| 2 | `0384.utils_graceful_shutdown_py.patch` | 42 |
| 3 | `0385.utils_image_processor_py.patch` | 554 |
| 4 | `0386.utils_image_validation_py.patch` | 165 |
| 5 | `0387.utils_keychain_stash_py.patch` | 28 |
| 6 | `0388.utils_markdown_config_loader_py.patch` | 69 |
| 7 | `0389.utils_message_mappers_py.patch` | 276 |
| 8 | `0390.utils_message_queue_manager_py.patch` | 123 |
| 9 | `0391.utils_messages_py.patch` | 335 |
| 10 | `0392.utils_pdf_extraction_py.patch` | 114 |
| 11 | `0393.utils_peer_address_py.patch` | 42 |
| 12 | `0394.utils_signal_py.patch` | 103 |
| 13 | `0395.utils_startup_profiler_py.patch` | 24 |
| 14 | `0396.utils_store_py.patch` | 116 |
| 15 | `0397.utils_stream_watchdog_py.patch` | 451 |
| 16 | `0398.utils_task_flags_py.patch` | 58 |
| 17 | `0399.vim___init___py.patch` | 14 |
| 18 | `0400.voice___init___py.patch` | 14 |
| 19 | `0401.agent__outlines_adapter_py.patch` | 28 |
| 20 | `0402.agent_background_runner_py.patch` | 19 |
| 21 | `0403.agent_background_state_py.patch` | 28 |
| 22 | `0404.agent_report_store_py.patch` | 24 |
| 23 | `0405.agent_routing_py.patch` | 23 |
| 24 | `0406.auth_codex_oauth_py.patch` | 8 |
| 25 | `0407.auth_codex_store_py.patch` | 14 |
| 26 | `0408.compact_service___init___py.patch` | 34 |
| 27 | `0409.context_system__gitpython_adapter_py.patch` | 32 |
| 28 | `0410.context_system_claude_md_py.patch` | 23 |
| 29 | `0411.entrypoints_orchestrator_py.patch` | 20 |
| 30 | `0412.entrypoints_tui_py.patch` | 31 |
| 31 | `0413.hooks__pluggy_adapter_py.patch` | 26 |
| 32 | `0414.permissions__treesitter_adapter_py.patch` | 8 |
| 33 | `0415.plugins_base_py.patch` | 140 |
| 34 | `0416.plugins_manager_py.patch` | 455 |
| 35 | `0417.plugins_sandbox_py.patch` | 462 |
| 36 | `0418.plugins_schema_py.patch` | 138 |
| 37 | `0419.providers__litellm_adapter_py.patch` | 31 |
| 38 | `0420.providers_codex_models_py.patch` | 24 |
| 39 | `0421.providers_native___init___py.patch` | 48 |
| 40 | `0422.providers_native_base_py.patch` | 8 |
| 41 | `0423.providers_native_capabilities_py.patch` | 8 |

### Part9.2 — 4575 行，160 个文件

**范围：** `0424.providers_native_gemini_adapter_py.patch` ~ `0583.utils_session_watcher_py.patch`

| # | 文件名 | 行数 |
|---|--------|------|
| 1 | `0424.providers_native_gemini_adapter_py.patch` | 19 |
| 2 | `0425.providers_native_grok_adapter_py.patch` | 21 |
| 3 | `0426.providers_native_openai_adapter_py.patch` | 21 |
| 4 | `0427.providers_openai_codex_provider_py.patch` | 20 |
| 5 | `0428.providers_runtime_py.patch` | 31 |
| 6 | `0429.query_streaming_py.patch` | 8 |
| 7 | `0430.repl___init___py.patch` | 19 |
| 8 | `0431.repl_agent_mention_completer_py.patch` | 19 |
| 9 | `0432.repl_at_file_completer_py.patch` | 40 |
| 10 | `0433.repl_background_escape_py.patch` | 20 |
| 11 | `0434.repl_core_py.patch` | 23 |
| 12 | `0435.repl_live_status_py.patch` | 33 |
| 13 | `0436.repl_task_notifications_py.patch` | 163 |
| 14 | `0437.repl_ui_host_py.patch` | 23 |
| 15 | `0438.replLauncher_py.patch` | 86 |
| 16 | `0439.services_channels___init___py.patch` | 8 |
| 17 | `0440.services_channels_base_py.patch` | 8 |
| 18 | `0441.services_channels_discord_py.patch` | 8 |
| 19 | `0442.services_channels_exceptions_py.patch` | 8 |
| 20 | `0443.services_channels_feishu_py.patch` | 8 |
| 21 | `0444.services_channels_models_py.patch` | 8 |
| 22 | `0445.services_channels_null_channel_py.patch` | 8 |
| 23 | `0446.services_channels_slack_py.patch` | 8 |
| 24 | `0447.services_channels_transport_py.patch` | 8 |
| 25 | `0448.services_computer_use___init___py.patch` | 14 |
| 26 | `0449.services_computer_use_base_py.patch` | 21 |
| 27 | `0450.services_computer_use_dry_run_py.patch` | 20 |
| 28 | `0451.services_computer_use_exceptions_py.patch` | 28 |
| 29 | `0452.services_computer_use_factory_py.patch` | 18 |
| 30 | `0453.services_computer_use_models_py.patch` | 22 |
| 31 | `0454.services_computer_use_platform___init___py.patch` | 18 |
| 32 | `0455.services_computer_use_platform_linux_py.patch` | 14 |
| 33 | `0456.services_computer_use_platform_null_py.patch` | 14 |
| 34 | `0457.services_context_collapse___init___py.patch` | 22 |
| 35 | `0458.services_context_collapse_boundary_py.patch` | 8 |
| 36 | `0459.services_context_collapse_engine_py.patch` | 8 |
| 37 | `0460.services_context_collapse_exceptions_py.patch` | 8 |
| 38 | `0461.services_context_collapse_persistence_py.patch` | 8 |
| 39 | `0462.services_context_collapse_summary_py.patch` | 8 |
| 40 | `0463.services_context_collapse_tokens_py.patch` | 8 |
| 41 | `0464.services_context_collapse_trigger_py.patch` | 8 |
| 42 | `0465.services_feature_gate___init___py.patch` | 37 |
| 43 | `0466.services_feature_gate_cli_py.patch` | 10 |
| 44 | `0467.services_feature_gate_config_py.patch` | 10 |
| 45 | `0468.services_feature_gate_decorators_py.patch` | 15 |
| 46 | `0469.services_feature_gate_registry_py.patch` | 10 |
| 47 | `0470.services_feature_gate_types_py.patch` | 10 |
| 48 | `0471.services_kairos___init___py.patch` | 14 |
| 49 | `0472.services_kairos_brief_py.patch` | 18 |
| 50 | `0473.services_kairos_daily_log_py.patch` | 18 |
| 51 | `0474.services_kairos_exceptions_py.patch` | 28 |
| 52 | `0475.services_kairos_models_py.patch` | 28 |
| 53 | `0476.services_kairos_scheduler_py.patch` | 18 |
| 54 | `0477.services_langfuse___init___py.patch` | 14 |
| 55 | `0478.services_langfuse_client_py.patch` | 28 |
| 56 | `0479.services_langfuse_exporter_py.patch` | 30 |
| 57 | `0480.services_langfuse_sink_py.patch` | 18 |
| 58 | `0481.services_session_migrate_py.patch` | 30 |
| 59 | `0482.services_tail_follower_py.patch` | 20 |
| 60 | `0483.services_templates___init___py.patch` | 14 |
| 61 | `0484.services_ultraplan___init___py.patch` | 14 |
| 62 | `0485.settings_pydantic_adapter_py.patch` | 38 |
| 63 | `0486.skills__frontmatter_adapter_py.patch` | 8 |
| 64 | `0487.tasks_dream___init___py.patch` | 40 |
| 65 | `0488.tasks_dream_dream_task_py.patch` | 44 |
| 66 | `0489.tool_system_tools_ask_issue_author_py.patch` | 8 |
| 67 | `0490.tool_system_tools_create_agent_tool_py.patch` | 8 |
| 68 | `0491.tool_system_tools_progress_report_py.patch` | 8 |
| 69 | `0492.tool_system_tools_task_directives_py.patch` | 8 |
| 70 | `0493.tool_system_tools_task_inspect_py.patch` | 8 |
| 71 | `0494.tui___init___py.patch` | 26 |
| 72 | `0495.tui_a11y_py.patch` | 27 |
| 73 | `0496.tui_agent_bridge_py.patch` | 22 |
| 74 | `0497.tui_app_py.patch` | 22 |
| 75 | `0498.tui_commands_py.patch` | 27 |
| 76 | `0499.tui_declared_cursor_py.patch` | 27 |
| 77 | `0500.tui_focus_router_py.patch` | 24 |
| 78 | `0501.tui_frame_metrics_py.patch` | 27 |
| 79 | `0502.tui_history_store_py.patch` | 24 |
| 80 | `0503.tui_hyperlinks_py.patch` | 25 |
| 81 | `0504.tui_keybindings_py.patch` | 25 |
| 82 | `0505.tui_markdown_cache_py.patch` | 25 |
| 83 | `0506.tui_messages_py.patch` | 36 |
| 84 | `0507.tui_paste_py.patch` | 24 |
| 85 | `0508.tui_screens___init___py.patch` | 24 |
| 86 | `0509.tui_screens_ask_user_question_py.patch` | 20 |
| 87 | `0510.tui_screens_cost_threshold_py.patch` | 22 |
| 88 | `0511.tui_screens_dialog_base_py.patch` | 22 |
| 89 | `0512.tui_screens_diff_dialog_py.patch` | 23 |
| 90 | `0513.tui_screens_doctor_py.patch` | 22 |
| 91 | `0514.tui_screens_effort_picker_py.patch` | 22 |
| 92 | `0515.tui_screens_exit_flow_py.patch` | 22 |
| 93 | `0516.tui_screens_generic_input_py.patch` | 22 |
| 94 | `0517.tui_screens_generic_select_py.patch` | 22 |
| 95 | `0518.tui_screens_history_search_py.patch` | 24 |
| 96 | `0519.tui_screens_idle_return_py.patch` | 22 |
| 97 | `0520.tui_screens_mcp_approval_py.patch` | 87 |
| 98 | `0521.tui_screens_mcp_dialogs_py.patch` | 25 |
| 99 | `0522.tui_screens_memory_save_py.patch` | 75 |
| 100 | `0523.tui_screens_message_selector_py.patch` | 23 |
| 101 | `0524.tui_screens_model_picker_py.patch` | 22 |
| 102 | `0525.tui_screens_monitor_panel_py.patch` | 20 |
| 103 | `0526.tui_screens_permission_modal_py.patch` | 23 |
| 104 | `0527.tui_screens_permission_mode_picker_py.patch` | 20 |
| 105 | `0528.tui_screens_repl_py.patch` | 22 |
| 106 | `0529.tui_screens_resume_conversation_py.patch` | 23 |
| 107 | `0530.tui_screens_startup_gates_py.patch` | 208 |
| 108 | `0531.tui_screens_theme_picker_py.patch` | 22 |
| 109 | `0532.tui_screens_workflow_dialog_py.patch` | 294 |
| 110 | `0533.tui_screens_workspace_search_py.patch` | 313 |
| 111 | `0534.tui_state_py.patch` | 26 |
| 112 | `0535.tui_terminal_chrome_py.patch` | 31 |
| 113 | `0536.tui_theme_py.patch` | 26 |
| 114 | `0537.tui_ui_host_py.patch` | 22 |
| 115 | `0538.tui_vim_py.patch` | 24 |
| 116 | `0539.tui_vim_buffer_py.patch` | 24 |
| 117 | `0540.tui_vim_find_py.patch` | 22 |
| 118 | `0541.tui_vim_operators_py.patch` | 25 |
| 119 | `0542.tui_vim_persistent_py.patch` | 33 |
| 120 | `0543.tui_vim_search_py.patch` | 26 |
| 121 | `0544.tui_vim_state_py.patch` | 35 |
| 122 | `0545.tui_vim_text_objects_py.patch` | 22 |
| 123 | `0546.tui_vim_visual_py.patch` | 24 |
| 124 | `0547.tui_widgets___init___py.patch` | 20 |
| 125 | `0548.tui_widgets_fullscreen_layout_py.patch` | 22 |
| 126 | `0549.tui_widgets_header_py.patch` | 22 |
| 127 | `0550.tui_widgets_messages___init___py.patch` | 20 |
| 128 | `0551.tui_widgets_messages_assistant_advisor_py.patch` | 22 |
| 129 | `0552.tui_widgets_messages_assistant_text_py.patch` | 22 |
| 130 | `0553.tui_widgets_messages_assistant_thinking_py.patch` | 23 |
| 131 | `0554.tui_widgets_messages_assistant_tool_use_py.patch` | 22 |
| 132 | `0555.tui_widgets_messages_base_py.patch` | 25 |
| 133 | `0556.tui_widgets_messages_tool_result_py.patch` | 22 |
| 134 | `0557.tui_widgets_messages_user_text_py.patch` | 22 |
| 135 | `0558.tui_widgets_prompt_input_py.patch` | 23 |
| 136 | `0559.tui_widgets_prompt_input_footer_py.patch` | 23 |
| 137 | `0560.tui_widgets_prompt_input_mode_indicator_py.patch` | 22 |
| 138 | `0561.tui_widgets_queued_commands_py.patch` | 127 |
| 139 | `0562.tui_widgets_select_list_py.patch` | 23 |
| 140 | `0563.tui_widgets_session_preview_py.patch` | 23 |
| 141 | `0564.tui_widgets_shortcuts_help_py.patch` | 109 |
| 142 | `0565.tui_widgets_status_line_py.patch` | 22 |
| 143 | `0566.tui_widgets_structured_diff_py.patch` | 27 |
| 144 | `0567.tui_widgets_task_list_py.patch` | 26 |
| 145 | `0568.tui_widgets_tool_activity___init___py.patch` | 22 |
| 146 | `0569.tui_widgets_tool_activity_base_py.patch` | 23 |
| 147 | `0570.tui_widgets_tool_activity_bash_py.patch` | 22 |
| 148 | `0571.tui_widgets_tool_activity_default_py.patch` | 22 |
| 149 | `0572.tui_widgets_tool_activity_edit_py.patch` | 22 |
| 150 | `0573.tui_widgets_tool_activity_glob_py.patch` | 22 |
| 151 | `0574.tui_widgets_tool_activity_grep_py.patch` | 22 |
| 152 | `0575.tui_widgets_tool_activity_read_py.patch` | 22 |
| 153 | `0576.tui_widgets_tool_activity_task_py.patch` | 22 |
| 154 | `0577.tui_widgets_tool_activity_write_py.patch` | 22 |
| 155 | `0578.tui_widgets_transcript_search_py.patch` | 24 |
| 156 | `0579.tui_widgets_transcript_view_py.patch` | 23 |
| 157 | `0580.utils_agent_mention_completer_py.patch` | 19 |
| 158 | `0581.utils_at_file_completer_py.patch` | 13 |
| 159 | `0582.utils_cache_warning_py.patch` | 24 |
| 160 | `0583.utils_session_watcher_py.patch` | 20 |


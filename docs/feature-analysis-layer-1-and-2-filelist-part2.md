# 特性群分析：clawcodex_ext 与 extensions — 详细文件清单（extensions）

> 生成日期：2026-07-25
> 统计口径：`.py` 文件，排除 `__pycache__`、`.egg-info`。

## extensions/ 文件清单

### 【G1】🤖 编排器 & 自动工作流

**`orchestrator/`**（101 files, 43,735 lines）
```
  orchestrator/__init__.py
  orchestrator/agent_runner.py
  orchestrator/approval_policy.py
  orchestrator/asciicast_sink.py
  orchestrator/channel_sink.py
  orchestrator/clarification.py
  orchestrator/clarification_queue.py
  orchestrator/cli/__init__.py
  orchestrator/cli/attach.py
  orchestrator/cli/dashboard.py
  orchestrator/cli/issue.py
  orchestrator/cli/resume_session.py
  orchestrator/cli/rules.py
  orchestrator/cli/server.py
  orchestrator/cli/takeover.py
  orchestrator/cli/workflow.py
  orchestrator/cli/workspace.py
  orchestrator/config/__init__.py
  orchestrator/config/schema.py
  orchestrator/control_socket.py
  orchestrator/debug_log.py
  orchestrator/event_tailer.py
  orchestrator/events/__init__.py
  orchestrator/events/emitter.py
  orchestrator/events/formatter.py
  orchestrator/events/types.py
  orchestrator/feishu_activity_sink.py
  orchestrator/git_sync.py
  orchestrator/im_gateway_client.py
  orchestrator/issue.py
  orchestrator/issue_clarifier/__init__.py
  orchestrator/issue_clarifier/cache.py
  orchestrator/issue_clarifier/gate.py
  orchestrator/issue_clarifier/models.py
  orchestrator/issue_clarifier/parser.py
  orchestrator/issue_clarifier/prompt.py
  orchestrator/issue_clarifier/service.py
  orchestrator/issue_registry.py
  orchestrator/issue_state_cache.py
  orchestrator/linear/__init__.py
  orchestrator/linear/adapter.py
  orchestrator/linear/client.py
  orchestrator/linear/issue.py
  orchestrator/local_tracker/__init__.py
  orchestrator/local_tracker/adapter.py
  orchestrator/local_tracker/parser.py
  orchestrator/logging_setup.py
  orchestrator/mode_router.py
  orchestrator/mode_selector.py
  orchestrator/modes/__init__.py
  orchestrator/modes/base.py
  orchestrator/modes/coordinator.py
  orchestrator/modes/debate.py
  orchestrator/modes/pipeline.py
  orchestrator/modes/single.py
  orchestrator/modes/swarm.py
  orchestrator/orchestrator.py
  orchestrator/premise_check.py
  orchestrator/progress_reporter.py
  orchestrator/progress_sink.py
  orchestrator/prompt_builder.py
  orchestrator/repo_tracker/__init__.py
  orchestrator/repo_tracker/adapter.py
  orchestrator/repo_tracker/client.py
  orchestrator/report_writer.py
  orchestrator/repro_gate.py
  orchestrator/review_feedback.py
  orchestrator/rules_learner.py
  orchestrator/session_viewer.py
  orchestrator/state_journal.py
  orchestrator/state_journal_sink.py
  orchestrator/status_dashboard.py
  orchestrator/task_decomposition/__init__.py
  orchestrator/task_decomposition/models.py
  orchestrator/task_decomposition/planner.py
  orchestrator/templates/__init__.py
  orchestrator/tool_event_log.py
  orchestrator/tracker.py
  orchestrator/workflow.py
  orchestrator/workflow_engine/__init__.py
  orchestrator/workflow_engine/audit.py
  orchestrator/workflow_engine/checkpoint.py
  orchestrator/workflow_engine/cost.py
  orchestrator/workflow_engine/decision_handler.py
  orchestrator/workflow_engine/engine.py
  orchestrator/workflow_engine/errors.py
  orchestrator/workflow_engine/event_bus.py
  orchestrator/workflow_engine/gate_handler.py
  orchestrator/workflow_engine/gate_rollback.py
  orchestrator/workflow_engine/observability.py
  orchestrator/workflow_engine/rollback.py
  orchestrator/workflow_engine/stage_runner.py
  orchestrator/workflow_engine/validators/__init__.py
  orchestrator/workflow_engine/validators/custom.py
  orchestrator/workflow_engine/validators/llm_judge.py
  orchestrator/workflow_engine/workflow_state.py
  orchestrator/workflow_orchestrator.py
  orchestrator/workflow_store.py
  orchestrator/workspace.py
  orchestrator/workspace_locator.py
  orchestrator/workspace_verify.py
```

**`orchestrator_runtime/`**（27 files, 3,263 lines）
```
  orchestrator_runtime/__init__.py
  orchestrator_runtime/adapters/__init__.py
  orchestrator_runtime/adapters/clawcodex_agent_runtime.py
  orchestrator_runtime/adapters/clawcodex_bootstrap_state.py
  orchestrator_runtime/adapters/clawcodex_compat.py
  orchestrator_runtime/adapters/clawcodex_coordinator.py
  orchestrator_runtime/adapters/clawcodex_im_channel.py
  orchestrator_runtime/adapters/clawcodex_session_storage.py
  orchestrator_runtime/protocols/__init__.py
  orchestrator_runtime/protocols/agent_runtime.py
  orchestrator_runtime/protocols/backend.py
  orchestrator_runtime/protocols/coordinator.py
  orchestrator_runtime/protocols/diagnostics.py
  orchestrator_runtime/protocols/git_backend.py
  orchestrator_runtime/protocols/im_channel.py
  orchestrator_runtime/protocols/intent_focus.py
  orchestrator_runtime/protocols/messages.py
  orchestrator_runtime/protocols/provider.py
  orchestrator_runtime/protocols/session_storage.py
  orchestrator_runtime/protocols/workspace_tooling.py
  orchestrator_runtime/utils/__init__.py
  orchestrator_runtime/utils/api_errors.py
  orchestrator_runtime/utils/bootstrap_state.py
  orchestrator_runtime/utils/diagnostics_impl.py
  orchestrator_runtime/utils/git_backend_impl.py
  orchestrator_runtime/utils/intent_focus_impl.py
  orchestrator_runtime/utils/messages_impl.py
```

**`context_providers/`**（4 files, 276 lines）
```
  context_providers/__init__.py
  context_providers/from_ci.py
  context_providers/from_config.py
  context_providers/from_issue.py
```

---

### 【G2】🏭 守护进程 & 后台服务

**`daemon/`**（15 files, 2,681 lines）
```
  daemon/__init__.py
  daemon/cli.py
  daemon/config.py
  daemon/constants.py
  daemon/errors.py
  daemon/lifecycle.py
  daemon/state.py
  daemon/supervisor.py
  daemon/worker_main.py
  daemon/worker_registry.py
  daemon/workers/__init__.py
  daemon/workers/base.py
  daemon/workers/cron.py
  daemon/workers/remote_control.py
  daemon/workers/task_worker.py
```

**`im_gateway/`**（3 files, 729 lines）
```
  im_gateway/__init__.py
  im_gateway/host_agent.py
  im_gateway/server.py
```

---

### 【G3】📋 LKB（逻辑看板）

**`lkb/`**（74 files, 26,357 lines）
```
  lkb/src/lkb/__init__.py
  lkb/src/lkb/acceptance_template.py
  lkb/src/lkb/acceptance_template_governance.py
  lkb/src/lkb/acceptance_template_prompt.py
  lkb/src/lkb/acceptance_template_seed.py
  lkb/src/lkb/adapters.py
  lkb/src/lkb/ambiguity_detector.py
  lkb/src/lkb/atp/__init__.py
  lkb/src/lkb/atp/base.py
  lkb/src/lkb/atp/mace4.py
  lkb/src/lkb/atp/prover9.py
  lkb/src/lkb/atp/vampire.py
  lkb/src/lkb/audit.py
  lkb/src/lkb/causal.py
  lkb/src/lkb/commit_gate_fuzzy.py
  lkb/src/lkb/context_adapter.py
  lkb/src/lkb/decomposer.py
  lkb/src/lkb/explain.py
  lkb/src/lkb/external_config.py
  lkb/src/lkb/external_config_lint.py
  lkb/src/lkb/flags.py
  lkb/src/lkb/fuzzy_patterns.py
  lkb/src/lkb/fuzzy_types.py
  lkb/src/lkb/glossary.py
  lkb/src/lkb/ir.py
  lkb/src/lkb/ir_hash.py
  lkb/src/lkb/ir_renderer.py
  lkb/src/lkb/llm_fact_extractor.py
  lkb/src/lkb/method_coverage.py
  lkb/src/lkb/method_governance.py
  lkb/src/lkb/method_library.py
  lkb/src/lkb/method_prompt.py
  lkb/src/lkb/method_proposer.py
  lkb/src/lkb/method_seed.py
  lkb/src/lkb/metrics.py
  lkb/src/lkb/multiworld_validator.py
  lkb/src/lkb/ontology_graph.py
  lkb/src/lkb/operation_schema.py
  lkb/src/lkb/orchestrator.py
  lkb/src/lkb/predicate_extractor.py
  lkb/src/lkb/rule_engine.py
  lkb/src/lkb/runtime.py
  lkb/src/lkb/scheduling_solver.py
  lkb/src/lkb/service.py
  lkb/src/lkb/solver_adapter.py
  lkb/src/lkb/solver_atp.py
  lkb/src/lkb/solver_limits.py
  lkb/src/lkb/solver_pipeline.py
  lkb/src/lkb/truth_maintenance.py
  lkb/src/lkb/types.py
  lkb/src/lkb/world_generator.py
  lkb/mcp/server.py
  lkb/mcp/tools/__init__.py
  lkb/mcp/tools/audit.py
  lkb/mcp/tools/decompose.py
  lkb/mcp/tools/explain.py
  lkb/mcp/tools/validate.py
  lkb/cli/main.py
  lkb/tests/__init__.py
  lkb/tests/test_audit.py
  lkb/tests/test_f142_external_atp.py
  lkb/tests/test_f151_eval_harness.py
  lkb/tests/test_f153_method_governance.py
  lkb/tests/test_f154_external_config.py
  lkb/tests/test_f155_acceptance_template.py
  lkb/tests/test_fuzzy_multiworld.py
  lkb/tests/test_rule_engine_layer1.py
  lkb/tests/test_solver_layer.py
  lkb/tests/test_solver_layer_atp.py
  lkb/tests/test_solver_layer_clingo.py
  lkb/tests/test_solver_layer_datalog.py
  lkb/tests/test_solver_layer_z3.py
  lkb/tests/test_truth_maintenance.py
  lkb/tests/test_validation_runs.py
```

---

### 【G4】📄 SOP 编译器

**`sop_converter/`**（159 files, 30,316 lines）
```
  sop_converter/__init__.py
  sop_converter/adapters/__init__.py
  sop_converter/adapters/agent_definition_adapter.py
  sop_converter/adapters/permission_adapter.py
  sop_converter/adapters/skill_adapter.py
  sop_converter/adapters/sop_provider_adapter.py
  sop_converter/adapters/tool_authoring_adapter.py
  sop_converter/agent_builder.py
  sop_converter/agent_catalog.py
  sop_converter/agent_catalog_resolver.py
  sop_converter/agent_md_writer.py
  sop_converter/agent_runtime.py
  sop_converter/asciicast_projector.py
  sop_converter/bundle_agents.py
  sop_converter/bundle_context.py
  sop_converter/bundle_discovery.py
  sop_converter/bundle_manifest.py
  sop_converter/bundle_resources.py
  sop_converter/bundle_skills.py
  sop_converter/bundle_venv.py
  sop_converter/bundle_workflow.py
  sop_converter/composite_runtime.py
  sop_converter/composite_workflows.py
  sop_converter/convert_sop_skill.py
  sop_converter/core/__init__.py
  sop_converter/core/agent_catalog.py
  sop_converter/core/agent_catalog_resolver.py
  sop_converter/core/agent_runtime.py
  sop_converter/core/asciicast_projector.py
  sop_converter/core/bundle_manifest.py
  sop_converter/core/bundle_resources.py
  sop_converter/core/bundle_venv.py
  sop_converter/core/bundle_workflow.py
  sop_converter/core/default_agent.py
  sop_converter/core/dependency/__init__.py
  sop_converter/core/dependency/detector.py
  sop_converter/core/dependency/heuristics.py
  sop_converter/core/dependency/models.py
  sop_converter/core/dependency/reader.py
  sop_converter/core/dependency/writer.py
  sop_converter/core/heuristics/lifecycle.py
  sop_converter/core/import_alias_resolver.py
  sop_converter/core/intent_tags.py
  sop_converter/core/path_resolver.py
  sop_converter/core/resource_catalog.py
  sop_converter/core/resource_handlers.py
  sop_converter/core/runtime_paths.py
  sop_converter/core/sdk_dependency_resolver.py
  sop_converter/core/sdk_parser.py
  sop_converter/core/sdk_serialization.py
  sop_converter/core/search_tags.py
  sop_converter/core/sop_prompts.py
  sop_converter/core/source_parser.py
  sop_converter/core/templates.py
  sop_converter/core/tool_dependencies.py
  sop_converter/core/tool_retrieval.py
  sop_converter/core/tool_state.py
  sop_converter/core/type_schema.py
  sop_converter/core/workflow_project.py
  sop_converter/cross_domain_orchestration.py
  sop_converter/default_agent.py
  sop_converter/import_alias_resolver.py
  sop_converter/intent_tags.py
  sop_converter/path_resolver.py
  sop_converter/resource_catalog.py
  sop_converter/resource_handlers.py
  sop_converter/runtime/__init__.py
  sop_converter/runtime/agent_builder.py
  sop_converter/runtime/agent_md_writer.py
  sop_converter/runtime/bundle_agents.py
  sop_converter/runtime/bundle_context.py
  sop_converter/runtime/bundle_discovery.py
  sop_converter/runtime/bundle_skills.py
  sop_converter/runtime/composite_runtime.py
  sop_converter/runtime/composite_tools/__init__.py
  sop_converter/runtime/composite_tools/builtin.py
  sop_converter/runtime/composite_tools/models.py
  sop_converter/runtime/composite_tools/registry.py
  sop_converter/runtime/composite_tools/scripts/invoke_existing_agent_wrapper.py
  sop_converter/runtime/composite_workflows.py
  sop_converter/runtime/convert_sop_skill.py
  sop_converter/runtime/cross_domain_orchestration.py
  sop_converter/runtime/macros/__init__.py
  sop_converter/runtime/macros/catalog.py
  sop_converter/runtime/macros/convert.py
  sop_converter/runtime/macros/errors.py
  sop_converter/runtime/macros/loader.py
  sop_converter/runtime/macros/models.py
  sop_converter/runtime/macros/overview_intent.py
  sop_converter/runtime/macros/persist.py
  sop_converter/runtime/macros/routing.py
  sop_converter/runtime/macros/templates/__init__.py
  sop_converter/runtime/macros/validation.py
  sop_converter/runtime/sdk_overview.py
  sop_converter/runtime/skill_grouper.py
  sop_converter/runtime/sop_exploration_guard.py
  sop_converter/runtime/sop_routing.py
  sop_converter/runtime/startup_agent.py
  sop_converter/runtime/task_guide.py
  sop_converter/runtime/tool_registry_bridge.py
  sop_converter/runtime_paths.py
  sop_converter/sdk_dependency_resolver.py
  sop_converter/sdk_overview.py
  sop_converter/sdk_parser.py
  sop_converter/sdk_serialization.py
  sop_converter/search_tags.py
  sop_converter/skill_grouper.py
  sop_converter/sop_exploration_guard.py
  sop_converter/sop_prompts.py
  sop_converter/sop_routing.py
  sop_converter/source_parser.py
  sop_converter/startup_agent.py
  sop_converter/task_guide.py
  sop_converter/templates.py
  sop_converter/tool_dependencies.py
  sop_converter/tool_registry_bridge.py
  sop_converter/tool_retrieval.py
  sop_converter/tool_state.py
  sop_converter/type_schema.py
  sop_converter/workflow_mode/__init__.py
  sop_converter/workflow_mode/ast_helpers.py
  sop_converter/workflow_mode/bridge/__init__.py
  sop_converter/workflow_mode/bridge/cli_discovery.py
  sop_converter/workflow_mode/bridge/dispatch.py
  sop_converter/workflow_mode/bridge/generator.py
  sop_converter/workflow_mode/bridge/health_check.py
  sop_converter/workflow_mode/bridge/mcp_adapter.py
  sop_converter/workflow_mode/capability/__init__.py
  sop_converter/workflow_mode/capability/analyzer.py
  sop_converter/workflow_mode/capability/arc_mapper.py
  sop_converter/workflow_mode/capability/mapper.py
  sop_converter/workflow_mode/capability/models.py
  sop_converter/workflow_mode/capability/patterns.py
  sop_converter/workflow_mode/completions.py
  sop_converter/workflow_mode/discriminator.py
  sop_converter/workflow_mode/extractors/__init__.py
  sop_converter/workflow_mode/extractors/adapters/__init__.py
  sop_converter/workflow_mode/extractors/adapters/arc.py
  sop_converter/workflow_mode/extractors/adapters/generic.py
  sop_converter/workflow_mode/extractors/base.py
  sop_converter/workflow_mode/extractors/models.py
  sop_converter/workflow_mode/extractors/preview.py
  sop_converter/workflow_mode/extractors/registry.py
  sop_converter/workflow_mode/generator/__init__.py
  sop_converter/workflow_mode/generator/agent_def_gen.py
  sop_converter/workflow_mode/generator/artifact_semantics.py
  sop_converter/workflow_mode/generator/overview_gen.py
  sop_converter/workflow_mode/generator/skill_gen.py
  sop_converter/workflow_mode/generator/tool_gen.py
  sop_converter/workflow_mode/heuristics.py
  sop_converter/workflow_mode/mapping.py
  sop_converter/workflow_mode/models.py
  sop_converter/workflow_mode/pipeline.py
  sop_converter/workflow_mode/scan_context.py
  sop_converter/workflow_mode/schema/__init__.py
  sop_converter/workflow_mode/schema/dag_validator.py
  sop_converter/workflow_mode/schema/emitter.py
  sop_converter/workflow_mode/schema/validator_spec.py
  sop_converter/workflow_project.py
```

---

### 【G5】🧪 协议契约层 & 外部 API

**`capabilities/`**（21 files, 2,282 lines）
```
  capabilities/__init__.py
  capabilities/acp_protocol.py
  capabilities/adapter_protocol.py
  capabilities/agent_definition_protocol.py
  capabilities/agent_protocol.py
  capabilities/automation_state_protocol.py
  capabilities/context_protocol.py
  capabilities/daemon_protocol.py
  capabilities/dashboard_entry.py
  capabilities/event_protocol.py
  capabilities/headless_protocol.py
  capabilities/headless_runner.py
  capabilities/permission_protocol.py
  capabilities/provider_protocol.py
  capabilities/recorder.py
  capabilities/skill_protocol.py
  capabilities/sop_provider_protocol.py
  capabilities/task_protocol.py
  capabilities/team_memory_protocol.py
  capabilities/tool_authoring_protocol.py
  capabilities/tool_protocol.py
```

**`api/`**（5 files, 968 lines）
```
  api/__init__.py
  api/debug_log.py
  api/orchestration.py
  api/query.py
  api/query_middleware.py
```

**`remote_api/`**（12 files, 2,665 lines）
```
  remote_api/__init__.py
  remote_api/auth.py
  remote_api/cli.py
  remote_api/core.py
  remote_api/errors.py
  remote_api/normalization.py
  remote_api/runner.py
  remote_api/server.py
  remote_api/sse.py
  remote_api/state.py
  remote_api/state_reporter.py
  remote_api/stdlib_server.py
```

---

### 【G6】📊 可视化 & 仪表盘

**`visualizer/`**（28 files, 6,273 lines）
```
  visualizer/__init__.py
  visualizer/_rendering.py
  visualizer/builders/__init__.py
  visualizer/builders/agent_tree_builder.py
  visualizer/builders/agent_tree_layout.py
  visualizer/builders/anomaly_builder.py
  visualizer/builders/export_builder.py
  visualizer/builders/operation_categorizer.py
  visualizer/builders/stats_builder.py
  visualizer/builders/timeline_builder.py
  visualizer/cli.py
  visualizer/fixtures/__init__.py
  visualizer/import_router.py
  visualizer/models/__init__.py
  visualizer/models/viz_models.py
  visualizer/orchestrator_link.py
  visualizer/parsers/__init__.py
  visualizer/parsers/multi_agent_parser.py
  visualizer/parsers/orchestrator_state_parser.py
  visualizer/parsers/session_parser.py
  visualizer/parsers/stats_parser.py
  visualizer/parsers/tool_events_parser.py
  visualizer/parsers/transcript_parser.py
  visualizer/protocols/__init__.py
  visualizer/protocols/dashboard.py
  visualizer/protocols/recorder.py
  visualizer/server.py
  visualizer/ws.py
```

**`agent_dashboard/`**（11 files, 1,665 lines）
```
  agent_dashboard/__init__.py
  agent_dashboard/source_registry.py
  agent_dashboard/sources/__init__.py
  agent_dashboard/sources/goal_source.py
  agent_dashboard/sources/orchestrator_source.py
  agent_dashboard/sources/sop_source.py
  agent_dashboard/sources/tasks_source.py
  agent_dashboard/store.py
  agent_dashboard/tools/__init__.py
  agent_dashboard/tools/dashboard_get.py
  agent_dashboard/tools/dashboard_list.py
```

---

### 【G7】🔌 扩展集成层

**`skills_ext/`**（10 files, 995 lines）
```
  skills_ext/__init__.py
  skills_ext/agent_config.py
  skills_ext/bundled/__init__.py
  skills_ext/bundled/dream.py
  skills_ext/bundled/sop_to_agent.py
  skills_ext/bundles.py
  skills_ext/cache.py
  skills_ext/hooks.py
  skills_ext/paths.py
  skills_ext/registry_ext.py
```

**`tool_system_ext/`**（6 files, 537 lines）
```
  tool_system_ext/__init__.py
  tool_system_ext/agent_config.py
  tool_system_ext/bundles.py
  tool_system_ext/registration.py
  tool_system_ext/registry_ext.py
  tool_system_ext/team_filter.py
```

**`providers_ext/`**（2 files, 51 lines）
```
  providers_ext/__init__.py
  providers_ext/litellm_provider.py
```

**`permissions/`**（2 files, 130 lines）
```
  permissions/__init__.py
  permissions/perms_reader.py
```

**`agent/`**（2 files, 360 lines）
```
  agent/__init__.py
  agent/session_persist.py
```

**`agents/`**（4 files, 1,408 lines）
```
  agents/__init__.py
  agents/team_memory.py
  agents/team_memory_integration.py
  agents/team_memory_policy.py
```

**`ports/`**（10 files, 5,945 lines）
```
  ports/__init__.py
  ports/bridge/__init__.py
  ports/bridge/bridge_main.py
  ports/bridge/remote_bridge_core.py
  ports/bridge/repl_bridge.py
  ports/bridge/session_runner.py
  ports/transports/__init__.py
  ports/transports/hybrid_v1.py
  ports/transports/serial_uploader.py
  ports/transports/websocket_v1.py
```

---

### 【G8】🔬 实验与辅助系统

**`prompt_lab/`**（6 files, 232 lines）
```
  prompt_lab/__init__.py
  prompt_lab/capabilities.py
  prompt_lab/experiments.py
  prompt_lab/sinks/__init__.py
  prompt_lab/sinks/ndjson.py
  prompt_lab/variants.py
```

**`recording/`**（21 files, 5,326 lines）
```
  recording/__init__.py
  recording/_factories.py
  recording/asciicast_writer.py
  recording/auto_demo.py
  recording/cast_to_mp4_cli.py
  recording/cli.py
  recording/config.py
  recording/examples/logical_kanban_repl_demo.py
  recording/examples/record_real_repl.py
  recording/examples/repl_demo_driver.py
  recording/examples/repl_orchestrator_showcase.py
  recording/headless_source.py
  recording/pty_recorder.py
  recording/query_forwarder.py
  recording/registry.py
  recording/renderers.py
  recording/repl_source.py
  recording/tools/__init__.py
  recording/tools/cast_to_mp4.py
  recording/validate_cast.py
  recording/visualizer_dashboard_source.py
```

**`multimodel/`**（0 files, 0 lines — 空占位）
```
```

**`trae/`**（3 files, 873 lines）
```
  trae/__init__.py
  trae/acp_cli_adapter.py
  trae/mcp_bridge.py
```

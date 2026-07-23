# F-157 宏 / 原子分层检索手工验收

> 验收范围：MacroRoute coverage、ToolRetrievalIndex、exclusive suppression、preflight 回滚、active tool shadow guard、普通评分偏置与 Task Guide 消歧。  
> 本流程不会删除或重建 `.venv`。

## 1. 建议执行顺序

在仓库根目录 `D:\projects\clawcodex` 执行。

### 1.1 F-157 核心用例

```powershell
python -m pytest -q tests/tool/test_tool_search_layered_retrieval.py tests/misc/test_sop_tool_retrieval_index.py tests/misc/test_sop_macro_coverage_validation.py
```

预期：全部通过。

### 1.2 F-57 宏与 convert 联动

```powershell
python -m pytest -q tests/tool/test_tool_search_macro_routes.py tests/misc/test_composite_tools.py tests/misc/test_sop_macro_convert_phase4.py tests/misc/test_sop_converter_lifecycle_prompts.py
```

重点确认：

- builtin route 包含 `intent_key=agent.invoke_existing`。
- builtin route 覆盖 `llmagent-invoke`、`send-to-agent`。
- convert 生成 `.clawcodex/tool-retrieval.yaml`。
- Task Guide 不再同时推荐被宏覆盖的 lifecycle 原子入口。

### 1.3 ToolSearch 与 workflow 回归

```powershell
python -m pytest -q tests/tool/test_tool_search_matching.py tests/misc/test_sop_composite_runtime.py tests/misc/test_workflow_tool_authoring.py tests/misc/test_sop_converter_invoke_existing_agent.py
```

预期：原有 select、lifecycle reorder、workflow dispatch 和 F-56 恢复链不回退。

## 2. 核心行为验收矩阵

| 场景 | 用例 | 预期 |
|------|------|------|
| verified exclusive | `test_verified_exclusive_hides_covered_atomics` | 只返回宏；原子从 `options.tools` 隐藏 |
| 陈旧工具引用 | `test_shadow_guard_blocks_stale_atomic_reference_then_macro_restores` | 原子调用返回 `tool_shadowed_by_macro` |
| 宏不可用 | `test_macro_preflight_failure_restores_atomics_same_search` | 同次 ToolSearch 恢复 covered atomic |
| 显式技术覆盖 | `test_new_search_restores_previous_hidden_tools` | `select:<atomic>` 清除旧 suppression |
| 普通评分 | `test_same_semantic_tier_prefers_macro_over_covered_atomic` | 同 tier 时宏排在覆盖原子之前 |
| prefer | `test_prefer_route_keeps_atomic_candidates` | 宏置顶但不隐藏原子 |
| metadata | `test_yaml_round_trip` | retrieval index 可持久化/加载 |
| convert 校验 | `TestMacroCoverageValidation` | 缺 intent、缺 coverage、歧义、自覆盖均拒绝 |

## 3. 自然语言 E2E 验收

使用已重新执行 `sop convert`、且包含 `invoke-existing-agent` 的 JiuwenAgent bundle。

### 3.1 正常调用

1. 创建 `verify-bot`，确认返回 `created_persisted: true`。
2. 输入：`用 verify-bot 回复 ping`。
3. 观察 ToolSearch 结果。

预期诊断：

```json
{
  "matches": ["invoke-existing-agent"],
  "retrieval": {
    "intent_key": "agent.invoke_existing",
    "selection": "exclusive",
    "selected_layer": "macro",
    "preflight": "ready"
  }
}
```

`suppressed_tools` 应包含 bundle 中实际解析出的 `llmagent-invoke` / `send-to-agent` 完整工具名，最终回复保持 `ping`。

### 3.2 SDK 词汇漂移

输入：`llmagent invoke verify-bot ping`。

预期：仍只返回并调用 `invoke-existing-agent`，不会把 SDK `llmagent-invoke` 暴露为并列候选。

### 3.3 相邻意图

分别输入：

```text
创建一个 agent
配置 verify-bot
删除 verify-bot
列出已有 agent
```

预期：不提交 `agent.invoke_existing` exclusive plan，不隐藏这些意图实际需要的工具。

## 4. 产物检查

重新 convert 后检查：

```powershell
Get-Content -Raw <bundle>/.clawcodex/tool-retrieval.yaml
```

至少应包含：

```yaml
tools:
  invoke-existing-agent:
    layer: macro
    call_type: workflow
coverage:
  - intent_key: agent.invoke_existing
    macro_tool: invoke-existing-agent
    selection: exclusive
    verified: true
```

不得包含 ResourceCatalog payload、API key、token 或其他 secret。

## 5. 失败记录建议

若有失败，请保留：

- 失败的 pytest node id；
- ToolSearch 返回的完整 `retrieval` 字段；
- `.clawcodex/tool-retrieval.yaml`；
- 当次 `context.options.tools` 的工具名列表；
- workflow trace 的 `error_code` / `step_id`。

不要通过删除 `.venv`、bundle venv 或 catalog 来清理现场。

# F-59 SOP Runtime Guards & Recovery — 工具调用防空转与标准恢复

> **状态**: 📋 规划中  
> **领域**: 04-architecture-sdk (SOP Runtime / Error Recovery)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-50, F-55, F-56, F-57, F-58

---

## §1 背景

当前 SOP 主要通过 prompt 约束模型：“不要重复 ToolSearch”、“工具失败后有限诊断”、“不要读 wrapper 代替调用”。这能降低空转，但不能从运行时阻止模型在多个语义相近工具之间反复试错。

verify-bot 失败表现就是典型空转：`run-agent`、`llmagent-invoke`、`send-to-agent`、源码搜索反复切换，最终耗尽轮次。

---

## §2 目标

建立 SOP runtime guard，在工具失败、ToolSearch 重复、资源缺失时给出标准恢复路径，并在必要时阻止重复无效动作。

---

## §3 Guard 类型

### 3.1 ToolSearch loop guard

检测同一子代理内：

| 条件 | 行为 |
|------|------|
| 相同 query 连续 ToolSearch > 2 次 | 返回提示：请调用已有 match 或换同义词 |
| 已返回高置信 match 后继续搜索同一意图 | 提示立即调用工具 |
| 搜索 kebab 工具名替代 Skill/ToolSearch 流程 | 沿用 sop_exploration_guard 阻断 |

### 3.2 Resource recovery guard

检测工具错误：

| 错误模式 | 恢复 |
|----------|------|
| `agent not exist` | 查 F-56 catalog，建议/自动调用 `invoke-existing-agent` |
| `session not exist` | 查 session catalog 或提示重新 create session |
| `'str' object has no attribute 'get'` | 对 mapping inputs 做 normalize |
| `abstract class` / config missing | 标记该工具与当前意图不兼容，降低 ToolSearch 排名 |

### 3.3 Source exploration guard

保留现有 guard，并增加：

| 条件 | 行为 |
|------|------|
| 已有标准恢复路径时仍 Grep wrapper | 阻断，提示调用宏工具 |
| catalog missing 后无限读源码 | 限制为一次有限诊断 |

---

## §4 标准错误 Envelope

所有 SOP 工具错误包装为：

```json
{
  "status": "error",
  "error_code": "resource_catalog_missing",
  "message": "No agent record found for id ...",
  "recovery": {
    "recommended_tool": "agentbuilder-build-agent",
    "reason": "The agent was not created in a catalog-enabled path."
  },
  "retryable": false
}
```

### 4.1 Error codes

| code | 说明 |
|------|------|
| `tool_input_normalized` | 输入已自动标准化 |
| `resource_catalog_missing` | catalog 无记录 |
| `resource_recovered` | 已通过 catalog 恢复 |
| `tool_incompatible_for_intent` | 工具与当前意图不兼容 |
| `toolsearch_loop_detected` | ToolSearch 空转 |
| `source_exploration_blocked` | 源码探索被阻断 |

---

## §5 实现位置

| 文件 | 改动 |
|------|------|
| `extensions/sop_converter/sop_exploration_guard.py` | 增加 resource recovery 上下文 |
| `clawcodex_ext/tool_system/tools/tool_search_matching.py` | 接入生命周期/失败降权 |
| `clawcodex_ext/agent/tool_authoring/factory.py` | 包装 SOP 工具错误 envelope |
| `extensions/sop_converter/runtime_recovery.py` | 新增恢复策略 |
| `extensions/sop_converter/bundle_context.py` | 子代理级 guard 状态 |

---

## §6 状态记录

在子代理 ToolContext 中记录轻量状态：

```python
@dataclass
class SopRuntimeGuardState:
    toolsearch_queries: Counter[str]
    failed_tools_by_intent: dict[str, list[str]]
    recovered_resources: set[tuple[str, str]]
    blocked_actions: list[dict[str, Any]]
```

状态只在当前 agent turn 内有效；持久资源状态由 F-56 catalog 负责。

---

## §7 恢复策略优先级

当工具失败时按顺序处理：

1. 输入形状错误：自动 normalize。
2. 资源不存在：查 catalog。
3. 工具不兼容：返回推荐宏工具。
4. SDK 真实错误：允许一次有限源码诊断。
5. 重复失败：停止工具尝试，要求自然语言报告。

---

## §8 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | `inputs="ping"` 自动 normalize | 工具收到 `{"query": "ping"}` 或约定字段 |
| 2 | `agent not exist` 触发 catalog recovery | 自动建议/调用 `invoke-existing-agent` |
| 3 | 相同 ToolSearch query 第三次被 guard | 返回 `toolsearch_loop_detected` |
| 4 | 不兼容工具降权 | `llmagent-invoke` 报 legacy incompat 后不再优先 |
| 5 | 缺 catalog 时停止乱试 | 返回 `resource_catalog_missing`，不继续 send/run/invoke 乱搜 |

---

## §9 测试计划

新增：

```text
tests/misc/test_sop_runtime_guards.py
tests/misc/test_sop_recovery_agent_invoke.py
```

覆盖：

- ToolSearch loop 计数。
- 错误字符串到 error_code 的映射。
- catalog recovery 成功/失败。
- 工具降权。
- source exploration 阻断。

---

## §10 风险

| 风险 | 缓解 |
|------|------|
| guard 过强阻止合法探索 | 只在 SOP bundle/domain agent 模式启用 |
| 错误模式匹配误判 | 优先显式 error_code，字符串匹配仅 fallback |
| 状态污染跨任务 | guard state 只绑定当前 subagent/turn |


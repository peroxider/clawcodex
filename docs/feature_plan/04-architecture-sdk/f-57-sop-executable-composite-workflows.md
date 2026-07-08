# F-57 SOP Executable Composite Workflows — 从描述型宏工具到可执行工作流

> **状态**: 📋 规划中  
> **领域**: 04-architecture-sdk (SOP Converter / Workflow Runtime)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-50, F-55, F-56

---

## §1 背景

当前 SOP 已有 composite tools 与 workflow mode 雏形，但多数能力仍偏“描述型”：生成 Skill、Agent、workflow.yaml 或宏工具说明，让模型按提示手动调用多个工具。对于稳定场景，应把常见多步流程编译成一个可执行 composite workflow，自动完成参数传递、资源记录、错误恢复和最终结果聚合。

典型失败场景是“已有 agent_id，要求发送 ping”。模型不应在 `run-agent`、`llmagent-invoke`、`send-to-agent` 间猜测；系统应提供一个标准可执行宏工具：

```text
invoke-existing-agent(agent_id, query)
  → catalog lookup
  → materialize
  → invoke
  → return output
```

---

## §2 目标

将 SOP composite tool 从“工具集合描述”升级为“可执行多步工作流”。

### 2.1 P0 范围

| 能力 | 说明 |
|------|------|
| Composite workflow spec | 定义 steps、inputs、outputs、resource bindings |
| 线性执行器 | 支持顺序执行工具 / Python callable |
| 参数绑定 | 支持 `$input.x`、`$steps.name.output.y`、`$resources.agent.id` |
| 标准宏工具 | `invoke-existing-agent` |
| 结果聚合 | 返回最终 output 原文 + trace |

### 2.2 P1 范围

- 条件分支。
- retry/backoff。
- 可选步骤。
- workflow.yaml 与 composite tool 双向生成。

---

## §3 CompositeWorkflowSpec

```yaml
version: 1
name: invoke-existing-agent
description: "按已有 agent_id 调用 SOP 创建的 Agent"

inputs:
  agent_id:
    type: string
    required: true
  query:
    type: string
    required: false
  inputs:
    type: object
    required: false

steps:
  - id: load_agent_record
    kind: python
    callable: extensions.sop_converter.resource_catalog:get_agent_record
    args:
      agent_id: $input.agent_id

  - id: materialize_agent
    kind: python
    callable: extensions.sop_converter.agent_runtime:materialize_agent
    args:
      record: $steps.load_agent_record.output

  - id: invoke_agent
    kind: python
    callable: extensions.sop_converter.agent_runtime:invoke_agent
    args:
      agent: $steps.materialize_agent.output.agent
      query: $input.query
      inputs: $input.inputs

outputs:
  output: $steps.invoke_agent.output.text
  raw: $steps.invoke_agent.output.raw
```

---

## §4 Runtime 设计

新增：

```text
extensions/sop_converter/composite_runtime.py
```

核心接口：

```python
class CompositeWorkflowRunner:
    def run(self, spec: CompositeWorkflowSpec, inputs: dict[str, Any]) -> CompositeResult: ...

@dataclass
class CompositeResult:
    output: dict[str, Any]
    trace: list[StepTrace]
    is_error: bool = False
    error_code: str | None = None
```

### 4.1 Step kind

| kind | P0 支持 | 说明 |
|------|---------|------|
| `python` | ✅ | 调用白名单 Python callable |
| `tool` | ✅ | 调用当前 ToolRegistry 中的工具 |
| `catalog` | ✅ | catalog lookup/upsert 的快捷步骤 |
| `condition` | P1 | 条件分支 |
| `parallel` | P2 | 并行 fan-out |

### 4.2 绑定语法

P0 只支持简单 JSONPath 子集：

```text
$input.agent_id
$steps.load_agent_record.output
$steps.invoke_agent.output.text
$resources.agent.agent_id
```

缺失绑定必须返回 `workflow_binding_missing`，不得静默传空。

---

## §5 标准宏工具

### 5.1 `invoke-existing-agent`

输入：

```json
{
  "agent_id": "0f40ed92-...",
  "query": "ping",
  "inputs": {"query": "ping"}
}
```

行为：

1. 从 F-56 Resource Catalog 读取 agent record。
2. 根据 record.materializer 构造 SDK Agent。
3. 根据 record.invoker 调用。
4. 返回原文 output。

### 5.2 `resume-resource`

P1 备选宏工具：

```json
{
  "resource_type": "agent",
  "resource_id": "0f40ed92-..."
}
```

仅 materialize 并做 smoke check，不执行业务 query。

---

## §6 与 ToolSearch 的关系

Composite workflow 也应注册为 `AgentToolSpec`：

| 字段 | 值 |
|------|----|
| `source` | `composite-tool` |
| `tags` | `agent`, `invoke`, `existing`, `lifecycle`, `macro` |
| `aliases` | `run-existing-agent`, `call-agent-by-id` |
| `should_defer` | true |

当用户说“用 ID 调用 agent / 发 ping / invoke existing agent”时，ToolSearch 应优先返回 `invoke-existing-agent`，而不是底层 `run-agent` / `llmagent-invoke`。

---

## §7 错误处理

| code | 场景 | 处理 |
|------|------|------|
| `workflow_binding_missing` | 绑定路径不存在 | 停止执行，返回缺失路径 |
| `workflow_step_failed` | 某步骤失败 | 返回 step id + 原始错误 |
| `resource_catalog_missing` | 找不到资源记录 | 透传 F-56 标准错误 |
| `agent_invoke_failed` | SDK invoke 报错 | 返回 SDK 错误，允许有限诊断 |

---

## §8 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | `invoke-existing-agent` 可通过 ToolSearch 找到 | query: “用已有 ID 调用 agent ping” |
| 2 | 不依赖前一工具进程内存 | build 后新进程 invoke 成功 |
| 3 | 参数绑定正确 | `$input.query` 传到 invoker |
| 4 | 错误 trace 可读 | 失败时包含 step id、error_code |
| 5 | 最终返回原文 | verify-bot 返回 `ping` 时工具 output 为 `ping` |

---

## §9 测试计划

新增：

```text
tests/misc/test_sop_composite_runtime.py
tests/misc/test_sop_invoke_existing_agent.py
```

覆盖：

- 线性 workflow 执行。
- binding 解析。
- fake catalog + fake materializer + fake invoker。
- ToolSearch 排序命中宏工具。
- 错误 trace。

---

## §10 分阶段实施

| 阶段 | 内容 |
|------|------|
| Phase 1 | CompositeWorkflowSpec + Python step runner |
| Phase 2 | `invoke-existing-agent` 宏工具 |
| Phase 3 | ToolSearch metadata + Task Guide 注入 |
| Phase 4 | workflow.yaml 互通与条件步骤 |


# F-58 SOP Resource Contract Schema — 返回值语义与资源契约

> **状态**: 📋 规划中  
> **领域**: 04-architecture-sdk (SOP Converter / Schema Semantics)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-52, F-55, F-56, F-57

---

## §1 背景

当前 `AgentToolSpec.input_schema` 已能约束工具入参，但工具返回值仍缺少机器可读语义。模型可以看到某个工具返回 `agent_id`，但系统不知道这是一个 `agent` resource，也不知道该 ID 应写入 catalog，或后续应由哪个工具消费。

这导致 SOP convert 停留在“函数签名工具化”，没有完成“资源契约编译”。

---

## §2 目标

为 SOP 工具增加返回值语义 schema，声明工具产出的资源、ID 字段、payload 字段、后续消费工具和 materializer/invoker。

---

## §3 Tool Resource Contract

新增 sidecar：

```text
<bundle>/.clawcodex/tool-contracts.yaml
```

### 3.1 示例

```yaml
version: 1

tools:
  agentbuilder-build-agent:
    produces:
      - resource_type: agent
        id_field: agent_id
        payload_fields: [dsl, config, model]
        catalog: true
        materializer:
          kind: python_function
          module: core.agent_factory
          name: create_llm_agent
        invoker:
          kind: python_method
          method: invoke
          input_param: query
    output_schema:
      type: object
      required: [agent_id]
      properties:
        agent_id:
          type: string
        dsl:
          type: object
        config:
          type: object

  invoke-existing-agent:
    consumes:
      - resource_type: agent
        id_param: agent_id
    output_schema:
      type: object
      properties:
        output:
          type: string
        raw:
          type: object
```

---

## §4 合约字段

### 4.1 produces

| 字段 | 说明 |
|------|------|
| `resource_type` | `agent` / `session` / `team` / `pipeline_run` |
| `id_field` | 工具输出中的 ID 字段 |
| `payload_fields` | 需要持久化以便恢复的字段 |
| `catalog` | 是否写入 F-56 catalog |
| `materializer` | 如何从 payload 恢复运行时实例 |
| `invoker` | 默认调用方式 |

### 4.2 consumes

| 字段 | 说明 |
|------|------|
| `resource_type` | 消费的资源类型 |
| `id_param` | 工具入参中的 ID 参数 |
| `fallback_catalog` | 找不到内存实例时是否查 catalog |
| `required_status` | 资源状态要求，如 `active` |

### 4.3 output_schema

标准 JSON Schema，用于：

- 校验 wrapper 输出。
- 提取资源 ID。
- 生成 Task Guide。
- 改善 ToolSearch 摘要。

---

## §5 合约生成策略

### 5.1 静态启发式

| 识别模式 | 合约 |
|----------|------|
| 返回字段 `agent_id` | `produces: resource_type=agent` |
| 返回字段 `session_id` | `produces: resource_type=session` |
| 入参 `agent_id` | `consumes: resource_type=agent` |
| 函数名 `invoke_*` / `run_*` | 默认消费者 |

### 5.2 docstring 提取

如果 docstring 包含：

```text
Returns:
  agent_id: ...
  dsl: ...
```

则增强 output_schema 字段说明。

### 5.3 人工 override

允许用户提供：

```text
<bundle>/.clawcodex/tool-contracts.override.yaml
```

override 优先级高于启发式推断。

---

## §6 与现有 AgentToolSpec 的关系

P0 不修改 `AgentToolSpec` dataclass 的必填字段，避免破坏现有 persisted specs。采用 sidecar 文件与可选字段：

```python
AgentToolSpec(
    ...,
    bundle_id="core_merged",
)
```

运行时通过 `bundle_id + tool_name` 查 `tool-contracts.yaml`。

P1 可考虑给 `AgentToolSpec` 增加可选 `output_schema` / `resource_contract` 字段。

---

## §7 运行时消费

| 消费方 | 用途 |
|--------|------|
| F-56 Resource Catalog | 根据 `produces.catalog` 自动 upsert |
| F-57 Composite Runtime | 根据 `consumes` 自动查 catalog |
| F-55 lifecycle deps | 生成依赖链 |
| ToolSearch | 提升“按 ID 调用”类 query 的排序 |
| Task Guide | 展示“此工具产出 agent_id，后续用 invoke-existing-agent” |

---

## §8 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | convert 后生成 `tool-contracts.yaml` | 文件存在且 version=1 |
| 2 | `agentbuilder-build-agent` 推断 produces agent | 合约含 `resource_type=agent` |
| 3 | `run-agent` / `invoke-existing-agent` 推断 consumes agent | 合约含 `id_param=agent_id` |
| 4 | wrapper 输出被 output_schema 校验 | 缺少 required 字段时报标准错误 |
| 5 | override 可修正误判 | override 后合约以人工配置为准 |

---

## §9 测试计划

新增：

```text
tests/misc/test_sop_tool_contracts.py
```

覆盖：

- 从 SourceOperation 推断 produces/consumes。
- docstring 输出字段提取。
- override 合并。
- output_schema 校验。
- 与 ResourceCatalog upsert 的集成。

---

## §10 风险

| 风险 | 缓解 |
|------|------|
| 启发式误判资源类型 | override + 低置信度不自动 catalog |
| output_schema 过严导致真实 SDK 输出失败 | P0 只校验 required ID 字段 |
| 合约与 SDK 版本漂移 | 合约记录 sdk/source hash |


# F-57 SOP Executable Composite Workflows — 从描述型宏工具到可执行工作流

> **状态**: 🔧 Phase 2–4 MVP 已接线；F-157 结构化 suppression 已实现，待开发者按手工清单复验宏选择效果
> **领域**: 04-architecture-sdk (SOP Converter / Workflow Runtime)
> **最后更新**: 2026-07-18
> **关联 Feature**: F-50, F-55, F-56, F-58, F-59, F-110, F-157

---

## §1 背景

SOP 已有 composite tools 与 workflow mode 雏形，但多数能力仍偏“描述型”：生成 Skill、Agent、`workflow.yaml` 或宏工具说明，让模型按提示手动调用多个工具。对于稳定场景，应把常见多步流程编译成一个可执行 composite workflow，自动完成参数传递、资源记录、错误处理和最终结果聚合。

典型失败场景是“已有 agent_id，要求发送 ping”。模型不应在 `run-agent`、`llmagent-invoke`、`send-to-agent` 间猜测；系统应提供一个标准可执行宏工具：

```text
invoke-existing-agent(agent_id, query)
  → catalog lookup
  → materialize
  → invoke
  → return output
```

### 1.1 当前实现

当前 F-57 已完成以下基础能力：

- `CompositeWorkflowSpec`、线性 step runner 和 binding 解析。
- `python`、`catalog`、`tool` step 的基础执行接口。
- `call_type="workflow"` 与主进程 `ToolRegistry.dispatch()` runner。
- public output 归一化、`output_schema` 验证和 trusted builtin private lane。
- `CatalogExecutionContext`、`workflow_stack`、deferred tool 激活和最小 MacroCatalog。
- `invoke-existing-agent` 主进程 builtin workflow 及其 F-56 catalog 恢复链。
- workflow trace 和标准错误码。
- 数据化 MacroRoute、`prefer` / verified `exclusive` 与 ToolSearch direct recall。
- 手写 bundle 宏 convert 装载、持久化、注册与最小 Task Guide 行。

### 1.2 当前缺口（摘要）

Phase 2–4 已打通 portable tool 链、trusted F-56 恢复链、direct route 和手写 bundle 宏装载。验收后的主要缺口已从“宏能否执行/召回”转为“宏与语义重合的 SDK 原子工具如何分层”：当前 route 未命中时仍回到普通文本评分，且 exclusive 只截断当次结果，没有结构化覆盖关系、active tool 隐藏和宏不可用回滚。该缺口由 F-157 负责；见 §8.5。

### 1.3 实现与未接线清单（相对本设计）

下表同时记录已完成的 Phase 2–4 能力、可选后续项和 F-157 接续边界，避免把“宏能执行/被 route 召回”误解为“宏已能稳定压住语义重合的原子工具”。

| 项 | 现状 | 目标阶段 |
|----|------|----------|
| `call_type="workflow"` | ✅ 已实现；ToolSpec 持久化 `catalog_id` 引用 | Phase 2 |
| 主进程 `ToolRegistry.dispatch` runner | ✅ 已实现；子 tool 保留原执行环境 | Phase 2 |
| `ToolResult` → `$steps.*.output` 归一化（§5.6） | ✅ 已实现并验证 output schema | Phase 2 |
| `workflow_stack` / 递归与深度限制（§5.4） | ✅ 已接 `ToolContext` | Phase 2 |
| 按宏依赖的 deferred tool 激活（§5.3） | ✅ 已实现 | Phase 2 |
| `MacroDefinition` / `extensions/sop_converter/macros/` | ✅ 最小执行模型与 bundle manifest 编译已实现 | Phase 2 / 4 |
| MacroCatalog（bundle/session/builtin） | ✅ 最小 builtin/bundle/session catalog 已实现；session 注册 API 待 Phase 5 | Phase 2 / 5 |
| 独立 `MacroRoute`（与 F-55 `PriorityRoute` 分离） | ✅ 已实现 | Phase 3 |
| ToolSearch direct route 主动召回 | ✅ 已实现；但未命中时宏仍与原子工具普通竞争 | Phase 3 / F-157 |
| `invoke-existing-agent` 数据化迁移（§9.2） | ✅ 执行体与 route 均已数据化 | Phase 2 / 3 |
| 默认 `prefer` / `verified` exclusive 策略 | ✅ route 策略已实现；结构化 covered-atomic suppression 待 F-157 | Phase 3 / F-157 |
| 手写/模板宏 + convert 装载校验（§6） | ✅ MVP：`sop-macros/` + `--macro-manifest` 校验/原子写入/注册 | Phase 4 |
| `AgentToolSpec.output_schema` 与 step `output_schema` | ✅ 已实现；bundle manifest 静态校验待 Phase 4 | Phase 2 / 4 |
| F-56 trusted private lane（opaque Agent 不进入 public output） | ✅ 已实现；bundle/session 宏禁止 private/python/catalog | Phase 2 |
| F-56 `CatalogExecutionContext` 注入 | ✅ 从 active bundle 注入，不要求模型传路径 | Phase 2 |
| F-56 create/invoke 宏向 output schema | ✅ create 正式 schema；invoke 使用 JSON-safe projection | Phase 2 |
| `resource_secret_missing` / `resource_version_unsupported` 发射 | ✅ 已发射并穿过 workflow | Phase 2 对齐门禁 |
| F-56 `resource_type` 注册表消费（通用 `resume-resource`） | ❌ 宏未实现；✅ F-56 注册表 + E1–E5 已就绪（§9.3） | 后续（F-56 §14.7 第 5 步） |
| Skill / Task Guide 从宏 catalog 通用生成 | ⚠️ 已有 `select:<macro>` 最小行；与 lifecycle 原子行的系统消歧待 F-157 | Phase 4 / F-157 |
| `RegisterMacroWorkflow` + 安全门闩（§7.2） | 未实现 | Phase 5（可选） |
| Session 宏 / trace-to-macro / promote | 未实现 | Phase 5（可选） |
| `condition` / retry / optional step | 未实现 | Phase 6 |
| AST/WorkflowGraph 自动挖宏 | **明确非目标**（§2.3 / §6.5） | 独立 Feature（若重评） |

**已通主路径：** portable 宏可在主进程 dispatch 多步 tool 链；`invoke-existing-agent` 以 builtin workflow 执行 F-56 get → materialize → invoke，opaque 状态留在 private lane；ToolSearch 已接 MacroRoute direct recall。

**验收后新增边界：** F-57 保留宏定义、路由意图与执行；“宏覆盖哪些原子工具、何时隐藏、何时恢复、如何从 active tools 移除”统一交由 F-157。session 注册仍是可选 Phase 5。

---

## §2 目标与边界

### 2.1 总体目标

将 SOP composite tool 从“工具集合描述”升级为“可执行多步工作流”，并支持两个来源：

| 来源 | scope | 生命周期 | 用途 |
|------|-------|----------|------|
| 手写/模板 MacroDefinition | `bundle` | 随 bundle 持久化 | 默认路径；由 convert 校验、规范化、持久化和注册 |
| 用户会话显式定义 | `session` | 当前 session 有效 | 记住用户临时约定或刚刚验证成功的调用链 |

两种来源必须落到同一份宏 IR，经过同一套校验、注册、执行和路由流程。`sop convert` 的职责是装载和验证已有宏，不负责从 SDK 源码发明宏。

### 2.2 基础能力

| 能力 | 状态 | 说明 |
|------|------|------|
| Composite workflow spec | ✅ | 定义 steps、inputs、outputs、resource bindings |
| 线性执行器 | ✅ | 支持顺序执行 Python/catalog/tool step |
| 参数绑定 | ✅ | 支持 `$input.x`、`$steps.name.output.y`、`$resources.x` |
| 标准宏工具 | ✅ | `invoke-existing-agent`（主进程 workflow + 暂时硬编码路由） |
| 结果聚合 | ✅ | 返回最终 output 原文和 trace |
| `call_type=workflow` + 主进程调度 | ✅ | 经 `ToolRegistry.dispatch`；见 §5.2、§1.3 |
| Output 归一化与 output_schema | ✅ | §5.6；字段 binding 契约 |
| `workflow_stack` / 递归限制 | ✅ | §5.4 |
| 宏依赖 deferred 激活 | ✅ | §5.3 |
| 最小 MacroCatalog | ✅ | builtin/bundle/session 分层；外部装载/注册分别待 Phase 4/5 |
| 独立 MacroRoute + 去硬编码 | ✅ | §8；Phase 3 |
| 显式宏 convert 校验与持久化 | ✅ MVP | §6；手写/模板，不发明编排 |
| session 宏注册 | 待实施（可选） | §7；Phase 5 |
| ToolSearch 直达路由 | ✅ | 主动召回 `target_tool`；宏/原子分层见 F-157 |

### 2.3 非目标

- 不把任意自然语言任务自动永久保存成 bundle 宏。
- 不允许用户宏生成任意 Python callable、Bash 命令或动态 import。
- F-57 不从 AST、`WorkflowGraph` 或 F-55 dependency graph 自动生成宏。
- convert 不推测业务编排，只验证显式 manifest 中已经声明的 step 和 binding。
- 不要求把 F-56 恢复 API 全部暴露成普通工具；builtin trusted workflow 可使用受限 private lane。
- 当前阶段仍以 `invoke-existing-agent` 为生产恢复宏；通用 `resume-resource` 见 §9.3（F-56 注册表与 E1–E5 已就绪，但宏本身尚未实现）。
- 不用宏工作流替代 F-110 的长流程编排、人工 gate、checkpoint 和跨 stage 恢复。
- 不让 LLM 直接决定未经 schema 校验的参数绑定或执行链。

---

## §3 总体架构

```text
Handwritten/template MacroDefinition ─────────────────────────┐
                                                              │
User workflow request / successful session trace              │
                               │                              │
                               ▼                              │
                           MacroDraft                         │
                    （用户意图、trace、诊断信息）               │
                               │                              │
                               ▼                              │
                         MacroCompiler                        │
                 （参数化、binding 和 route 草稿）             │
                               │                              │
                               └──────────────┬───────────────┘
                                              ▼
                                      MacroValidator
          （工具存在、schema、DAG、权限、递归、side effect）
                                              │
                                ┌─────────────┴─────────────┐
                                ▼                           ▼
                      CompositeWorkflowSpec             MacroRoute
                                │                           │
                                └─────────────┬─────────────┘
                                              ▼
                                         MacroCatalog
                 （bundle scope / session scope）
                                              │
                                              ▼
                                 AgentToolSpec(call_type=workflow)
                                              │
                                              ▼
                              ToolRegistry + deterministic ToolSearch
```

建议新增模块：

```text
extensions/sop_converter/macros/
├── models.py          # MacroDefinition / MacroDraft / MacroRoute
├── compiler.py        # session/trace draft → workflow spec
├── validation.py      # schema、binding、DAG、安全校验
├── catalog.py         # bundle/session 持久化与合并
├── registry.py        # workflow AgentToolSpec 注册
└── routing.py         # direct route 匹配与冲突处理
```

---

## §4 数据模型

### 4.1 CompositeWorkflowSpec

`CompositeWorkflowSpec` 继续作为唯一的执行 IR，不包含持久化 scope、定义来源和 ToolSearch 路由策略。

```yaml
name: create-and-invoke-agent
description: 创建 Agent 后立即调用

inputs:
  agent_config:
    type: object
    required: true
  query:
    type: string
    required: true

steps:
  - id: create
    kind: tool
    callable_ref: openjiuwen-core-application-llm-agent-create-llm-agent
    args:
      agent_config: $input.agent_config
    output_schema:
      type: object
      properties:
        agent_id: {type: string}
      required: [agent_id]

  - id: invoke
    kind: tool
    callable_ref: invoke-existing-agent
    args:
      agent_ref: $steps.create.output.agent_id
      query: $input.query

outputs:
  agent_id: $steps.create.output.agent_id
  output: $steps.invoke.output.output
```

### 4.2 MacroDefinition

`MacroDefinition` 是持久化和注册层包装，内部持有 `CompositeWorkflowSpec`（见 §4.1）。手写/模板宏、`--macro-manifest` 与 `sop-macros/*.yaml` **必须**符合本节 schema；convert 只认 `version: 1`，不合规直接失败。

#### 4.2.1 手写宏 YAML 固定模板（Canonical）

**权威模板文件（单源，给人与模型复制填写）：**

[`extensions/sop_converter/macros/templates/macro.definition.yaml.template`](../../../extensions/sop_converter/macros/templates/macro.definition.yaml.template)

用法：复制到源树 `sop-macros/<name>.yaml` 后按注释改字段；模板内附 `create-and-invoke-agent` 注释示例。模板宏实例化后也必须落到同一 `MacroDefinition` 结构。下文保留精简骨架便于阅读；字段释义与硬约束以模板文件头注释为准。

```yaml
version: 1
name: your-macro-name
description: 一句话说明意图与编排范围
scope: bundle
enabled: true

workflow:
  inputs:
    some_arg:
      type: string
      description: 参数说明
      required: true
  steps:
    - id: step1
      kind: tool
      callable_ref: some-atomic-tool
      args:
        x: $input.some_arg
  outputs:
    result: $steps.step1.output

routing:
  phrases: [自然语言召回短语]
  keywords: [关键词]
  negative_keywords: []
  target_tool: your-macro-name
  match_mode: all
  selection: prefer
  priority: 100
  verified: false

provenance:
  kind: handwritten
  manifest: sop-macros/your-macro-name.yaml
```

**硬约束（convert / `validate_macro_definition`）：**

| 规则 | 说明 |
|------|------|
| `version == 1` | 其他版本 → `macro_version_unsupported` |
| `name` / `workflow` 必填 | `workflow.steps` 必须为非空 list |
| 每步 `id` + `callable_ref` | `callable_ref` 映射到 allowlist / ToolIndex |
| bundle 宏 `kind` 仅 `tool` | `python` / `catalog` 仅 trusted builtin |
| `$input.*` | 必须在 `workflow.inputs` 声明 |
| `$steps.*.output.*` | 禁止前向引用；字段须有可证明的 output contract |
| 装载路径 | 源树 `sop-macros/*.yaml`、`--macros-dir`，或 `--macro-manifest` |

#### 4.2.2 填好的实例（create-and-invoke-agent）

与 §4.1 IR 对应的完整 MacroDefinition 示例如下（亦见单测 `tests/misc/test_sop_macro_convert_phase4.py` 中 `_SAMPLE_MACRO`）：

```yaml
version: 1
name: create-and-invoke-agent
description: 创建 Agent 后立即调用
scope: bundle
enabled: true

workflow:
  inputs:
    agent_config:
      type: object
      required: true
    query:
      type: string
      required: true
  steps:
    - id: create
      kind: tool
      callable_ref: create-llm-agent
      args:
        agent_config: $input.agent_config
      output_schema:
        type: object
        properties:
          agent_id: {type: string}
        required: [agent_id]
    - id: invoke
      kind: tool
      callable_ref: invoke-existing-agent
      args:
        agent_ref: $steps.create.output.agent_id
        query: $input.query
  outputs:
    agent_id: $steps.create.output.agent_id
    output: $steps.invoke.output

routing:
  phrases:
    - 创建并调用 agent
    - 创建 agent 后回复
  keywords:
    - 创建
    - agent
  negative_keywords: []
  target_tool: create-and-invoke-agent
  match_mode: all
  selection: prefer
  priority: 100
  verified: false

provenance:
  kind: handwritten
  manifest: sop-macros/create-and-invoke-agent.yaml
```

**其它可对照实例：** AscendDataForge G 组手写宏（单步封装 `skills-skill-handlers-execute-pipeline` + 嵌入 `pipeline.operations`）位于源仓 `sop-macros/{text,image,multimodal}-processing-pipeline.yaml`；convert 后落在 bundle `.clawcodex/macros/`。

### 4.3 MacroDraft

`MacroDraft` 只用于会话自然语言或 trace 固化，手写/模板宏直接提供完整 MacroDefinition，不经过 Draft：

| 字段 | 说明 |
|------|------|
| `proposed_name` | 草稿中的目标宏名称 |
| `requested_scope` | 用户要求的 session/bundle scope |
| `source_steps` | 从会话 trace 提取的工具调用序列 |
| `input_candidates` | 可能成为宏输入的参数 |
| `binding_candidates` | step 间返回值传递候选 |
| `provenance` | `session_nl` 或 `session_trace` |
| `diagnostics` | 未解析参数、歧义工具、缺失 contract 等原因 |

### 4.4 存储位置与优先级

| scope | 建议位置 | 说明 |
|-------|----------|------|
| Bundle | `<bundle>/.clawcodex/macros/<name>.yaml` | convert 产物，可复现、可版本化 |
| Session | `ToolContext.SessionMacroCatalog` | 临时宏定义/route；不污染 bundle，session 结束后失效 |

同名宏解析顺序为 `session > bundle > builtin`。session 宏不得静默覆盖 bundle 宏；覆盖时必须使用显式 `replace=true`，并保留原定义用于 session 结束后的恢复。`SessionMacroCatalog` 只存宏，不是 F-56 `ResourceCatalog`，两者不得简称为同一个 “session catalog”。

---

## §5 Runtime 设计

### 5.1 Step kind

| kind | 支持阶段 | 说明 |
|------|----------|------|
| `python` | builtin/trusted only | 调用显式白名单 Python callable |
| `tool` | P0 | 通过当前 `ToolRegistry.dispatch()` 调用工具 |
| `catalog` | builtin/trusted only | F-56 catalog lookup/upsert 快捷步骤 |
| `condition` | P1 | 声明式条件分支 |
| `parallel` | P2 | 并行 fan-out |

用户定义宏和普通手写/模板宏默认只允许 `kind=tool`。`python`、`catalog` 只允许内置、签名受信任的宏使用。两类宏不是同一种信任模型：portable 宏只处理 JSON-safe public output；trusted builtin 可以使用 §5.7 的 private context，但不能把 opaque value 暴露给 portable 宏。

### 5.2 一等 `workflow` call type

> **状态：✅ 已实现（Phase 2）**

`AgentToolSpec` 新增：

```python
call_type: Literal["bash", "http", "python", "workflow"]
```

新增：

```text
extensions/sop_converter/composite_runtime.py
```

核心接口：

```python
class CompositeWorkflowRunner:
    def run(self, spec: CompositeWorkflowSpec, inputs: dict[str, Any]) -> CompositeResult: ...

这样每个底层 step 仍经过：

- bundle allowlist 与 deferred tool 激活；
- JSON Schema coercion/validation；
- 权限检查和用户确认；
- session state、resource catalog 与 secret policy；
- 对应工具原有的 bundle venv 解释器和 `--catalog-metadata` 执行路径。

宏本身不得硬编码 `python3`，也不得绕过底层工具已经配置的 bundle venv。

### 5.3 Deferred tool 激活

> **状态：✅ 已实现（Phase 2）**

宏被注册时必须记录所有 `kind=tool` 依赖。执行前统一调用 bundle tool loader 激活这些工具，避免宏已被 ToolSearch 找到但内部 step 返回 `unknown tool`。

### 5.4 递归与深度限制

> **状态：✅ 已实现（Phase 2）**

`ToolContext` 增加 session-local `workflow_stack`：

- 禁止宏直接或间接调用自身。
- 默认最大嵌套深度为 8。
- convert 校验阶段拒绝静态可见的宏依赖环。
- 动态发现循环时返回 `workflow_cycle_detected`。

### 5.5 绑定语法

P0 支持简单 JSONPath 子集（绑定解析与运行时 output contract 校验均已实现；bundle manifest 的完整静态校验待 Phase 4）：

```text
$input.agent_id
$steps.create.output.agent_id
$steps.invoke_agent.output.text
$resources.catalog.bundle_id
$private.load_agent_record.record    # builtin trusted only，见 §5.7
```

缺失绑定必须返回 `workflow_binding_missing`，不得静默传空。编译阶段还必须验证：

- 绑定引用的 step 已在当前 step 之前完成；
- 目标字段满足被调用工具的 required schema；
- 已知 JSON 类型兼容；
- 宏 outputs 引用的路径存在。

### 5.6 `ToolResult` 输出归一化契约

> **状态：✅ 已实现（Phase 2）**

workflow runner 不得把任意 `ToolResult.output` 原样塞入 step context。每个 step 的 `$steps.<id>.output` 必须是 JSON object，并按以下稳定规则归一化：

| 原始 `ToolResult.output` | `$steps.<id>.output` |
|--------------------------|----------------------|
| `Mapping` / dict | 复制为普通 JSON object |
| 可解析为 JSON object 的字符串 | 解析后的 JSON object |
| 普通字符串 | `{"text": <raw>, "value": <raw>}` |
| list、number、boolean、null | `{"value": <raw>}` |
| 不可 JSON 序列化对象 | 返回 `workflow_output_unserializable`，不得把对象引用留在 context |

所有分支都必须递归检查 JSON 可序列化性；dict 内部包含 opaque object 时同样失败，不允许只检查顶层类型。

因此字段绑定统一写为 `$steps.create.output.agent_id`；对纯文本工具则显式使用 `$steps.step.output.text` 或 `$steps.step.output.value`。

字段级 binding 必须有显式 output contract，解析顺序为：

1. `AgentToolSpec.output_schema`；
2. convert/catalog metadata 中声明的 output schema；
3. builtin trusted adapter 的固定 output contract；
4. MacroDefinition step 上显式声明的 `output_schema`；该声明必须在运行时对归一化结果再次校验，不能只用于骗过 convert。

如果 validator 无法证明 `$steps.<id>.output.<field>` 存在，手写/模板宏校验直接失败；会话 MacroDraft 保持未注册并返回 diagnostics。运行时实际输出不满足声明 schema 时返回 `workflow_output_schema_mismatch`，字段缺失仍返回 `workflow_binding_missing`。

### 5.7 Trusted builtin private context

> **状态：✅ 已实现（Phase 2，F-56 对齐门禁）**

F-56 的 `ResourceRecord` 和 materialized Agent 是 Python 对象，不适用 §5.6 的 public output 归一化。runner 必须维护与 public `$steps` 分离的 private context：

```text
trusted get_agent_record
  → $private.load_agent_record.record
trusted materialize_agent
  → $private.materialize_agent.agent
trusted invoke_agent
  → public JSON-safe projection
```

约束：

- 只有 builtin catalog 中的签名受信任 workflow 可以声明 `visibility=private` 或引用 `$private.*`。
- bundle/session manifest 出现 private binding、`kind=python` 或 `kind=catalog` 时校验失败。
- private value 不进入 `ToolResult`、public `$steps.*.output`、trace、日志、持久化 manifest 或 session macro trace。
- trusted invoke 完成后必须通过固定 adapter 生成 §5.6 可验证的 JSON-safe output；SDK 原始对象只允许在投影完成前短暂存在。
- Phase 2 不要求把 F-56 的三个 Python API 包装成普通工具。若未来工具化，只能返回 resource handle/projection，不能返回 Agent 实例。

### 5.8 CatalogExecutionContext 注入

> **状态：✅ 已实现（Phase 2，F-56 对齐门禁）**

主进程 workflow runner 必须从 `ToolContext.bundle_context` / active bundle 构造 F-56 `CatalogExecutionContext`，至少包含 canonical `bundle_path`、`bundle_id` 和 `home_only`，并作为内部 `$resources.catalog` 注入 trusted workflow。

- 普通宏 input schema 不暴露 `bundle_path`，模型不能选择任意 catalog 路径。
- create step 经 `ToolRegistry.dispatch()` 调用时，底层 wrapper 继续使用 convert 固化的 `--catalog-metadata` 写盘。
- 同一宏后续 `get_agent_record` 使用 `$resources.catalog` 的相同 bundle identity 读取。
- 无 active bundle 时必须携带明确 `bundle_id` 访问 user-local catalog，不得以 CWD 猜测。
- 现有 `$input.bundle_path`、wrapper `--bundle-path` 和 `CLAWCODEX_BUNDLE_PATH` 仅保留兼容/CLI 路径，不作为新 MacroDefinition 契约。

---

## §6 `sop convert` 宏装载与校验

> **状态：✅ Phase 4 MVP 已接线**；`sop-macros/` + `--macro-manifest` → 校验 → 原子写入 `.clawcodex/macros/` → 注册 `call_type=workflow` 工具与 MacroRoute。Skill/Task Guide 深度生成仍可增强。

### 6.1 输入来源

convert 只接收已经声明好的 MacroDefinition，不分析 SDK 函数体来猜测编排：

- 可重复的 `--macro-manifest <path>`，显式传入一个或多个宏定义。
- source tree 中约定的 `sop-macros/*.yaml` 目录，存在时自动读取。
- converter 自带、受版本控制的模板：`extensions/sop_converter/macros/templates/macro.definition.yaml.template`；实例化后必须先形成完整 MacroDefinition。
- 由 session/trace 宏显式 promote 后产生的 bundle manifest。

模板只允许变量替换和工具引用映射，不得执行任意 Python、Jinja expression 或 shell。无论来源如何，最终输入都必须是相同版本的声明式 MacroDefinition（权威骨架见 **§4.2.1** 模板文件，填好的示例见 **§4.2.2**）。

### 6.2 处理流水线

```text
handwritten/template/promoted MacroDefinition
  → parse schema version
  → normalize name / aliases / route
  → resolve callable_ref against deterministic ToolIndex
  → validate input/output schema and bindings
  → validate allowlist / recursion / permissions / route
  → atomically persist into <bundle>/.clawcodex/macros/
  → register AgentToolSpec(call_type=workflow)
  → generate Skill allowlist / Task Guide / MacroRoute index
```

`ToolIndex` 使用与 component tool 注册完全相同的名称规范化规则，但不读取 operation 函数体，也不生成新的 step。F-55 dependency metadata 可以产生“不符合已知 lifecycle”的 warning，但不得增加、删除、重排 step 或补造 binding。

### 6.3 Convert 校验契约

每个显式宏至少必须通过：

- macro schema version、name、scope 和 route schema 校验；
- 所有 `callable_ref` 唯一映射到 bundle allowlist 或显式基础工具；
- input schema 覆盖所有 `$input.*` 引用；
- 所有 `$steps.*.output.*` 字段有 §5.6 定义的 output contract；
- step 顺序、binding 前向引用和 outputs 引用合法；
- 无宏依赖环，嵌套深度和 step 数满足限制；
- `selection=exclusive` 满足 verified 约束，否则降为 `prefer`；
- manifest、AgentToolSpec、MacroRoute 和 Skill 更新可以原子提交。

任何校验失败都不得部分写入 bundle。错误报告必须包含 manifest、step id、字段路径和稳定 error code，使作者可以直接修正 YAML。

### 6.4 Preview 与注册模式

| 模式 | 行为 |
|------|------|
| `--preview` | 解析和校验，输出规范化宏及 diagnostics，不写文件、不注册 |
| `--validate-only` | 执行完整校验并以退出码表示结果，不写文件、不注册 |
| 正常 convert + `--register-tools` | 原子写入 manifest、tool spec、route 和 Skill 引用 |
| 正常 convert但不注册工具 | 可写规范化 manifest，但不得产生指向未注册工具的 active route |

### 6.5 未来独立 Feature 的重评条件（F-57 非目标）

F-57 不包含 AST/WorkflowGraph 自动生成宏，也不预留 `--infer-macros` 作为本 Feature 的交付项。未来只有同时满足以下条件时，才以独立 Feature 重新评估：

1. 真实 SOP 中存在大量固定线性 orchestrator；
2. 工具名称、input/output schema 和字段契约已经高度规范化；
3. 手写/模板宏的实际维护成本已经明显高于自动推导的开发和误判成本。

在此之前，AST 自动推导不是阶段目标、验收项或代码修改范围。F-57 的成功指标是手写/模板宏能稳定装载执行，以及可选会话宏能安全固化。

---

## §5 标准宏工具

### 5.1 `invoke-existing-agent`

输入：

```json
{
  "agent_ref": "verify-bot",
  "agent_id": "optional-legacy-id",
  "query": "ping",
  "inputs": {"query": "ping"}
}
```

行为：

1. 从 F-56 Resource Catalog 按 name 或 agent_id 读取 agent record。
2. 根据 record.materializer 构造 SDK Agent。
3. 根据 record.invoker 调用。
4. 返回 JSON-safe output projection、text、agent_id 和 trace。

稳定 output contract：

```json
{
  "type": "object",
  "required": ["agent_id", "output", "raw", "text", "trace"],
  "properties": {
    "agent_id": {"type": "string"},
    "output": {},
    "raw": {},
    "text": {"type": "string"},
    "trace": {"type": "array"}
  }
}
```

`output` / `raw` 都表示 SDK 原始返回值的 JSON-safe projection；若原值不可 JSON 化，trusted adapter 必须转换为稳定文本或返回 `workflow_output_unserializable`，不得泄漏 Python 对象。

### 9.2 数据化迁移

> **状态：✅ 执行体与 direct route 数据化迁移已完成；covered atomic 分层与隐藏转交 F-157**

将 `invoke-existing-agent` 从“Python 函数 + 专用 ToolSearch 判断”迁移为：

- 一个 builtin `MacroDefinition`；
- 一个运行在主进程的 trusted catalog/python workflow；
- `ResourceRecord` 与 Agent 实例通过 §5.7 private context 传递；
- `CatalogExecutionContext` 由 §5.8 注入，不再要求模型传 `bundle_path`；
- 一条 builtin direct route；
- 原 aliases 与 `agent_ref` / `agent_id` / `query` / `inputs` 业务输入保持兼容；`bundle_path` 仅保留为隐藏的 CLI/旧 wrapper 兼容参数，不再暴露为模型业务输入。

迁移已经删除 existing-agent 专用判断并由通用 route 覆盖原回归用例；自然语言验收暴露出的 route 漂移、active atomic 暴露和可回滚 suppression 不再在本节追加专用判断，统一由 F-157 处理。

### 9.3 下一步：通用 `resume-resource`

> **状态**：❌ 宏尚未实现；✅ F-56 侧前置门禁已满足（注册表 + E1–E5 / `DemoHandle`）。
> **归属**：本 Feature（F-56 §14.7 第 5 步交出）。

目标形态（未接线）：

```json
{
  "resource_type": "agent",
  "resource_ref": "verify-bot",
  "query": "ping"
}
```

相对今日 `invoke-existing-agent` 的差异：

| 项 | `invoke-existing-agent`（已实现） | `resume-resource`（待实现） |
|----|-----------------------------------|------------------------------|
| 类型范围 | 仅 Agent 族 | 任意已注册 `resource_type` |
| 句柄入参 | `agent_ref` / `agent_id`（兼容） | 稳定 `resource_ref` + `resource_type` |
| 恢复路径 | 硬编码 get → materialize → invoke | `require_resource_handler(type)` → materialize → invoke |
| 未注册类型 | N/A（隐含 agent） | 透传 `resource_type_unregistered`，不得 silently 走 agent |

实现约束（验收前必须遵守）：

1. **只经 F-56 `ResourceHandler` 注册表**消费资源；禁止再复制一套 agent 专用 if / 新增 `invoke-existing-*` 作为扩展手段。
2. 继续使用 §5.7 trusted private lane：opaque 对象不得进入 public `$steps` / ToolResult。
3. public output 必须 JSON-safe，并验证 handler 的 `public_output_schema`。
4. 错误码原样透传 F-56（含 `resource_type_unregistered`、secret/version/missing/ambiguous）。
5. `invoke-existing-agent` 在通用宏落地前保持兼容；落地后可薄封装为对 `resume-resource(resource_type=agent, ...)` 的调用，或并存一段时间。
6. 真实第二产品 SDK（Team/Pipeline 等）仍属产品需求；`DemoHandle` 只证明机制，不阻塞本宏的**机制验收**，但产品宣称「支持某 SDK 种类」仍需该种类已注册。

未实现前：若只需 Agent 诊断，继续用明确命名的 `invoke-existing-agent`，不要提前占用通用名称却只接 agent。

### 9.4 F-56 对齐门禁

Phase 2 已按以下门禁完成并通过回归测试；`resource_type` 可扩展主路径为后续 `resume-resource` 追加：

| 对齐项 | F-57 要求 |
|--------|-----------|
| 消费通道 | portable 宏只 tool；builtin F-56 链只能经 trusted private lane |
| create output | `agent_id`、`created_persisted`、`resource_catalog_path` 有正式 output schema |
| materialize output | Agent 对象只在 private context，public context 仅可见 handle/projection |
| invoke output | `text`、`raw`、`output` 经过 JSON-safe projection 和 runtime schema 校验 |
| catalog context | create write 与 get read 使用同一 canonical bundle_path + bundle_id |
| 错误码 | F-56 实际发射并由 workflow 原样透传 secret/version/missing/ambiguous 错误 |
| session 语义 | `SessionMacroCatalog` 不等于 F-56 ResourceCatalog；宏删除不清理资源 |
| `resource_type` 注册表 | ✅ F-56 已提供；通用宏必须经 `require_resource_handler`，未注册拒绝 |
| 稳定句柄 | 新宏优先 `resource_ref`；`agent_id` 仅作 Agent 兼容读 |
| E1–E5 机制证明 | ✅ F-56 矩阵已绿；产品第二 SDK 仍可选 |

生产者侧完整契约见 F-56 §13 / §14。

---

## §10 安全与权限

| 约束 | 要求 |
|------|------|
| 用户宏 step 类型 | 仅允许 `tool` |
| Python callable | 仅 builtin allowlist，可审计、不可由会话注入 |
| Shell | 不允许宏定义内生成命令字符串 |
| 工具权限 | 每个 step 必须通过 `ToolRegistry.dispatch()` 重新检查 |
| Secret | 只允许 env ref 或既有 secret state，不将明文写入 manifest/trace |
| Bundle 边界 | bundle 宏只能引用本 bundle allowlist 或显式基础工具 |
| 循环 | 编译期和运行期双重检测 |
| Side effect | route 命中只选择工具，不绕过正常 permission ask |
| 注册确认 | create/replace/promote 必须经过独立宏计划确认 |
| 注册限额 | 默认 16 steps、32 active/session、5 registrations/10min |
| 管理工具 | 宏不得调用 register/promote/delete macro 工具 |

宏注册本身属于状态变更：session scope 可由用户明确指令授权；promote 到 bundle 必须是用户明确要求，不能从普通任务中推断。

---

## §11 错误处理

| code | 场景 | 处理 |
|------|------|------|
| `workflow_binding_missing` | 绑定路径不存在 | 停止执行，返回缺失路径 |
| `workflow_step_failed` | 某步骤失败 | 返回 step id、tool name 和原始错误 |
| `workflow_tool_missing` | step 工具不存在或无法激活 | 返回缺失工具及 bundle 信息 |
| `workflow_schema_mismatch` | 编译期或运行期 schema 不兼容 | 返回参数和期望 schema |
| `workflow_output_unserializable` | step output 无法归一化为 JSON object | 停止执行并返回 step/tool 信息 |
| `workflow_output_schema_mismatch` | 归一化输出不满足 step/tool output schema | 停止执行并返回字段差异 |
| `workflow_cycle_detected` | 宏递归或依赖环 | 停止执行并返回 workflow stack |
| `macro_route_conflict` | 多个 exclusive route 同分 | 不做直达选择，返回冲突候选 |
| `macro_validation_failed` | 宏定义未通过安全/结构校验 | 不注册并返回 diagnostics |
| `resource_catalog_missing` | 找不到资源记录 | 透传 F-56 标准错误 |
| `resource_catalog_ambiguous` | name/ref 命中多条 F-56 record | 原码透传，不猜测选择 |
| `resource_secret_missing` | F-56 record 依赖的 env secret 缺失 | 原码透传，列变量名但不含值 |
| `resource_version_unsupported` | F-56 catalog schema 版本不支持 | 原码透传，不降级为 missing |
| `resource_type_unregistered` | 通用恢复宏请求未登记 `resource_type` | 原码透传；不得 silently 走 agent（§9.3） |
| `agent_invoke_failed` | SDK invoke 报错 | 返回 SDK 错误和 step trace |

---

## §12 代码修改范围

| 文件/模块 | 修改内容 |
|-----------|----------|
| `extensions/sop_converter/composite_runtime.py` | tool result 规范化、trusted private context、递归保护、schema/binding 增强 |
| `extensions/sop_converter/composite_tools/models.py` | 与通用 MacroDefinition 对接，逐步移除 script-name 强依赖 |
| `extensions/sop_converter/composite_tools/__init__.py` | 支持 manifest/workflow 注册，不再要求每个宏有专用 wrapper |
| `extensions/sop_converter/macros/*` | 新增 definition/draft、会话编译、校验、catalog、注册和路由模块 |
| `clawcodex_ext/agent/tool_authoring/spec.py` | 增加 `call_type="workflow"` 和可选 `output_schema` |
| `clawcodex_ext/agent/tool_authoring/validators.py` | 校验 workflow manifest、可引用路径和可选 output schema |
| `clawcodex_ext/agent/tool_authoring/persistence.py` | 序列化 workflow call type、manifest 引用和 output schema |
| `clawcodex_ext/agent/tool_authoring/factory.py` | 在主进程构造 workflow runner，调用当前 ToolRegistry |
| `clawcodex_ext/tool_system/context.py` | 增加 CatalogExecutionContext、SessionMacroCatalog/route overlay 和 workflow stack |
| `clawcodex_ext/tool_system/tools/tool_search.py` | 加载 bundle + session direct routes |
| `clawcodex_ext/tool_system/tools/tool_search_matching.py` | direct target 召回、优先级、冲突处理，移除 F-57 专用硬编码 |
| `extensions/sop_converter/task_guide.py` | 从宏 catalog 通用生成 task-guide row |
| `clawcodex_ext/cli/sop_cmd/commands.py` | 加载、校验、规范化、持久化并注册显式 macro manifests |
| `extensions/sop_converter/resource_catalog.py` | 接收统一 catalog context，正式发射 version/secret 错误 |
| `extensions/sop_converter/agent_runtime.py` | opaque Agent 留在 private lane，输出 JSON-safe invoke projection |
| `extensions/sop_converter/tool_registry_bridge.py` | 发布 create output schema，并保持 catalog metadata 与 runtime bundle identity 一致 |

---

## §13 测试计划

建议新增：

```text
tests/misc/test_sop_macro_models.py
tests/misc/test_sop_macro_validation.py
tests/misc/test_sop_macro_catalog.py
tests/misc/test_sop_macro_registry.py
tests/misc/test_sop_session_macros.py
tests/tool/test_tool_search_macro_routes.py
```

保留并扩展：

```text
tests/misc/test_sop_composite_runtime.py
tests/misc/test_sop_invoke_existing_agent.py
```

必须覆盖：

- 线性 workflow、binding 和 output 聚合。
- dict、JSON 文本、普通文本、list/scalar output 的归一化契约。
- 缺少 output schema 的字段 binding 必须校验失败。
- step 显式 output schema 必须在运行时再次验证。
- trusted F-56 record/Agent 只能在 private context 传递，public output 与 trace 不含对象。
- create 子进程写入与同宏主进程读取使用相同 bundle_path + bundle_id。
- F-56 secret/version/missing/ambiguous 错误码原样穿过 workflow result/trace。
- 主进程 `ToolRegistry.dispatch()` 调用及 step 权限检查。
- deferred bundle tool 激活。
- bundle venv 工具在宏内部仍使用其指定解释器。
- 手写/模板 MacroDefinition 可由 convert 校验、规范化、持久化并注册。
- convert 不读取 SDK 函数体、WorkflowGraph 或 F-55 图来增加、删除或重排宏 step。
- 非法 callable_ref、binding、output contract、route 或循环依赖原子拒绝，不产生部分产物。
- session 宏即时注册、同名冲突、session 结束清理和 promote。
- session 注册确认、allowlist、step/数量/rate limit 和原子回滚。
- direct route 能召回未进入普通文本候选集的宏。
- 新宏默认 prefer；verified exclusive 的 route 决策由本 Feature 覆盖，covered atomic 的结构化隐藏与 active exposure 由 F-157 验收。
- exclusive 目标执行前不可用时恢复原子候选、执行后失败时不自动重放；前者的同调用回滚由 F-157 实现。
- route 冲突时稳定退化，不随机选择。
- `invoke-existing-agent` 数据化迁移前后行为一致。
- secret 不写入 manifest、route 或 trace。

---

## §14 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | `invoke-existing-agent` 通过通用 direct route 找到 | query: “用 verify-bot 回复 ping” |
| 2 | F-57 不再依赖 existing-agent 专用 ToolSearch 硬编码 | 删除专用分支后原测试继续通过 |
| 3 | convert 默认支持显式 bundle 宏 | 手写/模板 manifest 经校验后规范化、持久化并注册 |
| 4 | convert 不发明或修改编排 | 给定 SDK/WorkflowGraph/F-55 元数据时，manifest step 顺序和 binding 保持不变 |
| 5 | 非法 manifest 原子失败 | schema/binding/allowlist/route 错误不留下部分 tool、route 或文件 |
| 6 | 宏 step 保留底层执行环境 | bundle venv 依赖工具在宏内无需重新下载依赖 |
| 7 | 每个 step 保留权限检查 | 有权限要求的底层工具仍触发正常 permission flow |
| 8 | 路由结果确定 | 相同 query/catalog 多次搜索返回相同宏顺序 |
| 9 | 最终返回原文 | verify-bot 回复 `ping` 时宏 output 保留 `ping` |
| 10 | step output 契约稳定 | 文本、JSON、dict 和 scalar 工具均产生规定的 object 形状 |
| 11 | 可选 session 宏可安全注册 | 用户明确确认后可注册；未确认、超限、未 allowlist、headless 默认场景均拒绝 |
| 12 | 可选 trace 固化正确 | trace-to-macro 生成正确 step binding，并可显式 promote |
| 13 | 新建宏不激进截断候选 | session/convert 宏初始 route 均为 `prefer` |
| 14 | F-56 opaque 状态不泄漏 | materialized Agent 只存在 private context，ToolResult/trace 可 JSON 序列化 |
| 15 | catalog identity 对齐 | create dispatch 后同宏 get 无需用户传 bundle_path 即命中同一 record |
| 16 | F-56 错误码可依赖 | secret/version/missing/ambiguous 均按原码进入 workflow error |
| 17 | 宏/原子分层边界明确 | F-57 route 命中后交给 F-157 RetrievalPlan；不再以增加 existing-agent phrase 作为完整修复 |

---

## §15 分阶段实施

| 阶段 | 内容 | 完成标志 |
|------|------|----------|
| Phase 1 | 现有 CompositeWorkflowSpec、runner、`invoke-existing-agent` | ✅ 已完成 |
| Phase 2 | `workflow` call type、主进程 ToolRegistry runner、output 归一化、trusted private lane、CatalogExecutionContext、F-56 错误码、`workflow_stack`、deferred 激活、MacroCatalog | ✅ 已完成；portable tool 宏可执行，builtin F-56 链不泄漏 opaque 状态且 catalog identity 一致 |
| Phase 3 | 独立 MacroRoute、route overlay、硬编码数据化、`prefer`/`verified` 策略 | ⚠️ direct recall 已完成；宏/原子 structural suppression 与 active exposure 转交 F-157 |
| Phase 4 | 手写/模板宏接入、convert 校验/规范化/持久化、Skill/Task Guide | ✅ MVP：YAML+convert 装载/校验/原子写入/注册 workflow+route；Task Guide 深度生成可继续增强 |
| Phase 5（可选） | `RegisterMacroWorkflow`、安全门闩、trace-to-macro、session promote | 用户可在会话中安全定义并提升宏 |
| Phase 6 | condition、retry/backoff、optional step、F-110 互通 | 支持受控分支和长流程编排 |
| 后续 | 通用 `resume-resource`（§9.3） | 经 F-56 `ResourceHandler` 按 `resource_type` 恢复；`invoke-existing-agent` 保持兼容或薄封装 |

实现项、未接线项与 F-157 接续边界的完整对照见 §1.3。

F-57 的执行与声明式交付核心路径为 Phase 2 → Phase 3 → Phase 4；宏/原子检索稳定性的当前关键路径为 F-157 P157-A → C → D。Phase 5 会话宏是产品增强，不作为手写宏可用性或 F-157 分层检索的前置条件。通用 `resume-resource` 在 F-56 注册表就绪后作为独立后续项，不阻塞 Phase 2–4 验收。AST/WorkflowGraph 自动推导不在阶段表中，若未来满足 §6.5 条件，应新建独立 Feature 评估。

---

## §16 兼容性与 bundle 迁移

- 现有 `invoke-existing-agent` 名称、aliases、input schema 和 output 字段保持兼容。
- 旧 bundle 中已生成的 Bash `invoke-existing-agent` spec 继续按兼容路径运行，不会因只升级 runtime 自动改成主进程 workflow。
- 新执行一次 convert 会生成 `call_type="workflow"` + `builtin:invoke-existing-agent` 引用；要获得主进程执行必须重新 convert。
- session 宏不要求重新执行 `sop convert`。
- 要加入手写/模板 bundle 宏，现有 bundle 需要带 manifest 重新 convert 一次。
- 新 convert 产物必须记录 macro schema version；遇到更高版本时拒绝执行并给出升级提示，不得猜测解析。

# F-157 ToolSearch Layered Retrieval — 宏工具 / 原子工具分层检索

> **状态**: 🔧 P157-A～D 已实现；P157-E 测试已整理，待开发者手工验收  
> **领域**: 04-architecture-sdk (ToolSearch / SOP Runtime Discovery)  
> **最后更新**: 2026-07-18  
> **关联 Feature**: F-55, F-56, F-57, F-59, F-60

---

## §1 验收结论与问题定义

F-56 已解决“创建后的 SDK 资源如何持久化并恢复”，F-57 已解决“如何把恢复与调用链收成可执行宏”，但刚完成的自然语言验收表明：**宏可执行，不等于 Agent 会稳定选择宏。**

典型失败链是：

```text
用户：用 verify-bot 回复 ping
  → Agent 用语义词搜索 invoke / send / agent
  → SDK 原子工具 llmagent-invoke、send-to-agent 等先进入候选或已在上下文可见
  → 模型直接调用原子工具
  → invoke-existing-agent 宏未执行
```

F-57 `MacroRoute` 已能主动召回宏，`selection=exclusive` 也能在 route 命中后截断 ToolSearch 结果；当前缺口是：

1. route 仍主要依赖 phrase / keyword 命中，语义稍有漂移就回到普通评分；
2. 系统没有一等记录“此宏覆盖哪些原子工具、属于哪个精确检索意图”；
3. `AgentToolSpec.source`、`call_type`、宏 tags 在构造成运行时 `Tool` 后没有形成统一检索层级；
4. exclusive 截断只影响当次返回，不能屏蔽之前已加载、仍暴露给模型的原子工具；
5. 宏目标无法激活时，没有“撤销屏蔽并恢复原子候选”的两阶段提交。

因此本 Feature 不继续扩充同义 phrase 表，而是增加一层结构化检索规划：

> **先判断宏是否覆盖当前检索意图，再决定原子工具是否进入候选与模型可见面。**

---

## §2 目标与非目标

### 2.1 目标

| 目标 | 结果 |
|------|------|
| 区分工具层级 | ToolSearch 可稳定识别 `macro`、`atomic`、`neutral` |
| 建立覆盖关系 | 新宏声明 `intent_key` 与 `covered_tools`，不靠名字猜替代关系 |
| 做实 exclusive | verified exclusive 命中后，覆盖的原子工具从搜索结果和当前暴露面隐藏 |
| 安全恢复 | 宏执行前不可用时撤销隐藏，同一次搜索恢复原子候选 |
| 普通评分偏向宏 | 未达到 exclusive 时，同意图、同语义评分档位内宏优先 |
| 控制语料负担 | phrase 只定义高置信意图边界和少量漂移，不承担宏/原子区分 |
| 可观测 | 每次分层、隐藏、恢复均有结构化 decision/trace |

### 2.2 非目标

- 不用 LLM 分类器替换现有确定性 ToolSearch。
- 不把 F-55 的 lifecycle `IntentGroup` 直接当成隐藏边界；其粒度可能同时包含 create 与 invoke。
- 不在宏已经开始执行后自动重放原子工具；宏 step 可能已有副作用。
- 不要求所有历史工具立即人工补齐 metadata；未分类工具保持 `neutral`，不参与隐藏。
- 不根据 `call_type=workflow` 单字段武断判定所有宏；该字段只作为编译期信号之一。
- 不改变 F-56 ResourceCatalog 的存储、secret 或 materialize 契约。

---

## §3 与 F-55 / F-56 / F-57 的分工

| Feature | 继续负责 | 本 Feature 不接管 |
|---------|----------|------------------|
| F-55 | create/invoke 生命周期依赖、宽粒度 intent group、schema/fallback | 宏覆盖关系与 exclusive 隐藏 |
| F-56 | `resource_type`、资源句柄持久化、查找、materialize/invoke | ToolSearch 排名与候选曝光 |
| F-57 | MacroDefinition、MacroRoute、workflow 执行、宏注册与 preflight 基础 | 宏/原子分层规划和原子候选屏蔽 |
| F-157 | 检索层级、覆盖关系、RetrievalPlan、隐藏/恢复、分层观测 | 资源存取和 workflow step 执行 |

F-157 在 F-57 route 命中与普通 ToolSearch 评分之间增加结构化规划层；F-57 §8.5 的“exclusive 命中后隐藏同组原子工具”由本 Feature 负责完整落地。

---

## §4 核心术语

### 4.1 工具层级 `tool_layer`

| 值 | 定义 | 示例 |
|----|------|------|
| `macro` | 面向用户意图的稳定工作流入口，可协调多个步骤或 trusted runtime chain | `invoke-existing-agent` |
| `atomic` | SDK/API 的单操作暴露，可能是宏的底层能力或语义竞争者 | `llmagent-invoke`、`send-to-agent` |
| `neutral` | 未分类或不参与宏替代关系的通用工具 | Read、Glob、无覆盖声明的 SDK 工具 |

兼容规则：历史工具默认 `neutral`。只有被宏的 `covered_tools` 唯一解析命中的工具，或显式标注的工具，才进入对应 `atomic` 集合。

### 4.2 精确检索意图 `intent_key`

`intent_key` 是供 ToolSearch 使用的窄粒度稳定标识，例如：

```text
agent.create
agent.invoke_existing
team.resume_session
pipeline.run_existing
```

它与 F-55 `agent_lifecycle` 这类宽粒度生命周期组分离。一个 lifecycle group 可以包含多个 `intent_key`，因此不能直接用 lifecycle group 隐藏其中全部原子工具。

### 4.3 覆盖关系 `covered_tools`

宏必须显式声明它在某个 `intent_key` 下替代或封装的原子工具：

```text
invoke-existing-agent
  covers → llmagent-invoke
  covers → send-to-agent
  covers → run-agent
```

这是一条检索关系，不意味着宏的 workflow steps 必须直接调用这些原子工具。`invoke-existing-agent` 可以通过 F-56 trusted private lane 完成同一用户意图，同时在检索层覆盖 SDK invoke 工具。

---

## §5 声明模型

### 5.1 MacroRoute 扩展

在 F-57 `MacroRoute` 基础上新增：

```yaml
version: 1
name: invoke-existing-agent
scope: builtin

routing:
  intent_key: agent.invoke_existing
  target_tool: invoke-existing-agent
  selection: exclusive
  verified: true
  match_mode: all
  priority: 100

  # 语料只负责确认“是否为调用已有 agent”
  phrases:
    - 用已创建的 agent 回复
    - llmagent invoke
  keywords: [agent, 回复]
  negative_keywords: [创建, 配置, 列出, 删除]

  # 结构负责确认“命中后隐藏谁”
  covered_tools:
    - llmagent-invoke
    - send-to-agent
    - run-agent
  unavailable_policy: restore-covered
```

新增字段：

| 字段 | 说明 |
|------|------|
| `intent_key` | 窄粒度检索意图；exclusive 必填 |
| `covered_tools` | 被宏覆盖的原子工具引用；支持 exact、alias、唯一 normalized suffix |
| `unavailable_policy` | P0 仅支持 `restore-covered`；宏预检失败时恢复原子候选 |

现有 `phrases`、`keywords`、`negative_keywords`、`selection`、`verified` 继续由 F-57 MacroRoute 管理。

### 5.2 编译产物 `ToolRetrievalIndex`

`sop convert` 将 ToolSpec 与 MacroRoute 编译为：

```text
<bundle>/.clawcodex/tool-retrieval.yaml
```

示例：

```yaml
version: 1

tools:
  invoke-existing-agent:
    layer: macro
    source: composite-tool
    call_type: workflow
    intent_keys: [agent.invoke_existing]

  openjiuwen-core-application-llm-agent-invoke:
    layer: atomic
    source: sop-converter
    call_type: bash
    intent_keys: [agent.invoke_existing]

coverage:
  - intent_key: agent.invoke_existing
    macro_tool: invoke-existing-agent
    covered_tools:
      - openjiuwen-core-application-llm-agent-invoke
      - openjiuwen-core-controller-legacy-send-to-agent
    selection: exclusive
    verified: true
    unavailable_policy: restore-covered
```

该文件是 convert 产物，不要求用户手写。运行时合并顺序为 `session > bundle > builtin`，但 session/bundle 定义不得静默覆盖 builtin verified exclusive 安全关系。

### 5.3 分类来源与优先级

| 优先级 | 来源 | 用途 |
|--------|------|------|
| 1 | 显式 `tool_layer` / `covered_tools` | 权威分类 |
| 2 | `source=composite-tool` / `sop-converter-macro` | 推断 macro 候选 |
| 3 | `call_type=workflow` + `macro` tag | 推断 macro 候选 |
| 4 | 被 `covered_tools` 唯一解析 | 推断 atomic |
| 5 | 无信号 | `neutral` |

编译期推断必须写入索引，运行时不得每次靠 tag 字符串临时猜测。

### 5.4 校验规则

- `selection=exclusive` 必须同时满足 `verified=true`、非空 `intent_key`、非空 `covered_tools`。
- 每个 `covered_tools` 引用必须在目标 bundle 中唯一解析；歧义或缺失使 convert 原子失败。
- 宏不得覆盖自身、另一个 macro、ToolSearch 或宏管理工具。
- 覆盖图不得形成环。
- 同一 `intent_key` 下多个 verified exclusive 宏必须有冲突语料；无法稳定决胜时降为 `prefer`。
- 新建 bundle/session 宏默认 `prefer`；未验证 exclusive 继续按 F-57 规则降级。
- `neutral` 工具永不因名字相似被隐藏。

---

## §6 分层检索算法

### 6.1 总体顺序

```text
select:<exact-tool>                         # 显式技术覆盖
  → load merged ToolRetrievalIndex
  → match F-57 MacroRoute
  → build RetrievalPlan
  → preflight selected macro
  → commit exclusive suppression OR restore atomics
  → score remaining macro / atomic / neutral candidates
  → apply same-intent macro structural bias
  → F-55 lifecycle reorder within remaining candidates
  → publish ToolSearch matches + active exposure mask
```

`select:<exact-tool>` 保留为显式调试/技术覆盖入口，不做语义改写。Task Guide 在被覆盖意图下只能生成 `select:<macro>`，不得生成 covered atomic 的 select 行。

### 6.2 RetrievalPlan

ToolSearch 不再直接从 route 跳到字符串列表，而是先生成：

```python
@dataclass
class RetrievalPlan:
    query: str
    intent_key: str | None
    selected_macros: list[str]
    suppressed_tools: list[str]
    selection: Literal["exclusive", "prefer", "normal"]
    route_scope: str | None
    preflight_status: Literal["pending", "ready", "unavailable"]
    reason_codes: list[str]
```

先有 plan，后修改候选和上下文，才能实现可回滚的两阶段提交。

### 6.2.1 为何需要三种策略、如何判定

三种 `selection` 是在「敢不敢藏原子工具」上分档，而不是三套互不相关的搜索算法。只做 exclusive 会在误匹配时过度截断候选；只做 prefer 又无法挡住语义重合的原子工具抢戏。因此按置信度分档：

| 策略 | 何时需要 | 行为（白话） |
|------|----------|----------------|
| `exclusive` | 意图很明确（如「调用已有 Agent」），原子工具会抢戏 | 只露宏，并隐藏其 `covered_tools` 中的原子工具 |
| `prefer` | 希望优先宏，但用户仍可能要调单个算子（如手写流水线宏） | 宏置顶，**不**隐藏原子工具 |
| `normal` | 没命中宏路由、exclusive 冲突/非唯一、或宏预检失败 | 退回普通语义搜索，并常带回原子候选 |

**声明侧（作者 / convert）**

- MacroRoute 上写 `selection: exclusive | prefer`，以及 `verified`。
- `exclusive` 必须 `verified=true`，并具备窄粒度 `intent_key` 与非空 `covered_tools`；否则降级为 `prefer`。
- 新建 session / convert 装载的 bundle 手写宏默认 `prefer`；builtin 如 `invoke-existing-agent` 可为 verified exclusive。
- 路由未声明或未命中时，运行时 `RetrievalPlan.selection` 记为 `normal`（普通检索路径）。

**运行时（ToolSearch）判定顺序（摘要）**

```text
query → MacroRoute 匹配
  → 唯一命中 verified exclusive
        → 宏 preflight 通过 → plan.selection=exclusive（提交 suppression）
        → 宏 preflight 失败 → plan.selection=normal，同一次搜索恢复 covered 原子
  → 命中 prefer，或 exclusive 非唯一 / 冲突
        → plan.selection=prefer（宏置顶）或 normal（冲突时常不隐藏）
  → 无宏路由命中
        → plan.selection=normal（语义评分 + 同 tier 结构 tie-break）
```

完整 exclusive / prefer / normal 步骤见 §6.3–§6.5；冲突与回滚见 §6.6、§7。

### 6.3 verified exclusive

唯一高置信 route 命中后：

1. 根据 `covered_tools` 解析原子集合；
2. 对目标宏做无副作用 preflight；
3. preflight 通过后提交 plan；
4. ToolSearch 只返回目标宏；
5. 当前 turn 中已暴露的 covered atomic 从 `ToolContext.options.tools` 移除；
6. 后续同 intent 搜索继续应用 suppression overlay。

“只返回宏”与“原子工具不再暴露”必须同时满足；仅截断当次 `matches` 不算完成。

### 6.4 prefer

`selection=prefer` 时不隐藏原子工具：

```text
[matched macro] + [normal macro candidates] + [atomic candidates] + [neutral candidates]
```

宏只置顶一次，结果保持去重与稳定排序。

### 6.5 普通评分的结构加权

没有 exclusive route 时，仍使用现有 name / alias / tag / description 语义评分；新增以下稳定 tie-break：

1. semantic tier 不同：保持语义评分优先，不让弱相关宏压过 exact atomic；
2. semantic tier 相同且属于同一 `intent_key`：`macro` 排在其 covered `atomic` 之前；
3. macro 不覆盖该 atomic：保持原排序；
4. `neutral` 不参加宏覆盖加权。

P0 不使用一个全局“大额 macro boost”，避免所有 workflow 工具无条件压过精确原子工具。

### 6.6 冲突

- exact phrase > all-keyword > any-keyword。
- verified exclusive 唯一胜者才允许隐藏。
- 两个 exclusive 同分：不隐藏任何原子工具，返回冲突宏并进入 `prefer`。
- route 指向不存在或 metadata 不一致：忽略 exclusive，恢复 covered atomics，记录诊断。
- F-55 lifecycle reorder 只能重排未被 suppression 的候选，不能把已隐藏原子重新插回。

---

## §7 宏可用性预检与恢复

### 7.1 无副作用 preflight

exclusive 提交前至少验证：

- target tool 存在于 bundle allowlist 或 builtin registry；
- persisted AgentToolSpec 可读取且 schema 版本受支持；
- `call_type=workflow` 的 catalog/manifest 引用可解析；
- workflow definition 可加载；
- deferred 注册成功；
- step 工具引用可解析或可 deferred 激活。

preflight 不执行宏 step、不请求业务权限、不 materialize F-56 资源，因此不会产生副作用。

### 7.2 执行前不可用

preflight 失败时：

```text
discard exclusive plan
  → clear suppression overlay
  → re-run normal scoring with covered atomics
  → return atomic candidates + macro_unavailable diagnostic
```

恢复必须发生在同一次 ToolSearch 调用中，不能要求模型再猜一次搜索词。

### 7.3 执行开始后失败

一旦 `ToolRegistry.dispatch(macro)` 开始：

- 不自动调用 covered atomic；
- 返回 F-57 workflow trace、失败 step 和标准错误码；
- 清理当前 exclusive exposure overlay，允许下一次用户明确决策；
- 是否重试或改走原子工具交给 F-59 recovery policy / 用户确认。

### 7.4 陈旧原子句柄保护

若模型持有之前 API turn 暴露的 atomic tool reference，而当前 turn 已提交 exclusive plan，dispatch 层应返回：

```json
{
  "status": "error",
  "error_code": "tool_shadowed_by_macro",
  "recommended_tool": "invoke-existing-agent",
  "intent_key": "agent.invoke_existing",
  "retryable": true
}
```

该 guard 只阻止当前 active plan 中明确 suppressed 的工具，不做全局永久禁用。

---

## §8 F-56 资源信号的使用边界

F-56 可为检索提供只读、无 secret 的结构证据，但不负责意图分类：

| 信号 | P0 行为 |
|------|---------|
| `resource_type=agent` | 用于校验宏 intent 与恢复链类型一致 |
| query 中出现唯一 catalog `resource_id` / alias | 可把对应宏提升到 `prefer` |
| 仅命中资源名、没有动作边界 | 不得单独触发 exclusive |
| catalog payload / secret | ToolSearch 禁止读取或进入 trace |

因此“verify-bot”可以作为已有资源证据减少语料负担，但 exclusive 仍需 verified route 的动作边界或显式 `select:<macro>`。

---

## §9 Skill / Task Guide 契约

convert 生成任务指南时：

- verified exclusive 宏必须生成 `select:<macro-name>`；
- 说明中列出 covered atomic，并明确“此意图勿直接调用”；
- covered atomic 的 lifecycle 行若与宏意图相同，应隐藏或改写为宏恢复说明，避免一张表同时给出冲突指令；
- `allowed_tools` 仍保留宏内部真正需要的底层权限，不因隐藏而绕过 step permission；
- Task Guide 是模型侧约束，RetrievalPlan 才是运行时事实来源。

`invoke-existing-agent` 的目标行：

```text
调用已经创建的 Agent
  → select:invoke-existing-agent
  → 不使用 llmagent-invoke / send-to-agent / run-agent
```

---

## §10 错误码与可观测性

### 10.1 错误码

| code | 场景 | 行为 |
|------|------|------|
| `tool_retrieval_metadata_invalid` | 索引版本/字段非法 | 忽略该索引并退回普通搜索 |
| `macro_coverage_unresolved` | covered tool 缺失或歧义 | convert 原子失败 |
| `macro_preflight_unavailable` | 宏执行前不可激活 | 恢复原子候选 |
| `macro_route_conflict` | exclusive 宏同分 | 降为 prefer，不隐藏 |
| `tool_shadowed_by_macro` | active plan 下调用已隐藏原子 | 推荐宏，不执行原子 |

### 10.2 ToolSearch 输出

兼容保留 `matches`，新增可选诊断：

```json
{
  "matches": ["invoke-existing-agent"],
  "retrieval": {
    "intent_key": "agent.invoke_existing",
    "selection": "exclusive",
    "selected_layer": "macro",
    "suppressed_tools": ["llmagent-invoke", "send-to-agent"],
    "preflight": "ready",
    "reason_codes": ["verified_route", "macro_coverage"]
  }
}
```

### 10.3 F-60 指标

新增：

- `macro_route_hit_count`
- `macro_exclusive_commit_count`
- `atomic_suppressed_count`
- `macro_preflight_failure_count`
- `atomic_restore_count`
- `shadowed_atomic_call_count`
- `first_selected_tool_layer`

---

## §11 代码修改范围

| 文件/模块 | 修改内容 |
|-----------|----------|
| `extensions/sop_converter/macros/models.py` | `MacroRoute.intent_key`、`covered_tools`、`unavailable_policy` |
| `extensions/sop_converter/macros/loader.py` | 解析新增字段 |
| `extensions/sop_converter/macros/validation.py` | exclusive/coverage/环/唯一解析校验 |
| `extensions/sop_converter/macros/persist.py` | 持久化新增 route 字段 |
| `extensions/sop_converter/tool_retrieval.py` | 新增 ToolRetrievalIndex 模型、读写、merge、resolve |
| `extensions/sop_converter/macros/convert.py` | 编译 `.clawcodex/tool-retrieval.yaml` |
| `clawcodex_ext/agent/tool_authoring/factory.py` | 将 `source` / `call_type` / tags 编译信号保留到 retrieval index/runtime profile |
| `clawcodex_ext/tool_system/context.py` | `RetrievalPlan` 与 turn-local suppression overlay |
| `clawcodex_ext/tool_system/tools/tool_search.py` | 两阶段 preflight、提交/回滚、active tool exposure 过滤 |
| `clawcodex_ext/tool_system/tools/tool_search_matching.py` | 分层评分、macro tie-break、suppression 后 lifecycle reorder |
| `clawcodex_ext/tool_system/registry.py` | 陈旧 atomic reference 的 shadow guard |
| `extensions/sop_converter/task_guide.py` | 宏 select 行与冲突 atomic 行消歧 |

---

## §12 测试计划

新增：

```text
tests/tool/test_tool_search_layered_retrieval.py
tests/misc/test_sop_tool_retrieval_index.py
tests/misc/test_sop_macro_coverage_validation.py
```

扩展：

```text
tests/tool/test_tool_search_macro_routes.py
tests/misc/test_sop_macro_convert_phase4.py
tests/misc/test_sop_converter_invoke_existing_agent.py
```

必须覆盖：

- source/call_type/tags 被编译为稳定 tool layer，而不是只留在 ToolSpec。
- covered tool exact、alias、normalized suffix 唯一解析。
- missing、ambiguous、self-cover、macro-cover、cycle 均原子拒绝。
- verified exclusive 命中后 ToolSearch 结果不含 covered atomic。
- covered atomic 已在 `context.options.tools` 中时也被 turn-local 隐藏。
- 陈旧 atomic reference 被 `tool_shadowed_by_macro` 阻止。
- macro preflight 失败时同一次搜索恢复 atomic。
- macro 开始执行后失败不自动重放 atomic。
- prefer 宏置顶但保留 atomic。
- 普通评分同 tier / 同 intent 时宏先于 covered atomic。
- exact atomic 明显强于弱相关宏时保持原子优先。
- create/config/delete 相邻意图不会触发 invoke-existing suppression。
- 两个 exclusive 冲突时不隐藏、结果稳定。
- F-55 lifecycle reorder 不会把 suppressed atomic 插回。
- retrieval trace 不含 F-56 payload 或 secret。

---

## §13 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | verify-bot 调用意图宏独占 | “用 verify-bot 回复 ping”只返回 `invoke-existing-agent` |
| 2 | 最小漂移语料可命中 | “llmagent invoke verify-bot ping”走宏，不返回 SDK invoke 原子 |
| 3 | 已加载原子也被隐藏 | 先加载 `llmagent-invoke`，再命中 exclusive；下一 API turn 不再暴露它 |
| 4 | 宏不可用时恢复 | 删除/禁用宏 target；同一次搜索返回 covered atomic 并带 preflight 诊断 |
| 5 | 执行后不自动重放 | 宏第一 step 后失败，trace 中无原子 fallback 调用 |
| 6 | prefer 保守 | 未验证新宏排第一，但原子候选仍存在 |
| 7 | 普通评分有结构偏置 | 同 tier、同 intent 时 `macro > covered atomic` |
| 8 | 相邻意图不误伤 | “创建/配置/删除 agent”不触发 invoke-existing 独占 |
| 9 | metadata 可扩展 | 新宏只声明 intent + covered tools 即可接入，不改 ToolSearch 硬编码 |
| 10 | 不依赖同义词穷举 | route corpus 只覆盖意图边界、负向与少量漂移，覆盖关系完全由结构元数据决定 |
| 11 | 结果确定 | 相同 query/index/context 多次得到相同 plan、matches、suppressed 集合 |
| 12 | F-56 安全边界不变 | retrieval 日志无 catalog payload/secret，资源恢复仍只经 F-56/F-57 |

---

## §14 分阶段实施

| 阶段 | 内容 | 完成标志 |
|------|------|----------|
| P157-A | MacroRoute coverage 字段 + ToolRetrievalIndex + convert 校验 | 能稳定回答“哪个宏覆盖哪些原子” |
| P157-B | RetrievalPlan + 分层普通评分 | prefer 与同 tier macro bias 生效 |
| P157-C | verified exclusive preflight + 搜索结果 suppression | route 命中后原子不进入 matches |
| P157-D | active exposure mask + shadow guard + 原子恢复 | 已加载原子不可抢戏，宏不可用可回滚 |
| P157-E | Task Guide 消歧 + F-60 指标 + E2E corpus | verify-bot/ping 场景稳定通过 |

第一期优先级为 **A → C → D → B → E**：先做实覆盖关系与 exclusive 隐藏，再补普通评分偏置；phrase 只补最小回归集。

当前实现状态：P157-A/B/C/D 已接线；P157-E 的 Task Guide 消歧、turn-local 指标与自动化用例已提交，完整命令和自然语言 E2E 步骤见 `docs/guide/f157-layered-toolsearch-manual-acceptance.md`，由开发者手工执行后再更新为完成。

---

## §15 兼容性与迁移

- 现有没有 retrieval metadata 的工具按 `neutral` 处理，行为保持不变。
- 现有 F-57 MacroRoute 文件可按 schema v1 读取；缺少 `intent_key` / `covered_tools` 时只能 `prefer`，不得做结构化 exclusive suppression。
- builtin `invoke-existing-agent` 迁移时显式登记 `agent.invoke_existing` 与被覆盖 SDK 工具。
- F-57 原有 `exclusive=True → 直接返回 macro` 的快捷路径迁移为 RetrievalPlan，不再作为独立截断实现。
- bundle 需要重新执行一次 `sop convert` 才能生成 `tool-retrieval.yaml`；旧 bundle 继续走 F-57 route + 普通评分兼容路径。
- 本 Feature 不删除任何 SDK 原子工具；隐藏是 query/turn-local 的可逆检索策略。

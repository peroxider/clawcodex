# F-55 工具生命周期依赖 — SOP Bundle 编排断裂修复

> **状态**: 🔍 已分析，待实施  
> **领域**: 04-architecture-sdk (SOP Converter / SDK Tooling)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-50 (SOP Converter), F-52 (SDK→Tool 注册), F-18 (CreateAgentTool)

---

## §1 背景

### 1.1 问题复现

用户通过 SOP 代理 Agent 完成了 Agent 创建（`agentbuilder-build-agent`），拿到 ID `0f40ed92-...`，但后续「按 ID 调用 Agent 回复 ping」的任务在子代理 `core_merged-agent` 中**失败**：

| 步骤 | 结果 |
|------|------|
| 创建 Agent（`agentbuilder-build-agent`） | ✅ 返回 DSL + agent_id，报告「已就绪」 |
| `run-agent(agent_id="0f40ed92-...", inputs="ping")` | ❌ `'str' object has no attribute 'get'`（inputs 格式问题，已修复） |
| `run-agent(agent=ID, ...)` | ❌ `agent not exist`（Runner 无此 ID） |
| `llmagent-invoke` | ❌ `ReActAgentConfig` 与 Legacy 路径不兼容 |
| `send-to-agent` | ❌ 抽象类/配置缺失 |
| 反复 ToolSearch / Bash 读源码 | ❌ 消耗约 30 轮后超时 |

主循环最终绕过 SOP，用 Python SDK 直接 `invoke` 才拿到 ping 回复。

### 1.2 影响范围

凡涉及 **「SOP 创建 Agent 后，再按 ID 调用」** 的场景均可能复现：

- 创建成功、报告「已就绪」
- 调用阶段 ToolSearch 空转、选错工具、缺少 catalog 恢复 / materialize 路径
- `run-agent` → `agent not exist`
- 需主循环绕过 SOP 用 Python SDK 才能完成

---

## §2 根因分析

### 2.1 核心断裂：创建 → 调用缺少可恢复的运行时链路

```
创建路径:  agentbuilder-build-agent → SDK 调用 → DSL + agent_id（元数据）
                                                        ↓
                                             缺中间步骤:
                                             ① 持久化 agent_id → DSL/config 映射
                                             ② 调用时 materialize
                                             ③ 在同一运行时 invoke / run
                                                        ↓
调用路径:  invoke-existing-agent(agent_id)
                ↓
          catalog lookup → materialize → invoke / run → OK
                ↓
          ❌ catalog missing / materialize failed
```

创建报告写「Agent 已就绪，可用 ID 调用」，但 `agentbuilder-build-agent` **只返回了 ID 字符串，没有将可 materialize 的 DSL/config 持久化到一个后续工具可读取的 catalog**。当前 SOP converter 生成的 SDK 工具通常通过 bash wrapper 在独立 Python 子进程中执行；即便创建工具在内存 Runner 中完成 `add_agent`，下一次 `run-agent` 也可能运行在另一个进程，看不到前一次的内存 registry。因此问题不是单纯“少了一次 add_agent”，而是 **agent_id 到可调用实例的恢复路径没有成为一等运行时契约**。

### 2.2 元数据断层：SOP bundle 无依赖描述

当前 SOP converter 生成的 bundle 包含：

| 元数据类型 | 位置 | 用途 |
|-----------|------|------|
| `allowed-tools` | Skill frontmatter | 工具白名单 |
| `search_tags` | `AgentToolSpec.tags` | ToolSearch 匹配 |
| `intent_phrases` | ToolSearch metadata | 自然语言搜索 |
| Task Guide 表格 | SKILL.md | 操作指引 |

**缺少**：

- 工具间的 **生命周期依赖关系**（`build_agent` → catalog → `invoke_existing_agent` / `run_agent` fallback）
- **隐藏步骤声明**（persist catalog + materialize + invoke 对 Agent 不可见但必需）
- **参数传递链**（`agent_id` 跨步骤隐式传递）
- **意图族分组**（哪些工具属于同一生命周期）

### 2.3 ToolSearch 无法推断隐藏依赖

`tool_registry_bridge.py` 的签名分析只能推断：

- `build_agent` 返回 `Dict`（DSL）
- `run_agent` 接收 `agent_id: str`
- 两者签名类型不匹配 → 无法建立依赖关系

静态分析推不出「`build_agent` 的 DSL 必须先被持久化，再在调用阶段 materialize，最后在同一运行时 invoke / run」——这是**生命周期依赖**，不是普通类型传递。

### 2.4 ToolSearch 语义撞车

子代理的任务指南无「对已创建 Agent 按 ID 发消息」标准路径，导致：

- `invoke agent` / `send message` / `run agent` 同时匹配 Runner、LLMAgent、Session 等多域工具
- 顺序不确定 → 反复尝试错误工具 → 轮次耗尽

---

## §3 解决方案

### 3.1 方案总览

采用**三明治修复**策略，按实施顺序分三层：

| 层 | 方案 | 修复点 | 优先级 |
|----|------|--------|--------|
| **L1** | Agent catalog + 调用时自动恢复 | 创建阶段持久化 DSL/config；调用阶段 materialize + invoke/run | P0 |
| **L2** | Bundle 依赖元数据 | 新增 `tool-dependencies.yaml` + SOP converter 生成逻辑 | P1 |
| **L3** | Task Guide 增强 + ToolSearch 排序 | `task_guide.py` + `search_tags.py` | P1 |

---

### 3.2 L1 — Agent catalog + 调用时自动恢复（核心修复）

#### 3.2.1 改动目标

修改 `agentbuilder-build-agent`（或对应的 SDK wrapper 工具），在创建 Agent 后**持久化 `agent_id → DSL/config/model/provider/创建来源` 映射**。同时新增或改造按 ID 调用的入口（推荐新增宏工具 `invoke-existing-agent`，或给 `run-agent` 增加 fallback），在调用阶段自动读取 catalog、materialize，并在同一运行时完成 invoke / run。

P0 不应依赖“创建工具把实例注册进内存 Runner 后，后续工具仍能看到该 Runner”。SOP SDK 工具当前是独立子进程 wrapper 模型，内存 registry 不是跨工具调用的可靠边界。

#### 3.2.2 改动后流程

```
agentbuilder-build-agent(creds, config, name)
  │
  ├─ 1. SDK 调用创建 Agent → DSL + agent_id
  ├─ 2. persist: 写入 Agent catalog（agent_id → DSL/config/model/provider/metadata）
  ├─ 3. optional smoke check: 可选 materialize 校验，不要求保留内存实例
  └─ 4. return {"agent_id": agent_id,
                 "status": "created_persisted",
                 "hint": "可通过 invoke-existing-agent 或 run-agent fallback 按 ID 调用"}

invoke-existing-agent(agent_id, inputs/query)
  │
  ├─ 1. 从 Agent catalog 读取 DSL/config
  ├─ 2. materialize: create_llm_agent(DSL/config)
  ├─ 3. 在当前工具调用运行时 invoke / run
  └─ 4. 返回 output 原文
```

#### 3.2.3 实现要点

- **持久化 catalog**：创建成功后写入 bundle/session 可定位的 catalog，例如 `<bundle>/.clawcodex/agent-catalog.json` 或 `$CLAWCODEX_HOME/sop-agents/<bundle_id>/agents.json`
- **幂等性**：同一 `agent_id` 重复写入时合并 metadata；不得覆盖不兼容 DSL
- **调用入口收敛**：优先新增 `invoke-existing-agent(agent_id, query|inputs)` 作为标准宏工具；也可让 `run-agent` 在 `agent not exist` 时查 catalog 并自动恢复
- **同进程执行**：materialize 与 invoke / run 必须在同一次工具调用内完成，避免依赖前一次 wrapper 子进程中的内存状态
- **错误隔离与提示**：catalog 缺失、DSL 缺字段、materialize 不兼容时返回明确错误，不再让模型在 `llmagent-invoke` / `send-to-agent` / `run-agent` 间空转
- **报告措辞**：创建工具只有在 catalog 写入成功后，才可报告“可按 ID 调用”；否则必须报告“已创建但缺少可恢复调用记录”

#### 3.2.4 代码位置

```
改动文件：
  extensions/sop_converter/agent_catalog.py             ← 新增：catalog 读写
  extensions/sop_converter/composite_tools/             ← 新增/扩展：invoke-existing-agent 宏工具
  extensions/sop_converter/tool_registry_bridge.py      ← wrapper 生成：识别创建/调用类工具并注入 catalog 钩子
  clawcodex_ext/agent/tool_authoring/call_handlers/     ← 工具 call handler，可做 run-agent fallback
  
依赖：
  SOP SDK 的 create/materialize/invoke API
  AgentToolSpec.bundle_id / bundle tool dir
  src/tool_system/context.py                ← 可用于定位 bundle/session 上下文
```

---

### 3.3 L2 — Bundle 依赖元数据

#### 3.3.1 新增文件

`<bundle>/.clawcodex/tool-dependencies.yaml`

由 SOP converter 在工作流模式下从源码分析生成。

#### 3.3.2 格式定义

```yaml
# tool-dependencies.yaml — SOP bundle 工具生命周期依赖
# 由 sop convert / pos convert 自动生成，位于 bundle 根目录

version: 1

# ── 依赖链 ──────────────────────────────────────
# from:   前置工具名（kebab-case）
# to:     后置工具名（kebab-case）
# shared_params: 跨步骤传递的参数名列表
# hidden_steps:  中间隐含的运行时步骤（Agent 不可直接调用）
# lifecycle:     语义标签，用于 ToolSearch 排序

dependencies:
  - from: agentbuilder-build-agent
    to: invoke-existing-agent
    shared_params: [agent_id]
    hidden_steps:
      - action: persist_agent_catalog
        description: 保存 agent_id → DSL/config/model/provider 映射
      - action: materialize_on_invoke
        description: 调用时从 catalog 恢复并 create_llm_agent(DSL/config)
      - action: invoke_same_runtime
        description: 在同一工具调用运行时执行 invoke / run
    lifecycle: create → invoke

  - from: create-team-session
    to: run-agent-team
    shared_params: [session_id]
    lifecycle: create → invoke

  - from: load-spec-yaml
    to: start-team-session
    shared_params: [config_path]
    lifecycle: prepare → execute

# ── 意图族（解决 ToolSearch 撞车） ──────────────
# 同组工具共享语义意图，ToolSearch 可一次性返回
# 并按依赖顺序排列

intent_groups:
  agent_lifecycle:
    description: "Agent 完整生命周期（创建→持久化→恢复→调用）"
    tools:
      - agentbuilder-build-agent
      - invoke-existing-agent  # 推荐宏工具；若缺失则使用带 catalog fallback 的 run-agent
      - run-agent
    primary_entry: agentbuilder-build-agent   # 首选入口

  session_lifecycle:
    description: "团队会话生命周期"
    tools:
      - load-spec-yaml
      - create-agent-team-session
      - run-agent-team
    primary_entry: start-team-session   # macro 入口（若有）

# ── ToolSearch 优先级 ⚠️ P2 ─────────────────────
# 当 query 命中以下关键词时，优先返回对应组工具

priority_routes:
  - keywords: ["create agent", "build agent", "new agent", "创建 agent"]
    intent_group: agent_lifecycle
    entry_first: true

  - keywords: ["invoke agent", "run agent", "call agent", "调用 agent"]
    intent_group: agent_lifecycle
    entry_first: false    # 已有 agent_id 时优先返回 invoke-existing-agent / run-agent fallback
```

#### 3.3.3 SOP converter 生成逻辑

在 `extensions/sop_converter/workflow_mode/` 中新增依赖推断步骤：

```
[SourceComponent 列表]
       ↓
依赖推理引擎 (detect_lifecycle_patterns)
       │
       ├─ 识别 build_* / create_* ↔ run_* / invoke_* 配对
       ├─ 提取共享参数名
       ├─ 识别已知隐藏步骤模板
       └─ 分组 intent_groups
       ↓
[ToolDependencyGraph]  →  写入 tool-dependencies.yaml
```

**识别启发式规则**：

| 模式 | 推断 |
|------|------|
| `build_*` 返回 ID + `invoke_*` / `run_*` 接收 ID | `build → catalog → invoke` 依赖链 |
| `create_*` 返回 ID + `invoke_*` 接收 ID | `create → invoke` 依赖链 |
| 参数名与返回字段同名 | 共享参数传递 |
| `load_*` + `create_*` + `run_*` | 三阶段链 |
| `start-*` 是 macro 包装器 | 标记为 primary_entry |

#### 3.3.4 运行时消费

**消费方 1 — Task Guide 生成器**（`task_guide.py`）：

```python
# 读取 tool-dependencies.yaml，注入 task guide 表格
def _lifecycle_task_guide_rows(deps: list[Dependency]) -> list[tuple]:
    """生成依赖链对应的 task guide 行。"""
    rows = []
    for dep in deps:
        hidden_note = ""
        if dep.hidden_steps:
            steps = " → ".join(s.action for s in dep.hidden_steps)
            hidden_note = f"（自动：{steps}）"
        rows.append((dep.from, f"调用{dep.to}的前置步骤", hidden_note))
        rows.append((dep.to, f"前置：{dep.from}{hidden_note}", ""))
    return rows
```

**消费方 2 — ToolSearch 排序器**（P2 可选）：

```python
# 当 query 命中 priority_routes 关键词时
# 1. 找到对应 intent_group
# 2. 按依赖顺序排列工具列表
# 3. primary_entry 置顶
def rank_tools_by_lifecycle(
    matches: list[ToolMatch],
    query: str,
    deps: ToolDependencyGraph,
) -> list[ToolMatch]:
    ...
```

**消费方 3 — 运行时校验**（P2 可选）：

在子代理启动时，若 bundle 包含 `tool-dependencies.yaml`，注入一条 system prompt 摘要：

```
## 工具生命周期提示（来自 bundle 元数据）
本 bundle 检测到以下工具依赖链：
- agentbuilder-build-agent → [持久化 catalog] → invoke-existing-agent
  已有 agent_id 时优先使用 invoke-existing-agent；若只有 run-agent，则确认其具备 catalog fallback。
```

---

### 3.4 L3 — Task Guide + System Prompt 增强

#### 3.4.1 `domain_agent_sop_body()` 增加 Agent 生命周期段

在 `extensions/sop_converter/sop_prompts.py` 的 `domain_agent_sop_body()` 函数末尾增加条件块：

```python
def _lifecycle_prompt_block(bundle: BundleContext | None) -> str:
    """如果 bundle 含 tool-dependencies.yaml，生成生命周期提示块。"""
    if bundle is None:
        return ""
    deps_path = bundle.bundle_path / ".clawcodex" / "tool-dependencies.yaml"
    if not deps_path.exists():
        return ""
    # 解析依赖并生成提示文本
    ...
    return """\
## 工具生命周期提示

本 bundle 的工具间存在以下依赖关系，请注意调用顺序：

| 前置工具 | 后置工具 | 说明 |
|----------|----------|------|
| agentbuilder-build-agent | invoke-existing-agent | 创建后写入 Agent catalog，已有 agent_id 时由调用工具自动 materialize 并 invoke |

• 如果后置工具返回 `not found` / `not exist` 类错误，请先检查前置工具是否已调用
• 已标记为「自动完成」的中间步骤无需手动调用；但若 catalog 缺失，应报告缺失而不是改搜其他 Agent 工具
"""
```

#### 3.4.2 Task Guide 增加依赖链行

在 `generate_task_guide_markdown()` 中，若 bundle 含依赖元数据，在表格末尾追加依赖链信息。

#### 3.4.3 Skill frontmatter 增加 `lifecycle-deps` 引用（P2）

```yaml
# SKILL.md frontmatter 扩展
name: core_merged-skill
description: Core Engine 域工具
allowed-tools:
  - agentbuilder-build-agent
  - run-agent
lifecycle-deps: .clawcodex/tool-dependencies.yaml  # 新增
```

---

### 3.5 实施依赖关系

```
L1 (catalog + 恢复调用) ─ P0，无前置依赖
     │
     ├── 阻断 L2 的运行时消费（如果没有可恢复调用路径，依赖元数据只能减少空转，不能让调用成功）
     │
L2 (依赖元数据) ───── P1，依赖 L1 的格式命名
     │
     ├── task_guide.py 消费 ← 独立，可不依赖 L2 全量实现
     │
L3 (prompt 增强) ──── P1，依赖 L2 格式定型
```

---

## §4 验收标准

### 4.1 L1 验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | `agentbuilder-build-agent` 创建 Agent 后写入 catalog | catalog 中存在 `agent_id → DSL/config/model/provider` |
| 2 | 两次独立工具调用仍可按 ID invoke | `build-agent` 子进程结束后，再调用 `invoke-existing-agent(agent_id, query="ping")` 成功 |
| 3 | 已有 `agent_id`、当前轮未创建，也可恢复调用 | 直接从 catalog 读取并 materialize，返回 output 原文 |
| 4 | `run-agent` fallback（若实现）遇到 `agent not exist` 自动查 catalog | 能恢复则成功；不能恢复则返回明确 `agent catalog missing` |
| 5 | 创建报告措辞准确 | catalog 写入失败时不得报告“可直接按 ID 调用” |
| 6 | 重复写入幂等 | 同一 agent_id 重复创建/保存不破坏已有 DSL |

### 4.2 L2 验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | `sop convert` 后 bundle 目录生成 `.clawcodex/tool-dependencies.yaml` | 文件存在且格式合法 |
| 2 | 依赖链推断正确：`build_*` + `run_*` 配对并提取 `agent_id` | 人工审核生成结果 |
| 3 | 无显式配对时不误报（如独立工具无依赖链） | 空列表或无此文件 |
| 4 | `intent_groups` 分组合理 | 每组工具语义一致 |

### 4.3 L3 验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | 子代理 system prompt 含生命周期提示块 | 查验 `domain_agent_sop_body` 输出 |
| 2 | Task Guide 表格含依赖链行 | 查验 `generate_task_guide_markdown` 输出 |
| 3 | ToolSearch 含 `lifecycle-chain` 高级 query 支持 | 单元测试覆盖 |

### 4.4 E2E 验收

| # | 场景 | 期望 |
|---|------|------|
| 1 | 创建 Agent → 立即按 ID 调用 | 一次成功，ToolSearch 不空转 |
| 2 | 创建 Agent → wrapper 子进程退出 → 再按 ID 调用 | 通过 catalog 自动 materialize 并返回 ping 原文 |
| 3 | 创建 Agent → 关闭会话 → 新会话按 ID 调用（若 catalog 位于持久目录） | 成功恢复；若配置不支持跨会话，返回明确 `catalog unavailable` |
| 4 | 已有 agent_id 但 catalog 无记录 | 返回 `agent catalog missing`，不再在多个 invoke/send/run 工具间反复尝试 |

---

## §5 风险与约束

| 风险 | 影响 | 缓解 |
|------|------|------|
| catalog 泄漏敏感配置 | 可能持久化 API key / provider 凭据 | catalog 只存可重建配置引用或脱敏字段；敏感值走环境变量 / secret store |
| SDK DSL 版本演进 | 旧 catalog 记录无法 materialize | catalog 加 `schema_version` / `sdk_version`，失败时返回可诊断错误 |
| 调用宏工具覆盖不同 SDK 的 invoke 形态 | Agent SDK API 差异导致适配成本 | v1 只支持 Python SDK 已知 agentbuilder/llmagent 路径；其他 SDK 显式 unsupported |
| `tool-dependencies.yaml` 格式演进增加维护成本 | L2 JSON Schema + 版本号 | v1 最小集，后期兼容扩展 |
| 依赖推断启发式误报 | Task Guide 误导用户 | 人工审核 + 允许 `tool-dependencies.yaml.override` |
| 与上游 Claude Code merge 冲突 | 修改 `src/` 下的 Runner 相关代码 | 优先通过 `extensions/sop_converter/` 与 `clawcodex_ext/` 扩展实现 |

---

## §6 未涵盖的范围

以下问题已确认不在本方案 P0/P1 范围内，记录供后续参考：

- **完整跨机器 / 跨环境恢复**：L1 catalog 解决同机同 bundle 的可恢复调用；跨机器迁移、secret 同步、远端 Runner 恢复为独立 Feature
- **ToolSearch 全量重写**：L2 的 `priority_routes` 仅做关键词匹配，不做语义理解 → 若后续需要可引入 `intent_tags` 向量相似度
- **运行时依赖图 DAG 校验**：当前不阻止违反依赖顺序的调用 → 若频繁出现可加运行时 guard
- **非 Python SDK 工具**：当前方案仅适用于 Python SDK 解析的 SOP 工具；非 Python（OpenAPI、protobuf）需各自适配 `hidden_steps` 模板

---

## §7 附录

### 7.1 ToolDependencyGraph 数据结构（参考）

```python
# extensions/sop_converter/dependency/models.py (新增)

@dataclass
class HiddenStep:
    action: str              # persist_agent_catalog / materialize_on_invoke / invoke_same_runtime
    description: str         # 人工可读说明

@dataclass
class ToolDependency:
    from_tool: str           # agentbuilder-build-agent
    to_tool: str             # invoke-existing-agent
    shared_params: list[str] # ["agent_id"]
    hidden_steps: list[HiddenStep] = field(default_factory=list)
    lifecycle: str = ""      # "create → invoke"

@dataclass
class IntentGroup:
    name: str
    description: str
    tools: list[str]
    primary_entry: str | None = None

@dataclass
class PriorityRoute:
    keywords: list[str]
    intent_group: str
    entry_first: bool = True

@dataclass
class ToolDependencyGraph:
    version: int = 1
    dependencies: list[ToolDependency] = field(default_factory=list)
    intent_groups: list[IntentGroup] = field(default_factory=list)
    priority_routes: list[PriorityRoute] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> ToolDependencyGraph: ...
    def save(self, path: Path) -> None: ...
    def detect_from_components(
        cls, components: list[SourceComponent]
    ) -> ToolDependencyGraph: ...
```

### 7.2 依赖推断引擎（参考架构）

```
extensions/sop_converter/dependency/
├── __init__.py
├── models.py            # ToolDependencyGraph 数据模型
├── detector.py          # detect_lifecycle_patterns() 主入口
├── heuristics.py        # 配对启发式规则
├── writer.py            # YAML 写入
├── reader.py            # YAML 读取（运行时消费方用）
└── prompts.py           # 生成 system prompt 块
```

### 7.3 与本方案相关的现有代码

| 文件 | 与本方案关系 |
|------|-------------|
| `extensions/sop_converter/sop_prompts.py` | L3 修改目标：`domain_agent_sop_body()` 增加生命周期块 |
| `extensions/sop_converter/task_guide.py` | L3 修改目标：`generate_task_guide_markdown()` 增加依赖链行 |
| `extensions/sop_converter/bundle_context.py` | L2 消费：读取 `tool-dependencies.yaml` |
| `extensions/sop_converter/search_tags.py` | P2 扩展：`priority_routes` 支持 |
| `clawcodex_ext/agent/tool_authoring/factory.py` | L1 参考：`build_tool_from_spec()` |
| `clawcodex_ext/agent/run_agent.py` | L1 参考：`RunAgentParams` / `run_agent()` |

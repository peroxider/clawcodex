# F-55 工具生命周期依赖 — SOP Bundle 编排断裂修复

> **状态**: ✅ L1（catalog 恢复）+ L2（`tool-dependencies.yaml`）+ L3（Task Guide / ToolSearch）已实现；§7 类型契约已接线（可扩展性见 F-56 §14）。旧「Bundle Venv 长驻子进程」方案见附录 B（已废弃）。  
> **领域**: 04-architecture-sdk (SOP Converter / SDK Tooling)  
> **最后更新**: 2026-07-18  
> **关联 Feature**: F-50 (SOP Converter), F-52 (SDK→Tool 注册), F-18 (CreateAgentTool), F-56, F-57

---

## §0 实现现状（相对原文方案）

| 层 | 文档原方案 | 当前代码 |
|----|-----------|----------|
| **L1** | create 持久化 + invoke 时 materialize | ✅ create 经 `--catalog-metadata` 写入 F-56 `ResourceCatalog`；调用经 `invoke-existing-agent`（F-57）或 `--catalog-fallback` |
| **L2** | 生成 `tool-dependencies.yaml` | ✅ `extensions/sop_converter/dependency/` + convert 时写出 `.clawcodex/tool-dependencies.yaml` |
| **L3** | Task Guide / system prompt / Skill frontmatter | ✅ `sop_prompts._lifecycle_prompt_block`、`task_guide` 依赖行、`lifecycle-deps:` frontmatter |
| **ToolSearch** | `priority_routes` / `rank_tools_by_lifecycle` | ✅ `tool_search_matching.rank_tools_by_lifecycle`；支持 `lifecycle-chain:` query |
| **§7 类型契约** | `resource_type` 匹配 + `resource_ref` 注入 | ✅ `heuristics/lifecycle.py`；参数名 `*_id` 仅兜底 |
| **依赖隔离** | 曾设计长驻 BundleWorker | ❌ 废弃（见附录 B）；现用 `bundle_venv` 激活 / bash 注入 site-packages + in-process wrapper |
| **search_tags ← resource_type** | §7.3 Layer 3 设想自动共享类型关键词 | ❌ **未实现**；`generate_search_tags` 仍从 name/description/param 派生；宏 tags 手写 |

§1–§2 保留为**问题复现与根因**（修复前状态）。§3 起为原设计；实施结果以本表与 §7 / F-56 为准。

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

### 2.2 元数据断层：SOP bundle 曾无依赖描述（已补齐）

修复前，SOP converter 生成的 bundle 仅有：

| 元数据类型 | 位置 | 用途 |
|-----------|------|------|
| `allowed-tools` | Skill frontmatter | 工具白名单 |
| `search_tags` | `AgentToolSpec.tags` | ToolSearch 匹配 |
| `intent_phrases` | ToolSearch metadata | 自然语言搜索 |
| Task Guide 表格 | SKILL.md | 操作指引 |

当时**缺少**、现已由 L2/L3 补齐：

| 曾缺项 | 当前产物 / 消费方 |
|--------|-------------------|
| 生命周期依赖关系 | `.clawcodex/tool-dependencies.yaml`（`detect_lifecycle_patterns`） |
| 隐藏步骤声明 | `hidden_steps`（persist / materialize / invoke） |
| 参数传递链 | `shared_params` + create `handle_field` / invoke `resource_ref` |
| 意图族分组 | `intent_groups` + ToolSearch `priority_routes` |

### 2.3 ToolSearch 曾无法推断隐藏依赖（已部分解决）

仅靠签名分析仍推不出「必须先 persist catalog 再 materialize」——这是**生命周期依赖**，不是普通类型传递。现通过：

1. convert 时写出 `tool-dependencies.yaml`（显式依赖图）
2. §7 类型契约：`produces` / `consumes` 同 `resource_type` 即配对
3. ToolSearch 消费 `priority_routes` / `lifecycle-chain:`（不靠猜参数名）

### 2.4 ToolSearch 语义撞车（缓解中）

修复前子代理无「对已创建 Agent 按 ID 发消息」标准路径，导致多域工具撞车。现有缓解：

- 宏工具 `invoke-existing-agent` 作为标准恢复入口
- Skill `lifecycle-deps` + system prompt 生命周期块
- `rank_tools_by_lifecycle` 按 intent group 排序

> 注意：§7.3 设想的「search_tags 自动注入 `resource_type`」**尚未实现**；召回仍主要依赖依赖图与手写/启发式 tags。

---

## §3 解决方案

### 3.1 方案总览

采用**三明治修复**策略，按实施顺序分三层（**均已落地**，见 §0）：

| 层 | 方案 | 修复点 | 优先级 | 状态 |
|----|------|--------|--------|------|
| **L1** | Agent catalog + 调用时自动恢复 | 创建阶段持久化 DSL/config；调用阶段 materialize + invoke/run | P0 | ✅ |
| **L2** | Bundle 依赖元数据 | `tool-dependencies.yaml` + SOP converter 生成逻辑 | P1 | ✅ |
| **L3** | Task Guide 增强 + ToolSearch 排序 | `task_guide.py` + `sop_prompts.py` + `tool_search_matching.py` | P1 | ✅ |

> 主路径句柄契约以 §7（`resource_type` / `resource_ref`）为准；§3.2.3 原文以 `*_id` 为中心的描述仅作历史兜底路径。

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

#### 3.2.4 代码位置（已实现）

```
核心：
  extensions/sop_converter/resource_catalog.py          ← F-56 ResourceCatalog / get_resource_record
  extensions/sop_converter/resource_handlers.py         ← resource_type 注册表（Agent 为首行）
  extensions/sop_converter/agent_catalog.py             ← legacy AgentCatalog（仍双写）
  extensions/sop_converter/agent_runtime.py             ← materialize_agent / invoke_agent
  extensions/sop_converter/heuristics/lifecycle.py      ← 类型契约 + catalog metadata/fallback payload
  extensions/sop_converter/bundle_resources.py          ← resources.yaml sidecar
  extensions/sop_converter/dependency/                  ← L2 ToolDependencyGraph
  extensions/sop_converter/tool_registry_bridge.py      ← convert：钩子 + 写出 tool-dependencies.yaml
  extensions/sop_converter/composite_tools/builtin.py   ← invoke-existing-agent 宏
  extensions/sop_converter/composite_workflows.py       ← F-57 trusted workflow
  clawcodex_ext/agent/tool_authoring/call_handlers/     ← in-process / bash + catalog fallback
  clawcodex_ext/tool_system/tools/tool_search_matching.py ← rank_tools_by_lifecycle

依赖隔离（非 BundleWorker）：
  extensions/sop_converter/bundle_venv.py               ← ensure / activate bundle venv imports
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

#### 3.3.3 SOP converter 生成逻辑（已实现）

在 convert 注册组件工具时调用 `detect_lifecycle_patterns`（模块：`extensions/sop_converter/dependency/`，非单独挂在 `workflow_mode/` 下）：

```
[SourceComponent 列表]
       ↓
依赖推理引擎 (detect_lifecycle_patterns)
       │
       ├─ 识别 build_* / create_* ↔ run_* / invoke_* 配对（含 §7 类型匹配）
       ├─ 提取共享参数名
       ├─ 识别已知隐藏步骤模板
       └─ 分组 intent_groups
       ↓
[ToolDependencyGraph]  →  写入 .clawcodex/tool-dependencies.yaml
```

**识别启发式规则**：

| 模式 | 推断 |
|------|------|
| `build_*` 返回 ID + `invoke_*` / `run_*` 接收 ID | `build → catalog → invoke` 依赖链 |
| `create_*` 返回 ID + `invoke_*` 接收 ID | `create → invoke` 依赖链 |
| 参数名与返回字段同名 | 共享参数传递 |
| `load_*` + `create_*` + `run_*` | 三阶段链 |
| `start-*` 是 macro 包装器 | 标记为 primary_entry |

#### 3.3.4 运行时消费（已实现）

**消费方 1 — Task Guide 生成器**（`task_guide.py`）：读取 `tool-dependencies.yaml`，追加依赖链行。

**消费方 2 — ToolSearch 排序器**：`rank_tools_by_lifecycle` 在命中 `priority_routes` 时按 intent group / 依赖链重排；支持 `lifecycle-chain:` 高级 query。

**消费方 3 — System prompt**：`domain_agent_sop_body` → `_lifecycle_prompt_block`，bundle 含依赖文件时注入生命周期提示。

**消费方 4 — Skill frontmatter**：存在依赖文件时写入 `lifecycle-deps: .clawcodex/tool-dependencies.yaml`。

---

### 3.4 L3 — Task Guide + System Prompt 增强（已实现）

#### 3.4.1 `domain_agent_sop_body()` 生命周期段

`extensions/sop_converter/sop_prompts.py` 中 `_lifecycle_prompt_block(bundle)`：若存在 `.clawcodex/tool-dependencies.yaml` 则注入调用顺序提示。

#### 3.4.2 Task Guide 依赖链行

`generate_task_guide_markdown()` 读取同一依赖文件，在表格末尾追加依赖链信息。

#### 3.4.3 Skill frontmatter `lifecycle-deps`

```yaml
# SKILL.md frontmatter（convert 时按文件是否存在写入）
lifecycle-deps: .clawcodex/tool-dependencies.yaml
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

## §7 设计补丁：从参数名启发式升级为类型契约驱动

> **状态**: ✅ 类型匹配、`resource_ref` schema 注入、动态句柄与 F-56 注册表接线已实现；E1–E5 矩阵已绿（见 F-56 §14）。
> **触发场景**: JiuwenAgent SDK 的 `llmagent-invoke` 工具因参数名为 `agent_config`（而非 `agent_id`）被误判为 `lifecycle="none"`，导致 catalog fallback 与 schema 注入双双失效；agent 被迫绕过 SOP 直接调用 SDK 才能完成任务（详见 §1.1 与 7 月 15 日回归分析）。

### 7.1 为什么原方案不通用

§3.2.3 的 `infer_lifecycle_kind` 判定 invoke 类工具的唯一硬条件是：

```
参数名匹配 /^(?:[a-z]+_)?id$|^[a-z]+_id$/  →  才算 "invoke"
```

这条规则把"id 一定叫 `xxx_id`"当作跨 SDK 的不变量，但实际不是：

| SDK | 句柄参数名 | 原启发式判定 |
|-----|-----------|-------------|
| JiuwenAgent | `agent_config` | ❌ none（fallback 失效） |
| 假设 SDK B | `instance` | ❌ none |
| 假设 SDK C | `handle` | ❌ none |
| 旧 AgentBuilder | `agent_id` | ✅ invoke |

补 `agent_config` / `instance` / `handle` 都是治标——下一个 SDK 又要加一条。真正的不变量不是**参数名**，而是**资源类型**：create-X 产出的资源有类型，invoke-X 消费的资源有类型，两者类型一致即构成生命周期对。

### 7.2 核心思想：resource_type 作为一等公民

[SourceOperation](file:///d:/projects/clawcodex/extensions/sop_converter/source_parser.py#L175-L191) 已携带 `return_type: str` 与 [ParamSpec.type_hint](file:///d:/projects/clawcodex/extensions/sop_converter/source_parser.py#L109-L116)；类型信息已经在，无需 SDK 作者额外声明。缺的只是把它们用作依赖线索。

引入新概念 `resource_type`：从 `return_type` / `type_hint` 抽取的规范化类型名（如 `AgentConfig` / `TeamSession` / `SessionHandle`）。匹配规则：

```
create_agent   return_type=AgentConfig         → produces: AgentConfig
invoke         param agent_config: AgentConfig → consumes: AgentConfig
                                          ↑ 类型相同 → 自动建立依赖
```

类型匹配成功后：
- 自动给 invoke-X 的 schema 注入一个字段，字段名按 `resource_type` 派生（如 `agent_config_handle`），描述写明"由 `create-llm-agent` 返回值提供"
- create-X 的 wrapper 在 catalog 写入时记录"哪个返回字段是句柄"（动态发现，不靠猜）
- invoke-X 的 fallback 按 `resource_type` 从 catalog 取最近一条记录，按记录里的 `handle_field` 取句柄

### 7.3 三层修复（替代 §3.2.3 的实现要点）

#### Layer 1 — 事前：schema 自然暴露句柄（治本）

不再让 `infer_lifecycle_kind` 猜参数名。改用类型匹配表：

| 工具签名 | produces / consumes | 判定 |
|---------|--------------------|------|
| `create_agent() -> AgentConfig` | produces: `AgentConfig` | `create` |
| `invoke(agent_config: AgentConfig, query: str) -> str` | consumes: `AgentConfig` | `invoke` |
| `random_tool(x: int) -> str` | 无 | `none` |

匹配上后自动给 invoke-X 的 schema 注入句柄字段，agent 看 schema 就知道传什么，**根本不需要走到 fallback**。这层解决 JiuwenAgent 问题的真正瓶颈——schema 缺字段。类型驱动：任何 SDK，只要 create 和 invoke 用同一种类型传递句柄，就自动工作。

#### Layer 2 — 事后：catalog fallback 按类型匹配

`_try_catalog_fallback` 改为按 `resource_type` 查询，不再硬编码 `args["agent_id"]`：

```python
# 旧：按参数名取 id
id_arg = catalog_fallback.get("id_arg") or "agent_id"
agent_id = args.get(id_arg) or args.get("agent_id") or args.get("id")

# 新：按 resource_type + 稳定句柄从 catalog 取（需明确 ref；latest(type) 未实现）
resource_type = catalog_fallback["resource_type"]      # e.g. "AgentConfig"
handle_field = catalog_fallback["handle_field"]        # create-X 写入时动态记录
handle_value = args.get(handle_field) or args.get("resource_ref")
entry = catalog.get(resource_type, handle_value)       # 或 find_by_resource_id / find_by_agent_reference
```

fallback payload 不再存 `id_arg`（参数名），而存 `resource_type`（类型）+ `handle_field`（create-X 声明的句柄字段名）。字段名由 create-X 的实际返回动态发现，不由启发式猜。

#### Layer 3 — 发现：ToolSearch 依赖图排序（search_tags←resource_type 未做）

**原设想**：create-X / invoke-X 自动共享 `resource_type` 关键词写入 `search_tags`。

**当前实现**：
- ❌ `generate_search_tags()` **不**注入 `resource_type`；`invoke_existing_agent` tags 仍手写
- ✅ ToolSearch 通过加载 `tool-dependencies.yaml` 的 `priority_routes` + `rank_tools_by_lifecycle` 做生命周期排序
- ✅ 支持 `lifecycle-chain:` 高级 query

因此「create 与 invoke 同搜可见」主要靠依赖图 / 宏路由，而非共享类型 tags。若未来要补 Layer 3 原设想，应改 `search_tags.py`，而不是假定已完成。

### 7.4 与 F-56 的关系

F-56（SOP 资源目录）解决**持久化层**——catalog 怎么存、存哪。本补丁是 F-56 之上的**查询/匹配层**——catalog 怎么查、怎么自动注入。两者正交，组合起来才是完整解：

- F-56 保证 catalog 里有记录
- 类型契约保证任何 SDK 都能把记录和 invoke 工具对上

**JiuwenAgent / `agent_config` 是触发语料，不是设计上限。** 扩展点必须是 `resource_type`（及 F-56 §14 注册表），禁止把本补丁收成「只修 llmagent-invoke」的专用分支。可扩展性契约、统一 `resource_ref`、第二资源种类门禁见 **F-56 §14**。

### 7.5 改动位置（对照代码）

| 文件 | 状态 | 说明 |
|------|------|------|
| `heuristics/lifecycle.py` | ✅ | `derive_resource_type`、类型匹配 `infer_lifecycle_kind`、`inject_resource_ref_schema`、fallback payload 含 `resource_type` + `handle_field` |
| `tool_registry_bridge.py` | ✅ | convert 注入 schema / catalog hooks；写出依赖 yaml；fallback 按 type |
| `resource_handlers.py` / `resource_catalog.py` | ✅ | F-56 注册表与通用 get（见 F-56） |
| `composite_tools/builtin.py` | ⚠️ | `invoke_existing_agent` 存在；tags **仍手写**，未从 `resource_type` 派生 |
| `search_tags.py` | ❌ | **未**按 `resource_type` 派生 tags |
| `tool_search_matching.py` | ✅ | `rank_tools_by_lifecycle` **已接线**（不是 dead code）；排序键来自依赖图 intent group，非直接扫 `resource_type` tag |

### 7.6 兼容性与回退

- 原参数名启发式作为**兜底**保留：当类型信息缺失（return_type 为 None、type_hint 为 None）时，回退到 `*_id` 规则。保证旧 bundle 不破坏。
- `resource_type` 提取失败的 create-X 仍按原逻辑写 catalog，只是不参与类型匹配；invoke-X 仍可走旧的 `id_arg` 路径（如果参数名恰好命中）。
- catalog 记录新增 `resource_type` / `handle_field` 字段，旧记录缺失时按 `agent_id` 兜底读取。

### 7.7 验收补充

在 §4 验收标准基础上追加：

| # | 验收项 | 方法 |
|---|--------|------|
| L1-7 | `llmagent-invoke`（参数名 `agent_config`）被正确判为 `invoke` | `infer_lifecycle_kind` 单测覆盖类型匹配分支 |
| L1-8 | invoke-X 的 schema 自动包含句柄字段 | 优先 `resource_ref`（+ 可选 `resource_type`）；`agent_config_handle` 等派生名仅作兼容别名 |
| L2-5 | catalog 记录含 `resource_type` + `handle_field` | 创建后检查 catalog JSON；`handle_field` 由 create 动态发现，非写死 |
| L2-6 | `_try_catalog_fallback` 按 resource_type 查询成功 | 单测构造类型匹配但参数名非 `*_id` 的场景 |
| L3-4 | ToolSearch 按生命周期排序 / `lifecycle-chain:` | 依赖图路径已测；**不**要求 tags 含 `resource_type`（该设想未实现） |
| E4 | 第二资源种类（非 Agent）经同一类型契约完成 create→catalog→invoke | **可扩展硬门禁**；详见 F-56 §14.6 |

### 7.8 可扩展性（不得做成 Agent 特判）

后续实现与评审必须遵守：

1. **扩展点是 `resource_type`**，不是参数名列表，也不是再复制一个 `invoke-existing-*`。
2. **Layer 1 schema 注入**应对任意 `consumes == produces` 的类型对生效；稳定字段优先用 `resource_ref`（见 F-56 §14.5）。
3. **参数名启发式仅兜底**（§7.6）；新 SDK 不得靠「再加一个特殊参数名」进入主路径。
4. **未在 F-56 注册表登记的种类**不得 silently 走 agent materialize；可描述、不可假执行。
5. 详细注册表、sidecar、验收矩阵与实施优先级以 **F-56 §14** 为准；本文件只约束 convert / schema / fallback 匹配侧。

---

## 附录 A：数据结构与代码索引

### A.1 ToolDependencyGraph 数据结构（已实现）

实现位于 `extensions/sop_converter/dependency/models.py`（字段名：`from_tool` / `to_tool`；YAML 序列化为 `from` / `to`）。

```python
@dataclass
class HiddenStep:
    action: str              # persist_agent_catalog / materialize_on_invoke / invoke_same_runtime
    description: str

@dataclass
class ToolDependency:
    from_tool: str
    to_tool: str
    shared_params: list[str]
    hidden_steps: list[HiddenStep] = field(default_factory=list)
    lifecycle: str = ""

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
```

### A.2 依赖推断引擎（已实现）

```
extensions/sop_converter/dependency/
├── __init__.py
├── models.py            # ToolDependencyGraph 数据模型
├── detector.py          # detect_lifecycle_patterns() 主入口
├── heuristics.py        # 配对启发式规则
├── writer.py            # YAML 写入
└── reader.py            # YAML 读取（运行时消费方用）
```

system prompt 块在 `sop_prompts.py`（非 `dependency/prompts.py`）。

### A.3 与本方案相关的现有代码

| 文件 | 与本方案关系 |
|------|-------------|
| `extensions/sop_converter/sop_prompts.py` | ✅ L3：`domain_agent_sop_body()` / `_lifecycle_prompt_block` |
| `extensions/sop_converter/task_guide.py` | ✅ L3：依赖链行 |
| `extensions/sop_converter/bundle_context.py` | L2 消费上下文 |
| `extensions/sop_converter/search_tags.py` | 仍为 name/description 启发式；**未**从 `resource_type` 派生 tags |
| `clawcodex_ext/agent/tool_authoring/factory.py` | 工具执行 / workflow 宏 |
| `clawcodex_ext/tool_system/tools/tool_search_matching.py` | ✅ `rank_tools_by_lifecycle` |
| `extensions/sop_converter/bundle_venv.py` | 依赖隔离（替代废弃的 BundleWorker 方案） |

---

## 附录 B：Bundle Venv 长驻子进程方案（历史设计，已废弃）

> **状态**: ❌ **已废弃，不要实施**  
> **替代实现**: `extensions/sop_converter/bundle_venv.py` — convert 时准备 bundle venv；运行时 `activate_bundle_venv_imports` / bash 注入 site-packages；SDK wrapper 仍以 `execute_sdk_wrapper_in_process` 为主（辅以 `in_process_bundle_venv_reexec` 防护）。  
> **下文保留原因**: 仅作设计考古，避免重复提出同一方案。

以下 B.1–B.3 为废弃草案摘要，**不代表当前架构**。原详尽伪代码已压缩；完整历史草案见 git 历史。

### B.1 问题背景（历史）

撰写时 in-process wrapper 跑在 clawcodex 主 venv，可能缺 SDK 第三方依赖；wrapper 顶部 `os.execv` 切换 venv 会毁掉 agent runtime。`sop convert` 已建 bundle venv，但当时运行时消费不稳。

### B.2 曾选型（未落地）

曾选型「长驻子进程 + stdin/stdout JSON」（`BundleWorkerPool` / `bundle_worker.py`）。该设计**未落地**，仓库中无对应实现文件。勿实施：

- `clawcodex_ext/.../bundle_worker_pool.py` — 不存在
- `clawcodex_ext/.../bundle_worker.py` — 不存在
- 将 `execute_sdk_wrapper_in_process` 改为 worker pool — **未做**

### B.3 当前替代

依赖隔离请以 `bundle_venv.py` + 现有 in-process / bash handler 为准。

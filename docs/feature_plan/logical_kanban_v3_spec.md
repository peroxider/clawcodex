# 逻辑看板 / Proof-Carrying Logical Kanban v1.0 特性需求规格说明书

> **文档版本**: v1.1 INTEGRATED  
> **整合日期**: 2026-07-04  
> **状态**: 可直接交付开发团队（含模糊输入处理体系）  
> **总章节**: 26章 + 附录  
> **目标读者**: 系统架构师、后端/前端工程师、算法工程师、QA、DevOps  

---

## 1. 概述

### 1.1 产品名称与定位

**正式产品名称**: Proof-Carrying Logical Kanban (简称 **LKB**)

**产品定位**: 一个面向 Agent 的**形式化断言驱动的任务操作系统**。它不是传统 Todo List，也不是普通 Kanban，而是一个要求 Agent 在任务规划和执行中必须携带形式化断言、符号推理结果和验证证明的逻辑看板系统。

**核心公式**:
```
任务状态 = 事实 + 规则 + 断言 + 证明 + 审计记录
```

### 1.2 核心目标（一段话）

构建一个逻辑看板系统，使复杂任务规划、拆解、验证与推进都基于可验证的符号系统完成——Agent 只能提出候选操作（propose），不能直接修改最终状态（commit）；所有状态变更必须通过符号求解器（Datalog/ASP/SMT/定理证明器）验证；自然语言解释必须由形式化中间表示（Canonical IR）生成；所有断言和验证结果必须可追溯、可复现、可审计。

### 1.3 与传统看板的差异（对比表）

| 维度 | 普通看板 | 逻辑看板 (LKB) |
|------|---------|---------------|
| 任务对象 | 标题、描述、状态、负责人 | 任务 + 断言 + 依赖 + 因果 + 证据 + 验证状态 |
| 状态流转 | 人或 Agent 直接拖动 | 必须通过规则验证和 Commit Gate |
| 依赖表达 | 简单 `blocked_by` / `parent-child` | 可形式化表达 `Requires` / `Blocks` / `Causes` / `Supports` / `Contradicts` |
| 推理方式 | 人工判断或模型判断 | Datalog / ASP / SMT / 定理证明器 |
| 用户解释 | 评论或描述 | 由形式表达模板化生成自然语言解释 |
| 错误反馈 | 操作失败或无反馈 | 显示反例、违反规则、修复建议 |
| 审计能力 | 操作历史 | 断言历史、验证历史、证明轨迹、求解器版本、完整复现链 |
| Agent 权限 | 全读写 | Propose-only，Commit 需验证通过 |

---

## 2. 背景与问题定义

### 2.1 当前 Todo/Kanban 工具的局限性

当前主流工具（Trello、Jira、Notion、Linear、GitHub Projects）主要解决：

- 任务记录与分配
- 状态流转（Todo → In Progress → Done）
- 简单依赖关系（blocked_by、parent-child）
- 截止日期与优先级

但这些工具在 Agent 执行复杂任务时存在根本性不足：

### 2.2 Agent 任务规划中的 6 类典型问题

1. **Agent 可能生成看似合理但逻辑上不成立的任务链** — LLM 生成的依赖边可能不存在真实因果效应，仅凭"时间先后"被误认为"因果依赖"。
2. **Agent 可能遗漏前置条件，直接推进后续任务** — 无外部机制校验前置条件是否满足。
3. **Agent 可能在依赖尚未满足时将任务移动到 Doing** — 状态流转仅靠 LLM 自我判断，无符号验证门禁。
4. **Agent 可能用自然语言解释掩盖形式逻辑不一致** — 自然语言描述的"合理性"与形式逻辑的正确性可能严重偏离。
5. **人类只能看到任务状态，却无法看到状态背后的因果链、前提、断言、推理过程与验证结果** — 缺乏可解释性。
6. **当某个假设被推翻时，依赖该假设的任务、结论、计划不会自动失效** — 缺乏 Truth Maintenance 系统。

LKB 针对这 6 类问题，提出"形式化断言 + 符号验证 + 自然语言解释"三位一体的解决方案。

---

## 3. 核心设计原则（7 条原则）

### 原则 1: Agent 只能 Propose，不能直接 Commit
Agent 可以提出任务、断言、计划和状态迁移请求，但不能绕过验证器直接改变任务状态。验证通过是 Commit 的必要条件。

### 原则 2: Canonical Assertion IR 是唯一真源
自然语言断言、符号公式、Datalog、SMT-LIB、ASP 等表达都必须由同一个中间表示（Canonical IR）生成，禁止 Agent 同时自由生成自然语言和形式表达（防止漂移）。

### 原则 3: 自然文本不是事实来源
用户看到的自然语言解释应由形式化 IR 模板化生成。自然语言只承担"人类可读"职责，不承担"真值判定"职责。

### 原则 4: 形式化验证优先于模型判断
LLM 可以负责生成候选计划、候选断言和解释草稿，但最终是否成立由符号系统验证。LLM 是 proposal generator，不是 truth arbiter。

### 原则 5: 任务状态流转必须携带 Proof / Validation Result
任何关键状态变更都必须绑定对应的验证记录（validation_run），无验证记录的 transition 必须被 Commit Gate 拒绝。

### 原则 6: 验证失败必须给出可读反例或修复建议
系统不仅要拒绝非法操作，还要解释原因——显示违反了哪条规则、提供了什么反例、建议如何修复。

### 原则 7: 所有断言和验证结果必须可追溯、可复现、可审计
每次验证记录完整的输入快照 hash、规则集 hash、求解器版本、验证策略版本，确保给定相同输入可复现相同验证结果。

### 原则 8: 模糊性必须显式化处理，不得隐式消解

形式逻辑要求精确输入，但用户输入天然模糊。系统不得在黑盒中猜测用户的真实意图。所有模糊性必须：

- **被符号系统检测并分类** — Datalog 规则匹配为主，覆盖预设模糊模式库（`ambiguity_patterns.dl`），LLM self-critique 仅作 fallback
- **生成多世界验证所有合理解释** — ASP/clingo 多解枚举生成候选世界，每个世界独立走完整验证管线
- **标注假设和置信度** — Z3 约束传播计算置信度下界，假设必须显式声明来源和可信度
- **向用户透明展示模糊点和处理过程** — 看板 UI 模糊性面板展示检测到的模糊点、多世界验证结果、假设来源
- **用户澄清具有最高权威** — 用户澄清覆盖所有默认推断，`confidence → 1.0`，`source → user_clarified`

**核心约束**: LLM 仅用于自然语言→Canonical IR 翻译；模糊性检测、假设管理、置信度传播、澄清触发全部走符号系统。

**形式化保证**:
```text
INV-FUZZY-1: ∀a:Assertion. HasUnresolvedAssumption(a) → MarkConditional(DerivedFrom(a))
INV-FUZZY-2: CommitGateDefault(ambiguous_assertion) = DENY
INV-FUZZY-3: UserClarification(a) → Confidence(a) = 1.0 ∧ Source(a) = user_clarified
INV-FUZZY-4: MultiWorld(a) ∧ (∀w₁,w₂∈Worlds(a). Conclusion(w₁) = Conclusion(w₂)) → Deterministic(a)
INV-FUZZY-5: ∀op∈FuzzyProcessing. AuditLog(op) ≠ ⊥
```

---

## 4. 目标用户与使用场景

### 4.1 Agent 系统开发者

**关注点**:
- 如何约束 Agent 的任务规划行为
- 如何防止 Agent 生成逻辑不一致的计划
- 如何让 Agent 工具调用具备验证门禁
- 如何将任务状态与 proof token 绑定

**使用场景**: 开发需要严格任务规划约束的 Agent 系统（如多 Agent 协作系统、自动化工作流引擎），将 LKB 作为任务规划的验证基础设施。

### 4.2 项目负责人 / 产品经理

**关注点**:
- 为什么某个任务被阻塞（自然语言解释 + 形式化推导链）
- 哪些任务是关键路径
- 哪些假设支撑当前计划
- 当前计划是否存在循环依赖、冲突或未验证条件

**使用场景**: 通过看板 UI 查看任务状态、阻塞原因、假设依赖图，在计划出现逻辑问题时快速定位根因。

### 4.3 工程师 / 研究员

**关注点**:
- 查看形式化断言和 Datalog / SMT-LIB / ASP 表达
- 查看推理结果、反例和证明轨迹
- 调试规则、约束和状态机
- 验证求解器输出正确性

**使用场景**: 调试验证失败的原因、优化规则集、审计验证流程的正确性、研究新的规则模板。

### 4.4 安全关键场景审核人员

适用于机器人控制、生产系统、自动化运维、金融/法律流程等场景。

**关注点**:
- Agent 是否绕过规则
- 状态变更是否可证明
- 每个关键决策是否有证据链
- 是否存在未验证假设或逻辑漏洞

**使用场景**: 审计高风险任务的状态变更历史，验证关键决策的形式化证明，确认不存在未验证假设。

---

## 5. 核心概念模型

### 5.1 Task（任务）

Task 是逻辑看板的基本执行单元。

```yaml
task_id: T-settings-page
title: 实现设置页权限控制
description: "..."
status: Blocked           # 状态机见第10章
owner: agent-frontend
priority: high
created_by: agent
created_at: 2026-07-04T10:00:00Z
updated_at: 2026-07-04T10:00:00Z
version: 1                # 乐观锁版本号（并发控制）
deleted_at: null          # 软删除标记
```

**状态约束**: `status` 必须属于枚举 `{'Draft','Ready','Doing','Blocked','Done','Verified','Invalidated'}`。

### 5.2 Assertion（断言）—— 双存储设计

Assertion 是任务上的逻辑断言。采用**双存储**设计：

- **`nl_assertion`**: 自然语言断言原文，供人类阅读
- **`formal_assertion`**: 受 TPTP 启发的自定义 JSON 格式，可直接喂给外部求解器

**关键约束**: `nl_assertion` 和 `formal_assertion` 必须由同一个 **Canonical IR** 生成，禁止 Agent 分别独立生成两者。

```yaml
assertion_id: A-1024
task_id: T-settings-page          # NULLABLE: 为 NULL 时表示全局规则
kind: prerequisite
status: verified                  # {draft, pending, verified, refuted, stale, invalidated}
canonical_ir: {...}               # Canonical Assertion IR（唯一真源）
nl_assertion: "用户认证模块是设置页权限控制的前置条件。"
formal_assertion:                 # 受TPTP启发的自定义JSON格式
  role: axiom
  quantifier: forall
  vars: [{"name": "T", "type": "Task"}]
  body: {...}
  schema_version: "1.0"
glossary_refs:                    # 谓词词汇表引用（强制对齐机制）
  - predicate: "Requires"
    entry_id: "P-001"
  - predicate: "Done"
    entry_id: "P-004"
provenance:
  generated_by: llm-translator
  model: claude-sonnet-4          # 注意：固定模型版本防止漂移
  translation_confidence: 0.92    # 计算方法见第11章
  source_nl_hash: "sha256:..."
  created_at: 2026-07-04T10:00:00Z
  updated_at: 2026-07-04T10:00:00Z
validation:
  status: verified
  latest_run_id: V-2026-0001
assumption_set: ["H-001"]         # 该断言依赖的假设集合
derived_from: []                  # 若是派生断言，记录来源
valid_until: null                 # TMS 失效追踪
invalidated_reason: null
evidence: ["E-001"]
```

**task_id 可为 NULL 的设计 rationale**: 全局规则（如状态机公理、排他性约束）不关联特定任务。例如 `∀t:Task. Doing(t) -> Ready(t) ∧ ¬Blocked(t)` 是一条全局规则，其 `task_id` 为 NULL。

### 5.3 Rule（规则）—— 修正后的形式化定义

Rule 是全局或局部的逻辑规则，由 Canonical IR 编译到各求解器目标。

**语法修正**（修复原文档 L1/L2/L3/L5 问题）:

```text
# R-001: 前置条件未满足且b自身未完成/未在进行中，则b被阻塞
∀a,b:Task. Requires(a,b) ∧ ¬Done(a) ∧ ¬Done(b) ∧ ¬Doing(b) -> Blocked(b)

# R-002: 被阻塞任务不能进入 Doing
∀t:Task. Blocked(t) -> ¬CanMoveTo(t, Doing)

# R-003: Doing 任务必须 Ready 且不被阻塞
∀t:Task. Doing(t) -> Ready(t) ∧ ¬Blocked(t)

# R-004: 迁移许可规则——何时允许进入 Doing
∀t:Task. Ready(t) ∧ ¬Blocked(t) ∧ ¬(∃c:Assertion. Contradicts(c,t) ∧ Active(c)) 
  -> Permitted(t, Ready, Doing)

# R-005: Done 任务必须有验收证明
∀t:Task. Done(t) -> HasAcceptanceProof(t)

# R-006: 存在冲突的活跃断言互相使对方失效
∀a,b:Assertion. Contradicts(a,b) ∧ Active(a) ∧ Active(b) -> Invalid(a) ∧ Invalid(b)

# 状态机公理（排他性约束）
∀t:Task. Blocked(t) -> ¬(Ready(t) ∨ Doing(t) ∨ Done(t))
∀t:Task. Doing(t)  -> ¬(Ready(t) ∨ Blocked(t) ∨ Done(t))
∀t:Task. Done(t)   -> ¬(Ready(t) ∨ Doing(t) ∨ Blocked(t))
∀t:Task. Ready(t)  -> ¬(Blocked(t) ∨ Doing(t) ∨ Done(t))
```

**谓词完整定义表**（修复原文档 Active/Invalid/AcceptanceProof 未定义问题）:

| 谓词 | 签名 | 定义 |
|------|------|------|
| `Task` | `Entity -> Bool` | t 是一个任务实体 |
| `Status` | `Task × StatusEnum -> Bool` | t 当前处于状态 s |
| `Todo` | `Task -> Bool` | t 处于 Todo 状态 |
| `Ready` | `Task -> Bool` | t 处于 Ready 状态 |
| `Doing` | `Task -> Bool` | t 处于 Doing 状态 |
| `Blocked` | `Task -> Bool` | t 被推导为阻塞状态（推导谓词，非独立状态） |
| `Done` | `Task -> Bool` | t 处于 Done 状态 |
| `Verified` | `Task -> Bool` | t 已通过形式化验证 |
| `Requires` | `Task × Task -> Bool` | a 是 b 的前置条件 |
| `Blocks` | `Task × Task -> Bool` | a 阻塞 b |
| `Enables` | `Task × Task -> Bool` | a 的完成使 b 就绪 |
| `Causes` | `Task × Task -> Bool` | a 的完成因果影响 b |
| `Supports` | `Evidence × Assertion -> Bool` | 证据 e 支持断言 a |
| `Contradicts` | `Assertion × Assertion -> Bool` | 断言 a 与断言 b 互相矛盾 |
| `Assumes` | `Assertion × Hypothesis -> Bool` | 断言 a 依赖假设 h |
| `DerivedFrom` | `Assertion × Assertion -> Bool` | 断言 a 是从断言 b 派生的 |
| `CanMoveTo` | `Task × StatusEnum -> Bool` | t 可以迁移到目标状态 |
| `Permitted` | `Task × StatusEnum × StatusEnum -> Bool` | t 从状态 A 到状态 B 的迁移被许可 |
| `HasAcceptanceProof` | `Task -> Bool` | t 拥有验收证明 |
| `Active` | `Assertion -> Bool` | 断言 a 当前处于 {verified, pending} 状态 |
| `Invalid` | `Assertion -> Bool` | 断言 a 已被标记为无效 |
| `NoActiveContradiction` | `Task -> Bool` | t 不存在活跃冲突断言 |
| `AllRequiredAssertionsVerified` | `Task -> Bool` | t 的所有必需断言已验证通过 |
| `Ambiguous` | `Assertion × AmbiguityKind -> Bool` | 断言 a 具有某类模糊性 |
| `HasWorld` | `Assertion × WorldId -> Bool` | 断言 a 包含可能世界 w |
| `AssumptionField` | `Assertion × Field × Value × Confidence -> Bool` | 断言 a 在 field 上假设值为 value，置信度为 confidence |
| `NeedsClarification` | `Assertion -> Bool` | 断言 a 需要用户澄清 |

### 5.4 Fact（事实）

Fact 是当前被系统接受的原子命题，构成验证的输入基础。

```text
Fact 示例:
  Task(T_auth)
  Task(T_settings)
  Requires(T_auth, T_settings)
  ¬Done(T_auth)
  Done(T_api_v2)
```

Fact 的来源：
- 任务创建时自动生成的结构性事实（Task(T), Status(T, Ready) 等）
- Agent 提交的 `fact` 类型断言
- 外部系统同步的状态事实
- 求解器验证通过后生成的派生事实

### 5.5 Derived Fact（派生事实）

Derived Fact 是由规则和事实通过逻辑推导得出的事实。

```text
Derived Fact 示例:
  Blocked(T_settings)                    # 由 R-001 推导
  ¬CanMoveTo(T_settings, Doing)          # 由 R-002 推导
  NeedsRecheck(T_settings)               # 由假设失效传播推导
```

每条 Derived Fact 必须记录推导链（derivation chain），用于 proof trace 展示和 TMS 失效传播。

### 5.6 Validation Run（验证运行）

Validation Run 是某次验证的完整执行记录，是"可复现性"的核心载体。

```yaml
validation_run_id: V-2026-0001
assertion_id: A-1024
transition_id: TR-009                  # 若此验证关联某个 transition

# 输入描述（确保可复现）
input_facts_hash: "sha256:abc123..."    # 验证时使用的 facts snapshot 的 hash
ruleset_hash: "sha256:def456..."        # 当前活跃规则集的 hash
canonical_ir_hash: "sha256:ghi789..."   # 被验证断言的 canonical_ir hash
validation_policy_version: "1.2.0"      # 验证策略版本

# 求解器执行信息
solver: z3
solver_version: "4.16.0"
solver_syntax: smtlib2
timeout_seconds: 30
duration_ms: 245

# 结果
result: fail                           # {pass, fail, unknown, timeout, error, stale}

# 诊断信息
diagnostics:
  violated_rule: "R-001"
  violated_predicate: null
counterexample:                         # 求解器返回的反例
  model:
    doing(T_settings): true
    blocked(T_settings): true
unsat_core: null
proof_trace: null
solver_stderr: ""                       # 求解器标准错误输出（用于调试）

# 审计
created_at: 2026-07-04T10:05:00Z
requested_by: agent-frontend
```

### 5.7 Transition（状态迁移）

Transition 是任务状态迁移请求，采用 propose → validate → commit 三段式流程。

```yaml
transition_id: TR-009
task_id: T_settings
from_status: Ready
to_status: Doing
requested_by: agent-frontend
reason_assertions: ["A-1024", "A-1025"]  # 支撑此迁移的断言

# 验证绑定（通过关联表实现，非数组）
# transition_validations 关联表记录绑定的 validation_run

status: denied                         # {pending, validated, denied, committed, revoked}

# Commit Gate 检查结果
commit_gate_check:
  ready_check: pass
  blocked_check: fail                   # Blocked(T_settings) = true
  contradiction_check: pass
  assertion_check: pass
  validation_hash_check: pass
  
failure_reason: "blocked_task_cannot_enter_doing"
human_message:
  zh: "任务 T_settings 不能进入 Doing，因为它仍被 T_auth 阻塞。"
  en: "Task T_settings cannot enter Doing because it is blocked by T_auth."

repair_suggestions:
  - action: "complete_prerequisite"
    target: "T_auth"
    description_zh: "请先完成 T_auth。"
  - action: "remove_dependency"
    assertion_id: "A-003"
    description_zh: "或删除 Requires(T_auth, T_settings) 断言。"
  - action: "submit_proof"
    description_zh: "或提交新的证明说明该依赖不再成立。"

created_at: 2026-07-04T10:00:00Z
committed_at: null
committed_by: null
```

### 5.8 MultiWorldAssertion（多世界断言）

MultiWorldAssertion 是针对模糊输入生成的包含多个可能世界的断言结构。当模糊性检测器识别到语义模糊时，翻译器不输出单一 `formal_assertion`，而是输出一组由 ASP 枚举生成的可能世界。

**形式化定义**:
```text
给定自然语言断言 NL，翻译器生成一组可能世界：

Worlds(NL) = { W_1, W_2, ..., W_n }

其中每个 W_i = {
  world_id: WorldId,
  interpretation: Canonical_IR_i,
  confidence: float ∈ [0, 1],
  ambiguities_resolved: dict,
  assumptions: list of Assumption,
  verification_result: pending
}

总置信度归一化: Σ confidence(W_i) = 1.0
```

**JSON Schema**:
```json
{
  "assertion_id": "A-042",
  "kind": "multi_world_assertion",
  "nl_assertion": "离家50米的洗车店",
  "worlds": [
    {
      "world_id": "W_1",
      "confidence": 0.6,
      "interpretation": {
        "quantifier": "exists",
        "body": {
          "op": "and",
          "args": [
            {"pred": "Shop", "args": ["S"], "type": "car_wash"},
            {"pred": "WalkingDistance", "args": ["home", "S", 50]}
          ]
        }
      },
      "assumptions": [
        {"field": "distance_type", "value": "walking", "confidence": 0.6, "id": "H-001"}
      ]
    },
    {
      "world_id": "W_2",
      "confidence": 0.4,
      "interpretation": {
        "quantifier": "exists",
        "body": {
          "op": "and",
          "args": [
            {"pred": "Shop", "args": ["S"], "type": "car_wash"},
            {"pred": "EuclideanDistance", "args": ["home", "S", 50]}
          ]
        }
      },
      "assumptions": [
        {"field": "distance_type", "value": "straight_line", "confidence": 0.4, "id": "H-002"}
      ]
    }
  ],
  "ambiguity_report": {
    "detected_ambiguities": [
      {
        "phrase": "50米",
        "kind": "semantic_vagueness",
        "severity": "major",
        "resolved": false
      }
    ],
    "needs_clarification": true
  }
}
```

### 5.9 AmbiguityReport（模糊性报告）

AmbiguityReport 由 Datalog 模糊性检测引擎输出，记录自然语言断言中检测到的所有模糊点。

**形式化定义**:
```text
AmbiguityReport = {
  assertion_id: AssertionId,
  detected_ambiguities: list of Ambiguity,
  severity: {critical, major, minor, negligible},
  needs_clarification: Bool,
  detection_method: {datalog_rules, asp_enumeration, llm_fallback},
  processing_time_ms: Int
}

Ambiguity = {
  phrase: String,
  kind: {semantic_vagueness, informational_incompleteness, context_dependency, metaphorical},
  severity: {critical, major, minor, negligible},
  candidate_interpretations: list of {meaning: String, confidence: Float},
  resolved: Bool,
  resolution_method: {default_assumption, user_clarification, multi_world}
}
```

**Datalog 检测触发模式**:
```prolog
// ambiguity_patterns.dl — 模糊性检测规则库

// 语义模糊：距离表述
semantic_vagueness(A, "distance_type") :- 
  assertion(A, Text),
  regex_match(Text, "距离.*\\d+.*米").

// 语义模糊：服务主体
semantic_vagueness(A, "service_mode") :- 
  assertion(A, Text),
  regex_match(Text, "洗.*车"),
  not contains(Text, "自助"),
  not contains(Text, "代洗").

// 信息不完备：缺少位置
informational_incompleteness(A, "current_location") :- 
  assertion(A, Text),
  contains(Text, "去"),
  not contains(Text, "从").

// 严重度评级（Datalog 规则）
severity(A, "critical") :- semantic_vagueness(A, "service_mode").
severity(A, "major") :- semantic_vagueness(A, "distance_type").
severity(A, "minor") :- informational_incompleteness(A, _).
```

### 5.10 Assumption（假设）增强版

假设是系统中**暂时假定为真、可被后续推翻**的条件。每个假设必须携带置信度和来源，以便 Truth Maintenance 系统追踪和失效传播。

**形式化定义**:
```yaml
assumption:
  assumption_id: "H-001"
  assertion_id: "A-042"          # 所属断言
  field: "distance_type"         # 假设的字段
  assumed_value: "walking"       # 假设的值
  confidence: 0.6                # 置信度 [0.0, 1.0]
  source: "default_kb"           # 来源: user_input | default_kb | inferred | user_clarified
  source_ref: "default_assumptions.yaml#distance_unspecified"  # 具体规则引用
  needs_clarification: true      # 是否需要用户澄清
  clarification_prompt: "您说的50米是指直线距离还是步行距离？"
  
  # 生命周期
  created_at: "2026-07-04T10:00:00Z"
  clarified_at: null             # 用户澄清后填充
  invalidated_at: null           # 假设被推翻后填充
  invalidated_reason: null
```

**来源类型与置信度策略**:

| 来源 | 说明 | 初始置信度 | 可否自动澄清 |
|------|------|-----------|------------|
| `user_input` | 用户直接提供 | 1.0 | N/A |
| `default_kb` | 默认值知识库 | 按规则定义 | 是 |
| `inferred` | 上下文推断 | 0.5-0.7 | 是 |
| `user_clarified` | 用户确认后 | 1.0 | N/A |
| `datalog_derived` | Datalog 推导 | 1.0 | N/A |

---

## 6. 断言体系设计

### 6.1 AssertionKind（断言类型表）

| 类型 | 含义 | 示例 | 求解器推荐 |
|------|------|------|-----------|
| `prerequisite` | 前置条件依赖 | `Requires(T_auth, T_settings)` | Datalog + Z3 |
| `blocker` | 阻塞关系 | `Blocks(T_api, T_ui)` | Datalog + Z3 |
| `causal` | 因果关系（需因果层验证） | `Causes(T_schema, T_backend_ready)` | 因果服务 + ASP |
| `evidence` | 证据支持 | `Supports(E_doc, A_requires_auth)` | 元数据验证 |
| `contradiction` | 冲突关系 | `Contradicts(A1, A2)` | ASP + Z3 |
| `invariant` | 全局不变量 | `Doing(T) -> ¬Blocked(T)` | Z3 + Vampire |
| `transition_rule` | 状态迁移规则 | `Permitted(t, Ready, Doing) -> ...` | Z3 + Datalog |
| `plan_step` | 计划步骤 | `Step(1, Finish(T_auth))` | PDDL + ASP |
| `acceptance_rule` | 验收条件 | `Done(T) -> HasAcceptanceProof(T)` | Z3 + Vampire |
| `assumption` | 暂时假设 | `Assume(H_network_available)` | 元数据追踪 |
| `derived` | 派生结论 | `Derived(Blocked(T_settings))` | Datalog + ASP |
| `fact` | 原子事实 | `Task(T_auth)` | 语法检查 |
| `conditional_assertion` | 条件断言（依赖假设） | `If(H_walking_distance, CommuteTime < 10min)` | Datalog + Z3 |
| `multi_world_assertion` | 多世界断言（模糊输入） | `Worlds(NL) = {W_1, W_2}` | ASP 枚举 + Z3 |
| `assumption_with_confidence` | 带置信度的假设 | `Assumes(A, H, confidence=0.6)` | Datalog + TMS |

### 6.2 基础谓词（修正后的完整定义，包含排他性约束）

**类型定义**:
```text
sort Task       # 任务实体
sort Assertion  # 断言实体
sort Evidence   # 证据实体
sort Hypothesis # 假设实体
sort StatusEnum = {Todo, Ready, Doing, Blocked, Done, Verified, Invalidated}
```

**状态谓词与排他性约束**（修正原文档 L2 问题）:
```text
# 状态谓词定义（每个任务恰好处于一个状态）
predicate Todo      : Task -> Bool
predicate Ready     : Task -> Bool
predicate Doing     : Task -> Bool
predicate Blocked   : Task -> Bool    # 推导谓词：存在未完成前置条件
predicate Done      : Task -> Bool
predicate Verified  : Task -> Bool

# 排他性公理（每个任务恰好处于一个状态）
Axiom EXCL-1: ∀t:Task. Blocked(t) -> ¬Ready(t) ∧ ¬Doing(t) ∧ ¬Done(t)
Axiom EXCL-2: ∀t:Task. Doing(t)  -> ¬Ready(t) ∧ ¬Blocked(t) ∧ ¬Done(t)
Axiom EXCL-3: ∀t:Task. Done(t)   -> ¬Ready(t) ∧ ¬Doing(t) ∧ ¬Blocked(t)
Axiom EXCL-4: ∀t:Task. Ready(t)  -> ¬Blocked(t) ∧ ¬Doing(t) ∧ ¬Done(t)

# 完整性公理（每个任务至少处于一个状态）
Axiom COMP-1: ∀t:Task. Todo(t) ∨ Ready(t) ∨ Doing(t) ∨ Blocked(t) ∨ Done(t)
```

**关系谓词**:
```text
predicate Requires        : Task × Task -> Bool
predicate Blocks          : Task × Task -> Bool
predicate Enables         : Task × Task -> Bool
predicate Causes          : Task × Task -> Bool
predicate Supports        : Evidence × Assertion -> Bool
predicate Contradicts     : Assertion × Assertion -> Bool
predicate Assumes         : Assertion × Hypothesis -> Bool
predicate DerivedFrom     : Assertion × Assertion -> Bool
```

**状态迁移谓词**（统一为二元形式，修正原文档 L3 问题）:
```text
# CanMoveTo(t, s): 任务 t 可以迁移到目标状态 s（隐含从当前状态迁移）
predicate CanMoveTo : Task × StatusEnum -> Bool

# Permitted(t, from, to): 从 from 到 to 的迁移被许可
predicate Permitted : Task × StatusEnum × StatusEnum -> Bool
```

**断言状态谓词**（修正原文档 L5 问题）:
```text
# Active(a): 断言 a 处于活跃状态（verified 或 pending）
predicate Active : Assertion -> Bool
Active(a) <-> Assertion(a) ∧ status(a) ∈ {verified, pending}

# Invalid(a): 断言 a 已被标记为无效
predicate Invalid : Assertion -> Bool
Invalid(a) <-> status(a) = invalidated

# Stale(a): 断言 a 因假设失效或输入变化需要重新验证
predicate Stale : Assertion -> Bool
Stale(a) <-> status(a) = stale
```

### 6.3 常用规则模板（修正后的形式化正确版本）

#### RT-001: 前置条件未满足则阻塞（修正版）
```text
∀a,b:Task. Requires(a,b) ∧ ¬Done(a) ∧ ¬Done(b) ∧ ¬Doing(b) -> Blocked(b)
```
**Rationale**: 添加了 `¬Done(b) ∧ ¬Doing(b)` 前提，防止已完成或进行中的任务被推导为 Blocked（修正原文档 L1 问题）。

**自然语言模板**: "任务 {b} 依赖任务 {a}，而 {a} 尚未完成，且 {b} 自身也未完成或进行中，因此 {b} 被阻塞。"

#### RT-002: 被阻塞任务不能进入 Doing
```text
∀t:Task. Blocked(t) -> ¬CanMoveTo(t, Doing)
```
**自然语言模板**: "任务 {t} 当前被阻塞，因此不能进入 Doing 状态。"

#### RT-003: Doing 任务必须 Ready 且不被阻塞
```text
∀t:Task. Doing(t) -> Ready(t) ∧ ¬Blocked(t)
```
**自然语言模板**: "任务 {t} 处于 Doing 状态，因此它必须是 Ready 的且未被阻塞。"

#### RT-004: Ready 任务可以迁移到 Doing（当满足条件时）
```text
∀t:Task. Ready(t) ∧ ¬Blocked(t) ∧ NoActiveContradiction(t) 
  ∧ AllRequiredAssertionsVerified(t) -> CanMoveTo(t, Doing)
```
**自然语言模板**: "任务 {t} 已就绪、未被阻塞、无活跃冲突、所有必需断言已验证，因此允许迁移到 Doing。"

#### RT-005: Done 任务必须有验收证明
```text
∀t:Task. Done(t) -> HasAcceptanceProof(t)
```
**自然语言模板**: "任务 {t} 已完成，因此必须存在验收证明。"

**Datalog 编译**（存在量词在结论中无法直接表达，采用 witness 提取模式）:
```prolog
violation(t) :- done(t), not has_acceptance_proof(t).
```

#### RT-006: 存在冲突的活跃断言互相使对方失效
```text
∀a,b:Assertion. Contradicts(a,b) ∧ Active(a) ∧ Active(b) -> Invalid(a) ∧ Invalid(b)
```
**Rationale**: Active 和 Invalid 谓词已在 6.2 节定义（修正原文档 L5 问题）。

**自然语言模板**: "断言 {a} 与断言 {b} 互相冲突，且两者都处于活跃状态，因此两者都被标记为无效。"

#### RT-007: 假设失效传播
```text
∀a:Assertion. ∃h:Hypothesis. Assumes(a,h) ∧ Invalidated(h) -> Stale(a)
```
**自然语言模板**: "断言 {a} 依赖假设 {h}，而假设 {h} 已被推翻，因此 {a} 被标记为需要重新验证。"

### 6.4 符号映射规范

#### 6.4.1 逻辑符号的精确定义

| 符号 | Unicode | LKB-DSL 语法 | 语义定义 | TPTP 映射 |
|------|---------|-------------|---------|----------|
| 全称量词 | `∀` | `forall` / `∀` | "对于所有..." | `!` |
| 存在量词 | `∃` | `exists` / `∃` | "存在至少一个..." | `?` |
| 否定 | `¬` | `not` / `¬` | 逻辑非 | `~` |
| 合取 | `∧` | `and` / `∧` | 逻辑与 | `&` |
| 析取 | `∨` | `or` / `∨` | 逻辑或 | `\|` |
| 蕴含 | `→` | `implies` / `->` | 如果...那么... | `=>` |
| 等价 | `↔` | `iff` / `<->` | 当且仅当 | `<=>` |
| 因为 | `∵` | `because` / `∵` | 前提/公理（近似映射） | `role:axiom` |
| 所以 | `∴` | `therefore` / `∴` | 待证结论（近似映射） | `role:conjecture` |

#### 6.4.2 TPTP 映射详细说明

**标准逻辑符号映射**（全部正确，与 TPTP v9.2.1 规范一致）:
```
∀  →  !       (全称量词，TPTP FOF:  ![X] : p(X))
∃  →  ?       (存在量词，TPTF FOF:  ?[X] : p(X))
¬  →  ~       (否定，TPTP: ~p)
∧  →  &       (合取，TPTP: p & q)
∨  →  |       (析取，TPTP: p | q)
→  →  =>      (蕴含，TPTP: p => q)
↔  →  <=>     (等价，TPTP: p <=> q)
```

**∵ / ∴ 的近似映射说明**（修正原文档的过度简化问题）:

> **重要**: ∵ → `role:axiom` 和 ∴ → `role:conjecture` 是**近似映射**，而非严格等价：
>
> 1. TPTP 中的 `axiom` 是"被假定为真的公式"（declarative），不带有因果关系的暗示
> 2. TPTP 中的 `conjecture` 是"待证的目标命题"——在自动定理证明过程中会被**否定**后加入子句集（即证明 `axioms ∧ ¬conjecture` 不可满足）。这与口语"所以"（表示已推导的结论）有本质区别
> 3. 更准确的映射：
>    - ∵（前提陈述）→ `role:axiom` 或 `role:assumption`（如果条件性更强）
>    - ∴（推导结论）→ `role:conjecture`（在证明语境中）或 `role:lemma`（如果是中间结论）

**TPTP 公式示例**:
```tptp
% RT-001 的前置条件阻塞规则（TPTP FOF 格式）
fof(rt001, axiom, (
    ! [A,B] :
      ( ( requires(A,B) & ~ done(A) & ~ done(B) & ~ doing(B) )
        => blocked(B) )
)).

% RT-003 的 Doing 约束（TPTP FOF 格式）
fof(rt003, axiom, (
    ! [T] :
      ( doing(T) => ( ready(T) & ~ blocked(T) ) )
)).
```

#### 6.4.3 formal_assertion JSON 格式规范

`formal_assertion` 是**受 TPTP 启发的自定义 JSON 格式**，不是直接兼容 TPTP/JSON-LD-Logic。设计 rationale：TPTP 是纯文本格式，JSON-LD-Logic（jsfol）采用 Lisp 风格的 s-expression 列表表示，两者都不直接适合作为数据库字段的存储格式。本格式在语义上与 TPTP 对齐，但采用嵌套对象树的 JSON 结构。

```json
{
  "schema_version": "1.0",
  "role": "axiom",
  "quantifier": "forall",
  "vars": [
    {"name": "a", "type": "Task"},
    {"name": "b", "type": "Task"}
  ],
  "body": {
    "op": "implies",
    "args": [
      {
        "op": "and",
        "args": [
          {"pred": "Requires", "args": ["a", "b"]},
          {"op": "not", "arg": {"pred": "Done", "args": ["a"]}},
          {"op": "not", "arg": {"pred": "Done", "args": ["b"]}},
          {"op": "not", "arg": {"pred": "Doing", "args": ["b"]}}
        ]
      },
      {"pred": "Blocked", "args": ["b"]}
    ]
  },
  "glossary_refs": {
    "Requires": "P-001",
    "Done": "P-004",
    "Doing": "P-005",
    "Blocked": "P-006"
  },
  "provenance": {
    "generated_by": "llm-translator",
    "model": "claude-sonnet-4",
    "translation_confidence": 0.92,
    "source_nl_hash": "sha256:abc..."
  }
}
```

---

## 7. 双轨表达系统

### 7.1 设计目标

同一个 Assertion 必须同时服务两类对象：

1. **人类用户**: 需要自然语言解释，例如"因为 A 依赖 B 且 B 未完成，所以 A 被阻塞"。
2. **外部验证器**: 需要形式化表达，例如 `Requires(B,A) ∧ ¬Done(B) -> Blocked(A)`。

**核心原则**: 自然语言和形式化表达必须从同一个 Canonical IR 生成，确保两者语义一致。

### 7.2 禁止的设计

**严格禁止**以下设计（会导致自然语言和形式表达不一致）:

```yaml
# 错误设计：Agent 分别独立生成 natural_text 和 formal_text
assertion:
  natural_text: "因为登录模块没做完，所以设置页不能开始。"
  formal_text: "Requires(T_user, T_settings)"   # 可能语义不一致！
```

### 7.3 Canonical Assertion IR（分 Tier 设计）

Canonical IR 是系统的**唯一真源**。基于分析结论，将目标编译格式分为三个 Tier：

```
Canonical IR（唯一真源）
    │
    ├── Tier 1: 语义等价编译（MVP 阶段）
    │     ├── Datalog（依赖传播、阻塞推导）
    │     └── SMT-LIB 2 / Z3（不变量验证、反例生成）
    │
    ├── Tier 2: 近似编译（V1-V2 阶段）
    │     ├── ASP / clingo（多解枚举、冲突处理）
    │     └── Lean（协议级形式验证、构造性证明）
    │
    └── Tier 3: 结构化转换（V2+ 阶段）
          ├── PDDL（执行计划验证）
          └── Argdown（论证图可视化）
```

**分 Tier rationale**: Datalog 和 SMT-LIB 的表达能力和 IR 的表达力最接近，可实现语义等价编译。ASP 的稳定模型语义与 IR 的一阶逻辑存在语义差距（否定即失败 vs 经典否定），Lean 是高阶依赖类型系统，两者为近似编译。PDDL 是动作+状态转移系统，Argdown 是论证图结构，两者需要结构化转换而非逻辑编译。

**不可编译处理策略**: 当 IR 中的某个子表达式无法编译到目标 Tier 时，编译器应：
1. 记录 `unsupported_construct` 警告
2. 跳过不可编译部分，继续编译其余部分
3. 返回 `partial_compile` 状态，标记哪些部分被省略
4. 在验证报告中注明"部分验证"（而非"验证通过"）

**Canonical IR 的 AST 结构**:
```yaml
# 示例: RT-001 的 Canonical IR
canonical_ir:
  version: "1.0"
  op: forall
  vars:
    - name: a
      type: Task
    - name: b
      type: Task
  body:
    op: implies
    left:
      op: and
      args:
        - op: predicate
          name: Requires
          args: ["a", "b"]
        - op: not
          arg:
            op: predicate
            name: Done
            args: ["a"]
        - op: not
          arg:
            op: predicate
            name: Done
            args: ["b"]
        - op: not
          arg:
            op: predicate
            name: Doing
            args: ["b"]
    right:
      op: predicate
      name: Blocked
      args: ["b"]
```

### 7.4 自然语言 Renderer

自然语言 Renderer 从 Canonical IR 生成人类可读的解释。采用**模板化渲染**，非 LLM 自由生成：

```yaml
# 模板注册表
templates:
  zh:
    forall: "对于所有{type} {var}，"
    implies: "如果 {left}，那么 {right}。"
    and: "{args[0]}且{args[1]}"
    not: "{arg}不成立"
    predicate_Requires: "{args[0]}是{args[1]}的前置条件"
    predicate_Done: "{args[0]}已完成"
    predicate_Doing: "{args[0]}正在进行中"
    predicate_Blocked: "{args[0]}被阻塞"
  en:
    forall: "For every {type} {var}, "
    implies: "if {left}, then {right}."
    # ...
```

**渲染示例**:
```
IR: ∀a,b:Task. Requires(a,b) ∧ ¬Done(a) ∧ ¬Done(b) ∧ ¬Doing(b) -> Blocked(b)
ZH: 对于所有任务 a 和任务 b，如果 a 是 b 的前置条件且 a 尚未完成且 b 尚未完成且 b 尚未在进行中，那么 b 被阻塞。
EN: For every task a and task b, if a is a prerequisite of b and a is not done and b is not done and b is not in progress, then b is blocked.
```

### 7.5 形式化编译目标

#### 7.5.1 Datalog 编译（Tier 1，MVP）

```prolog
% RT-001 编译为 Datalog
.decl task(t:symbol)
.decl requires(a:symbol, b:symbol)
.decl done(t:symbol)
.decl doing(t:symbol)
.decl blocked(t:symbol)

blocked(b) :- requires(a,b), !done(a), !done(b), !doing(b).
```

#### 7.5.2 SMT-LIB 2 编译（Tier 1，MVP）

```smtlib
; RT-003 编译为 SMT-LIB 2
(declare-sort Task 0)
(declare-fun Doing (Task) Bool)
(declare-fun Ready (Task) Bool)
(declare-fun Blocked (Task) Bool)

(assert
  (forall ((t Task))
    (=> (Doing t)
        (and (Ready t) (not (Blocked t))))))

(check-sat)
```

#### 7.5.3 ASP / clingo 编译（Tier 2，V1）

```prolog
% RT-001 编译为 ASP/clingo
requires(t_auth, t_settings).
done(t_auth) :- completed(t_auth).

blocked(B) :- requires(A,B), not done(A), not done(B), not doing(B).

% 查询
#show blocked/1.
```

#### 7.5.4 Lean 编译（Tier 2，V2）

```lean
-- RT-003 编译为 Lean 4
inductive Status
| Todo | Ready | Doing | Blocked | Done

structure Task where
  id : String
  status : Status

-- 状态公理：Doing 蕴含 Ready 且非 Blocked
axiom doing_implies_ready_not_blocked :
  ∀ (t : Task), t.status = Status.Doing →
    t.status = Status.Ready ∧ t.status ≠ Status.Blocked
```

---

## 8. LKB-DSL 设计

### 8.1 DSL 目标与语法

LKB-DSL（Logical Kanban Board Domain Specific Language）是面向 Agent 和人类工程师的领域专用语言。

**设计目标**:
- 对 Agent 足够友好（结构化、可解析）
- 对人类工程师足够可读
- 能被 parser 解析为 AST
- 能编译到 Tier 1/2/3 目标格式
- 能生成自然语言解释

**语法规范**:
```ebnf
Program     := Decl*
Decl        := RuleDecl | FactDecl | DeriveDecl
RuleDecl    := "rule" ID ":" QuantifiedFormula
FactDecl    := "fact" ID ":" Formula
DeriveDecl  := "derive" ID ":" Premise+ Conclusion
QuantifiedFormula := "∀" VarDecl+ "." Formula
                  |  "∃" VarDecl+ "." Formula
VarDecl     := ID ":" Type
Formula     := Predicate | Not | And | Or | Implies | Iff
Predicate   := ID "(" ArgList ")"
Not         := "¬" Formula
And         := Formula "∧" Formula
Or          := Formula "∨" Formula
Implies     := Formula "→" Formula
Iff         := Formula "↔" Formula
Premise     := "∵" Formula
Conclusion  := "∴" Formula
Type        := "Task" | "Assertion" | "Evidence" | "Hypothesis" | ID
```

### 8.2 AST 规范

LKB-DSL 解析后的 AST 采用统一的 JSON 结构：

```json
{
  "version": "1.0",
  "declarations": [
    {
      "kind": "rule",
      "id": "R-001",
      "formula": {
        "op": "forall",
        "vars": [
          {"name": "a", "type": "Task"},
          {"name": "b", "type": "Task"}
        ],
        "body": {
          "op": "implies",
          "left": {
            "op": "and",
            "args": [
              {"op": "predicate", "name": "Requires", "args": ["a", "b"]},
              {"op": "not", "arg": {"op": "predicate", "name": "Done", "args": ["a"]}},
              {"op": "not", "arg": {"op": "predicate", "name": "Done", "args": ["b"]}},
              {"op": "not", "arg": {"op": "predicate", "name": "Doing", "args": ["b"]}}
            ]
          },
          "right": {"op": "predicate", "name": "Blocked", "args": ["b"]}
        }
      }
    }
  ]
}
```

### 8.3 MVP 能力范围

MVP 阶段 LKB-DSL 支持：

| 特性 | 语法 | 状态 |
|------|------|------|
| 全称量词 | `∀` / `forall` | ✅ MVP |
| 存在量词 | `∃` / `exists` | ✅ MVP |
| 否定 | `¬` / `not` | ✅ MVP |
| 合取 | `∧` / `and` | ✅ MVP |
| 析取 | `∨` / `or` | ✅ MVP |
| 蕴含 | `→` / `implies` | ✅ MVP |
| 等价 | `↔` / `iff` | ✅ MVP |
| 因为 | `∵` / `because` | ✅ MVP |
| 所以 | `∴` / `therefore` | ✅ MVP |
| 谓词调用 | `Pred(A,B)` | ✅ MVP |
| 类型变量 | `t: Task` | ✅ MVP |
| 规则声明 | `rule R-001: ...` | ✅ MVP |
| 事实声明 | `fact F-001: ...` | ✅ MVP |
| 派生声明 | `derive D-001: ...` | ✅ MVP |

**MVP 阶段不支持**（需人工 review 或报错）:
- 嵌套量词超过 2 层
- 自定义排序（sort）定义
- 算术表达式（需 clingcon/Z3 扩展）

### 8.4 后续扩展路线

| 版本 | 新增特性 | 求解器需求 | 预计阶段 |
|------|---------|-----------|---------|
| v1.1 | 时序操作符（`○` next, `□` always, `◇` eventually） | TLA+ / pltl | V2 |
| v1.2 | 概率标注（`P(φ) >= 0.9`） | Z3 + 概率扩展 | V3 |
| v1.3 | 可废止规则（`φ ~> ψ`） | ASP（defeasible ASP） | V3 |
| v2.0 | 模态操作符（`□` necessary, `◇` possible） | Modal logic solver | V4 |
| v2.1 | 论证攻击/支持关系 | Argdown + 抽象论证框架 | V4 |

**版本兼容性策略**: 每个 DSL 版本定义独立的 IR schema。v1.0 IR 是 FOL 子集，v1.1+ 引入时序/模态扩展时需要新的 IR schema。系统应同时支持多版本 IR 的解析和编译。

---


---

## 9. 模糊输入处理子系统（Fuzzy Input Handling Subsystem）

> **设计原则**: LLM 仅负责最必要的自然语言理解；所有结构化推理——模糊性检测、假设管理、置信度传播、澄清触发——必须走符号系统（Datalog / ASP / Z3）。

---

### 9.1 概述与必要性

#### 9.1.1 根本张力：形式逻辑要求精确 vs 人类输入天然模糊

LKB 的核心验证管线建立在形式逻辑之上：Datalog 推导、Z3 不变量检查、ASP 稳定模型枚举。这些求解器要求输入是**良构的（well-formed）**形式化表达式——每个谓词有明确签名，每个常量有确定指称，每个变量有约束范围。

然而，人类用户和 LLM Agent 提交的自然语言断言天生包含四类不精确性：

| 不精确性类别 | 示例 | 对形式化的影响 |
|-------------|------|---------------|
| 语义模糊 | "附近" | 无法确定 `Distance < 500m` 还是 `< 2km` |
| 信息不完备 | "去洗车" | 缺少 `At(车, ?)`，谓词无法完全实例化 |
| 上下文依赖 | "打印文件" | 在家 vs 在公司，隐含前提不同 |
| 隐喻与习惯用法 | "时间不早了" | 表面陈述时间，真实意图是催促行动 |

若将这类输入直接送入 LLM 翻译器，翻译器会被迫**猜测**唯一解释，导致：
1. **过度承诺**：将不确定的猜测编码为确定性断言
2. **隐性漂移**：`nl_assertion` 与 `formal_assertion` 之间的语义差距被掩盖
3. **不可回滚**：一旦猜测错误，依赖该断言的整个推理链需重新验证

#### 9.1.2 与传统 NLP 预处理的本质区别

| 维度 | 传统 NLP 消歧 | LKB 模糊处理子系统 |
|------|--------------|-------------------|
| 目标 | **消除**模糊，输出单一解释 | **显式管理**模糊，保留所有合理解释 |
| 策略 | 选择"最可能"的解释 | 生成多世界，验证所有世界 |
| 正确性保证 | 无——消歧可能错误 | 有——所有世界验证通过才提交 |
| 人机协作 | 无用户参与 | 用户澄清是闭环的一部分 |
| 可审计性 | 黑箱决策 | 每个假设、每个世界、每次澄清均记入日志 |

**核心设计决策**：在 LLM 翻译层与 Canonical IR 生成之间插入一个**模糊性处理层（Ambiguity Processing Layer）**。该层用符号系统检测模糊性，生成多个可能世界，对每个世界独立验证，仅在所有世界结论一致时才给出确定结论。

---

### 9.2 模糊性类型学

模糊性检测在符号系统中进行分类。Datalog 规则库维护四类模糊模式；当文本特征匹配多个模式时，触发多世界生成。

#### 9.2.1 语义模糊（Semantic Vagueness）

概念本身没有明确边界，导致同一自然语言表达对应多个不相容的形式化解释。

| 用户输入片段 | 模糊维度 | 形式化解释 W_1 | 形式化解释 W_2 | Datalog 触发模式 |
|-------------|---------|---------------|---------------|-----------------|
| "离家50米" | 距离度量 | `WalkingDistance(home, shop, 50)` | `EuclideanDistance(home, shop, 50)` | `pattern_distance_ambiguity` |
| "洗车" | 服务主体 | `SelfServiceWash(用户, 车)` | `StaffServiceWash(工作人员, 车)` | `pattern_service_mode` |
| "附近" | 范围阈值 | `Distance < 500m` | `Distance < 2000m` | `pattern_proximity_vague` |
| "很快" | 时间阈值 | `Duration < 5min` | `Duration < 30min` | `pattern_temporal_vague` |
| "便宜" | 价格区间 | `PriceTier = low` | `PriceTier = medium` | `pattern_price_vague` |

**形式化定义**:
```text
SemanticVagueness(NL) := 
  ∃ phrase ⊆ NL . |Formalizations(phrase)| > 1 ∧ 
  ∀ f_1, f_2 ∈ Formalizations(phrase) . f_1 ∧ f_2 → ⊥
```

> 自然语言解释：当自然语言片段 `phrase` 存在多于一种形式化解释，且任意两种解释在逻辑上不相容时，称 `phrase` 具有语义模糊性。

#### 9.2.2 信息不完备（Informational Incompleness）

关键信息缺失，导致形式化断言的谓词无法完整实例化。此类模糊性**不生成多世界**，而是触发假设填充（详见 9.5 节）。

| 用户输入 | 缺失参数 | 形式化阻塞点 | 默认填充策略 |
|---------|---------|-------------|-------------|
| "去洗车" | 车当前位置 | `At(车, ?)` 未知 | 假设 `At(车, 家)`（置信度 0.95） |
| "明天开会" | 具体时间、地点 | `Time(?, ?), Location(?, ?)` | 需用户澄清——无法可靠默认 |
| "买水果" | 水果种类、数量 | `Object(?, ?), Quantity(?, ?)` | 假设 `Quantity = 1`（置信度 0.7） |
| "寄快递" | 快递公司、时效要求 | `Carrier(?, ?), ServiceLevel(?, ?)` | 假设 `ServiceLevel = standard` |

**形式化定义**:
```text
InformationalIncompleteness(NL) :=
  ∃ pred(Args) ∈ CanonicalIR(NL) . ∃ arg_i ∈ Args . arg_i = ⊥ ∧
  arg_i ∉ Domain(default_knowledge_base)
```

> 自然语言解释：当 Canonical IR 中存在未实例化的参数，且该参数不在默认值知识库的覆盖范围内时，标记为信息不完备。若在覆盖范围内，直接用默认值填充并标注假设；否则触发澄清请求。

#### 9.2.3 上下文依赖（Context Dependency）

同一自然语言表达式在不同上下文假设下产生不同形式化解释。

| 用户输入 | 上下文 C_1 | 形式化解释 W_1 | 上下文 C_2 | 形式化解释 W_2 |
|---------|-----------|---------------|-----------|---------------|
| "去银行" | 取现金 | `NeedResource(用户, ATM)` | 办贷款 | `NeedResource(用户, 证件, 预约)` |
| "打印文件" | 在家 | `UseDevice(家用打印机)` | 在公司 | `UseDevice(办公打印机)` |
| "预订餐厅" | 工作日午餐 | `Constraint(时间, < 90min)` | 周末聚会 | `Constraint(时间, none)` |

**形式化定义**:
```text
ContextDependency(NL, Ctx) :=
  ∃ W_1, W_2 . W_1 ∈ Worlds(NL, Ctx_1) ∧ W_2 ∈ Worlds(NL, Ctx_2) ∧
  Ctx_1 ≠ Ctx_2 ∧ W_1 ≠ W_2
```

> 自然语言解释：同一自然语言输入 `NL` 在上下文 `Ctx_1` 和 `Ctx_2` 下产生不同的可能世界集合时，称 `NL` 具有上下文依赖性。

**Datalog 上下文检测规则**:
```prolog
// context_detection.dl —— 上下文依赖检测
.decl known_context(ctx:symbol)
.decl user_location(loc:symbol)
.decl user_time_category(tc:symbol)
.decl nl_contains_phrase(nl:symbol, phrase:symbol)
.decl context_dependency(nl:symbol, ctx1:symbol, ctx2:symbol)

% 上下文事实（由系统维护）
known_context("home").
known_context("office").
known_context("weekday").
known_context("weekend").

% 上下文依赖规则：当 NL 包含特定短语且系统记录多个可能上下文时
context_dependency(NL, Ctx1, Ctx2) :-
  nl_contains_phrase(NL, Phrase),
  phrase_context_sensitive(Phrase, Ctx1),
  phrase_context_sensitive(Phrase, Ctx2),
  Ctx1 != Ctx2,
  current_context_may_be(Ctx1),
  current_context_may_be(Ctx2).

% "去银行" 在多个上下文中含义不同
phrase_context_sensitive("银行", "home").
phrase_context_sensitive("银行", "office").
phrase_context_sensitive("银行", "weekday").
```

#### 9.2.4 隐喻与习惯用法（Metaphor & Idiom）

表面含义与真实意图不一致。此类模糊性**必须**经过 LLM 初步识别（这是 LLM 不可替代的少数场景之一），但识别后的处理仍走符号系统。

| 用户输入 | 表面（字面）含义 | 真实意图 | 处理策略 |
|---------|----------------|---------|---------|
| "时间不早了" | 时间陈述 | 建议尽快行动 | LLM 标记为 `idiom_urge_action`，Datalog 规则触发催促语义解释 |
| "这有点贵" | 价格评价 | 希望找到更便宜的替代方案 | LLM 标记为 `idiom_price_objection`，生成 `SeekAlternative(更便宜)` |
| "我看看" | 视觉动作 | 需要考虑/犹豫 | LLM 标记为 `idiom_hesitation`，不立即推进任务 |
| "随便吃点" | 随机选择 | 不挑剔，由对方推荐 | LLM 标记为 `idiom_delegate_choice`，生成 `Recommend(食物)` |

**形式化定义**:
```text
MetaphoricalUsage(NL) :=
  ∃ phrase ⊆ NL . LiteralMeaning(phrase) ≠ IntendedMeaning(phrase) ∧
  IdiomDetected(phrase) = true
```

**处理管线**（LLM 识别 → 符号系统处理）:
```text
Step 1: LLM 标记 phrase 为 idiom_type（必需 LLM，符号系统无法识别隐喻）
Step 2: Datalog 查询 idiom_rules 库，获取该 idiom_type 的形式化展开
Step 3: 将展开后的形式化表达纳入 Worlds(NL)，置信度 = idiom_base_confidence
Step 4: 若 idiom_type 不在规则库中 → 触发人类审查（不猜测）
```

**Datalog 习惯用法规则库**:
```prolog
// idiom_rules.dl —— 习惯用法的符号化处理
.decl idiom_pattern(idiom_type:symbol, phrase_pattern:symbol)
.decl idiom_formalization(idiom_type:symbol, formal_pred:symbol, confidence:float)
.decl idiom_detected(nl:symbol, idiom_type:symbol, position:number)

% 习惯用法模式库
idiom_pattern("urge_action", "时间不早").
idiom_pattern("urge_action", "该走了").
idiom_pattern("price_objection", "有点贵").
idiom_pattern("price_objection", "太贵").
idiom_pattern("hesitation", "我看看").
idiom_pattern("hesitation", "考虑一下").
idiom_pattern("delegate_choice", "随便").

% 形式化展开
idiom_formalization("urge_action", "SuggestExpedite(Task)", 0.85).
idiom_formalization("price_objection", "SeekAlternative(lower_price)", 0.80).
idiom_formalization("hesitation", "RequestPause(Task)", 0.75).
idiom_formalization("delegate_choice", "RequestRecommendation(domain)", 0.80).

% 检测规则：当 NL 包含习惯用法模式时
idiom_detected(NL, IdiomType, Pos) :-
  nl_text(NL, Text),
  idiom_pattern(IdiomType, Pattern),
  substring_match(Text, Pattern, Pos).
```

---

### 9.3 核心设计：多世界语义（Multi-World Semantics）

#### 9.3.1 形式化定义

给定自然语言断言 `NL`，模糊性处理层生成一组**可能世界（Possible Worlds）**：

```text
Worlds(NL) = { W_1, W_2, ..., W_n }

其中每个 W_i := <I_i, c_i, A_i, R_i, V_i>

  I_i : Canonical_IR          -- 第 i 种形式化解释（Canonical IR）
  c_i : [0, 1]                -- 该解释的置信度，满足 Σ c_i = 1.0
  A_i : Set<Assumption>       -- 该解释依赖的假设集合
  R_i : Set<AmbiguityResolution>  -- 该解释下如何消解了模糊性
  V_i : {pending, pass, fail, stale}  -- 验证结果（初始为 pending）
```

**世界的合法性约束**:
```text
∀ W_i ∈ Worlds(NL) .
  Consistent(W_i.I_i) ∧                -- 解释自身逻辑一致
  (∀ a ∈ W_i.A_i . a.confidence > 0) ∧ -- 所有假设有正置信度
  W_i.c_i > 0                           -- 所有世界有正概率
```

#### 9.3.2 多世界验证流程

```text
                    ┌─────────────────────────────────────┐
                    │         自然语言输入 NL               │
                    │   "离家50米的洗车店，走路还是开车？"    │
                    └─────────────────┬───────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────┐
                    │  模糊性检测器 (Datalog/ASP 优先)      │
                    │  - pattern_distance_ambiguity 匹配     │
                    │  - pattern_service_mode 匹配           │
                    │  - 信息不完备检测                      │
                    │  输出: AmbiguityReport                  │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │         世界生成器 (ASP)              │
                    │                                     │
                    │  ┌─────────────────────────────┐    │
                    │  │  W_1 (c=0.6)                │    │
                    │  │  I_1: WalkingDistance=50    │    │
                    │  │  A_1: {H_walking_dist}      │    │
                    │  │  R_1: distance→walking      │    │
                    │  └─────────────────────────────┘    │
                    │  ┌─────────────────────────────┐    │
                    │  │  W_2 (c=0.4)                │    │
                    │  │  I_2: EuclideanDistance=50  │    │
                    │  │  A_2: {H_straight_dist}     │    │
                    │  │  R_2: distance→straight     │    │
                    │  └─────────────────────────────┘    │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │      假设填充器 (Datalog 默认值 KB)    │
                    │  - H-002: 洗车=工作人员代洗 (c=0.8)   │
                    │  - H-003: 车在家 (c=0.95)             │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │       独立验证管线（每个世界）          │
                    │                                     │
                    │   W_1 ──→ Layer 1 Datalog ──→ V_1   │
                    │      ──→ Layer 2 Z3 ────────→ V_1   │
                    │                                     │
                    │   W_2 ──→ Layer 1 Datalog ──→ V_2   │
                    │      ──→ Layer 2 Z3 ────────→ V_2   │
                    │                                     │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │         结果聚合器 (符号规则)          │
                    │                                     │
                    │  IF V_1.pass ∧ V_2.pass:            │
                    │     IF Conclusion(W_1) = Conclusion(W_2):  → 确定结论
                    │     ELSE:  → 结论依赖解释，需澄清      │
                    │  IF V_1.pass ∧ V_2.fail:            │
                    │     → 结论依赖解释，需澄清             │
                    │  IF V_1.fail ∧ V_2.fail:            │
                    │     → 所有解释下不可行                 │
                    │                                     │
                    └─────────────────────────────────────┘
```

#### 9.3.3 结论聚合策略

聚合策略由 Datalog 规则实现，非 LLM 判断：

```prolog
// world_aggregation.dl —— 多世界结论聚合
.decl world_verification(world_id:symbol, result:symbol)
.decl world_conclusion(world_id:symbol, conclusion_hash:symbol)
.decl aggregation_result(strategy:symbol, action:symbol)

% 策略1: 所有世界通过且结论一致 → 确定结论
aggregation_result("unanimous_pass", "commit") :-
  world_verification(W1, "pass"),
  world_verification(W2, "pass"),
  world_conclusion(W1, CH),
  world_conclusion(W2, CH),
  W1 != W2.

% 策略2: 所有世界通过但结论不一致 → 需澄清
aggregation_result("divergent_conclusions", "request_clarification") :-
  world_verification(W1, "pass"),
  world_verification(W2, "pass"),
  world_conclusion(W1, CH1),
  world_conclusion(W2, CH2),
  CH1 != CH2.

% 策略3: 部分通过部分失败 → 需澄清（解释影响结论）
aggregation_result("partial_pass", "request_clarification") :-
  world_verification(_, "pass"),
  world_verification(_, "fail").

% 策略4: 所有世界失败 → 不可行
aggregation_result("unanimous_fail", "reject") :-
  world_verification(W, "fail") : world_id(W).
  % ^ 所有世界都失败

% 辅助：世界 ID 枚举
.decl world_id(w:symbol)
world_id("W_1").
world_id("W_2").
```

**聚合决策表**:

| W_1 结果 | W_2 结果 | 结论一致性 | 聚合策略 | 系统行动 |
|---------|---------|-----------|---------|---------|
| pass | pass | 一致 | `unanimous_pass` | 给出确定结论，允许 Commit |
| pass | pass | 不一致 | `divergent_conclusions` | 向用户展示两种结论，请求澄清 |
| pass | fail | — | `partial_pass` | 解释依赖解释选择，请求澄清 |
| fail | pass | — | `partial_pass` | 同上 |
| fail | fail | — | `unanimous_fail` | 拒绝断言，给出修复建议 |
| pending | any | — | `incomplete` | 等待验证完成 |

#### 9.3.4 与 Commit Gate 的集成

模糊断言通过 Commit Gate 时必须满足额外的模糊性检查项：

```python
def commit_gate_fuzzy_check(task: Task, worlds: list[World]) -> CommitDecision:
    """
    Commit Gate 模糊性增强检查。
    插入点：在标准 commit_gate_check 之后，最终决策之前。
    """
    # 检查1: 最低假设置信度
    min_assumption_confidence = min(
        a.confidence for w in worlds for a in w.assumptions
    ) if any(w.assumptions for w in worlds) else 1.0
    
    if min_assumption_confidence < FUZZY_THRESHOLD_MINOR:
        return CommitDecision(
            commit=False,
            reason="fuzzy_assumption_confidence_too_low",
            human_message={
                "zh": f"假设置信度过低 ({min_assumption_confidence:.2f})，需要澄清。",
                "en": f"Assumption confidence too low ({min_assumption_confidence:.2f}), clarification needed."
            }
        )
    
    # 检查2: 多世界一致性（调用 Datalog 聚合）
    aggregation = query_datalog_aggregation(worlds)
    if aggregation.strategy in ("divergent_conclusions", "partial_pass"):
        return CommitDecision(
            commit=False,
            reason="fuzzy_divergent_worlds",
            human_message=generate_divergence_explanation(worlds, aggregation),
            worlds=worlds  # 返回所有世界供用户选择
        )
    
    # 检查3: 未澄清的 critical 模糊性
    if any(a.severity == "critical" and not a.user_clarified 
           for w in worlds for a in w.ambiguities):
        return CommitDecision(
            commit=False,
            reason="fuzzy_critical_unresolved",
            human_message={
                "zh": "存在未澄清的关键模糊性，请先澄清。",
                "en": "Unresolved critical ambiguity exists. Please clarify."
            }
        )
    
    return CommitDecision(commit=True, checks={"fuzzy": "pass"})
```

---

### 9.4 模糊性检测机制 —— 符号系统优先

本节展示模糊性检测的完整管线。**核心原则**：Datalog 规则匹配 → ASP 多解枚举 → LLM Self-Critique fallback。LLM 仅在符号系统无法覆盖时介入。

#### 9.4.1 Datalog 规则匹配（第一优先级）

**预设模糊模式库**（YAML 格式，运行时加载为 Datalog 事实）：

```yaml
# fuzzy_patterns.yaml —— 模糊模式库
# 由运营团队维护，支持热更新
version: "1.0"
patterns:
  # ── 语义模糊模式 ──
  - pattern_id: "P-DIST-001"
    category: "semantic_vagueness"
    severity: "major"
    regex_tokens: ["距离", "(?<number>\\d+)", "米"]
    datalog_trigger: "pattern_distance_ambiguity"
    interpretations:
      - code: "walking"
        formalization: "WalkingDistance({from}, {to}, {number})"
        base_confidence: 0.60
      - code: "straight"
        formalization: "EuclideanDistance({from}, {to}, {number})"
        base_confidence: 0.40
      - code: "driving"
        formalization: "DrivingDistance({from}, {to}, {number})"
        base_confidence: 0.00  # 仅当上下文含"开车"时激活

  - pattern_id: "P-SERV-001"
    category: "semantic_vagueness"
    severity: "critical"
    regex_tokens: ["洗车"]
    datalog_trigger: "pattern_service_mode"
    interpretations:
      - code: "staff_service"
        formalization: "StaffServiceWash({staff}, {vehicle})"
        base_confidence: 0.80
      - code: "self_service"
        formalization: "SelfServiceWash({customer}, {vehicle})"
        base_confidence: 0.15
      - code: "automatic"
        formalization: "AutomaticWash({vehicle})"
        base_confidence: 0.05

  - pattern_id: "P-PROX-001"
    category: "semantic_vagueness"
    severity: "minor"
    regex_tokens: ["附近|旁边|周围|周边"]
    datalog_trigger: "pattern_proximity_vague"
    interpretations:
      - code: "very_close"
        formalization: "Distance < 100"
        base_confidence: 0.20
      - code: "close"
        formalization: "Distance < 500"
        base_confidence: 0.50
      - code: "moderate"
        formalization: "Distance < 2000"
        base_confidence: 0.30

  - pattern_id: "P-TEMP-001"
    category: "semantic_vagueness"
    severity: "minor"
    regex_tokens: ["很快|马上|不久|立马|立刻"]
    datalog_trigger: "pattern_temporal_vague"
    interpretations:
      - code: "immediate"
        formalization: "Duration < 5"
        base_confidence: 0.40
      - code: "soon"
        formalization: "Duration < 30"
        base_confidence: 0.45
      - code: "today"
        formalization: "SameDay"
        base_confidence: 0.15

  # ── 信息不完备模式 ──
  - pattern_id: "P-INFO-001"
    category: "informational_incompleteness"
    severity: "major"
    regex_tokens: ["去", "(?<place_type>洗|修|买|吃)"]
    datalog_trigger: "pattern_missing_location"
    required_predicate: "At(vehicle, ?location)"
    default_assumption:
      field: "vehicle_location"
      default_value: "user_home"
      confidence: 0.95

  # ── 上下文依赖模式 ──
  - pattern_id: "P-CTX-001"
    category: "context_dependency"
    severity: "major"
    regex_tokens: ["去银行"]
    datalog_trigger: "pattern_context_bank"
    context_dependent: true
    contexts:
      - code: "withdrawal"
        condition: "time = weekday_morning"
        formalization: "BankService(ATM, withdrawal)"
      - code: "loan"
        condition: "user_mentioned_loan_before"
        formalization: "BankService(appointment, loan)"

  # ── 隐喻/习惯用法模式 ──
  - pattern_id: "P-IDM-001"
    category: "metaphor_idiom"
    severity: "minor"
    regex_tokens: ["时间不早"]
    datalog_trigger: "pattern_idiom_urge"
    llm_required: true  # LLM 标记后 Datalog 处理
    formalization: "SuggestExpedite(current_task)"
    base_confidence: 0.85
```

**Datalog 规则匹配引擎**:
```prolog
// fuzzy_detection.dl —— 模糊性检测核心引擎
.decl tokenized_nl(seq_id:symbol, position:number, token:symbol)
.decl pattern_matched(seq_id:symbol, pattern_id:symbol, severity:symbol)
.decl ambiguity_detected(seq_id:symbol, amb_type:symbol, severity:symbol, pattern_id:symbol)
.decl detection_result(seq_id:symbol, trigger_multi_world:symbol)

% 事实：token 序列来自 NLP 分词器输出
tokenized_nl("SEQ-001", 0, "离家").
tokenized_nl("SEQ-001", 1, "50").
tokenized_nl("SEQ-001", 2, "米").
tokenized_nl("SEQ-001", 3, "的").
tokenized_nl("SEQ-001", 4, "洗车").
tokenized_nl("SEQ-001", 5, "店").

% 规则：连续 token 匹配模式 → 标记匹配
pattern_matched(Seq, "P-DIST-001", "major") :-
  tokenized_nl(Seq, P, Tok1),
  tokenized_nl(Seq, P+1, Tok2),
  tokenized_nl(Seq, P+2, Tok3),
  distance_token(Tok1),
  number_token(Tok2),
  meter_token(Tok3).

pattern_matched(Seq, "P-SERV-001", "critical") :-
  tokenized_nl(Seq, _, "洗车").

pattern_matched(Seq, "P-PROX-001", "minor") :-
  tokenized_nl(Seq, _, Tok),
  proximity_token(Tok).

% 模糊性分类
ambiguity_detected(Seq, "semantic_vagueness", Sev, PID) :-
  pattern_matched(Seq, PID, Sev),
  pattern_category(PID, "semantic_vagueness").

ambiguity_detected(Seq, "informational_incompleteness", Sev, PID) :-
  pattern_matched(Seq, PID, Sev),
  pattern_category(PID, "informational_incompleteness").

% 触发多世界生成的条件：存在语义模糊或上下文依赖
detection_result(Seq, "trigger_multi_world") :-
  ambiguity_detected(Seq, "semantic_vagueness", _, _).

detection_result(Seq, "trigger_multi_world") :-
  ambiguity_detected(Seq, "context_dependency", _, _).

detection_result(Seq, "trigger_assumption_fill") :-
  ambiguity_detected(Seq, "informational_incompleteness", _, _).

% 辅助谓词
.decl distance_token(t:symbol)
.decl number_token(t:symbol)
.decl meter_token(t:symbol)
.decl proximity_token(t:symbol)
.decl pattern_category(pid:symbol, cat:symbol)

distance_token("离家").
distance_token("距离").
number_token("50").
number_token("100").
meter_token("米").
meter_token("公里").
proximity_token("附近").
proximity_token("旁边").
proximity_token("周围").

pattern_category("P-DIST-001", "semantic_vagueness").
pattern_category("P-SERV-001", "semantic_vagueness").
pattern_category("P-PROX-001", "semantic_vagueness").
pattern_category("P-INFO-001", "informational_incompleteness").
pattern_category("P-CTX-001", "context_dependency").
pattern_category("P-IDM-001", "metaphor_idiom").

% 输出
.output ambiguity_detected
.output detection_result
```

#### 9.4.2 ASP 多解枚举（第二优先级）

当 Datalog 规则匹配产生多个候选解释时，调用 ASP（clingo）枚举所有合法世界组合。

```prolog
% fuzzy_worlds.lp —— ASP 多世界枚举
% 输入：Datalog 检测到的模糊点
% 输出：所有合法的可能世界组合

% 模糊点定义（来自 Datalog 输出）
ambiguity_point(1, distance, 2).    % 位置1有2种距离解释
ambiguity_point(2, service, 2).     % 位置2有2种服务解释

% 候选解释
candidate(1, 1, walking_distance).
candidate(1, 2, straight_distance).
candidate(2, 1, staff_service).
candidate(2, 2, self_service).

% 为每个模糊点恰好选择一个解释
1 { chosen(Point, Choice) : candidate(Point, Choice, _) } 1 :- ambiguity_point(Point, _, _).

% 世界编号：每个选择组合构成一个世界
world_id(W) :- W = #count{ P,C : chosen(P,C) }.

% 世界描述（用于人类可读展示）
world_description(W, Desc) :-
    world_id(W),
    Desc = #concat{
        CText : chosen(P, C), candidate(P, C, Meaning), meaning_text(Meaning, CText)
    }.

% 约束：排除不合法的组合（领域知识）
% 例：若选择"自助洗车"，则不需要车在店
:- chosen(2, 2), chosen(1, 2).  % 自助洗车 + 直线距离（到店通常需要走路，矛盾）

% 置信度计算：基于各选择的基础置信度
world_confidence(W, Conf) :-
    world_id(W),
    Conf = #product{
        BaseConf : chosen(P,C), candidate_base_confidence(P,C,BaseConf)
    }.

% 需要归一化（后处理）

% 输出
#show chosen/2.
#show world_confidence/2.
```

**Python 调用封装**:
```python
import clingo

def enumerate_fuzzy_worlds(datalog_output: dict) -> list[World]:
    """
    使用 clingo 枚举所有合法的模糊世界组合。
    输入：Datalog 模糊性检测输出
    输出：World 列表，含置信度（未归一化）
    """
    asp_facts = translate_detection_to_asp(datalog_output)
    
    ctl = clingo.Control(arguments=["--models=0"])
    ctl.add("base", [], ASP_WORLD_ENUMERATION_TEMPLATE + asp_facts)
    ctl.ground([("base", [])])
    
    worlds = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            symbols = model.symbols(shown=True)
            world = parse_world_from_model(symbols)
            worlds.append(world)
    
    # 归一化置信度
    total = sum(w.confidence for w in worlds)
    for w in worlds:
        w.confidence /= total
    
    return worlds
```

#### 9.4.3 LLM Self-Critique（Fallback 策略）

当 Datalog 规则库和 ASP 枚举均**无法覆盖**输入中的模糊性时，启用 LLM Self-Critique 作为 fallback。触发条件由 Datalog 规则判定：

```prolog
// llm_fallback.dl —— LLM fallback 触发判定
.decl llm_fallback_required(seq_id:symbol, reason:symbol)

% Fallback 条件1: 没有任何预设模式匹配，但文本长度 > 阈值
llm_fallback_required(Seq, "no_pattern_match") :-
  nl_text(Seq, Text),
  strlen(Text, Len),
  Len > 5,
  not pattern_matched(Seq, _, _).

% Fallback 条件2: 检测到可能的隐喻（token 不在任何字面模式库中）
llm_fallback_required(Seq, "possible_metaphor") :-
  tokenized_nl(Seq, _, Tok),
  not token_in_literal_vocab(Tok),
  token_frequency(Tok, Freq),
  Freq > 100.  % 高频词但不在模式库中，可能是习惯用法
```

**LLM Self-Critique Prompt 模板**:
```yaml
# llm_fallback_prompt.yaml
prompt_template:
  system: |
    你是 LKB 模糊性检测的 fallback 模块。你的任务是分析用户输入中
    可能存在的模糊性，输出结构化的模糊性报告。
    
    重要：你只处理符号系统（Datalog/ASP）无法覆盖的输入。
    不要重复符号系统已检测到的模糊点。

  user_template: |
    用户原始输入: "{nl_text}"
    
    符号系统已检测到的模糊点: {symbolic_detected_ambiguities}
    
    请分析：符号系统是否遗漏了任何模糊性？
    
    输出要求（严格 JSON 格式）:
    {{
      "llm_detected_ambiguities": [
        {{
          "phrase": "检测到的模糊片段",
          "kind": "semantic_vagueness|informational_incompleteness|context_dependency|metaphor_idiom",
          "interpretations": [
            {{"meaning": "解释1", "base_confidence": 0.6}},
            {{"meaning": "解释2", "base_confidence": 0.4}}
          ],
          "severity": "critical|major|minor|negligible",
          "rationale": "为什么符号系统遗漏了此模糊点"
        }}
      ],
      "symbolic_coverage_assessment": "complete|partial|none",
      "recommendation": "是否需要将此模糊模式加入符号规则库"
    }}
    
    如果符号系统已完整覆盖，返回 llm_detected_ambiguities 为空列表。

  constraints:
    temperature: 0.0        # 确定性输出
    max_tokens: 500
    require_json: true
    override_symbolic: false  # LLM 检测不覆盖符号系统结果，仅补充
```

#### 9.4.4 模糊性严重度评级（Datalog 规则判定）

严重度由 Datalog 规则根据**影响范围**自动判定，非 LLM 判断：

```prolog
// severity_rules.dl —— 模糊性严重度评级引擎
.decl ambiguity_severity(amb_id:symbol, severity:symbol, rationale:symbol)

% CRITICAL: 导致完全不同的行动方案（计划级影响）
ambiguity_severity(Amb, "critical", "plan_divergence") :-
  ambiguity_point(Amb, _, _),
  interpretation_plan_impact(Amb, Plan1, "completely_different"),
  interpretation_plan_impact(Amb, Plan2, "completely_different"),
  Plan1 != Plan2.

% MAJOR: 影响方案优劣排序但不改变根本可行性
ambiguity_severity(Amb, "major", "ranking_impact") :-
  ambiguity_point(Amb, _, _),
  interpretation_plan_impact(Amb, Plan1, "different_ranking"),
  interpretation_plan_impact(Amb, Plan2, "different_ranking"),
  Plan1 != Plan2,
  not ambiguity_severity(Amb, "critical", _).

% MINOR: 影响细节但不改变结论
ambiguity_severity(Amb, "minor", "detail_variation") :-
  ambiguity_point(Amb, _, _),
  interpretation_plan_impact(Amb, _, "same_conclusion"),
  count_interpretations(Amb, N),
  N > 1,
  not ambiguity_severity(Amb, "critical", _),
  not ambiguity_severity(Amb, "major", _).

% NEGLIGIBLE: 不影响任何决策
ambiguity_severity(Amb, "negligible", "no_decision_impact") :-
  ambiguity_point(Amb, _, _),
  forall interpretation_plan_impact(Amb, _, "no_impact"),
  count_interpretations(Amb, N),
  N >= 1.
```

**严重度判定表**:

| 严重度 | 判定标准（Datalog） | 示例 | 系统行动 |
|-------|-------------------|------|---------|
| `critical` | 不同解释导致完全不同的行动方案 | "洗车"→自助 vs 代洗（前者不需要车到店） | 必须向用户澄清 |
| `major` | 影响方案优劣排序或可行性 | "50米"→直线 vs 步行（步行时间差异） | 生成多世界验证，展示不同结论 |
| `minor` | 影响数值细节但不改变结论 | "很快到"→5min vs 10min | 使用合理默认值，标注假设 |
| `negligible` | 不影响任何决策 | "那家洗车店"→指代具体实例 | 忽略，使用上下文推断 |

---

### 9.5 假设驱动推演 —— 符号系统优先

信息不完备的处理不生成多世界，而是使用**默认值知识库**填充缺失信息。所有填充值被标注为假设，纳入 Truth Maintenance 追踪。

#### 9.5.1 默认值知识库（Datalog 事实+规则格式）

```prolog
// default_knowledge_base.dl —— 默认值知识库

% ── 通用默认值（领域无关）──
.decl default_universal(field:symbol, default_value:symbol, confidence:float, rationale:symbol)

default_universal("time_zone", "current_system_tz", 0.95, "设备时区最可能正确").
default_universal("distance_type", "walking", 0.60, "人类通常根据步行经验估算距离").
default_universal("quantity_when_unspecified", "1", 0.70, "未指定数量时最可能为单数").
default_universal("transport_preference_urban", "public_transit", 0.55, "城市环境公共交通基线偏好").

% ── 领域默认值（automotive）──
.decl default_domain(domain:symbol, field:symbol, default_value:symbol, confidence:float, rationale:symbol)

default_domain("automotive", "wash_service_type", "staff_service", 0.80, "大多数洗车店提供代洗服务").
default_domain("automotive", "key_location", "with_owner", 0.95, "车钥匙通常由车主携带").
default_domain("automotive", "vehicle_location_when_unspecified", "user_home", 0.90, "未提及位置时车辆最可能在用户住所").
default_domain("automotive", "fuel_type_default", "gasoline", 0.75, "汽油车仍占市场多数").

% ── 领域默认值（food）──
default_domain("food", "dining_party_size", "1", 0.70, "单人用餐为最小假设").
default_domain("food", "dietary_restriction", "none", 0.80, "无饮食禁忌为最大似然假设").
default_domain("food", "spice_preference_unspecified", "moderate", 0.65, "中等辣度为安全默认").

% ── 上下文敏感默认值 ──
.decl default_contextual(condition_pred:symbol, field:symbol, default_value:symbol, confidence:float)

default_contextual("user_at_home", "departure_location", "user_current_location", 0.95).
default_contextual("weekday_daytime", "transport_mode", "public_transit", 0.60).
default_contextual("weekend_shopping", "shopping_list_complete", "incomplete", 0.50).
default_contextual("evening_hours", "restaurant_reservation_needed", "true", 0.70).

% ── 默认值应用规则 ──
.decl applied_assumption(entity:symbol, field:symbol, value:symbol, confidence:float, source:symbol, assumption_id:symbol)

% 规则1: 通用默认
applied_assumption(Entity, Field, Value, Conf, "universal_default", AssumptionID) :-
  entity_needs_field(Entity, Field),
  not has_explicit_value(Entity, Field),
  default_universal(Field, Value, Conf, _),
  AssumptionID = cat(cat("H-UNIV-", Field), cat("-", Entity)).

% 规则2: 领域默认（优先级高于通用）
applied_assumption(Entity, Field, Value, Conf, cat("domain_", Domain), AssumptionID) :-
  entity_needs_field(Entity, Field),
  not has_explicit_value(Entity, Field),
  entity_domain(Entity, Domain),
  default_domain(Domain, Field, Value, Conf, _),
  AssumptionID = cat(cat("H-DOM-", Field), cat("-", Entity)).

% 规则3: 上下文敏感默认（优先级最高）
applied_assumption(Entity, Field, Value, Conf, cat("context_", Condition), AssumptionID) :-
  entity_needs_field(Entity, Field),
  not has_explicit_value(Entity, Field),
  default_contextual(Condition, Field, Value, Conf),
  condition_holds(Condition, Entity),
  AssumptionID = cat(cat("H-CTX-", Field), cat("-", Entity)).

% 优先级覆盖：上下文 > 领域 > 通用
.conflict_resolution applied_assumption {
  priority: context > domain > universal
}
```

#### 9.5.2 假设标注形式化（YAML Schema）

```yaml
# assumption_schema.yaml —— 假设标注规范
$schema: "https://json-schema.org/draft/07/schema#"
title: "LKB Assumption"
type: object
required:
  - assumption_id
  - field
  - assumed_value
  - confidence
  - source
properties:
  assumption_id:
    type: string
    description: "全局唯一假设标识符，格式 H-{source}-{field}-{entity}"
    pattern: "^H-[A-Z]+-.+-.+$"
  
  field:
    type: string
    description: "被假设填充的字段名"
  
  assumed_value:
    type: [string, number, boolean, object]
    description: "假设的值"
  
  confidence:
    type: number
    minimum: 0.0
    maximum: 1.0
    description: "假设的置信度 [0,1]"
  
  source:
    type: string
    enum:
      - universal_default      # 通用默认值
      - domain_default         # 领域默认值
      - context_default        # 上下文敏感默认值
      - llm_inference          # LLM 推理（最低优先级）
      - user_clarified         # 用户澄清（置信度=1.0）
      - historical_preference  # 用户历史偏好
    description: "假设来源"
  
  needs_clarification:
    type: boolean
    description: "是否需要向用户澄清此假设"
  
  severity_trigger:
    type: string
    enum: [critical, major, minor, negligible]
    description: "触发此假设的模糊性严重度"
  
  clarifiable:
    type: boolean
    default: true
    description: "此假设是否可通过用户澄清消除"
  
  clarification_prompt:
    type: string
    description: "向用户展示的澄清提示文本（多语言）"
    properties:
      zh:
        type: string
      en:
        type: string
  
  provenance:
    type: object
    required: [created_at, created_by]
    properties:
      created_at:
        type: string
        format: date-time
      created_by:
        type: string
        enum: [datalog_engine, asp_engine, llm_fallback, user_input]
      llm_model:
        type: string
        description: "若由 LLM 生成，记录模型版本"
  
  valid_until:
    type: [string, "null"]
    format: date-time
    description: "假设有效期截止时间（null 表示无限制）"
  
  invalidated_by:
    type: [string, "null"]
    description: "使此假设失效的事件/断言 ID"
  
  dependent_assertions:
    type: array
    items:
      type: string
    description: "依赖此假设的断言 ID 列表（Truth Maintenance 用）"
```

**假设标注示例**:
```yaml
# 假设标注实例
assumption_id: "H-DOM-wash_service_type-vehicle_001"
field: "wash_service_type"
assumed_value: "staff_service"
confidence: 0.80
source: "domain_default"
severity_trigger: "critical"
needs_clarification: true
clarifiable: true
clarification_prompt:
  zh: "您说的'洗车'是指工作人员代洗还是自助洗车？这会影响推荐的交通方式。"
  en: "When you say 'car wash', do you mean staff service or self-service? This affects the recommended transportation."
provenance:
  created_at: "2026-07-04T10:00:00Z"
  created_by: "datalog_engine"
valid_until: null
invalidated_by: null
dependent_assertions:
  - "A-1024"
  - "A-1025"
```

#### 9.5.3 假设与 Truth Maintenance 的集成

假设是 Truth Maintenance System（TMS）的一等公民。假设失效时，所有依赖断言自动标记为 stale。

```prolog
// tms_integration.dl —— 假设与 Truth Maintenance 集成

.decl assumes(assertion_id:symbol, assumption_id:symbol)
.decl assumption_status(assumption_id:symbol, status:symbol)
.decl assertion_status(assertion_id:symbol, status:symbol)
.decl derived_assertion(derived:symbol, source:symbol)

% TMS 规则：假设失效 → 依赖断言标记 stale
assertion_status(A, "stale") :-
  assumes(A, H),
  assumption_status(H, "invalidated").

% TMS 规则：递归传播——派生断言也 stale
assertion_status(D, "stale") :-
  derived_assertion(D, S),
  assertion_status(S, "stale").

% 假设失效来源记录
assumption_status(H, "invalidated") :-
  user_clarification_overrides(H).

assumption_status(H, "invalidated") :-
  contradictory_evidence(H, _).

assumption_status(H, "invalidated") :-
  context_change_invalidates(H, _).

% 用户澄清使假设升级为确定性事实
assumption_status(H, "user_confirmed") :-
  user_clarification_confirms(H).

% 假设确认后更新置信度
assumption_confidence(H, 1.0) :-
  assumption_status(H, "user_confirmed").
```

**TMS 传播流程**:
```text
1. 假设 H 被标记 invalidated（用户澄清/矛盾证据/上下文变化）
   │
   ▼
2. Datalog 查询 assumes(A, H) → 找到所有依赖 H 的断言 A
   │
   ▼
3. 将 A.status → stale, A.valid_until = now()
   │
   ▼
4. 递归查询 derived_assertion(D, A) → D 也 stale
   │
   ▼
5. 受影响任务重新运行 Layer 1 Datalog 推导
   │
   ▼
6. 若推导结果变化（如 Ready → Blocked），更新任务状态
   │
   ▼
7. 记录 event_log: event_type = "tms_propagation"
```

#### 9.5.4 Z3 置信度传播

用 Z3 约束传播计算断言的综合置信度。将置信度视为概率约束，利用 Z3 的优化功能传播不确定性。

```python
# confidence_propagation_z3.py
from z3 import *

def propagate_assertion_confidence(
    assertion_id: str,
    translation_confidence: float,
    assumptions: list[dict],
    ambiguity_resolved: bool,
    verification_result: str,
    user_clarified: bool
) -> dict:
    """
    使用 Z3 约束传播计算断言综合置信度。
    
    模型：链式置信度衰减 + 模糊性惩罚。
    Z3 用于验证置信度计算的正确性，而非替代计算。
    """
    
    # 创建 Z3 优化器
    opt = Optimize()
    
    # 定义置信度变量
    tc = Real('translation_confidence')       # 翻译置信度
    ac = Real('min_assumption_confidence')    # 最小假设置信度
    fc = Real('fuzzy_penalty')                # 模糊性惩罚
    vc = Real('verification_confidence')      # 验证置信度
    uc = Real('user_clarification_boost')     # 用户澄清加成
    final_c = Real('final_confidence')        # 最终置信度
    
    # 约束：各分量在 [0, 1] 范围内
    opt.add(tc >= 0, tc <= 1)
    opt.add(ac >= 0, ac <= 1)
    opt.add(fc >= 0, fc <= 1)
    opt.add(vc >= 0, vc <= 1)
    opt.add(uc >= 0, uc <= 1)
    opt.add(final_c >= 0, final_c <= 1)
    
    # 约束：翻译置信度
    opt.add(tc == translation_confidence)
    
    # 约束：最小假设置信度（最弱链路）
    if assumptions:
        assumption_confs = [a['confidence'] for a in assumptions]
        min_assumption = min(assumption_confs)
        opt.add(ac == min_assumption)
        
        # 额外约束：所有假设的置信度 ≥ ac
        for i, a_conf in enumerate(assumption_confs):
            ai = Real(f'assumption_{i}_confidence')
            opt.add(ai == a_conf)
            opt.add(ai >= ac)
    else:
        opt.add(ac == 1.0)
    
    # 约束：模糊性惩罚
    if ambiguity_resolved:
        opt.add(fc == 1.0)
    else:
        opt.add(fc == 0.7)  # 未消解模糊性 = 30% 惩罚
    
    # 约束：验证结果
    if verification_result == "pass":
        opt.add(vc == 1.0)
    elif verification_result == "fail":
        opt.add(vc == 0.0)
    else:
        opt.add(vc == 0.5)  # unknown/timeout = 50%
    
    # 约束：用户澄清
    if user_clarified:
        opt.add(uc == 1.0)
    else:
        opt.add(uc == 0.8)  # 未澄清 = 20% 惩罚
    
    # 核心约束：最终置信度 = 链式乘积
    opt.add(final_c == tc * ac * fc * vc * uc)
    
    # 优化目标：验证最终置信度
    opt.maximize(final_c)
    
    if opt.check() == sat:
        model = opt.model()
        final_confidence = float(model.eval(final_c).as_decimal(10))
        
        return {
            "assertion_id": assertion_id,
            "final_confidence": round(final_confidence, 4),
            "components": {
                "translation_confidence": float(model.eval(tc).as_decimal(10)),
                "min_assumption_confidence": float(model.eval(ac).as_decimal(10)),
                "fuzzy_penalty": float(model.eval(fc).as_decimal(10)),
                "verification_confidence": float(model.eval(vc).as_decimal(10)),
                "user_clarification_boost": float(model.eval(uc).as_decimal(10))
            },
            "z3_verified": True
        }
    else:
        # Z3 不可满足 → 置信度约束冲突（不应发生，用于调试）
        return {
            "assertion_id": assertion_id,
            "final_confidence": 0.0,
            "z3_verified": False,
            "error": "confidence_constraints_unsatisfiable"
        }
```

**置信度计算公式**（Z3 验证后的确定性计算）：
```text
Confidence(A) = tc(A) × min{conf(h) | h ∈ Assumptions(A)} × fc(A) × vc(A) × uc(A)

其中：
  tc(A) = translation_confidence(A)              ∈ [0, 1]
  ac(A) = min(confidence(h) for h in H(A))       ∈ [0, 1]（最弱链路）
  fc(A) = 1.0  if ambiguity_resolved else 0.7    ∈ {1.0, 0.7}
  vc(A) = 1.0  if verification == pass           ∈ {1.0, 0.5, 0.0}
           0.5  if verification == unknown/timeout
           0.0  if verification == fail
  uc(A) = 1.0  if user_clarified else 0.8        ∈ {1.0, 0.8}
```

**置信度阈值与视觉映射**:

| 置信度区间 | 级别 | 视觉指示 | 处理策略 |
|-----------|------|---------|---------|
| 0.90 - 1.00 | 高 | 绿色边框 + "verified" | 正常进入 Commit Gate |
| 0.70 - 0.89 | 中 | 黄色边框 + "assumption_dependent" | 可点击展开假设详情 |
| 0.50 - 0.69 | 低 | 橙色边框 + "needs_clarification" | 点击触发澄清交互 |
| 0.00 - 0.49 | 不可信 | 红色边框 + "unverifiable" | 禁止 Commit，需修复 |

---

### 9.6 人机协作澄清

#### 9.6.1 澄清触发条件（Datalog 规则判定）

澄清是否必要由 Datalog 规则判定，**不**由 LLM 判断：

```prolog
// clarification_trigger.dl —— 澄清触发判定引擎

.decl needs_clarification(entity:symbol, reason:symbol, priority:symbol)

% 条件1: 存在 critical 级别的未澄清模糊性
needs_clarification(Entity, "critical_ambiguity_unresolved", "mandatory") :-
  ambiguity_detected(Entity, _, "critical", AmbId),
  ambiguity_status(AmbId, "unresolved").

% 条件2: 多世界结论不一致
needs_clarification(Entity, "divergent_world_conclusions", "mandatory") :-
  entity_has_worlds(Entity, W1),
  entity_has_worlds(Entity, W2),
  world_verification(W1, "pass"),
  world_verification(W2, "pass"),
  world_conclusion(W1, C1),
  world_conclusion(W2, C2),
  C1 != C2.

% 条件3: 关键假设置信度 < 0.5
needs_clarification(Entity, "critical_assumption_low_confidence", "mandatory") :-
  applied_assumption(Entity, Field, _, Conf, _, H),
  Conf < 0.50,
  field_is_critical(Field).

% 条件4: 信息缺失导致形式化阻塞（无默认值可用）
needs_clarification(Entity, "formalization_blocked", "mandatory") :-
  entity_has_missing_field(Entity, Field),
  not has_default_value(Field, _, _).

% 条件5: 多世界结论一致 → 自动处理（不需要澄清）
auto_resolvable(Entity, "worlds_converge") :-
  entity_has_worlds(Entity, W1),
  entity_has_worlds(Entity, W2),
  W1 != W2,
  world_verification(W1, "pass"),
  world_verification(W2, "pass"),
  world_conclusion(W1, C),
  world_conclusion(W2, C).  % 同一结论

% 条件6: 默认值可靠（confidence >= 0.8）且非 critical → 自动处理
auto_resolvable(Entity, "reliable_default") :-
  applied_assumption(Entity, _, _, Conf, _, H),
  Conf >= 0.80,
  not needs_clarification(Entity, "critical_ambiguity_unresolved", _).

% 优先级排序
clarification_priority("mandatory", 1).
clarification_priority("recommended", 2).
clarification_priority("optional", 3).
```

**澄清触发决策表**:

| 条件 | Datalog 判定 | 澄清必要性 | 系统行为 |
|------|-------------|-----------|---------|
| 存在未澄清 critical 模糊 | `needs_clarification(_, "critical_ambiguity_unresolved", "mandatory")` | **必须澄清** | 阻塞 Commit，向用户发起澄清请求 |
| 多世界结论不一致 | `needs_clarification(_, "divergent_world_conclusions", "mandatory")` | **必须澄清** | 展示所有结论差异，请求用户选择解释 |
| 关键假设 confidence < 0.5 | `needs_clarification(_, "critical_assumption_low_confidence", "mandatory")` | **必须澄清** | 向用户确认该假设 |
| 形式化阻塞且无默认值 | `needs_clarification(_, "formalization_blocked", "mandatory")` | **必须澄清** | 请求用户提供缺失信息 |
| 多世界结论一致 | `auto_resolvable(_, "worlds_converge")` | **自动处理** | 不打扰用户，使用默认值+标注假设 |
| 高置信度默认值可用 | `auto_resolvable(_, "reliable_default")` | **自动处理** | 使用默认值，置信度透明 |

#### 9.6.2 澄清交互设计

**轻度澄清（Inline Clarification）**:

```yaml
# inline_clarification.yaml —— 轻度澄清交互
ui_spec:
  trigger: "1-2 个 minor/major 级别假设需澄清"
  layout: "嵌入任务卡片底部，不跳转页面"
  
  components:
    - type: "assumption_chip_group"
      label: "请确认以下假设："
      chips:
        - assumption_id: "H-DOM-wash_service_type-vehicle_001"
          text: "洗车 = 工作人员代洗"
          confidence: 0.80
          options:
            - label: "确认"
              action: "confirm_assumption"
            - label: "改为自助"
              action: "override_assumption"
              override_value: "self_service"
            - label: "不确定"
              action: "keep_assumption"
        
        - assumption_id: "H-UNIV-distance_type-vehicle_001"
          text: "50米 = 步行距离"
          confidence: 0.60
          options:
            - label: "步行距离"
              action: "confirm_assumption"
            - label: "直线距离"
              action: "override_assumption"
              override_value: "straight"
            - label: "开车距离"
              action: "override_assumption"
              override_value: "driving"
  
  actions:
    confirm_all: "用户确认所有假设 → 假设 confidence → 1.0, source → user_clarified"
    modify_any: "用户修改任一假设 → 重新生成世界 → 重新验证"
```

**深度澄清（Expanded Dialog Mode）**:

```yaml
# deep_clarification.yaml —— 深度澄清交互
trigger: "critical 模糊或多世界结论不一致"
flow:
  step_1:
    system_message:
      zh: "您的目标'{interpreted_goal}'在两种理解下会得到不同结论，需要您确认："
      en: "Your goal '{interpreted_goal}' leads to different conclusions under two interpretations. Please clarify:"
    
  step_2:
    present_worlds:
      format: "side_by_side_comparison"
      world_1:
        description: "理解A：{W1.description}"
        conclusion: "推荐：{W1.conclusion}"
        reason: "{W1.reasoning_chain}"
      world_2:
        description: "理解B：{W2.description}"
        conclusion: "推荐：{W2.conclusion}"
        reason: "{W2.reasoning_chain}"
    
  step_3:
    user_selection:
      options:
        - label: "理解A正确"
          action: "select_world_W1"
        - label: "理解B正确"
          action: "select_world_W2"
        - label: "都不对，我需要重新描述"
          action: "restart_with_rephrase"
    
  step_4:
    on_selection:
      - "清除未选择的世界"
      - "被选择世界的 confidence → 1.0"
      - "触发 Truth Maintenance 更新"
      - "重新运行验证管线"
      - "更新任务卡片状态"
```

#### 9.6.3 澄清结果的传播与重新验证

用户澄清后的处理流程：

```text
用户澄清输入
    │
    ▼
┌─────────────────────────────────────┐
│ 1. 解析澄清回答                      │
│    - 确认假设 → confidence = 1.0     │
│    - 修改假设 → 更新 assumed_value   │
│    - 提供新信息 → 添加新事实          │
│    - 重新描述 → 重启整个管线          │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 2. 更新假设数据库（Datalog 事实更新） │
│    - UPDATE assumption_status         │
│    - SET confidence = 1.0             │
│    - SET source = 'user_clarified'    │
│    - SET invalidated_by = NULL        │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 3. TMS 传播                          │
│    - 查询所有 assumes(A, H)          │
│    - 若 A 为 stale → 重新标记 pending │
│    - 递归传播 derived_assertion      │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 4. 重新验证                          │
│    - 清除多世界状态（已确定唯一解释）  │
│    - 重新运行 Layer 1 Datalog         │
│    - 异步启动 Layer 2/3               │
│    - 更新 validation_cache            │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 5. 事件日志                          │
│    - event_type: "assumption_clarified"│
│    - payload: {assumption_id,         │
│               old_confidence,         │
│               new_confidence,         │
│               clarification_type}     │
└─────────────────────────────────────┘
```

**Datalog 澄清更新规则**:
```prolog
// clarification_update.dl —— 澄清结果处理

.decl user_clarification(assumption_id:symbol, action:symbol, new_value:symbol)
.decl updated_assumption(assumption_id:symbol, new_confidence:float, new_source:symbol)

% 用户确认假设
updated_assumption(H, 1.0, "user_clarified") :-
  user_clarification(H, "confirm", _).

% 用户修改假设值
updated_assumption(H, 1.0, "user_override") :-
  user_clarification(H, "override", NewVal).

% 重新验证触发：假设被更新后，依赖断言需重新验证
needs_revalidation(A) :-
  updated_assumption(H, _, _),
  assumes(A, H).

needs_revalidation(D) :-
  needs_revalidation(A),
  derived_assertion(D, A).
```

---

### 9.7 在 LKB 架构中的集成

#### 9.7.1 模糊处理层的插入位置

模糊处理层插入在 **LLM 翻译层** 与 **Canonical IR 生成** 之间：

```text
原始管线（第13章）：
  NL 输入 → LLM 翻译 → Canonical IR → Compiler → Solver 验证 → Commit Gate

新增模糊处理层后的管线：
  NL 输入 ──→ [模糊性检测层] ──┬──→ 无模糊 ──→ LLM 翻译 ──→ Canonical IR ──→ ...
              │                │
              │                └──→ 有模糊 ──→ [世界生成器 (ASP)]
              │                         │
              │                    ┌────┴────┐
              │                    ▼         ▼
              │                  W_1       W_2       W_n
              │                    │         │         │
              │                    └────┬────┘
              │                         ▼
              │              [假设填充器 (Datalog)]
              │                         │
              │                    ┌────┴────┐
              │                    ▼         ▼
              │              [独立验证管线 × n]
              │                    │
              │                    ▼
              │           [结果聚合器 (Datalog)]
              │                    │
              │         ┌─────────┴─────────┐
              │         ▼                   ▼
              │    结论一致             结论不一致
              │    (unanimous_pass)    (divergent/partial)
              │         │                   │
              │         ▼                   ▼
              │    继续标准管线         触发澄清交互
              │    → Commit Gate       → 用户选择 → 重新验证
              │
              └──→ [事件日志记录所有步骤]
```

#### 9.7.2 数据流图

```yaml
# fuzzy_layer_dataflow.yaml —— 模糊处理层数据流
components:
  AmbiguityDetector:
    input: ["tokenized_nl", "context_facts", "pattern_library"]
    output: ["ambiguity_report"]
    solver: "Datalog (Soufflé)"
    fallback: "LLM Self-Critique"

  WorldGenerator:
    input: ["ambiguity_report", "domain_defaults"]
    output: ["world_set: Set<World>"]
    solver: "ASP (clingo)"
    fallback: "枚举+剪枝 (Python)"

  AssumptionFiller:
    input: ["world_set", "default_knowledge_base", "user_profile"]
    output: ["filled_world_set: Set<World_with_Assumptions>"]
    solver: "Datalog (Soufflé)"
    fallback: "无（Datalog 规则完备）"

  MultiWorldValidator:
    input: ["filled_world_set"]
    output: ["verification_results: Map<WorldId, ValidationResult>"]
    solver: "Datalog + Z3 + ASP（每个世界独立）"
    fallback: "无"

  ResultAggregator:
    input: ["verification_results"]
    output: ["aggregation_decision"]
    solver: "Datalog (Soufflé)"
    fallback: "无（规则完备）"

  ClarificationTrigger:
    input: ["aggregation_decision", "assumption_set"]
    output: ["clarification_request (optional)"]
    solver: "Datalog (Soufflé)"
    fallback: "无（规则完备）"

data_stores:
  fuzzy_patterns_library:
    type: "YAML file + Datalog facts"
    path: "config/fuzzy_patterns.yaml"
    hot_reload: true

  default_knowledge_base:
    type: "Datalog facts + PostgreSQL table"
    table: "default_assumptions"
    columns: [domain, field, default_value, confidence, rationale]

  assumption_index:
    type: "PostgreSQL表"
    table: "assumption_index"
    purpose: "Truth Maintenance 反向索引"
    columns: [hypothesis_id, dependent_assertion_id, dependency_type]
```

#### 9.7.3 与现有模块的兼容性矩阵

| 现有模块 | 兼容性 | 交互方式 | 影响说明 |
|---------|--------|---------|---------|
| **LLM 翻译层** | 增强 | 模糊层输出 → LLM 逐世界翻译 | LLM 每次只翻译一个确定的世界解释 |
| **Canonical IR** | 完全兼容 | 每个世界生成独立 IR | IR 结构不变，实例数变多 |
| **Compiler (Tier 1/2/3)** | 完全兼容 | 每个 IR 独立编译 | 编译次数 = 世界数量 |
| **Datalog 子系统** | 完全兼容 | 每个世界独立推导 | 性能影响：O(n_worlds) |
| **Z3 子系统** | 完全兼容 | 每个世界独立验证 | 性能影响：O(n_worlds) |
| **ASP/clingo** | 完全兼容 | 世界生成器本身使用 ASP | 重用现有 solver 封装 |
| **Commit Gate** | 增强 | 新增模糊性检查（9.3.4节） | 新增 `fuzzy_check` 模块 |
| **Truth Maintenance** | 完全兼容 | 假设是一等公民 | 复用现有 TMS 基础设施 |
| **event_log** | 完全兼容 | 模糊处理全过程记入日志 | 新增事件类型 |
| **验证缓存** | 增强 | 按 world_id 缓存验证结果 | 缓存 key 增加 world 维度 |
| **UI/UX** | 增强 | 新增模糊性面板、澄清交互 | 第15章 UI 需求需扩展 |

#### 9.7.4 新增 API 接口

```yaml
# fuzzy_api.yaml —— 模糊处理层新增 API
openapi: "3.0.0"
paths:
  /api/v1/fuzzy/detect:
    post:
      summary: "检测自然语言输入中的模糊性"
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [nl_text]
              properties:
                nl_text:
                  type: string
                context_facts:
                  type: array
                  items:
                    type: object
                    properties:
                      predicate: {type: string}
                      args: {type: array, items: {type: string}}
      responses:
        200:
          description: "模糊性检测报告"
          content:
            application/json:
              schema:
                type: object
                properties:
                  has_ambiguity:
                    type: boolean
                  ambiguity_points:
                    type: array
                    items:
                      type: object
                      properties:
                        point_id: {type: string}
                        phrase: {type: string}
                        category:
                          type: string
                          enum: [semantic_vagueness, informational_incompleteness, context_dependency, metaphor_idiom]
                        severity:
                          type: string
                          enum: [critical, major, minor, negligible]
                        interpretations:
                          type: array
                          items:
                            type: object
                            properties:
                              code: {type: string}
                              formalization: {type: string}
                              base_confidence: {type: number}
                  detection_method:
                    type: string
                    enum: [datalog_rule, asp_enum, llm_fallback]
                  execution_ms: {type: integer}

  /api/v1/fuzzy/worlds:
    post:
      summary: "生成所有合法的可能世界"
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [ambiguity_report]
              properties:
                ambiguity_report:
                  $ref: "#/paths/~1api~1v1~1fuzzy~1detect/responses/200/content/application~1json/schema"
                domain:
                  type: string
                  description: "领域标识，用于加载领域默认值"
      responses:
        200:
          description: "世界集合"
          content:
            application/json:
              schema:
                type: object
                properties:
                  worlds:
                    type: array
                    items:
                      type: object
                      properties:
                        world_id: {type: string}
                        interpretation:
                          type: object
                          description: "Canonical IR 预览"
                        confidence: {type: number}
                        assumptions:
                          type: array
                          items:
                            $ref: "#/components/schemas/Assumption"
                  total_worlds: {type: integer}
                  pruned_worlds:
                    type: integer
                    description: "被领域约束剪枝的不合法世界数"

  /api/v1/fuzzy/aggregate:
    post:
      summary: "聚合多世界验证结果"
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [world_results]
              properties:
                world_results:
                  type: array
                  items:
                    type: object
                    properties:
                      world_id: {type: string}
                      verification_status:
                        type: string
                        enum: [pass, fail, pending, timeout]
                      conclusion_hash: {type: string}
      responses:
        200:
          description: "聚合决策"
          content:
            application/json:
              schema:
                type: object
                properties:
                  strategy:
                    type: string
                    enum: [unanimous_pass, divergent_conclusions, partial_pass, unanimous_fail, incomplete]
                  action:
                    type: string
                    enum: [commit, request_clarification, reject, wait]
                  explanation:
                    type: object
                    properties:
                      zh: {type: string}
                      en: {type: string}

  /api/v1/fuzzy/clarify:
    post:
      summary: "提交用户澄清结果"
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [clarifications]
              properties:
                clarifications:
                  type: array
                  items:
                    type: object
                    properties:
                      assumption_id: {type: string}
                      action:
                        type: string
                        enum: [confirm, override, provide_info, rephrase]
                      new_value: {type: string}
      responses:
        200:
          description: "澄清处理结果"
          content:
            application/json:
              schema:
                type: object
                properties:
                  affected_assertions:
                    type: array
                    items: {type: string}
                  revalidation_required:
                    type: boolean
                  new_worlds_generated:
                    type: integer

event_types_added:
  - fuzzy_ambiguity_detected
  - fuzzy_world_generated
  - fuzzy_assumption_applied
  - fuzzy_clarification_requested
  - fuzzy_clarification_received
  - fuzzy_convergence_achieved
  - fuzzy_divergence_detected
```

---

### 9.8 形式化保证

#### 9.8.1 INV-FUZZY 不变量

```text
INV-FUZZY-1 (假设显式标注):
  ∀ a:Assertion . (∃ h:Assumption . Assumes(a,h) ∧ h.confidence < 1.0)
    → a.status = conditional ∧ a.derivation_note = "depends_on_assumptions"
  
  自然语言：任何带有未澄清假设的断言，其推导结论必须显式标注为
  "条件成立"，不得伪装为确定性结论。

INV-FUZZY-2 (Commit Gate 保守拒绝):
  ∀ t:Task . CommitGate(t) = Allowed
    → (∀ h ∈ Hypotheses(t) . h.confidence >= FUZZY_THRESHOLD_MINOR)
      ∧ (¬HasDivergentWorlds(t) ∨ UserSelectedWorld(t))
  
  自然语言：Commit Gate 对模糊断言的默认策略是"不确定 = 不通过"。
  任何置信度低于阈值或存在未消解多世界分歧的任务不得 Commit。

INV-FUZZY-3 (用户澄清最高优先级):
  ∀ h:Assumption . h.source = "user_clarified"
    → h.confidence = 1.0 ∧ (∀ h_default:Assumption . h_default.field = h.field
                                                      ∧ h_default.source ≠ "user_clarified"
                                                      → OverriddenBy(h, h_default))
  
  自然语言：用户澄清具有最高优先级，覆盖所有默认值和 LLM 推断。
  用户确认后的假设置信度为 1.0，且自动抑制同字段的其他默认假设。

INV-FUZZY-4 (多世界一致性要求):
  ∀ nl:NL_Assertion . |Worlds(nl)| > 1 ∧ CommitGate(Translate(nl)) = Allowed
    → (∀ w1, w2 ∈ Worlds(nl) . w1.verification = pass ∧ w2.verification = pass
          → w1.conclusion = w2.conclusion)
       ∨ UserSelectedSpecificWorld(nl)
  
  自然语言：多世界验证中，只有当所有通过验证的世界的结论一致时，
  才允许 Commit；否则必须等待用户选择特定世界。

INV-FUZZY-5 (全过程审计):
  ∀ e:fuzzy_processing_event . 
    ∃ log_entry:event_log . 
      log_entry.correlation_id = e.correlation_id
      ∧ log_entry.event_type ∈ {
          "fuzzy_ambiguity_detected",
          "fuzzy_world_generated", 
          "fuzzy_assumption_applied",
          "fuzzy_clarification_requested",
          "fuzzy_clarification_received",
          "fuzzy_convergence_achieved",
          "fuzzy_divergence_detected"
        }
  
  自然语言：模糊性处理的全过程——检测、世界生成、假设应用、
  澄清请求与响应、收敛/分歧判定——必须全部记入审计日志，
  确保事后可追溯、可复现。
```

#### 9.8.2 正确性保证矩阵

| 场景 | 系统行为 | 不变量保证 | 求解器验证 |
|------|---------|-----------|-----------|
| 用户输入语义模糊 | 检测 → 生成多世界 → 验证所有世界 | INV-FUZZY-1, INV-FUZZY-4 | Datalog + ASP + Z3 |
| 信息缺失 | 默认值填充 + 假设标注 | INV-FUZZY-1, INV-FUZZY-2 | Datalog |
| 多世界结论不一致 | 展示差异 + 请求澄清 | INV-FUZZY-4 | Datalog 聚合 |
| 用户澄清假设 | 更新假设 + TMS 传播 + 重新验证 | INV-FUZZY-3 | Datalog + Z3 |
| 假设后续被推翻 | TMS 传播 → 依赖结论 stale | INV-FUZZY-1, INV-FUZZY-5 | Datalog |
| Commit Gate 判定 | 模糊检查 → 保守拒绝 | INV-FUZZY-2 | Datalog |
| 审计审查 | 完整事件日志 | INV-FUZZY-5 | event_log 查询 |

#### 9.8.3 模糊处理层的故障模式与降级

| 故障场景 | 降级策略 | 保证级别 |
|---------|---------|---------|
| Datalog 引擎不可用 | 跳过模糊检测，LLM 翻译时增加自批判提示 | 部分保证（依赖 LLM） |
| ASP/clingo 不可用 | 使用 Python 枚举+剪枝替代世界生成 | 保证正确，性能降级 |
| 默认值知识库缺失 | 所有缺失信息标记为需澄清 | 保守策略（宁澄清不猜测） |
| LLM fallback 超时 | 拒绝形式化，返回 nl-only 草稿 | 不生成不可靠的形式化 |
| Z3 置信度传播超时 | 使用确定性公式计算（无 Z3 验证） | 数值正确，缺少约束验证 |
| 用户不响应澄清请求 | 使用最高置信度假设继续，标注为 pending_clarification | 次优但安全 |

---

> **第9章总结**: 模糊输入处理子系统通过"符号检测优先、多世界验证、假设显式管理、人机协作澄清"的四步闭环，将自然语言输入的固有模糊性从"系统漏洞"转化为"结构化交互机会"。LLM 仅承担最小必要的自然语言理解职责（习惯用法识别、澄清提示生成）；所有结构化推理——模糊性检测、世界生成、假设管理、置信度传播、澄清触发——均由 Datalog / ASP / Z3 符号系统完成，确保模糊性处理本身具备与 LKB 核心验证管线同等的形式化保证水平。

---

## 10. 推理与验证子系统

### 10.1 分层验证架构（核心设计）

基于分析结论，将验证架构分为三个 Layer，解决原文档"多 solver 同时调用过度"问题：

```
┌─────────────────────────────────────────────────────────────────┐
│                        分层验证架构                               │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: 同步快速验证  (< 200ms)                                  │
│   - Datalog 引擎（依赖传播、阻塞推导、循环检测）                     │
│   - 轻量 SMT 检查（状态互斥、基本不变量）                          │
│   - Commit Gate 决策依赖 Layer 1 结果                              │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: 异步深度验证  (< 5s)                                     │
│   - Z3 完整不变量验证（含反例生成）                                │
│   - ASP/clingo 冲突检测与多解枚举                                  │
│   - 结果用于报告、审计和深度验证，不阻塞 commit                     │
├─────────────────────────────────────────────────────────────────┤
│ Layer 3: 完全异步验证  (< 60s, 可更长)                             │
│   - 定理证明器（Vampire / Prover9）                               │
│   - PDDL 计划验证（如适用）                                        │
│   - Lean 协议级形式验证（如适用）                                  │
│   - 结果仅用于审计和报告，不阻塞任何操作                            │
└─────────────────────────────────────────────────────────────────┘
```

**Layer 1 提前终止机制**: 若 Layer 1 的 Datalog 推导发现 `Blocked(t)` 为 true，则立即返回失败，无需调用 Layer 2/3。这是"快速失败"（fail-fast）原则的实现。

**Solver 结果聚合策略**（保守拒绝）:
```python
def aggregate_results(layer_results: dict) -> ValidationResult:
    """
    保守拒绝策略：
    - 任一 solver 报告 fail → 整体 fail
    - 任一 solver 报告 unknown/timeout/error → 整体 unknown（默认不通过）
    - 所有 solver 报告 pass → 整体 pass
    - 结果不一致时触发审计告警
    """
    results = [r.result for r in layer_results.values()]
    
    if any(r == "fail" for r in results):
        return ValidationResult.FAIL
    if any(r in ("unknown", "timeout", "error") for r in results):
        return ValidationResult.UNKNOWN  # 默认不通过
    if all(r == "pass" for r in results):
        return ValidationResult.PASS
    
    # 结果不一致 → 触发审计告警
    trigger_audit_alert("solver_result_mismatch", layer_results)
    return ValidationResult.UNKNOWN
```

**Solver 优先级**（当结果冲突时）: Datalog（确定性） > Z3（半确定性） > ASP（启发式） > 定理证明器（完备但慢）

### 10.2 Datalog 子系统（依赖传播、阻塞推导）

**用途**: 任务依赖传播、阻塞状态推导、可达性分析、循环依赖检测、Ready/Blocked/CannotMove 推导。

**技术选型**: Soufflé Datalog（高性能 Datalog 引擎，支持 LLVM 编译）。MVP 阶段使用嵌入模式（embedded library mode）而非命令行调用，减少冷启动开销。

**核心规则集**:
```prolog
// facts.dl —— Datalog 规则文件
.decl task(t:symbol)
.decl requires(a:symbol, b:symbol)
.decl blocks(a:symbol, b:symbol)
.decl done(t:symbol)
.decl doing(t:symbol)
.decl ready(t:symbol)
.decl blocked(t:symbol)
.decl can_move_to(t:symbol, s:symbol)
.decl cannot_move_to(t:symbol, s:symbol)
.decl cycle_detected(a:symbol, b:symbol)

// RT-001: 前置条件未满足则阻塞（修正版）
blocked(b) :- requires(a,b), !done(a), !done(b), !doing(b).

// RT-002: 被阻塞任务不能进入 Doing
cannot_move_to(t, "Doing") :- blocked(t).

// Ready 推导: 未被阻塞的任务是 Ready
ready(t) :- task(t), !blocked(t), !done(t), !doing(t).

// 循环依赖检测（新增）
cycle_detected(a, b) :- requires(a, b).
cycle_detected(a, c) :- requires(a, b), cycle_detected(b, c).
cycle_detected(a, a) :- requires(a, b), cycle_detected(b, a).

// 输出
.output blocked
.output ready
.output cannot_move_to
.output cycle_detected
```

**性能目标**: 1,000 个任务 < 200ms（Layer 1 同步响应）。

### 10.3 ASP/clingo 子系统（多解枚举、冲突处理）

**用途**: 多计划选择、冲突求解、默认推理、在多个候选任务中选择满足约束的执行集合。

**技术选型**: clingo v5.8.0（Potassco 项目，PyPI CFFI bindings）。

**核心规则集**:
```prolog
% clingo 规则文件
% 任务和约束定义
task(t_auth; t_settings; t_api). % 聚合语法：定义多个任务
requires(t_auth, t_settings).

% 选择执行的任务子集
{ selected(T) } :- task(T).

% 约束：如果选择了 b，则必须完成 a
:- selected(B), requires(A, B), not done(A).

% 冲突检测：两个冲突的任务不能同时被选择
:- selected(T1), selected(T2), contradicts(T1, T2).

% 默认推理：优先选择更多任务
#maximize { 1,T : selected(T) }.

#show selected/1.
```

**Python 调用示例**:
```python
import clingo

def solve_with_clingo(rules: str) -> list:
    """调用 clingo 求解 ASP 程序，返回所有稳定模型。"""
    ctl = clingo.Control(arguments=["--models=0"])  # 枚举所有模型
    ctl.add("base", [], rules)
    ctl.ground([("base", [])])
    
    models = []
    with ctl.solve(yield_=True) as handle:
        for model in handle:
            models.append(model.symbols(shown=True))
    return models
```

### 10.4 SMT/Z3 子系统（不变量验证、反例生成）

**用途**: 全局不变量验证、状态互斥检查、资源约束、反例生成。

**技术选型**: Z3 v4.16.0（Microsoft Research，Python API 极成熟）。

**核心验证脚本**:
```python
from z3 import *

def verify_state_invariants(tasks: list, assertions: list) -> dict:
    """
    验证任务状态不变量。
    返回: {"result": "pass"|"fail", "counterexample": ...}
    """
    solver = Solver()
    Task = DeclareSort('Task')
    
    # 定义状态谓词
    Ready = Function('Ready', Task, BoolSort())
    Doing = Function('Doing', Task, BoolSort())
    Blocked = Function('Blocked', Task, BoolSort())
    Done = Function('Done', Task, BoolSort())
    
    # 排他性约束（EXCL-1 到 EXCL-4）
    t = Const('t', Task)
    solver.add(ForAll([t], Implies(Blocked(t), 
        Not(Or(Ready(t), Doing(t), Done(t))))))
    solver.add(ForAll([t], Implies(Doing(t), 
        Not(Or(Ready(t), Blocked(t), Done(t))))))
    solver.add(ForAll([t], Implies(Done(t), 
        Not(Or(Ready(t), Doing(t), Blocked(t))))))
    solver.add(ForAll([t], Implies(Ready(t), 
        Not(Or(Blocked(t), Doing(t), Done(t))))))
    
    # 检查可满足性
    if solver.check() == sat:
        return {"result": "pass"}
    else:
        return {
            "result": "fail",
            "counterexample": solver.model() if solver.check() == unsat else None,
            "unsat_core": solver.unsat_core() if solver.check() == unsat else None
        }
```

### 10.5 定理证明子系统（Vampire + Prover9 LADR-2026）

**技术选型**: 
- **主证明器**: Vampire（CASC-30 全胜，2025，BSD 许可证）
- **副证明器**: Prover9 LADR-2026（新增原生 TPTP 支持）
- **反例查找**: Mace4（有限模型构建器）

**分工策略**:

| 问题类型 | 主求解器 | 次求解器 | 反例查找 |
|---------|---------|---------|---------|
| 纯 FOL 定理证明 | Vampire | Prover9 | Mace4 |
| TPTP 兼容性问题 | Prover9 LADR-2026 | Vampire | Mace4 |
| 含算术/理论的约束 | Z3 | — | Z3 model |

**Python 子进程调用封装**:
```python
import subprocess
import tempfile
import os

def run_vampire(tptp_formula: str, timeout: int = 30) -> dict:
    """
    调用 Vampire 定理证明器。
    输入: TPTP FOF 格式的公式
    返回: {"result": "Theorem"|"CounterSatisfiable"|"Timeout", ...}
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.p', delete=False) as f:
        f.write(tptp_formula)
        temp_path = f.name
    
    try:
        result = subprocess.run(
            ['vampire', '--mode', 'casc', '--time_limit', str(timeout), temp_path],
            capture_output=True, text=True, timeout=timeout + 5
        )
        
        # 解析 SZS 状态行
        szs_status = parse_szs_status(result.stdout)
        return {
            "result": szs_status,  # "Theorem", "CounterSatisfiable", "Timeout", etc.
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.returncode
        }
    finally:
        os.unlink(temp_path)
```

### 10.6 因果验证层（CAP 语义兼容的轻量服务）

**设计决策**: CAP 协议确实存在（github.com/CausalAgentProtocol/cap-example），0 stars/0 forks，纯内存合成图，教学级实现。本系统**复用其 verb 语义设计**，而非依赖其实现。

**CAP 兼容的轻量因果服务接口**:
```yaml
# 自建轻量因果图服务，暴露 CAP-compatible 接口
endpoints:
  /causal/capabilities:
    method: POST
    body: { "verb": "meta.capabilities" }
    response: { "verbs": ["graph.neighbors", "intervene.do", "observe.predict"] }
    
  /causal/neighbors:
    method: POST
    body:
      verb: "graph.neighbors"
      node: "T_schema"
      scope: "children"        # parents | children | ancestors | descendants
    response:
      neighbors: ["T_backend_ready", "T_api_contract"]
      
  /causal/intervene:
    method: POST
    body:
      verb: "intervene.do"
      treatment_node: "T_auth"
      treatment_value: "completed"
      outcome_node: "T_settings"
    response:
      causal_effect: 0.81      # 标准化因果效应量
      is_significant: true     # >= 0.7 为显著
      mechanism: "direct"      # direct | indirect | null
```

**因果验证判定逻辑**:
1. Agent 提出"任务 A 完成会影响任务 B"的假设
2. 因果服务在维护的因果图上执行干预查询
3. 若 `causal_effect >= 0.7` 且 `is_significant = true` → 通过
4. 若 `causal_effect < 0.7` 或 `is_significant = false` → 拒绝，返回 `reject: not causal`

**双层验证顺序**（基于"先符号后因果"的快速失败原则）:
```
Agent 提出依赖边
    │
    ▼
Layer 1: 符号门（先执行，更便宜）
  - Datalog 结构检查
  - Z3 逻辑一致性
    │ 通过
    ▼
Layer 2: 因果门（后执行，可能依赖外部服务）
  - intervene.do 查询
  - 因果效应显著性检查
    │ 通过
    ▼
写入任务图（带 causal_weight + verification status）
```

**causal_weight 计算方法**:
```yaml
causal_weight:
  definition: "标准化因果效应量，取值范围 [0.0, 1.0]"
  calculation: |
    基于 do-calculus（Pearl）的干预效应强度标准化：
    causal_weight = |E[Y | do(T=1)] - E[Y | do(T=0)]| / max_observable_effect
  threshold:
    significant: 0.7     # >= 0.7 视为显著因果效应
    moderate: 0.4        # 0.4-0.7 需人工审查
    weak: 0.4            # < 0.4 视为非因果
  source: "自动计算（因果推断引擎）或人工标注"
```

### 10.7 Solver 结果聚合策略

详见 9.1 节的保守拒绝策略代码实现。补充说明：

**结果不一致处理流程**:
```
Datalog: pass
Z3:      fail
ASP:     pass

→ 整体结果: fail（保守拒绝）
→ 触发审计告警: "solver_result_mismatch"
→ 记录详细日志供人工审查
→ 不阻塞 commit（已经 fail）
```

```
Datalog: pass
Z3:      unknown
ASP:     pass

→ 整体结果: unknown（默认不通过）
→ 触发审计提示: "z3_unknown_needs_review"
→ 可人工覆盖为 pass（需审计记录）
```

---

## 11. Agent 操作协议

### 11.1 设计原则（propose-only）

**核心原则**: Agent 只能提出候选操作，不能直接修改最终状态。

**禁止**:
```python
# 错误：Agent 直接修改状态
agent.move_task_to_doing(task_id="T_settings")  # 绝对禁止！
```

**正确流程**:
```python
# 正确：Agent propose → 系统 validate → Commit Gate commit
transition = agent.proposeTransition(
    task_id="T_settings",
    from_status="Ready",
    to_status="Doing",
    reason_assertions=["A-1024", "A-1025"]
)
# 系统自动调用 Layer 1/2/3 验证
# Commit Gate 根据验证结果决定 commit 或 deny
```

### 11.2 工具接口（完整 API 定义）

```typescript
// LogicalBoardTools —— Agent 可调用的完整工具接口
interface LogicalBoardTools {
  // ── 任务操作 ──
  proposeTask(input: ProposeTaskInput): DraftTask;
  getTask(taskId: string): Task;
  listTasks(filter?: TaskFilter): Task[];
  
  // ── 断言操作 ──
  proposeAssertion(input: ProposeAssertionInput): DraftAssertion;
  compileAssertion(assertionId: string): CompileResult;
  validateAssertion(assertionId: string): ValidationResult;
  getAssertion(assertionId: string): Assertion;
  
  // ── 迁移操作 ──
  proposeTransition(input: ProposeTransitionInput): DraftTransition;
  validateTransition(transitionId: string): ValidationResult;
  commitTransition(transitionId: string): CommitResult;
  revokeTransition(transitionId: string): RevokeResult;
  
  // ── 查询与解释 ──
  getProofTrace(validationRunId: string): ProofTrace;
  explainFailure(validationRunId: string): HumanExplanation;
  getBlockedReason(taskId: string): BlockedExplanation;
  getImpactGraph(assertionId: string): ImpactGraph;
  
  // ── 批量操作 ──
  batchProposeTasks(inputs: ProposeTaskInput[]): DraftTask[];
  batchValidateAssertions(assertionIds: string[]): ValidationResult[];
}

// 输入类型定义
interface ProposeTaskInput {
  title: string;
  goal: string;
  priority?: "low" | "medium" | "high" | "critical";
  owner?: string;
  assertions?: ProposeAssertionInput[];
  dependencies?: string[];           // 依赖的任务 ID
  acceptance_criteria?: string[];
  evidence?: EvidenceInput[];
  assumptions?: string[];
}

interface ProposeAssertionInput {
  kind: AssertionKind;
  nl_assertion: string;              // 自然语言断言原文
  dsl?: string;                      // 可选：LKB-DSL 代码
  canonical_ir?: CanonicalIR;        // 可选：直接提供 Canonical IR
  task_id?: string;                  // 为 NULL 表示全局规则
  assumption_set?: string[];
  evidence?: string[];
}

interface ProposeTransitionInput {
  task_id: string;
  from_status: StatusEnum;
  to_status: StatusEnum;
  reason_assertions: string[];       // 支撑此迁移的断言 ID 列表
  requested_by: string;
}

// 返回类型定义
interface DraftTask {
  task_id: string;
  status: "Draft";
  next_required_action: "validate_assertions";
  created_at: string;
}

interface CompileResult {
  assertion_id: string;
  tier1_targets: CompiledTarget[];   // Datalog + SMT-LIB
  tier2_targets: CompiledTarget[];   // ASP + Lean
  tier3_targets: CompiledTarget[];   // PDDL + Argdown
  warnings: CompileWarning[];
}

interface ValidationResult {
  assertion_id?: string;
  transition_id?: string;
  overall_result: "pass" | "fail" | "unknown" | "timeout" | "error";
  layer_results: {
    layer1?: LayerResult;            // Datalog
    layer2?: LayerResult;            // Z3 + ASP
    layer3?: LayerResult;            // Vampire + PDDL
  };
  human_message: LocalizedText;
  repair_suggestions?: RepairSuggestion[];
}

interface CommitResult {
  transition_id: string;
  status: "committed" | "denied";
  reason?: string;
  human_message?: LocalizedText;
  validation_runs?: string[];
}
```

### 11.3 简化状态机（Draft -> Verified -> Committed）

基于分析结论，将原文档 7 步状态机简化为 3 步持久化状态，验证步骤作为内部子状态：

```
┌─────────┐     ┌───────────┐     ┌───────────┐
│  Draft  │ --> │  Verified │ --> │ Committed │
└─────────┘     └───────────┘     └───────────┘
     │                │                  │
     │                │                  │
     ▼                ▼                  ▼
  内部子状态:       内部子状态:        最终状态:
  - parsing        - layer1_pass     已提交到看板
  - type_checking  - layer2_running  不可撤销（需新 transition）
  - compiling      - layer2_pass
  - layer1_running - layer3_running
  - layer1_pass    - layer3_pass
  - all_layers_pass
```

**简化 rationale**: Parsed/TypeChecked/Compiled 是短暂计算步骤，不需要持久化状态。HumanApproved 是 Commit Gate 的策略条件而非状态机状态。

**新增关键状态**:
- `Stale`: 假设失效后需要重新验证
- `Invalidated`: 被推翻的状态
- `Error`: 验证失败（可修复后重试）

### 11.4 Agent 写入约束

**Agent 创建任务时必须提供**:
- task title（必需）
- task kind（必需）
- goal（必需）
- at least one assertion（必需，可为 `no_dependency` 显式断言）
- dependencies or explicit no-dependency assertion（必需）
- acceptance criteria（必需）
- evidence or assumption（必需）
- proposed validation targets（必需，指定哪些 solver 应验证此任务）

**Agent 请求状态迁移时必须提供**:
- transition reason（必需）
- supporting assertions（必需，至少一条）
- expected solver targets（必需）
- fallback plan if denied（可选但推荐）

### 11.5 Commit Gate 规则

Commit Gate 是状态从 Verified 到 Committed 的唯一入口，基于 Layer 1 验证结果做决策。

**默认规则**（任务从 Ready 到 Doing）:
```python
def commit_gate_ready_to_doing(task: Task, transition: Transition) -> CommitDecision:
    """
    Commit Gate: Ready -> Doing
    所有条件必须同时满足。
    """
    checks = {
        "ready": task.status == "Ready",
        "not_blocked": not is_blocked(task.id),
        "no_contradiction": not has_active_contradiction(task.id),
        "assertions_verified": all_assertions_verified(task.id),
        "validation_bound": transition_has_validation_runs(transition.id),
        "hash_consistent": validation_input_hash_matches_current(transition.id),
    }
    
    if all(checks.values()):
        return CommitDecision(commit=True, checks=checks)
    else:
        failed_checks = {k: v for k, v in checks.items() if not v}
        return CommitDecision(
            commit=False, 
            checks=checks,
            reason=f"Commit Gate checks failed: {list(failed_checks.keys())}",
            human_message=generate_failure_explanation(failed_checks)
        )
```

**强制拒绝条件**（任一满足则直接拒绝）:
1. 任务存在未完成前置条件
2. 任务被 Blocked
3. 任务存在活跃冲突断言
4. 任务依赖的假设已失效
5. Layer 1 solver 返回 fail / unknown / timeout
6. Transition 没有绑定 validation_run（通过关联表检查）
7. Validation_run 的 input hash 与当前 facts snapshot 不一致
8. 任务 Done 但没有验收证明



---

## 12. 假设与 Truth Maintenance

### 12.1 Assertion Provenance

每条断言必须记录完整的来源信息，用于 Truth Maintenance（真值维护）和审计追踪。

**Provenance 结构**:
```yaml
provenance:
  # 创建信息
  created_by: "agent-frontend"          # 创建者（Agent ID 或用户 ID）
  created_at: "2026-07-04T10:00:00Z"
  
  # 来源类型
  source_type: "llm_translation"        # 枚举见下表
  source_detail:
    model: "claude-sonnet-4"            # 固定模型版本
    prompt_version: "v2.1"
    temperature: 0.0                    # 确定性翻译
  
  # 翻译置信度（translation_confidence 计算方法）
  translation_confidence:
    value: 0.92
    method: "self_consistency_voting"   # 计算方法见下方
    sample_count: 5                     # 5 次独立采样
    agreement_rate: 0.92                # 5 次中 4 次结果一致
  
  # 输入来源
  source_nl_hash: "sha256:abc123..."    # 源自然语言文本的 hash
  source_assertion_id: null             # 若非翻译，记录源断言
  
  # 修改历史
  modified_by: []
  
  # 审计
  audit_trail:
    - action: "created"
      actor: "agent-frontend"
      timestamp: "2026-07-04T10:00:00Z"
    - action: "validated"
      actor: "system"
      timestamp: "2026-07-04T10:05:00Z"
      validation_run_id: "V-2026-0001"
```

**source_type 枚举**:

| 来源类型 | 说明 | 置信度策略 |
|---------|------|-----------|
| `llm_translation` | LLM 从自然语言翻译 | self_consistency_voting |
| `human_input` | 人类直接输入 | 1.0（人类为黄金标准） |
| `solver_derived` | 求解器推导 | 1.0（求解器输出确定性） |
| `imported` | 从外部系统导入 | 依赖外部系统可信度 |
| `template_instantiation` | 规则模板实例化 | 1.0（模板已验证） |

**translation_confidence 计算方法**:

推荐采用 **Self-Consistency Voting**（多次采样一致性投票）：

```python
def calculate_translation_confidence(
    nl_text: str,
    model: str,
    n_samples: int = 5
) -> float:
    """
    通过 n 次独立采样计算翻译置信度。
    策略：
    1. 对同一自然语言文本进行 n 次独立 LLM 调用（temperature > 0）
    2. 将每次输出编译为 Canonical IR
    3. 比较 IR 的结构等价性（忽略变量名差异）
    4. 置信度 = 一致结果数 / n
    
    阈值：
    - >= 0.9: 高置信度，自动通过
    - 0.7-0.9: 中置信度，需人工抽样审查
    - < 0.7: 低置信度，必须人工审查
    """
    samples = [translate_to_ir(nl_text, model, temperature=0.7) 
               for _ in range(n_samples)]
    
    # 结构等价性比较（规范化变量名后比较）
    canonical_forms = [canonicalize_ir(s) for s in samples]
    most_common = Counter(canonical_forms).most_common(1)[0]
    agreement_count = most_common[1]
    
    return agreement_count / n_samples
```

**置信度阈值与处理策略**:

| 置信度范围 | 处理策略 | 人工介入 |
|-----------|---------|---------|
| 0.90 - 1.00 | 自动通过，进入正常验证流程 | 不需要 |
| 0.70 - 0.89 | 标记为 `needs_human_review`，进入验证流程但需抽样审查 | 建议 |
| 0.00 - 0.69 | 标记为 `low_confidence`，暂停验证流程，必须人工审查 | 强制 |


**假设来源类型扩展**（模糊输入处理体系新增）：

| 来源类型 | 说明 | 置信度策略 |
|---------|------|-----------|
| `default_kb` | 默认值知识库填充 | 按知识库条目标注的 confidence |
| `domain_default` | 领域特定默认值 | 按领域知识库 confidence |
| `context_default` | 上下文敏感默认值 | 按上下文匹配度 confidence |
| `user_clarified` | 用户澄清后的值 | 1.0（用户为黄金标准） |
| `multi_world_inference` | 多世界验证推断 | 按世界 confidence 聚合 |

**默认值知识库引用规范**:
```yaml
assumption:
  assumption_id: "H-001"
  field: "距离类型"
  assumed_value: "步行距离"
  confidence: 0.6
  source: "default_kb"
  source_ref: "default:distance_type:v1.0"    # 知识库条目ID+版本
  needs_clarification: true
  clarification_prompt: "您说的50米是指直线距离还是步行距离？"
```

`source_ref` 格式: `{kb_type}:{entry_id}:{version}`


### 12.2 假设失效传播流程

当某个假设被推翻时，系统必须自动传播影响到所有依赖该假设的断言和派生事实。

**假设失效传播流程**:

```
1. 假设 H 被标记 invalid
   │
   ▼
2. 系统查询 assumption_index（假设→断言的反向索引）
   找到所有 Assumes(a, H) 的断言 a
   │
   ▼
3. 将相关断言标记 stale
   - status: verified → stale
   - valid_until: 当前时间戳
   - invalidated_reason: "依赖假设 {H} 已失效"
   │
   ▼
4. 递归传播：查询 derived_from 关系
   找到所有 DerivedFrom(d, a) 的派生断言 d
   将 d 也标记 stale
   （递归直到没有新的派生断言受影响）
   │
   ▼
5. 任务状态更新
   对于每个受影响的任务 t：
   - 如果 t 的 Ready/Doing 状态依赖 stale 断言
     → 重新运行 Layer 1 Datalog 推导
   - 如果推导结果变化（如 Ready → Blocked）
     → 更新任务状态
     → 记录状态变更事件到 event_log
   │
   ▼
6. UI 展示影响范围
   - 受影响假设: H
   - 受影响断言: [A-001, A-002, A-003, ...]
   - 受影响派生事实: [D-001, D-002, ...]
   - 受影响任务: [T-001, T-002, ...]
   - 建议操作: 重新验证 / 修改假设 / 修改断言
   │
   ▼
7. 通知
   - 通知创建了相关断言的 Agent
   - 在看板 UI 上高亮受影响任务
   - 可选：发送告警给项目负责人
```

**TMS 数据结构**:

```yaml
# 假设实体
hypothesis:
  id: "H-001"
  description: "网络服务在任务执行期间可用"
  status: invalid                      # {active, invalidated, superseded}
  invalidated_by: "A-EVENT-001"
  invalidated_at: "2026-07-04T12:00:00Z"
  invalidated_reason: "网络分区事件检测到"

# 假设→断言反向索引（用于快速传播）
assumption_index:
  hypothesis_id: "H-001"
  dependent_assertions:
    - assertion_id: "A-001"
      dependency_type: "direct"        # direct | transitive
    - assertion_id: "A-002"
      dependency_type: "transitive"
  updated_at: "2026-07-04T12:00:00Z"
```

---



#### 12.2.1 假设被用户澄清后的传播

当用户对假设提供澄清时，系统执行以下传播流程：

```
1. 用户澄清假设 H
   -> H.assumed_value = 用户确认值
   -> H.confidence = 1.0, H.source = user_clarified
   -> H.clarification_status = resolved
   |
2. 查询 assumption_index，找到所有 Assumes(a, H)
   -> 每个断言 a: verified -> stale（触发重新验证）
   |
3. 如果 a 是 multi_world_assertion:
   -> 包含 H 的世界更新 confidence
   -> 用户选择特定解释 -> 退化为普通 Assertion（单世界）
   -> 用户回答"不确定" -> 保留多世界，提升倾向世界权重
   |
4. 如果用户澄清与默认值不一致:
   -> 记录 user_override 到 event_log
   -> 更新用户偏好档案
   -> 触发知识库维护告警（如大量覆盖）
```

#### 12.2.2 多世界假设的失效处理

**形式化定义**:
```text
给定 MultiWorldAssertion MWA = {W_1, ..., W_n}
每个世界 W_i 依赖假设集合 H_i

当假设 h 失效时:
  AffectedWorlds = { W_i | h in H_i }

  AffectedWorlds = all_worlds   -> MWA.aggregate_result = consistent_fail
  AffectedWorlds ⊂ all          -> 仅受影响世界失效，检查剩余世界一致性
```

**Datalog 推导规则**:
```prolog
.decl affected_world(world_id:symbol)
.decl remaining_valid_world(mwa:symbol, world_id:symbol)

affected_world(W) :- invalidated_hypothesis(H), world_assumption(W, H).

remaining_valid_world(MWA, W) :- 
    world(MWA, W), !affected_world(W), verification_result(W, pass).

mwa_status(MWA, "all_failed") :- 
    multi_world_assertion(MWA), 
    world(MWA, W) -> affected_world(W).

mwa_status(MWA, "conditional_continue") :- 
    multi_world_assertion(MWA), 
    exists W. remaining_valid_world(MWA, W),
    forall W1. remaining_valid_world(MWA, W1) 
        -> verification_result(W1, consistent_conclusion).
```


## 13. 数据模型设计

### 13.1 完整 PostgreSQL 表设计（修正后的版本）

#### tasks 表

```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  
  -- 状态约束（修复原文档 D1 问题）
  status TEXT NOT NULL 
    CHECK (status IN ('Draft','Ready','Doing','Blocked','Done','Verified','Invalidated')),
  
  owner TEXT,
  priority TEXT CHECK (priority IN ('low','medium','high','critical')),
  goal TEXT,
  
  -- 审计字段
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- 并发控制（修复原文档 G1 问题）
  version INTEGER NOT NULL DEFAULT 1,
  
  -- 软删除
  deleted_at TIMESTAMPTZ,
  
  -- 元数据
  metadata JSONB DEFAULT '{}'
);

-- 索引
CREATE INDEX idx_tasks_status ON tasks(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_owner ON tasks(owner) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_priority ON tasks(priority) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX idx_tasks_active ON tasks(id) WHERE deleted_at IS NULL;
```

#### assertions 表（修复原文档 D2 问题：task_id 可为 NULL）

```sql
CREATE TABLE assertions (
  id TEXT PRIMARY KEY,
  
  -- task_id 可为 NULL 以支持全局规则（修复 D2）
  task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
  
  kind TEXT NOT NULL
    CHECK (kind IN (
      'prerequisite','blocker','causal','evidence','contradiction',
      'invariant','transition_rule','plan_step','acceptance_rule',
      'assumption','derived','fact'
    )),
  
  -- 双存储设计
  nl_assertion TEXT NOT NULL,
  formal_assertion JSONB NOT NULL,
  
  -- Canonical IR（唯一真源）
  canonical_ir JSONB NOT NULL,
  
  -- 符号文本表达
  symbolic_text TEXT,
  
  -- 状态
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','pending','verified','refuted','stale','invalidated')),
  
  -- Glossary 引用（强制对齐机制）
  glossary_refs JSONB DEFAULT '[]',
  
  -- Provenance
  provenance JSONB NOT NULL DEFAULT '{}',
  
  -- Truth Maintenance
  assumption_set TEXT[] DEFAULT '{}',
  derived_from TEXT[] DEFAULT '{}',
  valid_until TIMESTAMPTZ,
  invalidated_reason TEXT,
  
  -- Hash
  canonical_ir_hash TEXT NOT NULL,
  
  -- 审计
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- 并发控制
  version INTEGER NOT NULL DEFAULT 1
);

-- 索引
CREATE INDEX idx_assertions_task ON assertions(task_id);
CREATE INDEX idx_assertions_kind ON assertions(kind);
CREATE INDEX idx_assertions_status ON assertions(status);
CREATE INDEX idx_assertions_ir_hash ON assertions(canonical_ir_hash);
CREATE UNIQUE INDEX idx_assertions_active_task_kind 
  ON assertions(task_id, kind) 
  WHERE status IN ('verified', 'pending') AND task_id IS NOT NULL;
```

#### validation_runs 表（修复原文档 D3 问题：添加复现追踪字段）

```sql
CREATE TABLE validation_runs (
  id TEXT PRIMARY KEY,
  assertion_id TEXT REFERENCES assertions(id) ON DELETE CASCADE,
  transition_id TEXT REFERENCES transitions(id) ON DELETE SET NULL,
  
  -- 求解器信息
  solver TEXT NOT NULL
    CHECK (solver IN ('datalog','z3','clingo','vampire','prover9','pddl','lean','causal')),
  solver_version TEXT NOT NULL,
  solver_syntax TEXT,                   -- smtlib2, asp, tptp, pddl, etc.
  
  -- 输入描述（确保可复现，修复 D3）
  input_facts_hash TEXT NOT NULL,       -- facts snapshot 的 SHA-256 hash
  ruleset_hash TEXT NOT NULL,           -- 活跃规则集的 hash
  canonical_ir_hash TEXT NOT NULL,      -- 被验证断言的 IR hash
  validation_policy_version TEXT NOT NULL DEFAULT '1.0.0',
  
  -- 执行信息
  timeout_seconds INTEGER NOT NULL DEFAULT 30,
  duration_ms INTEGER,                  -- 实际执行耗时（毫秒）
  
  -- 结果
  result TEXT NOT NULL
    CHECK (result IN ('pass','fail','unknown','timeout','error','stale')),
  
  -- 诊断信息
  diagnostics JSONB DEFAULT '{}',
  counterexample JSONB,                 -- 求解器返回的反例
  unsat_core JSONB,                     -- Z3 返回的 unsat core
  proof_trace TEXT,                     -- 证明器返回的证明轨迹
  solver_stderr TEXT,                   -- 求解器 stderr（调试用）
  
  -- 审计
  requested_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  
  -- 并发控制
  version INTEGER NOT NULL DEFAULT 1
);

-- 索引
CREATE INDEX idx_validation_runs_assertion ON validation_runs(assertion_id);
CREATE INDEX idx_validation_runs_transition ON validation_runs(transition_id);
CREATE INDEX idx_validation_runs_result ON validation_runs(result);
CREATE INDEX idx_validation_runs_solver ON validation_runs(solver, solver_version);
-- 用于快速检查"相同输入是否已有验证结果"（缓存命中）
CREATE UNIQUE INDEX idx_validation_runs_cache_lookup 
  ON validation_runs(input_facts_hash, ruleset_hash, canonical_ir_hash, solver, solver_version, validation_policy_version)
  WHERE result = 'pass';
```

#### transitions 表（修复原文档 D4 问题：移除了数组字段）

```sql
CREATE TABLE transitions (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  from_status TEXT NOT NULL
    CHECK (from_status IN ('Draft','Ready','Doing','Blocked','Done','Verified','Invalidated')),
  to_status TEXT NOT NULL
    CHECK (to_status IN ('Draft','Ready','Doing','Blocked','Done','Verified','Invalidated')),
  requested_by TEXT NOT NULL,
  reason_assertions TEXT[] DEFAULT '{}',
  
  -- 状态
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','validated','denied','committed','revoked')),
  
  -- Commit Gate 检查结果
  commit_gate_checks JSONB DEFAULT '{}',
  failure_reason TEXT,
  human_message JSONB,                  -- {zh: "...", en: "..."}
  repair_suggestions JSONB DEFAULT '[]',
  
  -- 审计
  created_at TIMESTAMPTZ DEFAULT now(),
  committed_at TIMESTAMPTZ,
  committed_by TEXT,
  revoked_at TIMESTAMPTZ,
  revoked_by TEXT,
  revoke_reason TEXT,
  
  -- 并发控制
  version INTEGER NOT NULL DEFAULT 1
);

-- 索引
CREATE INDEX idx_transitions_task ON transitions(task_id);
CREATE INDEX idx_transitions_status ON transitions(status);
CREATE INDEX idx_transitions_created ON transitions(created_at);
```

#### transition_validations 关联表（修复原文档 D4 问题：替换数组设计）

```sql
CREATE TABLE transition_validations (
  transition_id TEXT NOT NULL REFERENCES transitions(id) ON DELETE CASCADE,
  validation_run_id TEXT NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
  layer INTEGER NOT NULL CHECK (layer IN (1, 2, 3)),  -- 记录此验证属于哪一层
  is_blocking BOOLEAN NOT NULL DEFAULT false,          -- 是否阻塞 commit
  PRIMARY KEY (transition_id, validation_run_id)
);

-- 索引
CREATE INDEX idx_tv_transition ON transition_validations(transition_id);
CREATE INDEX idx_tv_validation ON transition_validations(validation_run_id);
```

#### compiled_targets 表

```sql
CREATE TABLE compiled_targets (
  id TEXT PRIMARY KEY,
  assertion_id TEXT NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  target TEXT NOT NULL
    CHECK (target IN ('datalog','smtlib2','asp','lean','pddl','argdown','tptp')),
  content TEXT NOT NULL,
  compiler_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  tier INTEGER NOT NULL CHECK (tier IN (1, 2, 3)),
  is_latest BOOLEAN NOT NULL DEFAULT true,
  compile_warnings JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 唯一约束：每个断言 + 目标 + 编译器版本只有一个最新版本
CREATE UNIQUE INDEX idx_compiled_targets_latest 
  ON compiled_targets(assertion_id, target, compiler_version) 
  WHERE is_latest = true;
CREATE INDEX idx_compiled_targets_hash ON compiled_targets(content_hash);
```

#### assertion_dependencies 表

```sql
CREATE TABLE assertion_dependencies (
  assertion_id TEXT NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  depends_on_assertion_id TEXT NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL
    CHECK (relation_type IN ('requires','blocks','supports','contradicts','derives','assumes')),
  PRIMARY KEY (assertion_id, depends_on_assertion_id)
);

-- 双向索引
CREATE INDEX idx_assertion_deps_forward ON assertion_dependencies(assertion_id);
CREATE INDEX idx_assertion_deps_reverse ON assertion_dependencies(depends_on_assertion_id);
```

#### event_log 表（审计日志）

```sql
CREATE TABLE event_log (
  id BIGSERIAL PRIMARY KEY,
  event_type TEXT NOT NULL
    CHECK (event_type IN (
      'task_created','task_updated','task_deleted','task_status_changed',
      'assertion_created','assertion_updated','assertion_validated','assertion_invalidated',
      'transition_proposed','transition_validated','transition_committed','transition_denied','transition_revoked',
      'validation_run_created','validation_run_completed',
      'hypothesis_invalidated','tms_propagation',
      'human_override','human_waiver',
      'solver_error','system_alert'
    )),
  actor TEXT NOT NULL,                    -- Agent ID 或用户 ID
  actor_type TEXT NOT NULL 
    CHECK (actor_type IN ('agent','human','system')),
  entity_type TEXT NOT NULL
    CHECK (entity_type IN ('task','assertion','transition','validation_run','hypothesis','system')),
  entity_id TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  correlation_id TEXT,                    -- 分布式追踪 ID
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 索引
CREATE INDEX idx_event_log_entity ON event_log(entity_type, entity_id);
CREATE INDEX idx_event_log_actor ON event_log(actor);
CREATE INDEX idx_event_log_type ON event_log(event_type);
CREATE INDEX idx_event_log_correlation ON event_log(correlation_id);
CREATE INDEX idx_event_log_created ON event_log(created_at);
```

#### facts_snapshots 表（Fact Snapshot 机制）

```sql
CREATE TABLE facts_snapshots (
  id TEXT PRIMARY KEY,
  
  -- 内容
  snapshot JSONB NOT NULL,                -- 完整的 facts 集合
  snapshot_hash TEXT NOT NULL UNIQUE,     -- SHA-256(snapshot_canonical_json)
  
  -- 描述
  task_ids TEXT[],                        -- 涉及的任务 ID（为空表示全局）
  assertion_ids TEXT[],                   -- 涉及的断言 ID
  
  -- 生成信息
  generated_at TIMESTAMPTZ DEFAULT now(),
  generated_by TEXT NOT NULL,             -- 哪个验证请求生成了此 snapshot
  
  -- 一致性保证
  transaction_id BIGINT,                  -- PostgreSQL txid，用于一致性检查
  
  -- TTL
  expires_at TIMESTAMPTZ                  -- 缓存过期时间
);

-- 索引
CREATE INDEX idx_facts_snapshots_hash ON facts_snapshots(snapshot_hash);
CREATE INDEX idx_facts_snapshots_tasks ON facts_snapshots USING GIN(task_ids);
CREATE INDEX idx_facts_snapshots_expiry ON facts_snapshots(expires_at) 
  WHERE expires_at IS NOT NULL;
```

#### cache 表（验证结果缓存）

```sql
CREATE TABLE validation_cache (
  cache_key TEXT PRIMARY KEY,             -- hash(input_facts + ruleset + canonical_ir + solver + policy)
  validation_run_id TEXT NOT NULL REFERENCES validation_runs(id),
  hit_count INTEGER NOT NULL DEFAULT 0,
  last_hit_at TIMESTAMPTZ DEFAULT now(),
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_validation_cache_expiry ON validation_cache(expires_at);
```



#### ambiguities 表（记录检测到的模糊性）

CREATE TABLE ambiguities (
  id TEXT PRIMARY KEY,
  assertion_id TEXT NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  source_nl_hash TEXT NOT NULL,
  detected_phrase TEXT NOT NULL,
  kind TEXT NOT NULL
    CHECK (kind IN ('semantic_vagueness','informational_incompleteness',
                    'context_dependency','temporal_vagueness',
                    'spatial_vagueness','service_mode_uncertainty',
                    'metaphor_idiom','other')),
  severity TEXT NOT NULL
    CHECK (severity IN ('critical','major','minor','negligible')),
  detect_method TEXT NOT NULL DEFAULT 'datalog'
    CHECK (detect_method IN ('datalog','llm_self_critique','hybrid')),
  interpretations JSONB NOT NULL DEFAULT '[]',
  missing_context TEXT,
  resolution_status TEXT NOT NULL DEFAULT 'unresolved'
    CHECK (resolution_status IN ('unresolved','multi_world_generated',
                                 'default_applied','user_clarified','ignored')),
  matched_rule TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT
);

CREATE INDEX idx_ambiguities_assertion ON ambiguities(assertion_id);
CREATE INDEX idx_ambiguities_severity ON ambiguities(severity);
CREATE UNIQUE INDEX idx_ambiguities_active
  ON ambiguities(assertion_id, detected_phrase, kind)
  WHERE resolution_status IN ('unresolved','multi_world_generated','default_applied');


#### assertion_worlds 表（多世界断言的各世界记录）

CREATE TABLE assertion_worlds (
  id TEXT PRIMARY KEY,
  assertion_id TEXT NOT NULL REFERENCES assertions(id) ON DELETE CASCADE,
  world_id TEXT NOT NULL,
  interpretation JSONB NOT NULL,
  confidence DECIMAL(4,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  assumptions JSONB NOT NULL DEFAULT '[]',
  ambiguities_resolved JSONB DEFAULT '{}',
  verification_result TEXT
    CHECK (verification_result IN ('pending','pass','fail','unknown','stale')),
  validation_run_id TEXT REFERENCES validation_runs(id) ON DELETE SET NULL,
  derived_conclusions JSONB DEFAULT '[]',
  display_order INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (assertion_id, world_id) WHERE is_active = true
);

CREATE INDEX idx_assertion_worlds_assertion ON assertion_worlds(assertion_id);
CREATE INDEX idx_assertion_worlds_result ON assertion_worlds(verification_result);


#### assumption_defaults 表（默认值知识库）

CREATE TABLE assumption_defaults (
  id TEXT PRIMARY KEY,
  kb_type TEXT NOT NULL CHECK (kb_type IN ('universal','domain','context')),
  domain TEXT,
  field TEXT NOT NULL,
  condition TEXT NOT NULL,
  default_value JSONB NOT NULL,
  confidence DECIMAL(4,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  rationale TEXT NOT NULL,
  override_condition TEXT,
  datalog_rule TEXT,
  clarification_template_zh TEXT,
  clarification_template_en TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  is_current BOOLEAN NOT NULL DEFAULT true,
  usage_count INTEGER NOT NULL DEFAULT 0,
  override_count INTEGER NOT NULL DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (kb_type, domain, field, condition, version)
);

CREATE INDEX idx_assumption_defaults_current
  ON assumption_defaults(kb_type, domain, field) WHERE is_current = true;
CREATE INDEX idx_assumption_defaults_lookup
  ON assumption_defaults(kb_type, domain, field, condition) WHERE is_current = true;


#### assertions 表扩展列

ALTER TABLE assertions ADD COLUMN IF NOT EXISTS
  ambiguity_status JSONB DEFAULT '{}'::jsonb;
ALTER TABLE assertions ADD COLUMN IF NOT EXISTS
  aggregate_confidence DECIMAL(4,4) CHECK (aggregate_confidence >= 0 AND aggregate_confidence <= 1);

### 13.2 卡片 JSON Schema（双存储：nl_assertion + formal_assertion）

**完整卡片 Schema（API 返回格式）**:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LKB Card",
  "type": "object",
  "required": ["card_id", "nl_assertion", "formal_assertion", "provenance", "verification"],
  "properties": {
    "card_id": {
      "type": "string",
      "description": "卡片唯一标识符，格式: task_{0000} 或 assertion_{0000}",
      "pattern": "^[a-zA-Z]+_[0-9]+$"
    },
    "schema_version": {
      "type": "string",
      "default": "1.0"
    },
    "nl_assertion": {
      "type": "string",
      "description": "自然语言断言原文，人类可读"
    },
    "formal_assertion": {
      "type": "object",
      "description": "受TPTP启发的自定义JSON格式，语义对齐TPTP但采用嵌套对象树结构",
      "required": ["role", "body"],
      "properties": {
        "schema_version": { "type": "string", "default": "1.0" },
        "role": {
          "type": "string",
          "enum": ["axiom", "assumption", "hypothesis", "conjecture", "lemma"],
          "description": "TPTP role 近似映射"
        },
        "quantifier": {
          "type": "string",
          "enum": ["forall", "exists"]
        },
        "vars": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": { "type": "string" },
              "type": { "type": "string" }
            }
          }
        },
        "body": {
          "type": "object",
          "description": "嵌套逻辑表达式树"
        }
      }
    },
    "glossary_refs": {
      "type": "object",
      "description": "谓词词汇表引用，用于强制对齐",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "entry_id": { "type": "string" },
          "definition": { "type": "string" }
        }
      }
    },
    "provenance": {
      "type": "object",
      "required": ["generated_by", "translation_confidence"],
      "properties": {
        "generated_by": { "type": "string" },
        "model": { "type": "string" },
        "translation_confidence": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "翻译置信度，计算方法见第12章"
        },
        "source_nl_hash": { "type": "string" },
        "created_at": { "type": "string", "format": "date-time" },
        "updated_at": { "type": "string", "format": "date-time" }
      }
    },
    "verification": {
      "type": "object",
      "required": ["status"],
      "properties": {
        "status": {
          "type": "string",
          "enum": ["pending", "verified", "refuted", "error"]
        },
        "solver": { "type": ["string", "null"] },
        "solver_syntax": { "type": ["string", "null"] },
        "proof_trace": { "type": ["array", "null"] },
        "countermodel": { "type": ["object", "null"] },
        "checked_at": { "type": ["string", "null"], "format": "date-time" }
      }
    },
    "structural": {
      "type": "object",
      "properties": {
        "depends_on": {
          "type": "array",
          "items": { "type": "string" },
          "description": "结构依赖列表"
        },
        "causal_weight": {
          "type": "number",
          "minimum": 0,
          "maximum": 1,
          "description": "因果权重，取值范围[0,1]，>=0.7为显著"
        }
      }
    }
  }
}
```

### 13.3 Hash 与版本控制

**Hash 计算策略**:

```python
import hashlib
import json

def compute_canonical_ir_hash(canonical_ir: dict) -> str:
    """计算 Canonical IR 的 SHA-256 hash。"""
    canonical_json = json.dumps(canonical_ir, sort_keys=True, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical_json.encode()).hexdigest()}"

def compute_facts_snapshot_hash(facts: list) -> str:
    """计算 facts snapshot 的 SHA-256 hash。"""
    # 规范化：排序 facts，统一格式
    normalized = sorted(facts, key=lambda f: json.dumps(f, sort_keys=True))
    canonical_json = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical_json.encode()).hexdigest()}"

def compute_ruleset_hash(rules: list) -> str:
    """计算规则集的 SHA-256 hash。"""
    canonical_json = json.dumps(rules, sort_keys=True, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical_json.encode()).hexdigest()}"

def compute_validation_cache_key(
    facts_hash: str,
    ruleset_hash: str,
    canonical_ir_hash: str,
    solver: str,
    solver_version: str,
    policy_version: str
) -> str:
    """计算验证缓存的 key。"""
    data = {
        "facts": facts_hash,
        "ruleset": ruleset_hash,
        "ir": canonical_ir_hash,
        "solver": f"{solver}:{solver_version}",
        "policy": policy_version
    }
    canonical = json.dumps(data, sort_keys=True)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
```

---

## 14. 验证流水线

### 14.1 Assertion 验证流程（含错误处理、降级策略）

```
┌────────────────────────────────────────────────────────────────────┐
│                    Assertion 验证流程（10 步）                        │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  1. Agent 提交 DraftAssertion                                      │
│     │ 错误处理: DSL 语法错误 → 返回 parse_error + 位置信息          │
│     │ 降级策略: 允许提交 nl_assertion -only，标记为 needs_formalization│
│     ▼                                                              │
│  2. Parser 解析 LKB-DSL → AST                                      │
│     │ 错误处理: 类型错误 → 返回 type_error + 期望类型/实际类型       │
│     │ 降级策略: 跳过 type checking，标记为 unchecked                  │
│     ▼                                                              │
│  2.5 模糊性预处理层（Fuzzy Preprocessing Layer）【符号系统优先】
     |
     |-- 2.5a: Datalog 规则匹配检测模糊模式
     |   输入: nl_assertion 原文
     |   处理: Soufflé Datalog 运行 ambiguity_patterns.dl
     |   输出: AmbiguityReport（模糊点列表 + 严重度评级）
     |
     |-- 2.5b: ASP 多解枚举生成候选世界
     |   输入: AmbiguityReport + 模糊点
     |   处理: clingo 枚举所有解释组合（--models=0）
     |   输出: WorldCandidates[]（每个含 interpretation + confidence）
     |
     |-- 2.5c: 默认值知识库填充缺失信息
     |   输入: WorldCandidates + assumption_defaults 表查询
     |   处理: 按优先级(universal > domain > context)匹配默认值
     |   输出: Worlds[]（假设已填充）
     |
     |-- 2.5d: 严重度评级（Datalog 规则推导）
     |   输入: Worlds[] + 假设集合
     |   处理: Datalog 推导每个模糊点的 severity
     |   输出: severity 标注（critical/major/minor/negligible）
     |
     |-- 2.5e: 若 Datalog 无法覆盖 -> LLM self-critique fallback
     |   触发: detect_method='datalog' 未检测到模糊性，但 NL 含高风险词
     |   约束: LLM 结果仅作为补充，不覆盖 Datalog 检测结果
     |
     输出: AmbiguityReport + 填充后的 Worlds
     |
     | 错误处理: 全层失败 -> 标记 fuzzy_check_bypassed，继续后续流程
     | 降级策略: 跳过模糊性检查，按单世界处理（标注风险）
     ▼
  3. Type Checker 检查变量、谓词、类型、作用域                         │
│     │ 错误处理: 未定义谓词 → 查询 glossary，建议可用谓词              │
│     │ 降级策略: 自动创建 glossary 条目草稿，标记为 needs_review       │
│     ▼                                                              │
│  4. Normalizer 生成 canonical_ir                                   │
│     │ 错误处理: 不支持的构造 → 记录 unsupported_construct 警告        │
│     │ 降级策略: 部分编译（跳过不支持的部分）                          │
│     ▼                                                              │
│  5. Natural Renderer 生成自然语言断言（模板化）                       │
│     │ 错误处理: 缺少模板 → 使用默认模板 + 记录 warning                │
│     │ 降级策略: 返回 raw IR（人类可读但非自然语言）                   │
│     ▼                                                              │
│  6. Compiler 生成 Tier 1/2/3 编译目标                               │
│     │ 错误处理: 编译失败 → 返回 compile_error + 失败原因              │
│     │ 降级策略: 降级到更低 Tier（如 Tier 1 失败则标记为 needs_tier2）  │
│     ▼                                                              │
│  7. Solver Runner 执行 Layer 1 验证（同步，< 200ms）                 │
│     │ 错误处理: solver 超时 → 返回 timeout，使用缓存结果（如有）      │
│     │ 降级策略: solver 不可用 → 跳过验证，标记为 solver_unavailable   │
│     ▼                                                              │
│  8. [异步] Solver Runner 执行 Layer 2/3 验证                        │
│     │ 错误处理: solver 崩溃 → 记录 error，重试一次                    │
│     │ 降级策略: 跳过 Layer 2/3，仅依赖 Layer 1 结果                   │
│     ▼                                                              │
│  9. Aggregator 汇总验证结果（保守拒绝策略）                          │
│     │ 错误处理: 结果不一致 → 触发审计告警                             │
│     │ 降级策略: 以 Layer 1 结果为准                                   │
│     ▼                                                              │
│  10. Commit Gate 判断是否可提交                                     │
│      │ 错误处理: commit 失败 → 返回详细失败原因 + 修复建议             │
│      │ 降级策略: 人工覆盖（需审计记录）                                │
│      ▼                                                              │
│  11. UI 展示验证结果和解释                                          │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**步骤级错误处理策略**:

| 步骤 | 可能错误 | 错误处理 | 降级策略 | 恢复点 |
|------|---------|---------|---------|--------|
| 2.5 Fuzzy Preprocessing | Datalog引擎不可用 | 降级到LLM self-critique | bypass_datalog | 标记风险 |
| 2.5 Fuzzy Preprocessing | ASP枚举超时 | 仅生成最可能世界 | single_world | 后续人工审查 |
| 2.5 Fuzzy Preprocessing | 默认值无匹配 | 标记needs_clarification | manual_fill | 用户澄清 |
| 2.5 Fuzzy Preprocessing | 全层失败 | 跳过模糊性检查 | fuzzy_check_bypassed | 标注风险后继续 |
| 2. Parser | 语法错误 | 返回 parse_error | nl-only 提交 | 人工修正 DSL |
| 3. Type Checker | 类型不匹配 | 返回 type_error | 跳过 type check | 人工修正类型 |
| 4. Normalizer | 不支持的构造 | 记录 warning | 部分编译 | 人工简化表达式 |
| 6. Compiler | 编译失败 | 返回 compile_error | 降级 Tier | 人工修复或跳过 |
| 7. Layer 1 | 超时 | 返回 timeout | 使用缓存 | 增加 timeout 重试 |
| 7. Layer 1 | Solver 不可用 | 返回 error | 跳过验证 | 等待 solver 恢复 |
| 8. Layer 2/3 | 崩溃 | 记录 error，重试 1 次 | 依赖 Layer 1 | 重启 solver |

### 14.2 Transition 验证流程（分层调用）

```python
async def validate_transition(transition: Transition) -> ValidationResult:
    """
    Transition 分层验证流程。
    Layer 1 同步执行，Layer 2/3 异步执行。
    """
    # ── Layer 1: 同步快速验证 (< 200ms) ──
    layer1_result = await validate_layer1(transition)
    
    if layer1_result.result == "fail":
        # 快速失败：Layer 1 已失败，无需调用 Layer 2/3
        return ValidationResult(
            overall_result="fail",
            layer_results={"layer1": layer1_result},
            human_message=generate_failure_explanation(layer1_result)
        )
    
    # 记录 Layer 1 通过，启动异步 Layer 2/3
    # Layer 1 结果足够用于 Commit Gate 决策
    
    # ── Layer 2: 异步深度验证 (< 5s) ──
    layer2_task = asyncio.create_task(validate_layer2(transition))
    
    # ── Layer 3: 完全异步验证 (< 60s) ──
    layer3_task = asyncio.create_task(validate_layer3(transition))
    
    # Commit Gate 基于 Layer 1 立即决策
    commit_decision = commit_gate_check(transition, layer1_result)
    
    if commit_decision.commit:
        # 允许 commit，但继续等待 Layer 2/3
        await asyncio.gather(layer2_task, layer3_task, return_exceptions=True)
        
        # Layer 2/3 完成后更新验证结果
        layer2_result = layer2_task.result() if not layer2_task.done() else None
        layer3_result = layer3_task.result() if not layer3_task.done() else None
        
        # 如果 Layer 2/3 后续发现失败，触发重新验证
        if layer2_result and layer2_result.result == "fail":
            await trigger_revalidation_alert(transition, layer2_result)
    
    return ValidationResult(
        overall_result="pass" if commit_decision.commit else "fail",
        layer_results={
            "layer1": layer1_result,
            "layer2": await layer2_task,
            "layer3": await layer3_task
        }
    )

async def validate_layer1(transition: Transition) -> LayerResult:
    """Layer 1: Datalog + 轻量 SMT（同步，< 200ms）"""
    # 1. 生成 facts snapshot
    facts = await generate_facts_snapshot(transition.task_id)
    
    # 2. Datalog 推导
    datalog_result = await run_datalog(facts, transition)
    
    # 3. 轻量 SMT 检查（仅状态互斥）
    smt_result = await run_lightweight_smt(facts, transition)
    
    return LayerResult(
        layer=1,
        result="pass" if datalog_result.passed and smt_result.passed else "fail",
        details={"datalog": datalog_result, "smt": smt_result}
    )
```

### 14.3 Fact Snapshot 机制

Fact Snapshot 是验证可复现性的核心机制。

**Snapshot 生成流程**:

```python
async def generate_facts_snapshot(task_id: str | None) -> FactsSnapshot:
    """
    生成验证用的 facts snapshot。
    
    1. 从数据库读取所有相关 facts（加一致性保证）
    2. 规范化并排序
    3. 计算 hash
    4. 检查缓存（相同 snapshot 直接复用）
    """
    # 使用 PostgreSQL 的 REPEATABLE READ 隔离级别确保一致性
    async with db.transaction(isolation="repeatable_read"):
        # 读取任务相关断言
        task_assertions = await db.assertions.find_by_task(task_id)
        
        # 读取全局规则（task_id IS NULL）
        global_rules = await db.assertions.find_global_rules()
        
        # 读取相关假设
        hypotheses = await db.hypotheses.find_active()
        
        # 组合 facts
        facts = []
        for a in task_assertions + global_rules:
            if a.status in ("verified", "pending"):
                facts.append({
                    "assertion_id": a.id,
                    "canonical_ir": a.canonical_ir,
                    "status": a.status,
                    "assumption_set": a.assumption_set
                })
        
        for h in hypotheses:
            facts.append({
                "hypothesis_id": h.id,
                "status": h.status
            })
    
    # 规范化并排序（确保 hash 稳定）
    facts.sort(key=lambda f: json.dumps(f, sort_keys=True))
    
    # 计算 hash
    snapshot_hash = compute_facts_snapshot_hash(facts)
    
    # 检查缓存
    cached = await db.facts_snapshots.find_by_hash(snapshot_hash)
    if cached:
        return cached
    
    # 创建新 snapshot
    snapshot = FactsSnapshot(
        id=generate_id(),
        snapshot=facts,
        snapshot_hash=snapshot_hash,
        task_ids=[task_id] if task_id else [],
        assertion_ids=[a.id for a in task_assertions + global_rules],
        transaction_id=await db.get_current_txid(),
        expires_at=datetime.now() + timedelta(hours=24)
    )
    
    await db.facts_snapshots.save(snapshot)
    return snapshot
```

**Snapshot 一致性保证**:
- 生成 snapshot 时使用 PostgreSQL `REPEATABLE READ` 事务隔离级别
- 记录 `transaction_id` 用于后续一致性验证
- Snapshot 24 小时 TTL 后自动过期

### 14.4 验证结果状态定义

| 状态 | 含义 | Commit 允许 | 需要重试 | 人类可覆盖 |
|------|------|-----------|---------|----------|
| `pass` | 验证通过 | ✅ 是 | 否 | 否 |
| `fail` | 验证失败 | ❌ 否 | 是 | 否（必须修复问题） |
| `unknown` | 求解器无法判断 | ❌ 否（默认） | 是 | 是（需审计） |
| `timeout` | 验证超时 | ❌ 否（默认） | 是 | 是（需审计） |
| `error` | Solver 内部错误 | ❌ 否 | 是 | 是（需审计） |
| `stale` | 输入已变化，需要重验 | ❌ 否 | 必须 | 否 |
| `partial` | 部分编译/部分验证 | ⚠️ 需人工判断 | 是 | 是 |
| `waived` | 人类高权限豁免 | ✅ 是 | 否 | 是（已覆盖） |

### 14.5 缓存设计

**多级缓存策略**:

```
┌─────────────────────────────────────────────────────────┐
│                    验证缓存架构                           │
├─────────────────────────────────────────────────────────┤
│ L1: 内存缓存（进程内，TTL 60s）                          │
│   - key: canonical_ir_hash                              │
│   - value: compile_result                               │
│   - 命中: 跳过编译步骤                                   │
├─────────────────────────────────────────────────────────┤
│ L2: 数据库缓存（validation_cache 表，TTL 24h）            │
│   - key: SHA256(facts + ruleset + ir + solver + policy) │
│   - value: validation_run_id                            │
│   - 命中: 直接返回缓存的验证结果                          │
├─────────────────────────────────────────────────────────┤
│ L3: Facts Snapshot 缓存（facts_snapshots 表，TTL 24h）    │
│   - key: snapshot_hash                                  │
│   - value: facts snapshot JSON                          │
│   - 命中: 跳过 facts 生成步骤                            │
├─────────────────────────────────────────────────────────┤
│ L4: Solver 预编译缓存（磁盘，TTL 7d）                      │
│   - Datalog 规则预编译为共享库                            │
│   - SMT-LIB 模板缓存                                     │
└─────────────────────────────────────────────────────────┘
```

**缓存失效策略**:
- 断言变更 → 使该 assertion_id 相关的所有缓存条目失效
- 规则集变更 → 使所有依赖该规则集的缓存条目失效
- 假设失效 → 使依赖该假设的断言相关缓存失效
- Solver 版本升级 → 使该 solver 的所有缓存条目失效

---

## 15. 反例、失败解释与修复建议

### 15.1 失败输出结构

```yaml
result: fail
reason: invariant_violation          # 失败原因分类
violated_rule: "R-001"               # 违反的规则 ID
violated_predicate: "Blocked"        # 涉及的谓词

# 求解器返回的反例
counterexample:
  solver: "z3"
  solver_version: "4.16.0"
  model:
    - predicate: "Doing"
      args: ["T_settings"]
      value: true
    - predicate: "Blocked"
      args: ["T_settings"]
      value: true
    - predicate: "Ready"
      args: ["T_settings"]
      value: false

# 人类可读失败解释
human_message:
  zh: "任务 T_settings 不能进入 Doing，因为它同时满足 Doing 和 Blocked，违反了状态排他性公理 EXCL-2。"
  en: "Task T_settings cannot enter Doing because it simultaneously satisfies Doing and Blocked, violating state exclusivity axiom EXCL-2."

# Unsat Core（如求解器支持）
unsat_core:
  - "R-002"                          # 被阻塞任务不能进入 Doing
  - "EXCL-2"                         # Doing 与 Blocked 互斥

# 证明轨迹（如求解器返回）
proof_trace:
  - step: 1
    rule: "R-001"
    premises: ["Requires(T_auth, T_settings)", "¬Done(T_auth)"]
    conclusion: "Blocked(T_settings)"
  - step: 2
    rule: "R-002"
    premises: ["Blocked(T_settings)"]
    conclusion: "¬CanMoveTo(T_settings, Doing)"

# 修复建议
repair_suggestions:
  - action: "complete_prerequisite"
    target: "T_auth"
    description_zh: "请先完成前置任务 T_auth。"
    description_en: "Please complete prerequisite task T_auth."
    priority: 1
  - action: "remove_dependency"
    assertion_id: "A-003"
    description_zh: "或删除 Requires(T_auth, T_settings) 断言。"
    description_en: "Or remove the Requires(T_auth, T_settings) assertion."
    priority: 2
  - action: "submit_proof"
    description_zh: "或提交新的证明说明该依赖不再成立。"
    description_en: "Or submit new proof that the dependency no longer holds."
    priority: 3
```

### 15.2 修复建议类型

| 修复动作 | 适用场景 | 需要权限 | 自动化程度 |
|---------|---------|---------|----------|
| `complete_prerequisite` | 前置任务未完成 | Agent | 自动（推进前置任务） |
| `remove_dependency` | 依赖关系错误 | Agent（需验证） | 半自动（propose 后验证） |
| `modify_assertion` | 断言条件过强 | Agent（需验证） | 半自动 |
| `add_evidence` | 缺少证据 | Agent | 半自动 |
| `split_task` | 任务粒度过大 | Agent（需人工审批） | 手动 |
| `re_run_validation` | 验证环境变化 | Agent | 自动 |
| `request_human_review` | 需要人工判断 | 人类 | 手动 |
| `mark_assumption_invalid` | 假设失效 | 人类 | 手动（触发 TMS 传播） |
| `request_waiver` | 请求规则豁免 | 人类审批者 | 手动（强审计） |

---

## 16. UI/UX 需求

### 16.1 看板视图

**列定义**:
```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│  Draft   │  Ready   │  Doing   │ Blocked  │  Done    │ Verified │
│  (草稿)   │  (就绪)   │  (进行中) │  (阻塞)   │  (完成)   │  (已验证) │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

**每张卡片显示信息**:
- 任务标题（截断 50 字符）
- 当前状态（彩色标签）
- 验证状态图标（✅ 通过 / ❌ 失败 / ⏳ 待验证 / ⚠️ 超时）
- 阻塞器计数（红色徽章）
- 断言计数（蓝色徽章）
- 最后修改者
- 风险/冲突指示器（黄色警告 / 红色危险）
- 假设失效标记（橙色高亮）

### 16.2 任务详情页（5 个视图区域）

任务详情页包含 5 个主要视图区域：

1. **Readable View（可读视图）**: 给普通用户看的自然语言解释
2. **Symbolic View（符号视图）**: 形式化公式、DSL、谓词、规则
3. **Proof View（证明视图）**: Solver 结果、proof trace、counterexample、unsat core
4. **Graph View（图视图）**: Requires / Blocks / Causes / Supports / Contradicts 关系图
5. **History View（历史视图）**: 断言变更、验证历史、状态迁移历史

### 16.3 自然语言解释区域

**"为什么被阻塞"解释示例**:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
任务 T_settings 当前不能进入 Doing。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

原因：
  1. T_settings 依赖 T_auth。
  2. T_auth 尚未完成。
  3. 根据规则 R-001，当前置任务未完成且自身也未完成时，
     依赖任务会被阻塞。
  4. 根据规则 R-002，被阻塞任务不能进入 Doing。

推导链：
  F-003: Requires(T_auth, T_settings)  [事实]
  F-004: ¬Done(T_auth)                  [事实]
  ──────────────────────────────────────
  D-001: Blocked(T_settings)            [由 R-001 推导]
  ──────────────────────────────────────
  D-002: ¬CanMoveTo(T_settings, Doing)  [由 R-002 推导]

建议操作：
  [完成 T_auth]  [删除依赖]  [提交新证明]
```

### 16.4 形式化表达区域

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
形式化表达（Canonical IR）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Facts（事实）:
  Task(T_auth)
  Task(T_settings)
  Requires(T_auth, T_settings)
  ¬Done(T_auth)

Rules（规则）:
  [R-001] ∀a,b:Task. Requires(a,b) ∧ ¬Done(a) ∧ ¬Done(b) ∧ ¬Doing(b) -> Blocked(b)
  [R-002] ∀t:Task. Blocked(t) -> ¬CanMoveTo(t, Doing)

Derived（派生）:
  Blocked(T_settings)          ← R-001(F-003, F-004)
  ¬CanMoveTo(T_settings, Doing) ← R-002(D-001)

编译目标:
  [Datalog]  blocked.dl          ✅ 已验证
  [SMT-LIB]  blocked.smt2        ✅ 已验证
  [ASP]      blocked.lp          ⏳ 待验证
  [Lean]     Blocked.lean        ⏳ 待验证
```

### 16.5 Proof Trace 区域

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proof Trace（证明轨迹）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Datalog 推导:
  Step 1:  requires(t_auth, t_settings) + !done(t_auth) 
           ──[R-001]──> blocked(t_settings)
  Step 2:  blocked(t_settings) 
           ──[R-002]──> !can_move_to(t_settings, "Doing")

Transition Request:
  Move(T_settings, Ready → Doing)

Verification Result:
  ❌ DENIED
  
Counterexample:
  { doing(T_settings) = true, blocked(T_settings) = true }
  违反: Doing(t) -> ¬Blocked(t) （状态排他性公理 EXCL-2）
```

### 16.6 图视图

图视图至少支持以下 6 种图类型：

1. **Task Dependency DAG**: 任务依赖有向无环图（`Requires` 边）
2. **Blocker Graph**: 阻塞关系图（`Blocks` 边 + 推导的 `Blocked` 状态）
3. **Causal Graph**: 因果关系图（`Causes` 边 + causal_weight 权重）
4. **Argument Map**: 论证图（`Supports` / `Contradicts` 边）
5. **Proof Dependency Graph**: 证明依赖图（推导链可视化）
6. **Stale Propagation Graph**: 假设失效传播图（TMS 传播可视化）

**技术实现**: React Flow 或 D3.js，支持缩放、拖拽、节点高亮。

### 16.7 颜色与状态提示

| 状态/颜色 | 含义 | 适用场景 |
|----------|------|---------|
| 🟢 Green | 已验证 | 验证通过的断言和任务 |
| 🟡 Yellow | 待验证 / Solver unknown | 等待验证或求解器无法判断 |
| 🔴 Red | 验证失败 / 存在冲突 | 验证失败或有活跃冲突 |
| ⚪ Gray | 草稿 / 未解析 | Draft 状态的任务或断言 |
| 🟣 Purple | 需要人类批准 | 需要人工审查的断言或迁移 |
| 🟠 Orange | 受失效假设影响 | 假设失效后需要重新验证 |
| 🔵 Blue | 进行中 | Doing 状态的任务 |

---

## 17. API 规格

### 17.1 proposeTask

```http
POST /api/v1/tasks/propose
Content-Type: application/json
X-Request-ID: {correlation_id}
X-Actor-ID: {agent_id}
```

**请求体**:
```json
{
  "title": "实现设置页权限控制",
  "goal": "确保只有认证用户可以访问设置页",
  "priority": "high",
  "owner": "agent-frontend",
  "assertions": [
    {
      "kind": "prerequisite",
      "nl_assertion": "用户认证模块是设置页权限控制的前置条件。",
      "dsl": "fact F-003: Requires(T_auth, T_settings)"
    },
    {
      "kind": "acceptance_rule",
      "nl_assertion": "设置页权限控制完成后，必须通过所有安全审计测试。",
      "dsl": "rule R-005: ∀t:Task. Done(t) -> HasAcceptanceProof(t)"
    }
  ],
  "dependencies": ["T_auth"],
  "acceptance_criteria": ["通过安全审计测试", "权限控制覆盖所有设置页路由"],
  "evidence": ["E-001"],
  "assumptions": ["H-001"]
}
```

**响应**:
```json
{
  "task_id": "T_settings",
  "status": "Draft",
  "next_required_action": "validate_assertions",
  "created_at": "2026-07-04T10:00:00Z",
  "correlation_id": "{correlation_id}"
}
```

**错误响应**:
```json
{
  "error": "validation_failed",
  "message": "提交的 assertions 包含语法错误",
  "details": [
    {
      "assertion_index": 0,
      "error_type": "parse_error",
      "position": {"line": 1, "column": 20},
      "message": "Unexpected token 'Requires', expected variable declaration"
    }
  ]
}
```

### 17.2 validateAssertion

```http
POST /api/v1/assertions/{assertion_id}/validate
Content-Type: application/json
X-Request-ID: {correlation_id}
X-Actor-ID: {agent_id}

{
  "solvers": ["datalog", "z3"],
  "timeout_seconds": 30,
  "use_cache": true
}
```

**响应（同步返回 Layer 1，Layer 2/3 通过 webhook 通知）**:
```json
{
  "assertion_id": "A-1024",
  "validation_id": "V-2026-0001",
  "overall_result": "pass",
  "layer_results": {
    "layer1": {
      "result": "pass",
      "duration_ms": 45,
      "details": {
        "datalog": {"result": "pass"},
        "smt": {"result": "pass"}
      }
    },
    "layer2": {"status": "running", "estimated_seconds": 3},
    "layer3": {"status": "queued"}
  },
  "human_message": {
    "zh": "断言验证通过。Datalog 推导和 SMT 不变量检查均通过。",
    "en": "Assertion validation passed. Datalog derivation and SMT invariant check both passed."
  },
  "webhook_url": "https://agent.example.com/webhooks/validation/V-2026-0001"
}
```

### 17.3 proposeTransition

```http
POST /api/v1/transitions/propose
Content-Type: application/json
X-Request-ID: {correlation_id}
X-Actor-ID: {agent_id}

{
  "task_id": "T_settings",
  "from_status": "Ready",
  "to_status": "Doing",
  "reason_assertions": ["A-1024", "A-1025"],
  "fallback_plan": "如果验证失败，先完成 T_auth"
}
```

**响应**:
```json
{
  "transition_id": "TR-009",
  "status": "pending",
  "validation_status": "layer1_running",
  "estimated_seconds": 1,
  "created_at": "2026-07-04T10:00:00Z"
}
```

### 17.4 commitTransition

```http
POST /api/v1/transitions/{transition_id}/commit
Content-Type: application/json
X-Request-ID: {correlation_id}
X-Actor-ID: {agent_id}
```

**响应（成功）**:
```json
{
  "transition_id": "TR-009",
  "status": "committed",
  "task_id": "T_settings",
  "new_status": "Doing",
  "commit_gate_checks": {
    "ready": true,
    "not_blocked": true,
    "no_contradiction": true,
    "assertions_verified": true,
    "validation_bound": true,
    "hash_consistent": true
  },
  "committed_at": "2026-07-04T10:00:01Z"
}
```

**响应（失败）**:
```json
{
  "transition_id": "TR-009",
  "status": "denied",
  "reason": "blocked_task_cannot_enter_doing",
  "human_message": {
    "zh": "任务 T_settings 不能进入 Doing，因为它仍被 T_auth 阻塞。",
    "en": "Task T_settings cannot enter Doing because it is blocked by T_auth."
  },
  "commit_gate_checks": {
    "ready": true,
    "not_blocked": false,
    "no_contradiction": true,
    "assertions_verified": true,
    "validation_bound": true,
    "hash_consistent": true
  },
  "repair_suggestions": [
    {"action": "complete_prerequisite", "target": "T_auth"},
    {"action": "remove_dependency", "assertion_id": "A-003"}
  ]
}
```

### 17.5 批量操作 API

```http
POST /api/v1/tasks/batch/propose
Content-Type: application/json

{
  "tasks": [
    {"title": "任务A", "goal": "...", "assertions": [...]},
    {"title": "任务B", "goal": "...", "assertions": [...]}
  ]
}
```

```http
POST /api/v1/assertions/batch/validate
Content-Type: application/json

{
  "assertion_ids": ["A-001", "A-002", "A-003"],
  "solvers": ["datalog", "z3"],
  "parallel": true,
  "max_concurrency": 5
}
```

**批量操作限制**:
- 单次最多 50 个任务/断言
- 并发验证最多 5 个
- 超时：单个 30s，批量 120s

### 17.6 查询 API

```http
# 获取任务详情（含断言、验证状态）
GET /api/v1/tasks/{task_id}?include=assertions,validations,history

# 获取阻塞原因解释
GET /api/v1/tasks/{task_id}/blocked-reason?lang=zh

# 获取证明轨迹
GET /api/v1/validation-runs/{validation_run_id}/proof-trace

# 获取影响图（假设失效传播）
GET /api/v1/assertions/{assertion_id}/impact-graph

# 搜索断言
GET /api/v1/assertions/search?kind=prerequisite&status=verified&task_id=T_settings

# 获取事件日志
GET /api/v1/event-log?entity_type=task&entity_id=T_settings&limit=100
```

---

## 18. 安全设计

### 18.1 威胁模型（STRIDE）

| 威胁类别 | 威胁描述 | 影响 | 缓解措施 |
|---------|---------|------|---------|
| **S**poofing | Agent 伪造身份提交 proposal | 非法任务/断言进入系统 | Ed25519 身份验证 + 审计日志 |
| **T**ampering | 恶意 Agent 修改验证结果 | 非法状态变更被 commit | Validation run 不可变存储 + hash 链 |
| **R**epudiation | Agent 否认提交过 proposal | 无法追溯责任 | 所有操作入 event_log + 数字签名 |
| **I**nformation Disclosure | 敏感断言泄露 | 商业机密/隐私泄露 | RBAC 权限控制 + 数据分类 |
| **D**enial of Service | Agent 提交大量复杂断言耗尽 solver | 系统不可用 | 速率限制 + 复杂度检查 + 资源配额 |
| **E**levation of Privilege | Agent 绕过 propose-only 直接 commit | 非法状态变更 | Commit Gate 强制验证 + 关联表约束 |

### 18.2 RBAC 权限模型

```yaml
roles:
  agent_proposer:
    description: "只能 propose 的 Agent"
    permissions:
      - proposeTask
      - proposeAssertion
      - proposeTransition
      - getTask
      - getAssertion
      - getProofTrace
      - explainFailure
      - getBlockedReason
    restrictions:
      - cannot_commit: true
      - cannot_override: true
      - max_assertions_per_hour: 100
      - max_complexity_depth: 3

  agent_verifier:
    description: "验证专用 Agent"
    permissions:
      - compileAssertion
      - validateAssertion
      - getValidationRun
      - getProofTrace
    restrictions:
      - cannot_modify_tasks: true
      - cannot_commit: true

  agent_committer:
    description: "可执行 commit 的系统 Agent"
    permissions:
      - commitTransition           # 必须绑定 validation_run
      - revokeTransition
      - getTask
      - getTransition
    restrictions:
      - commit_requires_validation: true
      - cannot_propose_new_assertions: true

  human_approver:
    description: "人类审批者"
    permissions:
      - approveTransition
      - waiveValidation            # 豁免验证（强审计）
      - overrideBlocked            # 覆盖阻塞状态
      - getTask
      - getAssertion
      - getProofTrace
      - getEventLog

  auditor:
    description: "只读审计员"
    permissions:
      - readOnly: true
      - viewProofTrace: true
      - viewEventLog: true
      - exportAuditReport: true
    restrictions:
      - cannot_modify: true
      - cannot_approve: true

  admin:
    description: "系统管理员"
    permissions:
      - all: true
    restrictions:
      - admin_actions_logged: true
      - cannot_delete_audit_log: true
```

### 18.3 Agent 权限分级

| 操作 | agent_proposer | agent_verifier | agent_committer | human_approver |
|------|--------------|--------------|----------------|---------------|
| proposeTask | ✅ | ❌ | ❌ | ✅ |
| proposeAssertion | ✅ | ❌ | ❌ | ✅ |
| proposeTransition | ✅ | ❌ | ❌ | ✅ |
| compileAssertion | ❌ | ✅ | ❌ | ✅ |
| validateAssertion | ❌ | ✅ | ❌ | ✅ |
| commitTransition | ❌ | ❌ | ✅ | ✅ |
| revokeTransition | ❌ | ❌ | ✅ | ✅ |
| waiveValidation | ❌ | ❌ | ❌ | ✅ |
| overrideBlocked | ❌ | ❌ | ❌ | ✅ |

### 18.4 Solver 沙箱隔离

```yaml
solver_sandbox:
  # 资源限制
  resources:
    cpu_limit: "2 cores"
    memory_limit: "4GB"
    timeout_default: 30              # 秒
    timeout_max: 300                 # 秒
    disk_limit: "100MB"             # 临时文件
  
  # 网络隔离
  network:
    mode: "none"                    # Solver 不允许网络访问
    exception: []                   # 无例外
  
  # 输入验证
  input_validation:
    max_formula_size: 10000         # 最大公式字符数
    max_quantifier_nesting: 3       # 最大量词嵌套深度
    forbidden_functions: ["system", "exec", "eval", "os.", "subprocess"]
    syntax_check: "strict"          # 严格语法检查
  
  # 输出消毒
  output_sanitization:
    max_output_size: "1MB"
    strip_ansi: true
    escape_control_chars: true
  
  # 进程隔离
  process:
    user: "nobody"                  # 以最低权限用户运行
    namespace_isolation: true       # Linux namespace 隔离
    seccomp_profile: "solver"       # seccomp 系统调用过滤
```

### 18.5 审计日志

所有操作必须记录到 `event_log` 表，不可删除、不可修改。

**审计日志保留策略**:
- 在线查询：最近 90 天
- 归档存储：最近 3 年（冷存储）
- 合规要求：根据业务需求可延长至 7 年

**关键审计事件**:
- 所有 Agent 操作（propose/commit/revoke）
- 所有验证执行（请求/结果/失败）
- 所有人类覆盖/豁免操作（含理由）
- 所有假设失效和传播事件
- 所有权限变更
- 所有 solver 错误和降级事件

---

## 19. 性能设计

### 19.1 性能目标（修正后的现实目标）

基于分析结论，原文档"1000 任务 < 2 秒"的目标在多 solver 架构下不现实。修正后的目标：

| 场景 | 目标 | 优先级 | 备注 |
|------|------|--------|------|
| Layer 1 Datalog 推导（1000 任务） | < 200ms | P0 | 同步阻塞，必须快 |
| Layer 1 SMT 轻量检查（1000 任务） | < 200ms | P0 | 同步阻塞 |
| Layer 2 Z3 完整验证（单断言） | < 5s | P1 | 异步 |
| Layer 2 ASP 冲突检测（100 任务） | < 5s | P1 | 异步 |
| Layer 3 定理证明（单断言） | < 60s | P2 | 完全异步 |
| Facts Snapshot 生成 | < 100ms | P1 | 含缓存命中 |
| 编译 Canonical IR → Tier 1 | < 50ms | P1 | 含缓存命中 |
| API 响应（proposeTask） | < 500ms | P0 | 不含验证 |
| API 响应（validateAssertion Layer 1） | < 500ms | P0 | 仅 Layer 1 |

### 19.2 缓存策略

详见 13.5 节的多级缓存设计。补充关键实现：

```python
# 缓存配置
CACHE_CONFIG = {
    "l1_memory": {
        "backend": "in_memory_dict",      # 进程内字典
        "ttl_seconds": 60,
        "max_size": 10000,
    },
    "l2_database": {
        "backend": "postgresql",          # validation_cache 表
        "ttl_seconds": 86400,             # 24 小时
        "cleanup_interval": 3600,         # 每小时清理过期条目
    },
    "l3_snapshot": {
        "backend": "postgresql",          # facts_snapshots 表
        "ttl_seconds": 86400,
    },
    "l4_disk": {
        "backend": "filesystem",          # 磁盘缓存
        "path": "/var/cache/lkb/solver",
        "ttl_seconds": 604800,            # 7 天
    }
}
```

### 19.3 增量推理

**增量验证策略**: 当任务或断言发生变更时，仅重新验证受影响的子集，而非全量重算。

```python
def compute_affected_tasks(changed_assertion_id: str) -> set[str]:
    """
    计算受变更断言影响的所有任务。
    使用 assertion_dependencies 图的反向遍历。
    """
    affected = set()
    queue = [changed_assertion_id]
    visited = set()
    
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        
        # 找到依赖 current 的所有断言
        dependents = db.assertion_dependencies.find_reverse(current)
        for dep in dependents:
            if dep.assertion_id not in visited:
                affected.add(dep.assertion_id)
                queue.append(dep.assertion_id)
    
    # 将断言映射到任务
    task_ids = set()
    for assertion_id in affected:
        assertion = db.assertions.find_by_id(assertion_id)
        if assertion and assertion.task_id:
            task_ids.add(assertion.task_id)
    
    return task_ids
```

**增量 Datalog 推理**: Soufflé 支持增量评估模式（通过 `+fact` 和 `-fact` 语法），仅重新评估受影响规则。

### 19.4 异步验证

Layer 2/3 的异步验证架构：

```python
import asyncio
from dataclasses import dataclass
from enum import Enum

class AsyncValidationStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class AsyncValidationJob:
    job_id: str
    transition_id: str | None
    assertion_id: str
    layers: list[int]                    # [2, 3] 表示 Layer 2 + Layer 3
    status: AsyncValidationStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: ValidationResult | None
    error: str | None
    webhook_url: str | None

async def submit_async_validation(job: AsyncValidationJob) -> str:
    """提交异步验证任务到队列。"""
    await validation_queue.put(job)
    return job.job_id

async def validation_worker():
    """异步验证工作进程。"""
    while True:
        job = await validation_queue.get()
        try:
            job.status = AsyncValidationStatus.RUNNING
            job.started_at = datetime.now()
            
            result = await run_validation_layers(
                job.assertion_id, 
                job.layers
            )
            
            job.result = result
            job.status = AsyncValidationStatus.COMPLETED
            job.completed_at = datetime.now()
            
            # 通知 webhook
            if job.webhook_url:
                await notify_webhook(job.webhook_url, result)
                
        except Exception as e:
            job.status = AsyncValidationStatus.FAILED
            job.error = str(e)
            
        finally:
            await db.async_validation_jobs.save(job)
            validation_queue.task_done()
```

### 19.5 Solver 资源池

```yaml
solver_resource_pool:
  datalog:
    type: "embedded_library"           # Soufflé 嵌入模式
    max_concurrent: 4
    queue_size: 100
    warmup_on_startup: true            # 启动时预编译规则
    
  z3:
    type: "in_process"                 # Z3 Python API（进程内）
    max_concurrent: 8                  # Z3 实例可并发
    queue_size: 200
    context_isolation: "per_request"   # 每个请求独立上下文
    
  clingo:
    type: "subprocess"                 # 子进程调用
    max_concurrent: 4                  # 内存限制
    queue_size: 50
    process_pool_size: 4               # 预启动进程池
    
  vampire:
    type: "subprocess"
    max_concurrent: 2                  # CPU 密集型，限制并发
    queue_size: 20
    timeout_default: 60
    
  prover9:
    type: "subprocess"
    max_concurrent: 2
    queue_size: 20
    timeout_default: 60

# 健康检查
health_check:
  interval_seconds: 30
  timeout_seconds: 5
  failure_threshold: 3                # 连续 3 次失败标记为不可用
  recovery_threshold: 2               # 连续 2 次成功恢复为可用

# 降级策略
fallback:
  solver_unavailable: "skip_layer"    # Solver 不可用时跳过该层
  queue_full: "reject_with_retry"     # 队列满时拒绝并建议重试
  timeout: "return_unknown"           # 超时返回 unknown
```



---

## 20. 可观测性设计

### 20.1 监控指标

系统必须暴露以下 Prometheus 指标：

```yaml
# ── 业务指标 ──
lkb_tasks_total:
  type: gauge
  labels: [status, project]
  description: "各状态任务总数"

lkb_assertions_total:
  type: gauge
  labels: [kind, status]
  description: "各类型/状态的断言总数"

lkb_transitions_total:
  type: counter
  labels: [from_status, to_status, result]
  description: "状态迁移总数（按结果分类）"

lkb_validation_results_total:
  type: counter
  labels: [result, solver, layer]
  description: "验证结果分布"

# ── 性能指标 ──
lkb_validation_duration_seconds:
  type: histogram
  labels: [solver, layer]
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60]
  description: "验证耗时分布"

lkb_compile_duration_seconds:
  type: histogram
  labels: [target_tier]
  buckets: [0.001, 0.005, 0.01, 0.05, 0.1]
  description: "编译耗时分布"

lkb_facts_snapshot_generation_seconds:
  type: histogram
  labels: [task_count_range]
  description: "Facts snapshot 生成耗时"

# ── 缓存指标 ──
lkb_cache_hit_total:
  type: counter
  labels: [cache_level]
  description: "缓存命中次数"

lkb_cache_miss_total:
  type: counter
  labels: [cache_level]
  description: "缓存未命中次数"

lkb_cache_hit_ratio:
  type: gauge
  labels: [cache_level]
  description: "缓存命中率"

# ── 求解器健康指标 ──
lkb_solver_health:
  type: gauge
  labels: [solver_name]
  description: "求解器健康状态（1=健康，0=不健康）"

lkb_solver_queue_depth:
  type: gauge
  labels: [solver_name]
  description: "求解器请求队列深度"

lkb_solver_timeout_total:
  type: counter
  labels: [solver_name]
  description: "求解器超时次数"

# ── 错误指标 ──
lkb_errors_total:
  type: counter
  labels: [error_type, component]
  description: "错误次数"

lkb_tms_propagation_events_total:
  type: counter
  labels: []
  description: "假设失效传播事件总数"
```

### 20.2 健康检查

```yaml
health_checks:
  liveness:
    endpoint: "/health/live"
    interval: "10s"
    checks:
      - http_server_responding
    failure_action: "restart_pod"

  readiness:
    endpoint: "/health/ready"
    interval: "5s"
    checks:
      - database_connected
      - min_solvers_available: 1       # 至少 1 个 Layer 1 solver 可用
    failure_action: "remove_from_lb"

  startup:
    endpoint: "/health/startup"
    checks:
      - database_migrations_applied
      - solvers_warmed_up
      - cache_initialized
    timeout: "120s"

  solver_health:
    endpoint: "/health/solvers"
    interval: "30s"
    checks:
      - datalog: "layer1_ping"
      - z3: "simple_smt_check"
      - clingo: "simple_asp_check"
    failure_threshold: 3
    recovery_threshold: 2
```

### 20.3 告警规则

```yaml
alert_rules:
  # 关键告警（P0）
  - alert: LKBLayer1ValidationLatencyHigh
    expr: histogram_quantile(0.99, lkb_validation_duration_seconds{layer="1"}) > 1
    for: 5m
    severity: critical
    summary: "Layer 1 验证延迟超过 1 秒"
    
  - alert: LKBSolverUnavailable
    expr: lkb_solver_health == 0
    for: 2m
    severity: critical
    summary: "{{ $labels.solver_name }} 求解器不可用"
    
  - alert: LKBDatabaseDisconnected
    expr: up{job="lkb-api"} == 0
    for: 1m
    severity: critical
    summary: "LKB API 不可用"

  # 重要告警（P1）
  - alert: LKBLayer2ValidationTimeoutHigh
    expr: rate(lkb_solver_timeout_total{layer="2"}[5m]) > 10
    for: 10m
    severity: warning
    summary: "Layer 2 验证超时率过高"
    
  - alert: LKBCacheHitRatioLow
    expr: lkb_cache_hit_ratio < 0.5
    for: 15m
    severity: warning
    summary: "{{ $labels.cache_level }} 缓存命中率低于 50%"
    
  - alert: LKBTMSPropagationStalled
    expr: rate(lkb_tms_propagation_events_total[10m]) == 0
    for: 30m
    severity: warning
    summary: "TMS 传播事件长时间未发生（可能停滞）"

  # 提示告警（P2）
  - alert: LKBHighValidationFailureRate
    expr: rate(lkb_validation_results_total{result="fail"}[1h]) / rate(lkb_validation_results_total[1h]) > 0.3
    for: 1h
    severity: info
    summary: "验证失败率超过 30%"
    
  - alert: LKBSolverQueueDepthHigh
    expr: lkb_solver_queue_depth > 50
    for: 10m
    severity: warning
    summary: "{{ $labels.solver_name }} 队列深度超过 50"
```

### 20.4 分布式追踪

所有 API 请求必须携带 `X-Request-ID`（correlation_id），并在整个处理链中传播。

```python
# 分布式追踪中间件
async def tracing_middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID", generate_uuid())
    
    with tracer.start_span("api_request") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", request.url.path)
        span.set_attribute("request.id", request_id)
        
        # 在数据库查询中传播
        db.set_context({"request_id": request_id})
        
        # 在 solver 调用中传播
        solver.set_context({"request_id": request_id})
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

# 追踪关键路径
# proposeTask → parseDSL → typeCheck → normalizeIR → compile → validateLayer1 → commitGate
#            ↘ generateSnapshot → runDatalog → runSMT → aggregate → writeResult
```

**关键追踪点**:
- API 请求处理
- DSL 解析和类型检查
- Canonical IR 生成
- 编译到各 Tier
- 各 Layer 验证执行
- Facts Snapshot 生成
- Commit Gate 决策
- 数据库事务
- Solver 子进程调用

---

## 21. 技术选型

### 21.1 开源组件选型表（含实际版本号、许可证、状态）

| 组件 | 版本 | 许可证 | 状态 | 用途 | 选型理由 |
|------|------|--------|------|------|---------|
| **clingo** | 5.8.0 (PyPI, 2025-04) | MIT | 高度活跃 | ASP 求解器，Layer 2 冲突检测 | Multi-shot solving 生产可用，CFFI bindings 成熟，clingcon 活跃 |
| **clingcon** | 3.x | MIT | 活跃维护 | ASP 线性约束扩展 | clingcon 支持线性约束理论原子 |
| **Prover9** | LADR-2026 (2026-03) | GPLv2 | 重大现代化 | FOL 定理证明，Layer 3 | 新增原生 TPTP 支持，100% 向后兼容，13,000+ TPTP 问题无段错误 |
| **Vampire** | CASC-30 全胜 (2025) | BSD (2020+) | 极活跃 | 主定理证明器，Layer 3 | CASC-30 全胜，有限模型构建（反例查找） |
| **Z3** | 4.16.0 (2026-02) | MIT | 极活跃 | SMT 约束验证，Layer 1/2 | 12,400+ stars，Python API 极成熟，反例生成 |
| **TPTP** | v9.2.1 (2025-10) | 开放规范 | 高度活跃 | 定理证明标准格式 | 26,000+ 问题，50+ 域，行业标准 |
| **Souffle** | 2.4 | UPL | 活跃维护 | Datalog 引擎，Layer 1 | LLVM 编译，高性能，嵌入模式 |
| **CAP** | cap-example (2026-04) | Apache-2.0 | 教学级 | 因果语义参考 | 仅复用 verb 语义设计，不依赖实现 |
| **agent-kanban** | latest (384 stars) | FSL-1.1-ALv2 | 极活跃 | 看板执行层参考 | Ed25519 身份、worktree 隔离、环检测 |

**许可证兼容性说明**:
- **FSL-1.1-ALv2** (agent-kanban): 功能源许可证，允许修改和自建，2 年后自动转为 Apache 2.0。禁止对外提供竞争性托管服务。本项目使用场景符合限制。
- **GPLv2** (Prover9): 若直接链接需开源。本项目通过子进程调用，不构成衍生作品。
- **MIT** (clingo, Z3): 完全兼容，可自由使用。

### 21.2 学术依据表

| 学术项目 | 论文/来源 | 使用场景 | 验证状态 |
|---------|----------|---------|---------|
| **LINC** | Olausson et al., EMNLP 2023 Outstanding Paper | LLM→FOL→Prover9 模式 | ✅ 真实存在 |
| **FoVer** | TACL 2025, Vol. 13, pp. 1340-1359 | LLM→FOL→Z3 验证模式 | ✅ 真实存在 |
| **MATP** | ICSE 2026 | 多步 ATP 验证推理链 | ✅ 真实存在 |
| **LLM+P** | Liu et al., arXiv 2023 | LLM→PDDL→Fast-Downward | ✅ 真实存在 |
| **LLM+ASP** | Yang et al., KR 2023 | LLM→ASP→clingo 模式 | ✅ 真实存在 |
| **LLM-DP** | Dagan et al., 2023 | 动态交互 PDDL 规划 | ✅ 真实存在 |
| **LLM+PDDL** | Guan et al., 2023 | PDDL 人工校验流程 | ✅ 真实存在 |
| **PDDL-INSTRUCT** | Verma et al., MIT CSAIL, 2025 | 指令微调提升 PDDL 准确性 | ✅ 真实存在 |
| **Vampire Diary** | CAV 2025 Distinguished Paper | Vampire 系统设计 | ✅ 真实存在 |

### 21.3 备选方案

| 组件 | 首选 | 备选 | 备选切换条件 |
|------|------|------|-------------|
| Datalog (Layer 1) | Soufflé | 自定义嵌入 Datalog | Soufflé 嵌入模式不稳定 |
| ASP (Layer 2) | clingo | dlv | clingo Python API 破坏性变更 |
| SMT (Layer 1/2) | Z3 | cvc5 | Z3 对特定理论性能下降 |
| 定理证明 (Layer 3) | Vampire | Prover9 LADR-2026 | Vampire 不可用 |
| 定理证明 (副) | Prover9 LADR-2026 | E 2.3 | Prover9 维护中断 |
| 因果服务 | 自建 CAP-compatible | DoWhy (Microsoft) | 需要更成熟的因果推断 |
| 看板执行层 | agent-kanban 参考 | 自建 | FSL 许可证限制 |

---

## 22. 实施路线图

### 22.1 MVP 0: 逻辑卡片原型

**目标**: 证明"双轨断言 + Datalog/Z3 验证 + 自然解释"闭环成立。

**时间**: 4-6 周

**功能范围**:
- ✅ 任务 CRUD（Task 表）
- ✅ 断言双存储（nl_assertion + formal_assertion）
- ✅ LKB-DSL Parser（MVP 子集：∀ ∃ ¬ ∧ ∨ → ∵ ∴）
- ✅ Canonical IR 生成
- ✅ 自然语言 Renderer（模板化）
- ✅ Tier 1 编译目标（Datalog + SMT-LIB）
- ✅ Layer 1 验证（Datalog 阻塞推导 + Z3 不变量检查）
- ✅ 简化 Commit Gate（Ready → Doing 检查）
- ✅ 基础 UI（看板视图 + 任务详情页 Readable/Symbolic View）
- ✅ 反例展示

**技术栈**:
```
Frontend: React + TypeScript + React Flow
Backend: Python 3.12 + FastAPI
Database: PostgreSQL 16
Solver: Soufflé (Datalog) + Z3 4.16.0 (Python API)
Parser: Lark / PLY
```

**不做**:
- ❌ Layer 2/3 异步验证
- ❌ ASP/clingo
- ❌ 定理证明器（Vampire/Prover9）
- ❌ 因果验证层
- ❌ Truth Maintenance 完整实现
- ❌ 批量操作 API

### 22.2 MVP 1: Agent 操作协议

**目标**: 让 Agent 只能 propose，不能 commit。

**时间**: 3-4 周

**新增功能**:
- ✅ 完整 propose → validate → commit 三段式流程
- ✅ Agent 工具接口（LogicalBoardTools）
- ✅ RBAC 权限模型
- ✅ 简化状态机（Draft → Verified → Committed）
- ✅ transition_validations 关联表
- ✅ 验证结果缓存（L1/L2/L3）
- ✅ Facts Snapshot 机制
- ✅ 事件日志（event_log）
- ✅ Layer 2 异步验证（Z3 完整验证）
- ✅ 修复建议生成

### 22.3 MVP 2: 因果验证层

**目标**: 接入因果验证。

**时间**: 3-4 周

**新增功能**:
- ✅ CAP 语义兼容的轻量因果服务（自建）
- ✅ `intervene.do` 查询实现
- ✅ causal_weight 计算（标准化干预效应量）
- ✅ 因果验证门（符号门先、因果门后）
- ✅ 双层验证顺序优化（快速失败）
- ✅ 人类覆盖（override）机制 + 审计记录
- ✅ Graph View（因果图 + 依赖图）
- ✅ 验证缓存完整实现（L1-L4）

### 22.4 MVP 3: 定理证明集成

**目标**: 接入 Vampire + Prover9 LADR-2026，支持 ∀/∃ 量化的推理型断言验证。

**时间**: 3-4 周

**新增功能**:
- ✅ Vampire 子进程调用封装
- ✅ Prover9 LADR-2026 子进程调用封装
- ✅ TPTP 格式生成器
- ✅ SZS 状态行解析
- ✅ Mace4 反例格式解析（portable 格式 → JSON）
- ✅ Layer 3 完全异步验证
- ✅ Proof Trace 展示（Proof View）
- ✅ 求解器写回机制（proof_trace / countermodel）
- ✅ LLM 人类可读注解（打标签分离展示）

### 22.5 MVP 4: 协议级形式验证

**目标**: 验证看板状态机和 Commit Gate 本身是否安全。

**时间**: 4-6 周（可与 MVP 2/3 并行部分工作）

**新增功能**:
- ✅ TLA+ 规格（状态机模型检查）
- ✅ Alloy 模型（小范围反例搜索）
- ✅ Lean 核心不变量证明
- ✅ 并发控制完整实现（乐观锁 + 事务隔离）
- ✅ 降级策略完整实现
- ✅ 安全沙箱完整实现
- ✅ 可观测性完整实现（监控 + 告警 + 追踪）
- ✅ 批量操作 API
- ✅ 可解释性增强（自然语言 proof trace 翻译）

---

## 23. 风险与缓解

### 23.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **LLM 翻译准确率不足** | 高 | 高 | Self-consistency voting (5次采样)；glossary_refs 强制对齐；置信度阈值 (<0.7 强制人工审查)；语法检查层 |
| **Solver 版本兼容性** | 中 | 高 | 固定求解器版本；制定升级测试流程；抽象 solver 接口便于切换 |
| **Vampire/Prover9 子进程调用开销** | 高 | 中 | 进程池预热；限制最大并发；超时控制；异步执行 |
| **Datalog 表达能力限制** | 中 | 中 | 对存在量词结论采用 witness 提取模式；超出表达能力时降级到 Z3 |
| **TPTP ↔ SMT-LIB 格式转换限制** | 中 | 中 | 对转换范围做测试覆盖；超出范围时直接使用 Z3 Python API |
| **LLM API 版本漂移** | 中 | 中 | 固定 LLM 模型版本；建立翻译回归测试集；记录所用模型版本 |
| **json-ld-logic 维护不活跃** | 低 | 低 | 不直接依赖，仅作为参考设计；使用自定义 JSON 格式 |

### 23.2 工程风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **并发控制复杂度高** | 中 | 高 | PostgreSQL 乐观锁 + REPEATABLE READ；版本号冲突检测；幂等设计 |
| **Solver 资源竞争** | 高 | 中 | Solver 资源池（最大并发、队列、超时）；健康检查 + 自动恢复 |
| **异步验证状态管理** | 中 | 中 | 状态机持久化到数据库；webhook 通知；超时自动取消 |
| **降级时用户体验** | 中 | 中 | 清晰的降级提示；默认保守拒绝；人工覆盖通道 |
| **性能不达目标** | 中 | 高 | 多级缓存；增量推理；Datalog 预编译；性能监控 + 自动告警 |
| **分布式一致性** | 低 | 高 | 数据库事务保证原子性；幂等 solver 调用；snapshot 一致性检查 |
| **安全注入风险** | 中 | 高 | Solver 输入语法验证；沙箱隔离（namespace/seccomp）；禁止函数列表 |

### 23.3 缓解措施总结

**核心缓解原则**: 
1. **保守拒绝**: 任何不确定性默认不通过，而非默认通过
2. **多层降级**: Solver 不可用时降级到更轻量的验证，而非跳过验证
3. **完整审计**: 所有异常、降级、覆盖操作全部记录，不可删除
4. **快速失败**: Layer 1 发现问题立即返回，不浪费 Layer 2/3 资源
5. **人工兜底**: 自动验证无法处理时，提供清晰的人工介入通道

---

## 24. 示例完整流程

### 24.1 模糊输入处理完整流程：洗车场景

**场景**: 用户输入 "离家50米的洗车店，该开车去还是走路去？"

---

#### Step 1: Agent 提交任务（含模糊NL输入）

```
POST /api/v1/tasks/propose
{
  "title": "选择交通方式去洗车店",
  "goal": "到达离家50米的洗车店完成洗车",
  "assertions": [{"kind": "prerequisite", "nl_assertion": "离家50米的洗车店"}]
}
-> { "task_id": "T-001", "status": "Draft" }
```

#### Step 2.5: 模糊性预处理层（Fuzzy Preprocessing Layer）【符号系统优先】

```
2.5a: Datalog 规则匹配检测模糊模式
─────────────────────────────────────
输入: "离家50米的洗车店"
运行: Soufflé Datalog ambiguity_patterns.dl

匹配结果:
  ambiguity_detected(NL, "50米", semantic_vagueness, major)
    -> 解释1: EuclideanDistance(家, 店) = 50
    -> 解释2: WalkingDistance(家, 店) = 50

  ambiguity_detected(NL, "洗车", service_mode_uncertainty, critical)
    -> 解释1: SelfServiceWash(用户, 车)
    -> 解释2: StaffServiceWash(工作人员, 车)

  ambiguity_detected(NL, "车", informational_incompleteness, major)
    -> 缺失: 车当前位置？

输出 AmbiguityReport: report_id="AR-001", 3个模糊点, max_severity=critical

2.5b: ASP 多解枚举生成候选世界
─────────────────────────────────────
运行: clingo --models=0

约束规则（剪枝）:
  :- world(W), self_service(W), car_at_shop(W).
  :- world(W), staff_service(W), not car_at_shop(W).

剪枝后有效世界: W_1, W_3

WorldCandidates:
  W_1: {EuclideanDistance=50, StaffService, CarAtHome}   confidence: 0.32
  W_3: {WalkingDistance=50, StaffService, CarAtHome}     confidence: 0.48

2.5c: 默认值知识库填充缺失信息
─────────────────────────────────────
查询 assumption_defaults 表:

匹配条目:
  "default:distance_type:v1.0" -> 步行距离, confidence=0.6
  "domain:automotive:service_mode:v1.0" -> 工作人员代洗, confidence=0.8
  "context:user_at_home:car_location:v1.0" -> 在家, confidence=0.95

填充假设:
  H-001(W_1): 距离=Euclidean, confidence=0.4
  H-002(W_3): 距离=Walking, confidence=0.6
  H-003(共用): 服务模式=StaffService, confidence=0.8
  H-004(共用): 车位置=在家, confidence=0.95

归一化后: W_1=0.4, W_3=0.6

2.5d: 严重度评级（Datalog 推导）
─────────────────────────────────────
  severity(H-003) = critical  -> needs_clarification(H-003) = true

2.5e: Datalog 已覆盖，无需 LLM fallback
```

#### Step 3-4: Type Checker + Normalizer

Type Checker 验证所有谓词签名。Normalizer 为每个世界生成 Canonical IR：

```
W_1 IR: And(Exists(洗车店), EuclideanDistance(家, 店, 50),
            StaffServiceWash(工作人员, 车), At(车, 家))

W_3 IR: And(Exists(洗车店), WalkingDistance(家, 店, 50),
            StaffServiceWash(工作人员, 车), At(车, 家))
```

#### Step 5: 关键澄清（critical 模糊性）

```
系统: "洗车是您自己洗还是工作人员代洗？这会显著影响交通方式。"
用户: "工作人员代洗。"

-> H-003 更新: assumed_value="工作人员代洗", confidence=1.0, source=user_clarified
-> 确认谓词: RequiresResource(洗车, 车, 洗车店)
```

#### Step 6: 符号验证（每个世界独立）

```
── W_1 验证（Euclidean=50m, StaffService, CarAtHome）──

Datalog 推导:
  requires_resource(洗车, 车, 洗车店)      [H-003澄清]
  at(车, 家)                                [H-004]
  euclidean_distance(家, 店, 50)            [H-001]

  // 走路方案
  travel_mode(走路) -> can_carry(人, 车) = false
  -> can_reach(店, 车) = false -> goal_achievable(洗车) = false [走路: ❌]

  // 开车方案
  travel_mode(开车) -> can_carry(车, 车) = true
  -> can_reach(店, 车) = true -> goal_achievable(洗车) = true  [开车: ✅]

W_1 结果: verification_result="pass", 推荐=开车

── W_3 验证（Walking=50m, StaffService, CarAtHome）──

Datalog 推导:
  walking_distance(家, 店, 50)              [H-002]
  at(车, 家)                                [H-004]
  requires_resource(洗车, 车, 洗车店)       [H-003澄清]

  走路 -> can_carry(人, 车) = false -> at(车, 店) = false [走路: ❌]
  开车 -> can_carry(车, 车) = true  -> at(车, 店) = true  [开车: ✅]

W_3 结果: verification_result="pass", 推荐=开车
```

#### Step 7: 结果聚合

```
聚合规则:
  W_1: pass (开车可行, 走路不可行)
  W_3: pass (开车可行, 走路不可行)
  -> 结论跨解释一致

aggregate_result = "consistent_pass"
最终推荐: 开车去（唯一满足物理约束的方案）
置信度: 1.0

注: H-001/H-002（距离类型）不影响最终结论，保留为假设无需澄清。
```

#### Step 8: Commit Gate

```
检查:
  ✅ AllAssertionsVerified
  ✅ MinConfidenceCheck (1.0 >= 0.5)
  ✅ WorldConsistencyCheck (consistent_pass)
  ✅ NoActiveContradiction
  ✅ ValidationBound + HashConsistent

-> CommitDecision(commit=True)
T-001.status = "Ready"
```

#### Step 9: 看板展示

```
┌─────────────────────────────────────────────────────┐
│ 🟢 T-001: 选择交通方式去洗车店                       │
│    ✅ 已验证 (置信度: 1.00)                           │
│                                                      │
│ 推荐: 开车去                                         │
│ 原因: 工作人员代洗需要车在洗车店，走路无法携带车       │
│                                                      │
│ 推理链:                                              │
│  ∵ 洗车 = 工作人员代洗 [用户确认 ✅]                   │
│  ∵ 代洗需要车在洗车店                                │
│  ∵ 车当前在家 [假设, 置信度 0.95]                     │
│  ∴ 走路 -> 车仍在家 -> 无法洗车 ❌                   │
│  ∴ 开车 -> 车到店 -> 可以洗车 ✅                     │
│                                                      │
│ 多世界验证:                                          │
│   W_1 (直线50m): 开车 ✅ 走路 ❌                      │
│   W_3 (步行50m): 开车 ✅ 走路 ❌                      │
│   -> 两种解释下结论一致                               │
│                                                      │
│ 假设: H-001: 50米≈步行距离(0.6) [不影响结论]          │
│       H-004: 车在家(0.95) [不影响结论]                │
│                                                      │
│ [查看完整多世界分析] [修改假设] [提出替代方案]         │
└─────────────────────────────────────────────────────┘

替代方案（自动 proposeFollowUpTask）:
  T-002: "呼叫上门取车洗车服务"
  T-003: "使用代步工具拖拖车到店"
```

---

### 24.2 任务被阻塞的全流程

### 24.2 任务被阻塞的全流程

```
初始状态:
  Task(T_auth)       status: Ready
  Task(T_settings)   status: Ready
  Fact: Requires(T_auth, T_settings)
  Fact: ¬Done(T_auth)           # T_auth 未完成

Step 1: Agent 请求 T_settings 迁移到 Doing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POST /api/v1/transitions/propose { task_id: "T_settings", to_status: "Doing" }

Step 2: Layer 1 Datalog 推导
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  requires(t_auth, t_settings)  [事实 F-003]
  !done(t_auth)                 [事实 F-004]
  !done(t_settings)             [当前状态]
  !doing(t_settings)            [当前状态]
  ──────────────────────────────────────
  → blocked(t_settings)         [由 R-001 推导]
  → !can_move_to(t_settings, "Doing")  [由 R-002 推导]

Step 3: Commit Gate 拒绝
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ❌ ¬Blocked(T_settings) = FALSE  # T_settings 被阻塞！
  
→ commit = false

Step 4: 失败响应
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "transition_id": "TR-002",
  "status": "denied",
  "reason": "blocked_task_cannot_enter_doing",
  "human_message": {
    "zh": "任务 T_settings 不能进入 Doing，因为它仍被 T_auth 阻塞。"
  },
  "proof_trace": [
    {"step": 1, "rule": "R-001", 
     "premises": ["Requires(T_auth, T_settings)", "¬Done(T_auth)"],
     "conclusion": "Blocked(T_settings)"},
    {"step": 2, "rule": "R-002",
     "premises": ["Blocked(T_settings)"],
     "conclusion": "¬CanMoveTo(T_settings, Doing)"}
  ],
  "repair_suggestions": [
    {"action": "complete_prerequisite", "target": "T_auth"},
    {"action": "remove_dependency", "assertion_id": "A-003"}
  ]
}

Step 5: UI 展示
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Readable View:
  "任务 T_settings 当前不能进入 Doing。
   原因：T_settings 依赖 T_auth，而 T_auth 尚未完成。
   根据规则 R-001，当前置任务未完成时，依赖任务会被阻塞。
   根据规则 R-002，被阻塞任务不能进入 Doing。"

Symbolic View:
  Facts:  Requires(T_auth, T_settings)
          ¬Done(T_auth)
  Rules:  ∀a,b. Requires(a,b) ∧ ¬Done(a) ∧ ¬Done(b) ∧ ¬Doing(b) → Blocked(b)
          ∀t. Blocked(t) → ¬CanMoveTo(t, Doing)
  Derived: Blocked(T_settings)
           ¬CanMoveTo(T_settings, Doing)

Proof View:
  Datalog:  F-003 + F-004 + R-001 → D-001 Blocked(T_settings)
            D-001 + R-002 → D-002 ¬CanMoveTo(T_settings, Doing)
  Result:   DENIED
```

### 24.3 假设失效传播的全流程

```
初始状态:
  Hypothesis H-001: "网络服务在任务执行期间可用"  status: active
  Assertion A-001:  Requires(T_auth, T_settings)   status: verified
  Assertion A-002:  Causes(T_network, T_settings_ready)  status: verified
                    Assumes(A-002, H-001)
  Task T_settings:   status: Ready

事件: 网络分区检测到
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Step 1: H-001 被标记 invalid
  H-001.status = "invalid"
  H-001.invalidated_by = "NETWORK_PARTITION_EVENT_001"
  H-001.invalidated_at = "2026-07-04T14:00:00Z"

Step 2: 查询 assumption_index
  H-001 的 dependent_assertions:
    - A-002 (direct dependency: Assumes(A-002, H-001))

Step 3: 标记 A-002 为 stale
  A-002.status = "stale"
  A-002.valid_until = "2026-07-04T14:00:00Z"
  A-002.invalidated_reason = "依赖假设 H-001（网络可用）已失效"

Step 4: 递归传播
  查询 A-002 的派生断言:
    - D-001: DerivedFrom(D-001, A-002) → 标记 stale
    - D-002: DerivedFrom(D-002, D-001) → 标记 stale

Step 5: 任务状态更新
  T_settings 依赖 A-002 (Causes 关系):
  - 重新运行 Datalog 推导
  - 由于 A-002 变为 stale，Causes(T_network, T_settings_ready) 不再可靠
  - T_settings 可能需要重新验证
  - T_settings.status = "Ready" → 标记 "needs_recheck" 标签

Step 6: UI 展示影响范围
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 假设 H-001 已失效

影响范围:
  失效假设: H-001（网络服务在任务执行期间可用）
  
  受影响断言:
    🟠 A-002: Causes(T_network, T_settings_ready) — 已标记 stale
    
  受影响派生事实:
    🟠 D-001: Ready(T_settings) — 已标记 stale
    
  受影响任务:
    🟠 T_settings — 需要重新验证
    
  建议操作:
    [重新验证 T_settings]  [修改 H-001 假设]  [移除 A-002 依赖]

Step 7: 通知
  - 通知创建了 A-002 的 Agent: "你创建的断言 A-002 因假设 H-001 失效需要重新验证"
  - 在看板 UI 上高亮 T_settings 卡片（橙色）
```

---

## 25. 非功能需求

### 25.1 正确性

- **C-1**: Solver 返回 `fail` 时必须拒绝 commit，无任何例外。
- **C-2**: Solver 返回 `unknown` / `timeout` 默认不得自动放行，除非人类审批者显式覆盖。
- **C-3**: `natural_text` 必须可追溯到 `canonical_ir`（通过 hash 链）。
- **C-4**: `compiled_target` 必须可由 `canonical_ir` 重新生成。
- **C-5**: 验证结果必须绑定 `input_hash`（facts snapshot hash）。
- **C-6**: 状态排他性约束必须始终满足（任一任务不会同时处于两个状态）。
- **C-7**: Commit Gate 必须检查 transition 绑定了至少一个 Layer 1 validation_run。

### 25.2 可审计性

- **A-1**: 所有 Agent 操作必须进入 `event_log`。
- **A-2**: 所有状态变更必须记录 actor、time、reason、validation_run_id。
- **A-3**: 所有断言修改必须保留历史版本（通过 version 字段 + event_log）。
- **A-4**: 所有人类覆盖/豁免必须记录 approver 和 justification。
- **A-5**: 审计日志保留最少 90 天在线查询 + 3 年归档。
- **A-6**: 审计日志不可删除、不可修改。

### 25.3 可解释性

- **E-1**: 每个 `Blocked` 状态必须有自然语言解释。
- **E-2**: 每个 validation `fail` 必须有人类可读原因 + 修复建议。
- **E-3**: 每个 derived fact 必须能回溯到 facts + rules（proof trace）。
- **E-4**: UI 应提供 proof trace 的图形化展示。
- **E-5**: 用户能在 3 次点击内看到任务阻塞原因。
- **E-6**: LLM 生成的解释必须打标签 `explanation_generated_by: "llm-gloss"`，与验证真值分离展示。

### 25.4 性能

- **P-1**: Layer 1 Datalog 推导 1,000 任务 < 200ms（P0）。
- **P-2**: Layer 1 SMT 轻量检查 < 200ms（P0）。
- **P-3**: API proposeTask 响应 < 500ms（不含验证）（P0）。
- **P-4**: API validateAssertion (Layer 1) 响应 < 500ms（P0）。
- **P-5**: Layer 2 Z3 完整验证单断言 < 5s（P1，异步）。
- **P-6**: Layer 3 定理证明单断言 < 60s（P2，完全异步）。
- **P-7**: Facts Snapshot 生成 < 100ms（含缓存命中）（P1）。
- **P-8**: Canonical IR → Tier 1 编译 < 50ms（含缓存命中）（P1）。

### 25.5 安全

- **S-1**: Agent 不得直接写数据库最终状态（propose-only）。
- **S-2**: Agent 工具权限必须分级（RBAC）。
- **S-3**: Commit API 只接受已验证 transition。
- **S-4**: 验证器输入需要沙箱隔离（namespace/seccomp）。
- **S-5**: 外部 solver 需要资源限制（CPU/内存/超时）。
- **S-6**: Solver 输入需要语法验证和禁止函数过滤。
- **S-7**: 支持只读审计模式。
- **S-8**: 所有人类覆盖操作必须审计。

### 25.6 降级与容错

- **F-1**: Solver 不可用时降级到更低 Layer，而非跳过验证。
- **F-2**: 数据库不可用时返回 503 + 重试建议。
- **F-3**: 验证服务过载时启用速率限制 + 队列。
- **F-4**: Layer 2/3 超时时返回 Layer 1 结果。
- **F-5**: 所有 solver 崩溃时启用人工审批通道。
- **F-6**: 缓存未命中时不阻塞主流程。
- **F-7**: 系统重启后自动预热 solver 和缓存。

---

## 26. 附录

### 26.1 符号映射速查表

| 符号 | Unicode | LKB-DSL | TPTP | 语义 | 备注 |
|------|---------|---------|------|------|------|
| ∀ | U+2200 | `forall` | `!` | 全称量词 | |
| ∃ | U+2203 | `exists` | `?` | 存在量词 | |
| ¬ | U+00AC | `not` | `~` | 否定 | |
| ∧ | U+2227 | `and` | `&` | 合取 | |
| ∨ | U+2228 | `or` | `\|` | 析取 | |
| → | U+2192 | `implies` | `=>` | 蕴含 | |
| ↔ | U+2194 | `iff` | `<=>` | 等价 | |
| ∵ | U+2235 | `because` | `role:axiom` | 前提/公理 | **近似映射**，见 6.4.2 |
| ∴ | U+2234 | `therefore` | `role:conjecture` | 待证结论 | **近似映射**，见 6.4.2 |

### 26.2 TPTP 语法对照

**TPTP FOF (First-Order Form) 语法示例**:

```tptp
% LKB 规则 → TPTP FOF 对照

% RT-001: 前置条件未满足则阻塞（修正版）
fof(rt001, axiom,
    ! [A,B] :
      ( ( task(A) & task(B) & requires(A,B) & ~ done(A) & ~ done(B) & ~ doing(B) )
        => blocked(B) ) ).

% RT-003: Doing 任务必须 Ready 且不被阻塞
fof(rt003, axiom,
    ! [T] :
      ( ( task(T) & doing(T) )
        => ( ready(T) & ~ blocked(T) ) ) ).

% RT-005: Done 任务必须有验收证明
fof(rt005, axiom,
    ! [T] :
      ( ( task(T) & done(T) )
        => has_acceptance_proof(T) ) ).

% 状态排他性公理
fof(excl_blocked, axiom,
    ! [T] : ( blocked(T) => ~ ( ready(T) | doing(T) | done(T) ) ) ).

fof(excl_doing, axiom,
    ! [T] : ( doing(T) => ~ ( ready(T) | blocked(T) | done(T) ) ) ).
```

**TPTP 角色说明**:

| TPTP Role | 含义 | LKB 对应 | 备注 |
|----------|------|---------|------|
| `axiom` | 被假定为真的公式 | ∵（前提陈述）| 声明性，不带因果暗示 |
| `assumption` | 临时假设 | ∵（条件性前提）| 可被后续推翻 |
| `hypothesis` | 工作假设 | ∵（探索性前提）| 待验证 |
| `conjecture` | 待证目标命题 | ∴（待证结论）| 证明器内部会否定后加入子句集 |
| `lemma` | 已证明的中间结论 | ∴（中间结论）| 非 TPTP 标准，LKB 扩展 |
| `negated_conjecture` | 被否定的 conjecture | （内部使用）| 证明器自动生成 |

### 26.3 Glossary 规范（谓词词汇表）

**Glossary 是防止 LLM 翻译漂移的核心机制**。所有 formal_assertion 中使用的谓词必须在 glossary 中注册。

#### Glossary 存储方案

```yaml
# glossary.yaml —— Git 管理的谓词词汇表
glossary:
  version: "1.0"
  last_updated: "2026-07-04T00:00:00Z"
  
  predicates:
    P-001:
      name: "Requires"
      signature: "Task × Task -> Bool"
      definition_zh: "任务 A 是任务 B 的前置条件"
      definition_en: "Task A is a prerequisite of task B"
      example: "Requires(T_auth, T_settings)"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-002:
      name: "Blocks"
      signature: "Task × Task -> Bool"
      definition_zh: "任务 A 阻塞任务 B"
      definition_en: "Task A blocks task B"
      example: "Blocks(T_api, T_ui)"
      added_by: "human-approver-1"
      added_at: "2026-02-01T00:00:00Z"
      
    P-003:
      name: "Causes"
      signature: "Task × Task -> Bool"
      definition_zh: "任务 A 的完成对任务 B 有因果影响"
      definition_en: "Completion of task A causally affects task B"
      example: "Causes(T_schema, T_backend_ready)"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-004:
      name: "Done"
      signature: "Task -> Bool"
      definition_zh: "任务已完成"
      definition_en: "Task is completed"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-005:
      name: "Doing"
      signature: "Task -> Bool"
      definition_zh: "任务正在进行中"
      definition_en: "Task is in progress"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-006:
      name: "Blocked"
      signature: "Task -> Bool"
      definition_zh: "任务被阻塞（存在未完成的前置条件）"
      definition_en: "Task is blocked (has unmet prerequisites)"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-007:
      name: "Ready"
      signature: "Task -> Bool"
      definition_zh: "任务已就绪（未被阻塞）"
      definition_en: "Task is ready (not blocked)"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
      
    P-008:
      name: "HasAcceptanceProof"
      signature: "Task -> Bool"
      definition_zh: "任务拥有验收证明"
      definition_en: "Task has acceptance proof"
      added_by: "system"
      added_at: "2026-01-01T00:00:00Z"
```

#### Glossary 强制对齐机制

```python
def validate_glossary_alignment(formal_assertion: dict, glossary: dict) -> list:
    """
    验证 formal_assertion 中使用的所有谓词都在 glossary 中注册。
    返回未注册谓词列表（为空表示全部对齐）。
    
    规则：
    1. LLM 翻译器必须从 glossary 中选择谓词，不允许 invent 新谓词
    2. 如果需要的谓词不在 glossary 中，翻译器应：
       a. 使用最接近的已注册谓词
       b. 在翻译结果中标记 "needs_new_predicate: [suggested_name]"
    3. 新谓词需要人工审查后才能加入 glossary
    """
    unregistered = []
    predicates = extract_predicates(formal_assertion)
    
    for pred in predicates:
        if pred not in glossary["predicates"]:
            unregistered.append(pred)
    
    return unregistered
```

**新谓词注册流程**:
```
Agent/LLM 发现需要新谓词
    │
    ▼
在翻译结果中标记 "needs_new_predicate"
    │
    ▼
提交 proposeAssertion（含新谓词标记）
    │
    ▼
系统验证：新谓词不在 glossary 中
    │
    ▼
断言状态 = "needs_glossary_review"（暂停验证流程）
    │
    ▼
通知人类审批者审查新谓词
    │
    ▼
审批者审查并决定是否加入 glossary
    │ 通过
    ▼
更新 glossary.yaml → 提交 PR → 合并
    │
    ▼
断言状态 = "draft"（恢复正常验证流程）
```

### 26.4 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 断言 | Assertion | 任务上的逻辑陈述，含自然语言和形式化双存储 |
| 假设 | Hypothesis | 暂时假定为真的条件，可被后续推翻 |
| 规则 | Rule | 全局或局部逻辑规则，由 Canonical IR 编译到各求解器 |
| 事实 | Fact | 当前被系统接受的原子命题 |
| 派生事实 | Derived Fact | 由规则和事实推导得出的事实 |
| 验证运行 | Validation Run | 某次验证的完整执行记录 |
| 迁移 | Transition | 任务状态迁移请求（propose → validate → commit） |
| 中间表示 | Canonical IR | 系统的唯一真源，所有表达由此生成 |
| 提交门 | Commit Gate | 状态从 Verified 到 Committed 的唯一入口 |
| 真值维护 | Truth Maintenance | 假设失效时自动传播影响到依赖断言 |
| 求解器 | Solver | 外部符号推理系统（Datalog/ASP/SMT/ATP） |
| 快速失败 | Fail-Fast | Layer 1 发现问题立即返回，不调用 Layer 2/3 |
| 保守拒绝 | Conservative Rejection | 任何不确定性默认不通过 |
| 提议 | Propose | Agent 提交候选操作（不能直接修改状态） |

---

> **文档结束**
>
> 本文档整合了以下材料：
> - `logical_kanban_feature_requirements.md`（文档1，产品完整性与愿景）
> - `causal-symbolic-gated-kanban-spec.md`（文档2，学术深度与精确选型）
> - `fuzzy_input_handling.md`（模糊输入处理体系设计）
> - `analysis_doc1.md`（文档1技术分析报告，含所有问题修正）
> - `analysis_doc2.md`（文档2技术分析报告，含所有问题修正）
> - `tech_research_report.md`（关键技术组件调研报告）
>
> 所有 Critical 问题已修正，所有技术选型已验证，所有形式化表达式已校验。
> 模糊输入处理体系已集成，符号系统优先（Datalog/ASP/Z3）于大模型推理。
> 本文档可直接交付开发团队进入工程实现阶段。


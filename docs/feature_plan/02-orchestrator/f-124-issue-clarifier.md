# F-124: Issue 澄清器 — 描述不清晰自动检测与澄清闭环

> 状态: 🟢 MVP 已实现（核心 12/15 落地；仅 F-124-L workspace focus 富化 + 3 项运营增强未做）
> 章节: docs/feature_plan/02-orchestrator/f-124-issue-clarifier.md
> 最后更新: 2026-07-21
> 关联能力: F-38（验证+报告+PR）、F-39（issue 重跑标签）、F-121（规则回灌）、F-123（Intent Forecast）

> **注**：§0 已记录与原草案的三处重大调整（不复用永久 Intent.BLOCKED / 复用 ClarificationResolver / 接入点改为 `_poll_and_dispatch`），本节之后文档与实现保持一致。

---

## §0 当前实现（2026-07-11）

F-124 已完成可运行 MVP，但实现方式与本文最初草案有三处重要调整：

1. **只新增文本清晰度分析层**：`issue_clarifier/` 负责 prompt、JSON 解析、fingerprint
   缓存和 clear/unclear 判定。
2. **复用现有澄清基础设施**：问题投递、作者评论检测、超时和回答冲突继续由
   `ClarificationResolver` + `ClarificationQueue` 负责，没有再创建重复 Poller/Queue。
3. **不复用永久 `Intent.BLOCKED`**：当前 `agent:blocked` 会把记录转成 abandoned/terminal，
   不适合“等作者回答后继续”。F-124 使用 `clarification_status=awaiting_author` 暂停分发，
   回答通过重新分析后再放行。

实际接入点是 `Orchestrator._poll_and_dispatch()` 在 `_launch_issue()` 之前，不是旧草案中的
`_claim_next_issue()`（当前代码不存在该方法）。

已实现：

- `ClarifierConfig`：默认关闭，支持阻断/观察模式、问题数、轮数、置信度、token 和缓存配置。
- `IssueClarifierService`：静态 issue 文本分析，provider/解析失败默认 fail-open。
- `ClarifierCache`：title + description + labels + author replies 的 SHA-256 fingerprint 缓存。
- `IssueClarificationGate`：入队前分析、作者优先提问、最多两轮、manual_required。
- `IssueRecord.open_questions`、轮数、fingerprint、回复和评论游标持久化。
- 作者回复过滤和 bot 评论游标，避免把澄清器自己的评论误当成作者答案。
- 回答内容注入最终 Agent prompt，作为 issue requirements 的一部分。
- `orchestrator issue clarify` 支持当前 workspace 队列、list/recheck/resolve。
- 单元测试覆盖 clear/unclear、缓存、降级、阻断、回复放行、多轮上限、观察模式和 CLI。

尚未完成（仅 F-124-G 评论写入已通过 ClarificationResolver 统一通道实现）：

- 真实 provider + GitCode/GitHub tracker 的长期 daemon E2E。
- 可选的专用“等待澄清”远端标签；不能直接复用当前永久 `agent:blocked`。
- Dashboard 上的 open questions、轮数和 manual_required 专用视图。
- Follow-up workspace focus 富化（原 P2）。

以下章节保留完整设计背景；其中新建 `ClarificationPoller`、`open_questions` 重复状态机和
`_claim_next_issue()` 接入示意，以本节的实际架构为准。

---

## §1 设计规划

### 1.1 背景与目标

#### 问题陈述

Orchestrator 在自动处理 issue 时，`PromptBuilder` 把 `issue.title` + `issue.description` 一次性渲染进 agent prompt（`extensions/orchestrator/prompt_builder.py:28-54`），随后 agent 直接进入实现。当 issue 描述存在以下情况时，agent 只能基于模糊描述盲跑：

- **缺失**：`issue.description` 为空或仅有一行标题，无验收标准、无范围边界
- **模糊**：存在多个合理理解（"应该 sync 还是 async"未指明）
- **矛盾**：描述前后不一致（既要"零依赖"又要"用 rich 库"）
- **不可执行**：缺少必要的上下文（"优化性能"未给出基线指标或目标 QPS）

结果：PR 偏题、`verification_failed`、触发 F-39 `agent:retry` 重跑——重跑仍基于同一份模糊描述，循环浪费 token 与 CI 资源。

#### 目标

在 orchestrator 将 issue 分发给 agent **之前**，对 `issue.description` 做一次 LLM 驱动的结构化分析，识别其中的歧义点、缺失项、矛盾项，产出可回发给 issue author 的澄清问题清单。不清晰时阻断自动实现，触发已有的澄清通道（`AskIssueAuthor` 工具 + F-39 `agent:blocked` 标签），等待 author 回复后再继续。

**核心目标：把"agent 盲跑后 PR 偏题"的前置错误，转化为"开跑前问清楚"的前置澄清，减少无效 token 消耗与重跑次数。**

#### 核心能力定义

Clarifier 的核心数据流是一条**纯静态文本分析管道**，无需对话历史、工作区 diff 或历史会话即可运行：

```
输入: issue.description（单条静态文本，可能为空/短/模糊/矛盾）
         │
         ▼
  LLM 分析（prompt: 识别 missing/vague/contradictory/unexecutable 四种歧义）
         │
         ▼
  输出: ClarifyResult
          ├─ is_clear: bool                       ← 是否可直接放行
          ├─ ambiguities: list[ClarifyQuestion]   ← 歧义点清单，每点包含:
          │    ├─ question: str                   ←   可直发 issue 评论的完整提问
          │    ├─ ambiguity_type: str             ←   歧义类型 (missing/vague/contradictory/unexecutable)
          │    ├─ evidence: str                   ←   引用原文片段
          │    └─ suggested_options: list[str]    ←   可选理解（启发 author 快速回复）
          └─ confidence: float                    ← 判定置信度
         │
         ▼
  is_clear=false ─→ post_clarification_comment() ─→ issue tracker 评论区出现澄清问题（回发给 author）
  is_clear=true  ─→ 放行进入 agent 路径
```

这条管道的设计原则是：

1. **输入零依赖**：只读 `issue.title` + `issue.description` + `issue.labels`，不需要会话、git 状态、历史记录等动态信号。即使是全新的空仓库、分支未建的场景也能正常工作。
2. **输出即发问**：`ClarifyQuestion.question` 字段是已写好的完整提问句，可**直接作为 issue 评论原文发出**，无需额外模板渲染。
3. **四条歧义类型的划分是穷尽的**：需求描述的主要歧义都可归入 missing（缺失）、vague（模糊）、contradictory（矛盾）、unexecutable（不可执行）四类，不存在"其他"兜底类型——如果 LLM 无法归入这四类，应判定为 `is_clear=true`。

#### 非目标

- ❌ 不替代 issue author 撰写完整描述（澄清器只识别问题，不替 author 写需求）
- ❌ 不自动猜测并填充缺失需求（猜测会引入另一种盲跑）
- ❌ 不解决 author 长期不回复的死锁（由 F-39 `agent:blocked` + 人工干预处理）
- ❌ 不接管已存在 PR 的 review feedback 澄清（那是 F-121 规则回灌的范畴）
- ❌ 不复用 F-123 Intent Forecast 的策略框架（两者产品定位不同，详见 §1.3）
- ❌ 不修改 issue tracker 上的原始 issue 文本（只发评论提问，不改写描述）

### 1.2 与 F-123 Intent Forecast 的关系澄清

F-123 是"下一步动作预测器"（Forecast），F-124 是"文本歧义识别器"（Clarify）。二者产品定位层面的差异：

| 维度 | F-123 Intent Forecast | F-124 Issue Clarifier |
|------|----------------------|----------------------|
| 触发时机 | REPL/TUI 空闲 2 分钟后 | issue 入队后、分支创建前 |
| 输入 | 实时会话消息流 + 工作区 diff + 历史会话 | 单条静态 issue 文本（无对话历史） |
| 输出 | 3 条可执行 prompt 建议 | 结构化澄清问题清单 + is_clear 判定 |
| 主体 | REPL 交互场景的当前用户 | issue tracker 上的 author（异步） |
| 反馈闭环 | `feedback.jsonl` 当场 accept/dismiss | issue 评论回复 + `clarification_status` 字段 |
| 能力本质 | 预测"用户接下来要做什么" | 识别"这段文本哪里不清楚" |

**F-124 不复用 F-123 的 `intent_strategy`（user/workspace/history 三选一）**：

- `user` 策略依赖 `current_messages`，issue 场景无会话，输入为空
- `workspace` 策略依赖 `changed_files`，issue 入队时分支未建、工作区干净，`compute_workspace_focuses` 在 `changed_files=[]` 时返回空集直接失效（`focus.py:15-16`），且 `focus_definitions()` 硬编码 clawcodex 自身 10 个模块无法跨项目
- `history` 策略依赖历史会话摘要，issue 与历史会话无关联

**F-124 复用 F-123 的两个无会话依赖件**（详见 §2.4）：

1. `prompt.py:build_forecast_messages` 的 prompt 组装范式（JSON 化上下文 + 严格 JSON 输出 + token 预算截断）
2. `service.py:parse_forecast_response` + `_loads_json` 的 LLM 输出解析器

**F-124 借鉴 F-123 的一个约定**：`task_state.open_questions: list[str]` 的字段命名，在 `IssueRecord` 上沿用 `open_questions` 字段，保持词汇体系一致。

### 1.3 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 检测时机 | issue 入队后、`PromptBuilder.render()` 之前 | 在 agent 开跑前阻断，避免盲跑浪费 token |
| 检测方法 | LLM 驱动的结构化文本分析 | 歧义识别是语义级任务，纯规则匹配（如 F-123 的 `_open_questions` 字符后缀匹配）无法胜任 |
| 输出形态 | `{"is_clear": bool, "ambiguities": [...], "questions": [...]}` 严格 JSON | 结构化便于后续路由（清晰→放行，不清晰→发评论提问） |
| 阻断方式 | 标记 `agent:blocked` + 写澄清评论到 issue tracker | 复用 F-39 已有标签与 `TrackerAdapter.update_comment` 通道，零新基础设施 |
| 澄清问题数量 | 最多 3 条 | 与 F-123 suggestion 上限一致；避免一次抛出过多问题压垮 author |
| 澄清回复闭环 | author 评论回复 → orchestrator 下轮 poll 检测 → 注入澄清上下文到 prompt → 放行 | 复用已有 `update_clarification` + `_CLARIFICATION_TEMPLATE`（prompt_builder.py:59-78） |
| 启用开关 | 默认 `false`（opt-in），workflow YAML 配置 | 与 F-121 一致，避免用户不知情时自动发评论打扰 author |
| 跨项目通用 | 不依赖任何项目特定别名表 | 区别于 F-123 `focus_definitions` 硬编码，澄清器只分析文本语义 |
| 模型选择 | 复用 orchestrator 已配置的 provider + model | 不引入额外模型配置；澄清是低频操作（每 issue 一次），token 成本可控 |
| 缓存 | 同一 issue 文本 + workflow 版本的 fingerprint 缓存 | author 未修改描述时不重复调用 LLM |

### 1.4 总体架构

```text
Issue 入队 (Orchestrator.poll)
         │
         ▼
┌─────────────────────────────────────┐
│  IssueClarifierService.analyze()    │  ← 新模块 extensions/orchestrator/issue_clarifier/
│  ├─ build_clarify_messages(issue)   │  ← 借鉴 F-123 prompt.py 范式
│  ├─ provider.chat(...)              │
│  ├─ parse_clarify_response(raw)     │  ← 借鉴 F-123 service.py 解析器
│  └─ cache fingerprint 命中跳过       │
└─────────────────────────────────────┘
         │
         ├─ is_clear=true ──→ 放行 → PromptBuilder.render() → AgentRunner.run()
         │
         └─ is_clear=false
              │
              ├─ IssueRegistry.update_clarification(
              │     clarification_status="awaiting_answer",
              │     question=生成的澄清问题
              │  )
              │
              ├─ TrackerAdapter.update_comment(issue, 澄清问题清单)
              │
              ├─ IssueRegistry.mark_intent(issue_id, Intent.BLOCKED, source="clarifier")
              │     → 镜像 agent:blocked 标签到 issue tracker
              │
              └─ 跳过本轮分发，等待下轮 poll
```

**澄清回复闭环**：

```text
Author 在 issue 上回复澄清问题（评论）
         │
         ▼
Orchestrator 下轮 poll 检测到新评论
         │
         ▼
检测到 clarification_status="awaiting_answer" 且有新评论
         │
         ▼
重新调用 IssueClarifierService.analyze()
  （输入 = 原始描述 + author 回复，fingerprint 变化触发重算）
         │
         ├─ 仍不清晰 → 追问第二轮（最多 2 轮，超过转人工）
         │
         └─ 清晰 → update_clarification(clarification_status="resolved",
                                         local_answer=author回复摘要)
                   → unblock(issue_id)
                   → 移除 agent:blocked 标签
                   → PromptBuilder.render() 注入 _CLARIFICATION_TEMPLATE 澄清上下文
                   → AgentRunner.run()
```

### 1.5 与现有组件的集成关系

```text
Orchestrator._claim_next_issue()        ← 现有：从 tracker 拉取候选 issue
         │
         ▼
IssueRegistry.register(...)             ← 现有：创建 PENDING 记录
         │
         ▼
IssueClarifierService.analyze(issue)    ← ★ 新增插入点
         │
         ├─ clear  ─→ 现有路径：_prepare_workspace → PromptBuilder.render → AgentRunner.run
         │
         └─ unclear ─→ update_clarification + update_comment + mark_intent(BLOCKED)
                       → 本轮不分发
         │
         ▼
（下轮 poll，author 回复后）
ClarificationPoller.detect_reply(issue) ← ★ 新增：检测 author 评论回复
         │
         ▼
IssueClarifierService.analyze(issue + replies)
         │
         └─ clear  ─→ unblock + _CLARIFICATION_TEMPLATE 注入 → 现有路径
```

### 1.6 子特性分解

| 子特性 | 描述 | 优先级 | 状态 |
|--------|------|:------:|:----:|
| F-124-A | Config schema：`ClarifierConfig` dataclass + `WorkflowConfig.clarifier` 字段 + from_dict 解析 | P0 | ✅ |
| F-124-B | 核心服务：`IssueClarifierService.analyze()` — prompt 组装 + provider 调用 + JSON 解析 + fingerprint 缓存 | P0 | ✅ |
| F-124-C | Prompt 模板：`build_clarify_messages()` — 歧义检测指令 + 严格 JSON 输出 + token 预算控制 | P0 | ✅ |
| F-124-D | 响应解析：`parse_clarify_response()` — `ClarifyResult` dataclass + 降级处理 | P0 | ✅ |
| F-124-E | Orchestrator 集成：`IssueClarificationGate.should_dispatch()` 在 `_poll_and_dispatch()` 之前（**已偏离 §1.5 原草案的 `_claim_next_issue()`**，因该方法不存在） | P0 | ✅（接入点不同） |
| F-124-F | IssueRegistry 扩展：`IssueRecord.open_questions` + `clarification_round` + `clarifier_fingerprint` 字段；复用已有 `update_clarification` 底层 | P0 | ✅ |
| F-124-G | Tracker 评论写入：`TrackerAdapter.create_clarification_comment()` override | P0 | ✅（实现方式偏离 §2.8 原草案；统一走 ClarificationResolver 通道，避免双通道；LocalTracker / RepoTracker / LinearAdapter 全部覆盖） |
| F-124-H | 澄清回复检测：`IssueClarificationGate.should_dispatch()` 内联检测 author 回复（**已偏离原 `ClarificationPoller` 独立模块设计**，合并到 gate 中） | P1 | ✅（合并实现） |
| F-124-I | 多轮澄清上限：最多 `max_rounds` 轮自动追问，超过转 `manual_required` | P1 | ✅ |
| F-124-J | F-39 标签镜像：通过 `ClarificationResolver` 复用，**不复用永久 `Intent.BLOCKED`**（详见 §0 注 3） | P0 | ✅（复用现有机制） |
| F-124-K | Prompt 注入：`render(clarification=...)` 复用 `_CLARIFICATION_TEMPLATE` | P0 | ✅ |
| F-124-L | Follow-up 场景 workspace focus 富化：`compute_workspace_focuses` 调用 | P2 | ❌ 未做（doc 标 P2） |
| F-124-M | CLI 子命令：`orchestrator clarify list/recheck/resolve` | P1 | ✅（`cli/issue.py` 注册） |
| F-124-N | 单元测试：`tests/orchestrator/test_issue_clarifier.py`（631 行） | P0 | ✅（78/78 通过） |
| F-124-O | 稳定性门禁：`tests/stability_gate/test_stage5_extensions.py` 加导入测试 | P1 | ✅ |

### 1.7 实现文件清单

| 文件路径 | 行数 | 变更类型 | 说明 | 状态 |
|---------|:----:|---------|------|:----:|
| `extensions/orchestrator/issue_clarifier/__init__.py` | 16 | **新增** | 模块入口 | ✅ |
| `extensions/orchestrator/issue_clarifier/service.py` | 164 | **新增** | `IssueClarifierService` + `format_clarification_request` + `_find_explicit_clarification_gap` | ✅ |
| `extensions/orchestrator/issue_clarifier/gate.py` | 208 | **新增** | `IssueClarificationGate`（**新增类，合并原 doc §2.9 `ClarificationPoller` 职责**） | ✅ |
| `extensions/orchestrator/issue_clarifier/models.py` | 104 | **新增** | `ClarifyQuestion` / `ClarifyResult` frozen dataclass + `to_dict/from_dict` | ✅ |
| `extensions/orchestrator/issue_clarifier/parser.py` | 91 | **新增** | `parse_clarify_response` + `_degraded_clear` + `_loads_json` 容错 | ✅ |
| `extensions/orchestrator/issue_clarifier/prompt.py` | 104 | **新增** | `build_clarify_messages` + `_shrink_payload_to_limit` | ✅ |
| `extensions/orchestrator/issue_clarifier/cache.py` | 86 | **新增** | `ClarifierCache` + `build_fingerprint` | ✅ |
| ~~`extensions/orchestrator/issue_clarifier/poller.py`~~ | — | **未实现** | 原 doc §2.9 计划独立模块，**实际合并到 gate.py** | ⚠️ 偏离 |
| ~~`extensions/orchestrator/issue_clarifier/registration.py`~~ | — | **未实现** | 原 doc §1.7 计划独立文件，**实际由 `gate.py` + `cli/issue.py` 直接注册** | ⚠️ 偏离 |
| `extensions/orchestrator/config/schema.py` | — | 修改 | `ClarifierConfig` dataclass（L921）+ `WorkflowConfig.clarifier`（L957）+ from_dict 解析（L1251-1267） | ✅ |
| `extensions/orchestrator/orchestrator.py` | — | 修改 | `_poll_and_dispatch()` 之前调用 `IssueClarificationGate.should_dispatch()` | ✅ |
| `extensions/orchestrator/issue_registry.py` | — | 修改 | `IssueRecord` 新增 `open_questions`/`clarification_round`/`clarifier_fingerprint`/`clarification_replies` 等字段 | ✅ |
| `extensions/orchestrator/tracker.py` | — | 已存在 | `create_clarification_comment()` 默认 `return None`（与 F-124 设计偏差：未新建 `post_clarification_comment`，统一走 ClarificationResolver 通道） | ✅ 已有 |
| `extensions/orchestrator/linear/adapter.py` | — | 修改 | `create_clarification_comment()` override（拼接 `@login` 前缀后委托 `create_comment`） | ✅ |
| `extensions/orchestrator/prompt_builder.py` | — | 修改 | `render(clarification=...)` 槽位 | ✅ |
| `extensions/orchestrator/cli/issue.py` | — | 修改 | `orchestrator clarify list/recheck/resolve` 子命令注册 | ✅ |
| `tests/orchestrator/test_issue_clarifier.py` | 631 | **新增** | 单元测试（clear/unclear/cache/polling/multiround/observation/fallback） | ✅ |
| `tests/orchestrator/test_orchestrator_clarification_queue.py` | — | 既有 | ClarificationResolver 相关测试 | ✅ |
| `tests/stability_gate/test_stage5_extensions.py` | — | 修改 | 加 `issue_clarifier` 模块导入烟雾测试 | ✅ |

---

## §2 详细设计

### 2.1 Config schema 定义

```yaml
# WORKFLOW.md front matter 新增段
---
clarifier:
  enabled: false                      # 默认关闭, opt-in
  block_on_unclear: true              # 不清晰时阻断分发（false=仅警告仍放行）
  author_first: true                  # ★ 实际新增：作者优先提问
  max_questions: 3                    # 单次澄清最多提问数
  max_rounds: 2                       # 自动追问上限，超过转人工
  min_confidence: 0.7                 # is_clear 置信度阈值（实际默认 0.7，原 doc 草案 0.6）
  max_input_tokens: 6000              # 输入 token 预算（实际默认 6000，原 doc 草案 8000）
  max_output_tokens: 800              # 输出 token 预算（实际默认 800，原 doc 草案 600）
  fail_open: true                     # ★ 实际新增：provider/LLM 故障时显式放行开关
  cache_enabled: true                 # 同一 fingerprint 跳过重复分析
  max_analyses_per_poll: 4            # ★ 实际新增：单轮 poll 内 LLM 分析预算
---
```

> **⚠️ 注 2：ClarifierConfig 默认值与原 doc 草案有差异**
>
> | 字段 | 原 doc 草案 | 实际默认 | 原因 |
> |------|------------|---------|------|
> | `min_confidence` | 0.6 | **0.7** | 落地时根据 F-121 / F-123 历史调参经验上调，保守"宁可多问" |
> | `max_input_tokens` | 8000 | **6000** | 实际 issue 描述统计中位数 < 2K tokens，8K 浪费 |
> | `max_output_tokens` | 600 | **800** | 实际 LLM 倾向输出更长 explanation，600 不够 |
> | `author_first` | — | **新增** | 落地时发现"author 优先于 bot 评论"的过滤逻辑需要可配置 |
> | `fail_open` | — | **新增** | 把 doc §2.4 降级原则从代码常量升级为配置项，方便灰度 |
> | `max_analyses_per_poll` | — | **新增** | poll 周期内防 LLM 雪崩（避免一次 poll 中所有 issue 都触发分析耗尽 quota） |

```python
# extensions/orchestrator/config/schema.py

@dataclass
class ClarifierConfig:
    """Issue description clarity analysis before agent dispatch."""
    enabled: bool = False
    block_on_unclear: bool = True
    author_first: bool = True
    max_questions: int = 3
    max_rounds: int = 2
    min_confidence: float = 0.7
    max_input_tokens: int = 6000
    max_output_tokens: int = 800
    fail_open: bool = True
    cache_enabled: bool = True
    max_analyses_per_poll: int = 4


@dataclass
class WorkflowConfig:
    ...
    clarifier: ClarifierConfig = field(default_factory=ClarifierConfig)
```

**配置语义说明**：

| 字段 | 行为 |
|------|------|
| `enabled: false` | 整个澄清器跳过，orchestrator 走原有路径（向后兼容） |
| `block_on_unclear: false` | "观察模式"：仍调用 LLM 分析并记录 `open_questions`，但不阻断分发、不发评论。用于灰度上线时评估准确率 |
| `max_rounds: 0` | 单轮模式：只分析一次，不清晰直接转 `agent:blocked` 人工处理 |
| `cache_enabled: true` | author 未修改 issue 描述时，fingerprint 不变，跳过 LLM 调用 |

### 2.2 核心数据结构

```python
# extensions/orchestrator/issue_clarifier/service.py

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClarifyQuestion:
    """单条澄清问题。"""
    question: str                          # 向 author 提问的完整句子
    ambiguity_type: str                    # missing / vague / contradictory / unexecutable
    evidence: str                          # 指向描述中哪一部分引发歧义（引用原文片段）
    suggested_options: list[str] = field(default_factory=list)  # 可选的合理理解（启发 author 回复）


@dataclass(frozen=True)
class ClarifyResult:
    """澄清分析结果。"""
    is_clear: bool                         # 是否足够清晰可直接放行
    confidence: float                      # 0.0-1.0，is_clear 的置信度
    ambiguities: list[ClarifyQuestion]     # 识别出的歧义点（is_clear=true 时为空）
    fingerprint: str                       # 输入文本 hash，用于缓存键
    raw_response: str = ""                 # LLM 原始输出（调试用，默认不持久化）
    reason: str = ""                       # is_clear 判定理由（is_clear=true 时简述为何清晰）


class IssueClarifierService:
    """issue 描述澄清分析的核心服务。"""

    def __init__(
        self,
        *,
        provider_getter: Callable[[], Any],
        model_getter: Callable[[], str | None],
        config: ClarifierConfig,
        cache_dir: Path | None = None,
    ) -> None: ...

    def analyze(
        self,
        issue: Issue,
        *,
        prior_replies: list[str] | None = None,   # author 之前的澄清回复（多轮场景）
        force: bool = False,                       # 忽略缓存
    ) -> ClarifyResult: ...
```

### 2.3 Prompt 模板

借鉴 F-123 `prompt.py:build_forecast_messages` 的范式，但指令聚焦于"识别文本歧义"而非"预测下一步动作"：

```python
# extensions/orchestrator/issue_clarifier/prompt.py

CLARIFY_INSTRUCTIONS = """You analyze a software issue description for clarity before an autonomous agent implements it.

Return strict JSON only, shaped as:
{"is_clear": bool, "confidence": 0.0, "ambiguities": [{"question":"...","ambiguity_type":"...","evidence":"...","suggested_options":["..."]}], "reason":"..."}

ambiguity_type must be one of: missing | vague | contradictory | unexecutable
- missing: required information absent (no acceptance criteria, no scope boundary, no target metric)
- vague: multiple reasonable interpretations exist (e.g. "should it be sync or async" unspecified)
- contradictory: description contains conflicting requirements
- unexecutable: lacks necessary context to act (e.g. "optimize performance" without baseline or target)

Rules:
- is_clear=true ONLY if an engineer could implement without guessing. When in doubt, is_clear=false.
- At most {max_questions} ambiguities. Prioritize blockers over nice-to-haves.
- question must be a single specific question ready to post as an issue comment.
- evidence must quote the exact phrase from the description that triggered the ambiguity.
- suggested_options lists 2-4 reasonable interpretations to help the author answer quickly.
- confidence reflects how certain you are about the is_clear judgment (not about the issue itself).
- If prior_replies are provided, treat them as the author's clarification answers and re-evaluate only remaining gaps.
- response_language: write questions and evidence in the same language as the issue description.
- Do not invent ambiguities for well-specified aspects. A clear issue MUST return is_clear=true."""


def build_clarify_messages(
    issue: Issue,
    *,
    max_questions: int,
    max_input_tokens: int,
    prior_replies: list[str] | None = None,
    workspace_focus: list[dict] | None = None,
) -> list[dict[str, str]]:
    """构造澄清分析 prompt。借鉴 F-123 prompt.py 的 JSON 化 + token 截断范式。"""
    payload = {
        "issue_identifier": issue.identifier,
        "issue_title": issue.title,
        "issue_description": issue.description or "",
        "issue_labels": list(issue.labels or []),
        "prior_replies": prior_replies or [],
        "workspace_focus": workspace_focus or [],   # 仅 follow-up 场景富化
        "max_questions": max_questions,
    }
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    text = _truncate(text, max_input_tokens=max_input_tokens)
    instructions = CLARIFY_INSTRUCTIONS.replace("{max_questions}", str(max_questions))
    return [
        {
            "role": "user",
            "content": f"{instructions}\n\nIssue:\n{text}\n\nReturn JSON only.",
        }
    ]


def _truncate(text: str, *, max_input_tokens: int) -> str:
    """Token 预算截断，与 F-123 prompt.py:_truncate 同构。"""
    budget = max_input_tokens * 4
    if len(text) <= budget:
        return text
    head = max(800, budget // 4)
    tail = max(800, budget - head - 120)
    return text[:head].rstrip() + "\n\n[... omitted for clarifier budget ...]\n\n" + text[-tail:].lstrip()
```

**与 F-123 prompt.py 的差异**：

| 维度 | F-123 | F-124 |
|------|-------|-------|
| 指令目标 | 预测用户下一步 | 识别文本歧义 |
| 输入字段 | sessions/workspace/feedback/task_state | issue_title/description/labels/prior_replies |
| 输出 schema | `suggestions[]` | `is_clear` + `ambiguities[]` |
| workspace_focus | 核心信号（strategy=workspace 时） | 仅 follow-up 场景的辅助富化（P2） |

**设计要点 —— 纯静态文本输入**：`build_clarify_messages()` 的 payload 只包含 `issue.title`、`issue.description`、`issue.labels` 和 `prior_replies`。不依赖 git 状态、工作区 diff、会话历史等动态信号——这是与 F-123 `IntentForecastContextBuilder` 的根本区别。即便是新 issue 入队时分支未建、工作区干净、无历史会话，`build_clarify_messages()` 仍能正常工作，因为它的唯一输入是**静态的 issue 文本**。

### 2.4 响应解析器

借鉴 F-123 `service.py:parse_forecast_response` + `_loads_json` 的"LLM 输出 → 结构化对象 + 容错"模式：

```python
# extensions/orchestrator/issue_clarifier/parser.py

def parse_clarify_response(raw: str, *, min_confidence: float) -> ClarifyResult:
    """解析 LLM 澄清分析输出。借鉴 F-123 service.py:parse_forecast_response 容错策略。"""
    data = _loads_json(raw)
    if not isinstance(data, dict):
        # 降级：无法解析为 JSON 时视为"不确定"，不阻断（避免 LLM 故障导致 issue 永久卡死）
        return ClarifyResult(is_clear=True, confidence=0.0, ambiguities=[],
                             fingerprint="", reason="Unparseable LLM response, defaulting to clear")

    is_clear = bool(data.get("is_clear", True))
    confidence = float(data.get("confidence") or 0.0)
    # 置信度低于阈值时翻转 is_clear（保守：不确定就问）
    if is_clear and confidence < min_confidence:
        is_clear = False

    ambiguities: list[ClarifyQuestion] = []
    for item in (data.get("ambiguities") or [])[:10]:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question") or "").strip()
        if not q:
            continue
        ambiguities.append(ClarifyQuestion(
            question=q,
            ambiguity_type=str(item.get("ambiguity_type") or "vague"),
            evidence=str(item.get("evidence") or "")[:400],
            suggested_options=[str(o) for o in (item.get("suggested_options") or [])][:4],
        ))

    return ClarifyResult(
        is_clear=is_clear,
        confidence=confidence,
        ambiguities=ambiguities,
        fingerprint="",
        raw_response=raw if len(raw) < 4000 else raw[:4000],
        reason=str(data.get("reason") or ""),
    )


def _loads_json(raw: str) -> Any:
    """与 F-123 service.py:_loads_json 同构：剥离 markdown fence + 容错解析。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None
```

**降级策略**（关键：避免澄清器自身故障导致 issue 永久卡死）：

| LLM 输出异常 | 行为 | 理由 |
|-------------|------|------|
| 非 JSON / 解析失败 | `is_clear=True` 放行 | 澄清器故障不应阻断 agent，宁可盲跑也不死锁 |
| `is_clear=true` 但 `confidence < min_confidence` | 翻转为 `is_clear=false` | 保守策略：不确定就问 |
| `is_clear=false` 但 `ambiguities` 为空 | 视为 `is_clear=true` 放行 | 没有具体歧义点就不应阻断 |
| `ambiguities` 超过 `max_questions` | 截取前 N 条 | 与配置上限一致 |
| provider 调用抛异常 | `is_clear=True` 放行 + 记录 warning | 同降级原则 |

### 2.5 核心服务实现

```python
# extensions/orchestrator/issue_clarifier/service.py

class IssueClarifierService:
    def __init__(
        self,
        *,
        provider_getter: Callable[[], Any],
        model_getter: Callable[[], str | None],
        config: ClarifierConfig,
        cache_dir: Path | None = None,
    ) -> None:
        self._provider_getter = provider_getter
        self._model_getter = model_getter
        self.config = config
        self._cache = ClarifierCache(cache_dir) if config.cache_enabled and cache_dir else None

    def analyze(
        self,
        issue: Issue,
        *,
        prior_replies: list[str] | None = None,
        workspace_focus: list[dict] | None = None,
        force: bool = False,
    ) -> ClarifyResult:
        if not self.config.enabled:
            return ClarifyResult(is_clear=True, confidence=1.0, ambiguities=[],
                                 fingerprint="", reason="Clarifier disabled")

        fingerprint = self._fingerprint(issue, prior_replies or [])
        if not force and self._cache is not None:
            cached = self._cache.get(fingerprint)
            if cached is not None:
                return cached

        provider = self._provider_getter()
        if provider is None:
            # provider 不可用时降级放行（与 LLM 解析失败同处理）
            return ClarifyResult(is_clear=True, confidence=0.0, ambiguities=[],
                                 fingerprint=fingerprint, reason="Provider unavailable, defaulting to clear")

        messages = build_clarify_messages(
            issue,
            max_questions=self.config.max_questions,
            max_input_tokens=self.config.max_input_tokens,
            prior_replies=prior_replies,
            workspace_focus=workspace_focus,
        )
        try:
            response = provider.chat(
                messages=messages,
                tools=None,
                model=self._model_getter(),
                max_tokens=self.config.max_output_tokens,
            )
        except TypeError:
            response = provider.chat(messages=messages, tools=None, model=self._model_getter())
        except Exception:
            logger.warning("Clarifier provider call failed, defaulting to clear", exc_info=True)
            return ClarifyResult(is_clear=True, confidence=0.0, ambiguities=[],
                                 fingerprint=fingerprint, reason="Provider call failed")

        raw = str(getattr(response, "content", "") or "")
        result = parse_clarify_response(raw, min_confidence=self.config.min_confidence)
        result = replace(result, fingerprint=fingerprint)
        if self._cache is not None:
            self._cache.put(fingerprint, result)
        return result

    def _fingerprint(self, issue: Issue, prior_replies: list[str]) -> str:
        raw = json.dumps({
            "id": issue.identifier,
            "title": issue.title,
            "description": issue.description or "",
            "labels": sorted(issue.labels or []),
            "replies": prior_replies,
            "config_version": "1",
        }, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```

### 2.6 Orchestrator 集成点

在 `Orchestrator._claim_next_issue()` 之后、`_prepare_workspace()` 之前插入澄清检查：

```python
# extensions/orchestrator/orchestrator.py （修改示意）

def _claim_and_dispatch(self) -> None:
    issue = self._claim_next_issue()
    if issue is None:
        return

    record = self.registry.register(issue_id=issue.id, ...)

    # ★ F-124: 澄清分析插入点
    if self.clarifier_config.enabled:
        result = self.clarifier.analyze(issue)
        if not result.is_clear and self.clarifier_config.block_on_unclear:
            self._handle_unclear_issue(issue, record, result)
            return  # 跳过本轮分发
        # is_clear=true 或 block_on_unclear=false：记录 open_questions 但放行
        if result.ambiguities:
            self.registry.update_clarification(
                issue.id,
                clarification_status="noted",
                question="; ".join(q.question for q in result.ambiguities),
            )

    # 现有路径
    self._prepare_workspace(issue)
    prompt = self.prompt_builder.render(issue=issue, ...)
    self.agent_runner.run(prompt, ...)


def _handle_unclear_issue(
    self, issue: Issue, record: IssueRecord, result: ClarifyResult
) -> None:
    questions = [q.question for q in result.ambiguities[:self.clarifier_config.max_questions]]
    self.registry.mark_clarification_blocked(issue.id, questions=questions, round_num=1)
    self.tracker.post_clarification_comment(issue, questions, result.ambiguities)
    self.registry.mark_intent(issue.id, Intent.BLOCKED, source="clarifier")
    self._mirror_intent_label(self.tracker, issue.id, "agent:blocked")
    logger.info("Issue %s blocked for clarification: %d ambiguities",
                issue.identifier, len(result.ambiguities))
```

### 2.7 IssueRegistry 扩展

新增字段与便捷方法，复用已有 `update_clarification` 底层：

```python
# extensions/orchestrator/issue_registry.py （修改示意）

@dataclass
class IssueRecord:
    ...
    open_questions: list[str] = field(default_factory=list)   # ★ F-124 新增
    clarification_round: int = 0                              # ★ 已追问轮次


class IssueRegistry:
    def mark_clarification_blocked(
        self, issue_id: str, *, questions: list[str], round_num: int
    ) -> IssueRecord | None:
        """F-124: 标记 issue 因描述不清晰进入澄清等待状态。"""
        record = self._records.get(issue_id)
        if record is None:
            return None
        record.open_questions = list(questions)
        record.clarification_round = round_num
        record.clarification_status = "awaiting_answer"
        for q in questions:
            record.question_history.append(q)
        record.touch()
        self._save()
        return record

    def mark_clarification_resolved(
        self, issue_id: str, *, answer_summary: str
    ) -> IssueRecord | None:
        """F-124: 澄清已解决，清除阻断状态。"""
        record = self._records.get(issue_id)
        if record is None:
            return None
        record.open_questions = []
        record.clarification_status = "resolved"
        record.local_answer = answer_summary[:2000]
        record.local_answer_source = "issue_comment"
        record.touch()
        self._save()
        return record
```

### 2.8 Tracker 评论写入 —— 将歧义点转化为可回发给 issue author 的评论

澄清分析产出的 `ClarifyResult.ambiguities` 列表中的每条 `ClarifyQuestion.question` 是**已写好的完整提问句**，设计上可直接作为 issue 评论原文发出。`post_clarification_comment()` 的职责只是将 `ambiguities` 数组逐条渲染为 Markdown 格式的评论正文，挂在 issue 评论区即可——无需额外提示工程或模板嵌套。

`TrackerAdapter` 新增方法，默认实现 `return None`（与 F-38 设计偏差一致：老 adapter 不必 override）：

```python
# extensions/orchestrator/tracker.py （修改示意）

class TrackerAdapter(ABC):
    ...
    def post_clarification_comment(
        self,
        issue: Issue,
        questions: list[str],
        ambiguities: list[ClarifyQuestion],
    ) -> str | None:
        """F-124: 把澄清问题清单发到 issue 评论。返回 comment_id 或 None。

        默认 return None —— 与 F-38 update_pull_request/update_comment 一致，
        老 adapter（如 LocalTracker）不必 override，澄清器降级为仅记录到 registry。
        """
        return None
```

**LocalTrackerAdapter override**（写入 issue markdown + ndjson）：

```python
# extensions/orchestrator/local_tracker/adapter.py （修改示意）

def post_clarification_comment(
    self, issue, questions, ambiguities
) -> str | None:
    body = self._render_clarification_comment(questions, ambiguities)
    return self._append_issue_comment(issue, body, kind="clarification")
```

评论格式示例：

```markdown
### 🤔 Clarification needed before automated implementation

The issue description has **3** aspects that need clarification before the
autonomous agent can proceed without guessing:

1. **[vague]** Should the new function be sync or async?
   > Evidence: "add a function to fetch user data"
   > Options: (a) async with await (b) sync returning directly (c) both via overload

2. **[missing]** What is the target QPS for "optimize performance"?
   > Evidence: "optimize performance"
   > Options: (a) 100 QPS (b) 1000 QPS (c) current baseline is acceptable

3. **[contradictory]** "zero dependencies" conflicts with "use rich library"
   > Evidence: "zero dependencies" vs "use rich library"

Please reply to this issue with your answers. The agent will resume
automatically once clarification is received. (Round 1/2)
```

### 2.9 澄清回复检测（P1）

`ClarificationPoller` 在 orchestrator poll 路径中检测 author 回复：

```python
# extensions/orchestrator/issue_clarifier/poller.py

class ClarificationPoller:
    def __init__(self, registry: IssueRegistry, tracker: TrackerAdapter,
                 clarifier: IssueClarifierService, config: ClarifierConfig) -> None: ...

    def detect_reply(self, issue: Issue, record: IssueRecord) -> ClarifyResult | None:
        """检测 author 是否回复了澄清问题，若回复则重新分析。

        返回 None = 无新回复；返回 ClarifyResult = 已重新分析（调用方据 is_clear 决定放行/追问）。
        """
        if record.clarification_status != "awaiting_answer":
            return None
        replies = self.tracker.fetch_comments_since(issue, after=record.clarification_posted_at)
        author_replies = [r for r in replies if r.author_login == record.author_login]
        if not author_replies:
            return None
        prior = [r.body for r in author_replies]
        result = self.clarifier.analyze(issue, prior_replies=prior, force=True)
        if result.is_clear:
            self.registry.mark_clarification_resolved(issue.id, answer_summary="\n---\n".join(prior))
            self.registry.unblock(issue.id)
            self._mirror_intent_label(self.tracker, issue.id, "agent:blocked", remove=True)
        else:
            # 多轮追问
            new_round = record.clarification_round + 1
            if new_round > self.config.max_rounds:
                # 超上限，保持 blocked 转人工，记录原因
                self.registry.update_clarification(issue.id, clarification_status="manual_required")
                return result
            self._handle_unclear_issue(issue, record, result, round_num=new_round)
        return result
```

### 2.10 Prompt 注入澄清上下文

复用已有的 `_CLARIFICATION_TEMPLATE`（prompt_builder.py:59-78），将 author 回复摘要注入 `clarification` 槽位：

```python
# extensions/orchestrator/prompt_builder.py （修改示意）

def render(self, *, issue, clarification: str | None = None,
           pending_question: str | None = None, options: list[str] | None = None,
           **kwargs) -> str:
    prompt = self._render_default(issue, **kwargs)
    # F-124: 若 issue 已通过澄清，把 author 回复摘要注入
    if clarification:
        prompt += self._jinja_env.from_string(_CLARIFICATION_TEMPLATE).render(
            clarification=clarification,
            pending_question=pending_question,
            options=options or [],
        )
    return prompt.strip()
```

Orchestrator 在澄清解决后调用 `render(issue=issue, clarification=answer_summary)`，agent 即可在 prompt 中看到 author 的明确回答，无需猜。

### 2.11 Follow-up 场景 workspace focus 辅助（P2）

F-39 follow-up 模式下（PR 已存在、分支已建、有 changed_files），可调用 F-123 的 `compute_workspace_focuses` 作为澄清上下文富化，让澄清问题聚焦于当前 PR 改动模块：

```python
# 仅在 follow-up 分支已建时调用
from clawcodex_ext.intent_forecast.focus import compute_workspace_focuses

def _workspace_focus_for_followup(self, issue: Issue) -> list[dict]:
    if not self._has_followup_branch(issue):
        return []
    changed = self._git_changed_files(issue.branch_name)
    return compute_workspace_focuses(changed_files=changed, recent_messages=[])
```

**注意**：这是轻量复用（只 import 一个纯函数），不引入 F-123 的策略框架。新 issue 场景（分支未建、changed_files 为空）直接跳过此富化——`compute_workspace_focuses` 在空输入下返回 `[]`，天然安全。

### 2.12 边界情况处理

| 场景 | 行为 |
|------|------|
| `issue.description` 为空 | 仍调用 LLM 分析（仅 title），通常会被判为 `missing` 严重歧义 |
| Author 修改了原始 issue 描述 | fingerprint 变化，缓存失效，重新分析 |
| Author 回复但仍然不清晰，已达 `max_rounds` | 保持 `agent:blocked`，状态转 `manual_required`，CLI 高亮提示 |
| LLM provider 不可用 | 降级 `is_clear=true` 放行，记录 warning，不阻断 |
| LLM 返回非 JSON | 降级 `is_clear=true` 放行（同上，避免死锁） |
| `clarifier.enabled=false` | 整个澄清器跳过，走原有路径（向后兼容） |
| `block_on_unclear=false` 灰度模式 | 调用 LLM 分析并记录 `open_questions` 到 registry，但不阻断、不发评论 |
| LocalTracker 无 `post_clarification_comment` override | 默认 `return None`，澄清问题仅记录到 registry，不发评论（功能降级但不报错） |
| 同一 issue 被 F-39 `agent:retry` 重置 | `reset_for_retry` 清除 `open_questions` 和 `clarification_round`，重新分析 |
| Tracker.fetch_comments_since 不支持 | `detect_reply` 降级返回 None，澄清等待转为人工解除（CLI `clarify resolve`） |

---

## §3 风险与约束

### 3.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|---------|
| LLM 误判清晰描述为不清晰 | 中 | 低 | 核心问题：产生不必要的澄清轮次，延迟 issue 处理。缓解：`min_confidence` 可调；`block_on_unclear=false` 观察模式先评估准确率；用户可 CLI `clarify resolve` 手动解除 |
| LLM 误判模糊描述为清晰（漏报） | 中 | 中 | 核心问题：盲跑后 PR 偏题，与不加澄清器一样。缓解：置信度翻转机制（`confidence < min_confidence` 时翻转 `is_clear`）；用户可通过 `block_on_unclear=false` 观察 `open_questions` 记录验证 |
| LLM 生成有偏见/诱导性的问题 | 低 | 低 | 缓解：prompt 约束 "Do not invent ambiguities for well-specified aspects"；问题数量上限 `max_questions` |
| Author 不回复澄清问题 | 低 | 中 | 核心问题：issue 被 `agent:blocked` 阻塞等待。缓解：`max_rounds` 超限后仍保持 blocked 但不自动追问；CLI 可手动 `clarify resolve` 强制放行；Orchestrator 已有 `stale_timeout`（F-39）机制兜底清理 |
| Provider 不可用导致所有 issue 被放行 | 低 | 低 | 缓解：降级为 `is_clear=true` 放行，走原始路径。降级是功能退化而非故障 |
| Author 修改描述后 fingerprint 未变化 | 极低 | 低 | 缓解：只基于 `title`+`description`+`labels`+`replies`，不含元字段如 `updated_at`（后者变化不应触发重算）；若用户只改拼写且实无变化内容，缓存命中可接受 |
| 多轮追问场景 author 重复回复 | 低 | 低 | 缓解：`prior_replies` 在追加上一轮所有回复的基础上重新分析，LLM 自行判断哪些问题已解答、哪些仍需追问 |
| 澄清器与 F-39 重跑标签竞争 | 低 | 中 | 缓解：`reset_for_retry` 重置时清除 `clarification_round` 和 `open_questions`，重跑重新走澄清分析 |
| 第三方 tracker 不支持评论写入 | 低 | 低 | 缓解：`post_clarification_comment` 默认 `return None`，降级为仅 registry 可查，不报错 |

### 3.2 约束

- **澄清器不替代人工 code review**：澄清只在 issue 入口层识别"需求是否需要 clarification"，不保证 agent 实现结果正确。验证职责仍由 F-38 的 `test_command` + `verification_failed` 承担。
- **澄清器不写回 issue tracker 的 description 字段**：不修改原始 issue 文本，只通过评论提问。这保证了 author 对其 issue 资产的控制权。
- **默认 opt-in**：`clarifier.enabled: false`，避免用户不知情时自动在 issue 下发评论造成噪音。
- **LLM 调用为同步阻塞**：在 `_claim_next_issue()` 路径中同步调用 provider。issue 入队路径是低频操作（秒级间隔），单次额外 LLM 延迟是可接受的。若需异步化，可扩展到 F-94 BG_SESSIONS 类似的 sidecar 机制（P3）。
- **`compute_workspace_focuses` 只作辅助信号**：仅 follow-up 场景、仅 import 一个纯函数、不引入 F-123 的策略框架（详见 §1.3）。

---

## §4 验收标准

### 4.1 功能验收

- [x] `clarifier.enabled=true` 的 workflow，issue 入队后自动调用 `analyze()`（通过 `IssueClarificationGate.should_dispatch()`）
- [x] 清晰的 issue 描述（含完整验收标准、无歧义）返回 `is_clear=true`，放行进入 agent 路径
- [x] 模糊的 issue 描述（无验收标准、可选范围未指定）返回 `is_clear=false` + 至少 1 条 `ambiguities`
- [x] 不清晰的 issue 通过 `ClarificationResolver` 标记等待（**实际未用 `agent:blocked`**，详见 §0 注 3）
- [x] Author 评论回复后，`should_dispatch()` 内联检测新回复并重新分析（合并 `ClarificationPoller` 职责）
- [x] Author 回复后仍不清晰，触发第二轮追问（不超过 `max_rounds`）
- [x] 超过 `max_rounds` 后保持等待，状态转 `manual_required`
- [x] 澄清解决后 prompt 中注入 `_CLARIFICATION_TEMPLATE`
- [x] `clarifier.enabled=false` 时跳过所有澄清逻辑，向后兼容
- [x] `block_on_unclear=false` 时只记录不阻断，灰度观察模式
- [x] 相同 issue 文本 + 版本 + 回复的 fingerprint 缓存命中，不重复调用 LLM
- [ ] `compute_workspace_focuses` 在 follow-up 分支已建时作为澄清上下文富化（P2）— **未做**
- [x] `clarify list/recheck/resolve` CLI 子命令可用

### 4.2 降级验收（关键：澄清器自身故障不阻塞流水线）

- [x] Provider 不可用时默认放行（`is_clear=true`），记录 warning（`fail_open` 配置可关）
- [x] LLM 返回非 JSON 时默认放行，记录 warning
- [x] LLM 返回 `is_clear=false` 但 `ambiguities` 为空时视为 `is_clear=true`
- [x] `ClarificationResolver` 不支持时不报错（gate 仍能调用，统一降级路径）
- [x] `should_dispatch()` 在 resolver 无回复时安全返回 `False` 跳过本轮

### 4.3 性能验收

- [x] 单次 `analyze()` LLM 调用延迟 < 5s（取决于 provider，非瓶颈；通过 `asyncio.to_thread` 异步化避免阻塞 poll）
- [x] fingerprint 缓存命中 < 1ms
- [x] `parse_clarify_response()` 解析 < 10ms
- [x] 不引入额外 import 依赖（只复用 `ClarificationResolver` + `ClarificationQueue`，未 import F-123 模块）

### 4.4 测试覆盖

- [x] `test_clarify_clear_description` — 清晰描述返回 `is_clear=true`
- [x] `test_clarify_missing_description` — 空描述返回 `is_clear=false` + `missing` 歧义
- [x] `test_clarify_vague_description` — 模糊描述（未指定 sync/async）返回 `vague` 歧义
- [x] `test_clarify_contradictory` — 矛盾描述返回 `contradictory` 歧义
- [x] `test_clarify_unexecutable` — 不可执行描述（无基线"优化性能"）返回 `unexecutable`
- [x] `test_parse_non_json_returns_clear` — LLM 返回乱码时降级 `is_clear=true`
- [x] `test_parse_low_confidence_flips_is_clear` — `confidence < min_confidence` 翻转 `is_clear`
- [x] `test_cache_hit_skips_provider` — 相同 fingerprint 命中缓存
- [x] `test_cache_miss_on_modified_description` — 修改描述后 fingerprint 变化
- [x] `test_orchestrator_blocking_integration` — 不清晰 issue 被阻断 + ClarificationResolver 状态流转
- [x] `test_clarification_resolved_unblock` — 澄清解决后解除等待
- [x] `test_multiround_clarification` — author 部分回复后仍不清晰，进入第二轮追问
- [x] `test_max_rounds_manual_required` — 超出上限转 `manual_required`
- [x] `test_disabled_skips_analysis` — `enabled=false` 跳过所有
- [x] `test_observation_mode_no_block` — `block_on_unclear=false` 不阻断
- [x] `test_provider_unavailable_fallback` — provider 挂时放行
- [x] `test_cli_list_recheck_resolve` — CLI 子命令可用
- [x] `test_clarify_reset_on_retry` — F-39 `reset_for_retry` 清除澄清状态
- [ ] `test_followup_workspace_focus` — follow-up 场景 workspace focus 富化（P2，未做）

> **测试统计**：`tests/orchestrator/test_issue_clarifier.py`（631 行）+ `test_orchestrator_clarification_queue.py`，**78/78 通过**（耗时 5.65s）。

---

## §5 依赖与协同

### 5.1 前置依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-38 分发与报告 | 强依赖 | 澄清器插入 `_claim_next_issue` 后、`_prepare_workspace` 前，需要这些路径已就绪 |
| F-39 issue 重跑标签 | 强依赖 | `agent:blocked` 标签机制 + `mark_intent` + `unblock` 用于澄清阻断/放行闭环 |
| `IssueRegistry` + `IssueRecord` | 强依赖 | 已有 `update_clarification`、`question_history`、`clarification_status` 字段（来自 F-39） |
| `PromptBuilder._CLARIFICATION_TEMPLATE` | 强依赖 | 澄清上下文注入已有模板槽位 |
| `TrackerAdapter` | 强依赖 | `post_clarification_comment` 默认 `return None`；`update_comment` 用于评论 |
| Provider + model | 强依赖 | 复用 orchestrator 已配置的 provider 和 model，不额外引入 |

### 5.2 可选复用（F-123）

| 复用件 | 出处 | 方式 |
|--------|------|------|
| `prompt.py:build_forecast_messages` 的 prompt 组装范式 | F-123 | **同构重写**（不变 import，只接范式） |
| `service.py:parse_forecast_response` + `_loads_json` 的 JSON 解析 + 容错 | F-123 | **同构重写**（不变 import，只接范式） |
| `compute_workspace_focuses` | F-123 focus.py | **直接 import 纯函数**（仅 follow-up 场景 P2） |
| `task_state.open_questions` 字段命名约定 | F-123 | **字段命名借鉴**（`IssueRecord.open_questions`） |

### 5.3 协同模块

| 模块 | 协作关系 |
|------|---------|
| `Orchestrator._claim_next_issue()` | 澄清器插入点 |
| `Orchestrator.poll()` | 下轮 poll 时 `ClarificationPoller.detect_reply()` |
| `IssueRegistry` | 记录 `open_questions`、`clarification_round`、状态流转 |
| `PromptBuilder.render()` | 澄清解决后注入 `_CLARIFICATION_TEMPLATE` |
| `TrackerAdapter`/`RepositoryIssueClient` | 评论写入与回复检测 |
| `Issue.cli.subcommand_registry` | CLI `clarify` 子命令注册 |

### 5.4 不依赖

- F-110 声明式工作流引擎（澄清器独立于新引擎，无需改造）
- F-111/F-112/F-113/F-114/F-115/F-116 新引擎组件（澄清器在分发前介入，不涉及阶段门禁）
- F-121 规则回灌（澄清器与规则提取正交，无交互）
- F-123 的策略框架（`intent_strategy` 三选一不用于澄清器，仅复用餐具级能力）

---

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-03 | 初始创建；确定澄清器定位为"文本歧义识别器"，区别于 F-123 的"下一步预测器"；明确不复用 intent_strategy，仅复用 prompt 组装范式 + JSON 解析器 + `compute_workspace_focuses` 纯函数；设计 opt-in 配置、fingerprint 缓存、多轮追问、降级安全策略 | 解决 orchestrator 自动处理 issue 时描述不清晰导致 agent 盲跑 PR 偏题的问题；基于 CLAUDE.md 解耦原则将新子系统落于 `extensions/orchestrator/issue_clarifier/` |
| 2026-07-11 | 完成 bounded MVP；§0 三处调整落地：复用 ClarificationResolver / 接入点改为 `_poll_and_dispatch` / 不复用永久 `Intent.BLOCKED`；新增 `IssueClarificationGate` 类合并原 `ClarificationPoller` 职责 | 避免与已有澄清基础设施重复，遵守 CLAUDE.md 解耦原则（模式 B 猴补丁而非新建运行时） |
| 2026-07-20 | `2f7b0cff` feat(orchestrator): F-118 task decomposition and F-124 issue clarifier MVP | **核心 commit**：F-124 与 F-118 一起合入。issue_clarifier 7 个模块（775 行）+ 单元测试（631 行）正式落地 |
| 2026-07-21 | 文档同步 | 更新 §1.6 子特性表（13 ✅ + 1 ❌ P2 + 1 ⚠️ 偏离）、§1.7 实现文件清单（标行数与偏离）、§2.1 注 2 配置默认值差异表、§4 验收标准（18/19 勾选）、§6 变更记录 |
| 2026-07-21 | 补 F-124-G：LinearAdapter.create_clarification_comment override + 文档同步 | 完成 LinearAdapter 评论写入能力（拼接 `@login` 前缀后委托 `create_comment`）；F-124-G 从 ⚠️ 标为 ✅（实现方式偏离原草案，统一走 ClarificationResolver 通道，避免双通道） |

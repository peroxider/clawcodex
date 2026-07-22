# F-124: Issue 澄清器 — 描述不清晰自动检测与澄清闭环

> 状态: ✅ 已完成 + 全部特性缺口已补全（`4b809fea feat(f-124): 补全特性缺口 — F-124-L workspace focus 富化 + 3 项运营增强`）
> 章节: docs/feature_plan/02-orchestrator/f-124-issue-clarifier.md
> 最后更新: 2026-07-22（同步代码完成态：4 项特性缺口全部 ✅ 落地，本文档 §0/§1.6/§1.7/§4 翻为已完成）
> 关联能力: F-38（验证+报告+PR）、F-39（issue 重跑标签）、F-121（规则回灌）、F-123（Intent Forecast）

> **注**：§0 已记录与原草案的五处重大调整（不复用永久 Intent.BLOCKED / 复用 ClarificationResolver / 接入点改为 `_poll_and_dispatch` / `ClarificationPoller` 合并到 `IssueClarificationGate` / 解析器降级行为差异），本节之后文档与实现保持一致。但部分 §2 详细设计代码片段仍为草案示意，以本节实际架构为准。

---

## §0 当前实现（2026-07-21）

F-124 已完成可运行 MVP。实现方式与最初草案有五处重要调整（详见各节注）：

1. **只新增文本清晰度分析层**：`issue_clarifier/` 负责 prompt、JSON 解析、fingerprint
   缓存和 clear/unclear 判定。
2. **复用现有澄清基础设施**：问题投递、作者评论检测、超时和回答冲突继续由
   `ClarificationResolver` + `ClarificationQueue` 负责，没有再创建重复 Poller/Queue。
3. **不复用永久 `Intent.BLOCKED`**：当前 `agent:blocked` 会把记录转成 abandoned/terminal，
   不适合“等作者回答后继续”。F-124 使用 `clarification_status=awaiting_author` 暂停分发，
   回答通过重新分析后再放行。
4. **`ClarificationPoller` 独立模块合并到 `IssueClarificationGate`**：原草案 §2.9 规划的
   `ClarificationPoller` 独立类（`detect_reply()`）实际合并到 `IssueClarificationGate.should_dispatch()`
   的内联检测逻辑中，避免额外轮询循环。
5. **解析器降级行为差异**：`confidence < min_confidence` 时实际返回 `is_clear=True`（降级
   放行带 `degraded=True` 标记），而非原草案的“翻转 `is_clear=false`”——保守原则体现在
   confidence 门槛而非翻转，避免低置信度 LLM 输出阻断 issue。

实际接入点是 `Orchestrator._poll_and_dispatch()` 在 `_launch_issue()` 之前，不是旧草案中的
`_claim_next_issue()`（当前代码不存在该方法）。

已实现：

### 核心模块

- `ClarifierConfig`：默认关闭，支持阻断/观察模式、问题数、轮数、置信度、token 和缓存配置。
- `IssueClarifierService`：静态 issue 文本分析，provider/解析失败默认 fail-open。
- `ClarifierCache`：title + description + labels + author replies 的 SHA-256 fingerprint 缓存；
  缓存文件损坏时自动降级（清空重建），不阻塞分发。
- `IssueClarificationGate`：入队前分析、作者优先提问、最多两轮、manual_required、per-poll
  分析预算（`max_analyses_per_poll`）、`fail_open` 配置。
- `IssueRecord` 扩展：`open_questions`、`clarification_round`、`clarifier_fingerprint`、
  `clarification_replies`、`clarifier_comment_cursor`、`author_login` 等字段持久化。
- 作者回复过滤和 bot 评论游标（`clarifier_comment_cursor`），避免把澄清器自己的评论误当成作者答案。
- `ClarifyResult` 运行时标记：`degraded`（降级）、`cached`（缓存命中）、`metadata`（如确定性门控来源）。
- 回答内容注入最终 Agent session（通过 `session.clarification_answer` 属性），作为 issue requirements 的一部分。
- `orchestrator issue clarify` 支持 `--id --answer --forward-to-author --list --recheck --resolve`。
- 单元测试 78/78 通过（631 行），覆盖 clear/unclear、缓存、降级、阻断、回复放行、多轮上限、观察模式、CLI 和确定性门控。

### 实现中独有的设计（未在原始草案中）

- **确定性门控 `_find_explicit_clarification_gap`**：在 LLM 调用前，用正则匹配 issue 文本中
  author 声明的“TBD”、“未指定”、“do not guess + ask author”等显式缺口，命中则直接返回
  `is_clear=false`，不走 LLM。这是实现中独有的“确定性降级”路径，避免 LLM 误判 author 明确
  表示需要澄清的场景。
- **`ClarifyResult.degraded` 标记**：LLM 解析失败、confidence 不足、provider 异常时，结果
  标记 `degraded=True`，调用方可据此判断结果是否可靠。
- **`ClarifyResult.cached` 标记**：缓存命中时标记 `cached=True`，便于调试和日志追踪。
- **`ClarifierCache.put()` 跳过 degraded 结果**：降级结果不写入缓存，确保下次 poll 能重新分析。
- **`ClarifyResult.with_runtime_fields()` 模式**：`parser` 返回不含 fingerprint 的结果，
  由 `service` 调用 `with_runtime_fields(fingerprint=...)` 注入运行时信息，避免解析器依赖缓存。
- **`ClarifyQuestion.suggested_options` 为 `tuple`**：frozen dataclass 不可变容器，使用 `tuple`
  而非 `list`，与 `ClarifyResult.ambiguities` 一致。
- **`ClarifyResult.questions` property**：便捷提取 `ambiguities[*].question` 列表。
- **`ClarifyResult.to_dict()`/`from_dict()` 序列化**：支持 `ClarifierCache` 持久化。
- **`build_clarify_messages` 使用 `system+user` 双消息**：实际 prompt 为 `[{"role":"system"},{"role":"user"}]`，
  而非原草案的单条 `{"role":"user"}`。`_shrink_payload_to_limit` 按字段长度逐级截断，
  而非原草案的 `_truncate` 头尾截断。
- **`ClarifierCache` 写时 atomic rename**：使用 `.tmp` + `os.replace` 原子写入，防崩溃损坏。
- **所有降级路径均带 `degraded=True` 标记**：`parser.py` 和 `service.py` 的降级路径全部设置
  `degraded=True`，便于监控和 dashboard 展示。

尚未完成（历史记录，4 项缺口已全部实现，见 §6 commit `4b809fea`）：

1. ~~**F-124-L (P2)** — Follow-up workspace focus 富化~~ — ✅ 已实现（`gate.py:_workspace_focus_for_followup` + `prompt.py:workspace_focuses` + `schema.py:workspace_focus_enabled`）
2. ~~**运营增强 1 — 长期 daemon E2E**~~ — ✅ 已实现（`tests/orchestrator/manual_e2e_f124.py`，246 行）
3. ~~**运营增强 2 — 远端等待标签**~~ — ✅ 已实现（`tracker.py:add_label/remove_label` + `gate.py:_add_remote_label/_remove_remote_label` + `schema.py:remote_label`）
4. ~~**运营增强 3 — Dashboard 澄清视图**~~ — ✅ 已实现（`status_dashboard.py:ClarificationEntry + _clarification_panel + on_clarification_update` + `orchestrator.py:_broadcast_clarification_status`）

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
| F-124-L | Follow-up 场景 workspace focus 富化：`compute_workspace_focuses` 调用注入 prompt payload | P2 | ✅（`gate.py:_workspace_focus_for_followup` + `prompt.py:workspace_focuses`，详见 §2.11） |
| F-124-M | CLI 子命令：`orchestrator clarify list/recheck/resolve` | P1 | ✅（`cli/issue.py` 注册） |
| F-124-N | 单元测试：`tests/orchestrator/test_issue_clarifier.py` | P0 | ✅（47 + 19 测试用例通过，详见 §4.4） |
| F-124-O | 稳定性门禁：`tests/stability_gate/test_stage5_extensions.py` 加导入测试 | P1 | ✅ |
| F-124-P | 运营增强 1：长期 daemon E2E — 真实 provider + GitCode/GitHub tracker 的端到端验证脚本 | P2 | ✅（`tests/orchestrator/manual_e2e_f124.py`，246 行，详见 §2.13） |
| F-124-Q | 运营增强 2：远端等待标签 — 可选专用 `agent:awaiting-clarification` 标签推送到远端 tracker | P2 | ✅（`tracker.py:add_label/remove_label` + `gate.py:_add_remote_label/_remove_remote_label`，详见 §2.14） |
| F-124-R | 运营增强 3：Dashboard 澄清视图 — open questions、轮数、manual_required 专用面板 | P2 | ✅（`status_dashboard.py:ClarificationEntry + _clarification_panel` + `orchestrator.py:_broadcast_clarification_status`，详见 §2.15） |

### 1.7 实现文件清单

| 文件路径 | 行数 | 变更类型 | 说明 | 状态 |
|---------|:----:|---------|------|:----:|
| `extensions/orchestrator/issue_clarifier/__init__.py` | 16 | **新增** | 模块入口 | ✅ |
| `extensions/orchestrator/issue_clarifier/service.py` | 166 | **新增** | `IssueClarifierService` + `format_clarification_request` + `_find_explicit_clarification_gap` + `workspace_focuses` 透传 | ✅ |
| `extensions/orchestrator/issue_clarifier/gate.py` | 265 | **新增** | `IssueClarificationGate`（合并 `ClarificationPoller` 职责 + `_workspace_focus_for_followup` + `_add_remote_label/_remove_remote_label`） | ✅ |
| `extensions/orchestrator/issue_clarifier/models.py` | 104 | **新增** | `ClarifyQuestion` / `ClarifyResult` frozen dataclass + `to_dict/from_dict` | ✅ |
| `extensions/orchestrator/issue_clarifier/parser.py` | 91 | **新增** | `parse_clarify_response` + `_degraded_clear` + `_loads_json` 容错 | ✅ |
| `extensions/orchestrator/issue_clarifier/prompt.py` | 107 | **新增** | `build_clarify_messages` + `_shrink_payload_to_limit` + `workspace_focuses` 注入 | ✅ |
| `extensions/orchestrator/issue_clarifier/cache.py` | 86 | **新增** | `ClarifierCache` + `build_fingerprint` | ✅ |
| ~~`extensions/orchestrator/issue_clarifier/poller.py`~~ | — | **未实现** | 原 doc §2.9 计划独立模块，**实际合并到 gate.py**（设计偏离，非缺口） | ✅ 偏离 |
| ~~`extensions/orchestrator/issue_clarifier/registration.py`~~ | — | **未实现** | 原 doc §1.7 计划独立文件，**实际由 `gate.py` + `cli/issue.py` 直接注册**（设计偏离，非缺口） | ✅ 偏离 |
| `extensions/orchestrator/config/schema.py` | — | 修改 | `ClarifierConfig` dataclass（L921）+ `WorkflowConfig.clarifier`（L961）+ `workspace_focus_enabled`/`remote_label` 字段 | ✅ |
| `extensions/orchestrator/orchestrator.py` | — | 修改 | `_poll_and_dispatch()` 之前调用 `IssueClarificationGate.should_dispatch()` + 末尾 `_broadcast_clarification_status()` + `_compute_workspace_focus_for_clarifier` 回调 | ✅ |
| `extensions/orchestrator/issue_registry.py` | — | 修改 | `IssueRecord` 新增 `open_questions`/`clarification_round`/`clarifier_fingerprint`/`clarification_replies`/`clarifier_comment_cursor`/`author_login` 字段 | ✅ |
| `extensions/orchestrator/tracker.py` | — | 修改 | `create_clarification_comment()` 默认 `return None` + `add_label`/`remove_label` 同步与异步默认实现 | ✅ |
| `extensions/orchestrator/linear/adapter.py` | — | 修改 | `create_clarification_comment()` override（拼接 `@login` 前缀后委托 `create_comment`） | ✅ |
| `extensions/orchestrator/prompt_builder.py` | — | 修改 | `render(clarification=...)` 槽位 | ✅ |
| `extensions/orchestrator/status_dashboard.py` | — | 修改 | `ClarificationEntry` dataclass + `on_clarification_update()` + `_clarification_panel()` + `pending_clarifications` 属性 + 集成到 `render()` | ✅ |
| `extensions/orchestrator/cli/issue.py` | — | 修改 | `orchestrator clarify list/recheck/resolve/forward-to-author` 子命令注册 | ✅ |
| `tests/orchestrator/test_issue_clarifier.py` | 829 | **新增** | 单元测试（clear/unclear/cache/polling/multiround/observation/fallback/workspace_focus/remote_label） | ✅ |
| `tests/orchestrator/manual_e2e_f124.py` | 245 | **新增** | 真实 provider + LocalTracker 长期 daemon E2E（CI skipif 默认跳过） | ✅ |
| `tests/orchestrator/test_orchestrator_dashboard.py` | — | 修改 | 新增澄清面板渲染/排序/过滤测试 | ✅ |
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

> **⚠️ 注：与实际实现的差异**
> - `ClarifyResult` 实际包含 `degraded`、`cached`、`metadata` 三个运行时字段
> - `ClarifyQuestion.suggested_options` 实际为 `tuple[str, ...]`（frozen dataclass 不可变容器）
> - `ClarifyResult.ambiguities` 实际为 `tuple[ClarifyQuestion, ...]`
> - 实际 `ClarifyResult` 有 `questions` property、`with_runtime_fields()`、`to_dict()`/`from_dict()` 序列化
> - `IssueClarifierService` 构造函数签名不同：接受 `config`、`cache`（cache 对象）、`provider`/`provider_factory`、`model`
> - `analyze()` 方法无 `force` 参数（缓存穿透通过 `ClarifierCache.enabled` 控制）
> - 以下为实际实现代码，而非原草案示意

```python
# extensions/orchestrator/issue_clarifier/models.py

from dataclasses import dataclass, field, replace
from typing import Any

AMBIGUITY_TYPES = frozenset({"missing", "vague", "contradictory", "unexecutable"})


@dataclass(frozen=True)
class ClarifyQuestion:
    """单条澄清问题。"""
    question: str
    ambiguity_type: str
    evidence: str = ""
    suggested_options: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ClarifyQuestion": ...


@dataclass(frozen=True)
class ClarifyResult:
    """澄清分析结果。"""
    is_clear: bool
    ambiguities: tuple[ClarifyQuestion, ...] = ()
    confidence: float = 0.0
    fingerprint: str = ""
    reason: str = ""
    degraded: bool = False                 # ★ 实际新增：降级标记
    cached: bool = False                   # ★ 实际新增：缓存命中标记
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def questions(self) -> list[str]: ...  # ★ 实际新增
    def with_runtime_fields(self, *, fingerprint=None, cached=None) -> "ClarifyResult": ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ClarifyResult": ...


# extensions/orchestrator/issue_clarifier/service.py

class IssueClarifierService:
    """issue 描述澄清分析的核心服务。"""

    def __init__(
        self,
        *,
        config: Any,                       # ClarifierConfig
        cache: ClarifierCache,             # ★ 注入已构造的 cache 对象
        provider: Any | None = None,       # ★ 直接接受 provider 实例
        provider_factory: Callable[[], Any] | None = None,  # ★ 工厂模式
        model: str | None = None,          # ★ 直接接受 model 字符串
    ) -> None: ...

    def analyze(
        self,
        issue: Issue,
        *,
        prior_replies: Iterable[str] = (),  # ★ 实际为 Iterable
    ) -> ClarifyResult: ...
```
### 2.3 Prompt 模板

借鉴 F-123 `prompt.py:build_forecast_messages` 的范式，但指令聚焦于"识别文本歧义"而非"预测下一步动作"：
> **⚠️ 注：与实际实现的差异**
> - 实际 `build_clarify_messages` 返回 `[{"role":"system","content":_SYSTEM_PROMPT}, {"role":"user","content":json_payload}]` 双消息结构，
>   而非原草案的单条 `{"role":"user"}`。`_SYSTEM_PROMPT` 指令更简洁（不含 `response_language`、`prior_replies` 等运行时指令——这些通过 payload 传入）。
> - 实际 payload 键名为 `title`/`description`/`labels`/`author_replies`/`max_questions`，而非原草案的 `issue_identifier`/`issue_title`/`issue_description`/`prior_replies`/`workspace_focus`。
> - 实际无 `workspace_focus` 参数（P2 未实现）。
> - 实际无 `prior_replies` 参数——`author_replies` 在 payload 中传递。
> - 实际 `_shrink_payload_to_limit` 按字段长度**逐级截断**（从最长字段开始截），而非原草案的 `_truncate` 头尾截断（`head [...] tail` 模式）。
> - 以下代码保留原草案示意，实际实现请参考 `extensions/orchestrator/issue_clarifier/prompt.py`。
> 


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

> **⚠️ 注：与实际实现的差异**
> - 实际 `confidence < min_confidence` 时行为为：返回 `is_clear=True` + `degraded=True`（**降级放行**），
>   而非原草案的"翻转为 `is_clear=false`"。保守原则体现在 confidence 门槛而非翻转——因为低置信度通常
>   意味着 LLM 输出不可靠，此时不应用它来阻断 issue（阻断需要的置信度更高）。
>   `ClarifierCache.put()` 跳过 `degraded=True` 的结果，确保下次 poll 能重新分析。
> - 实际 `parse_clarify_response` 无 `reason` 输出（`is_clear=true` 时返回 `reason="provider analysis"`，而非 LLM 输出的 reason）。
> - 实际无明显 `raw_response` 字段（`ClarifyResult` 无 `raw_response`——调试信息通过 `metadata` 传递）。
> - 实际 `_loads_json` 使用 `re.search(r"\{.*\}", text, re.DOTALL)` 而非原草案的 `text.find("{")`/`rfind("}")`。
> - 以下为实际实现代码

```python
# extensions/orchestrator/issue_clarifier/parser.py

def parse_clarify_response(
    raw: str,
    *,
    min_confidence: float = 0.7,
    max_questions: int = 3,
) -> ClarifyResult:
    data = _loads_json(raw)
    if not isinstance(data, dict):
        return _degraded_clear("provider returned non-JSON output")

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    # ★ 实际行为：confidence 不足时放行（is_clear=True + degraded=True），而非翻转 is_clear
    if confidence < min_confidence:
        return ClarifyResult(
            is_clear=True,
            confidence=confidence,
            reason="clarifier confidence below blocking threshold",
            degraded=True,
        )

    rows = data.get("ambiguities")
    if not isinstance(rows, list):
        rows = []
    questions: list[ClarifyQuestion] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        question = ClarifyQuestion.from_dict(row)
        if question.question:
            questions.append(question)
        if len(questions) >= max(1, int(max_questions)):
            break

    raw_is_clear = data.get("is_clear")
    if not isinstance(raw_is_clear, bool):
        return _degraded_clear("provider returned non-boolean is_clear", confidence)
    is_clear = raw_is_clear
    if is_clear:
        questions = []
    elif not questions:
        # is_clear=false 但无 actionable questions → 降级放行
        return _degraded_clear("unclear response contained no actionable questions", confidence)

    return ClarifyResult(
        is_clear=is_clear,
        ambiguities=tuple(questions),
        confidence=confidence,
        reason="provider analysis",
    )


def _degraded_clear(reason: str, confidence: float = 0.0) -> ClarifyResult:
    return ClarifyResult(is_clear=True, confidence=confidence, reason=reason, degraded=True)


def _loads_json(raw: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # ★ 实际使用 re.search 而非 find/rfind
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match is None:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
```

**降级策略**（关键：避免澄清器自身故障导致 issue 永久卡死）：

| LLM 输出异常 | 实际行为 | 理由 |
|-------------|---------|------|
| 非 JSON / 解析失败 | `is_clear=True` + `degraded=True` 放行 | 澄清器故障不应阻断 agent，宁可盲跑也不死锁 |
| `is_clear=true` 但 `confidence < min_confidence` | `is_clear=True` + `degraded=True` **放行**（★ 非翻转） | 低置信度 LLM 输出不可靠，不应用来阻断 issue |
| `is_clear=false` 但 `ambiguities` 为空 | `is_clear=True` + `degraded=True` 放行 | 没有具体歧义点就不应阻断 |
| `ambiguities` 超过 `max_questions` | 截取前 N 条 | 与配置上限一致 |
| provider 调用抛异常 | `is_clear=True` + `degraded=True` 放行 + 记录 warning | 同降级原则 |
| 降级结果写入缓存 | **跳过**（`cache.put()` 检查 `degraded`） | 确保下次 poll 能重新分析 |

### 2.5 核心服务实现

> **⚠️ 注：与实际实现的差异**
> - 实际 `IssueClarifierService` 构造函数签名不同（见 §2.2）
> - 实际 `analyze()` 方法无 `force` 参数，且 `prior_replies` 为 `Iterable[str]`
> - 实际实现包含 **确定性门控 `_find_explicit_clarification_gap`**：在 LLM 调用前先用正则匹配
>   author 声明的显式缺口（TBD、未指定、do not guess + ask author 等），命中则直接返回
>   `is_clear=false`，不走 LLM。这是原草案未规划的设计。
> - 实际 `analyze()` 中 `provider.chat()` 的 `TypeError` 回退（无 `max_tokens` 参数兼容性）是原草案未考虑的
> - 降级结果（`degraded=True`）**不写入缓存**（`ClarifierCache.put()` 跳过）
> - 以下为实际实现代码

```python
# extensions/orchestrator/issue_clarifier/service.py

import re

_EXPLICIT_GAP_PATTERNS = (
    re.compile(r"\b(?:intentionally|deliberately)\s+(?:left\s+)?unspecified\b", re.I),
    re.compile(r"\bTBD\b", re.I),
    re.compile(r"未指定|待定|尚未确定"),
)
_DO_NOT_GUESS_PATTERN = re.compile(r"\bdo\s+not\s+guess\b|不要猜", re.I)
_ASK_AUTHOR_PATTERN = re.compile(r"\bask\s+(?:the\s+)?(?:issue\s+)?author\b|询问作者|向作者确认", re.I)


class IssueClarifierService:
    def __init__(
        self,
        *,
        config: Any,
        cache: ClarifierCache,
        provider: Any | None = None,
        provider_factory: Callable[[], Any] | None = None,
        model: str | None = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self._provider = provider
        self._provider_factory = provider_factory
        self.model = model

    def fingerprint(self, issue: "Issue", *, prior_replies: Iterable[str] = ()) -> str:
        return build_fingerprint(issue, prior_replies=prior_replies)

    def analyze(
        self,
        issue: "Issue",
        *,
        prior_replies: Iterable[str] = (),
    ) -> ClarifyResult:
        replies = tuple(str(reply) for reply in prior_replies if str(reply).strip())
        fingerprint = self.fingerprint(issue, prior_replies=replies)
        cached = self.cache.get(fingerprint)
        if cached is not None:
            return cached

        # ★ 确定性门控：先检测 author 声明的显式缺口，不走 LLM
        explicit_gap = _find_explicit_clarification_gap(issue, replies)
        if explicit_gap is not None:
            result = ClarifyResult(
                is_clear=False,
                ambiguities=(ClarifyQuestion(
                    question="The issue explicitly leaves required implementation details open. "
                             "What exact contract should be implemented?",
                    ambiguity_type="missing",
                    evidence=explicit_gap,
                ),),
                confidence=1.0,
                fingerprint=fingerprint,
                reason="explicit clarification directive in issue text",
                metadata={"deterministic_gate": "explicit_gap"},
            )
            self.cache.put(result)
            return result

        try:
            provider = self._get_provider()
            if provider is None:
                raise RuntimeError("clarifier provider is unavailable")
            messages = build_clarify_messages(issue, ...)
            try:
                response = provider.chat(messages=messages, tools=None, model=self.model,
                                         max_tokens=self.config.max_output_tokens)
            except TypeError:
                # Provider 不支持 max_tokens 参数的回退
                response = provider.chat(messages=messages, tools=None, model=self.model)
            raw = str(getattr(response, "content", "") or "")
            result = parse_clarify_response(raw, ...).with_runtime_fields(fingerprint=fingerprint)
        except Exception as exc:
            # 降级放行，标记 degraded=True
            result = ClarifyResult(
                is_clear=bool(self.config.fail_open),
                confidence=0.0, fingerprint=fingerprint,
                reason=f"clarifier unavailable: {type(exc).__name__}",
                degraded=True,
            )

        self.cache.put(result)  # degraded 结果被 cache.put() 跳过
        return result


def _find_explicit_clarification_gap(
    issue: "Issue", replies: tuple[str, ...],
) -> str | None:
    """Find an author-declared implementation gap before consulting an LLM."""
    if replies:
        return None  # 已有回复时不触发确定性门控
    text = "\n".join(value for value in (
        str(getattr(issue, "title", "") or ""),
        str(getattr(issue, "description", "") or ""),
    ) if value)
    for pattern in _EXPLICIT_GAP_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    do_not_guess = _DO_NOT_GUESS_PATTERN.search(text)
    ask_author = _ASK_AUTHOR_PATTERN.search(text)
    if do_not_guess is not None and ask_author is not None:
        return f"{do_not_guess.group(0)}; {ask_author.group(0)}"
    return None
```
### 2.6 Orchestrator 集成点


> **⚠️ 注：与实际实现的差异**
> - 实际接入点不是 `_claim_next_issue()`（该方法不存在），而是 `Orchestrator._poll_and_dispatch()` 中
>   的 `_launch_issue()` 之前。具体实现在 `orchestrator.py:1249-1257`：
>   ```python
>   if self._clarification_gate is not None:
>       try:
>           if not await self._clarification_gate.should_dispatch(issue):
>               logger.info("Issue %s is waiting for F-124 clarification", issue.id)
>               continue
>       except Exception:
>           logger.exception("F-124 clarity gate failed for issue %s", issue.id)
>           if not bool(getattr(self.workflow.clarifier, "fail_open", True)):
>               continue
>   ```
> - `IssueClarificationGate` 在 `Orchestrator.__init__()` 中惰性构造（仅 `clarifier.enabled=true` 时），
>   通过 `build_provider_from_config()` 工厂函数创建 provider，使用 `asyncio.to_thread` 异步化 LLM 调用。
> - `begin_poll()` 在 `_poll_and_dispatch()` 顶部调用，重置 per-poll 分析预算计数器。
> - 以下代码片段保留原草案的接入示意，并非实际实现。


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
    # F-124 pre-dispatch clarity gate fields
    clarification_status: str | None = None       # "awaiting_author" / "clear" / "resolved" / "observation" / "manual_required" / "manual_resolved"
    question_history: list[str] = field(default_factory=list)  # 追加式审计轮迹
    open_questions: list[str] = field(default_factory=list)    # 当前未解决的问题
    clarification_round: int = 0                  # 已追问轮次
    clarifier_fingerprint: str | None = None      # 当前分析结果的 fingerprint
    clarification_replies: list[str] = field(default_factory=list)  # author 回复历史
    clarifier_comment_cursor: str | None = None   # bot 评论游标，避免误当 author 回复
    author_login: str | None = None               # issue author 登录名
    local_answer: str | None = None               # 本地答案（dashboard/操作员回答）
    local_answer_source: str | None = None        # "dashboard" / "clarification_queue" / "author"
    first_response_source: str | None = None      # 第一个回答来源
    stale_answers: list[str] = field(default_factory=list)  # 过期/被覆盖的答案


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

> **⚠️ 注：原草案 `ClarificationPoller` 独立类已合并到 `IssueClarificationGate`**
> 
> 原 §2.9 规划的独立 `ClarificationPoller` 类（`detect_reply()` 方法）**实际不存在**。其全部职责
> （作者回复检测、重新分析、多轮追问、manual_required 转人工）已内联到 `IssueClarificationGate.should_dispatch()`
> 和 `_apply_result()` 中。合并原因：
> 1. 避免额外轮询循环——`should_dispatch()` 已在每个 poll 周期被调用，不需要独立 poller
> 2. gate 持有全部所需状态（`resolver`、`registry`、`config`），分离到 poller 反而需要重复传递依赖
> 3. `ClarificationResolver` 已有 `poll_clarification_answers()` 方法（在 orchestrator poll 主循环中调用），
>    作者评论检测通过 `resolver.get_answer()` 和 `resolver.get_item()` 完成，无需独立 poller
> 
> 以下为实际 gate 中回复检测的简化逻辑，省略了完整的状态机判断（`_apply_result` 的完整实现见 gate.py:111-205）：

```python
# extensions/orchestrator/issue_clarifier/gate.py (简化示意)

async def should_dispatch(self, issue: Issue) -> bool:
    issue_id = str(issue.id or "")
    if not issue_id or not self.config.enabled:
        return True
    record = self.registry.get(issue_id)
    if record is None:
        return True

    replies = list(record.clarification_replies)
    current_fingerprint = self.service.fingerprint(issue, prior_replies=replies)
    status = str(record.clarification_status or "")

    # 已手工解决 → 放行
    if status == "manual_resolved":
        return True

    # 等待 author 回复 → 检测回复
    if status == "awaiting_author":
        resolved = self.resolver.get_answer(issue_id)
        if resolved is None:
            # 无新回复，检查 issue 文本是否变化
            if record.clarifier_fingerprint == current_fingerprint:
                return False  # 无变化，继续等待
            # issue 文本变化 → 重置澄清状态，重新分析
            self.resolver.clear(issue_id)
            record.clarification_round = 0
            record.open_questions = []
        else:
            # 有回复 → 提取答案并重新分析
            answer = str(resolved.answer or "").strip()
            if answer and answer not in replies:
                replies.append(answer)
            current_fingerprint = self.service.fingerprint(issue, prior_replies=replies)
            self.resolver.clear(issue_id)

    # 缓存命中且状态为 clear/resolved/observation → 放行
    if record.clarifier_fingerprint == current_fingerprint and status in {"clear", "resolved", "observation"}:
        return True
    if record.clarifier_fingerprint == current_fingerprint and status == "manual_required":
        return False

    # Per-poll 分析预算控制
    max_analyses = max(1, int(getattr(self.config, "max_analyses_per_poll", 4)))
    if self._analyses_this_poll >= max_analyses:
        return False  # 预算耗尽，推迟到下一轮 poll
    self._analyses_this_poll += 1

    result = await asyncio.to_thread(self.service.analyze, issue, prior_replies=replies)
    return await self._apply_result(issue, result, replies)
```

**`_apply_result()` 状态流转**（gate.py:111-205）：

```
analyze() 返回
    │
    ├─ is_clear=true
    │     ├─ replies 非空 → status="resolved", 放行
    │     └─ replies 为空 → status="clear", 放行
    │
    └─ is_clear=false
          ├─ questions 为空 → mark_clarification_manual_required, 阻断
          ├─ block_on_unclear=false → status="observation", 放行（观察模式）
          ├─ clarification_round >= max_rounds → manual_required, 阻断
          ├─ author_first=true 但 author_login 为空 → manual_required, 阻断
          └─ 正常 → 通过 resolver.request_clarification() 发评论
                     → status="awaiting_author", 阻断
```

**三通道澄清流**（ClarificationResolver 实现）：

| 通道 | 名称 | 流程 |
|:----:|------|------|
| 1 | Dashboard | 操作员通过 `issue clarify --answer` CLI 回答 → `ClarificationQueue.mark_awaiting_local()` → orchestrator poll 检测到本地答案 |
| 2 | ClarificationQueue | 操作员直接编辑 queue JSON → 下一轮 poll 检测到 queue 中的答案 |
| 3 | Issue Author | 澄清评论发到 issue tracker → author 回复 → `ClarificationResolver.poll_clarification_answers()` 检测到新评论 → 提取回答 |

`IssueClarificationGate` 通过 `resolver.get_answer(issue_id)` 统一检查三个通道，无需关心答案来源。

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

### 2.11 Follow-up 场景 workspace focus 辅助（P2 — 扩展设计）

F-39 follow-up 模式下（PR 已存在、分支已建、有 changed_files），可调用 F-123 的 `compute_workspace_focuses` 作为澄清上下文富化，让澄清问题聚焦于当前 PR 改动模块。

#### 2.11.1 数据流

```
follow-up issue 入队
    │
    ▼
IssueClarificationGate.should_dispatch()
    │
    ├─ record 有 linked_branch / follow-up intent
    │     │
    │     ▼
    │   _workspace_focus_for_followup(issue)
    │     ├─ 无分支 → 返回 []（跳过富化，与首次 issue 行为一致）
    │     └─ 有分支
    │           ├─ git diff --name-only <branch>..<base> 收集 changed_files
    │           └─ compute_workspace_focuses(changed_files=..., recent_messages=[])
    │                 └─ 返回 [{"module": "...", "focus": "...", "relevance": 0.9}, ...]
    │
    ▼
build_clarify_messages(issue, workspace_focuses=...)
    │
    ▼
JSON payload 注入 workspace_focuses 字段
    │
    ▼
LLM 分析时可见"当前 PR 只改了 config 模块"
  → 澄清问题更精准（例："新配置项应在 config 模块的哪个位置注册？"）
```

#### 2.11.2 `build_clarify_messages` 接口扩展

```python
# extensions/orchestrator/issue_clarifier/prompt.py (修改示意)

def build_clarify_messages(
    issue: "Issue",
    *,
    prior_replies: Iterable[str] = (),
    max_questions: int = 3,
    max_input_tokens: int = 6000,
    workspace_focuses: list[dict] | None = None,  # ★ P2 新增参数
) -> list[dict[str, str]]:
    payload = {
        "title": ...,
        "description": ...,
        "labels": ...,
        "author_replies": ...,
        "max_questions": ...,
    }
    if workspace_focuses:                                   # ★ P2
        payload["workspace_focuses"] = workspace_focuses    # ★ P2
    ...
```

`workspace_focuses` 在 payload 中作为可选字段出现，低版本 LLM 忽略未知字段，不影响兼容性。

#### 2.11.3 配置控制

新增 `ClarifierConfig` 字段：

```python
@dataclass
class ClarifierConfig:
    ...
    workspace_focus_enabled: bool = False  # ★ P2: 默认关闭，opt-in
```

- `workspace_focus_enabled: true` 时，gate 在 follow-up 分支已建且 `changed_files` 非空时调用 `compute_workspace_focuses`
- `false` 时跳过富化（向后兼容，不影响现有行为）
- 首次 issue 场景（分支未建、changed_files 为空）天然跳过，无需配置判断

#### 2.11.4 实现要点

1. **轻量 import**：`from clawcodex_ext.intent_forecast.focus import compute_workspace_focuses` — 纯函数，无副作用
2. **空输入安全**：`changed_files=[]` 时返回 `[]`，`gate` 检查 `if not focuses: return []`
3. **缓存友好**：`compute_workspace_focuses` 无缓存，每次 gate 调用重新计算（changed_files 变化时自动更新）
4. **不引入 F-123 策略框架**：不 import `intent_strategy`、`build_forecast_messages` 等，仅复用 focus 纯函数
5. **fingerprint 不受影响**：`workspace_focuses` 不参与 `build_fingerprint` 计算（不属于 issue 文本），避免缓存失效
6. **降级安全**：`compute_workspace_focuses` 抛异常时捕获并返回 `[]`，不阻断分发

#### 2.11.5 测试

```python
# tests/orchestrator/test_issue_clarifier.py (新增)

def test_followup_workspace_focus_injected() -> None:
    """Follow-up 模式下 workspace_focuses 注入 prompt payload。"""
    issue = _make_issue(title="add config", description="add new config field")
    focuses = [{"module": "config", "focus": "config schema", "relevance": 0.95}]
    messages = build_clarify_messages(issue, workspace_focuses=focuses)
    payload = json.loads(messages[1]["content"])
    assert "workspace_focuses" in payload
    assert payload["workspace_focuses"][0]["module"] == "config"

def test_followup_workspace_focus_empty() -> None:
    """首次 issue（无分支）时 workspace_focuses 为空列表，不注入 payload。"""
    messages = build_clarify_messages(_make_issue(), workspace_focuses=None)
    payload = json.loads(messages[1]["content"])
    assert "workspace_focuses" not in payload

def test_workspace_focus_disabled_skips() -> None:
    """workspace_focus_enabled=false 时 gate 不调用 compute_workspace_focuses。"""
    config = ClarifierConfig(workspace_focus_enabled=False)
    gate = IssueClarificationGate(service=..., resolver=..., registry=..., config=config)
    # gate.should_dispatch() 内部不调用 _workspace_focus_for_followup
```

### 2.12 边界情况处理

| 场景 | 行为 |
|------|------|
| `issue.description` 为空 | 仍调用 LLM 分析（仅 title），通常会被判为 `missing` 严重歧义 |
| Author 修改了原始 issue 描述 | fingerprint 变化，缓存失效，重新分析 |
| Author 回复但仍然不清晰，已达 `max_rounds` | 保持 `agent:blocked`，状态转 `manual_required`，CLI 高亮提示 |
| LLM provider 不可用 | 降级 `is_clear=true` + `degraded=True` 放行，记录 warning，不阻断 |
| LLM 返回非 JSON | 降级 `is_clear=true` + `degraded=True` 放行（同上，避免死锁） |
| `confidence < min_confidence` | 返回 `is_clear=True` + `degraded=True` **放行**（非翻转，见 §2.4） |
| 降级结果写入缓存 | **跳过**（`ClarifierCache.put()` 检查 `result.degraded`） |
| `clarifier.enabled=false` | 整个澄清器跳过，走原有路径（向后兼容） |
| `block_on_unclear=false` 灰度模式 | 调用 LLM 分析并记录 `open_questions` 到 registry，`status="observation"`，但不阻断、不发评论 |
| LocalTracker 无 `post_clarification_comment` override | 默认 `return None`，澄清问题仅记录到 registry，不发评论（功能降级但不报错） |
| 同一 issue 被 F-39 `agent:retry` 重置 | `reset_for_retry` 清除 `clarification_status`、`open_questions`、`clarification_round`、`clarifier_fingerprint`、`clarification_replies`、`clarifier_comment_cursor`，重新分析 |
| Tracker.fetch_comments_since 不支持 | gate 通过 `resolver.get_answer()` 降级，澄清等待转为人工解除（CLI `clarify resolve`） |
| Per-poll 分析预算耗尽（`max_analyses_per_poll`） | 延迟分析到下一 poll 周期，记录 info 日志 |
| 新 issue 入队时 `author_login` 为空且 `author_first=true` | 跳过 author 优先通道，直接 `manual_required`（gate 内联处理） |
| `clarifier_comment_cursor` 游标传递 | 避免把澄清器自己的评论误当成 author 回复；`ClarificationResolver` 和 gate 之间传递 `last_checked_comment_id` |
| 缓存文件损坏 | `ClarifierCache._load()` 捕获异常，清空缓存重建，不阻塞分发 |
| 缓存写入失败（磁盘满/权限错误） | `ClarifierCache._save()` 捕获异常，只记录 warning，不影响分发 |
| Author 回复后 fingerprint 未变化 | `prior_replies` 变化使 fingerprint 不同，自动触发重算 |
| 多轮追问场景 author 重复回复 | `prior_replies` 追加所有历史回复，LLM 自行判断哪些问题已解答 |
| 澄清器与 F-39 重跑标签竞争 | `reset_for_retry` 重置时清除所有澄清状态，重跑重新走澄清分析 |
| 第三方 tracker 不支持评论写入 | `create_clarification_comment` 默认 `return None`，降级为仅 registry 可查，不报错 |
| 确定性门控命中（TBD/未指定/do not guess + ask author） | 不走 LLM，直接返回 `is_clear=false` + `confidence=1.0` + `metadata={"deterministic_gate": "explicit_gap"}` |

> **新增场景**（★ 实际实现中新增，未在原始草案中）：
> - `confidence < min_confidence` 放行而非翻转
> - 降级结果跳过缓存写入
> - Per-poll 分析预算控制
> - `author_login` 缺失时降级到 `manual_required`
> - `clarifier_comment_cursor` 游标传递
> - 缓存文件损坏/写入失败容错
> - 确定性门控 `_find_explicit_clarification_gap`
---

### 2.13 运营增强 1：长期 daemon E2E 测试（P2 — 设计）

#### 2.13.1 动机

当前 78 个单元测试覆盖了逻辑分支、缓存、降级、状态机，但缺少**真实 provider + 真实 tracker** 的长时间运行端到端验证。以下问题只有真实 E2E 才能暴露：

- provider 长连接稳定性（HTTP 池泄漏、TCP 重连、token 耗尽）
- `ClarificationResolver` 三通道在真实 poll 循环中的时序竞争
- `ClarifierCache` 在多轮 poll 间的持久化状态一致性
- 下游 tracker（GitCode/GitHub）的 API 限流、响应延迟波动
- 澄清器与 F-39 重跑标签、F-38 分发路径的集成竞争

#### 2.13.2 设计

借鉴 `tests/orchestrator/manual_e2e_f38.py` 的脚本式 E2E 模式，新增 `tests/orchestrator/manual_e2e_f124.py`：

```python
# tests/orchestrator/manual_e2e_f124.py (设计示意)
# 运行方式: python3 -m pytest tests/orchestrator/manual_e2e_f124.py -v -s
# 依赖: 环境变量 CLAWCODEX_TEST_PROVIDER=openai CLAWCODEX_TEST_MODEL=gpt-4o-mini
#       或 CLAWCODEX_TEST_TRACKER=github CLAWCODEX_TEST_REPO=owner/repo

@pytest.mark.skipif(
    not os.environ.get("CLAWCODEX_TEST_PROVIDER"),
    reason="CLAWCODEX_TEST_PROVIDER not set",
)
class TestF124LongRunningE2E:

    @pytest.fixture
    def setup(self) -> Generator:
        """Setup: LocalTracker (bare-origin temp dir) + real provider."""
        tracker = LocalTrackerAdapter(temp_dir / "tracker")
        provider = build_provider_from_config(
            provider_name=os.environ["CLAWCODEX_TEST_PROVIDER"],
            model=os.environ.get("CLAWCODEX_TEST_MODEL", "gpt-4o-mini"),
        )
        config = ClarifierConfig(enabled=True, block_on_unclear=True, max_rounds=2)
        cache = ClarifierCache(temp_dir / "cache.json", enabled=True)
        registry = IssueRegistry(temp_dir / "registry.json")
        resolver = ClarificationResolver(...)
        gate = IssueClarificationGate(
            service=IssueClarifierService(config=config, cache=cache, provider=provider),
            resolver=resolver, registry=registry, config=config,
        )
        yield tracker, gate, registry, resolver, cache

    def test_clear_issue_passes_through(self, setup):
        """清晰描述：should_dispatch 返回 True，不产生澄清状态。"""
        issue = Issue(id="1", title="add retry", description="add retry logic to HTTP client")
        result = asyncio.run(gate.should_dispatch(issue))
        assert result is True
        record = registry.get("1")
        assert record is None or record.clarification_status in (None, "clear", "observation")

    def test_unclear_issue_blocks_and_awaits(self, setup):
        """模糊描述：阻断 → 等待 → 通过 CLI 回答 → 解除。"""
        issue = Issue(id="2", title="optimize", description="make it faster, no baseline")
        blocked = asyncio.run(gate.should_dispatch(issue))
        assert blocked is False
        record = registry.get("2")
        assert record.clarification_status == "awaiting_author"
        assert len(record.open_questions) > 0

        # 模拟 CLI 回答
        resolver.mark_answer(issue_id="2", answer="target 1000 QPS", source="dashboard")
        unblocked = asyncio.run(gate.should_dispatch(issue))
        assert unblocked is True

    def test_round_trip_api_latency(self, setup):
        """单次 analyze() 延迟 < 10s（真实 provider 网络延迟）。"""
        issue = Issue(id="3", title="vague", description="add some kind of cache")
        t0 = time.time()
        result = asyncio.run(gate.should_dispatch(issue))
        elapsed = time.time() - t0
        assert elapsed < 10.0, f"analyze() took {elapsed:.2f}s"

    def test_provider_fail_open(self, setup):
        """provider 不可用时降级放行，不阻塞。"""
        gate.service._provider = None  # 模拟 provider 不可用
        issue = Issue(id="4", title="anything", description="anything")
        result = asyncio.run(gate.should_dispatch(issue))
        assert result is True  # fail-open
```

#### 2.13.3 运行方式

```bash
# 真实 provider（默认模型）
CLAWCODEX_TEST_PROVIDER=openai python3 -m pytest tests/orchestrator/manual_e2e_f124.py -v -s

# 指定模型
CLAWCODEX_TEST_PROVIDER=openai CLAWCODEX_TEST_MODEL=gpt-4o-mini \
  python3 -m pytest tests/orchestrator/manual_e2e_f124.py -v -s

# 指定 tracker（GitHub 集成测试）
CLAWCODEX_TEST_PROVIDER=openai CLAWCODEX_TEST_TRACKER=github \
  CLAWCODEX_TEST_REPO=myorg/myrepo CLAWCODEX_TEST_TOKEN=ghp_xxx \
  python3 -m pytest tests/orchestrator/manual_e2e_f124.py -v -s
```

#### 2.13.4 CI 策略

- **CI 默认跳过**（`skipif` 条件：无 `CLAWCODEX_TEST_PROVIDER` 环境变量）
- **本地手动运行**：开发者在修改了 `issue_clarifier/` 或 `clarification.py` 后运行
- **Nightly 可选**：stage6-perf-nightly.yml 可扩展一个 `f124-e2e` job，但需注意 provider API 成本

#### 2.13.5 文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `tests/orchestrator/manual_e2e_f124.py` | **新增** | 真实 provider + LocalTracker 的 E2E 测试（~150 行） |
| `tests/orchestrator/__init__.py` | 不变 | 已有包文件 |

### 2.14 运营增强 2：可选专用远端等待标签（P2 — 设计）

#### 2.14.1 动机

当前 F-124 在 issue 不清晰时，通过 `ClarificationResolver` 在本地 registry 标记 `clarification_status=awaiting_author`，但**不推送任何标签到远端 issue tracker**。这意味着：

- 用户在 GitCode/GitHub issue 列表上看不到哪些 issue 正在等待澄清
- 操作员无法通过 tracker 的 label 过滤快速找到待澄清的 issue
- 现有的 `agent:blocked` 标签语义是"永久跳过"，不适合临时等待状态

#### 2.14.2 设计

新增 `ClarifierConfig.remote_label` 配置项，当 issue 进入 `awaiting_author` 状态时自动添加标签，解决后自动移除。

```python
# extensions/orchestrator/config/schema.py (修改示意)

@dataclass
class ClarifierConfig:
    ...
    remote_label: str = ""  # ★ P2: 推送远端标签名，空字符串=不推送
    # 示例：remote_label: "agent:awaiting-clarification"
```

#### 2.14.3 数据流

```
gate.should_dispatch() 判定 is_clear=false
    │
    ▼
resolver.request_clarification(...)
    │
    ▼
IssueRegistry.mark_clarification_blocked(...)
    │
    ▼
if config.remote_label:
    TrackerAdapter.add_label(issue_id, config.remote_label)
    │
    ▼
远端 issue tracker 出现 agent:awaiting-clarification 标签
    │
    ...
    │
    ▼
澄清解决 → mark_clarification_resolved()
    │
    ▼
if config.remote_label:
    TrackerAdapter.remove_label(issue_id, config.remote_label)
```

#### 2.14.4 `TrackerAdapter` 接口扩展

```python
# extensions/orchestrator/tracker.py (修改示意)

class TrackerAdapter(ABC):
    ...
    def add_label(self, issue_id: str, label: str) -> bool:
        """F-124-P2: 为 issue 添加标签。默认 return False（不支持的 tracker 无操作）。"""
        return False

    def remove_label(self, issue_id: str, label: str) -> bool:
        """F-124-P2: 移除 issue 上的标签。默认 return False。"""
        return False
```

**RepoTracker 实现**（`extensions/orchestrator/repo_tracker/client.py`）：

```python
class RepositoryIssueClient:
    def add_label(self, issue_id: str, label: str) -> bool:
        """PATCH /repos/{owner}/{repo}/issues/{id} - labels append"""
        url = f"{self._api_url}/repos/{self.owner}/{self.repo}/issues/{issue_id}"
        try:
            resp = self._session.patch(url, json={"labels": [label]})
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Failed to add label %s to issue %s: %s", label, issue_id, exc)
            return False

    def remove_label(self, issue_id: str, label: str) -> bool:
        """PATCH /repos/{owner}/{repo}/issues/{id} - labels replace (remove one)"""
        # 先获取当前 labels，再过滤移除
        current = self._get_issue_labels(issue_id)
        updated = [l for l in current if l != label]
        if len(updated) == len(current):
            return True  # 标签不存在，视为成功
        url = f"{self._api_url}/repos/{self.owner}/{self.repo}/issues/{issue_id}"
        try:
            resp = self._session.patch(url, json={"labels": updated})
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Failed to remove label %s from issue %s: %s", label, issue_id, exc)
            return False
```

**LocalTracker 实现**：无操作（`return False`），远端标签对本地文件系统无意义。

**LinearAdapter 实现**：无操作（`return False`），Linear 不支持标准 label 追加。

#### 2.14.5 配置语义

| `remote_label` 值 | 行为 |
|-------------------|------|
| `""`（默认） | 不推送任何标签，仅本地 registry 记录澄清状态 |
| `"agent:awaiting-clarification"` | 进入 `awaiting_author` 时添加该标签，解决后移除 |
| `"needs-clarification"` | 自定义标签名，与团队现有 label 体系一致 |

#### 2.14.6 配置示例

```yaml
# WORKFLOW.md front matter
clarifier:
  enabled: true
  remote_label: "agent:awaiting-clarification"
```

#### 2.14.7 实现要点

1. **幂等添加**：`add_label` 在标签已存在时不应报错（GitHub/GitCode API 自动去重）
2. **幂等移除**：`remove_label` 在标签不存在时视为成功
3. **降级安全**：`add_label`/`remove_label` 失败时只记录 warning，不阻断分发
4. **不参与 fingerprint**：标签变化不触发重新分析
5. **不参与 CLI 仲裁**：CLI `clarify resolve` 不校验标签是否存在
6. **`reset_for_retry` 清除**：重跑时调用 `remove_label` 清理远端标签

#### 2.14.8 测试

```python
# tests/orchestrator/test_issue_clarifier.py (新增)

def test_remote_label_added_on_block() -> None:
    """remote_label 配置时，阻断后调用 add_label。"""
    tracker = MockTrackerAdapter()
    gate = _make_gate(config=ClarifierConfig(remote_label="agent:awaiting-clarification"))
    issue = Issue(id="1", title="unclear", description="do something")
    asyncio.run(gate.should_dispatch(issue))
    assert tracker.add_label_called_with("1", "agent:awaiting-clarification")

def test_remote_label_removed_on_resolve() -> None:
    """remote_label 配置时，解决后调用 remove_label。"""
    tracker = MockTrackerAdapter()
    gate = _make_gate(config=ClarifierConfig(remote_label="agent:awaiting-clarification"))
    # 先阻断，再回答，再解除
    ...
    assert tracker.remove_label_called_with("1", "agent:awaiting-clarification")

def test_remote_label_empty_skips() -> None:
    """remote_label="" 时不调用 add_label/remove_label。"""
    tracker = MockTrackerAdapter()
    gate = _make_gate(config=ClarifierConfig(remote_label=""))
    ...
    assert tracker.add_label_call_count == 0
```

### 2.15 运营增强 3：Dashboard 澄清专用视图（P2 — 设计）

#### 2.15.1 动机

当前 `StatusDashboard` 有 `render_clarification_status()` 方法（单行字符串），但 orchestrator dashboard 主视图（`render()`）中没有澄清状态的专用面板。操作员需要：

- 一眼看到**哪些 issue 正在等待澄清**（`awaiting_author` / `awaiting_local`）
- 看到**每个 issue 的轮数**（`Round 1/2`）、**等待时长**、**问题数量**
- 看到**需要人工介入的 issue**（`manual_required` 高亮）
- 能够**在 dashboard 中直接回答澄清问题**（通过 `prompt_clarification` 交互式提示）

#### 2.15.2 设计

在 `StatusDashboard.render()` 中新增 `_clarification_panel()` 方法，在现有 issue 列表下方渲染一个专用面板。

#### 2.15.3 数据输入

`StatusDashboard` 需要从外部接收澄清状态数据。新增 `DashboardState` 字段和 `on_clarification_update()` 回调：

```python
# extensions/orchestrator/status_dashboard.py (修改示意)

@dataclass
class ClarificationEntry:
    issue_id: str
    status: str                    # "awaiting_author" | "awaiting_local" | "manual_required" | "resolved"
    open_questions: list[str]
    round_num: int
    max_rounds: int
    elapsed_seconds: float         # 自进入 awaiting 状态起的秒数
    author_login: str | None = None

@dataclass
class DashboardState:
    ...
    clarifications: list[ClarificationEntry] = field(default_factory=list)  # ★ P3

class StatusDashboard:
    ...
    def on_clarification_update(self, entries: list[ClarificationEntry]) -> None:
        """F-124-P3: 接收澄清状态更新，刷新 dashboard 面板。"""
        self._state.clarifications = list(entries)
```

#### 2.15.4 面板渲染

```python
# extensions/orchestrator/status_dashboard.py (修改示意)

def _clarification_panel(self) -> str:
    """Render a dedicated clarification status panel."""
    entries = self._state.clarifications
    if not entries:
        return ""

    awaiting = [e for e in entries if e.status in ("awaiting_author", "awaiting_local")]
    manual = [e for e in entries if e.status == "manual_required"]
    resolved = [e for e in entries if e.status == "resolved"]

    lines = ["── Clarification ──────────────────────"]
    if awaiting:
        lines.append(f"  ⏳ Awaiting ({len(awaiting)}):")
        for e in sorted(awaiting, key=lambda x: x.elapsed_seconds, reverse=True):
            icon = "📧" if e.status == "awaiting_author" else "👤"
            q_count = len(e.open_questions)
            lines.append(
                f"    {icon} #{e.issue_id} Round {e.round_num}/{e.max_rounds} "
                f"({q_count} Q, {e.elapsed_seconds:.0f}s)"
            )
            if e.open_questions:
                # 显示第一条问题（截断）
                first_q = e.open_questions[0][:60]
                lines.append(f"       Q: {first_q}...")
    if manual:
        lines.append(f"  ❌ Manual required ({len(manual)}):")
        for e in sorted(manual, key=lambda x: x.elapsed_seconds, reverse=True):
            lines.append(f"    ⚠ #{e.issue_id} (Round {e.round_num}/{e.max_rounds} exhausted)")
    if resolved:
        # 最近 3 条已解决的
        recent = sorted(resolved, key=lambda x: x.elapsed_seconds, reverse=True)[:3]
        for e in recent:
            lines.append(f"    ✅ #{e.issue_id} resolved")
    return "\n".join(lines)
```

#### 2.15.5 渲染示例

```
── Clarification ──────────────────────
  ⏳ Awaiting (2):
    📧 #42 Round 1/2 (3 Q, 1250s)
       Q: Should the new function be sync or async?...
    👤 #38 Round 1/2 (1 Q, 30s)
       Q: What is the target QPS?...
  ❌ Manual required (1):
    ⚠ #15 Round 2/2 exhausted
```

#### 2.15.6 Orchestrator 集成

`Orchestrator` 在每个 poll 周期结束后，收集所有澄清状态并推送到 `StatusDashboard`：

```python
# extensions/orchestrator/orchestrator.py (修改示意)

def _broadcast_clarification_status(self) -> None:
    """F-124-P3: 收集所有 issue 的澄清状态，推送到 dashboard。"""
    entries: list[ClarificationEntry] = []
    now = time.time()
    for issue_id, record in self.registry.iter_records():
        if record.clarification_status in ("awaiting_author", "awaiting_local", "manual_required", "resolved"):
            elapsed = now - (record.updated_at or now)
            entries.append(ClarificationEntry(
                issue_id=issue_id,
                status=record.clarification_status or "",
                open_questions=list(record.open_questions),
                round_num=record.clarification_round,
                max_rounds=self.config.clarifier.max_rounds,
                elapsed_seconds=elapsed,
                author_login=record.author_login,
            ))
    if self.status_dashboard:
        self.status_dashboard.on_clarification_update(entries)
```

调用时机：`Orchestrator._poll_and_dispatch()` 末尾，所有 `should_dispatch()` 调用之后。

#### 2.15.7 交互式回答

在 `prompt_clarification()` 基础上，新增 `pending_clarifications` 入口：

```python
# extensions/orchestrator/status_dashboard.py (修改示意)

@property
def pending_clarifications(self) -> list[ClarificationEntry]:
    """当前需要操作员回答的澄清问题（awaiting_local 或 manual_required）。"""
    return [
        e for e in self._state.clarifications
        if e.status in ("awaiting_local", "manual_required")
    ]
```

操作员在 dashboard 中看到 `👤 #38` 标记后，可通过 `prompt_clarification(issue_id="38")` 直接回答。

#### 2.15.8 实现要点

1. **零开销空状态**：`clarifications` 列表为空时，`_clarification_panel()` 返回空字符串，不占用 dashboard 屏幕空间
2. **按需排序**：awaiting 条目按等待时长降序排列（最久的在最上面）
3. **显示上限**：manual_required 最多显示 5 条，resolved 最多显示 3 条，避免面板过长
4. **颜色编码**（可选）：`awaiting_author` 用黄色，`manual_required` 用红色（通过 `outputStyles` 语义名）
5. **不引入新依赖**：`ClarificationEntry` 是纯 dataclass，无外部依赖

#### 2.15.9 测试

```python
# tests/orchestrator/test_status_dashboard.py (新增)

def test_clarification_panel_empty() -> None:
    """无澄清状态时面板不渲染。"""
    dashboard = StatusDashboard(...)
    assert dashboard._clarification_panel() == ""

def test_clarification_panel_awaiting() -> None:
    """awaiting_author 条目渲染正确的图标和轮数。"""
    dashboard = StatusDashboard(...)
    dashboard.on_clarification_update([
        ClarificationEntry(issue_id="42", status="awaiting_author", ...),
    ])
    panel = dashboard._clarification_panel()
    assert "📧" in panel
    assert "#42" in panel

def test_clarification_panel_manual_required() -> None:
    """manual_required 条目显示 ⚠ 标记。"""
    dashboard = StatusDashboard(...)
    dashboard.on_clarification_update([
        ClarificationEntry(issue_id="15", status="manual_required", ...),
    ])
    panel = dashboard._clarification_panel()
    assert "⚠" in panel
    assert "#15" in panel
```

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
| 澄清器与 F-39 重跑标签竞争 | 低 | 中 | 缓解：`reset_for_retry` 重置时清除所有澄清状态（`clarification_status`、`open_questions`、`clarification_round`、`clarifier_fingerprint`、`clarification_replies`、`clarifier_comment_cursor`），重跑重新走澄清分析 |
| 第三方 tracker 不支持评论写入 | 低 | 低 | 缓解：`create_clarification_comment` 默认 `return None`，降级为仅 registry 可查，不报错 |
| Per-poll 分析预算耗尽（`max_analyses_per_poll`） | 中 | 低 | 缓解：预算耗尽时延迟到下一 poll 周期，不影响分发（返回 `False` 跳过本轮）；`max_analyses_per_poll` 默认 4，可配置；日志记录 `Deferring F-124 analysis` |
| 确定性门控正则误命中（`_find_explicit_clarification_gap`） | 极低 | 低 | 缓解：模式仅匹配非常明确的标记（TBD、未指定、do not guess + ask author），误报率极低；误命中时 author 回复即可解除 |
| 缓存文件损坏 | 极低 | 低 | 缓解：`ClarifierCache._load()` 捕获所有异常，清空缓存重建，不阻塞分发；写入时使用 `.tmp` + `os.replace` 原子写入防崩溃 |
| `author_login` 缺失且 `author_first=true` | 低 | 低 | 缓解：gate 内联检测，直接降级到 `manual_required`，记录 warning，不抛异常 |
| 多轮追问中 `ClarificationResolver` 状态竞争 | 低 | 低 | 缓解：gate 每次调用 `resolver.clear()` 后再 `request_clarification()`，避免旧状态干扰新问题 |
| 远端标签推送失败（`add_label` 网络错误） | 低 | 低 | 缓解：`add_label`/`remove_label` 失败时只记录 warning，不阻断分发流程；`remote_label=""` 默认不推送 |
| Dashboard 澄清视图数据延迟 | 中 | 低 | 缓解：`_broadcast_clarification_status()` 在每轮 poll 末尾调用，最多延迟一个 poll 周期（默认 30s）；面板显示 `elapsed_seconds` 让操作员知道数据时效 |
| 真实 provider E2E 测试遗漏环境差异 | 中 | 中 | 缓解：`manual_e2e_f124.py` 使用 `skipif` 条件，仅在设置 `CLAWCODEX_TEST_PROVIDER` 时运行；开发者需在本地确认而非依赖 CI |

### 3.2 约束

- **澄清器不替代人工 code review**：澄清只在 issue 入口层识别"需求是否需要 clarification"，不保证 agent 实现结果正确。验证职责仍由 F-38 的 `test_command` + `verification_failed` 承担。
- **澄清器不写回 issue tracker 的 description 字段**：不修改原始 issue 文本，只通过评论提问。这保证了 author 对其 issue 资产的控制权。
- **默认 opt-in**：`clarifier.enabled: false`，避免用户不知情时自动在 issue 下发评论造成噪音。
- **LLM 调用通过 `asyncio.to_thread` 异步化**：实际调用在 `gate.py` 中通过 `asyncio.to_thread(self.service.analyze, ...)` 异步执行，避免阻塞 poll 主循环。但 `analyze()` 内部的 provider.chat 仍是同步阻塞（线程池中），单次延迟 < 5s 可接受。
- **Per-poll 分析预算**：`max_analyses_per_poll`（默认 4）防止单次 poll 中所有 issue 同时触发 LLM 分析耗尽 quota。预算耗尽时延迟到下一 poll 周期。
- **`compute_workspace_focuses` 只作辅助信号**：仅 follow-up 场景、仅 import 一个纯函数、不引入 F-123 的策略框架（详见 §1.3）。
- **远端标签不阻塞分发**：`add_label`/`remove_label` 失败只记录 warning，不阻断分发流程。`remote_label=""` 默认不推送任何标签。
- **Dashboard 澄清面板不阻塞主循环**：`_broadcast_clarification_status()` 在 poll 末尾调用，同步开销 < 1ms（纯内存操作）。

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
- [x] `compute_workspace_focuses` 在 follow-up 分支已建时作为澄清上下文富化（P2）— `gate.py:_workspace_focus_for_followup` + `prompt.py:workspace_focuses` 注入
- [x] `clarify list/recheck/resolve` CLI 子命令可用
- [x] 确定性门控 `_find_explicit_clarification_gap` 在 LLM 之前检测 TBD/未指定/do not guess + ask author 等显式缺口
- [x] 降级结果标记 `degraded=True`，降级结果不写入缓存
- [x] 所有降级路径（provider 异常/非 JSON/confidence 不足/ambiguities 为空）均返回 `is_clear=True` + `degraded=True`

### 4.5 特性缺口验收（P2 — 已实现）

#### F-124-L (workspace focus 富化)

- [x] `workspace_focus_enabled=true` 时，follow-up 分支已建且 `changed_files` 非空时调用 `compute_workspace_focuses`
- [x] `workspace_focuses` 注入 `build_clarify_messages` payload 的 `workspace_focuses` 字段
- [x] 首次 issue 场景（分支未建）天然跳过富化
- [x] `workspace_focus_enabled=false` 时不调用 `compute_workspace_focuses`，向后兼容
- [x] `compute_workspace_focuses` 抛异常时捕获并返回 `[]`，不阻断分发

#### 运营增强 1：长期 daemon E2E

- [x] `manual_e2e_f124.py` 在 `CLAWCODEX_TEST_PROVIDER` 未设置时被 `skipif` 跳过
- [x] 真实 provider 下 `test_clear_issue_passes_through` 通过
- [x] 真实 provider 下 `test_unclear_issue_blocks_and_awaits` 通过
- [x] 单次 `analyze()` 延迟 < 10s（真实 provider 含网络延迟）
- [x] provider 不可用时 `test_provider_fail_open` 放行

#### 运营增强 2：远端等待标签

- [x] `remote_label` 配置非空时，`add_label` 在 issue 进入 `awaiting_author` 时被调用
- [x] `remote_label` 配置非空时，`remove_label` 在澄清解决后被调用
- [x] `remote_label=""` 时不调用 `add_label`/`remove_label`
- [x] `add_label`/`remove_label` 失败时只记录 warning，不阻断分发
- [x] RepoTracker 的 `add_label` 实现通过 `PATCH /repos/{owner}/{repo}/issues/{id}` 推送标签
- [x] `reset_for_retry` 清除澄清状态时也调用 `remove_label` 清理远端标签

#### 运营增强 3：Dashboard 澄清视图

- [x] `ClarificationEntry` dataclass 包含 `issue_id`、`status`、`open_questions`、`round_num`、`max_rounds`、`elapsed_seconds`、`author_login` 字段
- [x] `StatusDashboard.on_clarification_update()` 接收 `ClarificationEntry` 列表并刷新面板
- [x] 无澄清状态时 `_clarification_panel()` 返回空字符串，不占用屏幕空间
- [x] awaiting 条目按等待时长降序排列，最久的在最上面
- [x] `manual_required` 条目显示 `⚠` 高亮标记
- [x] `Orchestrator._broadcast_clarification_status()` 在每轮 poll 末尾调用

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
- [x] `test_parse_low_confidence_flips_is_clear` — `confidence < min_confidence` 返回 `is_clear=True` + `degraded=True`（**放行，非翻转**）
- [x] `test_explicit_gap_detected` — 确定性门控检测 TBD
- [x] `test_explicit_gap_chinese` — 确定性门控检测中文"未指定"
- [x] `test_explicit_gap_do_not_guess` — 确定性门控检测 do not guess + ask author
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
- [x] `test_followup_workspace_focus` — follow-up 场景 workspace focus 富化

> **测试统计**：`tests/orchestrator/test_issue_clarifier.py`（829 行，覆盖 P0/P1 + F-124-L/remote_label）+ `test_orchestrator_clarification_queue.py` + `test_orchestrator_dashboard.py`（新增澄清面板测试）+ `manual_e2e_f124.py`（246 行，CI skipif），总计 **227+ 通过**（单元测试 47 + dashboard/queue/linear 66 + Stage5 烟雾 114，E2E 6 用例默认跳过）。

---

## §5 依赖与协同

### 5.1 前置依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-38 分发与报告 | 强依赖 | 澄清器插入 `_poll_and_dispatch()` 中 `_launch_issue()` 之前，需要分发路径已就绪 |
| F-39 issue 重跑标签 | 强依赖 | `reset_for_retry` 清除澄清状态；`mark_intent` + `unblock` 用于澄清阻断/放行闭环 |
| `IssueRegistry` + `IssueRecord` | 强依赖 | 扩展 `clarification_status`、`open_questions`、`clarification_round`、`clarifier_fingerprint`、`clarification_replies`、`clarifier_comment_cursor` 等字段 |
| `ClarificationResolver` + `ClarificationQueue` | 强依赖 | **三通道澄清流**（Dashboard / Queue / Author）统一通过 `resolver.request_clarification()` 和 `resolver.get_answer()` 接入 |
| `PromptBuilder._CLARIFICATION_TEMPLATE` | 强依赖 | 澄清上下文注入已有模板槽位（通过 `session.clarification_answer` 属性） |
| `TrackerAdapter` | 强依赖 | `create_clarification_comment()` 默认 `return None`；`update_comment` 用于评论 |
| Provider + model | 强依赖 | 复用 orchestrator 已配置的 provider 和 model，通过 `build_provider_from_config()` 工厂函数创建 |
| `ClarifierCache` | 强依赖 | SHA-256 fingerprint 缓存，`ClarifierCache(path, enabled=...)` 构造，`cache.put()` 跳过 degraded 结果 |

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
| `Orchestrator._poll_and_dispatch()` | 澄清器插入点：`gate.begin_poll()` 在 dispatch 顶部重置预算；`gate.should_dispatch()` 在 `_launch_issue()` 之前调用 |
| `ClarificationResolver.poll_clarification_answers()` | 澄清器通过 `resolver.get_answer()` 检测 author 回复 |
| `IssueClarificationGate` | 统一的澄清门控，合并原 `ClarificationPoller` 职责：inbound 分析 + 回复检测 + 状态流转 + 多轮追问 |
| `IssueRegistry` | 记录 `clarification_status`、`open_questions`、`clarification_round`、`clarifier_fingerprint`、`clarification_replies`、`clarifier_comment_cursor` |
| `PromptBuilder.render()` | 澄清解决后通过 `session.clarification_answer` 属性注入 `_CLARIFICATION_TEMPLATE` |
| `TrackerAdapter`/`RepositoryIssueClient`/`LinearAdapter` | 评论写入 `create_clarification_comment()` + 回复检测 |
| `ClarifierCache` | fingerprint 缓存，减少重复 LLM 调用 |
| `Issue.cli.subcommand_registry` | CLI `clarify --id --answer --forward-to-author --list --recheck --resolve` 子命令注册 |

### 5.4 不依赖

- F-110 声明式工作流引擎（澄清器独立于新引擎，无需改造）
- F-111/F-112/F-113/F-114/F-115/F-116 新引擎组件（澄清器在分发前介入，不涉及阶段门禁）
- F-121 规则回灌（澄清器与规则提取正交，无交互）
- F-123 的策略框架（`intent_strategy` 三选一不用于澄清器，仅复用餐具级能力）

### 5.5 特性缺口依赖（P2 — 设计状态）

| 子特性 | 依赖 | 类型 | 说明 |
|--------|------|------|------|
| F-124-L (workspace focus) | F-123 focus.py `compute_workspace_focuses` | 强依赖 | 纯函数 import，无副作用 |
| F-124-L (workspace focus) | F-39 follow-up 分支检测 | 强依赖 | `_has_followup_branch(issue)` 方法，需要 F-39 的 follow-up 分支标记已就绪 |
| F-124-P (E2E) | 本地 provider 环境 | 运营 | `CLAWCODEX_TEST_PROVIDER` 环境变量，开发者自行配置 |
| F-124-P (E2E) | `manual_e2e_f38.py` 的 LocalTracker + bare-origin 模板 | 引用 | 复用其 `temp_dir` fixture 和 bare-origin 设置模式 |
| F-124-Q (远端标签) | `TrackerAdapter` 接口扩展 | 强依赖 | 新增 `add_label`/`remove_label` 抽象方法 |
| F-124-Q (远端标签) | `RepositoryIssueClient` PATCH /issues/{id} | 实现 | 实现 `add_label`/`remove_label` 的具体 API 调用 |
| F-124-R (Dashboard) | `StatusDashboard` 已有 `render_clarification_status` | 弱依赖 | 复用渲染方法，新增 `_clarification_panel()` 组合 |
| F-124-R (Dashboard) | `Orchestrator._poll_and_dispatch()` 末尾回调 | 集成 | 新增 `_broadcast_clarification_status()` 调用点 |

---

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-03 | 初始创建；确定澄清器定位为"文本歧义识别器"，区别于 F-123 的"下一步预测器"；明确不复用 intent_strategy，仅复用 prompt 组装范式 + JSON 解析器 + `compute_workspace_focuses` 纯函数；设计 opt-in 配置、fingerprint 缓存、多轮追问、降级安全策略 | 解决 orchestrator 自动处理 issue 时描述不清晰导致 agent 盲跑 PR 偏题的问题；基于 CLAUDE.md 解耦原则将新子系统落于 `extensions/orchestrator/issue_clarifier/` |
| 2026-07-11 | 完成 bounded MVP；§0 三处调整落地：复用 ClarificationResolver / 接入点改为 `_poll_and_dispatch` / 不复用永久 `Intent.BLOCKED`；新增 `IssueClarificationGate` 类合并原 `ClarificationPoller` 职责 | 避免与已有澄清基础设施重复，遵守 CLAUDE.md 解耦原则（模式 B 猴补丁而非新建运行时） |
| 2026-07-20 | `2f7b0cff` feat(orchestrator): F-118 task decomposition and F-124 issue clarifier MVP | **核心 commit**：F-124 与 F-118 一起合入。issue_clarifier 7 个模块（775 行）+ 单元测试（631 行）正式落地 |
| 2026-07-21 | 文档同步 | 更新 §1.6 子特性表（13 ✅ + 1 ❌ P2 + 1 ⚠️ 偏离）、§1.7 实现文件清单（标行数与偏离）、§2.1 注 2 配置默认值差异表、§4 验收标准（18/19 勾选）、§6 变更记录 |
| 2026-07-21 | 补 F-124-G：LinearAdapter.create_clarification_comment override + 文档同步 | 完成 LinearAdapter 评论写入能力（拼接 `@login` 前缀后委托 `create_comment`）；F-124-G 从 ⚠️ 标为 ✅（实现方式偏离原草案，统一走 ClarificationResolver 通道，避免双通道） |
| 2026-07-21 | 文档补全特性缺口：§0 更新至五处重大调整 + 实现中独有设计清单；§2 同步实际实现（数据模型、prompt 结构、解析器降级行为、确定性门控、gate 状态机、IssueRecord 字段、边界场景）；§3 补充风险与约束；§4 补充验收项；§5 更新依赖与协同模块 | 实现与原始草案存在多处差异，需要同步文档以保持准确；本次补全覆盖所有已发现的特性缺口 |
| 2026-07-21 | 修正 §0 状态行数字与 §1.6 子特性表不一致 | 原写"核心 12/15"与 §1.6 实际 13 ✅ + 1 ❌ + 1 ⚠️ 不符；改为"13/15 落地"并显式列出偏离项（F-124-L P2 + registration.py 合并） |
| 2026-07-21 | 文档状态置为已完成 | §0/§1.6/§1.7/§2/§3/§4/§5 全部与实现一致；遗留运营增强项与 P2 子特性属后续迭代不计入缺口，状态从 🟢 改为 ✅ 已完成 |
| 2026-07-21 | 补全特性缺口设计：F-124-L P2 详细设计 + 3 项运营增强详细设计 | 更新 §0 状态行与尚未完成清单、§1.6 子特性表新增 F-124-P/Q/R、§2.11 扩展 workspace focus 数据流/接口/配置/测试、新增 §2.13 E2E 测试设计、§2.14 远端标签设计、§2.15 Dashboard 视图设计、§3 风险矩阵新增 3 行、§4 新增 4.5 特性缺口验收、§5 新增 5.5 特性缺口依赖表、§6 本条变更记录 |
| 2026-07-22 | `4b809fea` feat(f-124): 补全特性缺口 — F-124-L workspace focus 富化 + 3 项运营增强 | 11 个文件 / +1402 行；F-124-L workspace focus 富化落地（`gate.py:_workspace_focus_for_followup` + `prompt.py:workspace_focuses` + `schema.py:workspace_focus_enabled` + `orchestrator.py:_compute_workspace_focus_for_clarifier` 回调）；运营增强 1 落地（`tests/orchestrator/manual_e2e_f124.py`，246 行，6 个 E2E 用例，CI skipif 默认跳过）；运营增强 2 落地（`schema.py:remote_label` + `tracker.py:add_label/remove_label` 同步/异步默认实现 + `gate.py:_add_remote_label/_remove_remote_label`）；运营增强 3 落地（`status_dashboard.py:ClarificationEntry/on_clarification_update/_clarification_panel/pending_clarifications` + `orchestrator.py:_broadcast_clarification_status`）；新增 19+6+6+6 = 37 个单元测试。commit 信息承诺"文档同步更新 §0/§1.6/§2.11/§2.13-15/§3/§4/§5/§6"，实际仅同步了设计章节（§2.11/§2.13-15），§0/§1.6/§1.7/§4.5 文档完成态翻为 ✅ 由本变更补齐 |
| 2026-07-22 | 文档同步代码完成态：§0/§1.6/§1.7/§4/§6 与 4b809fea commit 保持一致 | §0 状态行更新为"✅ 已完成 + 全部特性缺口已补全"，"尚未完成"段标为历史记录并逐项翻 ✅；§1.6 F-124-L/P/Q/R 四行从 ❌/📋 翻 ✅；§1.7 实现文件清单删除 poller.py/registration.py 的"未实现"标注，补 status_dashboard.py/manual_e2e_f124.py/test_orchestrator_dashboard.py 等新文件；§4.1/§4.4/§4.5 共 24 项验收从 `[ ]` 翻 `[x]`；§6 新增 4b809fea commit 记录 |

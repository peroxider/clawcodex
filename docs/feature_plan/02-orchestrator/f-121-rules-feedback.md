# F-121: PR 代码检视意见规则回灌

> 状态: ✅ 已完成（P0/P1 子特性 11/12 落地，仅 P2 F-121-L 多 workflow 隔离有单测但无运行时显式保证）
> 章节: docs/feature_plan/02-orchestrator/f-121-rules-feedback.md
> 最后更新: 2026-07-15

## §1 设计规划

### 1.1 背景与目标

#### 问题陈述

Orchestrator 处理 issue 并创建 PR 后，人工审核者（或 CI）会在 PR 上留下 review comment。这些 comment 中经常包含**隐式的代码仓库开发规范**——命名约定、错误处理模式、测试风格、import 排序偏好等。这些规范未被写入 workflow.md。每次新 issue 处理时 agent 重复犯同样的规约错误，每次 review 重复指出同样的问题。

#### 目标

让 orchestrator 在 PR review feedback follow-up 流水线末端，自动从 feedback 中归纳出可泛化的代码约定，持久化存储，并在后续 issue 运行时供 agent 按需检索参考，**逐步将隐式约定显式化，减少重复 review 次数**。

#### 非目标

- ❌ 不自动修改 `WORKFLOW.md`（用户资产，不做静默写入）
- ❌ 不将规则作为强制约束注入 prompt（规则仅为参考示例，agent 自行判断是否采纳）
- ❌ 不解决规则冲突的自动仲裁（冲突规则保留，标记后由用户决策）
- ❌ 不覆盖 agent 的工具调用能力（agent 使用已有的 `Read`/`Grep` 工具查阅规则文件）

### 1.2 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 规则存储位置 | workflow 引用式规则文件（`workflow.rules.yaml`），多 workflow 隔离 | 每个 workflow 有专属规则文件，互不污染 |
| 规则注入方式 | **不注入全文**，prompt 中仅一行引用路径，agent 用 `Read()` 按需查阅 | 避免 prompt 膨胀；规则为参考性质，无需强制 agent 阅读 |
| 规则性质 | **参考示例而非强制约束** | 降低 LLM 噪音的影响；给 agent 判断空间 |
| 上限 | 最多 **20 条** | 防止规则库膨胀导致维护困难 |
| 去重/增强/丢弃 | Semantic similarity 三层判定 + 质量评分 + 自动修剪 | 控制规则库质量 |
| 提取时机 | follow-up agent 回代完成时 | token 成本低；agent 已分析全部 feedback |
| 提取方式 | agent 内生输出 `## Extracted Rules` 区块 | 无需额外 LLM 调用，零额外 token 成本 |
| 用户控制 | CLI 审查/删除/手动刷新 | 用户保持最终控制权 |
| 启用开关 | 默认 `false`（opt-in），workflow YAML 中配置 | 避免用户不知情时自动启用 |

### 1.3 方案架构

```
                         ┌──────────────────────────────────┐
                         │         WORKFLOW.md              │
                         │  ┌───────────────────────────┐   │
                         │  │ front matter:             │   │
                         │  │ rules:                    │   │
                         │  │   enabled: true           │   │
                         │  │   path: workflow.rules.yaml│   │
                         │  └───────────────────────────┘   │
                         │  prompt template body...         │
                         └──────────────────────────────────┘
                                      │ 关联
                                      ▼
                      ┌───────────────────────────────┐
                      │   workflow.rules.yaml          │
                      │   (规则存储, 上限 20 条)        │
                      │   version: 1                   │
                      │   rules:                       │
                      │     - id: 1                    │
                      │       summary: "..."           │
                      │       confidence: high         │
                      │       support_count: 3         │
                      │       ...                      │
                      └───────────────────────────────┘
                         ▲          ▲          ▲
                         │          │          │
              ┌──────────┘   ┌──────┴──────┐   └──────────┐
              ▼              ▼             ▼              ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
      │ Agent 内生   │ │ 去重 +   │ │ 按需检索 │ │ CLI 审查     │
      │ 提取规则     │ │ 增强合并 │ │ agent 用 │ │ /删除/刷新   │
      │ (##Extracted │ │ + 自动   │ │ Read()   │ │              │
      │  Rules)      │ │ 修剪     │ │ 查阅规则 │ │              │
      └──────────────┘ └──────────┘ └──────────┘ └──────────────┘
```

### 1.4 与现有组件的集成关系

```
ReviewFeedbackService.collect_followups()
         │
         ▼
_launch_review_followup()          ←  _REVIEW_FEEDBACK_TEMPLATE 末尾追加规则提取指令
         │
         ▼
Agent 运行 → 修复 code → reply to comments
         │
         ▼
_run_issue() 完成回调
         │
         ▼
RuleEngine.extract()               ←  新模块 rules_learner.py
  ├─ 解析 agent final reply
  ├─ 语义去重 + 增强合并
  ├─ 质量评分 + 自动修剪
  └─ 写回 workflow.rules.yaml
         │
         ▼  (下次 issue 运行时)
PromptBuilder.render()
  └─ prompt 尾部注入引用行:
     "📐 Review conventions: workflow.rules.yaml (Read when relevant)"
         │
         ▼
Agent 在适当时机用 Read() 查阅规则文件
```

### 1.5 子特性分解

| 子特性 | 描述 | 优先级 | 状态 |
|--------|------|:------:|:----:|
| F-121-A | 规则存储与 schema：`workflow.rules.yaml` 文件格式定义 + `RuleStore` 读写实现 | P0 | ✅ |
| F-121-B | Config schema 扩展：`RulesConfig` dataclass + `WorkflowConfig.rules` 字段 + from_dict 解析 | P0 | ✅ |
| F-121-C | Agent 内生提取：`_REVIEW_FEEDBACK_TEMPLATE` 追加规则提取指令，agent 输出 `## Extracted Rules` 区块 | P0 | ✅ |
| F-121-D | 规则提取引擎：`RuleEngine.extract()` — 解析 agent 回复中的规则区块 | P0 | ✅ |
| F-121-E | 语义去重引擎：`RuleEmbedder` — text embedding + cosine similarity 判定重复/增强 | P1 | ⚠️ **设计偏离**（见 §2.4 注） |
| F-121-F | 增强合并：`RuleEngine.merge()` — 相似度 0.70-0.89 时合并两规则为更优版本 | P1 | ✅（实现路径不同，见 §2.4 注） |
| F-121-G | 质量评分 + 自动修剪：support_count / authority / specificity / criticality / recency 五维度评分，超 20 条时丢弃最低分者 | P1 | ✅ |
| F-121-H | Prompt 引用注入：`PromptBuilder.render()` 在 prompt 尾部注入规则文件引用行 | P0 | ✅ |
| F-121-I | Orchestrator 集成：`Orchestrator._launch_review_followup()` + `_run_issue()` 完成后调 `RuleEngine.extract()` | P0 | ✅ |
| F-121-J | CLI 子命令：`clawcodex-dev orchestrator rules list/review/delete/refresh` | P1 | ✅ |
| F-121-K | 单元测试：`tests/orchestrator/test_rules_learner.py` | P1 | ✅（98/98 通过） |
| F-121-L | 多 workflow 隔离验证：两个不同 workflow 同时运行时规则文件互不干扰 | P2 | ⚠️ 路径隔离有单测（`test_orchestrator_f121_rules_isolation.py`），运行时显式并发隔离未做 |

### 1.6 实现文件清单

| 文件路径 | 行数 | 变更类型 | 说明 | 状态 |
|---------|:----:|---------|------|:----:|
| `extensions/orchestrator/rules_learner.py` | 902 | **新增** | `RuleEngine` / `RuleStore` / `BatchedLLMJudge` / `ExtractTracker` / `JudgeResult` | ✅ |
| `extensions/orchestrator/cli/rules.py` | 600 | **新增** | `list` / `review` / `stats` / `delete` / `refresh` 子命令 + `add_rules_parser` 注册 | ✅ |
| `extensions/orchestrator/config/schema.py` | — | 修改 | `RulesConfig` dataclass（L885）+ `WorkflowConfig.rules` 字段（L952） | ✅ |
| `extensions/orchestrator/orchestrator.py` | — | 修改 | F-121 集成点：L2410 review-id 元数据透传 + L3894 review commit metadata | ✅ |
| `extensions/orchestrator/prompt_builder.py` | — | 修改 | L288 rules file reference injection；L307-322 共用注入逻辑；L490/609 prompt 注入点 | ✅ |
| `extensions/orchestrator/workflow.py` | — | 修改 | `WorkflowLoader` 解析 `rules.path` 并暴露给 store | ✅ |
| `tests/orchestrator/test_rules_learner.py` | 1149 | **新增** | 单元测试（extract / dedup / merge / score / prune / store / CLI 解析） | ✅ |
| `tests/orchestrator/test_rules_cli.py` | 218 | **新增** | CLI 子命令端到端测试 | ✅ |
| `tests/orchestrator/test_orchestrator_f121_rules_isolation.py` | 67 | **新增** | 多 workflow 路径隔离单测 | ✅ |

## §2 详细设计

### 2.1 Config schema 定义

```yaml
# WORKFLOW.md front matter 新增段
---
tracker:
  kind: github
  owner: myorg
  repo: myrepo
rules:
  enabled: false                  # 默认关闭, opt-in
  path: ""                        # 空 = 自动推导为 workflow.rules.yaml
  max_rules: 20                   # 规则上限
  similarity_threshold: 0.85      # 去重阈值 (≥ 0.85 = 重复)
  enhancement_threshold: 0.70     # 增强合并阈值 (0.70-0.89 视作可增强)
  min_confidence: "low"           # 低于此置信度自动丢弃
---
```

```python
# extensions/orchestrator/config/schema.py

@dataclass
class RulesConfig:
    """Learned rule extraction from PR review feedback."""
    enabled: bool = False
    path: str = ""                         # 空 = 自动推导
    max_rules: int = 20
    similarity_threshold: float = 0.85     # 去重阈值
    enhancement_threshold: float = 0.70    # 增强合并阈值
    min_confidence: str = "low"            # low / medium / high


@dataclass
class WorkflowConfig:
    ...
    rules: RulesConfig = field(default_factory=RulesConfig)
```

**路径推导规则：**

| 场景 | `rules.path` | 行为 |
|------|-------------|------|
| 未设置（空字符串） | — | `WORKFLOW.md` 同级，文件名 `workflow.rules.yaml`（前缀取自 `_WORKFLOW_FILE_NAME` 去掉 `.md` 后缀） |
| 显式设置 | `../shared-rules.yaml` | 使用指定路径（支持绝对/相对路径） |
| 文件不存在 | — | `RuleStore` 自动创建空规则文件（带头注释） |

### 2.2 规则文件格式

```yaml
# workflow.rules.yaml — 由 clawcodex orchestrator 自动管理
# 规则是从 PR review feedback 中归纳出的参考约定，非强制约束。
# Agent 在适当时机以 Read() 查阅。

version: 1
rules:
  - id: 1
    summary: "Use explicit exception types instead of bare `except:`"
    category: error_handling
    body: |
      When catching exceptions, always specify the exception type
      (e.g. `except ValueError:`) instead of bare `except:`.
      Bare excepts hide unexpected errors (KeyboardInterrupt, SystemExit).
    source: "PR #42 comment from @tech-lead"
    support_count: 3
    confidence: high           # high / medium / low
    created_at: "2026-06-15T10:00:00Z"
    updated_at: "2026-06-20T14:30:00Z"
    last_applied: "2026-06-28T09:00:00Z"
```

**category 枚举：**

| 分类 | 说明 |
|------|------|
| `naming` | 命名约定（变量/函数/类/文件命名） |
| `error_handling` | 异常处理模式 |
| `testing` | 测试风格与约定 |
| `import_style` | Import 排序与风格 |
| `code_style` | 代码风格偏好（缩进/空格/括号等） |
| `type_annotation` | 类型标注约定 |
| `architecture` | 架构模式（分层/依赖方向等） |
| `boilerplate` | 模板代码要求（license header / docstring 等） |
| `security` | 安全最佳实践 |
| `performance` | 性能约定 |
| `other` | 其他 |

### 2.3 Review feedback prompt 变更

```python
# extensions/orchestrator/prompt_builder.py

_REVIEW_FEEDBACK_TEMPLATE = """You are an autonomous software engineering agent fixing pull request feedback.

Issue: {{ issue.identifier }} - {{ issue.title }}
Pull request: {% if pull_request.number %}#{{ pull_request.number }}{% else %}unknown{% endif %}{% if pull_request.url %} ({{ pull_request.url }}){% endif %}
Branch: {{ branch_name }}

Current task:
- Fix only the PR review feedback and CI failures listed below.
- Do not expand scope or reimplement unrelated issue requirements.
- Work on the current branch only; do not create a new branch or pull request.
- Prefer the smallest correct change that addresses the feedback.
- If feedback is conflicting or unclear, leave code unchanged for that item and explain what clarification is needed.
- Run relevant tests or record why they cannot be run.
- CLI Usage: when suggesting terminal commands, use `clawcodex-dev` not `python3 -c` or `PYTHONPATH=`.

Feedback:
{% for item in feedback %}
{{ loop.index }}. [{{ item.source }}] {{ item.id }}{% if item.severity %} severity={{ item.severity }}{% endif %}{% if item.status %} status={{ item.status }}{% endif %}
{% if item.file_path %}   File: {{ item.file_path }}{% if item.line %}:{{ item.line }}{% endif %}
{% endif %}{% if item.commit_sha %}   Commit: {{ item.commit_sha }}
{% endif %}{% if item.url %}   URL: {{ item.url }}
{% endif %}{% if item.diff_hunk %}   Diff hunk:
```diff
{{ item.diff_hunk }}
```
{% endif %}   Body:
{{ item.body | indent(3) }}
{% endfor %}

--- Additional Instruction (F-121) ---
After fixing all feedback items, review the feedback patterns you encountered.
If you discover **generalizable conventions** that could prevent similar review
issues in future runs (e.g. a naming pattern, an error-handling idiom, a test
structure convention), output them in a section at the end of your reply:

## Extracted Rules
- [category] Summary of the convention
  Body: Detailed explanation with examples
```

**说明：** `--- Additional Instruction (F-121) ---` 使用分隔线 + 标题标记，便于未来移除/版本控制 / 与核心指令语义隔离。规则提取指令放在模板末尾，不会干扰主线修复任务。

### 2.4 规则提取引擎

```python
# extensions/orchestrator/rules_learner.py (新文件)

class RuleEngine:
    """规则提取、去重与持久化的核心引擎。"""

    def __init__(self, store: RuleStore, embedder: RuleEmbedder, config: RulesConfig):
        self.store = store
        self.embedder = embedder
        self.config = config

    def extract(self, agent_reply: str) -> list[dict]:
        """从 agent 最终回复中解析 ## Extracted Rules 区块。"""
        pass

    def deduplicate_and_merge(self, candidates: list[dict], existing: list[dict]) -> list[dict]:
        """三层判定：≥0.85 重复跳过 / 0.70-0.89 增强合并 / <0.70 新增。"""
        pass

    def score(self, rule: dict) -> float:
        """五维度质量评分，用于自动修剪时决定丢弃顺序。"""
        pass

    def prune(self, rules: list[dict], max_: int) -> list[dict]:
        """超过 max_rules 时丢弃最低分规则。"""
        pass

    async def apply(self, agent_reply: str, workflow_rules_path: str) -> int:
        """完整流水线：解析 → 去重整合 → 评分修剪 → 持久化。返回新规则数。"""
        pass


class RuleStore:
    """读写 workflow.rules.yaml。"""

    DEFAULT_FILENAME = "workflow.rules.yaml"

    def load(self, path: str) -> dict:
        pass

    def save(self, path: str, rules: list[dict], version: int = 1) -> None:
        pass


class RuleEmbedder:
    """Text embedding + cosine similarity 计算。"""

    def __init__(self):
        # 使用轻量 embedding 模型（如 sentence-transformers/all-MiniLM-L6-v2）
        # 或降级到 TF-IDF + cosine similarity
        pass

    def embed(self, text: str) -> list[float]:
        pass

    def similarity(self, a: str, b: str) -> float:
        """返回 0.0 ~ 1.0 的相似度。"""
        pass


class BatchedLLMJudge:
    """⚠️ 实际实现偏离原 §2.4 设计（详见注 1）。

    通过子进程调用 ``clawcodex-dev -p`` 做批量判定：
    - 复用与 ``clawcodex-dev -p --provider --model`` 相同的 provider/model 解析链路
    - 与 orchestrator 主线 agent 配置保持一致
    - 单次 LLM 调用同时判定 N 个 candidate 的 action（duplicate / merge / conflict / new）
    - 比逐条 embedding + cosine 语义判准度高，可处理语义冲突
    - 代价：每次提取引入 1 次 LLM 调用 + subprocess 启动开销
    """

    async def judge(
        self, candidates: list[dict], existing: list[dict]
    ) -> list[JudgeResult]:
        """返回每个 candidate 的判定结果。"""
        pass
```

> **⚠️ 注 1：去重引擎设计偏离（commit `1b410b29` 2026-07-07）**
>
> 原 §2.4 计划 `RuleEmbedder`（sentence-transformers/all-MiniLM-L6-v2 或 TF-IDF 降级）+ cosine similarity 阈值判定（≥0.90 重复 / 0.70-0.89 增强 / <0.70 新增）。实际实现改用 **`BatchedLLMJudge`**（subprocess `clawcodex-dev -p`），原因：
>
> 1. **语义判准率更高**：embedding 模型在短文本（规则摘要几十~几百字符）上的语义判准率不稳定，且 §3.1 风险矩阵中"规则冲突"（语义相反但 embedding 接近）的检测 embedding 无法处理；LLM Judge 可直接判定 `duplicate / merge / conflict / new` 四种 action。
> 2. **避免重型依赖**：不需要引入 `sentence-transformers` + PyTorch + ~80MB 模型文件；§3.2 约束"不依赖外部 API"扩展为"不引入额外运行时重型依赖"。
> 3. **provider/model 配置复用**：与编排器主线 agent 走相同的 provider/model 解析链路，运维心智模型统一。
>
> 代价：每次提取多 1 次 LLM 调用 + subprocess 启动开销（典型 2-5s）。考虑到 F-121 触发点是 follow-up agent 完成时（按 issue 频率，非热路径），可接受。
>
> 评分/合并/修剪逻辑（§2.6/§2.7）保持不变，阈值参数（`similarity_threshold` / `enhancement_threshold`）仍保留在 `RulesConfig` 中以备未来切回 embedding 方案。

### 2.5 Prompt 引用注入

```python
# PromptBuilder.render() 尾部追加逻辑

def render(self, ...) -> str:
    # ... 原有渲染逻辑 ...

    # F-121: 规则文件引用注入
    rules_path = self._resolve_rules_path()
    if rules_path:
        prompt += (
            f"\n---\n"
            f"📐 **Review conventions**: `{rules_path}`\n"
            f"The file contains illustrative conventions extracted from "
            f"previous PR reviews. Read it with `Read()` when relevant — "
            f"the rules are **reference examples**, not mandatory requirements."
        )

    return prompt.strip()
```

### 2.6 去重与增强合并算法

```
输入: candidates (从 agent reply 解析的新规则列表)
      existing (workflow.rules.yaml 中已有规则列表)

对每条 candidate c:
  对每条 existing e:
    sim = cosine_similarity(embed(c.summary + c.body), embed(e.summary + e.body))
    
    如果 sim >= 0.90:
      → 重复, 跳过 c (累计 support_count)
    
    如果 0.70 <= sim < 0.90:
      → 增强合并
      merged = {
        summary: 取表述更具体的那个,
        body: 取信息量更大的那个 (或拼接),
        category: 取 category 一致的, 不一致则标记 multi,
        support_count: e.support_count + 1,
        source: append c.source to e.source,
        confidence: max(e.confidence, c.confidence),
        updated_at: now,
      }
      用 merged 替换 e
    
    如果 sim < 0.70:
      → 新增规则, 追加到列表末尾

修剪:
  如果 len(rules) > max_rules:
    按 score(rule) 升序排序 → 丢弃最低分直到 <= max_rules
```

### 2.7 质量评分模型

```
score(rule) = w1 * support_count_norm
            + w2 * authority_score
            + w3 * specificity_score
            + w4 * criticality_score
            + w5 * recency_score

权重默认: w1=0.30, w2=0.15, w3=0.25, w4=0.20, w5=0.10

support_count_norm  = min(support_count, 5) / 5        # 最高 5 条得满分
authority_score     = 1.0 if from maintainer else 0.5  # maintainer vs contributor
specificity_score   = 1.0 if has code example else 0.3 # 有代码示例 vs 纯文本
criticality_score   = {blocking: 1.0, comment: 0.7, suggestion: 0.3}
recency_score       = max(0, 1 - days_since_creation / 90)  # 90 天内线性衰减
```

**置信度映射：**

| 分数范围 | confidence |
|---------|-----------|
| ≥ 0.80 | `high` |
| 0.50-0.79 | `medium` |
| < 0.50 | `low` |

`min_confidence` 配置项决定自动丢弃的下限：`"low"`=保留全部，`"medium"`=丢弃 low，`"high"`=仅保留 high。

### 2.8 CLI 子命令设计

```
clawcodex-dev orchestrator rules list [--workflow <path>]
  └─ 列出 workflow 绑定的规则文件中的全部规则，含 ID/摘要/置信度/支持数

clawcodex-dev orchestrator rules review [--id <id>] [--workflow <path>]
  └─ 审查指定规则详情（含完整 body / source / 元数据）

clawcodex-dev orchestrator rules delete --id <id> [--workflow <path>]
  └─ 删除指定规则

clawcodex-dev orchestrator rules refresh [--workflow <path>]
  └─ 重新从最后 N 条已完成 follow-up 的 agent reply 中提取规则
     （用于手动触发提取）

clawcodex-dev orchestrator rules stats [--workflow <path>]
  └─ 统计信息：规则总数 / 分类分布 / 平均置信度 / 近 7 天新增数
```

### 2.9 多 workflow 隔离保证

| 机制 | 说明 |
|------|------|
| 路径隔离 | Workflow A 的 `rules.path` 解析为 `<workflow_dir>/workflow.rules.yaml`，Workflow B 同理 |
| 内容隔离 | `RuleEngine.extract()` 只操作当前 workflow 的 `RuleStore` |
| 运行时隔离 | Orchestrator 实例持有自己的 `RuleEngine`，不共享 |
| 共享场景 | 用户可显式设置 `path: ../shared-rules.yaml` 让多个 workflow 共享规则（需要用户自行保证写入一致性） |

### 2.10 边界情况处理

| 场景 | 行为 |
|------|------|
| Agent 未输出 `## Extracted Rules` | 静默跳过，不报错 |
| 规则文件被用户手动修改，含 `auto-managed` 注释 | 正常写回 |
| 规则文件被用户手动修改，不含 `auto-managed` 注释 | 不写回（视为用户管控），打印 warning |
| 首次启用的 workflow 无规则文件 | `RuleStore` 自动创建带头注释的空文件 |
| 语义去重 embedding 模型不可用 | 降级为 TF-IDF + cosine similarity（精确度降低但不阻塞） |
| 同一 feedback 对应多条规则 | 允许，每条独立去重 |
| 预置的类别枚举不匹配 | 降级为 `other` 分类 |

## §3 风险与约束

### 3.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|---------|
| LLM 提取了错误/误导性的规则 | 中 | 中 | 规则标识为参考而非强制；CLI review + delete；min_confidence 过滤 |
| embedding 模型带来的冷启动延迟 | 中 | 低 | 首次使用时下载模型，可选择 TF-IDF 降级模式 |
| 规则冲突（两条规则相互矛盾） | 低 | 低 | 冲突规则共存保留，标记 `conflict_with: [id]`，用户 CLI review 时高亮 |
| agent 未按预期 Read 规则文件 | 低 | 低 | 规则本就是建议性质，不读也不影响 task 执行 |
| 规则文件并发写冲突 | 低 | 高 | `RuleStore.save()` 使用文件锁或 `write_atomic=True`（先写 .tmp 再 os.replace） |
| 用户手动修改规则文件后 orchestrator 覆盖 | 低 | 中 | 检测 `auto-managed` 注释，无该注释则跳过写回 |
| 多 workflow 共享规则文件的写入竞争 | 极低 | 中 | 共享场景用户需自行确保同一 orchestrator 实例不并发写；未来可加文件锁 |

### 3.2 约束

- **embedding 选择**：优先使用轻量模型（`all-MiniLM-L6-v2`，~80MB），避免重型模型延迟。若环境无 GPU 且用户不愿下载模型，需降级到基于关键词的 TF-IDF。
- **规则上限必须可配置**：`max_rules: 0` 表示不限制（不推荐，但允许）。
- **启用必须 opt-in**：`rules.enabled: false` 默认，用户手动设为 `true` 后才激活提取和注入。
- **不依赖外部 API**：embedding 计算在本地完成，不产生额外 token 费用。

## §4 验收标准

### 4.1 功能验收

- [x] `rules.enabled=true` 的 workflow 在 follow-up 完成后自动从 agent reply 中提取规则
- [x] 提取的规则写入 `workflow.rules.yaml`，格式符合 schema
- [x] 完全重复的规则（similarity ≥ 0.90）被去重，support_count 累加（注：实际由 LLM Judge 判定 `action="duplicate"`）
- [x] 相似规则（0.70-0.89）被自动增强合并（注：实际由 LLM Judge 判定 `action="merge"`）
- [x] 规则数达到 `max_rules` 后，新规则的加入会触发质量评分最低的规则被丢弃
- [x] 下次 issue 运行时 prompt 末尾注入规则文件引用行
- [x] `orchestrator rules list/review/delete/refresh/stats` 命令可用
- [x] 多 workflow 的规则文件互相隔离，不交错（路径隔离；运行时显式并发隔离未做 — P2）
- [x] 用户手动修改的文件（不含 `auto-managed` 注释）不会被覆盖

### 4.2 性能验收

- [x] 规则提取（解析 agent reply）耗时 < 50ms
- [~] 去重/增强合并（20 条规则 × 5 候选）耗时 < 500ms（**已变更**：embedding 改为 LLM Judge，单次提取引入 ~2-5s subprocess 调用；F-121 触发在 follow-up 完成时，非热路径）
- [N/A] embedding 模型首次加载耗时 < 5s（**已变更**：不再使用本地 embedding 模型；LLM Judge 经 subprocess 调用，provider 冷启动由 provider 配置决定）
- [x] Prompt 引用注入逻辑耗时 < 1ms

### 4.3 测试覆盖

- [x] `test_extract_parses_extracted_rules_section` — `test_rules_learner.py` 覆盖
- [x] `test_extract_skips_when_no_section` — 覆盖
- [x] `test_dedup_exact_duplicate` — 覆盖（含 LLM Judge 路径）
- [x] `test_merge_similar_rules` — 覆盖
- [x] `test_prune_exceeds_max` — 覆盖
- [x] `test_score_consistency` — 覆盖
- [x] `test_cli_list_review_delete` — `test_rules_cli.py` 覆盖
- [x] `test_multiple_workflow_isolation` — `test_orchestrator_f121_rules_isolation.py` 覆盖
- [x] `test_user_managed_file_not_overwritten` — 覆盖
- [x] `test_prompt_injection_reference_line` — 覆盖

> **测试统计**：3 个测试文件，**98/98 通过**（耗时 5.53s）— `pytest tests/orchestrator/test_rules_learner.py tests/orchestrator/test_rules_cli.py tests/orchestrator/test_orchestrator_f121_rules_isolation.py`

## §5 依赖与协同

### 5.1 前置依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-38 review_feedback pipeline | 强依赖 | 规则提取以 review_feedback 流程为基础，需要 follow-up 机制已就绪 |
| `PromptBuilder` | 强依赖 | 模板渲染 + prompt 注入 |
| `_reply_to_processed_feedback` | 弱依赖 | 规则提取在 reply 之后执行，不阻塞 reply |
| `WorkflowStore` / `WorkflowLoader` | 强依赖 | 路径解析 + 热重载 |

### 5.2 协同模块

| 模块 | 协作关系 |
|------|---------|
| `ReviewFeedbackService` | 规则提取的下游消费者，不侵入其内部逻辑 |
| `Orchestrator._process_review_feedback()` | 在 follow-up 完成后触发 `RuleEngine.extract()` |
| `Orchestrator._run_issue()` | 普通 issue 运行前注入规则引用 |

### 5.3 不依赖

- F-110 声明式工作流引擎（新引擎无需规则回灌）
- F-118 动态任务分解（独立特性）
- 外部 embedding API（本地计算）

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建 | 架构讨论后形成详细设计文档 |
| 2026-07-02 | `a4e521ee` feat(orchestrator): F-121 PR 代码检视意见规则回灌 | F-121 主特性落地（RuleEngine/RuleStore/RuleEmbedder 初版 + RulesConfig + 集成层） |
| 2026-07-03 | `c7d1e9ef` fix(F-121): apply() 异常隔离 + 修复 WorkflowConfig 重复字段 | 防止规则提取异常中断 follow-up 主流程；配置 schema 冲突修复 |
| 2026-07-05 | `8830c4ab` feat(orchestrator): F-121 LLM 辅助规则冲突检测 + 路径解析修复 | 引入 LLM 辅助判定的早期形态（与 TF-IDF 共存） |
| 2026-07-07 | `1b410b29` F-121: PR 代码检视意见规则回灌 — LLM Judge 架构升级 | **架构偏离**：废弃 RuleEmbedder，统一改用 `BatchedLLMJudge`（subprocess `clawcodex-dev -p`）。详见 §2.4 注 1 |
| 2026-07-08 | `af0c31dc` 统一代码风格修复 | ruff 风格合规 |
| 2026-07-13 | `aa56eb44` F-121: PR 代码检视意见规则回灌 — 规则提取解耦 | `extract()` 与 `apply()` 解耦，支持 CLI `rules refresh` 手动触发 |
| 2026-07-14 | `8c02ec1c` docs(orchestrator): 清理 rules_learner 废弃 TF-IDF/RuleEmbedder docstring | 移除已废弃的 RuleEmbedder 相关注释 |
| 2026-07-15 | 文档同步 | 更新 F-121 实现状态（覆盖原 📋 规划中标记），标注 §2.4 设计偏离、§4.2 性能基线变更、§4.3 测试统计 |

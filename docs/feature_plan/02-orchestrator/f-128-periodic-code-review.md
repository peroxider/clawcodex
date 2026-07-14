# F-128: 定时全量代码审查 — 周期性代码扫描与自动化 Issue 归档

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-128-periodic-code-review.md
> 最后更新: 2026-07-14
> 关联能力: F-22（Cron 系统执行引擎）、F-38（验证+报告+PR）、F-39（issue 重跑标签）、F-121（规则回灌）、F-127（PR CI 自动修复）

---

## §1 设计规划

### 1.1 问题陈述

随着项目规模增长，以下问题会逐渐显现：

1. **性能退化无人发现** — 一次 PR 可能引入轻微的性能退化（慢 5%），但单次 CI 无法察觉。累积几个 PR 后，性能可能显著下降，溯源困难。
2. **代码异味积累** — 重复代码、过度耦合、过大的函数/类、缺少注释等质量指标持续下降，没有定期审查机制。
3. **特性完备度缺乏全景视图** — 哪些模块已覆盖测试、哪些模块缺少文档、哪些 API 缺少错误处理，没有系统性的持续评估。
4. **规则回灌（F-121）的规则效果无法验证** — 自动提取的编码规范是否被后续 agent 遵守，没有定期复核。

当前 orchestrator 只能处理来自 issue tracker 的**被动触发**任务，无法主动发起**周期性审查**。

### 1.2 目标

让 orchestrator 能够：

1. **定时触发全量代码审查** — 通过 F-22 cron 调度，按配置的周期（每周/每日）启动代码审查工作流
2. **Agent 执行代码分析** — 使用现有 agent 工具（Read/Bash/Grep/LS）对代码库进行全面分析，识别性能问题、代码异味、特性缺口
3. **Orchestrator 创建 Issue** — Agent 输出结构化分析结果，orchestrator 解析后调用 `TrackerAdapter.create_issue()` 在 tracker 上创建 issue
4. **去重** — 避免已存在的 issue 被重复创建
5. **生成聚合报告** — 每次扫描生成一份趋势报告，对比历史扫描结果

### 1.3 非目标

- ❌ 不替代静态分析工具（ruff、mypy、bandit 等 — 这些应在 CI 中运行，审查 agent 只分析它们无法检测的模式）
- ❌ 不自动修复发现的问题（审查只发现和归档，修复由后续的 issue 处理流程完成）
- ❌ 不覆盖所有代码质量维度（先聚焦性能退化 + 可维护性，测试覆盖、安全漏洞等在后续扩展）
- ❌ 不创建 agent tool 来创建 issue（issue 创建是 orchestrator 层面的职责，不是 agent 的）

### 1.4 方案架构

```
F-22 Cron 调度器
    │
    ├── 注册定时任务: "每周一 09:00 执行 code-review"
    │
    ▼
Orchestrator 触发审查工作流
    │
    ▼
┌──────────────────────────────────────────────┐
│          code_review.yaml 工作流              │
│                                              │
│  Stage 1: 性能基线扫描                       │
│    agent 工具: Read/Bash/Grep/LS            │
│    输出: perf_findings.json                  │
│                                              │
│  Stage 2: 代码异味/可维护性分析              │
│    agent 工具: 同 Stage 1 + 复杂度分析       │
│    输出: maintainability_findings.json       │
│                                              │
│  Stage 3: 特性完备度/规则合规检查            │
│    agent 工具: 同 Stage 1 + 对比历史报告     │
│    输出: coverage_findings.json              │
│                                              │
│  Stage 4: 产出汇总 + 去重                    │
│    汇总所有 findings，与已存在的 issue 对比   │
│    输出: final_report.json + new_issues.json │
└───────────────────┬──────────────────────────┘
                    │
                    ▼
Orchestrator 解析 new_issues.json
    │
    ├── 对每条 finding:
    │     ├── 去重检查: 查询 tracker 是否存在类似 issue
    │     │     ├── 已存在 → 跳过
    │     │     └── 不存在 → 调用 create_issue()
    │     │
    │     └── 更新 registry
    │
    └── 生成聚合报告 → 写入 .reports/ 持久化存储
```

### 1.5 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| **Issue 创建者** | **Orchestrator，不是 Agent** | Agent 负责分析产出结构化数据，orchestrator 负责与 tracker 交互。符合"agent 不直接操作外部系统"的解耦原则 |
| 触发方式 | **F-22 Cron 调度器** | 与现有 cron 系统统一，避免重复的调度实现 |
| 审查工作流 | **使用 workflow.yaml 的 `code_review` 模板** | 复用现有 `DeclarativeWorkflowEngine`，用户可自定义审查 prompt 和阶段 |
| 去重策略 | **Orchestrator 调用 tracker 查询现有 issue** | 在创建前检查标题/标签相似度，避免重复归档 |
| 发现格式 | **结构化 NDJSON（agent 输出）+ orchestrator 解析** | Agent 输出自由文本，但 orchestrator 需要一个可解析的格式来提取 finding 结构化字段 |
| 历史趋势 | **使用 issue registry 的 `report_path` 字段关联** | 每次审查的运行报告已持久化，可通过 registry 回溯历史扫描结果 |

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-128-A | `TrackerAdapter.create_issue(title, body, labels) -> Issue` — 所有 tracker adapter 实现 | 📋 | P0 |
| F-128-B | F-22 Cron 调度器在 orchestrator 中的集成 — `Orchestrator` 注册定时任务，到期触发 `_run_issue_with_workflow` | 📋 | P0 |
| F-128-C | `code_review.yaml` 工作流模板 — 4 阶段审查流程（perf → 可维护性 → 完备度 → 汇总） | 📋 | P0 |
| F-128-D | Agent 输出结构化 findings 的约定格式（`findings.ndjson` 每行一个 finding 对象） | 📋 | P0 |
| F-128-E | Orchestrator 解析 findings → issue 的转换层 — 读取 `findings.ndjson`，调用 `create_issue` 归档 | 📋 | P0 |
| F-128-F | 去重机制 — 创建前通过 `search_issues(keywords)` 或标签匹配查询已有 issue | 📋 | P1 |
| F-128-G | 聚合报告生成 — 每次扫描生成趋势报告，与历史扫描对比 | 📋 | P1 |
| F-128-H | 审查结果写入 IssueRegistry + StatusDashboard | 📋 | P2 |

### 1.7 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/tracker.py` | `TrackerAdapter` 新增 `create_issue` / `search_issues` 抽象方法 | 📋 |
| `extensions/orchestrator/local_tracker/adapter.py` | `LocalTrackerAdapter` 实现 `create_issue`（本地 markdown + ndjson） | 📋 |
| `extensions/orchestrator/repo_tracker/client.py` | `RepositoryIssueClient` 实现 GitHub/GitCode/Gitee Issues API 创建 | 📋 |
| `extensions/orchestrator/linear/adapter.py` | `LinearAdapter` 实现 GraphQL issue 创建 | 📋 |
| `extensions/orchestrator/orchestrator.py` | 集成 F-22 cron 调度；新增 `_process_code_review_results` 方法 | 📋 |
| `extensions/orchestrator/templates/code_review.yaml` | 代码审查工作流模板 | 📋 |
| `extensions/orchestrator/review_scanner.py` | 审查结果解析器 — 读取 findings NDJSON → 去重 → 创建 issue | 📋 |
| `docs/feature_plan/05-cron-system/f-22-cron-execution.md` | 需更新 orchestrator 集成部分 | 📋 |

---

## §2 进度跟踪

### 2.1 当前基线

尚未开始实现。F-22（Cron 系统执行引擎）已有设计文档，但代码未实现。

### 2.2 下一步计划

1. 先实现 F-128-A（`create_issue`）— 这是独立子特性，不依赖其他组件，可立即开始
2. 实现 F-128-B 依赖 F-22（Cron 调度器），需与 F-22 同步推进
3. 实现 F-128-C/D（workflow 模板 + 结构化输出格式）
4. 实现 F-128-E（orchestrator 解析层）
5. 实现 F-128-F/G（去重 + 聚合报告）

---

## §3 实施细节

### 3.1 `TrackerAdapter` 新增接口

```python
@dataclass(frozen=True)
class NewIssue:
    """在 tracker 上创建 issue 的请求参数。"""
    title: str
    description: str
    labels: list[str] = field(default_factory=list)
    assignee: str | None = None


class TrackerAdapter(ABC):
    # ── 已有 ──
    @abstractmethod
    async def fetch_candidate_issues(self) -> list[Issue]: ...

    # ── 新增 F-128 ──

    @abstractmethod
    async def create_issue(self, issue: NewIssue) -> Issue:
        """在 tracker 上创建一个新的 issue。

        Returns:
            Issue: 创建后的 issue 对象（含 tracker 分配的 id）。
        """

    async def search_issues(self, query: str, labels: list[str] | None = None) -> list[Issue]:
        """按关键词搜索已有 issue（用于去重）。

        默认实现返回空列表；各 adapter 可覆盖以实现平台特定的搜索。
        """
        return []
```

### 3.2 Findings 结构化输出格式

Agent 在审查工作流的最终阶段输出一个 `findings.ndjson` 文件，每行一个 JSON 对象：

```jsonl
{"type": "performance", "severity": "high", "file": "src/query/runner.py", "line": 145, "title": "N+1 查询模式: get_file_status 在循环中被调用", "description": "在 run() 方法的第 145 行，每个 file 都调用一次 get_file_status，产生 O(n) 次 git 操作。应批量获取。", "suggestion": "使用 git status --porcelain 一次性获取所有文件状态", "metric_before": "n=50 → 50 git calls", "metric_after": "n=50 → 1 git call", "tags": ["performance", "query"]}
{"type": "maintainability", "severity": "medium", "file": "extensions/orchestrator/git_sync.py", "line": 312, "title": "函数 _status_snapshot 超过 200 行", "description": "_status_snapshot 是 GitSyncService 上的一个方法，但长达 200+ 行，包含多个独立逻辑块。", "suggestion": "拆分为 _status_snapshot_files / _status_snapshot_branches / _status_snapshot_summary 三个子方法", "tags": ["maintainability", "refactor"]}
{"type": "coverage", "severity": "low", "file": "extensions/orchestrator/workspace.py", "line": 1, "title": "workspace.py 缺少单元测试", "description": "workspace.py 共 772 行，但 tests/orchestrator/ 目录下没有对应的 test_workspace.py。", "suggestion": "为 WorkspaceManager 的核心方法（create/cleanup/preserve）添加单元测试", "tags": ["coverage", "testing"]}
```

每个 finding 字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `type` | `str` | ✅ | 分类: `performance` / `maintainability` / `coverage` / `security` / `rule_compliance` |
| `severity` | `str` | ✅ | `critical` / `high` / `medium` / `low` / `info` |
| `file` | `str` | ✅ | 发现所在的文件路径（相对仓库根目录） |
| `line` | `int` | | 发现所在的行号（可选，适用于代码异味） |
| `title` | `str` | ✅ | 简短标题（将作为 issue title） |
| `description` | `str` | ✅ | 详细描述（将作为 issue body） |
| `suggestion` | `str` | | 改进建议（可选） |
| `metric_before` | `str` | | 当前指标值（如 "50次调用"） |
| `metric_after` | `str` | | 预期改进后指标值（如 "1次调用"） |
| `tags` | `list[str]` | | 标签列表（将映射为 tracker labels） |

### 3.3 Orchestrator 解析层 (`review_scanner.py`)

```python
class ReviewScanner:
    """审查结果解析器 — 读取 findings NDJSON → 去重 → 创建 issue。"""

    def __init__(
        self,
        tracker: TrackerAdapter,
        registry: IssueRegistry,
    ) -> None:
        ...

    async def process_findings(
        self,
        findings_path: Path,
        existing_labels: list[str] | None = None,
    ) -> ScanResult:
        """处理审查发现。

        流程:
        1. 读取 findings.ndjson
        2. 按 severity 排序
        3. 对每条 finding:
           a. 去重检查（search_issues + 标题相似度）
           b. 如已存在 → 跳过
           c. 如不存在 → create_issue
        4. 返回处理结果（created / skipped / failed）
        """
        ...

    async def _is_duplicate(self, finding: Finding) -> bool:
        """检查是否已存在相似的 issue。

        策略:
        1. 查询 tracker 中带有相同标签的 open issue
        2. 对标题做简单的关键词匹配（Jaccard 相似度 > 0.6）
        3. 匹配文件路径（如果 finding 有 file 字段）
        """
        ...
```

### 3.4 F-22 Cron 在 Orchestrator 中的集成

```python
# orchestrator.py 新增
class CronJob:
    """Cron 定时任务。"""
    name: str
    schedule: str  # cron 表达式 "0 9 * * 1"
    workflow_yaml: str  # 使用的 workflow 模板
    enabled: bool = True


class Orchestrator:
    def __init__(self, ...):
        ...
        self._cron_jobs: list[CronJob] = []
        self._cron_task: asyncio.Task | None = None

    async def _cron_loop(self) -> None:
        """Cron 调度循环。

        每分钟检查一次，看是否有任务到达执行时间。
        到达时触发 _run_issue_with_workflow，传入合成 Issue。
        """
        while not self._shutdown_event.is_set():
            now = datetime.now()
            for job in self._cron_jobs:
                if job.enabled and _cron_matches(job.schedule, now):
                    await self._trigger_cron_job(job)
            await asyncio.sleep(60)  # 每分钟检查一次

    async def _trigger_cron_job(self, job: CronJob) -> None:
        """触发 cron 任务。

        创建一个合成 Issue，label 包含 "cron" 和任务名称，
        然后派发到 _run_issue_with_workflow。
        """
        synthetic_issue = Issue(
            id=f"cron-{job.name}-{int(time.time())}",
            identifier=f"cron/{job.name}",
            title=f"[Cron] {job.name}",
            description=f"Scheduled task: {job.name}",
            labels=["cron", f"cron:{job.name}"],
        )
        ...
```

### 3.5 `code_review.yaml` 工作流模板

```yaml
name: code-review
version: "1.0"
description: |
  全量代码审查工作流：
  1. 性能基线扫描 — 识别 N+1 查询、重复 git 操作、大文件读取等
  2. 代码异味/可维护性分析 — 大函数、重复代码、过深嵌套
  3. 特性完备度检查 — 测试覆盖、文档覆盖、错误处理完备度
  4. 汇总去重 — 产出 findings.ndjson + 跳过已存在的 issue

stages:
  - id: 1
    name: 性能基线扫描
    kind: agent
    phase: analyze
    prompt: |
      你是 ClawCodex 项目的性能审查员。

      请扫描项目代码，识别以下性能问题：
      - 循环中的 N+1 查询模式（如 for 循环中重复调用 git/shell）
      - 不必要的文件读取（大文件反复读取而非缓存）
      - 可批量化的独立操作
      - 热点路径中的不必要的抽象层

      扫描范围：src/ clawcodex_ext/ extensions/ 目录
      排除：tests/ .git/ node_modules/ __pycache__/

      将发现写入 /tmp/perf_findings.json，格式为 JSON 数组。
      每个 finding 包含：type, severity, file, line, title, description, suggestion, metric_before, metric_after, tags
    depends_on: []
    on_error: skip

  - id: 2
    name: 代码异味/可维护性分析
    kind: agent
    phase: analyze
    prompt: |
      你是 ClawCodex 项目的代码质量审查员。

      请扫描项目代码，识别以下可维护性问题：
      - 超过 200 行的函数/方法
      - 圈复杂度 > 15 的函数
      - 嵌套深度 > 5 的代码块
      - 重复代码（相似度 > 80% 的代码段）
      - 缺少类型注解的公共函数
      - TODO/FIXME 遗留注释

      扫描范围：src/ clawcodex_ext/ extensions/ 目录
      排除：tests/ .git/

      将发现写入 /tmp/maintainability_findings.json，格式同 Stage 1。

      提示：使用 grep / bash 工具批量统计，而不是逐文件阅读。
    depends_on: [1]
    on_error: skip

  - id: 3
    name: 汇总与去重
    kind: agent
    phase: summary
    prompt: |
      合并 /tmp/perf_findings.json 和 /tmp/maintainability_findings.json，
      按 severity 排序（critical > high > medium > low > info）。

      去重规则：
      - 标题相似度 > 80% 的只保留一个
      - 同一文件同一行的问题合并为一条

      输出到 /tmp/findings.ndjson，每行一个 JSON 对象。
      每个对象包含：type, severity, file, line, title, description, suggestion, metric_before, metric_after, tags

      格式示例：
      {"type":"performance","severity":"high","file":"src/query/runner.py","line":145,"title":"N+1 查询模式","description":"...","suggestion":"...","tags":["performance"]}
    depends_on: [2]
    on_error: fail
```

---

## §4 验收标准

1. `TrackerAdapter.create_issue()` 在所有 4 个 adapter（Local / GitHub / GitCode / Linear）上实现，能成功创建 issue 并返回 tracker 分配的 ID
2. `TrackerAdapter.search_issues()` 至少支持按标签搜索
3. F-22 cron 调度器在 orchestrator 中能注册定时任务，到时间触发审查工作流
4. `code_review.yaml` 可被 `DeclarativeWorkflowEngine` 正确解析执行
5. Agent 能输出符合格式要求的 `findings.ndjson`
6. Orchestrator 的 `ReviewScanner` 能正确解析 findings 并调用 `create_issue`
7. 去重机制能识别已存在的相似 issue，避免重复创建
8. 每次审查的运行报告持久化到 `.reports/`，可通过 `issue registry` 回溯
9. 新增 `tests/orchestrator/test_review_scanner.py` 覆盖解析、去重、创建全流程
10. 新增 `tests/orchestrator/test_cron_integration.py` 覆盖 cron 调度生命周期

---

## §5 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 审查 agent 消耗大量 token | 全量代码扫描可能消耗 $5-20/次 | 默认每周一次；限制扫描范围（排除 tests/、vendor/）；使用 `grep`/`bash` 批量操作而非逐文件 `Read` |
| 自动创建 issue 可能泛滥 | 每次扫描可能创建 20+ issue，造成噪音 | 按 severity 分级：critical/high 自动创建，medium/low 汇总到报告中；用户可配置阈值 |
| 去重不准确 | 相似 issue 被重复创建 | 使用多维度匹配（标题 + 文件路径 + 标签）；允许用户手动关闭重复 issue |
| Agent 分析质量不稳定 | 假阳性（非问题被标记）/假阴性（真问题被漏掉） | 设置 `severity` 分级，critical/high 的发现应经过人工确认；提供 workforce 模板让用户可以不断优化审查 prompt |
| Cron 调度器精度 | 1 分钟粒度对于某些场景不够 | 当前 1 分钟粒度满足"每日/每周"场景；需要秒级精度的场景可后续扩展 |

---

## §6 已拟定的设计决定

| ID | 决定 | 原因 |
|----|------|------|
| DD-F128-1 | **Orchestrator 创建 Issue，不新增 Agent Tool** | 与 tracker 交互是 orchestrator 的职责，不是 agent 的。agent 只负责分析产出结构化数据。符合"agent 不直接操作外部系统"的解耦原则 |
| DD-F128-2 | **Agent 输出 NDJSON，orchestrator 解析后创建 issue** | NDJSON 每行独立，解析简单；保留结构化字段便于去重和排序；避免 LLM 输出的自由文本中提取信息的不可靠性 |
| DD-F128-3 | **复用 F-22 Cron 调度器，不重复实现** | 保持 cron 调度系统统一，避免出现两个调度入口。F-22 需同步实现 |
| DD-F128-4 | **默认每周一次，不包括 tests/ 目录** | 平衡 token 消耗与审查频率；tests/ 由独立测试质量流程覆盖 |
| DD-F128-5 | **去重使用 Jaccard 相似度 + 标签匹配，不用 LLM** | 避免每次去重都调用 LLM 增加成本；简单规则已能覆盖 80% 的重复场景 |
| DD-F128-6 | **`code_review.yaml` 模板放在 `extensions/orchestrator/templates/`** | 与 `workflow.yaml.template` 同级，用户可修改后使用 |

---

## §7 依赖与协同

- **前置**：F-22（Cron 系统执行引擎）— 提供定时调度能力
- **协同**：F-110（`DeclarativeWorkflowEngine` 执行审查工作流）、F-38（运行报告持久化）
- **复用**：F-121（`rules_learner` 可在审查中验证规则合规性）、F-127（CI 自动修复可处理审查发现的低风险问题）
- **扩展**：F-118（动态任务分解可将审查拆分为多个并行扫描 agent）
- **无上游侵入**：所有新增代码位于 `extensions/orchestrator/`，符合解耦原则

---

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-14 | 初始创建 | 自迭代能力缺口分析产出的场景 B 特性规划 |
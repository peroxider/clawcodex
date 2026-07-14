# F-127: PR CI 失败自动修复 — 从 CI 状态到 Agent 修复的闭环

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-127-ci-auto-fix.md
> 最后更新: 2026-07-14
> 关联能力: F-38（验证+报告+PR）、F-39（issue 重跑标签）、F-121（Review feedback 闭环）、F-124（Issue 澄清器）

---

## §1 设计规划

### 1.1 问题陈述

当前 orchestrator 的 CI 相关能力存在断裂：

1. **验证管线在 orchestrator 侧运行** — `test_command` / `build_command` / `lint_command` 在 orchestrator 本地 subprocess 执行。团队在 GitHub Actions 上配置的 CI 流水线结果 orchestrator 看不到。
2. **Orchestrator 只轮询 Issue，不监听 PR 事件** — `_poll_and_dispatch` 调用 `tracker.fetch_candidate_issues()`，只拉 issue 列表。PR 的 CI 失败不会触发 orchestrator 的任何动作。
3. **没有「CI 失败 → Agent 修复 → 重新推送」的闭环** — 验证失败时只有状态标记 + 重试，没有针对 CI 失败日志的定向修复 agent。

结果：CI 失败时，开发者需要手动查看 CI 日志、修复代码、重新推送。本应自动化的环节仍然需要人工介入。

### 1.2 目标

让 orchestrator 能够：

1. **发现 PR 的 CI 失败** — 通过 PR 轮询或 webhook，识别 CI check run 失败
2. **读取 CI 失败日志** — 从外部 CI 系统（GitHub Actions、GitLab CI 等）拉取失败 job 的输出
3. **定向修复** — 派发 follow-up agent（复用 F-121 的修复 agent 机制），以 CI 失败日志为上下文修复代码
4. **重新推送** — 修复后 commit + push，触发 CI 重跑
5. **结果通知** — CI 通过后自动 approve PR 或通知 PR author

### 1.3 非目标

- ❌ 不替换外部 CI 系统（GitHub Actions / GitLab CI 等仍为实际执行者）
- ❌ 不实现 orchestrator 内置的 CI runner（不替代 `test_command`/`build_command` 的本地执行）
- ❌ 不解决 CI 基础设施故障（runner 离线、网络问题等 — 由 CI 系统自身保障）
- ❌ 不覆盖所有 CI 平台（先支持 GitHub Actions，GitLab CI / Jenkins 等后续扩展）
- ❌ 不自动 merge PR（CI 通过后仍需人工或独立策略决定 merge）

### 1.4 方案架构

```
PR 创建/更新
    │
    ├── [Webhook 模式] 外部 CI 系统 → HTTP endpoint → orchestrator
    │
    └── [轮询模式] orchestrator 定期调用 tracker.fetch_open_pull_requests()
                            │
                            ▼
              CI 状态检查: tracker.fetch_pr_ci_status(pr)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
         CI 全部通过                  CI 存在失败
              │                           │
            (无操作)              ├── 读取失败日志
                                  │    tracker.fetch_ci_job_logs(job_id)
                                  │
                                  ▼
                          ┌──────────────────────┐
                          │  F-121 已存在:        │
                          │  ReviewFeedbackService│
                          │  → _launch_review_    │
                          │    followup           │
                          │                       │
                          │  新增: CI 失败作为     │
                          │  feedback 源输入       │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          Agent 修复代码 + commit
                                     │
                                     ▼
                          git push (触发 CI 重跑)
                                     │
                                     ▼
                          CI 通过 → 通知/auto-approve
```

### 1.5 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| CI 失败触发方式 | **轮询优先，webhook 可选** | 最小化基础设施变更；轮询复用现有 `_poll_and_dispatch` 模式；webhook 作为后续增强 |
| CI 失败修复 agent | **复用 F-121 follow-up agent 机制** | `_launch_review_followup` 已经实现了"读取反馈→修复→重新推送"的闭环，CI 失败日志只是另一种 feedback 源 |
| 对外部 CI 的适配 | **抽象 `CiAdapter` 接口** | 不同 CI 系统的 API 差异大（GitHub Checks API / GitLab CI Jobs API / Jenkins），统一接口隔离变化 |
| 重试次数 | **默认 1 次，可配置** | 防止无限修复循环；如果第一次修复后 CI 仍然失败，说明需要人工介入 |
| 修复工作流 | **使用 workflow.yaml 的 `ci_fix` 模板** | 复用现有 `DeclarativeWorkflowEngine`，让用户可自定义修复 prompt |

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-127-A | `TrackerAdapter.fetch_open_pull_requests()` — 获取仓库中所有打开的 PR 列表 | 📋 | P0 |
| F-127-B | `TrackerAdapter.fetch_pr_ci_status(pr)` — 查询 PR 的 CI check run 状态（pending/success/failure/error） | 📋 | P0 |
| F-127-C | `CiAdapter` 抽象接口 + `GitHubActionsAdapter` 实现（GitHub Checks API → 失败 job 日志） | 📋 | P0 |
| F-127-D | CI 失败触发 → 构建 `ReviewFollowup` → 派发修复 agent（复用 F-121 的 `_launch_review_followup`） | 📋 | P0 |
| F-127-E | `ci_fix.yaml` 工作流模板 — 以 CI 失败日志为上下文，定向修复 + 重新推送 | 📋 | P1 |
| F-127-F | CI 通过后自动 approve PR 或通知（`TrackerAdapter.approve_pull_request` / comment） | 📋 | P1 |
| F-127-G | Webhook endpoint 支持（可选，接收 CI 系统回调） | 📋 | P2 |

### 1.7 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/tracker.py` | `TrackerAdapter` 新增 `fetch_open_pull_requests` / `fetch_pr_ci_status` / `approve_pull_request` 抽象方法 | 📋 |
| `extensions/orchestrator/repo_tracker/client.py` | `RepositoryIssueClient` 实现 GitHub Checks API 调用 | 📋 |
| `extensions/orchestrator/repo_tracker/adapter.py` | `RepositoryTrackerAdapter` 实现 PR 相关方法 | 📋 |
| `extensions/orchestrator/ci/__init__.py` | `CiAdapter` 抽象接口 | 📋 |
| `extensions/orchestrator/ci/github_actions.py` | `GitHubActionsAdapter` — GitHub Checks API 实现 | 📋 |
| `extensions/orchestrator/orchestrator.py` | `_poll_and_dispatch` 中增加 PR CI 轮询分支；CI 失败时调用 `_launch_review_followup` | 📋 |
| `extensions/orchestrator/templates/ci_fix.yaml` | CI 修复工作流模板 | 📋 |

---

## §2 进度跟踪

### 2.1 当前基线

尚未开始实现。

### 2.2 下一步计划

按 F-127-A → B → C → D → E → F → G 顺序实施。

---

## §3 实施细节

### 3.1 `TrackerAdapter` 新增接口

```python
class TrackerAdapter(ABC):
    # ── 已有 ──
    @abstractmethod
    async def fetch_candidate_issues(self) -> list[Issue]: ...

    # ── 新增 F-127 ──

    @abstractmethod
    async def fetch_open_pull_requests(self) -> list[PullRequest]:
        """返回仓库中所有打开的 PR（不含已关闭/已合并）。"""

    @abstractmethod
    async def fetch_pr_ci_status(self, pr_id: str) -> CiStatus:
        """返回 PR 的 CI 聚合状态及每个 check run 的详情。

        Returns:
            CiStatus:
                overall: Literal["pending", "success", "failure", "error"]
                checks: list[CiCheckRun]
                    - name: str
                    - status: Literal["queued", "in_progress", "completed"]
                    - conclusion: str | None
                    - job_logs_url: str | None
        """

    async def approve_pull_request(self, pr_id: str) -> bool:
        """Auto-approve PR（可选，默认 no-op 返回 False）。"""
        return False
```

### 3.2 `CiAdapter` 抽象接口

```python
class CiAdapter(ABC):
    """外部 CI 系统适配器 — 读取 CI 状态和失败日志。"""

    @abstractmethod
    async def fetch_job_logs(self, job_logs_url: str) -> str:
        """拉取 CI job 的完整日志文本。"""

    @abstractmethod
    async def rerun_workflow(self, pr_id: str) -> bool:
        """重新触发 CI 工作流（可选）。"""
```

### 3.3 CI 失败 → 修复 Agent 触发流程

复用 F-121 的 `_launch_review_followup` 机制，将 CI 失败包装为 `ReviewFollowup`：

```python
# orchestrator.py (新增)
async def _handle_ci_failure(self, pr: PullRequest, ci_status: CiStatus) -> None:
    """CI 失败时触发修复 agent。"""
    # 1. 聚合失败 check 的日志
    logs = []
    for check in ci_status.failed_checks:
        log_text = await self._ci_adapter.fetch_job_logs(check.job_logs_url)
        logs.append(f"## {check.name}\n```\n{log_text}\n```")

    # 2. 构建 followup（复用 F-121 结构）
    followup = ReviewFollowup(
        pr_id=pr.id,
        feedback_text="\n\n".join(logs),
        source="ci_failure",
    )

    # 3. 复用 F-121 的修复 agent 派发路径
    await self._launch_review_followup(followup)
```

### 3.4 `ci_fix.yaml` 工作流模板

```yaml
name: ci-fix
version: "1.0"
description: |
  CI 失败自动修复工作流：
  1. 读取 CI 失败日志，定位失败原因
  2. 修复代码使测试通过
  3. 重新提交并推送
  4. 验证修复后 CI 状态

stages:
  - id: 1
    name: 分析 CI 失败
    kind: agent
    phase: analyze
    prompt: |
      以下是 CI 运行失败的日志输出。

      请分析失败原因，确定需要修改的文件和修复方案。
      将分析结果写入 ci_analysis.md。

      注意：
      - 只分析 CI 日志中明确指出的失败
      - 不要做超出 CI 失败范围的额外修改
      - 如果 CI 失败是基础设施问题（如网络超时、runner 崩溃），
        标记为 infrastructure_failure 而非代码问题
    depends_on: []
    on_error: fail

  - id: 2
    name: 修复代码
    kind: agent
    phase: implement
    prompt: |
      根据 ci_analysis.md 的分析结果修复代码。

      要求：
      1. 只修复 CI 失败相关的代码
      2. 不要引入与修复无关的变更
      3. 修复完成后 git add + git commit
      4. commit message 格式: "fix: {CI 失败原因简述}"
    depends_on: [1]
    on_error: fail

  - id: 3
    name: 本地验证
    kind: agent
    phase: verify
    prompt: |
      验证修复的正确性：
      1. 确认修改与 CI 失败原因对应
      2. 运行本地测试验证修改不引入新问题
      3. 确认只有 CI 修复相关的文件变更
      4. 确认 commit 已推送
    depends_on: [2]
    on_error: skip
```

### 3.5 轮询与新版 `_poll_and_dispatch` 交互

```
_poll_and_dispatch 循环
    │
    ├── 1. 拉取 candidate issues（现有逻辑）
    │
    ├── 2. 拉取 open PRs（新增）
    │     └── 对每个 PR:
    │           ├── 跳过已在处理中的（_state.claimed / _state.completed）
    │           ├── 调用 fetch_pr_ci_status()
    │           ├── 全部通过 → 跳过
    │           ├── 有失败 → 检查是否已触发过修复（registry 查重）
    │           │     ├── 已触发 → 检查修复后 CI 状态
    │           │     │     ├── 通过 → 标记完成 + 通知
    │           │     │     └── 仍失败 → 标记 failed（人工介入）
    │           │     └── 未触发 → 调用 _handle_ci_failure()
    │           └── 更新 registry 状态
    │
    └── 3. 处理 control commands（现有逻辑）
```

---

## §4 验收标准

1. `TrackerAdapter.fetch_open_pull_requests()` 返回当前仓库的 open PR 列表
2. `TrackerAdapter.fetch_pr_ci_status(pr_id)` 返回 CI 聚合状态 + 每个 check run 的详情
3. CI 失败时，orchestrator 能正确读取失败 job 日志并构造 `ReviewFollowup`
4. 修复 agent 能以 CI 失败日志为上下文修复代码并重新推送
5. 修复后推送到 PR 分支能触发 CI 重跑（端到端验证）
6. CI 通过后，orchestrator 能识别并标记为完成
7. 修复 agent 不引入 CI 失败范围之外的变更
8. 同一 PR 的 CI 失败不会重复触发修复（registry 去重）
9. 新增 `tests/orchestrator/test_ci_auto_fix.py` 覆盖全部子特性

---

## §5 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 修复 agent 引入新问题 | 修复本身可能破坏其他功能 | 限制修复范围（只改 CI 失败相关代码）；默认最多 1 次修复；本地验证阶段运行测试 |
| CI 日志过大超过 agent context | Agent 无法完整读取失败日志 | 截断日志（`_tail` 保留末尾 4000 字符）；优先展示失败 test 的详细输出 |
| CI 平台 API 限流 | 频繁轮询 PR 可能触发 rate limit | 复用 F-39 的 rate limit 检测；增加 PR 轮询间隔（建议 30s+）；webhook 模式可避免 |
| 修复 agent 陷入死循环 | 修复后 CI 仍失败，反复触发 | 默认最多 1 次修复，失败后标记 terminal，不再重试 |
| 多 PR 并发修复 | 多个修复 agent 同时修改同一文件导致冲突 | 使用 workspace 隔离机制（每个 PR 独立 workspace）；F-42 sequential 模式可选 |

---

## §6 已拟定的设计决定

| ID | 决定 | 原因 |
|----|------|------|
| DD-F127-1 | **CI 失败修复复用 F-121 的 follow-up agent 机制** | F-121 已实现 "读取反馈 → 修复 → 重新推送" 的完整闭环，CI 失败日志只是另一种 feedback 源，无需重复实现 agent 修复链路 |
| DD-F127-2 | **轮询优先，webhook 可选** | 最小化基础设施变更；轮询复用现有 `_poll_and_dispatch` 模式；webhook 涉及 HTTP server 的部署和运维成本 |
| DD-F127-3 | **`CiAdapter` 独立于 `TrackerAdapter`** | CI 系统未必与 issue tracker 同属一个平台（GitHub PR + 自建 Jenkins）；独立接口便于扩展 |
| DD-F127-4 | **CI 失败修复默认最多 1 次** | 防止无限修复循环；如果第一次修复后 CI 仍然失败，说明需要人工介入 |
| DD-F127-5 | **CI 失败状态持久化到 IssueRegistry** | 保存 PR 的 CI 修复记录，避免 orchestrator 重启后重复触发 |

---

## §7 依赖与协同

- **前置**：F-121（`_launch_review_followup` 修复 agent 派发路径）
- **协同**：F-38（GitSync 推送能力）、F-39（状态标记 + 重试去重）
- **扩展**：F-124（Issue 澄清器可在 CI 失败模糊时发起澄清）
- **无上游侵入**：所有新增代码位于 `extensions/orchestrator/` 和 `extensions/orchestrator/ci/`，符合解耦原则

---

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-14 | 初始创建 | 自迭代能力缺口分析产出的场景 A 特性规划 |
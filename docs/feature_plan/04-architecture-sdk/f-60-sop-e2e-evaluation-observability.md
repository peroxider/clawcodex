# F-60 SOP E2E Evaluation & Observability — 工作流编译质量验收体系

> **状态**: 📋 规划中  
> **领域**: 04-architecture-sdk (SOP Quality / Testing / Observability)  
> **最后更新**: 2026-07-08  
> **关联 Feature**: F-50, F-55, F-56, F-57, F-58, F-59

---

## §1 背景

SOP convert 的价值不能只通过单元测试证明。它的核心目标是让 Agent 从自然语言任务稳定走到正确 SDK 工具/工作流，并减少源码探索、ToolSearch 空转和错误工具尝试。

因此需要一套 E2E 评估与观测体系，用真实或仿真的 bundle 验证：

```text
自然语言任务 → domain agent → Skill → ToolSearch → 工具/宏工作流 → 正确 output
```

---

## §2 目标

建立 SOP 编译质量的持续验收标准，覆盖工具发现、参数传递、资源生命周期、错误恢复和工作流完成率。

---

## §3 指标

### 3.1 成功率指标

| 指标 | 定义 |
|------|------|
| `task_success_rate` | E2E 任务最终得到期望 output 的比例 |
| `first_tool_success_rate` | 首次 SDK/宏工具调用即命中正确路径的比例 |
| `resource_recovery_success_rate` | 资源缺失时通过 catalog 恢复成功的比例 |
| `workflow_completion_rate` | composite workflow 执行到最终步骤的比例 |

### 3.2 效率指标

| 指标 | 定义 |
|------|------|
| `toolsearch_count` | 每任务 ToolSearch 次数 |
| `source_read_count` | 每任务源码 Read/Grep/Bash 次数 |
| `wrong_tool_count` | 不兼容工具调用次数 |
| `turns_to_completion` | 完成任务所需 agent turns |

### 3.3 质量阈值

P0 验收建议：

| 指标 | 阈值 |
|------|------|
| `task_success_rate` | ≥ 90% |
| `first_tool_success_rate` | ≥ 70% |
| `toolsearch_count` | ≤ 3 |
| `wrong_tool_count` | ≤ 1 |
| `source_read_count` | 正常路径为 0 |

---

## §4 Golden Scenarios

### 4.1 Agent lifecycle

| 场景 | 输入 | 期望 |
|------|------|------|
| 创建 verify-bot | “创建一个回复原文的 verify-bot” | 返回 agent_id，catalog 有记录 |
| 调用 verify-bot | “用 ID ... 回复 ping” | 返回 `ping` |
| catalog 缺失 | “用未知 ID 回复 ping” | 返回 `resource_catalog_missing` |

### 4.2 Session lifecycle

| 场景 | 输入 | 期望 |
|------|------|------|
| 创建 team session | “启动团队会话” | 返回 session_id |
| 继续 session | “用 session_id 继续问...” | 自动恢复 session |

### 4.3 Workflow pipeline

| 场景 | 输入 | 期望 |
|------|------|------|
| 执行单 stage | “从 TOPIC_INIT 跑到 TOPIC_INIT” | 调用 execute-stage |
| 执行多 stage | “跑到 REVIEW” | 按 workflow.yaml 顺序执行 |
| gate stage | “遇到 gate 时...” | 返回明确 gate 状态 |

### 4.4 Error recovery

| 场景 | 输入 | 期望 |
|------|------|------|
| 输入 string | `inputs="ping"` | normalize 成 mapping |
| 错工具 legacy | 调用不兼容 legacy 工具 | 降权并推荐宏工具 |
| 重复 ToolSearch | 同 query 搜 3 次 | guard 阻断 |

---

## §5 Trace Schema

每个 SOP E2E run 输出：

```json
{
  "scenario_id": "agent.invoke_existing.ping",
  "bundle_id": "core_merged",
  "success": true,
  "final_output": "ping",
  "metrics": {
    "toolsearch_count": 1,
    "wrong_tool_count": 0,
    "source_read_count": 0,
    "turns_to_completion": 2
  },
  "events": [
    {"type": "skill", "name": "core_merged-skill"},
    {"type": "toolsearch", "query": "调用已有 agent ping", "matches": ["invoke-existing-agent"]},
    {"type": "tool", "name": "invoke-existing-agent", "status": "success"}
  ]
}
```

---

## §6 CLI

新增：

```bash
clawcodex-dev sop eval <bundle_path> --scenario agent-lifecycle
clawcodex-dev sop eval <bundle_path> --all --json
clawcodex-dev sop eval <bundle_path> --record traces/sop-eval.ndjson
```

P0 可先用 Python test harness，不要求完整 CLI。

---

## §7 实现位置

| 文件 | 说明 |
|------|------|
| `extensions/sop_converter/eval/scenarios.py` | golden scenarios |
| `extensions/sop_converter/eval/runner.py` | E2E runner |
| `extensions/sop_converter/eval/metrics.py` | 指标汇总 |
| `extensions/sop_converter/eval/report.py` | Markdown/JSON 报告 |
| `tests/sop_e2e/` | E2E 测试 |

---

## §8 验收标准

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | verify-bot 创建+调用场景通过 | E2E 返回 `ping` |
| 2 | trace 记录 Skill/ToolSearch/Tool 顺序 | JSON trace 可断言 |
| 3 | 空转指标可统计 | 记录 ToolSearch 和 wrong_tool_count |
| 4 | 失败报告可定位缺口 | 报告含失败 step/error_code |
| 5 | CI 可运行 smoke subset | 不依赖真实外部 LLM/API |

---

## §9 测试分层

| 层级 | 是否进 CI | 说明 |
|------|-----------|------|
| Unit | 是 | parser/schema/catalog/guard |
| Smoke E2E | 是 | fake SDK + fake model |
| Live E2E | 手动 | 真实 SDK/LLM/API |
| Regression replay | 是 | 使用历史 JSONL/trace 重放 |

---

## §10 与 Feature 的关系

| Feature | 验证点 |
|---------|--------|
| F-56 | catalog 写入/读取/缺失 |
| F-57 | composite workflow 执行 |
| F-58 | contract 推断与 output_schema |
| F-59 | guard 是否减少空转 |
| F-55 | lifecycle metadata 是否改善 ToolSearch 排序 |


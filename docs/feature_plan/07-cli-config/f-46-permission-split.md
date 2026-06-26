# F-46: permission_mode 正交拆分

> 状态: 🔄 进行中（F-46.0 部分完成）
> 章节: docs/feature_plan/07-other/f-46-permission-split.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

把 `permission_mode` 混合 enum（`default` / `plan` / `bypassPermissions` / `acceptEdits` / `dontAsk` 等）拆为三个正交字段。

### 1.2 三字段拆分方案

- `interactive: bool` — 是否需要 TTY 弹 prompt
- `default_decision: Literal["allow", "deny", "ask"]` — 没 policy 命中时的默认
- `audit_log: Literal["none", "minimal", "full"]` — per-tool 决策是否落盘

### 1.3 子特性分解

| Sub | 名称 | 目标 | 状态 |
|-----|------|------|:----:|
| A | `WorkflowConfig.audit_log` 字段（F-46.0） | 先把 audit_log 这一维拆出 | 📋 |
| B | `permission_mode` → 三字段语义糖（F-46.0） | 兼容旧 workflow.yaml | 📋 |
| C | `interactive` 字段（F-46.1） | 显式化 "是否要 TTY 弹 prompt" | 📋 |
| D | `default_decision` 字段（F-46.1） | 显式化 "无人值守默认决策" | 📋 |
| E | `permission_mode` 降级为 shim（F-46.2） | 彻底摆脱 enum | 📋 |
| F | 文档与迁移指南 | 让用户跟得上 | 📋 |

### 1.4 当前基线

| 能力 | 当前状态 |
|------|----------|
| `permission_mode` schema 声明 | ⚠️ 太窄（仅 3 值，runtime 实际 5 值） |
| `dontAsk` 模式触发 ApprovalPolicy headless 卡死 | ❌ 已知 |
| 三个正交概念合在一字段 | ❌ 设计债 |
| `WorkflowConfig.audit_log` 字段 | ❌ 缺失 |

## §2 进度跟踪

### 2.1 已实现

F-46.0: headless auto-override 已实现（`clawcodex_ext/agent/session.py`）。

### 2.2 当前瓶颈

F-46.0 的 `audit_log` 字段依赖 F-45 NDJSON 旁路落地后才能端到端验证。

### 2.3 下一步计划

1. F-46.0: `WorkflowConfig.audit_log` 字段 + `report_writer` 读取
2. F-46.0: `permission_mode` → 三字段 translate 函数
3. F-46.1: interactive + default_decision 字段
4. F-46.2: permission_mode 标 deprecated

## §3 实施细节

### 3.1 验收标准

- `workflow.yaml` 写 `audit_log: full` 时 tool-events.ndjson 落盘
- `permission_mode: bypassPermissions` + `audit_log: full` 组合正确
- 旧 workflow.yaml 不写 audit_log 默认 minimal 不破坏现有 run
- `pytest tests/test_orchestrator_*.py -q` 无回归

### 3.2 风险与约束

1. enum 拆分 breaking change — 旧 workflow.yaml 用户看到 "deprecated" 会慌
2. F-46.0 与 F-45 顺序依赖
3. 上游 TS 未拆分
4. 三字段组合爆炸（3 × 3 × 3 = 27 种组合，部分无意义）

### 3.3 已拟定的设计决定

| # | 决定 | 理由 |
|---|------|------|
| 1 | F-46.0 只拆 audit_log | 拆得越多风险越大 |
| 2 | permission_mode 保留为 backward-compat shim | TS 上游仍用 enum |
| 3 | audit_log 默认 "minimal"（只记 deny） | 节省磁盘 |
| 4 | 不动 AppState.permission_mode | runtime 和 config 不同层 |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |

# F-100: Dreaming 后台记忆整合系统

> 状态: 🔄 进行中（主体已落地，Phase B 待补）
> 章节: docs/feature_plan/03-agent-core/f-100-dreaming.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 背景与目标

从上游 fork 移植 dreaming 子系统（`DreamTask` 后台探索 + `autoDream` 自动 consolidate auto-memory + `/dream` slash skill），让 clawcodex 拥有"空闲时自我整合记忆"的能力。

### 1.2 上游参考实现

上游 `claude-code-best` 在 `KAIROS` / `KAIROS_DREAM` 特性开关下提供完整的 dreaming：

- `src/services/autoDream/` — 后台 consolidate 服务（autoDream.ts 调度、config.ts 配置、consolidationLock.ts 文件锁、consolidationPrompt.ts 总结 prompt）
- `src/tasks/DreamTask/DreamTask.ts` — Dream 任务实现
- `src/skills/bundled/dream.ts` — `/dream` slash skill
- `src/components/tasks/DreamDetailDialog.tsx` — TUI 详情对话框
- `docs/features/auto-dream.md` + `docs/features/kairos.md` — 设计文档

### 1.3 现状（clawcodex 侧）

clawcodex 已在多处为 dreaming 预留"字面量桩"，但原无运行实现：

| 位置 | 现状 | 缺口 |
|------|------|------|
| `src/tasks_core.py:38` | `TaskType` literal 已声明 `"dream"` | 无对应 Task 类 |
| `src/tasks_core.py:75` | `_TASK_ID_PREFIXES["dream"] = "d"` | 无 |
| `src/task_registry.py:184` | 注释标记 Dream 为 out-of-scope | 无 |
| `tests/tasks/test_task_registry.py:202` | `assert get_task_by_type("dream") is None` | 需解锁 |
| `extensions/skills_ext/bundles.py:36` | bundle 列表里有 `"dream"` | 无 skill 实现 |
| `clawcodex_ext/cron_system/runtime.py:126` | 文档提及 dream 为 permanent cron | 未注册 |
| `clawcodex_ext/cron_system/tools.py:82` | dream 列入免清理名单 | 未注册 |

### 1.4 方案

1. **DreamTask**（`src/tasks/dream/dream_task.py`）— 继承 `LocalAgentTask` 模式，调度周期 24h + 立即触发入口
2. **autoDream 服务**（`clawcodex_ext/dreaming/service.py`）— 周期 loop + 错误隔离
3. **consolidationLock**（`clawcodex_ext/dreaming/lock.py`）— 基于分布式锁，TTL 30min
4. **/dream slash skill**（`extensions/skills_ext/builtin/dream.py`）— `/dream run` / `/dream status` / `/dream once`
5. **永久 cron 集成**（`clawcodex_ext/cron_system/builtin_tasks.py`）— 注册 dream/catch-up/morning-checkin

### 1.5 任务拆分

| 任务 | 预计工时 | 依赖 | 状态 |
|------|:--------:|:----:|:----:|
| 100.1 DreamTask 类 | 1天 | — | ✅ |
| 100.2 autoDream 服务主循环 | 1天 | 100.1 | ✅ |
| 100.3 consolidationLock | 0.5天 | 100.2 | ✅ |
| 100.4 /dream slash skill | 0.5天 | 100.1 | ✅ |
| 100.5 永久 cron 集成 | 0.5天 | 100.2 | ✅ |
| 100.6 解锁 test 不变量 | 0.25天 | 100.1 | ✅ |
| 100.7 测试 + 门禁 | 1天 | 全部 | ✅ |

**Phase B 待补**: consolidationLock 30min TTL 增强（0.5天）

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| Phase A | DreamTask 实现 | ✅ | P2 |
| Phase B | 30min TTL 增强 | 📋 | P2 |
| Phase C | autoDream 服务主循环 | ✅ | P2 |
| Phase D | consolidationLock | ✅ | P2 |
| Phase E | /dream slash skill | ✅ | P2 |
| Phase F | 永久 cron 集成 | ✅ | P2 |

### 1.7 风险与缓解

- **LLM 成本**: 默认 24h 周期 + `dreaming.interval_hours` 可配
- **写回竞态**: 复用 workspace lock
- **特性开关**: 不引入 KAIROS/KAIROS_DREAM，直接实现
- **TUI 暂缓**: 本期不做 DreamDetailDialog，先 CLI + skill

### 1.8 落地位置

| 类别 | 落地位置 |
|------|---------|
| DreamTask | `src/tasks/dream/dream_task.py` |
| autoDream 服务 | `clawcodex_ext/dreaming/service.py` |
| consolidationLock | `clawcodex_ext/dreaming/lock.py` |
| /dream slash skill | `extensions/skills_ext/bundled/dream.py` |
| 永久 cron 集成 | `clawcodex_ext/dreaming/cron_integration.py` |
| 测试 | `tests/dreaming/` 106 单测 + 6 E2E |

### 1.9 依赖

| 依赖 | 类型 |
|------|------|
| `src/tasks_core.py` 已有 literal | 内置 |
| `clawcodex_ext/cron_system/dist_lock.py` | 复用 |
| `src/memory/`（auto-memory） | 复用 |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 验证方式 |
|------|--------|---------|
| 2026-06-18 | 100.1~100.7 七子特性全 ✅ | 106 单测 + 12 门禁 + 6 E2E |

### 2.2 当前瓶颈

Phase B 30min TTL 增强待补。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（背景+状态表+方案+任务分解+风险） | 对齐 FEATURE_PLAN.legacy.md |

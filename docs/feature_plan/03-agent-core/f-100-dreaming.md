# F-100: Dreaming 后台记忆整合系统

> 状态: ✅ 已完成（主体已落地，Phase B 30min TTL 增强已完成 — 2026-07-07）
> 章节: docs/feature_plan/03-agent-core/f-100-dreaming.md
> 最后更新: 2026-07-07

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

**Phase B 已完成** ✅（2026-07-07）：consolidationLock 30min TTL 增强已落地。详见 §3 Phase B 增量说明。

### 1.6 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| Phase A | DreamTask 实现 | ✅ | P2 |
| Phase B | 30min TTL 增强 | ✅ | P2 |
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
| 2026-07-07 | Phase B：consolidationLock 30min TTL 增强 ✅ | 16 单测 + 1 service 集成测试 + 455/455 稳定性门禁 |

### 2.2 当前瓶颈

无。F-100 全部完成（包括 Phase B TTL 增强）。

## §3 Phase B 增量说明（2026-07-07）

### 3.1 设计动机

Phase A 的 `consolidationLock` 是被动式 TTL：只在 `try_acquire_consolidation_lock` 内做时效检查，且仅在 holder PID 已死时回收。Linux 的 PID 回收策略下，被复用的 PID + 老 mtime 会让锁永远卡死。

**Phase B** 把 TTL 从被动检查提升为权威新鲜度信号，并新增主动清理入口：

1. **TTL 是权威的** — `try_acquire_consolidation_lock` 在 mtime 超时（>30min）时无条件 reclaim，无论 holder PID 是否还活着。
2. **可被外部主动清理** — `force_release_if_stale()` 让 service 主循环在上 lock gate 之前就能 unlink stale 锁，即使本次 gate chain 提前 short-circuit。
3. **诊断 API** — `get_holder_pid()` / `get_lock_age_seconds()` / `is_lock_stale()` 让 `/dream status`、`/dream once`、调试脚本可以探测锁的状态。

### 3.2 改动清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `clawcodex_ext/dreaming/lock.py` | 新增 4 个 public API (`force_release_if_stale` / `get_lock_age_seconds` / `is_lock_stale` / `get_holder_pid`)，把 TTL 提升为权威 reclaim 信号，修正 HOLDER_STALE_MS 注释 | +106 |
| `clawcodex_ext/dreaming/service.py` | 在 Lock gate 之前增加一次 `force_release_if_stale()` 调用，确保即便上游 gate 被 short-circuit 也保留 stale 锁清理 | +6 |
| `clawcodex_ext/dreaming/__init__.py` | 重新导出 4 个新 public API | +8 |
| `tests/dreaming/test_lock.py` | 新增 14 个 Phase B 单测（诊断 API + TTL reclaim + force_release 边界 + OSError 隔离） | +130 |
| `tests/dreaming/test_service.py` | 新增 2 个 Phase B 集成测试（stale-lock force-released + fresh-lock 仍阻塞） | +56 |

### 3.3 新 API 行为契约

| API | 输入 | 输出 | 行为 |
|-----|------|------|------|
| `get_holder_pid()` | — | `int \| None` | 读锁文件 body。失败/缺失/不可解析 → `None` |
| `get_lock_age_seconds(now_ms=None)` | `now_ms` | `int` | 距上次 stamp 的秒数（`0` = 无锁） |
| `is_lock_stale(now_ms=None)` | `now_ms` | `bool` | `True` 当且仅当锁存在且不可解析 *或* age ≥ TTL |
| `force_release_if_stale(now_ms=None)` | `now_ms` | `bool` | stale → unlink 返回 `True`；fresh/missing → 不动返回 `False`；never raises |

### 3.4 兼容性

- **Phase A 行为保留** — fresh + alive-PID 锁仍 blocked（`test_acquire_lock_blocked_by_foreign_live_pid`、`test_try_acquire_still_blocks_when_fresh` 双层断言）。
- **无外部 schema 变更** — 锁文件格式（mtime + body）完全不变，向前兼容。
- **失败安全** — `force_release_if_stale` 在锁不存在 / 文件系统异常时全部 silently 返回 `False`，绝不抛异常。

### 3.5 测试覆盖

- **16 个新单测**（`tests/dreaming/test_lock.py`）— 覆盖所有 4 个新 API + TTL reclaim + force_release 边界
- **2 个 service 集成测试**（`tests/dreaming/test_service.py`）— 验证 stale lock force-release 接入 gate chain，且 Phase A 的 fresh-lock-blocking 路径未被破坏
- **455/455 稳定性门禁** — 包括 Stage 5 extensions（dreaming 模块 21+ 个 import 验证）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（背景+状态表+方案+任务分解+风险） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-07 | Phase B TTL 30min 增强落地（详见 §3） | 补齐 PROGRESS.md §十三"Phase B 30min TTL 增强待补"项；109 个 dreaming 单测 + 455/455 稳定性门禁全绿 |

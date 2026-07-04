# F-102: Agent Loop Hook 扩展点增强

> 状态: 🔄 进行中（P102-A~E 全部实现）
> 章节: docs/feature_plan/03-agent-core/f-102-hook-extensions.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 背景

对 `clawcodex_ext/query/query.py` 代码审计发现，agent loop 虽有 7 类 18 个扩展点，但均为**命名参数式**硬编码扩展，缺少统一的、可注册的钩子注册表。

### 1.2 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工时 |
|:----:|--------|------|:----:|:--------:|
| P102-A | pre-LLM 通用扩展钩子 | query() Phase 0 之后、_call_model_sync 之前添加回调链 | ✅ | 2-3d |
| P102-B | post-LLM 恢复策略注册表 | if/elif 硬编码恢复链改为注册式 RecoveryStrategy | ✅ | 3-5d |
| P102-C | outbox 类型化 | ToolContext.outbox 从 list[dict] 改为 list[OutboxEvent] | ✅ | 1-2d |
| P102-D | formal plugin hook registry | register_loop_hook(name, fn, phase) 统一 API | ✅ | 2-3d |
| P102-E | 逐 turn 回调注册 | QueryState 添加 on_turn_start / on_turn_end callback | ✅ | 1-2d |

### 1.3 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-68 Feature Gate | 消费者 | P102-A pre-LLM 钩子是条件启用的注入点 |
| F-69 Budget Mode | 消费者 | P102-A pre-LLM 钩子用于注入节俭提示 |
| F-70 Plugin 系统 | 前置依赖 | P102-D formal registry 是插件注册机制的基础 |
| F-84 Context Collapse | 协同 | P102-B 恢复策略注册表可替代当前 CollapseEngine 特殊参数 |

### 1.4 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `clawcodex_ext/query/hook_registry.py` | P102-D | LoopHookPhase / LoopHook / register_loop_hook / call_hooks |
| `clawcodex_ext/query/outbox_types.py` | P102-C | CronPromptEvent / CronMissedEvent / GenericOutboxEvent |
| `clawcodex_ext/query/recovery_strategies.py` | P102-B | RecoveryContext / RecoveryStrategy / 6 内置策略 |

**修改文件**: query.py（5 处 hook 注入）、transitions.py、tool_system/context.py、cron_system/runtime.py、repl/core.py 等。

### 1.5 核心注入点（query.py）

| 注入位置 | Phase | 说明 |
|---------|-------|------|
| while True 顶部 | on_turn_start | P102-E |
| Phase 0 压缩流水线之后 | pre_llm | P102-A |
| LLM 响应返回后 | post_llm | P102-D |
| no-follow-up 分支 | recovery | P102-B |
| _run_tools_partitioned 之前 | pre_tool | P102-D |
| _run_tools_partitioned 之后 | post_tool | P102-D |
| state 重建之前 | on_turn_end | P102-E |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| 2026-06-22 | P102-A~E 全部代码实现 | 3 新建 + 9 修改文件 | py_compile 验证 |

### 2.2 待验证项

- mypy `--strict` 验证（无运行环境）
- 稳定性门禁全量运行（245/245）
- 集成测试

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_loop_hook("pre_llm", fn)` 注册后，query() 每次 LLM 调用前调用 fn | ✅ 实现 |
| 2 | `register_recovery_strategy(err_type, fn)` 注册后优先调用 | ✅ 实现 |
| 3 | outbox 元素有类型标注 | 🔄 待验证 |
| 4 | 稳定性门禁 + orchestrator 测试通过 | 🔄 待验证 |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |

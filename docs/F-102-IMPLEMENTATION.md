# F-102 Agent Loop Hook 扩展点增强 — 实现总结

> 文档路径: `docs/F-102-IMPLEMENTATION.md`  
> 版本: v1.0  
> 更新日期: 2026-06-22  
> 状态: 🟡 部分完成（核心实现全部落地，待 mypy `--strict` 验证 + 稳定性门禁全量跑通）

---

## 概述

F-102 填补了 agent loop (`query()`) 中 5 个 hook 扩展点缺口，为 F-68 Feature Gate / F-70 Plugin 系统提供基础设施，使新特性无需修改 `query()` 函数体即可注入自定义逻辑。

5 个子特性全部实现完成：

| 编号 | 子特性 | 状态 | 核心文件 |
|:----:|--------|:----:|---------|
| P102-A | pre-LLM 通用扩展钩子 | ✅ | `clawcodex_ext/query/query.py` |
| P102-B | post-LLM 恢复策略注册表 | ✅ | `clawcodex_ext/query/recovery_strategies.py` + `query.py` |
| P102-C | outbox 类型化 | ✅ | `clawcodex_ext/query/outbox_types.py` + 多文件适配 |
| P102-D | formal plugin hook registry | ✅ | `clawcodex_ext/query/hook_registry.py` + `query.py` |
| P102-E | 逐 turn 回调注册 | ✅ | `clawcodex_ext/query/transitions.py` + `query.py` |

---

## 新建文件

### 1. `clawcodex_ext/query/hook_registry.py` (P102-D)

- `LoopHookPhase` Literal: `pre_llm` / `post_llm` / `pre_tool` / `post_tool` / `on_turn_start` / `on_turn_end`
- `LoopHook` dataclass: 存储 name / fn / phase / priority
- 全局 `_REGISTRY` 按 phase 分桶，按 priority 排序
- **公共 API**:
  - `register_loop_hook(name, fn, phase, priority=0)` — 注册 hook（同名自动替换）
  - `unregister_loop_hook(name, phase)` — 注销 hook
  - `call_hooks(phase, *args, **kwargs)` — 按优先级顺序调用，返回值传播替换 args
  - `list_hooks(phase=None)` — 只读列表（调试/测试）
  - `clear_hooks(phase=None)` — 清空注册表（测试隔离）
- Hook 异常处理：单个 hook raise 被忽略，不影响后续 hook 执行

### 2. `clawcodex_ext/query/outbox_types.py` (P102-C)

- `CronPromptEvent` — scheduler 触发的 cron 任务提示
- `CronMissedEvent` — missed one-shot 通知
- `GenericOutboxEvent` — 通用事件，兼容 `tool`/`message`/`questions` 等任意字段
- `OutboxEvent = Union[CronPromptEvent, CronMissedEvent, GenericOutboxEvent]`
- 所有 dataclass 实现 `get()` / `__getitem__()` / `__contains__()`，兼容现有 dict 读取代码
- `outbox_event_from_dict(d)` — 从原始 dict 反序列化为类型化事件

### 3. `clawcodex_ext/query/recovery_strategies.py` (P102-B)

- `RecoveryContext` dataclass — 恢复策略执行时传入的完整上下文（state / last_message / config / params / messages / assistant_messages / error_type）
- `RecoveryStrategy` dataclass — name / fn / priority
- `RecoveryStrategyFn` — 支持 sync 和 async 两种策略函数
- **公共 API**:
  - `register_recovery_strategy(name, fn, priority=0)`
  - `unregister_recovery_strategy(name)`
  - `find_recovery_strategies(error_type, state)` — 返回按优先级排序的策略列表
  - `clear_recovery_strategies()` — 测试隔离
- **内置策略**（6 个，按优先级排序）:
  1. `max_output_tokens_escalate` (priority=10) — 首次 max_output_tokens 错误提升到 ESCALATED_MAX_TOKENS
  2. `max_output_tokens_recovery` (priority=20) — 注入恢复提示并重试
  3. `max_output_tokens_exhausted` (priority=45) — 恢复次数用尽，yield last_message 并终止
  4. `collapse_engine_recovery` (priority=30) — PTL 错误 + CollapseEngine 配置时走引擎恢复
  5. `reactive_compact_recovery` (priority=40) — PTL/media_size 错误 + reactive_compact 启用时走 LLM 压缩恢复
  6. `media_size_fallback` / `prompt_too_long_fallback` (priority=100) — 所有恢复策略耗尽后终止

---

## 修改文件

### `clawcodex_ext/query/query.py` — 核心注入点

| 注入位置 | Phase | 说明 |
|---------|-------|------|
| while True 顶部 | `on_turn_start` | P102-E: 调用 `state.on_turn_start_callbacks` |
| Phase 0 压缩流水线之后 | `pre_llm` | P102-A: `call_hooks("pre_llm", messages, system_prompt)` → 修改后传给 `_call_model_sync` |
| LLM 响应返回后 | `post_llm` | P102-D: `call_hooks("post_llm", assistant_messages, tool_use_blocks)` → 修改后进入工具执行或恢复 |
| no-follow-up 分支 | recovery | P102-B: 将 max_tokens/PTL/media_size 的硬编码 `if/elif/continue` 链替换为 `find_recovery_strategies` + 策略执行 |
| `_run_tools_partitioned` 之前 | `pre_tool` | P102-D: `call_hooks("pre_tool", tool_use_blocks)` → 修改后执行工具 |
| `_run_tools_partitioned` 之后 | `post_tool` | P102-D: `call_hooks("post_tool", tool_results)` → 修改后 yield |
| state 重建之前 | `on_turn_end` | P102-E: 调用 `state.on_turn_end_callbacks` + `call_hooks("on_turn_end", state)` |

**恢复策略调用逻辑**（替代原有硬编码链）：
1. 检测 `last_message` 的 withheld 错误类型（max_output_tokens / prompt_too_long / media_size）
2. 构建 `RecoveryContext`
3. 遍历 `find_recovery_strategies(error_type, state)`，按优先级执行
4. 支持 async 策略（检测 coroutine 并 `await`）
5. 策略返回 `(new_state, yield_messages)` → `new_state` 非 None 时 `continue`；`new_state` 为 None 时 yield 并 terminate
6. 无策略适用时 fallthrough 到原有 `completed` 终止逻辑

### `clawcodex_ext/query/transitions.py` — P102-E

- `QueryState` 添加两个字段：
  - `on_turn_start_callbacks: list[Callable[[QueryState], None]]`
  - `on_turn_end_callbacks: list[Callable[[QueryState], None]]`

### `clawcodex_ext/tool_system/context.py` — P102-C

- `outbox: list[dict[str, Any]]` → `outbox: list[OutboxEvent]`
- 导入 `OutboxEvent` from `clawcodex_ext.query.outbox_types`

### `clawcodex_ext/cron_system/runtime.py` — P102-C

- 导入 `CronPromptEvent`, `CronMissedEvent`
- `on_fire` / `on_fire_task` / `on_missed` 中的 `outbox.append({"type": "...", ...})` 全部改为 `outbox.append(CronPromptEvent(...))` / `outbox.append(CronMissedEvent(...))`

### `clawcodex_ext/repl/core.py` — P102-C

- `_drain_cron_outbox` 中 `isinstance(entry, dict)` 改为 `hasattr(entry, "get")`，兼容 OutboxEvent dataclass
- 保留 legacy dict fallback（backward compat）

### `clawcodext/command_system/builtins.py` — P102-C

- `_append_cron_outbox` 中 `outbox.append({"type": "cron_prompt", ...})` → `outbox.append(CronPromptEvent(...))`

### `clawcodex_ext/query/agent_loop_compat.py` — P102-C

- `isinstance(entry, dict)` 改为 `hasattr(entry, "get")`
- `entry["message"]` 改为 `entry.get("message")`

### 工具 outbox 写入点（6 个文件）— P102-C

| 文件 | 改动 |
|------|------|
| `tool_system/tools/ask_user_question.py` | `GenericOutboxEvent.from_dict({"tool": "AskUserQuestion", ...})` |
| `tool_system/tools/brief.py` | `GenericOutboxEvent.from_dict({"tool": "Brief", ...})` |
| `tool_system/tools/send_user_message.py` | `GenericOutboxEvent.from_dict({"tool": "SendUserMessage", ...})` |
| `tool_system/tools/structured_output.py` | `GenericOutboxEvent.from_dict({"tool": "StructuredOutput", ...})` |
| `tool_system/tools/ask_issue_author.py` | `GenericOutboxEvent.from_dict({"tool": "AskIssueAuthor", ...})` |

---

## 测试

新建测试文件 3 个：

| 文件 | 覆盖内容 |
|------|---------|
| `tests/clawcodex_ext/query/test_hook_registry.py` | register/unregister/call_hooks/priority/clear/exception 隔离 |
| `tests/clawcodex_ext/query/test_outbox_types.py` | CronPromptEvent/CronMissedEvent/GenericOutboxEvent/getitem/contains/from_dict/ToolContext 类型标注 |
| `tests/clawcodex_ext/query/test_recovery_strategies.py` | 内置策略注册/优先级/escalate/fallback/条件判断 |

所有测试通过验证（Python 运行时验证）。

---

## 验收标准检查

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_loop_hook("pre_llm", fn)` 注册后，`query()` 每次 LLM 调用前调用 `fn(messages, system_prompt)` | ✅ 实现 |
| 2 | `register_recovery_strategy(err_type, fn)` 注册后，API 返回对应错误时优先调用注册的恢复策略 | ✅ 实现 |
| 3 | `ToolContext.outbox` 元素有类型标注，`mypy --strict` 通过 | 🟡 实现待验证（无 mypy 运行环境） |
| 4 | 现有 245/245 稳定性门禁 + 全部 orchestrator 测试通过 | 🟡 待验证（无 pytest 运行环境） |

---

## 后续验证项

1. **mypy --strict 验证**：在 `clawcodex_ext/query/` 和 `clawcodex_ext/tool_system/` 上运行 `mypy --strict`，确认无类型错误
2. **稳定性门禁全量运行**：运行 `pytest tests/ -q`，确认 245/245 通过
3. **集成测试**：注册一个 dummy pre_llm hook 和 recovery strategy，验证 query loop 正确调用

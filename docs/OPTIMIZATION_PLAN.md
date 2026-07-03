# 二开扩展层优化分析与实施计划

> 范围：`extensions/`（Layer 2 扩展子系统）与 `clawcodex_ext/`（Layer 1 补丁层），约 20 万行扩展代码。
> 方法：四路并行代码审计（orchestrator / clawcodex_ext 核心 / ports·remote·sop_converter / 解耦与跨层）。
> 生成日期：2026-06-27
> 性质：现状评估 + 优先级排序的改进建议，**非强制清单**——落地需结合 CLAUDE.md 解耦原则逐项评估。

---

## 摘要

| 主题 | 高优先级问题数 | 核心症状 |
|------|---------------|---------|
| 架构腐化（God Object） | 5 | 单文件 1000–5300 行，单类/单方法混杂多职责 |
| 性能热路径 | 4 | 函数内重复 import、异步循环中同步 subprocess、缺缓存 |
| 解耦违规 | 3 | `extensions/`→`src.` 深耦合、`clawcodex_ext/`→`extensions/` 反向依赖、Protocol 形同虚设 |
| 错误处理与可观测性 | 2 | 裸 `except Exception:` 泛滥（百余处）、fire-and-forget task 无背压 |

**建议落地顺序（性价比优先）**：① 函数内 import 上提 → ② 异步路径同步 subprocess 改造 → ③ 收窄异常 + 补 logging → ④ 拆分 God Object → ⑤ 解耦违规整改。

---

## 一、架构腐化：God Object（高）

几个文件膨胀成"全能类"，混杂大量本应分离的职责。

| 文件 | 行数 | 症状 | 建议拆分 |
|------|------|------|---------|
| `clawcodex_ext/repl/core.py:588` `ClawcodexREPL` | 5342 | prompt-toolkit 接线、键绑定、权限、cron 调度、新旧两套命令路由、TUI 切换、后台 fork、流式/diff 渲染、会话存取、resume 回放、重登录全在一类 | `repl/commands.py`（命令路由 ~800 行）、`repl/rendering.py`（预览/diff/replay ~700 行）、`repl/cron.py`（~250 行）、`repl/permissions.py`（~200 行） |
| `extensions/orchestrator/orchestrator.py:76` `Orchestrator` | 2344 | 轮询、派发、意图解析、重试、review 反馈、控制命令、遥测全揽；`_run_issue` 单方法 ~200 行嵌套 try/except | 抽出 `IntentResolver` / `RetryQueueProcessor` / `ReviewFeedbackProcessor` / `ControlCommandProcessor` |
| `extensions/orchestrator/agent_runner.py:741` `run()` | 2322 | `run()` 约 1200 行巨方法：事件循环 + 停滞/循环/只读螺旋检测 + 限流 + transcript 缓冲 + 控制 socket 交织 | 状态机式 `TurnExecutor` / `GuardEvaluator` / `TranscriptManager` / `ControlSocketManager` |
| `extensions/ports/bridge/remote_bridge_core.py` | 1134 | `TokenRefreshScheduler` / `FlushGate` / `RemoteBridgeCore` / `AuthFailureRecovery` 同居一文件 | `token_refresh.py` / `flush_gate.py` / `auth_recovery.py` |
| `extensions/sop_converter/skill_grouper.py` | 1315 | `SkillGrouper` + 5 种分组算法 + 多个 model 类 | `strategies/{keyword_match,io_relation,component_group,llm_semantic}.py` + `models.py` |
| `extensions/orchestrator/cli/issue.py` | 2581 | 15+ 子命令 handler + parser + 业务逻辑单文件 | `cli/issue/{commands,parsers,shared}.py` 包化 |

---

## 二、性能热路径（高）

### 2.1 函数内重复 import —— 最普遍的隐性开销
`_load_heavy_runtime()` 机制本是为解决此问题，但只覆盖约 30 个符号，其余被本地 import 绕过。

- `clawcodex_ext/repl/core.py`：**28+ 处**每次调用重 import（如 `_bottom_toolbar` 内 import advisor/pricing：`core.py:1029,1070`；`chat` 内 import 一堆 `src` 模块：`core.py:4492,4497,4544,4702`）。
- `clawcodex_ext/query/query.py`：**20+ 处**在每个 query 轮次内 import（`query.py:130,167,314,315,488,489,579`）。

**修复**：全部上提到模块级（或并入 `_load_heavy_runtime()` 全局块）。纯收益、零风险。

### 2.2 异步循环中的同步 subprocess —— 阻塞事件循环（真 bug）
- `extensions/orchestrator/agent_runner.py:2117` `_should_continue()` 用 `subprocess.run` 跑 `git status`/`git rev-parse`。
- `extensions/orchestrator/git_sync.py:930-950,531-566` 全程同步 git 调用。

**修复**：改 `asyncio.create_subprocess_exec` 或 `asyncio.to_thread`。

### 2.3 缺缓存 / 全量重算
- `extensions/orchestrator/issue_registry.py:184` 每次变更全量重写 JSON → 改脏标记批量 flush。
- `extensions/orchestrator/cli/dashboard.py:1247` 每 2s SSE 心跳全量重读 registry → 改 inotify/watchdog 监听文件变更。
- `extensions/sop_converter/skill_grouper.py:444,682` O(n²) 分组合并循环 → 堆 + 预计算 Jaccard。
- `clawcodex_ext/context_system/prompt_assembly.py:586` 系统提示词每轮重建 → `lru_cache` 按 `(cwd, git_head_mtime, tool_registry_version)` 键缓存。
- `extensions/orchestrator/repo_tracker/client.py:200` 每次轮询拉全部 comment 再过滤 → 用 API `since` 参数或缓存 comment ID。

---

## 三、解耦违规（高 —— 直接违反 CLAUDE.md 黄金法则）

### 3.1 `extensions/` 深度直连 `src.` 内部模块（绕过 capabilities 层）
| 文件 | 违规 import |
|------|------------|
| `extensions/ports/bridge/remote_bridge_core.py:59-90` | `src.bridge.bounded_uuid_set` / `code_session_api` / `messaging` / `jwt_utils` |
| `extensions/ports/bridge/repl_bridge.py:67-100` | `src.bridge.bridge_api` / `bridge_pointer` / `jwt_utils` |
| `extensions/ports/bridge/bridge_main.py:71-96` | `src.bridge.bridge_api` / `session_runner` / `work_secret` |
| `extensions/ports/transports/hybrid_v1.py:50-58` | `src.transports.*` / `src.utils.session_ingress_auth` |
| `extensions/remote_api/runner.py:189-294` | `src.bootstrap.state` / `src.config` / `src.providers` / `src.tool_system.defaults` |
| `extensions/sop_converter/skill_grouper.py:27,1017` | `src.providers.base` |
| `extensions/tool_system_ext/registry_ext.py:23-24` | `src.tool_system.build_tool` / `registry` |

**修复**：在 `extensions/capabilities/` 补 bridge/transport/orchestrator 的 Protocol，扩展依赖 Protocol，具体实现以适配器/注册表运行时绑定。

### 3.2 `clawcodex_ext/`（L1）反向 import `extensions/`（L2）—— 方向错误
| 文件 | 违规 import |
|------|------------|
| `clawcodex_ext/entrypoints/orchestrator.py:67-105` | `extensions.orchestrator.cli.*` |
| `clawcodex_ext/cli/pos_cmd/commands.py:41-603` | `extensions.sop_converter.*` |
| `clawcodex_ext/query/query.py:579,674` | `extensions.api.query_middleware` |
| `clawcodex_ext/tool_system/defaults.py:22` | `extensions.tool_system_ext.registration` |
| `clawcodex_ext/agent/session.py:88,146` | `extensions.agent.session_persist` |
| `clawcodex_ext/permissions/modes.py:132,145` | `extensions.permissions.perms_reader` |

> 例外：`clawcodex_ext/capabilities/__init__.py` 作为 re-export 桥是文档明示的合法用法。

**修复**：将 CLI 派发/query 中间件/工具扩展下沉回 `clawcodex_ext/`，或反转依赖（让 `extensions/` 依赖 `clawcodex_ext/` 接口）。

### 3.3 capabilities Protocol 形同虚设
8 个 Protocol 中仅 `LLMProviderProtocol` 真正被用（`clawcodex_ext/providers/_litellm_adapter.py:44`），其余无 `isinstance`/结构化使用。大量"函数内懒 import"正是这种紧耦合规避循环依赖的症状（`agent_runner.py:253-277`、`remote_api/runner.py:189-191` 等）。

---

## 四、错误处理与可观测性（高）

### 4.1 裸 `except Exception:` 泛滥
| 文件 | 数量 | 危险点 |
|------|------|--------|
| `clawcodex_ext/repl/core.py` | **49** | `_bottom_toolbar`(1104) 全包 catch 吞掉状态栏任何错误使调试不能 |
| `clawcodex_ext/command_system/builtins.py` | **20+** | `compact_command_call`/`context_command_call` 掩盖真 bug |
| `extensions/ports/bridge/repl_bridge.py` | 28 | session 创建/重连(317,346,355) 把 `NameError` 当良性失败 |
| `extensions/ports/bridge/bridge_main.py` | 12 | 轮询退避(512) 把 `MemoryError` 当瞬时网络错误**无限重试** |
| `extensions/orchestrator/*` | 30+ | telemetry/control socket `except: pass` 静默吞错 |

**修复**：收窄异常类型；每个 `except` 至少 `logger.exception(...)`；顶层才保留 `except Exception: logger.exception; raise` 安全网。

### 4.2 fire-and-forget `create_task` 无背压
`websocket_v1.py:415,535,750` 与 `remote_bridge_core.py:696-853`（约 10+ 处）发后即忘，无 task 引用、无法取消、慢传输时无限堆积；`ws.close()` 也以 `create_task` 调度，事件循环关闭时可能泄漏 socket。

**修复**：加 `asyncio.Semaphore`/有界队列；存 task 引用并在 `close()`/`teardown()` 显式取消。

---

## 五、代码重复 / Monkey-patch 散落 / 测试缺口（中·低）

- **重复逻辑**：`agent_runner.py` 事件广播块重复 4 次(1100,1174,1234)→ 抽 `_broadcast_event`；bridge `_safe_ack`/kill 信号跨文件重复(`repl_bridge.py:862` / `bridge_main.py:790` / `session_runner.py:487`)→ 抽 `bridge_utils.py`；`repl/core.py` 新旧命令路由双轨(3343-3748)→ 统一走新命令系统。
- **Monkey-patch 散落**：10+ 个 `install_*` 在 import 时各改全局（`__init__.py:41-44` 等）→ 收敛成声明式 `ExtensionRegistry`（`PatchSpec(phase, target, patch_fn)`）。
- **测试缺口**：bridge（remote_bridge_core/repl_bridge/bridge_main）、orchestrator 核心、sop_converter 几乎零单测 → 用 Protocol mock 补单测。
- **死代码**：`extensions/orchestrator/progress_reporter.py` 为 F-40 后的向后兼容 shim，疑仅测试引用，待审计后删除。

---

## 六、落地路线图

| 阶段 | 任务 | 风险 | 收益 | 符合解耦 |
|------|------|------|------|---------|
| P0 | 函数内 import 上提（`repl/core.py` + `query/query.py`） | 极低 | 冷启动 + 每轮开销 | ✅ 纯 L1 内部 |
| P0 | 异步路径同步 subprocess 改造（`agent_runner.py` / `git_sync.py`） | 低 | 修事件循环阻塞真 bug | ✅ 纯 L2 内部 |
| P1 | 收窄 `except Exception` + 补 logging（逐文件） | 低 | 可观测性 | ✅ |
| P1 | bridge transport 加背压 + task 生命周期管理 | 中 | 修资源泄漏 | ✅ |
| P2 | 拆分 God Object（先 repl/core.py 或 orchestrator.py 单点试水） | 中 | 可维护性 | ✅ |
| P3 | 解耦违规整改（先补 `extensions/capabilities/` Protocol） | 高 | 合规 + 上游同步 | ✅ 核心目标 |

> **判断原则（援引 CLAUDE.md）**：解耦是手段不是目的。若整改增加的复杂度（间接层 + 维护负担 + 性能成本）超过直接修改的合并成本，应选直接修改并在 PR 标注原因与上游兼容性标记。

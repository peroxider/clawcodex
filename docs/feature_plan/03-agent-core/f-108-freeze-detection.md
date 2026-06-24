# F-108: Freeze Detection & Auto-Recovery

> 状态: 📋 规划中
> 章节: docs/feature_plan/03-agent-core/f-108-freeze-detection.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

系统性解决 clawcodex 偶发软件卡死与 LLM 对话卡死问题。全链路代码审计发现 8 个卡死风险点（2 CRITICAL + 3 HIGH + 2 MEDIUM + 1 LOW），采用四层混合方案（Layer 0 快速修复 + Layer 1 冻结检测 + Layer 2 硬超时 + Layer 3 自动恢复 + Layer 4 诊断命令），确保用户在卡死发生后 < 30s 内自动恢复或收到明确诊断。

### 1.2 卡死风险点审计

审计范围：`clawcodex_ext/agent/run_agent.py`、`clawcodex_ext/entrypoints/headless.py`、`clawcodex_ext/tui/agent_bridge.py`、`clawcodex_ext/query/query.py`、`extensions/api/query.py`、`clawcodex_ext/providers/anthropic_provider.py`、`src/utils/stream_watchdog.py`。

| # | 卡死点 | 位置 | 严重度 | 现有防护 | 根因 |
|---|--------|------|:------:|----------|------|
| 1 | API 流式响应无任何 chunk 到达 | `_call_model_sync` → provider.chat_stream_response() | **CRITICAL** | StreamWatchdog(90s) + F-99 read_timeout(5s) | LLM 服务端卡死 |
| 2 | TUI 权限弹窗不响应 | AgentBridge._permission_handler → done.wait() | **CRITICAL** | ❌ 无超时 | UI bug / 模态弹窗未渲染 |
| 3 | AskUserQuestion 弹窗不响应 | AgentBridge._ask_user_handler → done.wait() | **CRITICAL** | ❌ 无超时 | UI bug |
| 4 | Agent loop 永久死循环 | query() while-true 循环 | **HIGH** | max_turns 计次 | LLM 行为失控 |
| 5 | headless future 永远不完成 | QueryRunner.stream() → future = run_in_executor() | **HIGH** | ❌ 无硬超时 | 工作线程死锁 |
| 6 | Bash/Edit 工具执行挂起 | tool_system tools/ | **HIGH** | ❌ 无工具级超时 | 子进程 I/O 阻塞 |
| 7 | TUI 主渲染线程死锁 | Textual 事件循环 | **MEDIUM** | ❌ 无 UI watchdog | _post() 队列满 |
| 8 | conversation persistence 阻塞 | session.save_transcript() + add_message() | **LOW** | try/except | 磁盘故障/NFS 挂住 |

### 1.3 四层方案架构

```
Layer 4: 诊断命令 — freeze-report / diag viewer / SIGUSR1 dump
Layer 3: 自动恢复 — permission 超时→auto-deny / tool 超时→cancel / turn 超时→abort
Layer 2: 硬超时防护 — agent_loop(600s) / turn(300s) / tool(120s) / permission(30s) / freeze(60s)
Layer 1: 冻结检测 — FreezeDetector watchdog 线程每 10s 检查 → 超时 60s → dump 线程栈
Layer 0: 快速修复 — P108-A: done.wait(timeout=30) → auto-deny
                     P108-B: asyncio.wait_for(future, 300)
                     P108-C: asyncio.wait_for(tool_exec, 120)
```

### 1.4 子特性分解

| # | 子特性 | 改动文件 | 改动量 | 风险 | 工时 |
|:-:|--------|----------|:------:|:----:|:----:|
| A | Permission/AskUser done.wait(30) → auto-deny | agent_bridge.py | ~20 行 | 低 | 0.5d |
| B | headless query future asyncio.wait_for(300) | extensions/api/query.py | ~10 行 | 低 | 0.5d |
| C | Tool 执行 asyncio.wait_for(120) | tool_system/ | ~50 行 | 中 | 1d |
| D | FreezeDetector 冻结检测 + thread stack dump | claws/diagnostics/freeze_detector.py | ~200 行 | 低 | 1.5d |
| E | 超时配置 schema 扩展 | schema.py + settings/ | ~80 行 | 低 | 1d |
| F | Agent loop / turn / tool 三层硬超时 | query.py + _call_model_sync | ~150 行 | 中 | 1.5d |
| G | 自动恢复策略 | agent_bridge.py + query.py | ~100 行 | 中 | 1.5d |
| H | freeze-report CLI 子命令 | 新建 CLI 命令 | ~150 行 | 低 | 1d |

**预计总工时**: 7 天

### 1.5 详细设计

#### P108-A — Permission/AskUser 超时（Layer 0, #2 #3）

```python
# _permission_handler: 超时 → auto-deny
done.wait(timeout=30.0)
if not done.is_set():
    outcome["allowed"] = False
    outcome["enable"] = False

# _ask_user_handler: 超时 → 返回空 dict
done.wait(timeout=30.0)
if not done.is_set():
    outcome["answers"] = {}
```

**恢复行为**: 当前 turn 继续执行，用户无明显感知。

#### P108-B — Headless Query Future 超时（Layer 0, #5）

```python
exit_code = await asyncio.wait_for(future, timeout=300.0)
```

超时触发 `TimeoutError` → `SessionComplete(reason="timeout")`，不丢失已完成结果。

#### P108-C — Tool 执行超时（Layer 0, #6）

```python
try:
    result = await asyncio.wait_for(
        execute_tool(tool_call, context),
        timeout=_resolve_tool_timeout(tool_call.name),
    )
except asyncio.TimeoutError:
    result = ToolResult(is_error=True, error=f"Tool {tool_call.name} timed out after 120s")
```

#### P108-D — FreezeDetector 冻结检测（Layer 1）

```python
class FreezeDetector:
    """监控 agent loop 活动，检测到冻结时 dump 诊断信息。"""
    def __init__(self, threshold: float = 60.0, check_interval: float = 10.0):
        self._threshold = threshold
        self._check_interval = check_interval
        self._last_heartbeat: float = time.monotonic()
        self._lock = threading.Lock()
        self._watchdog: threading.Thread | None = None

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def check(self) -> bool:
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed >= self._threshold:
            stacks = self._dump_thread_stacks()
            append_debug_event(None, "freeze_detected", elapsed_seconds=round(elapsed, 1), thread_stacks=stacks)
            return True
        return False

    def _dump_thread_stacks(self) -> list[dict]:
        result = []
        for tid, frame in sys._current_frames().items():
            stack = "".join(traceback.format_stack(frame))
            result.append({"thread_id": tid, "stack": stack})
        return result

    def start(self) -> None:
        if self._watchdog is not None: return
        self._watchdog = threading.Thread(target=self._run, daemon=True, name="freeze-detector")
        self._watchdog.start()

    def _run(self) -> None:
        while True:
            time.sleep(self._check_interval)
            self.check()
```

#### P108-E — 超时配置 schema 扩展（Layer 2）

| 配置键 | 类型 | 默认值 | 环境变量 |
|--------|------|:------:|---------|
| freeze.agent_loop_timeout_s | int | 600 | CLAWCODEX_AGENT_LOOP_TIMEOUT |
| freeze.turn_timeout_s | int | 300 | CLAWCODEX_TURN_TIMEOUT |
| freeze.tool_timeout_s | int | 120 | CLAWCODEX_TOOL_TIMEOUT |
| freeze.permission_timeout_s | int | 30 | CLAWCODEX_PERMISSION_TIMEOUT |
| freeze.threshold_s | int | 60 | CLAWCODEX_FREEZE_THRESHOLD |

所有超时支持 `0` 表示"不超时"（回退旧行为）。

#### P108-F — Agent loop / turn / tool 三层硬超时（Layer 2）

1. Agent loop 超时（最外层）：asyncio.wait_for(agent_loop_timeout_s)
2. Turn 超时（中间层）：asyncio.wait_for(turn_timeout_s)
3. Tool 超时（内层）：asyncio.wait_for(tool_timeout_s)

超时触发协作式取消，保存已完成 turn 的结果。

#### P108-G — 自动恢复策略（Layer 3）

| 卡死类型 | 恢复策略 | 用户感知 |
|----------|---------|---------|
| Permission 弹窗超时 | auto-deny → 继续 agent loop | 无 |
| AskUser 超时 | 返回空 dict → 继续 agent loop | 模型可能重试 |
| 单 LLM turn 超时 | AbortController.abort() → 下一 turn | 短暂提示 |
| 工具执行超时 | CancelledError → agent 继续 | 工具超时提示 |
| Agent loop 总超时 | abort → SessionComplete | 完整的结果输出 |

所有恢复行为**不丢失已完成的对话内容**。

#### P108-H — freeze-report CLI 子命令（Layer 4）

```bash
clawcodex-dev diag freeze-report        # 生成最近的 freeze dump
clawcodex-dev diag viewer               # 查看诊断日志
CLAWCODEX_FREEZE_DIAG=1 clawcodex-dev   # 实时启用冻结检测
```

输出：最后 N 个事件的时间线 + 各线程 stack trace + heartbeat gap 分布

### 1.6 实施建议顺序

```
Phase 1 (0.5d): [A] Permission 超时 + [B] headless future 超时
Phase 2 (1d): [C] Tool 超时
Phase 3 (1.5d): [D] FreezeDetector + [E] 配置 schema
Phase 4 (1.5d): [F] 三层硬超时贯穿
Phase 5 (1.5d): [G] 自动恢复策略
Phase 6 (1d): [H] freeze-report CLI
```

### 1.7 验收标准

| # | 验收项 | 验收方式 |
|:-:|--------|---------|
| 1 | Permission 弹窗不响应 ≥30s → agent loop 自动继续 | 单元测试 |
| 2 | headless run 超过 300s → SessionComplete(reason="timeout") | 单元测试 + E2E |
| 3 | Tool 执行超过 120s → ToolResult(is_error=True) | 单元测试 |
| 4 | FreezeDetector 60s 无 heartbeat → dump thread stacks | 单元测试 |
| 5 | CLAWCODEX_FREEZE_DIAG=1 环境变量生效 | 单元测试 |
| 6 | clawcodex-dev diag freeze-report 输出非空 | 手动 + E2E |
| 7 | 0 个 src/ 文件被修改（完全解耦扩展实现） | git diff --stat src/ |

### 1.8 关键设计决定

1. Permission/AskUser 超时值 30s: 低于 TUI 渲染超时，auto-deny 安全
2. Agent loop 超时 600s: 足够大多数任务完成
3. FreezeDetector 60s 阈值: 与 StreamWatchdog 90s 错开，两阶段互不干扰
4. 不修改 src/：所有修改落在 clawcodex_ext/、extensions/
5. timeout=0 = 不超时：提供快速回退路径

### 1.9 依赖与协同

| 依赖 | 说明 |
|------|------|
| agent_bridge.py | P108-A |
| extensions/api/query.py | P108-B |
| tool_system/ | P108-C |
| query.py | P108-F |
| extensions/orchestrator/config/schema.py | P108-E |
| clawcodex_ext/diagnostics/ | P108-D+H |
| F-99 Ctrl+C 中断优化 | 互不冲突 |

## §2 进度跟踪

尚未开始实现。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（风险点+代码示例+配置+恢复策略） | 对齐 FEATURE_PLAN.legacy.md |

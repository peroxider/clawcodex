# F-89: Proactive 自主模式 + KAIROS Tick 集成

> 状态: 🟡 KAIROS TickScheduler 已落地(`clawcodex_ext/services/kairos/`,746 行,6 模块);PROACTIVE 整套能力(状态机 + `<tick>` 注入 + SleepTool 协同 + 系统提示注入)待补
> 章节: `docs/feature_plan/06-ccb-benchmark/f-89-proactive.md`
> 最后更新: 2026-06-30
> 缺口来源: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)

## §1 设计规划

### 1.1 目标

对标 CCB `PROACTIVE` + `KAIROS` 双 feature flag,在 `clawcodex_ext/services/kairos/` 已落地 `TickScheduler` 原语的基础上,补齐面向用户的 `/proactive` 命令、`ProactiveController` 状态机、`<tick>` 提示注入机制、`SleepTool` 双向唤醒、REPL 状态栏倒计时、`automation_state` 元数据透出到 F-82 Remote Control,使 ClawCodex 支持 tick 驱动的自主 agent 工作模式。

### 1.2 背景

**已完成基础设施**(`clawcodex_ext/services/kairos/`,共 746 行):

| 模块 | 行数 | 内容 |
|------|------|------|
| `models.py` | 223 | `TickConfig` / `TickEvent` / `BriefSummarySnapshot` / `DailyLogEntry` / `format_local_timestamp` |
| `scheduler.py` | 244 | `TickScheduler`(继承 `PeriodicDaemon`,支持 jitter / pause / resume / drift-free fire) |
| `brief.py` | 95 | `BriefSummaryBuilder`(status bar 简报生成) |
| `daily_log.py` | 94 | `append_log()` / `read_recent()`(每日 tick 日志) |
| `__init__.py` | 66 | 公共导出 |
| `exceptions.py` | 24 | `SchedulerStateError` 等 |

**CCB 上游关键常量**(从 `src/proactive/useProactive.ts:25` + `src/commands/proactive.ts:7-8`):

| 常量 | 值 | 含义 |
|------|-----|------|
| `TICK_INTERVAL_MS` | `30_000`(30 秒) | prompt cache TTL ~5 分钟之下,保持 cache warm |
| `TICK_TAG` | `<tick>` | XML 标签,内含 `HH:MM:SS` 本地时间 |
| Feature flag | `PROACTIVE` OR `KAIROS` | 任一启用即激活命令 |

**缺口**(用户面向层):

1. **状态机**: `activateProactive()` / `deactivateProactive()` / `pauseProactive()` / `resumeProactive()` **完全缺失**;CCB `src/proactive/index.ts:37-135` 有完整 9 个公共 API;
2. **`<tick>` 注入**: `useProactive.ts:83` 构造 `<tick>HH:MM:SS</tick>` 推入 `QueuedCommand` 队列,ClawCodex **无**对应 tick 注入路径;
3. **REPL 集成**: `PromptInputFooterLeftSide` 渲染 countdown 倒计时(`getNextTickAt()`),ClawCodex **无**;
4. **API 错误防护**: CCB `setContextBlocked(true)` 防止 `tick → error → tick` 失控循环,**无**;
5. **`<system-reminder>` 元消息**: CCB `/proactive` 命令 emit `metaMessages` 含 `<system-reminder>` 提示文本,**无**;
6. **`SleepTool`**: CCB 在 `packages/builtin-tools/src/tools/SleepTool/SleepTool.ts`,ClawCodex `clawcodex_ext/tool_system/tools/bash/sleep_detection.py`(31 行)只是**检测器**(`sleep N ≥ 2s` 静态阻塞),不是真正的 SleepTool;
7. **`getProactiveSection()`**: CCB 系统提示拼装(~55 行),按 `terminalFocus` 调节自主程度,ClawCodex **无**;
8. **`automation_state` 元数据**: CCB 通过 F-82 RCS 暴露 `standby` / `sleeping` / `active` 状态,ClawCodex **无**;

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P89-A | `ProactiveController` 状态机(inactive/active/paused/blocked + listeners) | 📋 | 3 天 |
| P89-B | `TickEmitter` 驱动 `<tick>` 提示注入,默认 30s,复用 `kairos.TickScheduler` | 📋 | 3-4 天 |
| P89-C | `SleepTool` 真实实现(替换现有 `sleep_detection.py` 的阻塞检测 + 增加 sleep→resume 唤醒队列) | 📋 | 3-4 天 |
| P89-D | `/proactive` 斜杠命令(注册 `PROACTIVE_COMMAND`,emit `<system-reminder>`) | 📋 | 1 天 |
| P89-E | REPL 集成:footer 倒计时 + standby/sleeping 状态渲染 + Ctrl+B 切换 | 📋 | 2-3 天 |
| P89-F | API 错误防护:`setContextBlocked(true)` 防止 tick 失控循环 | 📋 | 1-2 天 |
| P89-G | `getProactiveSection()` 系统提示拼装(按 `terminalFocus` 调节) | 📋 | 2 天 |
| P89-H | `automation_state` 元数据暴露到 `extensions/remote_api/`(F-82 协同) | 📋 | 1-2 天 |
| P89-I | 单元测试 + E2E + 稳定性门禁 Stage 10 | 📋 | 2 天 |

**估算总工时**: 18-23 天(单人)

### 1.4 架构设计

#### 1.4.1 进程模型

```
┌────────────────────────────────────────────────────────────────┐
│ clawcodex REPL process                                         │
│                                                                │
│  ┌──────────────────┐                                          │
│  │  /proactive 命令 │  activateProactive("slash_command")      │
│  └──────────────────┘            │                             │
│         │                        ▼                             │
│         │              ┌──────────────────┐                    │
│         │              │ ProactiveController│                   │
│         │              │  (state machine) │                    │
│         │              └──────────────────┘                    │
│         │                  ▲          ▲                        │
│         │   notify()       │          │                        │
│         │                  │          │                        │
│  ┌──────▼─────────┐  ┌─────┴───┐  ┌───┴──────────┐            │
│  │ REPL Footer    │  │TickEmit │  │SleepTool     │            │
│  │ (countdown     │  │ter      │  │(sleep→resume)│            │
│  │  渲染)         │  │(30s循环)│  │              │            │
│  └────────────────┘  └─────────┘  └──────────────┘            │
│         │                  │                                    │
│         │                  │ tick 注入                          │
│         │                  ▼                                    │
│         │       <tick>14:23:45</tick>                          │
│         │                  │                                    │
│         │                  ▼                                    │
│         │       ┌──────────────────┐                          │
│         │       │ QueryEngine /    │                          │
│         │       │ REPL prompt queue│                          │
│         │       └──────────────────┘                          │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────────┐  automation_state                        │
│  │ extensions/      │  ───────────────►                         │
│  │ remote_api/      │  (F-82 协同)                             │
│  └──────────────────┘                                          │
└────────────────────────────────────────────────────────────────┘
```

#### 1.4.2 包结构(全部解耦,不动 `src/`)

```
clawcodex_ext/services/proactive/             ← 全新 Layer 1 子模块
├── __init__.py                               # 公共导出
├── controller.py                             # P89-A: ProactiveController 状态机
├── tick_emitter.py                          # P89-B: TickEmitter(复用 kairos.TickScheduler)
├── state.py                                  # 状态 dataclass(AutomationState 等)
└── constants.py                              # TICK_INTERVAL_MS / TICK_TAG / contextBlocked 默认值

clawcodex_ext/services/proactive/prompts.py   # P89-G: getProactiveSection() 系统提示拼装

clawcodex_ext/tool_system/tools/sleep.py      # P89-C: SleepTool(替换 bash/sleep_detection.py 概念)
clawcodex_ext/repl/proactive_integration.py   # P89-E: REPL 状态栏 + keybinding 注入
clawcodex_ext/command_system/builtins.py      # P89-D: 注册 PROACTIVE_COMMAND

extensions/capabilities/automation_state_protocol.py  # P89-H: Protocol 接口(避免 Remote API 直接依赖)

# F-82 侧(已存在的 extensions/remote_api/)只需添加一个字段:
extensions/remote_api/state_reporter.py       # P89-H: ProactiveAutomationStateReporter(可选)
```

#### 1.4.3 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| 状态机 | `clawcodex_ext/services/proactive/controller.py`(新) | 镜像 CCB `src/proactive/index.ts`,封装为 Python class |
| Tick 调度 | 复用 `clawcodex_ext/services/kairos/scheduler.py::TickScheduler` | 已有 drift-free + jitter + pause/resume,直接 `subscribe()` |
| `<tick>` 注入 | 新建 `TickEmitter` 订阅 TickScheduler,推 prompt 到 REPL 队列 | 不改 QueryEngine 入口 |
| SleepTool | 新建 `clawcodex_ext/tool_system/tools/sleep.py` | 现有 `bash/sleep_detection.py` 是检测器,不是工具 |
| `/proactive` 命令 | `PROACTIVE_COMMAND` 注册到 `clawcodex_ext/command_system/builtins.py` | 与 F-88 Monitor 同样模式 |
| REPL footer | `clawcodex_ext/repl/proactive_integration.py` 猴补丁 footer 组件 | 不改 `src/repl/` |
| API 错误防护 | `ProactiveController.set_context_blocked()` 在 query error handler 中调用 | 不改 `src/query.py` |
| `getProactiveSection()` | 新建 `prompts.py` 模块,被 `src/context_system/builder.py` 通过 `clawcodex_ext.hook` 注册 | 模式 C / hook |
| `automation_state` 元数据 | `extensions/capabilities/automation_state_protocol.py` 定义 Protocol,`extensions/remote_api/` 实现 consumer | Layer 2 → Layer 1 解耦 |
| Feature Flag | F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `PROACTIVE` / `KAIROS` | 复用 F-68 |

### 1.5 核心数据模型

```python
# clawcodex_ext/services/proactive/constants.py

from __future__ import annotations

# 镜像 CCB src/proactive/useProactive.ts:25 — prompt cache TTL ~5min,
# 30s 留足够缓冲保持 cache warm。
TICK_INTERVAL_MS: int = 30_000

# 镜像 CCB src/constants/xml.js:TICK_TAG — <tick>HH:MM:SS</tick>
TICK_TAG: str = "tick"

# API 错误防护窗口:错误发生后 60s 内不重新生成 tick,避免 tick → error → tick 循环
CONTEXT_BLOCKED_TTL_SEC: int = 60

# 默认 jitter 比例(对齐 kairos TickConfig.jitter_fraction 默认 0.0)
DEFAULT_JITTER_FRACTION: float = 0.05  # 5% — 避免多 cli 实例 tick 完全同步
```

```python
# clawcodex_ext/services/proactive/state.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AutomationPhase = Literal["inactive", "active", "paused", "sleeping", "blocked"]

@dataclass(frozen=True)
class AutomationState:
    """单一可信源,被 REPL footer + Remote API 同时消费。"""
    phase: AutomationPhase
    next_tick_at: float | None = None           # epoch ms,None 表示无下一 tick
    activation_source: str | None = None       # 'slash_command' / 'cli_flag' / 'auto_resume'
    last_sleep_until: float | None = None      # epoch ms,SleepTool 设置
    tick_count: int = 0                         # 自当前 session 启动后的 tick 数
    blocked_until: float | None = None          # epoch ms,API 错误防护窗口

    @property
    def is_active(self) -> bool:
        return self.phase in ("active", "sleeping")

    @property
    def is_blocked(self) -> bool:
        return self.phase == "blocked"
```

### 1.6 核心接口

#### 1.6.1 ProactiveController(`clawcodex_ext/services/proactive/controller.py`)

镜像 CCB `src/proactive/index.ts` 的 9 个公共 API:

```python
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Literal

from .state import AutomationState, AutomationPhase

logger = logging.getLogger(__name__)

StateListener = Callable[[AutomationState], None]


class ProactiveController:
    """Tick 驱动的自主 agent 状态机。

    状态转换:
        inactive → active → (paused → active → sleeping → active) → inactive
                        ↘ blocked (auto-clear after CONTEXT_BLOCKED_TTL_SEC)

    镜像 CCB src/proactive/index.ts:15-135。线程安全(RLock)。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = AutomationState(phase="inactive")
        self._listeners: list[StateListener] = []

    # ---- 状态查询(对齐 CCB src/proactive/index.ts:37-39, 60-61) ----

    def is_active(self) -> bool:
        """对齐 CCB isProactiveActive()。"""
        with self._lock:
            return self._state.is_active

    def is_paused(self) -> bool:
        """对齐 CCB isProactivePaused()。"""
        with self._lock:
            return self._state.phase == "paused"

    def is_context_blocked(self) -> bool:
        """对齐 CCB isContextBlocked()。"""
        with self._lock:
            if self._state.phase != "blocked":
                return False
            # 自动解除窗口
            if (
                self._state.blocked_until is not None
                and time.time() * 1000 >= self._state.blocked_until
            ):
                self._set_phase("active")
                return False
            return True

    def should_tick(self) -> bool:
        """对齐 CCB shouldTick():active && !paused && !blocked。"""
        with self._lock:
            return (
                self._state.phase == "active"
                and not self._state.is_blocked
            )

    # ---- 状态变更(对齐 CCB activateProactive/deactivateProactive/pauseProactive/resumeProactive) ----

    def activate(self, source: str = "unknown") -> None:
        """对齐 CCB activateProactive(source?: string)。"""
        with self._lock:
            if self._state.phase != "inactive":
                return
            self._state = AutomationState(
                phase="active",
                activation_source=source,
            )
            self._notify()

    def deactivate(self) -> None:
        """对齐 CCB deactivateProactive()。"""
        with self._lock:
            self._state = AutomationState(phase="inactive")
            self._notify()

    def pause(self) -> None:
        """对齐 CCB pauseProactive()。"""
        with self._lock:
            if self._state.phase != "active":
                return
            self._state = AutomationState(
                phase="paused",
                activation_source=self._state.activation_source,
                tick_count=self._state.tick_count,
            )
            self._notify()

    def resume(self) -> None:
        """对齐 CCB resumeProactive()。"""
        with self._lock:
            if self._state.phase != "paused":
                return
            self._state = AutomationState(
                phase="active",
                activation_source=self._state.activation_source,
                tick_count=self._state.tick_count,
            )
            self._notify()

    def set_context_blocked(self, blocked: bool) -> None:
        """对齐 CCB setContextBlocked(blocked: boolean)。

        API 错误时由 query.py 错误钩子调用,防止 tick → error → tick 失控。
        """
        with self._lock:
            if blocked:
                self._state = AutomationState(
                    phase="blocked",
                    blocked_until=time.time() * 1000 + 60_000,
                    tick_count=self._state.tick_count,
                )
            elif self._state.phase == "blocked":
                self._state = AutomationState(
                    phase="active",
                    activation_source=self._state.activation_source,
                    tick_count=self._state.tick_count,
                )
            self._notify()

    def set_next_tick_at(self, ts_ms: float | None) -> None:
        """对齐 CCB setNextTickAt(ts: number | null)。"""
        with self._lock:
            self._state = AutomationState(
                phase=self._state.phase,
                next_tick_at=ts_ms,
                activation_source=self._state.activation_source,
                last_sleep_until=self._state.last_sleep_until,
                tick_count=self._state.tick_count,
                blocked_until=self._state.blocked_until,
            )
            self._notify()

    # ---- SleepTool 协同 ----

    def enter_sleep(self, until_ms: float) -> None:
        """SleepTool 调用,设置 sleeping 阶段到 until_ms。"""
        with self._lock:
            self._state = AutomationState(
                phase="sleeping",
                last_sleep_until=until_ms,
                activation_source=self._state.activation_source,
                tick_count=self._state.tick_count,
            )
            self._notify()

    def wake_from_sleep(self) -> None:
        """sleep 到期后由 TickEmitter 回调,转回 active。"""
        with self._lock:
            if self._state.phase != "sleeping":
                return
            self._state = AutomationState(
                phase="active",
                activation_source=self._state.activation_source,
                tick_count=self._state.tick_count,
            )
            self._notify()

    def increment_tick_count(self) -> int:
        """Tick 触发后累加计数。返回新计数。"""
        with self._lock:
            self._state = AutomationState(
                phase=self._state.phase,
                next_tick_at=self._state.next_tick_at,
                activation_source=self._state.activation_source,
                last_sleep_until=self._state.last_sleep_until,
                tick_count=self._state.tick_count + 1,
                blocked_until=self._state.blocked_until,
            )
            self._notify()
            return self._state.tick_count

    # ---- Listener(对齐 CCB subscribeToProactiveChanges) ----

    def subscribe(self, listener: StateListener) -> Callable[[], None]:
        """注册状态变化监听器,返回 unsubscribe 函数。"""
        with self._lock:
            self._listeners.append(listener)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return _unsubscribe

    @property
    def state(self) -> AutomationState:
        """当前状态(只读快照)。"""
        with self._lock:
            return self._state

    # ---- 内部 ----

    def _set_phase(self, phase: AutomationPhase) -> None:
        with self._lock:
            self._state = AutomationState(
                phase=phase,
                activation_source=self._state.activation_source,
                tick_count=self._state.tick_count,
            )
        self._notify()

    def _notify(self) -> None:
        # 在锁外回调,避免死锁
        with self._lock:
            listeners = list(self._listeners)
            snapshot = self._state
        for cb in listeners:
            try:
                cb(snapshot)
            except Exception:
                logger.exception("proactive state listener raised")


# 全局单例(对齐 CCB src/proactive/index.ts 的 module-level state)
_default_controller: ProactiveController | None = None


def get_default_controller() -> ProactiveController:
    global _default_controller
    if _default_controller is None:
        _default_controller = ProactiveController()
    return _default_controller
```

#### 1.6.2 TickEmitter(`clawcodex_ext/services/proactive/tick_emitter.py`)

```python
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Callable, Awaitable

from clawcodex_ext.services.kairos.scheduler import TickScheduler
from clawcodex_ext.services.kairos.models import TickConfig, TickEvent

from .constants import TICK_INTERVAL_MS, TICK_TAG, DEFAULT_JITTER_FRACTION
from .controller import ProactiveController, get_default_controller

logger = logging.getLogger(__name__)

TickHandler = Callable[[str], Awaitable[None]]
"""接受 tick 文本(如 '14:23:45'),异步推送到 REPL queue。"""


class TickEmitter:
    """驱动 <tick>HH:MM:SS</tick> 提示注入。

    镜像 CCB src/proactive/useProactive.ts:
      - 默认 30s 间隔(低于 prompt cache TTL)
      - tick 文本通过 subscriber 推送到 prompt queue
      - 跳过条件:isLoading / isInPlanMode / hasActiveLocalJsxUI / hasQueuedCommands
    """

    def __init__(
        self,
        controller: ProactiveController | None = None,
        tick_handler: TickHandler | None = None,
    ) -> None:
        self._ctrl = controller or get_default_controller()
        self._tick_handler = tick_handler
        self._scheduler: TickScheduler | None = None
        # 跳过条件由外部注入(REPL 状态)
        self._should_skip: Callable[[], bool] = lambda: False

    def bind_skip_check(self, should_skip: Callable[[], bool]) -> None:
        """REPL 注入:返回 True 时跳过本次 tick(对齐 CCB useProactive.ts:67-78)。"""
        self._should_skip = should_skip

    async def start(self) -> None:
        """启动 TickScheduler(默认 30s 间隔 + 5% jitter)。"""
        if not self._ctrl.is_active():
            return
        config = TickConfig(
            id="proactive-main",
            interval_seconds=TICK_INTERVAL_MS / 1000.0,
            enabled=True,
            jitter_fraction=DEFAULT_JITTER_FRACTION,
            name="Proactive Tick",
        )
        self._scheduler = TickScheduler(config)
        self._scheduler.subscribe(self._on_tick_event)
        # 调度第一 tick
        self._ctrl.set_next_tick_at(time.time() * 1000 + TICK_INTERVAL_MS)

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.stop()
            self._scheduler = None

    def _on_tick_event(self, event: TickEvent) -> None:
        """TickScheduler 回调(同步) → 异步注入。"""
        if not self._ctrl.should_tick():
            # 条件不满足,重新调度(对齐 CCB useProactive.ts:54-57)
            self._reschedule()
            return
        if self._should_skip():
            self._reschedule()
            return

        # 构造 <tick>HH:MM:SS</tick>(对齐 CCB useProactive.ts:83)
        now_str = datetime.now().strftime("%H:%M:%S")
        tick_text = f"<{TICK_TAG}>{now_str}</{TICK_TAG}>"

        if self._tick_handler is not None:
            asyncio.create_task(self._dispatch_tick(tick_text))
        else:
            logger.debug("TickEmitter fired (no handler bound): %s", tick_text)

        self._ctrl.increment_tick_count()
        self._reschedule()

    async def _dispatch_tick(self, tick_text: str) -> None:
        try:
            await self._tick_handler(tick_text)
        except Exception:
            logger.exception("Tick handler raised; setting context blocked")
            self._ctrl.set_context_blocked(True)

    def _reschedule(self) -> None:
        next_ts = time.time() * 1000 + TICK_INTERVAL_MS
        self._ctrl.set_next_tick_at(next_ts)
```

#### 1.6.3 SleepTool(`clawcodex_ext/tool_system/tools/sleep.py`)

替换现有 `clawcodex_ext/tool_system/tools/bash/sleep_detection.py`(31 行,仅检测器)。

```python
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.tool_system.base import Tool, ToolContext, ToolResult

from clawcodex_ext.services.proactive.controller import get_default_controller
from clawcodex_ext.services.proactive.constants import (
    TICK_INTERVAL_MS, CONTEXT_BLOCKED_TTL_SEC,
)

logger = logging.getLogger(__name__)

DEFAULT_SLEEP_SEC = 5 * 60  # 5 minutes(对齐 CCB SleepTool 默认)


class SleepTool(Tool):
    """SleepTool — 让模型控制自己的 wake-up cadence。

    与 bash `sleep N` 区别:
      - 不 spawn 进程;仅记录下次唤醒时间
      - 立即返回(不阻塞 REPL)
      - 与 ProactiveController 双向联动:
          * enter_sleep() 设置 phase='sleeping'
          * 到期后由 TickEmitter 调 wake_from_sleep()
    """

    name: str = "Sleep"
    description: str = (
        "Pause autonomous ticks for the given number of seconds. "
        "Returns immediately; the model can continue with other work "
        "or end its turn."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 24 * 60 * 60,
                "description": "Seconds to sleep (default 300)",
            },
        },
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        seconds = params.get("seconds", DEFAULT_SLEEP_SEC)
        ctrl = get_default_controller()
        if not ctrl.is_active():
            return ToolResult(
                success=True,
                data={"message": "Proactive mode is inactive; sleep is a no-op"},
            )

        wake_at_ms = time.time() * 1000 + seconds * 1000
        ctrl.enter_sleep(wake_at_ms)

        # 调度唤醒(独立 task,不阻塞 tool return)
        async def _wakeup() -> None:
            await asyncio.sleep(seconds)
            ctrl.wake_from_sleep()

        asyncio.create_task(_wakeup())

        return ToolResult(
            success=True,
            data={
                "slept_seconds": seconds,
                "wake_at_ms": wake_at_ms,
                "message": f"Sleeping for {seconds}s; will resume at {time.strftime('%H:%M:%S', time.localtime(wake_at_ms / 1000))}",
            },
        )
```

#### 1.6.4 getProactiveSection(`clawcodex_ext/services/proactive/prompts.py`)

```python
from __future__ import annotations

from .controller import get_default_controller
from .constants import TICK_TAG

# 镜像 CCB src/proactive/prompts.ts:getProactiveSection()
# (~55 行,按 terminalFocus 调节自主程度)
# terminalFocus 三档(对齐 CCB proactive.ts:7-8 + prompts.ts:25):
#   - "full"    : 全自主 — tick 触发后 Agent 可自行调用工具 / 启动子任务 / 调用 SendMessage
#   - "medium"  : 半自主 — Agent 可读 / 分析,但写操作前必须经用户授权
#   - "minimal" : 仅观察 — Agent 仅产出 1 句状态报告,不主动调用工具
#   - "off"     : 不注入(get_proactive_section 返回 None)

# 三档模板共享同一个 proactive_mode 包裹,但内文按 focus 收缩可执行动作清单
_PROACTIVE_SECTION_FULL = """\
<proactive_mode focus="full">
You are in PROACTIVE mode (full autonomy). You will receive periodic <{tag}>HH:MM:SS</{tag}> prompts.

On each tick, you MAY:
  1. Do useful work related to the active goal / pending tasks
  2. Spawn sub-agents via SendMessage for parallelizable work
  3. Call the Sleep tool with `seconds` to pause ticks (e.g. when idle)
  4. Briefly acknowledge if there is truly nothing to do (1 sentence)

Do NOT:
  - Output "still waiting" / "no new tasks" repeatedly without action
  - Spawn blocking shell `sleep N` (use the Sleep tool instead)
  - Continue ticks after the user pauses proactive mode

Current tick count: {tick_count}
Next tick at: {next_tick_at_str}
Phase: {phase}
</proactive_mode>
"""

_PROACTIVE_SECTION_MEDIUM = """\
<proactive_mode focus="medium">
You are in PROACTIVE mode (medium autonomy, write tools gated). You will receive periodic <{tag}>HH:MM:SS</{tag}> prompts.

On each tick, you MAY:
  1. Read-only inspection (Glob / Grep / Read / WebFetch)
  2. Plan / propose the next action in plain text — wait for user confirmation before executing writes
  3. Call the Sleep tool with `seconds` to pause ticks (e.g. when idle)
  4. Briefly acknowledge if there is truly nothing to do (1 sentence)

Do NOT:
  - Call write tools (Edit / Write / Bash with side effects) without prior user confirmation
  - Output "still waiting" / "no new tasks" repeatedly without action
  - Spawn blocking shell `sleep N` (use the Sleep tool instead)

Current tick count: {tick_count}
Next tick at: {next_tick_at_str}
Phase: {phase}
</proactive_mode>
"""

_PROACTIVE_SECTION_MINIMAL = """\
<proactive_mode focus="minimal">
You are in PROACTIVE mode (observation only). You will receive periodic <{tag}>HH:MM:SS</{tag}> prompts.

On each tick, you MAY:
  1. Output ONE short sentence describing the current observation / status
  2. Call the Sleep tool with `seconds` to defer the next tick

Do NOT:
  - Call any tool beyond Sleep
  - Output multi-paragraph reports or analysis

Current tick count: {tick_count}
Next tick at: {next_tick_at_str}
Phase: {phase}
</proactive_mode>
"""


def get_proactive_section(terminal_focus: Literal["full", "medium", "minimal", "off"] = "medium") -> str | None:
    """返回拼装好的 proactive section 文本,或 None(若未启用或 focus='off')。

    对齐 CCB src/proactive/prompts.ts:getProactiveSection()。
    terminal_focus 调节自主程度:
      - "full"    : 全自主(可写 + 派发子 agent)
      - "medium"  : 半自主(读 OK,写需用户确认) ← 默认
      - "minimal" : 仅观察(只输出 1 句状态)
      - "off"     : 不注入
    """
    if terminal_focus == "off":
        return None
    ctrl = get_default_controller()
    state = ctrl.state
    if not state.is_active:
        return None
    next_tick_str = (
        time.strftime("%H:%M:%S", time.localtime(state.next_tick_at / 1000))
        if state.next_tick_at is not None else "(not scheduled)"
    )
    template = {
        "full": _PROACTIVE_SECTION_FULL,
        "medium": _PROACTIVE_SECTION_MEDIUM,
        "minimal": _PROACTIVE_SECTION_MINIMAL,
    }[terminal_focus]
    return template.format(
        tag=TICK_TAG,
        tick_count=state.tick_count,
        next_tick_at_str=next_tick_str,
        phase=state.phase,
    )
```

#### 1.6.5 `/proactive` 命令(`clawcodex_ext/command_system/builtins.py`)

```python
PROACTIVE_COMMAND: LocalCommand = {
    "name": "proactive",
    "description": "Toggle proactive (autonomous tick-driven) mode",
    "is_enabled": lambda: (
        feature_gate.is_enabled("PROACTIVE")
        or feature_gate.is_enabled("KAIROS")
    ),
    "args": [],
    "handler": _handle_proactive_command,
}

def _handle_proactive_command(args: dict, ctx: CommandContext) -> CommandResult:
    """镜像 CCB src/commands/proactive.ts:34-53。"""
    from clawcodex_ext.services.proactive.controller import get_default_controller
    ctrl = get_default_controller()
    if ctrl.is_active():
        ctrl.deactivate()
        return LocalCommandResult("Proactive mode disabled", display="system")
    else:
        ctrl.activate("slash_command")
        return LocalCommandResult(
            "Proactive mode enabled — model will work autonomously between ticks",
            display="system",
            meta_messages=[
                "<system-reminder>\n"
                "Proactive mode is now enabled. You will receive periodic <tick> prompts. "
                "Do useful work on each tick, or call Sleep if there is nothing to do. "
                "Do not output 'still waiting' — either act or sleep.\n"
                "</system-reminder>"
            ],
        )
```

### 1.7 REPL 集成(`clawcodex_ext/repl/proactive_integration.py`)

```python
# 镜像 CCB src/components/PromptInputFooterLeftSide.tsx:倒计时渲染

def install_proactive_footer() -> None:
    """注入 footer 倒计时 + standby/sleeping 状态渲染。"""
    from clawcodex_ext.services.proactive.controller import get_default_controller
    from src.repl.footer_renderer import register_footer_widget

    ctrl = get_default_controller()

    def _render_proactive_widget() -> str | None:
        state = ctrl.state
        if state.phase == "inactive":
            return None  # 不显示 widget
        if state.phase == "blocked":
            return "[proactive: blocked ⛔]"
        if state.phase == "paused":
            return "[proactive: paused ⏸]"
        if state.phase == "sleeping":
            until = state.last_sleep_until
            remaining = max(0, int((until - time.time() * 1000) / 1000)) if until else 0
            return f"[proactive: sleeping 💤 {remaining}s]"
        # active
        next_tick = state.next_tick_at
        remaining = max(0, int((next_tick - time.time() * 1000) / 1000)) if next_tick else 0
        return f"[proactive: active ⚡ next {remaining}s]"

    register_footer_widget("proactive", _render_proactive_widget)
```

### 1.8 automation_state 元数据(F-82 协同,P89-H)

```python
# extensions/capabilities/automation_state_protocol.py

from typing import Protocol
from clawcodex_ext.services.proactive.state import AutomationState

class AutomationStateReporter(Protocol):
    """Layer 2 (Remote API) → Layer 1 (ProactiveController) 契约。"""

    def get_automation_state(self) -> AutomationState: ...
    def subscribe_state_change(self, callback) -> None: ...
```

`extensions/remote_api/state_reporter.py`(消费者)注册到 ProactiveController:

```python
def install_automation_state_reporter() -> None:
    from extensions.remote_api.session_store import set_session_metadata
    from clawcodex_ext.services.proactive.controller import get_default_controller

    ctrl = get_default_controller()

    def _on_state_change(state: AutomationState) -> None:
        set_session_metadata("automation_state", {
            "phase": state.phase,
            "tick_count": state.tick_count,
            "next_tick_at": state.next_tick_at,
        })

    ctrl.subscribe(_on_state_change)
```

### 1.9 依赖与协同

| 依赖 | 说明 |
|------|------|
| `clawcodex_ext/services/kairos/scheduler.py` | `TickScheduler` 复用 |
| `clawcodex_ext/services/kairos/models.py` | `TickConfig` / `TickEvent` |
| F-68 Feature Gate | `PROACTIVE` / `KAIROS` 注册 |
| F-82 Remote Control | `automation_state` 元数据暴露 |
| F-88 Monitor Tool | Monitor + Proactive 协同(Proactive tick 可触发 Monitor) |
| F-85 Pipe IPC | `automation_state` 可跨实例同步(可选,P2) |

| 协同 | 说明 |
|------|------|
| F-64 Voice Mode | Voice Mode 的 Push-to-Talk 可复用状态机(`active` ↔ `sleeping`) |
| F-71 Tool Gap | SleepTool 作为 builtin tool 注册到 tool_registry |
| F-118 动态任务分解 | Proactive tick 可触发 task planner |

### 1.10 测试策略

#### 1.10.1 单元测试

- `tests/services/proactive/test_controller.py`:
  - 状态转换(inactive ↔ active ↔ paused ↔ blocked ↔ sleeping)
  - listener 订阅 + notify
  - contextBlocked 自动解除窗口(60s)
  - RLock 死锁检测
- `tests/services/proactive/test_tick_emitter.py`:
  - TickScheduler subscribe/unsubscribe
  - tick_handler 调用 + 异常 → set_context_blocked(true)
  - should_skip 检查跳过
  - jitter 不漂移
- `tests/services/proactive/test_sleep_tool.py`:
  - enter_sleep + 异步 wakeup 完整流程
  - proactive 关闭时 sleep 为 no-op
- `tests/services/proactive/test_prompts.py`:
  - `get_proactive_section()` inactive 时返回 None
  - active 时返回完整模板,字段正确
- `tests/services/proactive/test_repl_footer.py`:
  - 5 种 phase 的 widget 渲染
  - inactive 不渲染

#### 1.10.2 集成测试(E2E)

- `tests/services/proactive/e2e_lifecycle.py`:
  1. 启动 REPL → `/proactive` 启用
  2. 等 35s,验证至少 1 次 `<tick>` 注入
  3. 模拟 API 错误,验证 contextBlocked + 60s 内不重新 tick
  4. `/proactive` 关闭,验证 tick 停止
- `tests/services/proactive/e2e_sleep.py`:
  1. 启用 proactive,等第一个 tick
  2. AI 调 SleepTool(seconds=3)
  3. 验证 3s 内 phase='sleeping',footer 显示 "sleeping 💤 3s"
  4. 3s 后 wake_from_sleep,phase='active'
- `tests/services/proactive/e2e_remote_api.py`(F-82 协同):
  1. 启用 proactive,调 RCS endpoint
  2. 验证返回 `automation_state` 含 phase + tick_count + next_tick_at

#### 1.10.3 稳定性门禁

- `tests/stability_gate/test_stage5_extensions.py` 增补 proactive 模块 import smoke test
- 新增 `tests/stability_gate/test_stage10_proactive.py`(轻量,只验证状态机 + listener,实际 TickScheduler 短间隔 1s)

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|----------|
| 2026-Q1 | KAIROS TickScheduler(244 行,继承 PeriodicDaemon) | `clawcodex_ext/services/kairos/scheduler.py` |
| 2026-Q1 | TickConfig / TickEvent / BriefSummarySnapshot / DailyLogEntry 数据模型(223 行) | `clawcodex_ext/services/kairos/models.py` |
| 2026-Q1 | BriefSummaryBuilder(95 行)+ DailyLog(94 行) | `clawcodex_ext/services/kairos/{brief,daily_log}.py` |
| 2026-Q1 | sleep_detection.py 检测器(31 行,F-89 替换) | `clawcodex_ext/tool_system/tools/bash/sleep_detection.py` |
| 2026-Q2 | bash `sleep N ≥ 2` 检测规则(用于阻止模型用 bash sleep 替代 SleepTool) | 同上 |
| 2026-06-30 | 详设文档 + 子特性分解 | `f-89-proactive.md`(本文) |
| 2026-06-30 | 缺口盘点纳入 [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵) | gap-analysis |

### 2.2 下一步计划

按子特性顺序(底层 → 上层):
1. P89-A `ProactiveController` 状态机(独立,可单测)
2. P89-G `getProactiveSection()` 系统提示拼装(依赖 A)
3. P89-I 单元测试(先 A + G,稳定基础)
4. P89-B `TickEmitter`(依赖 A + kairos TickScheduler)
5. P89-C `SleepTool`(依赖 A)
6. P89-F `set_context_blocked` 在 query error handler 中 hook
7. P89-D `/proactive` 命令 + `<system-reminder>` 元消息
8. P89-E REPL footer 倒计时 + Ctrl+B 切换
9. P89-H `automation_state` 元数据暴露到 `extensions/remote_api/`
10. P89-I E2E + Stage 10 门禁

## §3 验收标准

### 3.1 功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| V-1 | `/proactive` 启用后 ProactiveController.phase='active',emit `<system-reminder>` | 单元测试 |
| V-2 | `/proactive` 关闭后 phase='inactive',emit 'Proactive mode disabled' | 单元测试 |
| V-3 | TickEmitter 默认 30s 间隔 + 5% jitter | 单元测试 |
| V-4 | Tick 触发后 `<tick>HH:MM:SS</tick>` 文本注入到 REPL queue | 单元测试 |
| V-5 | `should_skip()` 返回 True 时跳过 tick + 重新调度 | 单元测试 |
| V-6 | SleepTool(seconds=N) 设置 phase='sleeping',N 秒后 wake_from_sleep | 单元测试 + E2E |
| V-7 | Proactive 关闭时 SleepTool 是 no-op | 单元测试 |
| V-8 | API 错误触发 `set_context_blocked(true)`,60s 内不重新 tick | 单元测试 + E2E |
| V-9 | 60s 后 context_blocked 自动解除,phase 回到 active | 单元测试(time_machine) |
| V-10 | REPL footer 5 种 phase 渲染:active ⚡ / paused ⏸ / sleeping 💤 / blocked ⛔ / inactive 隐藏 | 单元测试 |
| V-11 | `get_proactive_section()` 在 inactive 时返回 None | 单元测试 |
| V-12 | `automation_state` 通过 Protocol 暴露给 `extensions/remote_api/` | 集成测试(F-82 协同) |

### 3.2 非功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| N-1 | 状态机操作(<1ms)RLock 锁开销 < 100μs | 单元测试 + Stage 6 perf |
| N-2 | TickEmitter 内存占用 < 5MB(TickScheduler + listener) | 单元测试 |
| N-3 | 30s 间隔稳定性:连续 1000 tick drift < 1s | 单元测试(time_machine) |
| N-4 | listener 异常不影响主流程(已捕获) | 单元测试 |
| N-5 | 多 listener 通知顺序稳定(订阅顺序) | 单元测试 |
| N-6 | contextBlocked 60s 窗口准确(monotonic time,不受系统时钟漂移影响) | 单元测试 |
| N-7 | 单元测试覆盖率 ≥ 75% | `pytest --cov` |

### 3.3 集成验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| I-1 | 不修改 `src/` 任何业务模块(允许 facade 桩) | `git diff --stat src/` |
| I-2 | `python3 -m pytest tests/stability_gate/ -q` 全绿 | CI |
| I-3 | `extensions/orchestrator/` 测试不受影响 | CI |
| I-4 | 与 F-68 Feature Gate(`PROACTIVE` / `KAIROS`)集成,默认 off | 单元测试 |
| I-5 | KAIROS TickScheduler 现有 behavior 不变(回归测试) | CI |
| I-6 | F-82 Remote Control session metadata 含 `automation_state` 字段 | 集成测试 |
| I-7 | 与 F-88 Monitor Tool 协同:Proactive tick 可触发 Monitor | 集成测试(后续) |

## §4 风险与约束

| ID | 风险 | 缓解策略 |
|:--:|------|----------|
| R-1 | 多 listener 在 `_notify()` 中抛异常相互影响 | try/except 包每个 listener,记录日志但不中断 |
| R-2 | TickEmitter 与现有 kairos.TickScheduler 的 jitter 算法不同(CCB 默认 0,F-89 默认 5%) | 文档明确;5% 避免多实例 tick 完全同步 |
| R-3 | RLock 嵌套死锁(状态变更内再调 subscribe) | _notify() 在锁外回调(对齐 CCB `notify()`) |
| R-4 | SleepTool 异步 `_wakeup()` task 在 REPL 退出时未清理 | 注册 `asyncio.shutdown_default_executor()` 钩子取消所有 wakeup task |
| R-5 | `<tick>` prompt 被错误传给下游 API 时被误解 | XML tag 与 CCB 完全一致 + parser 显式 strip;E2E 测试覆盖 |
| R-6 | `automation_state` 通过 Protocol 暴露,Protocol 改动会引起 F-82 编译失败 | Protocol 字段稳定,新增字段只追加 |
| R-7 | contextBlocked 60s 窗口对短 API 错误不友好(用户等 60s) | 增加 manual unblock:`/proactive resume-blocked` 命令 |
| R-8 | Bash `sleep` 检测(`sleep_detection.py`)与新 SleepTool 概念冲突 | 保留 detection(用于阻止 bash 替代),同时注册新 SleepTool;两者并存,文档明确分工 |
| R-9 | Tick 文本 `<tick>HH:MM:SS</tick>` 中时间格式本地化不一致 | 统一 `datetime.now().strftime("%H:%M:%S")`(本地时区,24h) |
| R-10 | Proactive 在 Bridge / Remote 模式下的语义差异 | `bridgeSafe: true`(对齐 CCB proactive.ts:16),bridge 模式下默认禁用 |

## §5 与现有架构的对齐

- **三层架构**:
  - `clawcodex_ext/services/proactive/` 全新子模块(Layer 1)— 状态机 + tick 注入
  - `clawcodex_ext/tool_system/tools/sleep.py`(Layer 1)— SleepTool 内置工具
  - `extensions/capabilities/automation_state_protocol.py`(Layer 2 Protocol)— F-82 协同契约
  - `src/` 不动
- **复用优先**: `kairos.TickScheduler` / `TickConfig` / `TickEvent` 直接复用,零重复实现
- **状态机模式**: 镜像 CCB `src/proactive/index.ts` 的 9 个公共 API(`isActive/activate/deactivate/isPaused/pause/resume/setContextBlocked/isContextBlocked/setNextTickAt`)+ Python 化扩展(`enter_sleep/wake_from_sleep`)
- **注册模式**: `PROACTIVE_COMMAND` 注册到 `command_system`;`SleepTool` 注册到 `tool_registry`;listener 订阅到 `ProactiveController`
- **猴补丁**: `clawcodex_ext/repl/proactive_integration.py` 注入 footer widget(对齐 F-85/F-88 同样模式)
- **Protocol 接口**: `extensions/capabilities/automation_state_protocol.py` 定义 `AutomationStateReporter`,允许 F-82 Remote API 不依赖具体 ProactiveController 实现
- **Feature Flag**: F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `PROACTIVE` + `KAIROS`(对齐 CCB `feature('PROACTIVE') || feature('KAIROS')`)
- **稳定性门禁**: 复用 `tests/stability_gate/`,新增 Stage 10 proactive smoke test

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建(9 子特性,12 验收项,10 风险) | 派工 F-89 P0 缺口,对接 CCB PROACTIVE + KAIROS 双 flag |
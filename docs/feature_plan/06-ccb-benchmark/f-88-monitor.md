# F-88: Monitor 后台监控 + MonitorTool

> 状态: 🟡 后台执行原语已落地(`clawcodex_ext/tool_system/tools/bash/background.py`,292 行;`clawcodex_ext/agent/background_runner.py`,449 行);`MonitorTool` + `/monitor` 命令 + TUI 面板待补
> 章节: `docs/feature_plan/06-ccb-benchmark/f-88-monitor.md`
> 最后更新: 2026-06-30
> 缺口来源: [gap-analysis-2026q2.md §3.1](./gap-analysis-2026q2.md#f-88-monitor-后台监控--monitortool)

## §1 设计规划

### 1.1 目标

对标 CCB `MONITOR_TOOL` + `/monitor` 命令,补齐 ClawCodex 的后台监控能力,使 AI 和用户都能通过 `/monitor <cmd>` 或 `MonitorTool` 启动长驻 shell 任务(`tail -f` / `watch -n <sec> <cmd>` / 自定义轮询循环),后台进程独立于 REPL,输出实时写入日志文件,REPL 通过 Shift+↓ 展开 TUI 面板查看。

### 1.2 背景

**已完成基础设施**:

| 模块 | 行数 | 复用点 |
|------|------|--------|
| `clawcodex_ext/tool_system/tools/bash/background.py` | 292 | `spawn_background_bash` + `read_background_output` + `stop_background_bash`(F-88 直接复用 spawn + stop,只新增 `kind='monitor'` 标签) |
| `clawcodex_ext/tasks_core.py` | (tasks_type discriminator) | `LocalShellTaskState` 类型已存在,只需扩展 `kind` 字段 |
| `clawcodex_ext/services/tail_follower.py` | 133 | 已有 JSONL tail-follow 逻辑,F-88 借鉴 polling 模式做通用文本 tail |
| `clawcodex_ext/agent/background_runner.py` | 449 | agent-loop 后台化(不同生命周期,F-88 不直接复用) |
| `clawcodex_ext/repl/background_escape.py` | (存在) | Ctrl+B 后台化(F-88 不冲突,各管各的) |
| `clawcodex_ext/command_system/builtins.py` | (存在) | 命名命令注册入口 |

**缺口**:

1. **命名命令族**: `/monitor <cmd>` 斜杠命令 **完全缺失**;
2. **AI 可调工具**: `MonitorTool`(内置工具,允许 AI 触发后台监控) **完全缺失**;
3. **`kind='monitor'` 标签**: `LocalShellTaskState` 当前无 `kind` 字段,无法区分普通 bash 后台任务 vs 监控任务;
4. **stall 看门狗豁免**: CCB `LocalShellTask.tsx:64` 对 `kind==='monitor'` 的任务跳过 stall watchdog(否则 `tail -f` 永远不退出,被误判 stall);ClawCodex 缺少对应豁免;
5. **Windows watch 兼容**: `watch -n <sec> <cmd>` 在 Windows 需转 PowerShell `while(1){cmd; Start-Sleep <sec>}` **未实现**;
6. **TUI 后台任务面板**: Shift+↓ 展开后台任务列表 + tail 输出 **未接入**;
7. **输出实时 tail**: TUI 面板需轮询 tail 文件,ClawCodex 缺通用文本 tail(现有 `tail_follower.py` 只解析 JSONL)。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P88-A | `LocalShellTaskState` 增加 `kind: Literal['shell', 'monitor']` 字段 | 📋 | 1 天 |
| P88-B | `MonitorController`(`clawcodex_ext/services/monitor/controller.py`),复用 `spawn_background_bash` + 加 `kind='monitor'` | 📋 | 2-3 天 |
| P88-C | `WatchCompat`(`watch_compat.py`),Windows `watch -n <sec> <cmd>` → PowerShell 循环 | 📋 | 1 天 |
| P88-D | `OutputBuffer` ring buffer + 通用文本 `TailFollower`(`text_tail.py`,与 JSONL 版解耦) | 📋 | 2 天 |
| P88-E | stall 看门狗豁免:hook `LocalShellTask` 状态变更时跳过 `kind='monitor'` | 📋 | 1 天 |
| P88-F | `/monitor <cmd>` 斜杠命令(`clawcodex_ext/command_system/builtins.py` 注册) | 📋 | 1-2 天 |
| P88-G | `MonitorTool`(`clawcodex_ext/tool_system/tools/monitor.py`),AI 可调,接受 `command` + `kind` + `interval_sec` | 📋 | 2-3 天 |
| P88-H | TUI 监控面板(`clawcodex_ext/tui/screens/monitor_panel.py`),Shift+↓ 展开 + 实时 tail | 📋 | 3-4 天 |

**估算总工时**: 12-15 天(单人)

### 1.4 架构设计

#### 1.4.1 进程模型

```
┌────────────────────────────────────────────────────────────────┐
│ clawcodex REPL process                                         │
│                                                                │
│  ┌──────────────────┐  spawn   ┌────────────────────────┐    │
│  │  REPL main loop  │──────────►│  bash -lc "cmd"        │    │
│  │                  │  Popen    │  (detached session)    │    │
│  └──────────────────┘           └────────────────────────┘    │
│         │                              │                       │
│         │ context.runtime_tasks        │ stdout/stderr         │
│         │ (LocalShellTaskState)        ▼                       │
│         │                    /tmp/clawcodex-bg/<id>.log        │
│         │                              │                       │
│         │                              ▼                       │
│         │                    TextTailFollower(poll 500ms)      │
│         ▼                              │                       │
│  ┌──────────────────┐                  │                       │
│  │ TUI Monitor Panel│◄─────────────────┘                       │
│  │ (Shift+↓)        │  tail last N bytes + auto-refresh      │
│  └──────────────────┘                                          │
└────────────────────────────────────────────────────────────────┘

                ↓ (AI call)

  ┌──────────────────────┐
  │ MonitorTool          │
  │ (built-in tool)      │
  │  command: str        │
  │  kind: 'shell'|'mon' │  ← 若 kind='monitor',自动应用
  │  interval_sec: int   │     watch -n 转换 + stall 豁免
  │  → returns task_id   │
  └──────────────────────┘
```

#### 1.4.2 包结构(全部解耦,不动 `src/`)

```
clawcodex_ext/services/monitor/             ← 全新 Layer 1 子模块
├── __init__.py                             # 公共导出
├── controller.py                           # P88-B: MonitorController 封装 spawn + kind 标签
├── watch_compat.py                         # P88-C: Windows PowerShell 循环转换
├── text_tail.py                            # P88-D: 通用文本 TailFollower(扩展现有 tail_follower.py)
└── stall_guard.py                          # P88-E: stall watchdog 豁免 hook

clawcodex_ext/tool_system/tools/monitor.py  # P88-G: MonitorTool(AI 可调)
clawcodex_ext/command_system/builtins.py    # P88-F: 注册 /monitor 命令(MONITOR_COMMAND)
clawcodex_ext/tui/screens/monitor_panel.py  # P88-H: Shift+↓ 监控面板
clawcodex_ext/repl/monitor_integration.py   # P88-H: REPL keybinding(Shift+↓) 猴补丁
```

#### 1.4.3 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| 后台执行底层 | 复用 `clawcodex_ext/tool_system/tools/bash/background.py::spawn_background_bash` | 已实现 Popen + 输出文件 + reaper;只需加 `kind` 标签 |
| `kind` 字段 | 扩展 `LocalShellTaskState`(Layer 1) | 镜像 CCB `kind: 'monitor'` 字段,不破坏现有 bash 路径 |
| Text tail | 新建 `text_tail.py`(不动现有 JSONL 版 `tail_follower.py`) | 单一职责 + JSONL 解析依赖不影响通用文本 |
| stall 豁免 | 注册 `stall_guard.py` hook 到 `LocalShellTask` 状态机 | 不改 `src/tool_system/tools/bash/background.py` 的 watchdog 实现 |
| `/monitor` 命令 | 在 `builtins.py` 注册 `MONITOR_COMMAND` | 沿用 `EXTENSION_COMMANDS` 模式,不修改 `src/command_system/builtins.py` |
| MonitorTool | 在 `clawcodex_ext/tool_system/tools/monitor.py` 定义 + `tool_registry.register()` | F-71 风格,Tool 工具统一入口 |
| TUI 面板 | 新建 `tui/screens/monitor_panel.py` | 与现有 model_picker/effort_picker 同目录风格一致 |
| Shift+↓ 绑定 | `clawcodex_ext/repl/monitor_integration.py` 猴补丁 `src/repl/` | 不改上游 REPL 入口 |

### 1.5 核心数据模型(扩展)

```python
# clawcodex_ext/tasks_core.py(扩展 LocalShellTaskState)

from typing import Literal

# 新增 kind discriminator(CCB LocalShellTask.tsx:82 一致)
TaskKind = Literal['shell', 'monitor']

@dataclass
class LocalShellTaskState:
    """现有字段保持不变,新增 kind 字段。"""
    id: str
    type: str
    status: str
    description: str
    start_time: float
    output_file: str
    command: str
    cwd: str
    pid: int
    output_path: str
    proc: subprocess.Popen | None
    handle: Any | None

    # F-88 新增字段
    kind: TaskKind = 'shell'           # 'shell' = 普通 bash 后台;'monitor' = 监控任务
    interval_sec: int | None = None    # 'monitor' 时记录 watch 间隔
    tail_buffer_size: int = 200_000    # TUI tail 缓存大小(可配置)
    auto_refresh: bool = False         # TUI 是否自动刷新
```

### 1.6 核心接口

#### 1.6.1 MonitorController(`clawcodex_ext/services/monitor/controller.py`)

```python
from typing import Literal
from pathlib import Path

class MonitorController:
    """高层封装:复用 spawn_background_bash,只多一步 kind='monitor' 标签 + watch 兼容转换。"""

    def __init__(self, context: ToolContext) -> None:
        self._ctx = context

    def start(
        self,
        command: str,
        *,
        kind: Literal['shell', 'monitor'] = 'monitor',
        interval_sec: int | None = None,
        cwd: Path | None = None,
        description: str | None = None,
    ) -> MonitorStartResult:
        """启动后台监控任务。

        步骤:
          1. 若 kind='monitor' 且当前平台 Windows:
             通过 WatchCompat 将 `watch -n <sec> <cmd>` 转为 PowerShell 循环
          2. 调用 spawn_background_bash(复用现有逻辑)
          3. 将返回的 LocalShellTaskState.kind 设为 'monitor' / interval_sec 填入
          4. 返回 task_id + output_path
        """

    def stop(self, task_id: str) -> bool:
        """复用 stop_background_bash(stop 逻辑与 kind 无关)。"""

    def list_active(self) -> list[LocalShellTaskState]:
        """列出所有 kind='monitor' 且 status='running' 的任务。"""

    def tail(
        self,
        task_id: str,
        *,
        max_bytes: int = 200_000,
        follow: bool = False,
    ) -> TextTailReader:
        """返回 tail reader(follow=True 时持续 yield 新行)。"""
```

#### 1.6.2 WatchCompat(`clawcodex_ext/services/monitor/watch_compat.py`)

```python
import platform
import re

_WATCH_PATTERN = re.compile(r'^watch\s+-n\s+(\d+)\s+(.+)$')

def normalize_watch_command(command: str) -> str:
    """跨平台 watch 命令规范化。

    Windows (process.platform === 'win32' 等价):
      `watch -n <sec> <cmd>` → `powershell -c "while(1){<cmd>; Start-Sleep <sec>}"`
      (镜像 CCB monitor.ts:51-58)

    POSIX / macOS:
      原样返回。
    """
    if platform.system() != 'Windows':
        return command

    m = _WATCH_PATTERN.match(command.strip())
    if not m:
        return command
    interval, inner_cmd = m.group(1), m.group(2)
    return f'powershell -c "while(1){{{inner_cmd}; Start-Sleep {interval}}}"'
```

#### 1.6.3 TextTailFollower(`clawcodex_ext/services/monitor/text_tail.py`)

通用文本 tail(非 JSONL)。借鉴 `tail_follower.py` 的 poll-based 模式,但不解析 JSON:

```python
import asyncio
import os
from collections import deque
from pathlib import Path

class TextTailFollower:
    """通用文本 tail — 复用 tail_follower 的 polling 模式,不做 JSON 解析。"""

    _POLL_INTERVAL = 0.5

    def __init__(self, path: str | Path, *, ring_size: int = 200_000) -> None:
        self._path = str(path)
        self._offset: int = 0
        self._ring = deque(maxlen=ring_size)
        self._stopping = False

    async def start(self, from_offset: int = 0) -> None: ...
    async def stop(self) -> None: ...
    async def read_chunk(self) -> str: ...
        """返回自上次读取以来的新文本(自动追加到 ring buffer)。"""

    @property
    def current_tail(self) -> str:
        """返回 ring buffer 当前内容(最多 ring_size 字节)。"""
```

#### 1.6.4 StallGuard(`clawcodex_ext/services/monitor/stall_guard.py`)

```python
class StallWatchdogExemptor:
    """Stall watchdog 豁免 hook — 对 kind='monitor' 任务跳过 stall 检测。

    对齐 CCB LocalShellTask.tsx:64
      if (kind === 'monitor') return () => {};
    """

    @classmethod
    def should_skip_stall_check(cls, state: LocalShellTaskState) -> bool:
        return getattr(state, 'kind', 'shell') == 'monitor'
```

#### 1.6.5 MonitorTool(`clawcodex_ext/tool_system/tools/monitor.py`)

```python
from src.tool_system.base import Tool, ToolContext, ToolResult

class MonitorTool(Tool):
    """AI-callable monitor tool — 启动后台监控任务并返回 task_id。

    与 BashTool 的 run_in_background 区别:
      - 默认 kind='monitor'(长驻任务,stall watchdog 豁免)
      - 可选 interval_sec(自动转 watch -n)
      - 输出写到 /tmp/clawcodex-bg/<id>.log,可被 TUI panel tail
    """

    name: str = "Monitor"
    description: str = (
        "Start a long-running background monitor task. "
        "Returns the task_id which can be used with TaskOutput / TaskStop. "
        "Output is streamed to a log file viewable via Shift+Down."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run in background"},
            "interval_sec": {"type": "integer", "description": "Optional watch interval (auto-converts to PowerShell loop on Windows)"},
            "cwd": {"type": "string", "description": "Working directory"},
            "description": {"type": "string", "description": "Human-readable label for the monitor"},
        },
        "required": ["command"],
    }

    async def execute(self, params: dict, context: ToolContext) -> ToolResult:
        from clawcodex_ext.services.monitor.controller import MonitorController
        ctrl = MonitorController(context)
        result = ctrl.start(
            command=params["command"],
            kind='monitor',
            interval_sec=params.get("interval_sec"),
            cwd=Path(params["cwd"]) if params.get("cwd") else None,
            description=params.get("description"),
        )
        return ToolResult(
            success=True,
            data={
                "task_id": result.task_id,
                "output_path": str(result.output_path),
                "kind": "monitor",
                "message": (
                    f"Monitor started (task_id={result.task_id}). "
                    f"Output: {result.output_path}. "
                    f"Use TaskOutput / TaskStop to interact; Shift+Down to view in TUI."
                ),
            },
        )
```

### 1.7 命令族

| 命令 | 描述 | CCB 等价 |
|------|------|---------|
| `/monitor <cmd>` | 启动后台监控任务,显示 task_id + 输出路径 | ✅ |
| `/monitor list` | 列出所有活动监控任务 | (扩展,CCB 仅单任务) |
| `/monitor stop <task_id>` | 停止指定监控任务 | (扩展) |
| `/monitor tail <task_id>` | 立即 tail 输出到 REPL | (扩展) |

```python
# clawcodex_ext/command_system/builtins.py(MONITOR_COMMAND)

from clawcodex_ext.command_system.types import LocalCommand

MONITOR_COMMAND: LocalCommand = {
    "name": "monitor",
    "description": "Start a background monitor task (Shift+Down to view)",
    "is_enabled": lambda: feature_gate.is_enabled("MONITOR_TOOL"),
    "args": [
        {"name": "action", "required": False, "default": "start"},
        {"name": "command", "required": False, "remainder": True},
    ],
    "handler": _handle_monitor_command,
}

def _handle_monitor_command(args: dict, ctx: CommandContext) -> CommandResult:
    """分发到 MonitorController.start / list / stop / tail。"""
    ...
```

### 1.8 TUI 集成(`clawcodex_ext/tui/screens/monitor_panel.py`)

```python
from textual.screen import ModalScreen
from textual.widgets import Static, RichLog
from textual.containers import Vertical

class MonitorPanel(ModalScreen):
    """Shift+↓ 展开的后台任务监控面板。

    布局:
      ┌─────────────────────────────────┐
      │ [1] tail -f /var/log/syslog     │ ← 任务列表(左)
      │ [2] watch -n 5 git status      │
      ├─────────────────────────────────┤
      │ Tail of [1]:                    │ ← 实时 tail 输出(右)
      │ 2026-06-30 10:23:45 ...        │
      │ 2026-06-30 10:23:46 ...        │
      └─────────────────────────────────┘

      快捷键:
        ↑/↓     切换任务
        d       删除(停止)
        r       手动刷新
        q/Esc   关闭面板
    """

    BINDINGS = [
        ("up", "prev_task", "Previous"),
        ("down", "next_task", "Next"),
        ("d", "delete_task", "Delete"),
        ("r", "refresh", "Refresh"),
        ("q,escape", "dismiss", "Close"),
    ]

    def __init__(self, monitor_controller: MonitorController) -> None:
        super().__init__()
        self._ctrl = monitor_controller
        self._tasks: list[LocalShellTaskState] = []
        self._selected_idx: int = 0
```

`Shift+↓` keybinding 注入(猴补丁 `src/repl/` 的 keymap):

```python
# clawcodex_ext/repl/monitor_integration.py

def install_monitor_panel_binding() -> None:
    """注入 Shift+Down → 打开 MonitorPanel。

    镜像 CCB monitor.ts:5 — 'Shift+Down to view' 提示。
    """
    from src.repl.keymap import get_repl_keymap
    keymap = get_repl_keymap()
    keymap.register("S-down", "monitor_panel.open", _open_monitor_panel)
```

### 1.9 依赖与协同

| 依赖 | 说明 |
|------|------|
| `clawcodex_ext/tool_system/tools/bash/background.py` | `spawn_background_bash` / `stop_background_bash` |
| `clawcodex_ext/tasks_core.py` | `LocalShellTaskState` 类型(扩展 `kind` 字段) |
| `clawcodex_ext/services/tail_follower.py` | 借鉴 polling 模式(不直接复用,JSONL-only) |
| `clawcodex_ext/feature_gate/registry.py` | 注册 `MONITOR_TOOL` feature flag(F-68) |
| `clawcodex_ext/tool_system/registry.py` | `tool_registry.register(MonitorTool)` |
| `clawcodex_ext/command_system/registry.py` | `command_registry.register(MONITOR_COMMAND)` |

| 协同 | 说明 |
|------|------|
| F-82 Remote Control | RCS 可通过 MonitorTool 在远端触发后台监控 |
| F-84 Daemon | Daemon Worker 可通过 MonitorTool 持续 tail 服务日志 |
| F-89 Proactive | Proactive Tick 可通过 MonitorTool 触发周期性监控 |
| F-85 Pipe IPC | Monitor task_id 可作为 pipe 消息体在多实例间共享 |

### 1.10 测试策略

#### 1.10.1 单元测试

- `tests/services/monitor/test_controller.py`:
  - start/stop/list/tail 完整生命周期
  - `kind='monitor'` 标签正确写入 LocalShellTaskState
  - `interval_sec` + Windows PowerShell 转换(用 monkeypatch 模拟 platform.system)
- `tests/services/monitor/test_watch_compat.py`:
  - Linux/macOS 平台原样返回
  - Windows 平台 `watch -n 5 git status` → `powershell -c "while(1){git status; Start-Sleep 5}"`
  - 非 `watch -n` 命令不变
- `tests/services/monitor/test_text_tail.py`:
  - ring buffer 滚动正确
  - 多行追加 + 文件截断恢复
- `tests/services/monitor/test_stall_guard.py`:
  - `kind='monitor'` → skip
  - `kind='shell'` → 不 skip(走原 watchdog)
- `tests/tool_system/test_monitor_tool.py`:
  - MonitorTool.execute 返回正确 task_id / output_path
  - 入参校验(command 必填,interval_sec 可选)

#### 1.10.2 集成测试(E2E)

- `tests/services/monitor/e2e_lifecycle.py`:
  1. 启动 `/monitor tail -f /tmp/some_log`
  2. 写新行到 /tmp/some_log
  3. 验证 TextTailFollower 读到新行
  4. `/monitor stop <task_id>`,验证进程消失
- `tests/services/monitor/e2e_watch.py`(Windows 跳过):
  1. `/monitor watch -n 1 "echo tick"` (Linux)
  2. 等 3 秒,验证输出文件含 ≥ 3 个 "tick"
  3. 验证 kind='monitor' + interval_sec=1

#### 1.10.3 稳定性门禁

- `tests/stability_gate/test_stage5_extensions.py` 增补 monitor 模块 import smoke test
- 新增 `tests/stability_gate/test_stage9_monitor.py`(轻量,只验证 MonitorController 构造 + 不启动实际 Popen)

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|----------|
| 2026-Q1 | BashTool background mode(292 行) | `clawcodex_ext/tool_system/tools/bash/background.py` |
| 2026-Q1 | LocalShellTaskState 类型 + TaskType discriminator | `clawcodex_ext/tasks_core.py` |
| 2026-Q1 | agent-loop 后台化(449 行,生命周期不同,不直接复用) | `clawcodex_ext/agent/background_runner.py` |
| 2026-Q1 | JSONL TailFollower(133 行,借鉴而非复用) | `clawcodex_ext/services/tail_follower.py` |
| 2026-Q2 | REPL Ctrl+B 后台化(独立链路) | `clawcodex_ext/repl/background_escape.py` |
| 2026-06-30 | 详设文档 + 子特性分解 | `f-88-monitor.md`(本文) |
| 2026-06-30 | 缺口盘点纳入 [gap-analysis-2026q2.md §3.1](./gap-analysis-2026q2.md#f-88-monitor-后台监控--monitortool) | gap-analysis |

### 2.2 下一步计划

按子特性顺序(底层 → 上层):
1. P88-A `LocalShellTaskState` 加 `kind` 字段
2. P88-D `TextTailFollower`(独立,可先单测)
3. P88-C `WatchCompat`(独立,Windows-only)
4. P88-B `MonitorController`(组合 A+D+C)
5. P88-E `StallGuard` hook(对 B 已启动任务生效)
6. P88-G `MonitorTool`(基于 B)
7. P88-F `/monitor` 命令(基于 B + TaskOutput/TaskStop)
8. P88-H TUI 面板(基于 B + TextTailFollower)

## §3 验收标准

### 3.1 功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| V-1 | `/monitor tail -f /tmp/test.log` 启动后返回 task_id + 输出路径 | 单元测试 |
| V-2 | `kind='monitor'` 正确写入 LocalShellTaskState | 单元测试 |
| V-3 | `/monitor list` 列出所有 kind='monitor' 且 status='running' 的任务 | 单元测试 |
| V-4 | `/monitor stop <task_id>` 通过 `os.killpg(SIGTERM)` 终止进程组 | 单元测试 |
| V-5 | `/monitor tail <task_id>` 通过 TextTailFollower 返回最新输出 | 单元测试 |
| V-6 | Linux 上 `watch -n 1 "echo tick"` 原样 spawn,3 秒后输出含 ≥ 3 行 | E2E(Linux) |
| V-7 | Windows 上 `watch -n 1 "echo tick"` 转为 `powershell -c "while(1){echo tick; Start-Sleep 1}"` | 单元测试 + platform monkeypatch |
| V-8 | `MonitorTool.execute` AI 调用返回正确 task_id + output_path | 单元测试 |
| V-9 | stall watchdog 对 `kind='monitor'` 任务豁免(后台无 45s stall 警报) | 单元测试 |
| V-10 | TUI 面板 Shift+↓ 打开 + ↑/↓ 切换 + d 删除 + q 关闭 | 集成测试 |
| V-11 | TUI 面板实时 tail 新增行(每 500ms 轮询) | 集成测试 |

### 3.2 非功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| N-1 | MonitorController.start < 200ms(Popen + tag 写入) | Stage 6 perf |
| N-2 | TextTailFollower 轮询开销 < 1% CPU(空闲时) | Stage 6 perf |
| N-3 | 100 并发 monitor 任务内存占用 < 50MB(每个 ~500KB) | 单元测试 |
| N-4 | ring buffer 截断不丢失最近 N 字节 | 单元测试 |
| N-5 | TUI 面板 60fps 渲染(无 MarkupError) | Stage 3e |
| N-6 | Windows PowerShell 转换对引号转义安全(注入防护) | 单元测试 |
| N-7 | 单元测试覆盖率 ≥ 75% | `pytest --cov` |

### 3.3 集成验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| I-1 | 不修改 `src/` 任何业务模块(允许 facade 桩) | `git diff --stat src/` |
| I-2 | `python3 -m pytest tests/stability_gate/ -q` 全绿 | CI |
| I-3 | `extensions/orchestrator/` 测试不受影响 | CI |
| I-4 | 与 F-68 Feature Gate(`MONITOR_TOOL`)集成(默认 off) | 单元测试 |
| I-5 | BashTool.run_in_background 现有行为不受影响(默认 kind='shell') | 单元测试(回归) |
| I-6 | MonitorTool 在 REPL + headless + remote-control 三模式均可用 | 集成测试 |
| I-7 | 与 F-89 Proactive 协同:Proactive Tick 可触发 MonitorTool | 集成测试(后续 F-89) |

## §4 风险与约束

| ID | 风险 | 缓解策略 |
|:--:|------|----------|
| R-1 | `kind` 字段加在 `LocalShellTaskState` 上可能与上游 TS 类型结构漂移 | 字段设为可选 + 默认 `'shell'`,序列化时 omit 空值 |
| R-2 | `tail -f` 任务永驻,REPL 退出时忘记清理 → 僵尸进程 | REPL 退出时 `_cleanup_monitors()` 调 `stop_background_bash` for all kind='monitor' |
| R-3 | Windows PowerShell 注入风险(命令含引号 / `$` 等) | `WatchCompat` 用 `shlex.quote` 转义 inner_cmd;E2E 测试覆盖 `echo "hello $world"` 等 case |
| R-4 | TUI 面板 100 个并发 monitor → 渲染卡顿 | panel 默认显示前 20 个 + lazy load;切任务时不阻塞 UI |
| R-5 | TextTailFollower poll 间隔 500ms 对高频输出不实时 | 增加 `--fast` 模式(poll 100ms);默认保持 500ms 避免空转 |
| R-6 | stall watchdog 豁免逻辑 hook 注入可能与现有 watchdog 实现冲突 | 仅跳过 `kind='monitor'` 检查;其他 watchdog 行为不变 |
| R-7 | `/tmp/clawcodex-bg/<id>.log` 大小无限制 → 磁盘爆满 | 加 ring buffer 截断(默认 200MB per file);定期 GC 完成 > 7 天的任务 |
| R-8 | 多窗口/多 REPL 共享 `/tmp/clawcodex-bg/` → task_id 冲突 | `generate_task_id` 加 hostname 前缀(已有 `b` prefix,扩展为 `m<host_short><id>`) |
| R-9 | PowerShell 在 zh-CN Windows 默认 GBK 编码,导致 UTF-8 输出乱码 | 复用 BashTool background 已有的 `PYTHONIOENCODING=utf-8` 修复;显式 `encoding="utf-8"` |
| R-10 | `MonitorTool` 与 BashTool.run_in_background 功能重叠(都是后台 spawn) | 文档明确:`MonitorTool` 默认长驻 + stall 豁免 + tail 面板;BashTool 用于一次性后台任务 |

## §5 与现有架构的对齐

- **三层架构**: `clawcodex_ext/services/monitor/` 全新子模块(Layer 1),`clawcodex_ext/tool_system/tools/monitor.py` AI 工具(Layer 1),`extensions/` 无新增(F-88 完全 Layer 1 内部,符合"对上游模块的增强/覆盖 → clawcodex_ext/"原则)
- **复用优先**: `spawn_background_bash` / `stop_background_bash` 直接复用,只在 state 上加 `kind` 标签(零重复实现)
- **类型扩展**: `LocalShellTaskState` 新增可选 `kind` 字段(默认 `'shell'`),不破坏现有 bash 路径(回归安全)
- **注册模式**: `MonitorTool` 注册到 `tool_registry`,`MONITOR_COMMAND` 注册到 `command_registry`,`StallGuard` 注册为 watchdog hook(全部避免改 `src/`)
- **猴补丁**: `clawcodex_ext/repl/monitor_integration.py` 注入 Shift+↓ keybinding(对齐 F-85 同样模式)
- **Feature Flag**: F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `MONITOR_TOOL`(默认 off,需 env `FEATURE_MONITOR_TOOL=1` 启用)
- **稳定性门禁**: 复用 `tests/stability_gate/`,新增 Stage 9 monitor smoke test

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建(8 子特性,11 验收项,10 风险) | 派工 F-88 P0 缺口,对接 CCB MONITOR_TOOL + `/monitor` 命令 |
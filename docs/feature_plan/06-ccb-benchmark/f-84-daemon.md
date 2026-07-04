# F-84: Daemon 后台守护进程

> 状态: 📋 规划中
> 章节: `docs/feature_plan/06-ccb-benchmark/f-84-daemon.md`
> 最后更新: 2026-06-30
> 缺口来源: [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵)

## §1 设计规划

### 1.1 目标

对标 CCB `src/daemon/main.ts`(Supervisor + Worker 生命周期管理 + 指数退避重启),实现 ClawCodex 的后台守护进程,负责管理多个长驻 Worker 子进程的生命周期,支撑 Remote Control(远程控制)、Cron 调度、Proactive 自主模式等场景。

### 1.2 背景

ClawCodex 当前 `src/entrypoints/daemon.py` 显式声明"not yet implemented",导致 `clawcodex daemon` 命令族完全不可用。同时:

- CCB 的 DAEMON 与 BRIDGE_MODE 强绑定,缺 Daemon 即缺完整 RCS(Remote Control Server)体验;
- ClawCodex 已落地的 `extensions/remote_api/`(Hermes 兼容 API,2,606 行)与 `extensions/ports/bridge/`(4,158 行)运行在当前进程内,无法做到 supervisor-worker 进程隔离;
- 现有 `clawcodex_ext/agent/background_runner.py`(fork 后台 Agent)使用 `subprocess.Popen` 在 Windows 上提供单进程后台模式,不适合多 worker 长驻场景。

### 1.3 子特性分解

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P84-A | Supervisor 进程入口与状态文件 IO | 📋 | 3-5 天 |
| P84-B | Worker 生命周期管理(启动/重启/退避/parking) | 📋 | 5-7 天 |
| P84-C | 优雅关闭与强制 kill(SIGTERM/SIGINT/SIGKILL) | 📋 | 2-3 天 |
| P84-D | Worker 注册表(Worker kind → Worker 工厂) | 📋 | 3-5 天 |
| P84-E | `daemon start/stop/status/ps` CLI 子命令 | 📋 | 3-5 天 |
| P84-F | `daemon bg/attach/logs/kill` 后台会话子命令 | 📋 | 3-5 天 |
| P84-G | `remoteControl` Worker(对接 `extensions/ports/bridge/`) | 📋 | 5-7 天 |
| P84-H | Feature Flag 双门控(DAEMON + BRIDGE_MODE) | 📋 | 1 天 |
| P84-I | 单元测试 + 集成测试(E2E 启动/重启/关闭) | 📋 | 5-7 天 |

**估算总工时**: 6-8 周(单人)

### 1.4 架构设计

#### 1.4.1 进程模型

```
┌─────────────────────────────────────────────────┐
│ Supervisor (clawcodex-dev daemon start)         │
│   - 主进程 (long-running)                       │
│   - 维护 WorkerState 列表 + 文件系统状态文件     │
│   - 接收 SIGTERM/SIGINT 优雅关闭                 │
└─────────────────────────────────────────────────┘
        │
        │ spawn (subprocess.Popen, env vars)
        │
        ├──> Worker: remoteControl
        │       - run_bridge_headless() — Remote Control headless 模式
        │       - 复用 extensions/ports/bridge/bridge_main.py(986 行)
        │       - 经 env vars (DAEMON_WORKER_*) 接收 supervisor 配置
        │
        ├──> Worker: cron(预留)
        │       - 复用 clawcodex_ext/cron_system/ 的 TickScheduler
        │
        └──> Worker: orchestrator(预留)
                - 复用 extensions/orchestrator/ 的 Orchestrator daemon

        ▼
文件系统状态文件: ~/.clawcodex/daemon/<name>.json
  {
    "pid": <supervisor_pid>,
    "cwd": "/abs/path/to/cwd",
    "started_at": "2026-06-30T12:34:56Z",
    "worker_kinds": ["remoteControl"],
    "last_status": "running" | "stopped" | "error"
  }
```

#### 1.4.2 包结构(全部落在 `extensions/daemon/`,不动 `src/`)

```
extensions/daemon/
├── __init__.py                       # 版本 + 公共导出
├── supervisor.py                     # P84-A: Supervisor 主循环
├── state.py                          # P84-A: 状态文件 IO
├── worker_registry.py                # P84-D: Worker kind → factory
├── lifecycle.py                      # P84-B/C: 启动/重启/退避/parking/关闭
├── cli.py                            # P84-E/F: CLI 子命令(start/stop/status/...)
├── workers/
│   ├── __init__.py
│   ├── base.py                       # Worker 抽象基类
│   ├── remote_control.py             # P84-G: 远程控制 Worker
│   └── cron.py                       # 预留:Cron Worker
├── config.py                         # P84-H: DaemonConfig pydantic 模型
├── errors.py                         # 自定义异常类
└── constants.py                      # 退出码/退避常量

clawcodex_ext/daemon/
└── bridge_integration.py             # 与 src/bridge/ 桥接(猴补丁)

extensions/capabilities/daemon_protocol.py  # Protocol 接口(Layer 2 → Layer 1)
```

#### 1.4.3 解耦要点

| 设计点 | 解耦方式 | 理由 |
|--------|----------|------|
| Supervisor 进程 | 全新子系统 → `extensions/daemon/` | 不依赖上游具体实现 |
| Worker 入口 | Worker 协议(`Worker` Protocol) → `extensions/capabilities/` | Layer 2 → Layer 1 解耦 |
| `remoteControl` Worker 实现 | 复用 `extensions/ports/bridge/bridge_main.py`(已存在) | 不重复造轮子 |
| `clawcodex daemon` 子命令注册 | 通过 `clawcodex_ext/cli/dispatch.py` 扩展 | 避免改 `src/cli.py` |
| Feature Flag | 在 `clawcodex_ext/feature_gate/registry.py` 注册 | 复用 F-68 |
| 与 `src/bridge/` 协同 | `clawcodex_ext/daemon/bridge_integration.py` 猴补丁 | 不改 `src/` |

### 1.5 核心数据模型

```python
# extensions/daemon/state.py

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
import json

class DaemonStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STALE = "stale"     # 状态文件存在但 PID 已死
    ERROR = "error"

@dataclass
class DaemonState:
    """持久化到 ~/.clawcodex/daemon/<name>.json 的状态。"""
    pid: int
    cwd: str
    started_at: str                     # ISO 8601
    worker_kinds: list[str]
    last_status: DaemonStatus = DaemonStatus.RUNNING
    name: str = "remote-control"        # 多 daemon 支持(如 "default" / "staging")

@dataclass
class WorkerState:
    """Supervisor 内存中的 Worker 状态(不持久化)。"""
    kind: str
    process: subprocess.Popen | None = None
    backoff_ms: int = BACKOFF_INITIAL_MS
    failure_count: int = 0
    parked: bool = False
    last_start_time: float = 0.0
    restart_timer: asyncio.Task | None = None

# constants.py
EXIT_CODE_PERMANENT = 78       # ex_config — 不再重启
EXIT_CODE_TRANSIENT = 1        # 普通错误 — 进入退避
BACKOFF_INITIAL_MS = 2_000     # 初始退避
BACKOFF_CAP_MS = 120_000       # 退避上限
BACKOFF_MULTIPLIER = 2         # 指数倍数
MAX_RAPID_FAILURES = 5         # 快速失败阈值
RAPID_FAILURE_WINDOW_MS = 10_000  # "快速失败"窗口(10s 内)
GRACEFUL_SHUTDOWN_TIMEOUT_MS = 30_000  # SIGTERM 后等 30s 再 SIGKILL
```

### 1.6 核心接口

#### 1.6.1 Supervisor 接口

```python
# extensions/daemon/supervisor.py

class Supervisor:
    """Supervisor 主进程:管理多个 Worker 的生命周期。"""

    def __init__(
        self,
        config: DaemonConfig,
        worker_registry: WorkerRegistry,
        *,
        state_dir: Path | None = None,
    ): ...

    async def run(self) -> int:
        """Supervisor 主循环:启动 Worker → 监听信号 → 优雅关闭。"""

    def start_worker(self, kind: str) -> None:
        """启动一个新 Worker(由 WorkerRegistry.factory[kind] 实例化)。"""

    def stop_worker(self, kind: str, *, timeout_ms: int = 30_000) -> bool:
        """优雅关闭: SIGTERM → 等待 → SIGKILL。"""

    def restart_worker(self, kind: str) -> None:
        """手动重启(暴露给 CLI / RPC)。"""

    def get_status(self) -> dict[str, WorkerStatusInfo]:
        """返回所有 Worker 的当前状态(PID/uptime/restarts/failures)。"""
```

#### 1.6.2 Worker 协议(在 `extensions/capabilities/daemon_protocol.py` 定义)

```python
from typing import Protocol, runtime_checkable
import asyncio

@runtime_checkable
class Worker(Protocol):
    """Worker 子进程入口协议 — Supervisor 通过此协议调用 Worker。"""

    kind: str

    async def run(self, env: dict[str, str]) -> int:
        """Worker 主循环入口;返回 exit code(0=正常 / 78=PERMANENT / 1=TRANSIENT)。
        env 中包含 Supervisor 注入的 DAEMON_WORKER_* 配置。"""

    def health_check(self) -> dict[str, Any] | None:
        """可选:返回 Worker 健康状态(供 Supervisor / RCS 监控面板使用)。"""
```

#### 1.6.3 Worker Registry

```python
# extensions/daemon/worker_registry.py

class WorkerRegistry:
    """Worker kind → Worker 工厂注册表。"""

    _factories: dict[str, Callable[[], Worker]] = {}

    @classmethod
    def register(cls, kind: str, factory: Callable[[], Worker]) -> None:
        cls._factories[kind] = factory

    @classmethod
    def create(cls, kind: str) -> Worker:
        factory = cls._factories.get(kind)
        if not factory:
            raise UnknownWorkerKindError(kind)
        return factory()

    @classmethod
    def known_kinds(cls) -> list[str]:
        return list(cls._factories.keys())
```

注册示例(`extensions/daemon/workers/remote_control.py`):

```python
from extensions.daemon.worker_registry import WorkerRegistry
from extensions.ports.bridge.bridge_main import run_bridge_loop, BridgeConfig

class RemoteControlWorker:
    kind = "remoteControl"

    async def run(self, env: dict[str, str]) -> int:
        config = BridgeConfig(
            spawn_mode=env.get("DAEMON_WORKER_SPAWN_MODE", "same-dir"),
            capacity=int(env.get("DAEMON_WORKER_CAPACITY", "4")),
            permission_mode=env.get("DAEMON_WORKER_PERMISSION"),
            sandbox=env.get("DAEMON_WORKER_SANDBOX") == "1",
        )
        try:
            await run_bridge_loop(config=config, ...)
            return 0
        except PermanentError as e:
            logger.error("permanent error: %s", e)
            return 78  # EXIT_CODE_PERMANENT
        except Exception as e:
            logger.exception("transient error")
            return 1   # EXIT_CODE_TRANSIENT

WorkerRegistry.register("remoteControl", RemoteControlWorker)
```

### 1.7 状态文件 IO

```python
# extensions/daemon/state.py

def get_state_path(name: str = "remote-control") -> Path:
    return Path.home() / ".clawcodex" / "daemon" / f"{name}.json"

def write_daemon_state(state: DaemonState) -> None:
    """Supervisor 启动时写入;stop 时删除。原子写(.tmp + os.replace)。"""
    path = get_state_path(state.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换

def read_daemon_state(name: str = "remote-control") -> DaemonState | None:
    """读取状态;文件不存在返回 None。"""
    path = get_state_path(name)
    try:
        return DaemonState(**json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def remove_daemon_state(name: str = "remote-control") -> None:
    """优雅关闭后清理状态文件。"""
    try:
        get_state_path(name).unlink()
    except FileNotFoundError:
        pass

def is_process_alive(pid: int) -> bool:
    """PID 存活检测 — 用 signal.SIG_DFL (signal 0) 探测。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False

def query_daemon_status(name: str = "remote-control") -> tuple[DaemonStatus, DaemonState | None]:
    """查询 daemon 状态;若 PID 已死则自动清理 stale 状态文件。
    Returns: (status, state_or_None)"""
    state = read_daemon_state(name)
    if state is None:
        return DaemonStatus.STOPPED, None
    if is_process_alive(state.pid):
        return DaemonStatus.RUNNING, state
    remove_daemon_state(name)  # 自动清理
    return DaemonStatus.STALE, None
```

### 1.8 Worker 生命周期

#### 1.8.1 启动 Worker

```python
async def spawn_worker(
    worker: WorkerState,
    config: DaemonConfig,
    supervisor_pid: int,
    stop_event: asyncio.Event,
) -> None:
    if stop_event.is_set() or worker.parked:
        return

    worker.last_start_time = time.monotonic()

    # 注入环境变量
    env = {
        **os.environ,
        "DAEMON_WORKER_DIR": str(config.dir),
        "DAEMON_WORKER_NAME": config.name or "",
        "DAEMON_WORKER_SPAWN_MODE": config.spawn_mode,
        "DAEMON_WORKER_CAPACITY": str(config.capacity),
        "DAEMON_WORKER_PERMISSION": config.permission_mode or "",
        "DAEMON_WORKER_SANDBOX": "1" if config.sandbox else "0",
        "DAEMON_WORKER_TIMEOUT_MS": str(config.timeout_ms),
        "DAEMON_WORKER_CREATE_SESSION": "1",
        "CLAWCODEX_SESSION_KIND": "daemon-worker",
        "CLAWCODEX_SUPERVISOR_PID": str(supervisor_pid),
    }

    # 构建 CLI 启动命令 — `clawcodex-dev --daemon-worker=<kind>`
    argv = [sys.executable, "-m", "clawcodex_dev", f"--daemon-worker={worker.kind}"]

    logger.info("[supervisor] spawning worker '%s' (pid will be assigned)", worker.kind)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(config.dir),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    worker.process = proc

    # 异步读取 stdout/stderr + 加前缀 + 转发到 supervisor 日志
    asyncio.create_task(_pump_stream(proc.stdout, worker.kind, level=logging.INFO))
    asyncio.create_task(_pump_stream(proc.stderr, worker.kind, level=logging.ERROR))

    # 监听 exit
    try:
        exit_code = await proc.wait()
    except asyncio.CancelledError:
        return

    worker.process = None
    await _on_worker_exit(worker, exit_code, config, stop_event)
```

#### 1.8.2 退避 + Parking

```python
async def _on_worker_exit(
    worker: WorkerState,
    exit_code: int,
    config: DaemonConfig,
    stop_event: asyncio.Event,
) -> None:
    if stop_event.is_set():
        return  # supervisor 在关闭,不重启

    # 永久错误 → parking(不再重启)
    if exit_code == EXIT_CODE_PERMANENT:
        logger.error("[supervisor] worker '%s' exited with PERMANENT error — parking", worker.kind)
        worker.parked = True
        return

    # 快速失败检测(run duration < 10s → failure_count++)
    run_duration_ms = (time.monotonic() - worker.last_start_time) * 1000
    if run_duration_ms < RAPID_FAILURE_WINDOW_MS:
        worker.failure_count += 1
        if worker.failure_count >= MAX_RAPID_FAILURES:
            logger.error(
                "[supervisor] worker '%s' failed %d times rapidly — parking",
                worker.kind, worker.failure_count,
            )
            worker.parked = True
            return
    else:
        # 正常运行一段时间 → 重置 failure_count 与 backoff
        worker.failure_count = 0
        worker.backoff_ms = BACKOFF_INITIAL_MS

    # 指数退避重启
    logger.info(
        "[supervisor] worker '%s' exited (code=%d), restarting in %dms",
        worker.kind, exit_code, worker.backoff_ms,
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=worker.backoff_ms / 1000)
        return  # stop_event 被 set,supervisor 在关闭
    except asyncio.TimeoutError:
        pass  # 正常超时 → 重启

    if not stop_event.is_set() and not worker.parked:
        await spawn_worker(worker, config, supervisor_pid, stop_event)

    worker.backoff_ms = min(worker.backoff_ms * BACKOFF_MULTIPLIER, BACKOFF_CAP_MS)
```

#### 1.8.3 优雅关闭

```python
async def graceful_shutdown(
    workers: list[WorkerState],
    *,
    timeout_ms: int = GRACEFUL_SHUTDOWN_TIMEOUT_MS,
) -> None:
    """SIGTERM → 等待 → SIGKILL 兜底。"""
    for w in workers:
        if w.process and w.process.returncode is None:
            logger.info("[supervisor] sending SIGTERM to worker '%s' (pid=%d)", w.kind, w.process.pid)
            try:
                w.process.terminate()  # SIGTERM on POSIX; CTRL_BREAK on Windows
            except ProcessLookupError:
                pass

    # 等所有 worker 退出
    pending = [w for w in workers if w.process and w.process.returncode is None]
    if not pending:
        return

    done, still_running = await asyncio.wait(
        [asyncio.create_task(w.process.wait()) for w in pending],
        timeout=timeout_ms / 1000,
    )

    for w in still_running:
        proc = w.process
        if proc and proc.returncode is None:
            logger.warning("[supervisor] worker '%s' did not exit gracefully, sending SIGKILL", w.kind)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
```

### 1.9 CLI 子命令

```python
# extensions/daemon/cli.py
# 注册到 clawcodex_ext/cli/dispatch.py(避免改 src/cli.py)

DAEMON_COMMANDS = {
    "start": cmd_daemon_start,
    "stop": cmd_daemon_stop,
    "status": cmd_daemon_status,
    "ps": cmd_daemon_status,  # 别名
    "bg": cmd_daemon_bg,
    "attach": cmd_daemon_attach,
    "logs": cmd_daemon_logs,
    "kill": cmd_daemon_kill,
}

async def cmd_daemon_start(args: list[str]) -> int:
    """`clawcodex-dev daemon start [--dir X] [--spawn-mode Y] ...`

    1. 检查是否已有 daemon 在跑(query_daemon_status)
    2. 若已 RUNNING,提示并返回 1
    3. 写状态文件(pid/cwd/started_at/worker_kinds)
    4. 注册 signal handlers(SIGTERM/SIGINT)
    5. 进入 supervisor.run() 主循环
    """
```

#### 1.9.1 `daemon status` 输出格式

```
=== Daemon Supervisor ===
  Status:  running
  PID:     12345
  CWD:     /home/user/proj
  Started: 2026-06-30T12:34:56Z
  Workers: remoteControl

=== Workers ===
  ✓ remoteControl   pid=12346  uptime=00:15:32  restarts=0  failures=0
```

#### 1.9.2 `--daemon-worker=<kind>` Worker 入口

需要在 `src/entrypoints/cli.py` 路由分发前注入,但我们不动 `src/`,所以方案是:

- **方案 A**: 在 `clawcodex_ext/cli/dispatch.py` 注册 `clawcodex-dev --daemon-worker=<kind>` 顶层选项(优先级高于 src/cli.py 的默认路由)
- **方案 B**: 在 `extensions/daemon/__init__.py` 提供 `python -m extensions.daemon.worker_main <kind>` 子命令,Supervisor 用 `python -m extensions.daemon.worker_main <kind>` 启动

**推荐方案 B**(纯 Python module,不污染 CLI 入口,Worker 与 Supervisor 通过 module 路径直接 import)。

```python
# extensions/daemon/worker_main.py

async def main(kind: str) -> int:
    """`python -m extensions.daemon.worker_main <kind>` Worker 入口。"""
    from extensions.daemon.worker_registry import WorkerRegistry
    worker = WorkerRegistry.create(kind)
    return await worker.run(os.environ.copy())

if __name__ == "__main__":
    import sys
    kind = sys.argv[1] if len(sys.argv) > 1 else None
    if not kind:
        print("usage: python -m extensions.daemon.worker_main <kind>", file=sys.stderr)
        sys.exit(78)
    sys.exit(asyncio.run(main(kind)))
```

Supervisor 启动命令相应改为:

```python
argv = [sys.executable, "-m", "extensions.daemon.worker_main", worker.kind]
```

### 1.10 与 BRIDGE_MODE 的双门控

```python
# clawcodex_ext/daemon/bridge_integration.py

from clawcodex_ext.feature_gate.registry import get_registry
from extensions.daemon.cli import DAEMON_COMMANDS

def install_daemon_gate() -> None:
    """Feature Flag 双门控:DAEMON + BRIDGE_MODE 同时启用才注册 daemon CLI。"""
    from clawcodex_ext.cli.dispatch import register_subcommand

    def _is_daemon_available() -> bool:
        reg = get_registry()
        return reg.is_enabled("DAEMON") and reg.is_enabled("BRIDGE_MODE")

    for subcmd, handler in DAEMON_COMMANDS.items():
        wrapped = require_feature("DAEMON")(require_feature("BRIDGE_MODE")(handler))
        register_subcommand("daemon", subcmd, wrapped, is_enabled=_is_daemon_available)
```

`clawcodex_ext/__init__.py` 调用 `install_daemon_gate()` 触发(模式 B 猴补丁)。

### 1.11 依赖与协同

| 依赖 | 说明 |
|------|------|
| F-68 Feature Gate | DAEMON / BRIDGE_MODE 双门控 |
| F-82 Remote Control | `extensions/remote_api/`(OpenAI 兼容 API) + `extensions/ports/bridge/`(bridge core) |
| `clawcodex_ext/feature_gate/` | 已完成,直接复用 |
| `extensions/capabilities/` | Protocol 接口定义 |
| `src/bridge/bridge_main.py` facade | 通过 `extensions/ports/bridge/bridge_main.py` 复用,不直接 import `src/` |

| 协同 | 说明 |
|------|------|
| F-85 Pipe IPC | Worker 可通过 pipe 与 main REPL 通信 |
| F-89 Proactive | Daemon 可作为 Proactive Tick 的执行宿主 |
| F-83 远程 Triggers | 远程 trigger 通过 daemon 派发执行 |

### 1.12 测试策略

#### 1.12.1 单元测试

- `tests/extensions/daemon/test_state.py` — 状态文件 IO + 原子写 + stale 自动清理
- `tests/extensions/daemon/test_lifecycle.py` — 退避 / parking / 优雅关闭(用 mock subprocess)
- `tests/extensions/daemon/test_worker_registry.py` — Worker 注册与解析
- `tests/extensions/daemon/test_cli.py` — CLI 子命令参数解析

#### 1.12.2 集成测试(E2E)

- `tests/extensions/daemon/e2e_supervisor.py`:
  1. 启动 daemon(start → 后台 spawn)
  2. kill Worker 子进程,验证 Supervisor 在 BACKOFF_INITIAL_MS 后重启
  3. 让 Worker 返回 EXIT_CODE_PERMANENT,验证 parking
  4. send SIGTERM 给 Supervisor,验证 graceful_shutdown + remove_daemon_state
- 参考 `tests/orchestrator/manual_e2e_f38.py` 的 LocalTracker 模式(子进程 sandbox)

#### 1.12.3 稳定性门禁

- `tests/stability_gate/test_stage5_extensions.py` 增补 daemon import smoke test
- 新增 `tests/stability_gate/test_stage7_daemon.py`(轻量,只验证 start/stop round-trip,30s 超时)

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|----------|
| 2026-06-30 | 初始创建(P0 缺口派工,详设) | `f-84-daemon.md`(本文) |
| 2026-06-30 | 缺口盘点纳入 [README.md §A 缺口矩阵](./README.md#a-全特性对照矩阵) | gap-analysis §3.1 |

### 2.2 下一步计划

按 1.3 子特性表顺序推进:
1. P84-A Supervisor + 状态 IO(并行可做 P84-H Feature Flag)
2. P84-B/C Worker 生命周期(退避 / 优雅关闭)
3. P84-D Worker Registry + P84-G remoteControl Worker
4. P84-E/F CLI 子命令(start/stop/status/bg/attach/logs/kill)
5. P84-I 测试(单元 + E2E + 稳定性门禁)

## §3 验收标准

### 3.1 功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| V-1 | `clawcodex-dev daemon start` 启动 supervisor,写状态文件 | E2E 测试:启动后 `~/.clawcodex/daemon/remote-control.json` 存在 |
| V-2 | `clawcodex-dev daemon status` 返回 supervisor + workers 状态 | E2E 测试:输出包含 PID / uptime / workers 列表 |
| V-3 | `clawcodex-dev daemon stop` 优雅关闭(SIGTERM → 30s 内退出) | E2E 测试:start → sleep 5 → stop → 验证状态文件被清理 |
| V-4 | Worker 崩溃后 Supervisor 在 BACKOFF_INITIAL_MS(2s)内重启 | E2E 测试:Worker 异常退出 → 验证 2-5s 内 restart |
| V-5 | Worker 返回 EXIT_CODE_PERMANENT(78)后 parking(不再重启) | 单元测试 + E2E |
| V-6 | 10s 内连续 5 次崩溃 → parking | 单元测试 |
| V-7 | `remoteControl` Worker 复用 `extensions/ports/bridge/` 启动 headless bridge | 集成测试:Worker 启动后能接受 WebSocket 连接 |
| V-8 | Feature Flag 双门控(DAEMON + BRIDGE_MODE)生效 | 单元测试 |
| V-9 | Stale 状态自动清理(PID 死后 query 清理) | 单元测试 |
| V-10 | 原子状态文件写(`.tmp` + `os.replace`) | 单元测试 |

### 3.2 非功能验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| N-1 | Supervisor 冷启动 < 3s(纯 Python module) | Stage 6 perf 测试 |
| N-2 | 内存占用 < 100MB(空载,无 Worker) | Stage 6 perf 测试 |
| N-3 | 状态文件原子写不出现半写 | 单元测试 + 并发测试 |
| N-4 | Supervisor 关闭优雅退出 < 30s | E2E 测试 |
| N-5 | 单元测试覆盖率 ≥ 75% | `pytest --cov` |

### 3.3 集成验收

| ID | 标准 | 验证方式 |
|:--:|------|----------|
| I-1 | 不修改 `src/` 任何业务模块 | `git diff --stat src/` 应为 0(除必要的 facade 桩) |
| I-2 | `python3 -m pytest tests/stability_gate/ -q` 全绿 | CI |
| I-3 | `extensions/orchestrator/` 测试不受影响 | CI |
| I-4 | 新增 E2E 测试不依赖外部服务(LocalTracker 风格) | 本地可独立跑 |
| I-5 | 与 F-82 Remote Control / F-85 Pipe IPC 协同无回归 | CI + 手动集成测试 |

## §4 风险与约束

| ID | 风险 | 缓解策略 |
|:--:|------|----------|
| R-1 | `extensions/ports/bridge/bridge_main.py` 是 986 行 monolith,Worker 复用可能引入耦合 | Worker 仅调用 `run_bridge_loop()`,不直接接触内部状态 |
| R-2 | Windows subprocess 创建标志与 POSIX 差异 | 参考 `clawcodex_ext/agent/background_runner.py:_launch_via_subprocess`(已实现 Windows 分支) |
| R-3 | SIGTERM 在 Windows 上语义不同 | Windows 用 `CTRL_BREAK_EVENT`(CREATE_NEW_PROCESS_GROUP);POSIX 用 SIGTERM |
| R-4 | Daemon 状态文件并发写竞态 | 原子写(`.tmp` + `os.replace`)+ fcntl flock 兜底 |
| R-5 | 多 daemon 实例(同名)冲突 | start 前先 query_daemon_status,RUNNING 则拒绝 |
| R-6 | Worker 进程 leak(supervisor kill 但 Worker 没 kill) | process group leader(POSIX `setsid`)+ Windows `CREATE_NEW_PROCESS_GROUP` |
| R-7 | 与 `src/bridge/` facade 升级路径冲突 | 通过 `extensions/ports/bridge/` 走解耦路径,不直接 import `src.bridge` |
| R-8 | 长跑稳定性(daemon 跑几天不挂) | E2E 测试 24h soak test + 内存泄漏监控 |

## §5 与现有架构的对齐

- **三层架构**: `extensions/daemon/` 全部为新代码,`clawcodex_ext/daemon/bridge_integration.py` 为猴补丁,`src/` 不动;
- **Protocol 接口**: 在 `extensions/capabilities/daemon_protocol.py` 定义 `Worker` Protocol,允许三方扩展不依赖具体实现;
- **注册模式**: 通过 `WorkerRegistry.register(kind, factory)` 注册,默认注册 `remoteControl`;
- **Feature Flag**: F-68 `clawcodex_ext/feature_gate/registry.py` 注册 `DAEMON` / `BRIDGE_MODE`;
- **稳定性门禁**: 复用 `tests/stability_gate/` 框架,新增 Stage 7 daemon smoke test。

## §6 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建(详设文档,9 子特性,10 验收项,8 风险) | 派工 F-84 P0 缺口,对接 CCB DAEMON 实现 |
"""通用远程任务执行 worker（F-84 重构）。

替代原有的 ``remoteControl`` worker，不再依赖 Anthropic Cloud bridge。
使用 Unix Domain Socket 监听入站任务，通过子进程执行 agent 任务。

核心设计
--------
* 监听 ``~/.clawcodex/task_server/task.sock``（可通过环境变量覆盖）
* 接受 JSON 行协议（每行一个完整的 JSON 对象）
* 每个入站连接可发送多个 TaskRequest（连接保持）
* 任务通过 ``clawcodex-dev -p <prompt>`` 子进程执行
* 结果回写到同一个 socket 连接

使用示例
--------
发送任务::

    echo '{"id":"t1","command":"run_agent","payload":{"prompt":"检查代码"}}' \\
      | socat - UNIX-CONNECT:~/.clawcodex/task_server/task.sock

"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess  # noqa: S404 — controlled subprocess spawn
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from extensions.capabilities.task_protocol import (
    RemoteTaskWorker,
    TaskRequest,
    TaskResult,
)

logger = logging.getLogger(__name__)

# ── 默认路径 ──────────────────────────────────────────────────────

DEFAULT_STATE_DIR = Path.home() / ".clawcodex" / "task_server"
ENV_SOCK_PATH = "CLAWCODEX_TASK_SOCK"
ENV_STATE_DIR = "CLAWCODEX_TASK_STATE_DIR"


# ── TaskRequest JSON 解析 ──────────────────────────────────────────


def _parse_task_request(raw: dict[str, Any]) -> TaskRequest:
    """从 JSON dict 解析 TaskRequest，缺失字段用默认值填充。"""
    return TaskRequest(
        id=str(raw.get("id", uuid.uuid4().hex)),
        command=str(raw.get("command", "run_agent")),
        payload=raw.get("payload", {}),
        metadata=raw.get("metadata", {}),
    )


def _task_result_to_json(result: TaskResult) -> str:
    """序列化 TaskResult 为 JSON 行。"""
    return json.dumps(
        {
            "task_id": result.task_id,
            "status": result.status,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
    )


# ── 任务执行 ──────────────────────────────────────────────────────


async def _execute_task(request: TaskRequest) -> TaskResult:
    """执行一个任务请求。

    当前支持的命令:
    * ``run_agent`` — 通过 ``clawcodex-dev -p <prompt>`` 子进程运行 agent
    * ``exec`` — 直接执行 shell 命令（由 payload["cmd"] 指定）
    * ``ping`` — 返回存活确认
    """
    logger.info("[task_worker] executing task id=%s command=%s", request.id, request.command)

    if request.command == "ping":
        return TaskResult(
            task_id=request.id,
            status="completed",
            output="pong",
            exit_code=0,
            metadata={"executed_at": time.time()},
        )

    if request.command == "exec":
        cmd = request.payload.get("cmd", "")
        if not cmd:
            return TaskResult(
                task_id=request.id,
                status="failed",
                error="payload.cmd is required for 'exec' command",
                exit_code=1,
            )
        return await _run_subprocess(request.id, cmd, shell=True)

    if request.command == "run_agent":
        prompt = request.payload.get("prompt", "")
        if not prompt:
            return TaskResult(
                task_id=request.id,
                status="failed",
                error="payload.prompt is required for 'run_agent' command",
                exit_code=1,
            )
        cwd = request.payload.get("cwd") or os.getcwd()
        model = request.payload.get("model") or ""
        max_turns = request.payload.get("max_turns", 20)
        agent_cli = [sys.executable, "-m", "clawcodex"]
        if model:
            agent_cli += ["--model", str(model)]
        agent_cli += ["-p", prompt, "--max-turns", str(max_turns)]
        return await _run_subprocess(
            request.id,
            agent_cli,
            shell=False,
            cwd=cwd,
            timeout=request.payload.get("timeout"),
        )

    return TaskResult(
        task_id=request.id,
        status="failed",
        error=f"unknown command: {request.command!r}",
        exit_code=1,
    )


async def _run_subprocess(
    task_id: str,
    cmd: str | list[str],
    *,
    shell: bool = False,
    cwd: str | None = None,
    timeout: float | None = None,
) -> TaskResult:
    """运行子进程并捕获输出。"""
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd if isinstance(cmd, list) else [cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            shell=shell,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = time.monotonic() - start
            return TaskResult(
                task_id=task_id,
                status="failed",
                error=f"timed out after {timeout}s",
                exit_code=-1,
                metadata={"elapsed_s": round(elapsed, 3)},
            )

        elapsed = time.monotonic() - start
        out_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        err_text = stderr.decode("utf-8", errors="replace") if stderr else ""

        if proc.returncode == 0:
            return TaskResult(
                task_id=task_id,
                status="completed",
                output=out_text,
                exit_code=0,
                metadata={"elapsed_s": round(elapsed, 3)},
            )

        return TaskResult(
            task_id=task_id,
            status="failed" if proc.returncode != 78 else "permanent_failure",
            output=out_text,
            error=err_text,
            exit_code=proc.returncode or -1,
            metadata={"elapsed_s": round(elapsed, 3)},
        )

    except FileNotFoundError as exc:
        return TaskResult(
            task_id=task_id,
            status="failed",
            error=f"executable not found: {exc}",
            exit_code=1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[task_worker] subprocess error task_id=%s", task_id)
        return TaskResult(
            task_id=task_id,
            status="failed",
            error=str(exc),
            exit_code=1,
        )


# ── Socket 服务 ──────────────────────────────────────────────────


def _get_sock_path(state_dir: Path | None = None) -> Path:
    """获取 Unix Socket 路径。

    优先顺序: CLAWCODEX_TASK_SOCK 环境变量 → state_dir/task.sock。
    """
    env_sock = os.environ.get(ENV_SOCK_PATH)
    if env_sock:
        return Path(env_sock)

    base = state_dir or Path(os.environ.get(ENV_STATE_DIR, DEFAULT_STATE_DIR))
    base = Path(base).expanduser().resolve()
    return base / "task.sock"


class TaskServerWorker:
    """通用远程任务执行 worker。

    监听 Unix Domain Socket，接受 JSON 行协议的任务请求，
    执行后返回结果。
    """

    kind = "task_server"

    def __init__(self, state_dir: str | Path | None = None) -> None:
        self.state_dir = Path(state_dir).expanduser().resolve() if state_dir else DEFAULT_STATE_DIR
        self.sock_path = _get_sock_path(self.state_dir)
        self._server: asyncio.AbstractServer | None = None
        self._cancel_event: asyncio.Event | None = None
        self._started_at: float = 0.0

    # ── Worker 生命周期（RemoteTaskWorker Protocol）───────────────

    async def run(self, env: dict[str, str]) -> int:
        """启动 socket 监听循环。

        实现了 :class:`extensions.capabilities.task_protocol.RemoteTaskWorker` 接口。
        """
        self._started_at = time.time()
        cancel = asyncio.Event()
        self._cancel_event = cancel

        # 安装信号处理器
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, cancel.set)
            except (NotImplementedError, RuntimeError):
                pass

        # 确保目录存在 + 清理 stale socket
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.sock_path.exists():
            self.sock_path.unlink(missing_ok=True)

        try:
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=str(self.sock_path),
            )
        except OSError as exc:
            logger.error("[task_worker] failed to bind socket %s: %s", self.sock_path, exc)
            return 78  # permanent

        # 设置 socket 权限（仅 owner 可读写）
        try:
            self.sock_path.chmod(0o600)
        except OSError:
            pass

        logger.info(
            "[task_worker] listening on %s (pid=%d)",
            self.sock_path,
            os.getpid(),
        )

        try:
            async with self._server:
                await cancel.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

        logger.info("[task_worker] shutdown complete")
        return 0

    def health_check(self) -> dict[str, Any] | None:
        """健康检查快照。"""
        if not self._started_at:
            return None
        return {
            "kind": self.kind,
            "uptime_s": round(time.time() - self._started_at, 3),
            "socket": str(self.sock_path),
            "listening": self._server is not None and self._server.is_serving(),
        }

    # ── 内部 ──────────────────────────────────────────────────────

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """处理单个客户端连接。

        每个连接可发送多个请求（每行一个 JSON 对象）。
        保持连接打开，直到客户端关闭写端或发生错误。
        """
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug("[task_worker] client connected: %s", peer)

        try:
            while not self._cancel_event or not self._cancel_event.is_set():
                line = await reader.readline()
                if not line:
                    break  # 客户端关闭连接

                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    err_result = TaskResult(
                        task_id="unknown",
                        status="failed",
                        error=f"invalid JSON: {exc}",
                        exit_code=1,
                    )
                    writer.write((_task_result_to_json(err_result) + "\n").encode("utf-8"))
                    await writer.drain()
                    continue

                request = _parse_task_request(data)
                result = await _execute_task(request)
                writer.write((_task_result_to_json(result) + "\n").encode("utf-8"))
                await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            logger.debug("[task_worker] client disconnected: %s", peer)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("[task_worker] handler error peer=%s", peer)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _cleanup(self) -> None:
        """清理 socket 文件。"""
        if self.sock_path.exists():
            try:
                self.sock_path.unlink(missing_ok=True)
            except OSError:
                pass


# ── WorkerRegistry 工厂 ────────────────────────────────────────────


def build_task_server_worker() -> TaskServerWorker:
    """Factory for ``WorkerRegistry.register("task_server", ...)``."""
    return TaskServerWorker()


__all__ = [
    "DEFAULT_STATE_DIR",
    "TaskServerWorker",
    "build_task_server_worker",
]

"""通用远程任务执行协议 — Layer 2 Protocol 定义。

定义 daemon worker 与外部任务调度方之间的接口契约，不绑定
任何特定云厂商或消息队列实现。

设计规则（遵循 CLAUDE.md 三层架构）：
  * typing.Protocol 仅声明签名，不含实现
  * 无 ABC 继承
  * 不导入 Layer 1 (src/) 模块
  * 实现方分别在 extensions/daemon/workers/（worker 侧）和
    clawcodex_ext/（客户端侧）中提供
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ── 数据模型 ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskRequest:
    """来自外部调度方的任务请求。

    ``id`` 由调度方生成，全局唯一；worker 执行完成后通过
    ``TaskResult.task_id`` 回传对应关系。
    """

    id: str
    """调用方指定的全局唯一任务 ID。"""

    command: str
    """要执行的命令/动作标识符（如 ``"run_agent"``、``"exec"``）。"""

    payload: dict[str, Any] = field(default_factory=dict)
    """命令参数 payload（如 prompt、工作目录、模型选择等）。"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """调度方附加的元数据（如来源标签、优先级、超时时间）。"""


@dataclass(frozen=True)
class TaskResult:
    """任务执行结果。"""

    task_id: str
    """对应 TaskRequest.id。"""

    status: str
    """执行状态: ``"completed"`` / ``"failed"`` / ``"cancelled"``。"""

    output: str = ""
    """标准输出/结果文本。"""

    error: str = ""
    """错误信息（如有）。"""

    exit_code: int = 0
    """进程退出码（0 = 成功）。"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """执行方附加的元数据（如耗时、token 用量）。"""


# ── 传输层协议 ────────────────────────────────────────────────────


@runtime_checkable
class TaskTransportServer(Protocol):
    """daemon worker 侧的任务传输服务。

    负责监听入站连接、接收 TaskRequest、发送 TaskResult。
    """

    async def serve(self, cancel_event: Any | None = None) -> None:
        """启动传输服务，持续监听入站任务。

        Args:
            cancel_event: asyncio.Event，设置后优雅关闭。
        """
        ...

    async def shutdown(self) -> None:
        """关闭传输服务，释放资源。"""
        ...


@runtime_checkable
class TaskTransportClient(Protocol):
    """外部调度方侧的任务传输客户端。

    负责连接到 daemon worker、发送 TaskRequest、接收 TaskResult。
    """

    async def connect(self) -> None:
        """连接到 daemon worker 的传输端点。"""
        ...

    async def send_request(self, request: TaskRequest) -> TaskResult:
        """发送任务请求并等待执行结果。

        Args:
            request: 任务请求。

        Returns:
            任务执行结果。
        """
        ...

    async def close(self) -> None:
        """关闭连接。"""
        ...


# ── 执行层协议 ────────────────────────────────────────────────────


@runtime_checkable
class TaskExecutor(Protocol):
    """任务执行器 —— 接收 TaskRequest，产生 TaskResult。"""

    async def execute(self, request: TaskRequest) -> TaskResult:
        """执行一个任务。

        Args:
            request: 待执行的任务请求。

        Returns:
            执行结果。
        """
        ...

    async def cancel(self, task_id: str) -> bool:
        """取消正在执行的任务（如支持）。

        Args:
            task_id: 要取消的任务 ID。

        Returns:
            True 表示成功取消，False 表示任务不存在或无法取消。
        """
        ...


# ── Worker 整体契约 ────────────────────────────────────────────────


@runtime_checkable
class RemoteTaskWorker(Protocol):
    """远程任务执行 worker 的整体契约。

    daemon supervisor 通过这个接口管理 worker 的生命周期。
    """

    kind: str
    """Worker 类型标识符。"""

    async def run(self, env: dict[str, str]) -> int:
        """启动 worker 的主循环。

        Args:
            env: 从 supervisor 继承的环境变量。

        Returns:
            退出码（0 = 正常退出，78 = 永久错误，其他 = 临时错误）。
        """
        ...

    def health_check(self) -> dict[str, Any] | None:
        """返回健康检查快照（可选）。"""
        ...


__all__ = [
    "RemoteTaskWorker",
    "TaskExecutor",
    "TaskRequest",
    "TaskResult",
    "TaskTransportClient",
    "TaskTransportServer",
]

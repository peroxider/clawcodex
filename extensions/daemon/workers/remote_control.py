"""``remoteControl`` daemon worker（重构版）。

重构：不再依赖 Anthropic Cloud bridge。

现在 ``remoteControl`` worker 是 :class:`TaskServerWorker`
的薄封装 —— 监听本地 Unix Domain Socket，接受 JSON 行协议的
任务请求，通过子进程执行 agent 任务。

向后兼容
---------
``WorkerRegistry`` 中 ``remoteControl`` 这个 kind 保持不变，
已有的 ``--workers remoteControl`` 仍然可用。新增的 ``task_server``
kind 是完全一致的实现，供新部署使用。

迁移路径
---------
未来版本 ``remoteControl`` 将废弃，统一使用 ``task_server``。
"""

from __future__ import annotations

import logging
from typing import Any

from extensions.daemon.workers.task_worker import TaskServerWorker

logger = logging.getLogger(__name__)


class RemoteControlWorker(TaskServerWorker):
    """``remoteControl`` worker（TaskServerWorker 别名）。

    保持 ``kind = "remoteControl"`` 以实现向后兼容。
    """

    kind = "remoteControl"


def build_remote_control_worker() -> RemoteControlWorker:
    """Factory for ``WorkerRegistry.register("remoteControl", ...)``."""
    return RemoteControlWorker()


__all__ = ["RemoteControlWorker", "build_remote_control_worker"]

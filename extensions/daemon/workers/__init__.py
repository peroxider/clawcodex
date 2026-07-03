"""Built-in daemon workers.

Importing this package **eagerly** registers the built-in worker
factories with :class:`extensions.daemon.worker_registry.WorkerRegistry`.

Callers that want a clean registry (e.g. tests that override the
``remoteControl`` factory) should call ``WorkerRegistry.reset()``
**before** importing this package.
"""

from __future__ import annotations

import logging

from extensions.daemon.worker_registry import WorkerRegistry

from .base import BaseWorker
from .cron import CronWorker, build_cron_worker
from .remote_control import RemoteControlWorker, build_remote_control_worker

logger = logging.getLogger(__name__)

# Register built-in workers. Re-registration is allowed; this is the
# canonical place to declare default factories.
WorkerRegistry.register("remoteControl", build_remote_control_worker)
WorkerRegistry.register("cron", build_cron_worker)

__all__ = [
    "BaseWorker",
    "CronWorker",
    "RemoteControlWorker",
    "build_cron_worker",
    "build_remote_control_worker",
]
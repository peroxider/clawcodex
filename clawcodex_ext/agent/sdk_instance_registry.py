"""SDK instance registry stub — per-script instance caching for wrapper calls.

This module is a downstream extension point.  The minimal implementation here
satisfies the import surface used by ``clawcodex_ext.agent.tool_authoring``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BucketKey:
    session_id: str
    agent_id: str
    script_path: Path


class _InstanceRegistry:
    _buckets: dict[BucketKey, dict[int, Any]] = {}
    _locks: dict[BucketKey, threading.RLock] = {}
    _lock = threading.Lock()

    def bucket_key(
        self,
        *,
        session_id: str,
        agent_id: str,
        script_path: Path,
    ) -> BucketKey:
        return BucketKey(
            session_id=session_id,
            agent_id=agent_id,
            script_path=Path(script_path),
        )

    def get_bucket(self, key: BucketKey) -> dict[int, Any]:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = {}
            return self._buckets[key]

    def lock_for(self, key: BucketKey) -> threading.RLock:
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            return self._locks[key]


_INSTANCE_REGISTRY = _InstanceRegistry()


def get_sdk_instance_registry() -> _InstanceRegistry:
    return _INSTANCE_REGISTRY


__all__ = ["BucketKey", "get_sdk_instance_registry"]

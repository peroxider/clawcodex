"""Task queue: manages pending and retry tasks."""

from __future__ import annotations

import heapq
from typing import List, Optional

from src.models import Task
from src.utils import now_iso


class TaskQueue:
    """Priority-based task queue with retry support."""

    def __init__(self) -> None:
        self._tasks: List[tuple] = []  # (priority, timestamp, task)
        self._counter = 0

    def add_task(self, task: Task) -> None:
        """Add a task to the queue (higher priority = executed first)."""
        self._counter += 1
        heapq.heappush(self._tasks, (-task.priority, self._counter, task))

    def add_tasks(self, tasks: List[Task]) -> None:
        """Add multiple tasks at once."""
        for t in tasks:
            self.add_task(t)

    def get_next_task(self) -> Optional[Task]:
        """Pop the highest-priority task, or None if empty."""
        if not self._tasks:
            return None
        _, _, task = heapq.heappop(self._tasks)
        return task

    def requeue_for_retry(self, task: Task) -> None:
        """Re-queue a task if it hasn't exceeded max retries."""
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            self.add_task(task)

    @property
    def size(self) -> int:
        return len(self._tasks)

    def peek(self) -> Optional[Task]:
        """Look at the next task without popping."""
        if not self._tasks:
            return None
        return self._tasks[0][2]

    def clear(self) -> None:
        self._tasks.clear()

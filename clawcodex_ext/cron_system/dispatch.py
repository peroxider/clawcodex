"""Typed dispatch bridge for cron fire events (F-22-G-2).

Replaces ad-hoc outbox-drain logic in REPL, headless, and TUI
frontends with a unified :class:`CronDispatchBridge`.

The bridge maps directly to ``CronPromptEvent`` (fire) and
``CronMissedEvent`` (missed one-shot) from
``clawcodex_ext/query/outbox_types.py``.  The ``drain()`` method
pops ``CronPromptEvent`` entries from the outbox; callers are
responsible for reading ``CronMissedEvent`` separately (typically
via a missed-task notification callback).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from clawcodex_ext.cron_system.runs import claim_cron_run, finalize_cron_run
from clawcodex_ext.query.outbox_types import CronPromptEvent


@dataclass
class CronDispatchEvent:
    """A single cron fire event, ready for execution.

    Maps directly from a ``CronPromptEvent`` in the outbox.
    """

    prompt: str
    task_id: str
    run_id: str
    wrapped_prompt: str


def _default_wrap_prompt(prompt: str, task_id: str, run_id: str) -> str:
    """Default prompt wrapper (mirrors headless ``_wrap_cron_prompt``)."""
    _ = run_id  # unused in default wrapper
    now = datetime.now()
    time_str = now.strftime("%b %d %-I:%M%p").lower()
    header = f"✻ Running scheduled task ({time_str})"
    if task_id:
        header += f" · {task_id}"
    return f"{header}\n\nThis prompt was generated automatically from a scheduled task.\n\n{prompt}"


class CronDispatchBridge:
    """Typed dispatch bridge for cron fire events.

    Replaces ad-hoc outbox-drain logic in REPL, headless, and TUI
    frontends with a unified dispatcher.

    The ``drain()`` method pops ``CronPromptEvent`` entries from the
    outbox, filtering out any non-cron events that remain in the list.
    Callers are responsible for handling ``CronMissedEvent`` entries
    separately.
    """

    def __init__(
        self,
        workspace_root: Path,
        wrap_prompt: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._wrap_prompt = wrap_prompt or _default_wrap_prompt

    def drain(self, outbox: list) -> list[CronDispatchEvent]:
        """Pop ``CronPromptEvent`` entries from the outbox.

        ``CronMissedEvent`` and other entries are left in place for
        the caller to handle.

        Returns a list of :class:`CronDispatchEvent` ready for execution.
        """
        events: list[CronDispatchEvent] = []
        remaining: list = []
        for event in outbox:
            if isinstance(event, CronPromptEvent):
                events.append(
                    CronDispatchEvent(
                        prompt=event.prompt,
                        task_id=event.task_id,
                        run_id=event.run_id,
                        wrapped_prompt=self._wrap_prompt(
                            event.prompt, event.task_id, event.run_id
                        ),
                    )
                )
            else:
                remaining.append(event)
        outbox[:] = remaining
        return events

    def claim(self, task_id: str, run_id: str) -> str | None:
        """Mark a run as started (queued → running).

        Returns the task_id on success, or None if the run was already
        claimed (e.g. duplicate).
        """
        return claim_cron_run(self._workspace_root, run_id, task_id)

    def finalize(
        self,
        task_id: str,  # noqa: ARG002
        run_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Mark a run as completed/failed/cancelled."""
        finalize_cron_run(self._workspace_root, run_id, status, error=error)
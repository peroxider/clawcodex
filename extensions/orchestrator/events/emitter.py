"""OrchestratorEventEmitter — a ProgressSink + explicit emit().

Captures session-level terminal events via the ProgressSink protocol
(``on_session_complete``) and lets call sites emit explicit events for
blind spots the sink cannot see (clarification, git/PR, control). Storm
suppression dedupes warn/error by ``(event_type, issue_id)`` within a
window; every sink dispatch is exception-isolated so an IM failure
never propagates into the orchestrator main flow.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from .types import EventLevel, OrchestratorEvent, TERMINAL_REASON_LEVEL

if TYPE_CHECKING:
    from ..progress_sink import ProgressSink  # noqa: F401
    from ..api.query import SessionComplete, PhaseComplete, TurnComplete  # noqa: F401

logger = logging.getLogger(__name__)

EventSink = Callable[[OrchestratorEvent], None]

IMMEDIATE_INFO_EVENT_TYPES = {
    "orchestrator.started",
    "orchestrator.im_registered",
    "orchestrator.im_reconnected",
    "issue.detected",
    "issue.started",
    "issue.completed",
    "issue.cancelled",
    "pr.opened",
    "pr.updated",
    "intent.retry",
    "control.pause",
    "control.resume",
}

# Terminal SessionComplete reasons whose IM event is owned by the
# orchestrator's status dispatch (``agent.stagnation`` /
# ``agent.loop_detected`` / ``agent.max_turns_exceeded``). The sink
# callback must NOT also emit a generic ``issue.failed`` here: the two
# event_types differ, so storm dedupe would not suppress the second,
# and the operator would be double-notified for one failure.
_STATUS_BRANCH_TERMINAL_REASONS = frozenset(
    {
        "stagnation",
        "loop_detected",
        "budget_exhausted",
        "max_turns_exceeded",
    }
)

_SUCCESS_TERMINAL_REASONS = frozenset({"success", "task_complete", "already_completed"})


class OrchestratorEventEmitter:
    """ProgressSink that fans orchestrator events out to IM/audit sinks.

    ``task_id`` is the bound issue id. Phase/turn events are NOT pushed
    to IM (too noisy — they live in audit/LiveView); only terminal
    session events and explicit ``emit()`` calls reach the sinks.
    """

    def __init__(
        self,
        task_id: str,
        sinks: list[EventSink] | None = None,
        *,
        storm_window_seconds: int = 60,
        dedupe_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.task_id = task_id
        self._sinks: list[EventSink] = list(sinks or [])
        self._storm_window = storm_window_seconds
        self._dedupe_seconds = dedupe_seconds
        self._clock = clock
        self._last_emit: dict[tuple[str, str], float] = {}
        self._info_buffer: dict[str, list[OrchestratorEvent]] = {}

    def add_sink(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    def emit(self, event: OrchestratorEvent) -> None:
        """Fan ``event`` to sinks with storm suppression + isolation.

        INFO events are buffered per issue and flushed as one summary on
        :meth:`flush` / terminal, except for lifecycle/control INFO events
        that must be visible immediately. Warn/error/success and immediate
        INFO events are deduped by ``(event_type, issue_id)``.
        """
        if event.level is EventLevel.INFO and event.event_type not in IMMEDIATE_INFO_EVENT_TYPES:
            self._info_buffer.setdefault(event.issue_id, []).append(event)
            return
        key = (event.event_type, event.issue_id)
        now = self._clock()
        last = self._last_emit.get(key)
        window = (
            self._storm_window
            if event.level in (EventLevel.WARN, EventLevel.ERROR)
            else self._dedupe_seconds
        )
        if last is not None and (now - last) < window:
            logger.debug("deduped event %s for %s", event.event_type, event.issue_id)
            return
        self._last_emit[key] = now
        self._dispatch(event)

    def flush(self, issue_id: str) -> None:
        """Dispatch buffered INFO events for ``issue_id`` as one summary."""
        buffered = self._info_buffer.pop(issue_id, [])
        if not buffered:
            return
        summary = OrchestratorEvent(
            event_type="info.summary",
            issue_id=issue_id,
            level=EventLevel.INFO,
            message=f"{len(buffered)} 个 info 事件: "
            + ", ".join(sorted({e.event_type for e in buffered})),
            payload={"count": len(buffered), "types": sorted({e.event_type for e in buffered})},
        )
        self._dispatch(summary)

    def _dispatch(self, event: OrchestratorEvent) -> None:
        for sink in list(self._sinks):
            try:
                sink(event)
            except Exception as exc:  # noqa: BLE001
                logger.exception("IM event sink failed for %r: %s", sink, exc)

    # -- ProgressSink ----------------------------------------------------
    def on_phase_complete(self, event: "PhaseComplete", session: Any) -> None:
        # Phase events are audit/LiveView only; not pushed to IM.
        return None

    def on_turn_complete(self, event: "TurnComplete", session: Any) -> None:
        # Turn events are audit/LiveView only; not pushed to IM.
        return None

    def on_session_complete(self, event: "SessionComplete", session: Any) -> None:
        reason = getattr(event, "reason", "") or ""
        issue_id = self.task_id or getattr(getattr(session, "issue", None), "id", "") or ""
        # flush buffered INFO events as one summary before the terminal event
        self.flush(issue_id)
        if reason in _STATUS_BRANCH_TERMINAL_REASONS:
            # The orchestrator's status dispatch emits the specific
            # ``agent.*`` terminal event; emitting a generic
            # ``issue.failed`` here would double-notify (different
            # event_type, not deduped).
            return
        level = TERMINAL_REASON_LEVEL.get(reason, EventLevel.WARN)
        if reason in _SUCCESS_TERMINAL_REASONS:
            event_type = "issue.completed"
            message = "任务完成"
        elif reason == "rate_limit_circuit_open":
            event_type = "agent.rate_limit_circuit_open"
            message = "限流熔断，会话终止"
        elif reason == "noop_completed":
            event_type = "issue.completed"
            message = "无操作完成"
            level = EventLevel.INFO
        else:
            event_type = "issue.failed"
            message = f"会话结束: {reason}"
        # Build a rich payload from the session context.
        payload: dict[str, Any] = {}
        issue = getattr(session, "issue", None)
        if issue is not None:
            pr = getattr(issue, "pr_url", None)
            if pr:
                payload["pr"] = pr
            title = getattr(issue, "title", None)
            if title:
                payload["title"] = title
            branch = getattr(issue, "branch_name", None)
            if branch:
                payload["branch"] = branch
        ver = getattr(session, "verification_status", None)
        if ver:
            payload["verification"] = ver
        turns = getattr(session, "turn_count", None)
        if turns:
            payload["turns"] = turns
        self.emit(
            OrchestratorEvent(
                event_type=event_type,
                issue_id=issue_id,
                level=level,
                message=message,
                payload=payload,
            )
        )


__all__ = ["EventSink", "OrchestratorEventEmitter"]

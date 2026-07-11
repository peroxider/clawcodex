"""FeishuActivitySink — translate agent lifecycle into Feishu-visible actions.

The orchestrator's :class:`ProgressSink` protocol gives us three hooks
(``on_phase_complete`` / ``on_turn_complete`` / ``on_session_complete``),
and :class:`StatusDashboard` fires ``on_session_start`` for global
lifecycle flips. This sink combines them to produce the two Feishu-side
visual signals we actually have (Feishu Open Platform has no bot_typing
push):

* On ``on_session_start`` — react to the inbound user message with the
  ``OnIt`` emoji (👀) and send a placeholder progress card back to the
  same chat. The card's ``message_id`` is cached so subsequent updates
  can target it.
* On every ``on_phase_complete`` — rebuild the placeholder card with the
  fresh phase progress and ``update_card`` it. Keeps the Feishu-side
  progress bar / header in lock-step with the agent runner.
* On ``on_session_complete`` — replace the 👀 reaction with the terminal
  emoji (``OK`` / ``Cross`` / ``Typing``) and rewrite the card title and
  header template to the terminal colour (green / red / grey).

All entry points are synchronous (matches the :class:`ProgressSink`
contract) but each Feishu API call is ``async`` — we hop onto the
adapter's main loop with :func:`asyncio.run_coroutine_threadsafe` and
swallow every exception. The sink *never* propagates errors back into
the agent runner; :class:`CompositeProgressSink` already isolates us,
but we also try/except inside this class so any direct caller is
safe.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable

from ..api.query import PhaseComplete, SessionComplete, TurnComplete
from ..capabilities.automation_state_protocol import (
    AutomationStateObserver,
    AutomationStateReporter,
)

if TYPE_CHECKING:
    from clawcodex_ext.services.channels.feishu_app import FeishuAppChannelAdapter

    from .agent_runner import AgentSession
    from .progress_sink import ProgressSink
    from .status_dashboard import SessionStatus, StatusDashboard

logger = logging.getLogger(__name__)


# Feishu message-reaction emoji_type constants (lark-oapi 1.7.0).
_REACTION_WORKING = "OnIt"      # 👀
_REACTION_OK = "OK"             # ✅
_REACTION_CROSS = "Cross"       # ❌
_REACTION_PAUSED = "Typing"     # ⏸ (no dedicated "paused" emoji)


# Terminal header colours used by the Feishu card template.
_HEADER_BLUE = "blue"
_HEADER_GREEN = "green"
_HEADER_RED = "red"
_HEADER_GREY = "grey"


def _schedule(adapter: Any, coro: Any) -> None:
    """Schedule ``coro`` on the adapter's main loop with full error isolation.

    Resolution order:

    1. If the adapter exposes ``_main_loop`` and we are *not* on it,
       :func:`asyncio.run_coroutine_threadsafe` hands the coroutine off.
    2. If we are already on a running loop (the agent runner calls us
       from a coroutine), ``create_task`` schedules a task on it.

    When there is no running loop at all (only happens in synchronous
    unit tests where the test driver invokes the sink from a ``def test_*``),
    the coroutine is added to :data:`_PENDING_TEST_COROS`. The unit-test
    helper :func:`_drain_pending_for_test` runs them on a fresh loop
    before assertions. In production this branch is unreachable — every
    :class:`ProgressSink` hook is dispatched from the agent runner's
    own coroutine, which is always on a running loop.

    Exceptions are logged and swallowed — the sink is best-effort.
    """
    loop = getattr(adapter, "_main_loop", None)
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    try:
        if loop is not None and loop is not running_loop:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            future.add_done_callback(_log_future_exception)
            return
        if running_loop is not None:
            running_loop.create_task(coro)
            return
        # No running loop. Stash for the test helper to drain. In
        # production this branch never fires.
        _PENDING_TEST_COROS.append(coro)
    except Exception as exc:  # noqa: BLE001
        logger.exception("feishu activity sink schedule failed: %s", exc)


_PENDING_TEST_COROS: list[Any] = []


def drain_pending_for_test() -> None:
    """Run any coroutines the sink scheduled off-loop (test-only helper)."""
    if not _PENDING_TEST_COROS:
        return
    # Pop the pending list before draining — do NOT use chained
    # ``pending, _PENDING_TEST_COROS[:] = _PENDING_TEST_COROS, []``
    # because the slice-assignment rebinds the *same* list object in
    # place, so ``pending`` would also be empty.
    pending = list(_PENDING_TEST_COROS)
    _PENDING_TEST_COROS.clear()
    loop = asyncio.new_event_loop()
    try:
        for coro in pending:
            try:
                loop.run_until_complete(coro)
            except Exception as exc:  # noqa: BLE001
                logger.debug("test drain: coroutine raised %s", exc)
    finally:
        loop.close()


def _log_future_exception(future: "asyncio.Future[Any]") -> None:
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        logger.exception("feishu activity sink coroutine raised: %s", exc)


class FeishuActivitySink:
    """Translate agent lifecycle into Feishu reactions + card updates.

    Conforms to three contracts:

    * :class:`ProgressSink` — synchronous protocol; AgentRunner dispatches
      ``on_phase_complete / on_turn_complete / on_session_complete`` into
      this sink via :class:`CompositeProgressSink`.
    * :class:`AutomationStateObserver` — push-protocol; this sink also
      implements ``on_automation_state`` so any caller (typically the
      orchestrator at session-start time) can drive the 👀-reaction
      phase explicitly.
    * :class:`AutomationStateReporter` — pull-protocol via
      :meth:`automation_state` for health checks / future dashboards.

    The :class:`StatusDashboard` has no generic subscribe() method — the
    orchestrator drives this sink via ``orchestrator.notify_session_start``
    which simply forwards a synthetic snapshot into :meth:`on_automation_state`.
    """

    task_id: str

    def __init__(
        self,
        *,
        task_id: str,
        feishu_adapter: "FeishuAppChannelAdapter",
        clock: Callable[[], float],
        status_dashboard: "StatusDashboard | None" = None,
        phases_total: int | None = None,
    ) -> None:
        self.task_id = task_id
        self._adapter = feishu_adapter
        self._clock = clock
        self._remove_session_listener: Callable[[], None] | None = None
        # ``workflow_phases`` is optional — when configured we can show
        # honest "phase 2/4" labels; otherwise we fall back to "phase N".
        self._phases_total = phases_total
        self._last_phase: int = 0
        self._last_emitted_at: float | None = None
        # Subscribe to the dashboard's session-start so users see 👀 on
        # their inbound message the moment work begins.
        if status_dashboard is not None:
            self._remove_session_listener = (
                status_dashboard.add_session_start_listener(self._on_session_status)
            )

    # ------------------------------------------------------------------
    # Explicit entry point — driven by orchestrator on session start
    # ------------------------------------------------------------------

    def _on_session_status(self, status: "SessionStatus") -> None:
        """Listener wired by ``StatusDashboard.add_session_start_listener``.

        Filters to ``task_id`` so multiple sessions in flight do not
        trigger each other's reactions.
        """
        if status.issue_id != self.task_id:
            return
        self.notify_session_start(
            issue_id=status.issue_id,
            issue_identifier=status.issue_identifier,
        )

    def notify_session_start(
        self,
        issue_id: str,
        issue_identifier: str = "",
    ) -> None:
        """React to inbound + send placeholder card.

        Called by the session-start listener (or by any direct caller).
        Errors are isolated inside :func:`_schedule`; this method never
        raises.
        """
        message_id = self._adapter._last_inbound_message_id  # type: ignore[attr-defined]
        chat_id = self._adapter._last_inbound_chat_id  # type: ignore[attr-defined]
        if not message_id or not chat_id:
            # No inbound context cached yet — usually because the agent
            # was launched out-of-band (e.g. via CLI). Soft skip.
            return
        self._last_emitted_at = self._clock()
        card = _build_card(
            title="⏳ ClawCodex 正在处理",
            header_template=_HEADER_BLUE,
            progress=0,
            summary=(
                f"已收到任务 {issue_identifier or issue_id}, "
                f"phase 1/{self._phases_total or '?'}"
            ).strip(),
        )
        _schedule(
            self._adapter,
            self._emit_session_start(message_id, chat_id, card),
        )

    # ------------------------------------------------------------------
    # AutomationStateObserver (push)
    # ------------------------------------------------------------------

    def on_automation_state(self, snapshot: dict[str, Any]) -> None:
        event = snapshot.get("event")
        if event == "session_start":
            self.notify_session_start(
                issue_id=str(snapshot.get("issue_id") or ""),
                issue_identifier=str(snapshot.get("issue_identifier") or ""),
            )

    async def _emit_session_start(
        self,
        message_id: str,
        chat_id: str,
        card: dict,
    ) -> None:
        try:
            await self._adapter.set_reaction(message_id, _REACTION_WORKING)
            placeholder_id = await self._adapter.send_placeholder_card(chat_id, card)
            if placeholder_id:
                self._adapter.remember_placeholder_message_id(self.task_id, placeholder_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "feishu activity sink session_start dispatch failed: %s", exc
            )

    # ------------------------------------------------------------------
    # ProgressSink (synchronous dispatch from AgentRunner)
    # ------------------------------------------------------------------

    def on_phase_complete(
        self,
        event: PhaseComplete,
        session: "AgentSession",
    ) -> None:
        placeholder_id = self._adapter.placeholder_message_id(self.task_id)
        if not placeholder_id:
            return
        phase_idx = event.phase or 0
        self._last_phase = phase_idx
        self._last_emitted_at = self._clock()
        progress = _phase_progress(phase_idx, self._phases_total)
        card = _build_card(
            title=f"⏳ ClawCodex Phase {phase_idx}",
            header_template=_HEADER_BLUE,
            progress=progress,
            summary=_phase_summary(session, phase_idx, self._phases_total),
        )
        _schedule(self._adapter, self._adapter.update_progress_card(placeholder_id, card))

    def on_turn_complete(
        self,
        event: TurnComplete,
        session: "AgentSession",
    ) -> None:
        # Turn events are too noisy for visible UI updates (mirrors
        # :class:`ToolContextProgressSink.on_turn_complete` which also
        # no-ops). Debug log only.
        logger.debug(
            "feishu activity sink turn %d complete for task %s",
            event.turn,
            self.task_id,
        )

    def on_session_complete(
        self,
        event: SessionComplete,
        session: "AgentSession",
    ) -> None:
        message_id = self._adapter._last_inbound_message_id  # type: ignore[attr-defined]
        placeholder_id = self._adapter.placeholder_message_id(self.task_id)
        reaction, header, title, progress = _terminal_visuals(event.reason)
        # The card might never have been emitted (CLI-launched session);
        # ``update_progress_card`` returns False silently in that case.
        if placeholder_id:
            card = _build_card(
                title=title,
                header_template=header,
                progress=progress,
                summary=f"session: {event.reason}",
            )
            _schedule(self._adapter, self._adapter.update_progress_card(placeholder_id, card))
        if message_id:
            _schedule(
                self._adapter,
                self._emit_terminal_reaction(message_id, reaction),
            )
        # Drop cached placeholder so a re-run can claim a fresh card.
        self._adapter.forget_placeholder_message_id(self.task_id)
        self._last_emitted_at = self._clock()

    async def _emit_terminal_reaction(self, message_id: str, emoji_type: str) -> None:
        try:
            await self._adapter.set_reaction(message_id, emoji_type)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "feishu activity sink terminal reaction failed: %s", exc
            )

    # ------------------------------------------------------------------
    # AutomationStateReporter (pull)
    # ------------------------------------------------------------------

    def automation_state(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "last_phase": self._last_phase,
            "last_emitted_at": self._last_emitted_at,
            "placeholder_message_id": self._adapter.placeholder_message_id(self.task_id)
            if self._adapter
            else None,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _phase_progress(phase: int, phases_total: int | None) -> int:
    """Mirror :class:`ToolContextProgressSink._phase_progress` semantics."""
    if phase <= 0:
        return 0
    if phases_total and phases_total > 0:
        return max(0, min(100, int(phase / phases_total * 100)))
    # No configured total — fall back to the F-38 era 25/50/75/100 cadence
    # so the user still sees movement.
    return min(phase * 25, 100)


def _phase_summary(
    session: "AgentSession",
    phase: int,
    phases_total: int | None,
) -> str:
    issue_id = getattr(getattr(session, "issue", None), "identifier", "") or ""
    total = phases_total if phases_total and phases_total > 0 else "?"
    issue_part = f"{issue_id} " if issue_id else ""
    return f"{issue_part}phase {phase}/{total}"


def _terminal_visuals(reason: str) -> tuple[str, str, str, int | None]:
    """Map a :class:`SessionComplete.reason` to (reaction, header, title, progress)."""
    if reason == "success":
        return _REACTION_OK, _HEADER_GREEN, "✅ 已完成", 100
    if reason == "paused":
        return _REACTION_PAUSED, _HEADER_GREY, "⏸ 已暂停", None
    # Everything else (stagnation / loop_detected / max_turns_exceeded /
    # rate_limit_circuit_open / exit_code=N / noop_completed / failed /
    # budget_exhausted …) is a failure for visual purposes.
    return _REACTION_CROSS, _HEADER_RED, f"❌ 失败: {reason}", None


def _build_card(
    *,
    title: str,
    header_template: str,
    progress: int | None,
    summary: str,
) -> dict:
    """Build a Feishu interactive card payload.

    Mirrors the existing ``feishu_cards.build_permission_card`` shape so
    the resulting JSON matches what the SDK schema expects.
    """
    elements: list[dict] = []
    if summary:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": summary},
            }
        )
    if progress is not None:
        elements.append(
            {
                "tag": "progress",
                "percent": max(0, min(100, progress)),
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


# Protocol satisfaction at import time (helps the type checker + Stage 1 imports).
def __build_sink_protocol_satisfaction() -> type["ProgressSink"]:
    from .progress_sink import ProgressSink

    return ProgressSink


__all__ = ["FeishuActivitySink"]

"""Unit tests for the Feishu activity sink (Activity visibility).

Processing reactions are owned by the IM gateway. This sink translates
orchestrator lifecycle events into progress updates to a placeholder card.

These tests exercise the translation layer in isolation, mocking both
the :class:`FeishuAppChannelAdapter` and the asynchronous coroutines
the sink schedules.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from extensions.api.query import PhaseComplete, SessionComplete, TurnComplete
from extensions.orchestrator.feishu_activity_sink import (
    FeishuActivitySink,
    drain_pending_for_test,
)
from extensions.orchestrator.status_dashboard import SessionStatus
from clawcodex_ext.services.channels.capabilities import (
    ChannelCapability,
    ChannelCapabilitySet,
    InboundActivityContext,
)


# ---------------------------------------------------------------------------
# Fake adapter / dashboard helpers
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Drop-in replacement for :class:`FeishuAppChannelAdapter` for tests.

    Records every call so the assertions can introspect the order and
    arguments; returns ``None`` / ``True`` for the success path.
    """

    def __init__(self) -> None:
        self.channel_id = "feishu"
        self.capabilities = ChannelCapabilitySet.of(ChannelCapability.CARD_UPDATE)
        self.calls: list[tuple[str, tuple, dict]] = []
        self.inbound_context: InboundActivityContext | None = InboundActivityContext(
            message_id="om_inbound_001",
            chat_id="oc_chat_001",
        )
        self.placeholder_result = "om_placeholder_001"

    def last_inbound_context(self) -> InboundActivityContext | None:
        return self.inbound_context

    async def set_reaction(self, message_id: str, emoji_type: str, *, remove: bool = False) -> bool:
        self.calls.append(("set_reaction", (message_id, emoji_type), {"remove": remove}))
        return True

    async def update_progress_card(self, message_id: str, card: dict) -> bool:
        self.calls.append(("update_progress_card", (message_id,), {"card": card}))
        return True

    async def send_placeholder_card(self, chat_id: str, card: dict) -> str | None:
        self.calls.append(("send_placeholder_card", (chat_id,), {"card": card}))
        return self.placeholder_result


class _FakeDashboard:
    """Drop-in replacement for :class:`StatusDashboard` with listener API."""

    def __init__(self) -> None:
        self.listeners: list = []

    def add_session_start_listener(self, listener):
        self.listeners.append(listener)

        def _remove():
            try:
                self.listeners.remove(listener)
            except ValueError:
                pass

        return _remove


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class FeishuActivitySinkSessionStartTests(unittest.TestCase):
    """``notify_session_start`` triggers the placeholder card only."""

    def test_session_start_emits_reaction_and_placeholder(self) -> None:
        adapter = _FakeAdapter()
        dashboard = _FakeDashboard()
        sink = FeishuActivitySink(
            task_id="ISSUE-1",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
            status_dashboard=dashboard,  # type: ignore[arg-type]
            phases_total=4,
        )
        try:
            sink.notify_session_start(issue_id="ISSUE-1", issue_identifier="ISSUE-1 title")

            drain_pending_for_test()

            kinds = [c[0] for c in adapter.calls]
            self.assertEqual(
                kinds,
                ["send_placeholder_card"],
            )
            send_call = adapter.calls[0]
            placeholder_card = send_call[2]["card"]
            self.assertIn("header", placeholder_card)
            self.assertEqual(placeholder_card["header"]["template"], "blue")
            self.assertIn("phase 1", placeholder_card["elements"][0]["text"]["content"])
        finally:
            pass

    def test_session_start_noop_when_inbound_context_missing(self) -> None:
        adapter = _FakeAdapter()
        adapter.inbound_context = None
        sink = FeishuActivitySink(
            task_id="ISSUE-2",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )

        sink.notify_session_start(issue_id="ISSUE-2")
        drain_pending_for_test()

        self.assertEqual(adapter.calls, [])

    def test_session_start_filter_by_task_id(self) -> None:
        """Listeners must not trigger on mismatched task ids."""
        adapter = _FakeAdapter()
        dashboard = _FakeDashboard()
        sink = FeishuActivitySink(
            task_id="ISSUE-3",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
            status_dashboard=dashboard,  # type: ignore[arg-type]
        )
        # Directly invoke the listener path with a non-matching issue_id
        # (simulates ``StatusDashboard`` firing for a different session).
        sink._on_session_status(SessionStatus(issue_id="other-task", issue_identifier="other"))
        drain_pending_for_test()
        self.assertEqual(adapter.calls, [])


class FeishuActivitySinkProgressTests(unittest.TestCase):
    """``on_phase_complete`` rewrites the placeholder card with fresh progress."""

    def test_phase_complete_updates_placeholder_card(self) -> None:
        adapter = _FakeAdapter()
        sink = FeishuActivitySink(
            task_id="ISSUE-4",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 2.0,
            phases_total=4,
        )
        sink.notify_session_start(issue_id="ISSUE-4")
        drain_pending_for_test()
        session = _make_session_stub(identifier="ISSUE-4")
        sink.on_phase_complete(
            PhaseComplete(phase=2, turn_count=2),
            session,
        )
        drain_pending_for_test()

        update_calls = [c for c in adapter.calls if c[0] == "update_progress_card"]
        self.assertEqual(len(update_calls), 1)
        _op, args, kwargs = update_calls[0]
        self.assertEqual(args, ("om_placeholder_001",))
        card = kwargs["card"]
        # Progress for phase 2/4 should be 50%.
        progress_elements = [el for el in card["elements"] if el.get("tag") == "progress"]
        self.assertEqual(progress_elements[0]["percent"], 50)

    def test_phase_complete_noop_when_placeholder_missing(self) -> None:
        adapter = _FakeAdapter()
        sink = FeishuActivitySink(
            task_id="ISSUE-5",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        sink.on_phase_complete(PhaseComplete(phase=1, turn_count=1), _make_session_stub())
        drain_pending_for_test()
        self.assertEqual(adapter.calls, [])


class FeishuActivitySinkTerminalTests(unittest.TestCase):
    """``on_session_complete`` maps reasons to the terminal card template."""

    def _assert_terminal(
        self,
        reason: str,
        *,
        header: str,
        title_substring: str,
    ) -> None:
        adapter = _FakeAdapter()
        adapter.placeholder_result = "om_placeholder_006"
        sink = FeishuActivitySink(
            task_id="ISSUE-6",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        sink.notify_session_start(issue_id="ISSUE-6")
        drain_pending_for_test()
        sink.on_session_complete(SessionComplete(reason=reason), _make_session_stub())
        drain_pending_for_test()
        reactions = [c for c in adapter.calls if c[0] == "set_reaction"]
        self.assertEqual(reactions, [])
        updates = [c for c in adapter.calls if c[0] == "update_progress_card"]
        self.assertEqual(len(updates), 1)
        card = updates[0][2]["card"]
        self.assertEqual(card["header"]["template"], header)
        self.assertIn(title_substring, card["header"]["title"]["content"])

    def test_success_terminal(self) -> None:
        self._assert_terminal(
            "success",
            header="green",
            title_substring="已完成",
        )

    def test_paused_terminal(self) -> None:
        self._assert_terminal(
            "paused",
            header="grey",
            title_substring="暂停",
        )

    def test_failure_terminal(self) -> None:
        self._assert_terminal(
            "stagnation",
            header="red",
            title_substring="失败",
        )

    def test_session_complete_clears_placeholder(self) -> None:
        adapter = _FakeAdapter()
        adapter.placeholder_result = "om_placeholder_007"
        sink = FeishuActivitySink(
            task_id="ISSUE-7",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        sink.notify_session_start(issue_id="ISSUE-7")
        drain_pending_for_test()
        sink.on_session_complete(
            SessionComplete(reason="success"),
            _make_session_stub(),
        )
        drain_pending_for_test()
        self.assertIsNone(sink.automation_state()["placeholder_message_id"])

    def test_session_complete_without_placeholder_does_not_react(self) -> None:
        adapter = _FakeAdapter()
        sink = FeishuActivitySink(
            task_id="ISSUE-8",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        sink.on_session_complete(
            SessionComplete(reason="success"),
            _make_session_stub(),
        )
        drain_pending_for_test()
        reactions = [c for c in adapter.calls if c[0] == "set_reaction"]
        self.assertEqual(reactions, [])


class FeishuActivitySinkExceptionIsolationTests(unittest.TestCase):
    """Adapter failures must never propagate into the sink's callers."""

    def test_adapter_card_failure_does_not_raise(self) -> None:
        adapter = _FakeAdapter()

        # Patch the async method to raise.
        async def _boom(*a, **kw):
            raise RuntimeError("sdk blew up")

        adapter.send_placeholder_card = _boom  # type: ignore[assignment]
        sink = FeishuActivitySink(
            task_id="ISSUE-9",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        # No exception should escape ``notify_session_start``.
        sink.notify_session_start(issue_id="ISSUE-9")
        drain_pending_for_test()


class FeishuActivitySinkStateReportTests(unittest.TestCase):
    """``automation_state`` (pull) returns the sink's bookkeeping snapshot."""

    def test_automation_state_snapshot(self) -> None:
        adapter = _FakeAdapter()
        adapter.placeholder_result = "om_placeholder_010"
        sink = FeishuActivitySink(
            task_id="ISSUE-10",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 5.0,
        )
        sink.notify_session_start(issue_id="ISSUE-10")
        drain_pending_for_test()
        sink.on_phase_complete(
            PhaseComplete(phase=3, turn_count=3),
            _make_session_stub(identifier="ISSUE-10"),
        )
        snapshot = sink.automation_state()
        self.assertEqual(snapshot["task_id"], "ISSUE-10")
        self.assertEqual(snapshot["last_phase"], 3)
        self.assertEqual(snapshot["placeholder_message_id"], "om_placeholder_010")
        # clock() was invoked by _schedule paths and on_phase_complete itself
        self.assertEqual(snapshot["last_emitted_at"], 5.0)


class FeishuActivitySinkTurnTests(unittest.TestCase):
    """``on_turn_complete`` is a no-op (mirrors ToolContextProgressSink)."""

    def test_turn_complete_is_silent(self) -> None:
        adapter = _FakeAdapter()
        sink = FeishuActivitySink(
            task_id="ISSUE-11",
            feishu_adapter=adapter,  # type: ignore[arg-type]
            clock=lambda: 1.0,
        )
        sink.on_turn_complete(TurnComplete(turn=7), _make_session_stub())
        drain_pending_for_test()
        self.assertEqual(adapter.calls, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_stub(identifier: str = "ISSUE") -> Any:
    """Build a namespace the sink can read without a full AgentSession."""

    issue = MagicMock()
    issue.identifier = identifier
    session = MagicMock()
    session.issue = issue
    return session


if __name__ == "__main__":
    unittest.main()

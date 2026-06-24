"""Tests for the Session WebSocket compatibility and change channels."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from extensions.visualizer.ws import SessionLiveTail


def _ts(offset: float = 0.0) -> float:
    return 1_787_000_000.0 + offset


class TestEntryToBarUpdate:
    def test_tool_use_emits_running_bar(self):
        tail = SessionLiveTail("s1")
        entry = {
            "role": "assistant",
            "timestamp": _ts(0),
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "tool_use_id": "toolu_abc",
                    "input": {"command": "ls"},
                }
            ],
        }
        ev = tail._entry_to_bar_update(entry, emit_ts=_ts(0))
        assert ev is not None
        assert ev["type"] == "bar_update"
        assert ev["session_id"] == "s1"
        bar = ev["bar"]
        assert bar["id"] == "toolu_abc"
        assert bar["tool_name"] == "Bash"
        assert bar["label"] == "Bash"
        assert bar["start_time"] == _ts(0)
        assert bar["end_time"] == _ts(0)
        assert bar["status"] == "running"
        assert bar["category"] == "execute"
        # Bash → #ee6666 (from _TOOL_COLORS palette)
        assert bar["color"] == "#ee6666"

    def test_tool_result_updates_pending_bar_to_success(self):
        tail = SessionLiveTail("s1")
        # First the tool_use registers the pending bar.
        tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "tool_use_id": "toolu_xyz",
                        "input": {},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        # Then the matching tool_result mutates it.
        ev = tail._entry_to_bar_update(
            {
                "role": "user",
                "timestamp": _ts(2),
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_xyz",
                        "content": "ok",
                        "is_error": False,
                    }
                ],
            },
            emit_ts=_ts(2),
        )
        assert ev is not None
        bar = ev["bar"]
        assert bar["id"] == "toolu_xyz"
        assert bar["end_time"] == _ts(2)
        assert bar["status"] == "success"

    def test_tool_result_error_sets_status_error(self):
        tail = SessionLiveTail("s1")
        tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "tool_use_id": "toolu_err",
                        "input": {},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        ev = tail._entry_to_bar_update(
            {
                "role": "user",
                "timestamp": _ts(1),
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_err",
                        "content": "permission denied",
                        "is_error": True,
                    }
                ],
            },
            emit_ts=_ts(1),
        )
        assert ev["bar"]["status"] == "error"

    def test_orphan_tool_result_synthesizes_bar(self):
        """A tool_result with no matching tool_use still emits a bar so
        the client can show it; without this, late results would be
        silently dropped on the live channel."""
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "user",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_orphan",
                        "content": "ok",
                        "is_error": False,
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        assert ev is not None
        assert ev["bar"]["id"] == "toolu_orphan"
        assert ev["bar"]["status"] == "success"
        assert ev["bar"]["label"] == "result"

    def test_text_block_returns_none(self):
        """Text blocks don't produce bars — only tool_use/tool_result do."""
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [{"type": "text", "text": "thinking…"}],
            },
            emit_ts=_ts(0),
        )
        assert ev is None

    def test_system_role_returns_none(self):
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "system",
                "timestamp": _ts(0),
                "content": [{"type": "tool_use", "name": "Bash", "tool_use_id": "t1", "input": {}}],
            },
            emit_ts=_ts(0),
        )
        assert ev is None

    def test_agent_tool_use_classified_as_orchestrate(self):
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "tool_use_id": "toolu_orch",
                        "input": {"subagent_type": "review"},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        assert ev is not None
        assert ev["bar"]["category"] == "orchestrate"
        # Agent isn't in the _TOOL_COLORS palette, so we fall back to the
        # OperationCategory.ORCHESTRATE color (pink, matches the fork curves).
        assert ev["bar"]["color"] == "#f778ba"

    def test_is_agent_invocation_flag_overrides_tool_name(self):
        """Even if a tool isn't in the ORCHESTRATE rule set, an explicit
        ``isAgentInvocation`` flag from upstream parsers marks the bar
        as orchestration. (Defends against future Agent-like tools.)"""
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_use",
                        "name": "CustomDispatcher",
                        "tool_use_id": "toolu_d",
                        "isAgentInvocation": True,
                        "input": {},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        assert ev["bar"]["category"] == "orchestrate"

    def test_unknown_tool_name_lands_in_other(self):
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {
                        "type": "tool_use",
                        "name": "MyWeirdTool",
                        "tool_use_id": "toolu_w",
                        "input": {},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        assert ev["bar"]["category"] == "other"
        # No matching palette entry → OperationCategory.OTHER color.
        assert ev["bar"]["color"] == "#6e7681"

    def test_iso8601_timestamp_is_coerced_to_float(self):
        """Timestamps in the entry are coerced with the same rules as
        the static parser — ISO 8601 strings are converted to epoch
        floats so the client gets a uniform numeric x coordinate."""
        tail = SessionLiveTail("s1")
        ev = tail._entry_to_bar_update(
            {
                "role": "assistant",
                # 2024-06-04T12:00:00Z  →  1717502400.0 (real epoch, not a guess)
                "timestamp": "2024-06-04T12:00:00Z",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "tool_use_id": "toolu_iso",
                        "input": {},
                    }
                ],
            },
            emit_ts=_ts(0),
        )
        assert ev["bar"]["start_time"] > 0
        # Should match the well-known epoch within 1 second.
        assert abs(ev["bar"]["start_time"] - 1717502400.0) < 1.0

    def test_pending_tools_cleared_after_match(self):
        """A tool_result pops its pending entry so the next call sees
        a clean state — guards against a malformed replay that would
        otherwise re-trigger the same update."""
        tail = SessionLiveTail("s1")
        tail._entry_to_bar_update(
            {
                "role": "assistant",
                "timestamp": _ts(0),
                "content": [
                    {"type": "tool_use", "name": "Bash", "tool_use_id": "toolu_t", "input": {}}
                ],
            },
            emit_ts=_ts(0),
        )
        assert "toolu_t" in tail._pending_tools
        tail._entry_to_bar_update(
            {
                "role": "user",
                "timestamp": _ts(1),
                "content": [{"type": "tool_result", "tool_use_id": "toolu_t", "content": "ok"}],
            },
            emit_ts=_ts(1),
        )
        assert "toolu_t" not in tail._pending_tools


@pytest.mark.asyncio
async def test_session_json_change_emits_refetch_notification(tmp_path):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"conversation": {"messages": []}}), encoding="utf-8")
    tail = SessionLiveTail("single-file", path)
    events = []

    async def capture(event):
        events.append(event)

    tail.broadcast = capture
    task = asyncio.create_task(tail.tail_loop(interval=0.01))
    await asyncio.sleep(0.03)
    path.write_text(
        json.dumps({"conversation": {"messages": [{"role": "user"}]}}), encoding="utf-8"
    )
    await asyncio.sleep(0.05)
    tail.stop()
    await task

    assert any(
        event.get("type") == "transcript_event"
        and event.get("source") == "session.json"
        and event.get("changed") is True
        for event in events
    )


def test_websocket_endpoint_accepts_urlencoded_session_id(tmp_path):
    from extensions.visualizer.server import create_app

    sessions = tmp_path / "sessions"
    session_dir = sessions / "session with #hash"
    session_dir.mkdir(parents=True)
    (session_dir / "transcript.jsonl").write_text(
        json.dumps({"role": "user", "content": "hello", "timestamp": _ts()}),
        encoding="utf-8",
    )
    app = create_app(sessions_dir=sessions, allow_import=False)
    client = TestClient(app)

    with client.websocket_connect("/api/viz/ws/sessions/session%20with%20%23hash") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"

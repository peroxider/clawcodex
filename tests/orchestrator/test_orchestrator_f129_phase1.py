"""Phase 1 tests: socket persistence + event broadcasting.

Covers:
  * ``_event_to_broadcast_dict`` handles PhaseComplete / TurnComplete /
    SessionComplete (new in Phase 1).
  * ``_broadcast_to_socket`` helper sends events to connected clients
    and is a no-op when no socket is attached.

Uses ``unittest.IsolatedAsyncioTestCase`` (the repo's canonical async
test pattern) and ``tempfile.TemporaryDirectory`` for isolation.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from extensions.orchestrator.agent_runner import AgentRunner


# ------------------------------------------------------------------
# _event_to_broadcast_dict — new event types
# ------------------------------------------------------------------


class TestEventToBroadcastDict(unittest.TestCase):
    """Phase 1: PhaseComplete / TurnComplete / SessionComplete branches."""

    def test_phase_complete(self) -> None:
        from extensions.api.query import PhaseComplete

        d = AgentRunner._event_to_broadcast_dict(PhaseComplete(phase=3, turn_count=3))
        self.assertEqual(d, {"phase": 3, "turn_count": 3})

    def test_turn_complete(self) -> None:
        from extensions.api.query import TurnComplete

        d = AgentRunner._event_to_broadcast_dict(TurnComplete(turn=5))
        self.assertEqual(d, {"turn": 5})

    def test_session_complete(self) -> None:
        from extensions.api.query import SessionComplete

        d = AgentRunner._event_to_broadcast_dict(SessionComplete(reason="task_complete"))
        self.assertEqual(d, {"reason": "task_complete"})

    def test_unknown_event_returns_empty(self) -> None:
        d = AgentRunner._event_to_broadcast_dict(object())
        self.assertEqual(d, {})


# ------------------------------------------------------------------
# _broadcast_to_socket — async helper
# ------------------------------------------------------------------


class TestBroadcastToSocket(unittest.IsolatedAsyncioTestCase):
    """Phase 1: _broadcast_to_socket sends to connected clients."""

    async def test_broadcast_no_socket_is_noop(self) -> None:
        """Broadcasting with control_socket=None must not raise."""
        from extensions.orchestrator.agent_runner import AgentSession
        from extensions.orchestrator.issue import Issue
        from extensions.orchestrator.workspace import Workspace

        session = AgentSession(
            issue=Issue(id="I", identifier="I", title="t"),
            workspace=Workspace(path="/tmp", issue_identifier="I", issue_id="I"),
        )
        # control_socket is None by default
        from extensions.api.query import PhaseComplete

        await AgentRunner._broadcast_to_socket(session, PhaseComplete(phase=1, turn_count=1))

    async def test_broadcast_sends_to_connected_client(self) -> None:
        """A connected client receives the broadcast frame."""
        from extensions.orchestrator.agent_runner import AgentSession
        from extensions.orchestrator.control_socket import ControlSocket, send_cmd  # noqa: F401
        from extensions.orchestrator.issue import Issue
        from extensions.orchestrator.workspace import Workspace
        from extensions.api.query import PhaseComplete

        with TemporaryDirectory() as tmp:
            ws_path = Path(tmp) / "ws"
            ws_path.mkdir()
            sock_path = ws_path / ".run_control" / "test.sock"
            cs = ControlSocket(sock_path)
            await cs.start()
            try:
                session = AgentSession(
                    issue=Issue(id="I", identifier="I", title="t"),
                    workspace=Workspace(path=str(ws_path), issue_identifier="I", issue_id="I"),
                    run_id="run-1",
                )
                session.control_socket = cs

                reader, writer = await asyncio.open_unix_connection(str(sock_path))
                try:
                    await asyncio.sleep(0.05)  # let server accept
                    await AgentRunner._broadcast_to_socket(
                        session,
                        PhaseComplete(phase=2, turn_count=2),
                    )
                    line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                    payload = json.loads(line.decode("utf-8"))
                    self.assertEqual(payload["type"], "PhaseComplete")
                    self.assertEqual(payload["data"], {"phase": 2, "turn_count": 2})
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
            finally:
                await cs.stop()


if __name__ == "__main__":
    unittest.main()

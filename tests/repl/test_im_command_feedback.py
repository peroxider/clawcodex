from __future__ import annotations

from unittest.mock import Mock

from src.repl import ClawcodexREPL


def _make_clear_repl() -> ClawcodexREPL:
    repl = ClawcodexREPL.__new__(ClawcodexREPL)
    repl._built_in_commands = ["/clear"]
    repl._try_execute_new_command = Mock(side_effect=RuntimeError("fallback"))
    repl._run_command_async_with_status = Mock(side_effect=RuntimeError("fallback"))
    repl.command_registry = Mock()
    repl.command_registry.get.return_value = None
    repl.console = Mock()
    repl.session = Mock()
    repl.session.conversation = Mock()
    repl._engine_messages = ["old"]
    return repl


def test_handle_command_clear_sends_im_command_feedback() -> None:
    """IM-driven /clear should get a visible command completion notice."""
    repl = _make_clear_repl()
    calls: list[str] = []

    class _FakeImReply:
        def send_command_feedback(self, command: str) -> bool:
            calls.append(command)
            return True

    repl._im_reply_controller = _FakeImReply()

    repl.handle_command("/clear")

    assert calls == ["/clear"]

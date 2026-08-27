from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from clawcodex_ext.frontend.repl import REPLFrontend
from clawcodex_ext.frontend.tui import TUIFrontend


def _runtime_context() -> MagicMock:
    context = MagicMock()
    context.provider_name = "test"
    context.provider = MagicMock()
    context.session = MagicMock()
    context.tool_registry = MagicMock()
    context.tool_context = MagicMock()
    context.workspace_root = Path.cwd()
    context.options = SimpleNamespace(
        model="test-model",
        max_turns=5,
        allowed_tools=(),
        disallowed_tools=(),
        stream=False,
        permission_mode="default",
        is_bypass_permissions_mode_available=False,
        append_system_prompt="",
        resume_session_id=None,
        resume_browse=False,
    )
    return context


class TestPassiveMemoryFrontendShutdown(unittest.TestCase):
    def test_repl_closes_runtime_context(self) -> None:
        context = _runtime_context()

        with (
            patch("clawcodex_ext.repl.app.ClawCodexExtREPL") as repl_class,
            patch("clawcodex_ext.frontend.repl_extensions.install_repl_extensions"),
            patch("extensions.recording.repl_source.install_repl_capture"),
        ):
            result = REPLFrontend().run(context, [])

        self.assertEqual(result, 0)
        repl_class.return_value.run.assert_called_once()
        context.close.assert_called_once()

    def test_tui_closes_runtime_context(self) -> None:
        context = _runtime_context()

        entrypoint = ModuleType("clawcodex_ext.tui.entrypoint")
        run_tui = MagicMock(return_value=7)
        entrypoint.run_tui = run_tui
        with patch.dict(sys.modules, {"clawcodex_ext.tui.entrypoint": entrypoint}):
            result = TUIFrontend().run(context, [])

        self.assertEqual(result, 7)
        run_tui.assert_called_once()
        context.close.assert_called_once()

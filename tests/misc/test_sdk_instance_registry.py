"""Tests for session-scoped SDK wrapper in-process execution (Plan A)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clawcodex_ext.agent.sdk_instance_registry import reset_sdk_instance_registry
from clawcodex_ext.agent.sdk_context_registry import reset_sdk_context_registry
from clawcodex_ext.agent.tool_authoring.call_handlers import sdk_wrapper
from clawcodex_ext.agent.tool_authoring.factory import build_tool_from_spec
from clawcodex_ext.agent.tool_authoring.spec import AgentToolSpec
from clawcodex_ext.tool_system.context import ToolContext
from extensions.sop_converter.source_parser import SourceCodeParser
from extensions.sop_converter.tool_registry_bridge import (
    _generate_wrapper_script,
    operation_to_spec,
)


class CounterSource:
    SOURCE = '''
class Counter:
    def __init__(self) -> None:
        self._value = 0

    @property
    def value(self) -> int:
        """Current counter value."""
        return self._value

    def bump(self) -> None:
        """Increment the counter."""
        self._value += 1
'''


class TestSdkWrapperParsing(unittest.TestCase):
    def test_parse_wrapper_call_impl(self) -> None:
        parsed = sdk_wrapper.parse_sdk_wrapper_call_impl(
            'python3 "/tmp/wrapper.py" bump \'{json_args}\''
        )
        self.assertEqual(parsed, (Path("/tmp/wrapper.py"), "bump"))


class TestSdkInstanceRegistryCrossCall(unittest.TestCase):
    def setUp(self) -> None:
        reset_sdk_instance_registry()
        reset_sdk_context_registry()
        sdk_wrapper._MODULE_CACHE.clear()
        sdk_wrapper._SCRIPT_USES_INSTANCE_CACHE.clear()

    def _build_counter_tools(self, tmp: Path) -> tuple[Path, object, object]:
        pkg = tmp / "demo_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "counter.py").write_text(CounterSource.SOURCE)

        parser = SourceCodeParser(tmp)
        components = parser.parse()
        ops = components[0].operations

        script_path = _generate_wrapper_script(
            ops,
            class_name="Counter",
            module_name="demo_pkg.counter",
            file_stem="counter",
            source_dir=str(tmp),
        )

        bump_spec = operation_to_spec(
            next(op for op in ops if op.name == "bump"),
            source_dir=str(tmp),
            script_path=str(script_path),
            comp_name="demo",
        )
        value_spec = operation_to_spec(
            next(op for op in ops if op.name == "value"),
            source_dir=str(tmp),
            script_path=str(script_path),
            comp_name="demo",
        )
        self.assertTrue(bump_spec.stateful_wrapper)
        self.assertTrue(value_spec.stateful_wrapper)

        bump_tool = build_tool_from_spec(bump_spec)
        value_tool = build_tool_from_spec(value_spec)
        return script_path, bump_tool, value_tool

    def test_increment_persists_across_tool_calls_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _, bump_tool, value_tool = self._build_counter_tools(tmp)
            ctx = ToolContext(workspace_root=tmp, session_id="sess-a")

            with patch.object(sdk_wrapper, "is_allowed_wrapper_script", return_value=True):
                bump_tool.call({}, ctx)
                result = value_tool.call({}, ctx)

            self.assertFalse(result.is_error, result.output)
            self.assertEqual(result.output, 1)

    def test_sessions_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _, bump_tool, value_tool = self._build_counter_tools(tmp)

            with patch.object(sdk_wrapper, "is_allowed_wrapper_script", return_value=True):
                bump_tool.call({}, ToolContext(workspace_root=tmp, session_id="sess-a"))
                result_a = value_tool.call({}, ToolContext(workspace_root=tmp, session_id="sess-a"))
                result_b = value_tool.call({}, ToolContext(workspace_root=tmp, session_id="sess-b"))

            self.assertEqual(result_a.output, 1)
            self.assertEqual(result_b.output, 0)


class SessionContextSource:
    SOURCE = '''
import contextvars
from contextvars import Token
from typing import Optional

_session_id_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "session_id",
    default=None,
)


def set_session_id(session_id: str) -> Token[str]:
    """Set the current session_id context."""
    return _session_id_context.set(session_id)


def get_session_id() -> Optional[str]:
    """Get the current session_id from context."""
    return _session_id_context.get() or ""
'''


class TestSdkContextRegistryCrossCall(unittest.TestCase):
    def setUp(self) -> None:
        reset_sdk_instance_registry()
        reset_sdk_context_registry()
        sdk_wrapper._MODULE_CACHE.clear()
        sdk_wrapper._SCRIPT_USES_INSTANCE_CACHE.clear()

    def _build_session_tools(self, tmp: Path) -> tuple[object, object]:
        pkg = tmp / "teams_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "context.py").write_text(SessionContextSource.SOURCE)

        parser = SourceCodeParser(tmp)
        components = parser.parse()
        ops = components[0].operations

        script_path = _generate_wrapper_script(
            ops,
            class_name=None,
            module_name="teams_pkg.context",
            file_stem="context",
            source_dir=str(tmp),
        )
        self.assertFalse(sdk_wrapper.wrapper_uses_instance_cache(script_path))

        set_spec = operation_to_spec(
            next(op for op in ops if op.name == "set_session_id"),
            source_dir=str(tmp),
            script_path=str(script_path),
            comp_name="agent_teams",
        )
        get_spec = operation_to_spec(
            next(op for op in ops if op.name == "get_session_id"),
            source_dir=str(tmp),
            script_path=str(script_path),
            comp_name="agent_teams",
        )
        self.assertTrue(set_spec.stateful_wrapper)
        self.assertTrue(get_spec.stateful_wrapper)

        return build_tool_from_spec(set_spec), build_tool_from_spec(get_spec)

    def test_contextvar_session_persists_across_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            set_tool, get_tool = self._build_session_tools(tmp)
            ctx = ToolContext(workspace_root=tmp, session_id="verify-session-001")

            with patch.object(sdk_wrapper, "is_allowed_wrapper_script", return_value=True):
                set_tool.call({"session_id": "verify-session-001"}, ctx)
                result = get_tool.call({}, ctx)

            self.assertFalse(result.is_error, result.output)
            self.assertEqual(result.output, "verify-session-001")

    def test_contextvar_sessions_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            set_tool, get_tool = self._build_session_tools(tmp)

            with patch.object(sdk_wrapper, "is_allowed_wrapper_script", return_value=True):
                set_tool.call(
                    {"session_id": "verify-session-001"},
                    ToolContext(workspace_root=tmp, session_id="sess-a"),
                )
                result_a = get_tool.call({}, ToolContext(workspace_root=tmp, session_id="sess-a"))
                result_b = get_tool.call({}, ToolContext(workspace_root=tmp, session_id="sess-b"))

            self.assertEqual(result_a.output, "verify-session-001")
            self.assertEqual(result_b.output, "")


if __name__ == "__main__":
    unittest.main()

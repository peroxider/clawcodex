"""Unit tests for :mod:`extensions.sop_converter.tool_state`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extensions.sop_converter.tool_state import (
    enrich_tool_input,
    get_session_secrets,
    is_cli_secret_consumer,
    is_configure_tool,
    load_tool_state,
    persist_configure_secrets,
    set_session_secret,
    tool_state_path,
)


class TestToolState(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self._tmpdir.name) / "sessions"
        self.session_id = "test-session-001"

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _patch_sessions_dir(self):
        import extensions.sop_converter.tool_state as ts

        return mock.patch.object(
            ts,
            "resolve_sessions_dir",
            return_value=self.sessions_dir,
        )

    def test_set_and_get_session_secret(self) -> None:
        with self._patch_sessions_dir():
            set_session_secret(self.session_id, "llm_api_key", "sk-test")
            secrets = get_session_secrets(self.session_id)
            self.assertEqual(secrets["llm_api_key"], "sk-test")
            path = tool_state_path(self.session_id)
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["secrets"]["llm_api_key"], "sk-test")

    def test_persist_configure_secrets(self) -> None:
        with self._patch_sessions_dir():
            persist_configure_secrets(
                "agentsdk-data-generation-platform-backend-config-memoryconfig-set-llm-api-key",
                {"api_key": "sk-from-configure"},
                self.session_id,
            )
            self.assertEqual(
                get_session_secrets(self.session_id)["llm_api_key"],
                "sk-from-configure",
            )

    def test_enrich_tool_input_injects_stdin_and_env(self) -> None:
        with self._patch_sessions_dir():
            set_session_secret(self.session_id, "llm_api_key", "sk-injected")
            enriched = enrich_tool_input(
                "agentsdk-data-generation-platform-execute-application",
                {"args": "--project demo --generate_questions"},
                self.session_id,
            )
            self.assertEqual(enriched["__stdin_config"]["llm_api_key"], "sk-injected")
            self.assertEqual(enriched["__env"]["LLM_API_KEY"], "sk-injected")
            self.assertEqual(enriched["__env"]["DEEPSEEK_API_KEY"], "sk-injected")
            self.assertEqual(enriched["__interactive_inputs"], ["sk-injected"])

    def test_enrich_skips_without_session(self) -> None:
        params = {"args": "--project demo"}
        self.assertEqual(
            enrich_tool_input(
                "agentsdk-data-generation-platform-execute-application",
                params,
                None,
            ),
            params,
        )

    def test_heuristics(self) -> None:
        self.assertTrue(
            is_configure_tool(
                "agentsdk-data-generation-platform-backend-config-memoryconfig-set-llm-api-key"
            )
        )
        self.assertTrue(
            is_cli_secret_consumer("agentsdk-data-generation-platform-execute-application")
        )
        self.assertFalse(is_configure_tool("agentsdk-data-generation-platform-execute-application"))


class TestCliStubSecretsForwarding(unittest.TestCase):
    def test_cli_main_stub_accepts_stdin_config_and_env(self) -> None:
        from extensions.sop_converter.source_parser import SourceOperation
        from extensions.sop_converter.tool_registry_bridge import _generate_cli_main_stub

        op = SourceOperation(name="execute_application", description="CLI entry")
        stub = _generate_cli_main_stub(op)
        self.assertIn("__stdin_config", stub)
        self.assertIn("__env", stub)
        self.assertIn("env=_run_env", stub)
        self.assertIn("_stdin_payload", stub)


if __name__ == "__main__":
    unittest.main()

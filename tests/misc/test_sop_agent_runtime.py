"""Regression tests for F-56/F-57 SDK reconstruction and secret references."""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from extensions.sop_converter.agent_runtime import AgentRuntimeError, materialize_agent
from extensions.sop_converter.resource_catalog import ResourceRecord
from extensions.sop_converter.sdk_serialization import resolve_env_references


class TestEnvironmentReferences(unittest.TestCase):
    def test_only_explicit_env_references_are_resolved(self) -> None:
        value = {
            "api_key": "env:DEEPSEEK_API_KEY",
            "shell_style": "$DEEPSEEK_API_KEY",
        }

        resolved = resolve_env_references(
            value,
            environ={"DEEPSEEK_API_KEY": "secret-value"},
        )

        self.assertEqual(resolved["api_key"], "secret-value")
        self.assertEqual(resolved["shell_style"], "$DEEPSEEK_API_KEY")

    def test_missing_environment_reference_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "environment variable is not set"):
            resolve_env_references("env:MISSING_DEEPSEEK_API_KEY", environ={})

    def test_shell_style_api_key_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "use env:NAME"):
            resolve_env_references({"api_key": "$DEEPSEEK_API_KEY"}, environ={})


class TestAgentMaterialization(unittest.TestCase):
    def test_missing_record_secret_has_stable_error_code(self) -> None:
        record = ResourceRecord(
            resource_type="agent",
            resource_id="verify-bot",
            source_tool="create-agent",
            materializer={"kind": "python_function", "module": "x", "name": "create"},
            invoker={},
            payload={"init_kwargs": {"api_key": "env:TEST_F57_MISSING_KEY"}},
            secrets={"env_refs": ["TEST_F57_MISSING_KEY"]},
        )
        with self.assertRaises(AgentRuntimeError) as raised:
            materialize_agent(record)
        self.assertEqual(raised.exception.error_code, "resource_secret_missing")
        self.assertIn("TEST_F57_MISSING_KEY", str(raised.exception))

    def test_factory_reconstructs_typed_config_and_resolves_env_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            package = tmp / "typed_sdk"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "factory.py").write_text(
                textwrap.dedent(
                    """
                    from dataclasses import dataclass


                    @dataclass
                    class AgentConfig:
                        id: str
                        api_key: str


                    class Agent:
                        def __init__(self, config: AgentConfig):
                            self.config = config


                    def create_agent(agent_config: AgentConfig) -> Agent:
                        return Agent(agent_config)
                    """
                ).strip(),
                encoding="utf-8",
            )
            record = ResourceRecord(
                resource_type="agent",
                resource_id="verify-bot",
                source_tool="create-agent",
                materializer={
                    "kind": "python_function",
                    "module": "typed_sdk.factory",
                    "name": "create_agent",
                },
                invoker={"kind": "python_method", "method": "invoke"},
                payload={
                    "init_kwargs": {
                        "agent_config": {
                            "id": "verify-bot",
                            "api_key": "env:TEST_F57_DEEPSEEK_KEY",
                        }
                    }
                },
                sdk={"source_dir": str(tmp)},
            )
            previous = os.environ.get("TEST_F57_DEEPSEEK_KEY")
            os.environ["TEST_F57_DEEPSEEK_KEY"] = "secret-value"
            try:
                materialized = materialize_agent(record)
            finally:
                if previous is None:
                    os.environ.pop("TEST_F57_DEEPSEEK_KEY", None)
                else:
                    os.environ["TEST_F57_DEEPSEEK_KEY"] = previous
                sys.modules.pop("typed_sdk.factory", None)
                sys.modules.pop("typed_sdk", None)

        agent = materialized["agent"]
        self.assertEqual(agent.config.id, "verify-bot")
        self.assertEqual(agent.config.api_key, "secret-value")

    def test_omitted_list_factory_defaults_match_create_wrapper(self) -> None:
        """F-56/F-57: rematerialize must apply create-wrapper ``(param or [])``.

        Create wrappers coerce omitted ``List[...] = None`` factory args to
        ``[]`` before calling the SDK. Catalog ``init_kwargs`` only stores
        args the model passed (often just ``agent_config``). Materialize must
        still supply empty lists so SDK helpers like ``len(workflows)`` do not
        crash with ``object of type 'NoneType' has no len()``.
        """
        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            package = tmp / "list_default_sdk"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "factory.py").write_text(
                textwrap.dedent(
                    """
                    from dataclasses import dataclass
                    from typing import List, Optional


                    @dataclass
                    class AgentConfig:
                        id: str


                    class Agent:
                        def __init__(self, config: AgentConfig, workflows, tools, note):
                            self.config = config
                            self.workflows = workflows
                            self.tools = tools
                            self.note = note


                    def create_agent(
                        agent_config: AgentConfig,
                        workflows: List[str] = None,
                        tools: List[str] = None,
                        note: Optional[str] = None,
                    ) -> Agent:
                        # Mirrors Jiuwen BaseAgent.add_workflows(len(workflows)).
                        if len(workflows) != 0:
                            raise AssertionError("expected empty workflows list")
                        if len(tools) != 0:
                            raise AssertionError("expected empty tools list")
                        return Agent(agent_config, workflows, tools, note)
                    """
                ).strip(),
                encoding="utf-8",
            )
            record = ResourceRecord(
                resource_type="agent",
                resource_id="verify-bot",
                source_tool="create-agent",
                materializer={
                    "kind": "python_function",
                    "module": "list_default_sdk.factory",
                    "name": "create_agent",
                },
                invoker={"kind": "python_method", "method": "invoke"},
                payload={"init_kwargs": {"agent_config": {"id": "verify-bot"}}},
                sdk={"source_dir": str(tmp)},
            )
            try:
                materialized = materialize_agent(record)
            finally:
                sys.modules.pop("list_default_sdk.factory", None)
                sys.modules.pop("list_default_sdk", None)

        agent = materialized["agent"]
        self.assertEqual(agent.config.id, "verify-bot")
        self.assertEqual(agent.workflows, [])
        self.assertEqual(agent.tools, [])
        self.assertIsNone(agent.note)


if __name__ == "__main__":
    unittest.main()

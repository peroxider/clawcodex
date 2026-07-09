"""E2E integration test for F-55 create → catalog → invoke lifecycle.

This test exercises the full L1 chain that the plan describes:

1. A temporary SDK exposes ``build_agent()`` (create) and ``run_agent(agent_id, query)``
   (invoke).
2. ``register_component_tools`` emits a wrapper for ``build_agent`` with the
   ``--catalog-metadata`` flag and writes the spec to the bundle-local tool dir.
3. Running the create wrapper writes ``agent_id`` into
   ``<bundle>/.clawcodex/agent-catalog.json``.
4. The ``invoke-existing-agent`` composite macro wrapper reads the catalog,
   materializes the SDK class, and calls ``run_agent`` with the query.

The test drives the wrapper scripts via ``subprocess.run`` exactly as the
Agent tool's bash call handler does.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from extensions.sop_converter.agent_catalog import AgentCatalog
from extensions.sop_converter.agent_catalog_resolver import (
    HOME_ONLY_ENV,
    HOME_ROOT_ENV,
)
from extensions.sop_converter.source_parser import SourceCodeParser
from extensions.sop_converter.tool_registry_bridge import register_component_tools


REPO_ROOT = Path(__file__).resolve().parents[2]
INVOKE_WRAPPER = (
    REPO_ROOT
    / "extensions"
    / "sop_converter"
    / "composite_tools"
    / "scripts"
    / "invoke_existing_agent_wrapper.py"
)


def _last_json_line(raw: str) -> dict:
    """Return the last non-empty line parsed as JSON."""
    text = raw.strip()
    if not text:
        raise AssertionError("no output")
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no JSON line found in output: {raw!r}")


def _write_fake_sdk(parent: Path) -> Path:
    """Create a tiny importable SDK and return the directory containing it."""
    sdk_dir = parent / "fake_sdk"
    sdk_dir.mkdir(parents=True, exist_ok=True)
    (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
    (sdk_dir / "agent.py").write_text(
        textwrap.dedent(
            """
            from typing import Any


            class DemoAgent:
                def __init__(self, temperature: float = 0.0, model: str = "gpt-4o"):
                    self.temperature = temperature
                    self.model = model

                def build_agent(self, query: str) -> dict[str, Any]:
                    \"\"\"Create a new agent and return its stable id.\"\"\"
                    return {"agent_id": "agent-1", "query": query}

                def invoke(self, query: str) -> dict[str, Any]:
                    \"\"\"Run this agent on the provided query.\"\"\"
                    return {
                        "echo": query,
                        "model": self.model,
                        "temperature": self.temperature,
                    }

                def run_agent(self, agent_id: str, query: str) -> dict[str, Any]:
                    \"\"\"Run an existing agent by id on the provided query.\"\"\"
                    return {
                        "echo": query,
                        "agent_id": agent_id,
                        "model": self.model,
                        "temperature": self.temperature,
                    }
            """
        ).strip(),
        encoding="utf-8",
    )
    return parent


class TestCreateToInvokeLifecycleE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self.sdk_parent = _write_fake_sdk(self.tmp)
        self._saved_env = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_create_wrapper_writes_catalog_then_invoke_recovers(self) -> None:
        # Parse the fake SDK into SourceComponents.
        parser = SourceCodeParser(str(self.sdk_parent), extern_only=True)
        components = parser.parse()
        self.assertTrue(components, "SourceCodeParser found no operations")

        # Register tools into the bundle-local registry.
        name_map = register_component_tools(
            components,
            str(self.sdk_parent),
            persist=True,
            bundle_dir=self.bundle,
            bundle_id="test-bundle",
        )

        # Locate the registered build-agent tool.
        build_tool_name: str | None = None
        for key, value in name_map.items():
            if key.endswith(".build_agent"):
                build_tool_name = value
                break
        self.assertIsNotNone(build_tool_name, f"build_agent not found in {name_map}")
        assert build_tool_name is not None

        spec_path = self.bundle / "agent-tools" / f"{build_tool_name}.json"
        self.assertTrue(spec_path.exists(), f"spec not found at {spec_path}")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        call_impl = spec["call_impl"]
        self.assertIn("--catalog-metadata", call_impl)

        # Execute the create wrapper.
        args = {"query": "hello"}
        command = call_impl.replace("'{json_args}'", shlex.quote(json.dumps(args)))
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"create wrapper failed: stderr={proc.stderr!r} stdout={proc.stdout!r}",
        )
        create_result = _last_json_line(proc.stdout)
        self.assertEqual(create_result.get("agent_id"), "agent-1")

        # Catalog should now exist and contain the agent.
        catalog_path = self.bundle / ".clawcodex" / "agent-catalog.json"
        self.assertTrue(catalog_path.exists(), "agent catalog was not written")
        catalog = AgentCatalog.load(catalog_path)
        self.assertIn("agent-1", catalog.list_ids())
        entry = catalog.get("agent-1")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.class_name, "DemoAgent")
        self.assertEqual(entry.module_name, "fake_sdk.agent")

        # Execute the invoke-existing-agent macro wrapper.
        invoke_cmd = [
            sys.executable,
            str(INVOKE_WRAPPER),
            "invoke_existing_agent",
            json.dumps({"agent_id": "agent-1", "query": "hello"}),
        ]
        env = os.environ.copy()
        env["CLAWCODEX_BUNDLE_PATH"] = str(self.bundle)
        invoke_proc = subprocess.run(
            invoke_cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(
            invoke_proc.returncode,
            0,
            f"invoke wrapper failed: stderr={invoke_proc.stderr!r}",
        )
        invoke_result = _last_json_line(invoke_proc.stdout)
        self.assertEqual(invoke_result.get("agent_id"), "agent-1")
        self.assertEqual(invoke_result.get("output", {}).get("echo"), "hello")
        self.assertEqual(invoke_result.get("output", {}).get("model"), "gpt-4o")


if __name__ == "__main__":
    unittest.main()

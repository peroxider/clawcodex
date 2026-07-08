"""E2E unit tests for F-55 L1 — :mod:`extensions.sop_converter.composite_tools`.

Covers the four scenarios from F-55 §4.4:

1. 创建 → 立即按 ID 调用 (single-process happy path)
2. 创建 → wrapper 子进程退出 → 新进程按 ID 调用 (cross-process recovery)
3. 创建 → 关闭会话 → 新会话按 ID 调用, catalog 在 home 目录 (跨会话)
4. 已有 agent_id 但 catalog 无记录 (graceful ``agent_catalog_missing`` error)

The tests drive the wrapper script directly via ``subprocess.run`` so they
exercise the same code path the Agent tool uses (call_handlers/bash.py →
subprocess → wrapper → JSON stdout).  A tiny fake SDK module is written to
a temp dir and its absolute path is stuffed into ``sys.path`` so the
wrapper's importlib call lands on the fake class.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from extensions.sop_converter.agent_catalog import (
    AgentCatalog,
    AgentCatalogEntry,
)
from extensions.sop_converter.agent_catalog_resolver import (
    HOME_ONLY_ENV,
    HOME_ROOT_ENV,
    resolve_catalog_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_PATH = (
    REPO_ROOT
    / "extensions"
    / "sop_converter"
    / "composite_tools"
    / "scripts"
    / "invoke_existing_agent_wrapper.py"
)


def _run_wrapper(
    args: dict,
    *,
    env: dict | None = None,
    bundle_path: str | None = None,
) -> dict:
    """Invoke the wrapper exactly the way the Agent tool does.

    ``bundle_path`` is set into the wrapper subprocess as
    ``CLAWCODEX_BUNDLE_PATH`` so the resolver finds the bundle-local
    catalog.  Tests that want the home fallback can omit it.
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    if bundle_path is not None:
        full_env["CLAWCODEX_BUNDLE_PATH"] = str(bundle_path)
    cmd = [sys.executable, str(WRAPPER_PATH), "invoke_existing_agent", json.dumps(args)]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
    )
    out = proc.stdout.strip()
    if not out:
        raise AssertionError(
            f"wrapper produced no stdout; stderr={proc.stderr!r} rc={proc.returncode}"
        )
    return json.loads(out)


def _write_fake_sdk(parent: Path, *, class_name: str = "DemoAgent", method: str = "invoke") -> Path:
    """Create a tiny SDK module on disk and return its parent dir (for sys.path)."""
    sdk_dir = parent / "fake_sdk"
    sdk_dir.mkdir(parents=True, exist_ok=True)
    (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
    src = textwrap.dedent(
        f"""
        class {class_name}:
            def __init__(self, temperature=0.0, model="gpt-4o"):
                self.temperature = temperature
                self.model = model
            def {method}(self, query=""):
                return {{"echo": query, "model": self.model, "temperature": self.temperature}}
        """
    ).strip()
    (sdk_dir / "agent.py").write_text(src, encoding="utf-8")
    return sdk_dir


class TestInvokeExistingAgentHappyPath(unittest.TestCase):
    """Scenario 1: same-process create → call."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self.sdk = _write_fake_sdk(self.tmp, method="invoke")
        # Save env so the resolver can find the catalog.
        self._saved = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_create_then_invoke_round_trip(self) -> None:
        # 1. Pretend a create tool wrote the catalog.  ``sdk_source_dir`` is
        # the parent of the importable package (matches the convention in
        # ``lifecycle_metadata_payload`` / ``register_component_tools``).
        entry = AgentCatalogEntry(
            agent_id="agent-1",
            sdk_source_dir=str(self.tmp),
            dsl={"name": "demo", "max_steps": 4},
            model="gpt-4o",
            provider="openai",
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            init_kwargs={"temperature": 0.7, "model": "gpt-4o-mini"},
        )
        cat_path = self.bundle / ".clawcodex" / "agent-catalog.json"
        AgentCatalog().upsert(entry, bundle_id="bundle").__class__  # silence linter
        cat = AgentCatalog()
        cat.upsert(entry, bundle_id="bundle")
        cat.save(cat_path)

        # 2. Verify path resolver points at the bundle-local file.
        loc = resolve_catalog_path(self.bundle)
        self.assertEqual(loc.path, cat_path)
        self.assertTrue(cat_path.exists())

        # 3. Drive the wrapper.
        out = _run_wrapper(
            {"agent_id": "agent-1", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["agent_id"], "agent-1")
        self.assertEqual(out["output"]["echo"], "ping")
        self.assertEqual(out["output"]["model"], "gpt-4o-mini")
        self.assertEqual(out["output"]["temperature"], 0.7)


class TestInvokeExistingAgentCrossProcess(unittest.TestCase):
    """Scenario 2: write in one process, read in another."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self.sdk = _write_fake_sdk(self.tmp, method="invoke")
        self._saved = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v

    def test_catalog_written_in_subprocess_readable_in_subprocess(self) -> None:
        cat_path = self.bundle / ".clawcodex" / "agent-catalog.json"
        write_script = textwrap.dedent(
            f"""
            import json
            from pathlib import Path
            from extensions.sop_converter.agent_catalog import AgentCatalog, AgentCatalogEntry

            cat = AgentCatalog()
            entry = AgentCatalogEntry(
                agent_id="agent-2",
                sdk_source_dir={str(self.tmp)!r},
                dsl={{}},
                model="gpt-4o",
                provider="openai",
                class_name="DemoAgent",
                module_name="fake_sdk.agent",
                init_kwargs={{}},
            )
            cat.upsert(entry, bundle_id="bundle")
            cat.save(Path({str(cat_path)!r}))
            print("OK")
            """
        )
        proc = subprocess.run(
            [sys.executable, "-c", write_script],
            capture_output=True,
            text=True,
            timeout=20,
            env=os.environ.copy(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK", proc.stdout)
        self.assertTrue(cat_path.exists())

        # Now a second process drives the wrapper.
        out = _run_wrapper(
            {"agent_id": "agent-2", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["agent_id"], "agent-2")
        self.assertEqual(out["output"]["echo"], "ping")


class TestInvokeExistingAgentHomeOnly(unittest.TestCase):
    """Scenario 3: CLAWCODEX_CATALOG_HOME_ONLY=1 → catalog in $HOME."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self.sdk = _write_fake_sdk(self.tmp, method="invoke")
        # Force catalog into a custom home so the test doesn't touch the
        # real ~/.clawcodex.
        self._saved = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }
        os.environ[HOME_ROOT_ENV] = str(self.tmp)
        os.environ[HOME_ONLY_ENV] = "1"

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_home_only_writes_to_clawcodex_home(self) -> None:
        cat_path = self.tmp / "sop-agents" / "bundle" / "agents.json"
        entry = AgentCatalogEntry(
            agent_id="agent-3",
            sdk_source_dir=str(self.tmp),
            dsl={},
            model="gpt-4o",
            provider="openai",
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            init_kwargs={},
        )
        cat = AgentCatalog()
        cat.upsert(entry, bundle_id="bundle")
        cat.save(cat_path)

        out = _run_wrapper(
            {"agent_id": "agent-3", "query": "hello"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["agent_id"], "agent-3")
        self.assertEqual(out["output"]["echo"], "hello")


class TestInvokeExistingAgentMissingCatalog(unittest.TestCase):
    """Scenario 4: agent_id not in catalog → structured error, not a stack trace."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self._saved = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }
        os.environ[HOME_ROOT_ENV] = str(self.tmp)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_no_catalog_file(self) -> None:
        out = _run_wrapper(
            {"agent_id": "ghost", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["error_code"], "agent_catalog_missing")
        self.assertEqual(out["agent_id"], "ghost")
        self.assertIn("agent catalog not found", out["error"])

    def test_agent_id_absent_from_existing_catalog(self) -> None:
        cat = AgentCatalog()
        cat.upsert(
            AgentCatalogEntry(
                agent_id="present",
                sdk_source_dir="/tmp",
                class_name="X",
                module_name="y",
            )
        )
        cat.save(self.bundle / ".clawcodex" / "agent-catalog.json")
        out = _run_wrapper(
            {"agent_id": "missing", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["error_code"], "agent_not_in_catalog")


class TestInvokeExistingAgentMaterializeFailures(unittest.TestCase):
    """Edge: catalog row references an unloadable module/class."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bundle = self.tmp / "bundle"
        self.bundle.mkdir()
        self._saved = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }
        os.environ[HOME_ROOT_ENV] = str(self.tmp)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_module_not_found(self) -> None:
        cat = AgentCatalog()
        cat.upsert(
            AgentCatalogEntry(
                agent_id="unloadable",
                sdk_source_dir=str(self.tmp),
                class_name="Nope",
                module_name="does.not.exist",
            )
        )
        cat.save(self.bundle / ".clawcodex" / "agent-catalog.json")
        out = _run_wrapper(
            {"agent_id": "unloadable", "query": "x"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["error_code"], "materialize_failed")

    def test_invoke_falls_back_to_run_method(self) -> None:
        sdk = _write_fake_sdk(self.tmp, method="run")
        cat = AgentCatalog()
        cat.upsert(
            AgentCatalogEntry(
                agent_id="run-agent",
                sdk_source_dir=str(self.tmp),
                class_name="DemoAgent",
                module_name="fake_sdk.agent",
                invoke_method="run",
            )
        )
        cat.save(self.bundle / ".clawcodex" / "agent-catalog.json")
        out = _run_wrapper(
            {"agent_id": "run-agent", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["output"]["echo"], "ping")


if __name__ == "__main__":
    unittest.main()

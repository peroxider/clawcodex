"""E2E unit tests for F-55 L1 — invoke-existing-agent via F-56 ResourceCatalog.

Covers:

1. Persist → invoke by id (happy path)
2. Persist in subprocess → invoke in another process
3. Home-only resource catalog recovery
4. Missing catalog / missing id → structured error
5. Materialize failures

Legacy ``agent-catalog.json`` is no longer consulted (F-56 Phase D).
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

from extensions.sop_converter.agent_catalog import AgentCatalogEntry
from extensions.sop_converter.agent_catalog_resolver import (
    HOME_ONLY_ENV,
    HOME_ROOT_ENV,
)
from extensions.sop_converter.resource_catalog import (
    ResourceCatalog,
    agent_entry_to_resource_record,
    resolve_resource_catalog_path,
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


def _persist_entry(
    bundle: Path,
    entry: AgentCatalogEntry,
    *,
    bundle_id: str = "bundle",
) -> Path:
    """Write an agent fixture into the F-56 resource catalog."""
    loc = resolve_resource_catalog_path(bundle, bundle_id=bundle_id)
    loc.ensure_parent()
    cat = ResourceCatalog()
    cat.upsert(agent_entry_to_resource_record(entry, bundle_id=bundle_id))
    cat.save(loc.path)
    return loc.path


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
        cat_path = _persist_entry(self.bundle, entry)
        self.assertTrue(cat_path.exists())
        self.assertEqual(cat_path.name, "resource-catalog.json")

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
        cat_path = self.bundle / ".clawcodex" / "resource-catalog.json"
        write_script = textwrap.dedent(
            f"""
            from pathlib import Path
            from extensions.sop_converter.agent_catalog import AgentCatalogEntry
            from extensions.sop_converter.resource_catalog import (
                ResourceCatalog,
                agent_entry_to_resource_record,
                resolve_resource_catalog_path,
            )

            bundle = Path({str(self.bundle)!r})
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
            loc = resolve_resource_catalog_path(bundle, bundle_id="bundle")
            loc.ensure_parent()
            cat = ResourceCatalog()
            cat.upsert(agent_entry_to_resource_record(entry, bundle_id="bundle"))
            cat.save(loc.path)
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

        out = _run_wrapper(
            {"agent_id": "agent-2", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["agent_id"], "agent-2")
        self.assertEqual(out["output"]["echo"], "ping")


class TestInvokeExistingAgentResourceCatalogFallback(unittest.TestCase):
    """F-56: resource-catalog alone can recover an existing agent."""

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

    def test_resource_catalog_recovers_when_agent_catalog_missing(self) -> None:
        entry = AgentCatalogEntry(
            agent_id="agent-f56",
            sdk_source_dir=str(self.tmp),
            dsl={"name": "verify-bot"},
            model="gpt-4o",
            provider="openai",
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            init_kwargs={"model": "gpt-4o-mini"},
            resource_type="AgentConfig",
            handle_field="agent_id",
        )
        loc = resolve_resource_catalog_path(self.bundle)
        cat = ResourceCatalog()
        cat.upsert(agent_entry_to_resource_record(entry, bundle_id="bundle"))
        cat.save(loc.path)

        self.assertFalse((self.bundle / ".clawcodex" / "agent-catalog.json").exists())
        out = _run_wrapper(
            {"agent_id": "agent-f56", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["agent_id"], "agent-f56")
        self.assertEqual(out["output"]["echo"], "ping")
        self.assertEqual(out["output"]["model"], "gpt-4o-mini")
        self.assertEqual(
            [step["step_id"] for step in out["trace"]],
            ["load_agent_record", "materialize_agent", "invoke_agent"],
        )
        self.assertTrue(all(step["status"] == "success" for step in out["trace"]))

    def test_resource_catalog_resolves_agent_name_without_agent_id(self) -> None:
        entry = AgentCatalogEntry(
            agent_id="agent-by-name",
            sdk_source_dir=str(self.tmp),
            dsl={"name": "verify-bot"},
            model="gpt-4o",
            provider="openai",
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            init_kwargs={"model": "gpt-4o-mini"},
            resource_type="AgentConfig",
            handle_field="agent_id",
        )
        location = resolve_resource_catalog_path(self.bundle)
        catalog = ResourceCatalog()
        catalog.upsert(agent_entry_to_resource_record(entry, bundle_id="bundle"))
        catalog.save(location.path)

        out = _run_wrapper(
            {"agent_ref": "verify-bot", "query": "ping"},
            bundle_path=str(self.bundle),
        )

        self.assertEqual(out["agent_ref"], "verify-bot")
        self.assertEqual(out["agent_id"], "agent-by-name")
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
        loc = resolve_resource_catalog_path(self.bundle, bundle_id="bundle")
        loc.ensure_parent()
        cat = ResourceCatalog()
        cat.upsert(agent_entry_to_resource_record(entry, bundle_id="bundle"))
        cat.save(loc.path)
        self.assertIn("sop-resources", str(loc.path))

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
        self.assertEqual(out["error_code"], "resource_catalog_missing")
        self.assertEqual(out["agent_id"], "ghost")
        self.assertEqual(out["step_id"], "load_agent_record")
        self.assertEqual(out["trace"][-1]["status"], "error")

    def test_agent_id_absent_from_existing_catalog(self) -> None:
        entry = AgentCatalogEntry(
            agent_id="present",
            sdk_source_dir="/tmp",
            class_name="X",
            module_name="y",
        )
        _persist_entry(self.bundle, entry)
        out = _run_wrapper(
            {"agent_id": "missing", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["error_code"], "resource_catalog_missing")


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
        entry = AgentCatalogEntry(
            agent_id="unloadable",
            sdk_source_dir=str(self.tmp),
            class_name="Nope",
            module_name="does.not.exist",
        )
        _persist_entry(self.bundle, entry)
        out = _run_wrapper(
            {"agent_id": "unloadable", "query": "x"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["error_code"], "resource_materialize_failed")

    def test_invoke_falls_back_to_run_method(self) -> None:
        _write_fake_sdk(self.tmp, method="run")
        entry = AgentCatalogEntry(
            agent_id="run-agent",
            sdk_source_dir=str(self.tmp),
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            invoke_method="run",
        )
        _persist_entry(self.bundle, entry)
        out = _run_wrapper(
            {"agent_id": "run-agent", "query": "ping"},
            bundle_path=str(self.bundle),
        )
        self.assertEqual(out["output"]["echo"], "ping")


if __name__ == "__main__":
    unittest.main()

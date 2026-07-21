"""Tests for F-56 SOP ResourceCatalog."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.sop_converter.agent_catalog import AgentCatalogEntry
from extensions.sop_converter.agent_catalog_resolver import HOME_ONLY_ENV, HOME_ROOT_ENV
from extensions.sop_converter.resource_catalog import (
    RESOURCE_CATALOG_AMBIGUOUS,
    RESOURCE_CATALOG_MISSING,
    RESOURCE_VERSION_UNSUPPORTED,
    SCHEMA_VERSION,
    CatalogExecutionContext,
    ResourceCatalogError,
    ResourceCatalog,
    ResourceRecord,
    agent_entry_to_resource_record,
    get_agent_record,
    resolve_resource_catalog_path,
    resource_error,
)


def _tmp_path() -> Path:
    return Path(tempfile.mkdtemp(prefix="resource_catalog_test_"))


def _make_record(*, resource_id: str = "agent-1") -> ResourceRecord:
    return ResourceRecord(
        resource_type="AgentConfig",
        resource_id=resource_id,
        bundle_id="core",
        source_tool="agentbuilder-build-agent",
        materializer={
            "kind": "python_class",
            "module": "fake_sdk.agent",
            "class_name": "DemoAgent",
        },
        invoker={"kind": "python_method", "method": "invoke", "input_param": "query"},
        payload={
            "kind": "inline",
            "dsl": {"name": "verify-bot", "api_key": "sk-secret"},
            "model": "gpt-4o",
        },
        sdk={"source_dir": "/tmp/sdk"},
    )


class TestResourceCatalogRoundTrip(unittest.TestCase):
    def test_save_load_and_lookup_round_trip(self) -> None:
        path = _tmp_path() / "resource-catalog.json"
        cat = ResourceCatalog()
        cat.upsert(_make_record())
        cat.save(path)

        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret", raw)
        self.assertIn("CLAWCODEX_CORE_API_KEY", raw)

        with patch.dict(os.environ, {"CLAWCODEX_CORE_API_KEY": "sk-restored"}):
            loaded = ResourceCatalog.load(path)
            record = loaded.get("agentconfig", "agent-1")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.payload["dsl"]["api_key"], "sk-restored")
        self.assertEqual(record.materializer["class_name"], "DemoAgent")
        self.assertEqual(record.invoker["input_param"], "query")

    def test_upsert_is_idempotent_and_preserves_created_at(self) -> None:
        cat = ResourceCatalog()
        first = cat.upsert(_make_record())
        second_record = _make_record()
        second_record.metadata = {"extra": "x"}
        second = cat.upsert(second_record)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(cat.list_keys(), ["agentconfig:agent-1"])
        self.assertEqual(cat.get("agentconfig", "agent-1").metadata["extra"], "x")  # type: ignore[union-attr]

    def test_mark_failed_sets_status_and_reason(self) -> None:
        cat = ResourceCatalog()
        cat.upsert(_make_record())
        cat.mark_failed("AgentConfig", "agent-1", "broken payload")
        record = cat.get("agentconfig", "agent-1")
        assert record is not None
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.metadata["failure_reason"], "broken payload")

    def test_missing_and_bad_files_degrade_to_empty(self) -> None:
        missing = _tmp_path() / "missing.json"
        self.assertEqual(ResourceCatalog.load(missing).list_keys(), [])
        bad = _tmp_path() / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(ResourceCatalog.load(bad).list_keys(), [])

    def test_unsupported_catalog_version_raises_resource_version_unsupported(self) -> None:
        future = _tmp_path() / "future.json"
        future.write_text(json.dumps({"version": 999, "records": {}}), encoding="utf-8")
        with self.assertRaises(ResourceCatalogError) as raised:
            ResourceCatalog.load(future)
        self.assertEqual(raised.exception.error_code, RESOURCE_VERSION_UNSUPPORTED)
        self.assertIn("999", str(raised.exception))
        self.assertIn(str(SCHEMA_VERSION), str(raised.exception))

    def test_get_agent_record_propagates_unsupported_catalog_version(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        location = resolve_resource_catalog_path(bundle)
        location.path.parent.mkdir(parents=True, exist_ok=True)
        location.path.write_text(
            json.dumps({"version": 999, "records": {}}),
            encoding="utf-8",
        )
        with self.assertRaises(ResourceCatalogError) as raised:
            get_agent_record(
                agent_ref="verify-bot",
                catalog_context=CatalogExecutionContext(
                    bundle_path=bundle,
                    bundle_id="bundle",
                ),
            )
        self.assertEqual(raised.exception.error_code, RESOURCE_VERSION_UNSUPPORTED)


class TestResourceCatalogResolver(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = {
            HOME_ROOT_ENV: os.environ.pop(HOME_ROOT_ENV, None),
            HOME_ONLY_ENV: os.environ.pop(HOME_ONLY_ENV, None),
        }

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def test_bundle_user_and_session_paths(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        os.environ[HOME_ROOT_ENV] = str(root)

        bundle_loc = resolve_resource_catalog_path(bundle)
        self.assertEqual(bundle_loc.reason, "bundle-local")
        self.assertEqual(bundle_loc.path, bundle / ".clawcodex" / "resource-catalog.json")

        user_loc = resolve_resource_catalog_path(bundle, bundle_id="core", scope="user")
        self.assertEqual(user_loc.reason, "user-local")
        self.assertEqual(user_loc.path, root / "sop-resources" / "core" / "catalog.json")

        session_loc = resolve_resource_catalog_path(bundle, session_id="s1", scope="session")
        self.assertEqual(session_loc.reason, "session-local")
        self.assertEqual(session_loc.path, root / "sessions" / "s1" / "sop-resources.json")

    def test_home_only_forces_user_catalog(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        os.environ[HOME_ROOT_ENV] = str(root)
        os.environ[HOME_ONLY_ENV] = "1"
        loc = resolve_resource_catalog_path(bundle, bundle_id="core")
        self.assertEqual(loc.reason, "home-forced")
        self.assertEqual(loc.path, root / "sop-resources" / "core" / "catalog.json")


class TestResourceCatalogAgentBridge(unittest.TestCase):
    def test_get_agent_record_resolves_saved_agent_name(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        location = resolve_resource_catalog_path(bundle)
        catalog = ResourceCatalog()
        catalog.upsert(_make_record(resource_id="agent-verify"))
        catalog.save(location.path)

        record = get_agent_record(agent_ref="verify-bot", bundle_path=bundle)

        self.assertEqual(record.resource_id, "agent-verify")
        self.assertEqual(record.payload["dsl"]["name"], "verify-bot")

    def test_get_agent_record_uses_catalog_execution_context(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        location = resolve_resource_catalog_path(bundle)
        catalog = ResourceCatalog()
        catalog.upsert(_make_record(resource_id="agent-context"))
        catalog.save(location.path)

        record = get_agent_record(
            agent_id="agent-context",
            catalog_context=CatalogExecutionContext(
                bundle_path=bundle,
                bundle_id="bundle",
            ),
        )

        self.assertEqual(record.resource_id, "agent-context")

    def test_get_agent_record_rejects_ambiguous_saved_name(self) -> None:
        root = _tmp_path()
        bundle = root / "bundle"
        bundle.mkdir()
        location = resolve_resource_catalog_path(bundle)
        catalog = ResourceCatalog()
        catalog.upsert(_make_record(resource_id="agent-one"))
        catalog.upsert(_make_record(resource_id="agent-two"))
        catalog.save(location.path)

        with self.assertRaisesRegex(Exception, "multiple records") as raised:
            get_agent_record(agent_ref="verify-bot", bundle_path=bundle)
        self.assertEqual(getattr(raised.exception, "error_code", ""), RESOURCE_CATALOG_AMBIGUOUS)

    def test_agent_entry_to_resource_record(self) -> None:
        entry = AgentCatalogEntry(
            agent_id="agent-1",
            sdk_source_dir="/tmp/sdk",
            dsl={"name": "verify-bot"},
            model="gpt-4o",
            class_name="DemoAgent",
            module_name="fake_sdk.agent",
            init_kwargs={"temperature": 0.2},
            metadata={"source_tool": "agentbuilder-build-agent"},
            resource_type="AgentConfig",
            handle_field="agent_id",
        )
        record = agent_entry_to_resource_record(entry, bundle_id="core")
        self.assertEqual(record.resource_type, "agentconfig")
        self.assertEqual(record.resource_id, "agent-1")
        self.assertEqual(record.payload["agent_catalog_entry"]["agent_id"], "agent-1")
        self.assertEqual(record.materializer["class_name"], "DemoAgent")

    def test_resource_error_envelope(self) -> None:
        out = resource_error(
            RESOURCE_CATALOG_MISSING,
            "missing",
            resource_type="AgentConfig",
            resource_id="agent-1",
        )
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], RESOURCE_CATALOG_MISSING)
        self.assertEqual(out["resource_type"], "agentconfig")


if __name__ == "__main__":
    unittest.main()

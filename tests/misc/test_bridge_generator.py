"""Tests for the bridge generator and CLI discovery."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from extensions.sop_converter.skill_grouper import GroupStrategy, group_source_components
from extensions.sop_converter.source_parser import SourceCodeParser
from extensions.sop_converter.workflow_mode.bridge import BridgeGenerator
from extensions.sop_converter.workflow_mode.bridge.cli_discovery import discover_cli_prefix
from extensions.sop_converter.workflow_mode.capability import StageCapabilityMapper
from extensions.sop_converter.workflow_mode.capability.models import (
    ExecutionMode,
    StageAgentMap,
    StageCapabilityProfile,
)
from extensions.sop_converter.workflow_mode.extractors.adapters.generic import (
    GenericPipelineExtractor,
)
from extensions.sop_converter.workflow_mode.extractors.models import ExtractedStage, WorkflowGraph
from extensions.sop_converter.workflow_mode.scan_context import SourceScanContext

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestCliDiscovery:
    def test_discovers_matching_script_name(self):
        root = FIXTURES / "fixture_cli_bridge_project"
        assert discover_cli_prefix(root, "fixture-cli-bridge") == "fixture-cli-bridge"

    def test_override_wins(self, tmp_path: Path):
        assert discover_cli_prefix(tmp_path, "x", override="my-cli") == "my-cli"


class TestBridgeGenerator:
    def test_generate_python_bridge_skipped_for_agent_native(self, tmp_path: Path):
        path = FIXTURES / "fixture_fwa_project"
        scan = SourceScanContext.build(path)
        graph = GenericPipelineExtractor(scan=scan, mode="fwa").extract(path)
        components = SourceCodeParser(str(path)).parse()
        skills = group_source_components(components, strategy=GroupStrategy.COMPONENT_GROUP).skills
        agent_map = StageCapabilityMapper().map(graph, components, skills, scan=scan)

        script = BridgeGenerator().generate(
            graph,
            agent_map,
            path,
            tmp_path,
            project_name="fwa-test",
        )
        assert script is None

    def test_generate_cli_bridge_and_execute(self, tmp_path: Path):
        fixture = FIXTURES / "fixture_cli_bridge_project"
        cli_cmd = f"{sys.executable} {fixture / 'pipeline_cli.py'}"
        graph = WorkflowGraph(
            stages=[
                ExtractedStage(id=1, name="preprocess", label="PREPROCESS"),
            ],
            transitions=[],
            gates={},
            decisions={},
            contracts={},
            source_dir=str(fixture),
        )
        profile = StageCapabilityProfile(
            stage_id=1,
            execution_mode=ExecutionMode.WRAPPER,
            entry_function="main",
        )
        agent_map = StageAgentMap(by_stage_id={1: profile}, skill_to_agent={})

        script = BridgeGenerator().generate(
            graph,
            agent_map,
            fixture,
            tmp_path,
            mode="cli",
            project_name="cli-test",
            cli_entry=cli_cmd,
        )
        assert script is not None
        assert script.is_file()
        assert "CLI_PREFIX" in script.read_text(encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(script), "--stage-id", "1", "--project-dir", str(tmp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["returncode"] == 0
        assert payload["stage_id"] == 1
        assert "ok" in payload["stdout"]

        health = json.loads((tmp_path / "bridge" / "health.json").read_text(encoding="utf-8"))
        assert health["mode"] == "cli"
        assert health["ok"] is True

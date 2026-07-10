"""Tests for contract parsing and artifact semantics."""

from __future__ import annotations

import ast
from pathlib import Path

from extensions.sop_converter.workflow_mode.ast_helpers import parse_contracts_dict
from extensions.sop_converter.workflow_mode.extractors.adapters.arc import ArcExtractor
from extensions.sop_converter.workflow_mode.generator.artifact_semantics import (
    ARTIFACT_SEMANTICS,
    describe_output_file,
)

ARC_REPO = Path(__file__).resolve().parents[2].parent / "AutoResearchClaw"


class TestParseContractsDict:
    def test_extracts_dod_from_fixture(self):
        source = '''
CONTRACTS = {
    Stage.TOPIC_INIT: StageContract(
        stage=Stage.TOPIC_INIT,
        input_files=(),
        output_files=("goal.md", "hardware_profile.json"),
        dod="SMART goal statement with topic, scope, and constraints",
    ),
}
'''
        tree = ast.parse(source)
        dict_node = tree.body[0].value  # type: ignore[assignment]
        parsed = parse_contracts_dict(
            dict_node,
            {"Stage"},
            {"TOPIC_INIT": 1},
        )
        assert parsed[1][3] == "SMART goal statement with topic, scope, and constraints"


class TestArtifactSemantics:
    def test_goal_md_has_field_semantics(self):
        desc = describe_output_file("goal.md")
        assert "SMART" in desc
        assert "goal.md" in ARTIFACT_SEMANTICS

    def test_hardware_profile_has_field_semantics(self):
        desc = describe_output_file("hardware_profile.json")
        assert "gpu_type" in desc
        assert "vram_mb" in desc


class TestArcContractExtraction:
    def test_topic_init_contract_from_arc_repo(self):
        if not (ARC_REPO / "researchclaw" / "pipeline" / "contracts.py").is_file():
            return
        graph = ArcExtractor().extract(ARC_REPO)
        contract = graph.contracts.get(1)
        assert contract is not None
        assert "goal.md" in contract.output_files
        assert "hardware_profile.json" in contract.output_files
        assert "SMART" in contract.dod

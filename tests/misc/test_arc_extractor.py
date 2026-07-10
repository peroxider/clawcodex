"""Tests for F-50-G ArcExtractor and generic dict-comp / CONTRACTS parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from extensions.sop_converter.workflow_mode.discriminator import _detect_adapter_name
from extensions.sop_converter.workflow_mode.extractors.adapters.arc import (
    ArcExtractor,
    resolve_arc_pipeline_dir,
)
from extensions.sop_converter.workflow_mode.extractors.adapters.generic import GenericPipelineExtractor
from extensions.sop_converter.workflow_mode.extractors.registry import ExtractorRegistry
from extensions.sop_converter.workflow_mode.scan_context import SourceScanContext

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ARC_FIXTURE = FIXTURES / "fixture_arc_project"
ARC_REPO = Path(r"D:\projects\AutoResearchClaw")


class TestArcExtractorFixture:
    def test_resolve_pipeline_dir(self):
        assert resolve_arc_pipeline_dir(ARC_FIXTURE) == ARC_FIXTURE.resolve()

    def test_registry_returns_arc_for_arc_name(self):
        ext = ExtractorRegistry.get_extractor(ARC_FIXTURE, name="arc")
        assert isinstance(ext, ArcExtractor)

    def test_arc_fixture_graph(self):
        ext = ArcExtractor(mode="fwa")
        graph = ext.extract(ARC_FIXTURE)
        assert len(graph.stages) == 3
        assert len(graph.transitions) == 2
        assert graph.gates[2].stage_id == 2
        assert graph.contracts[1].output_files == ["normalized.json"]
        assert graph.stages[0].entry_function == "_execute_preprocess"
        assert graph.stages[0].file_path == "executor.py"

    def test_generic_dict_comp_transitions(self):
        scan = SourceScanContext.build(ARC_FIXTURE)
        ext = GenericPipelineExtractor(scan=scan, mode="fwa")
        transitions = ext.extract_transitions(ARC_FIXTURE)
        assert len(transitions) == 2
        assert (1, 2) in {(t.from_stage, t.to_stage) for t in transitions}

    def test_generic_contracts_dict(self):
        scan = SourceScanContext.build(ARC_FIXTURE)
        ext = GenericPipelineExtractor(scan=scan, mode="fwa")
        contracts = ext.extract_contracts(ARC_FIXTURE)
        assert contracts[1].output_files == ["normalized.json"]
        assert contracts[3].input_files == ["analysis.json"]


@pytest.mark.skipif(not ARC_REPO.is_dir(), reason="AutoResearchClaw not checked out locally")
class TestArcExtractorRealRepo:
    def test_detect_adapter_arc(self):
        assert _detect_adapter_name(ARC_REPO) == "arc"

    def test_full_pipeline_extraction(self):
        ext = ArcExtractor(mode="fwa")
        graph = ext.extract(ARC_REPO)
        assert len(graph.stages) == 23
        assert len(graph.transitions) == 22
        assert len(graph.contracts) == 23
        assert graph.gates
        assert graph.stages[0].entry_function == "_execute_topic_init"
        assert graph.extraction_quality == "full"

    def test_registry_auto_select_arc(self):
        ext = ExtractorRegistry.get_extractor(ARC_REPO)
        assert isinstance(ext, ArcExtractor)

"""Regression tests for the production PatternExtractor package boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_examples_namespace_reexports_production_types() -> None:
    from examples.sdk_extractor import PatternExtractor as CompatibilityExtractor
    from examples.sdk_extractor import PipelineConfig as CompatibilityConfig
    from extensions.sop_converter.workflow_mode.extractors.pattern import (
        PatternExtractor,
        PipelineConfig,
    )

    assert CompatibilityExtractor is PatternExtractor
    assert CompatibilityConfig is PipelineConfig


def test_production_modules_do_not_import_examples() -> None:
    production_files = (
        REPO_ROOT
        / "extensions"
        / "sop_converter"
        / "workflow_mode"
        / "extractors"
        / "pattern.py",
        REPO_ROOT
        / "extensions"
        / "sop_converter"
        / "workflow_mode"
        / "extractors"
        / "adapters"
        / "arc.py",
    )

    for path in production_files:
        source = path.read_text(encoding="utf-8")
        assert "from examples" not in source
        assert "import examples" not in source


def test_capability_import_outside_repo_does_not_load_arc_support(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from extensions.sop_converter.workflow_mode.capability import (
    StageCapabilityMapper,
    ensure_stage_skills,
)

skills = [object()]
assert ensure_stage_skills(object(), [], skills, Path.cwd()) is skills
assert StageCapabilityMapper.__name__ == "StageCapabilityMapper"
assert "extensions.sop_converter.workflow_mode.capability.arc_mapper" not in sys.modules
assert "extensions.sop_converter.workflow_mode.extractors.adapters.arc" not in sys.modules
"""
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

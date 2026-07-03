"""ArcExtractor — AutoResearchClaw (ARC) workflow extractor (F-50-G).

Extracts stages/transitions/gates/decisions/contracts from projects following
the ARC convention:

* ``.arc-workflow`` marker file in the project root (optional but preferred).
* Stage enum classes following the ``*Stage*`` / ``*Step*`` naming pattern.
* Per-stage implementation files under ``stage_impls/`` or similar directory.
``"""

from __future__ import annotations

import logging
from pathlib import Path

from ...ast_helpers import (
    _to_kebab,
    extract_docstring_first_para,
    find_enum_classes,
    get_enum_members,
    parse_ast,
    parse_contracts_dict,
    walk_py_files,
)
from ..base import WorkflowExtractorBase
from ..models import (
    DecisionSpec,
    ExtractedStage,
    GateSpec,
    OutcomeSpec,
    StageContract,
    Transition,
)
from .generic import GenericPipelineExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ARC-specific paths
# ---------------------------------------------------------------------------

_ARC_STAGE_DIR_NAMES = ("stage_impls", "stages", "steps", "pipeline")
_ARC_WORKFLOW_MARKER = ".arc-workflow"


class ArcExtractor(WorkflowExtractorBase):
    """Workflow extractor for AutoResearchClaw (ARC) projects.

    Detects the ARC project convention (``.arc-workflow`` marker or
    ``autoresearch``/``arc`` in the directory name) and extracts a
    ``WorkflowGraph`` from stage enums, implementation files, and
    contract definitions.

    Falls back to ``GenericPipelineExtractor`` when ARC-specific patterns
    are not found, ensuring robust extraction for any Python project.
    """

    def __init__(
        self,
        scan=None,
        *,
        mode: str = "fwa",
        allow_coarse: bool = False,
    ) -> None:
        super().__init__(scan=scan, mode=mode, allow_coarse=allow_coarse)
        self._fallback: GenericPipelineExtractor | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_fallback(self, source_dir: Path) -> GenericPipelineExtractor:
        """Lazy-initialize a fallback generic extractor."""
        if self._fallback is None:
            self._fallback = GenericPipelineExtractor(
                scan=self._scan,
                mode=self._mode,
                allow_coarse=self._allow_coarse,
            )
        return self._fallback

    def _is_arc_project(self, source_dir: Path) -> bool:
        """Check if the source directory is an ARC project."""
        name_lower = source_dir.name.lower()
        if "autoresearch" in name_lower or "arc" in name_lower:
            return True
        if (source_dir / _ARC_WORKFLOW_MARKER).is_file():
            return True
        # Check for ARC stage directories
        for d in _ARC_STAGE_DIR_NAMES:
            if (source_dir / d).is_dir():
                return True
        return False

    def _find_stage_enum(self, source_dir: Path):
        """Find the primary stage enum class across all Python files."""
        best_name: str | None = None
        best_count = 0
        for py_file in walk_py_files(source_dir):
            tree = parse_ast(py_file)
            if tree is None:
                continue
            for cls in find_enum_classes(tree):
                members = get_enum_members(cls)
                if len(members) >= best_count:
                    best_name = cls.name
                    best_count = len(members)
        return best_name

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def extract_stages(self, source_dir: Path) -> list[ExtractedStage]:
        if not self._is_arc_project(source_dir):
            return self._get_fallback(source_dir).extract_stages(source_dir)

        stages: list[ExtractedStage] = []
        primary_enum = self._find_stage_enum(source_dir)

        # ── Phase 1: extract from stage enum ──
        if primary_enum:
            for py_file in walk_py_files(source_dir):
                tree = parse_ast(py_file)
                if tree is None:
                    continue
                for cls in find_enum_classes(tree):
                    if cls.name != primary_enum:
                        continue
                    members = get_enum_members(cls)
                    doc = extract_docstring_first_para(cls)
                    for idx, (member_name, member_value) in enumerate(
                        members.items()
                    ):
                        stages.append(
                            ExtractedStage(
                                id=len(stages) + 1,
                                name=_to_kebab(member_name),
                                label=member_name,
                                source_class=cls.name,
                                source_value=member_value,
                                file_path=str(py_file),
                                description=doc or "",
                                inferred=False,
                            )
                        )

        # ── Phase 2: fall back to directory-based detection ──
        if not stages:
            for stage_dir_name in _ARC_STAGE_DIR_NAMES:
                stage_dir = source_dir / stage_dir_name
                if not stage_dir.is_dir():
                    continue
                for py_file in sorted(stage_dir.glob("*.py")):
                    if py_file.name.startswith("_"):
                        continue
                    tree = parse_ast(py_file)
                    doc = ""
                    if tree:
                        doc = extract_docstring_first_para(tree)
                    stages.append(
                        ExtractedStage(
                            id=len(stages) + 1,
                            name=py_file.stem,
                            label=py_file.stem.replace("_", " ").title(),
                            source_class=None,
                            file_path=str(py_file),
                            description=doc or "",
                            inferred=False,
                        )
                    )

        # ── Phase 3: final fallback to generic ──
        if not stages:
            return self._get_fallback(source_dir).extract_stages(source_dir)

        return stages

    def extract_transitions(self, source_dir: Path) -> list[Transition]:
        if not self._is_arc_project(source_dir):
            return self._get_fallback(source_dir).extract_transitions(source_dir)

        stages = self.extract_stages(source_dir)
        if len(stages) <= 1:
            return []

        # Default linear chain: stage 1 → stage 2 → stage 3 → …
        transitions: list[Transition] = []
        for i in range(len(stages) - 1):
            transitions.append(
                Transition(
                    from_stage=stages[i].id,
                    to_stage=stages[i + 1].id,
                    is_default=True,
                )
            )
        return transitions

    def extract_gates(self, source_dir: Path) -> dict[int, GateSpec]:
        if not self._is_arc_project(source_dir):
            return self._get_fallback(source_dir).extract_gates(source_dir)
        # ARC convention: default manual gates between stages
        stages = self.extract_stages(source_dir)
        gates: dict[int, GateSpec] = {}
        for stage in stages:
            if stage.id < len(stages):
                gates[stage.id] = GateSpec(
                    stage_id=stage.id,
                    approval_mode="manual",
                    description=f"Gate before {stage.label}",
                )
        return gates

    def extract_decisions(self, source_dir: Path) -> dict[int, DecisionSpec]:
        if not self._is_arc_project(source_dir):
            return self._get_fallback(source_dir).extract_decisions(source_dir)
        return {}

    def extract_contracts(self, source_dir: Path) -> dict[int, StageContract]:
        if not self._is_arc_project(source_dir):
            return self._get_fallback(source_dir).extract_contracts(source_dir)

        contracts: dict[int, StageContract] = {}
        stages = self.extract_stages(source_dir)

        # Parse contract definitions from stage implementation files
        for stage in stages:
            if not stage.file_path:
                continue
            fp = Path(stage.file_path)
            if not fp.exists():
                continue
            tree = parse_ast(fp)
            if tree is None:
                continue

            contract_dict = parse_contracts_dict(tree)
            if contract_dict:
                contracts[stage.id] = StageContract(
                    stage_id=stage.id,
                    input_files=contract_dict.get("input_files", []),
                    output_files=contract_dict.get("output_files", []),
                    dod=contract_dict.get("dod", ""),
                    source_class=stage.source_class,
                )

        return contracts

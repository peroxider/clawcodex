"""ArcExtractor — AutoResearchClaw (ARC) workflow extractor (F-50-G).

Extracts stages/transitions/gates/decisions/contracts from projects following
the ARC convention:

* ``.arc-workflow`` marker file in the project root (optional but preferred).
* Stage enum classes following the ``*Stage*`` / ``*Step*`` naming pattern.
* Per-stage implementation files under ``stage_impls/`` or similar directory.
``"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from ...ast_helpers import (
    _to_kebab,
    extract_docstring_first_para,
    find_dict_mapping_assignments,
    find_enum_classes,
    find_frozenset_assigns,
    get_enum_members_ordered,
    parse_ast,
    parse_contracts_dict,
    parse_enum_dict_mapping_from_expr,
    parse_enum_to_name_dict,
    parse_frozenset_members,
    parse_stage_sequence_from_expr,
    parse_string_to_stage_dict,
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

_EXECUTOR_TABLE_NAMES = ("_STAGE_EXECUTORS", "STAGE_EXECUTORS")


# ---------------------------------------------------------------------------
# ARC-specific paths
# ---------------------------------------------------------------------------

def resolve_arc_pipeline_dir(source_dir: Path) -> Path | None:
    """Locate ``researchclaw/pipeline`` (or equivalent) under *source_dir*."""
    root = source_dir.resolve()
    candidates = [
        root,
        root / "researchclaw" / "pipeline",
        root / "pipeline",
    ]
    for candidate in candidates:
        if (candidate / "stages.py").is_file() and (candidate / "contracts.py").is_file():
            return candidate
    for stages_py in root.rglob("stages.py"):
        parent = stages_py.parent
        if parent.name == "pipeline" and (parent / "contracts.py").is_file():
            return parent
    return None


class ArcExtractor(WorkflowExtractorBase):
    """Extract WorkflowGraph from AutoResearchClaw pipeline modules."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pipeline_dir: Path | None = None
        self._enum_class: str | None = None
        self._member_to_value: dict[str, int] = {}
        self._member_order: list[tuple[str, int]] = []
        self._stage_sequence: list[int] = []
        self._executor_rel: str | None = None
        self._executor_by_stage: dict[int, str] = {}

    def _bootstrap(self, source_dir: Path) -> bool:
        pipeline = resolve_arc_pipeline_dir(source_dir)
        if pipeline is None:
            return False
        self._pipeline_dir = pipeline

        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return False

        for cls in find_enum_classes(stages_tree):
            members = get_enum_members_ordered(cls)
            if not members:
                continue
            self._enum_class = cls.name
            self._member_order = members
            self._member_to_value = dict(members)
            break

        if not self._member_to_value:
            return False

        enum_names = {self._enum_class} if self._enum_class else set()
        module_assigns = dict(find_dict_mapping_assignments(stages_tree))
        if "STAGE_SEQUENCE" in module_assigns:
            self._stage_sequence = parse_stage_sequence_from_expr(
                module_assigns["STAGE_SEQUENCE"],
                enum_class_names=enum_names,
                enum_members_ordered=self._member_order,
                module_assigns=module_assigns,
            )
        if not self._stage_sequence:
            self._stage_sequence = [v for _, v in self._member_order]

        executor_path = pipeline / "executor.py"
        if executor_path.is_file():
            self._executor_rel = executor_path.relative_to(source_dir.resolve()).as_posix()
            exec_tree = parse_ast(executor_path)
            if exec_tree is not None:
                for var_name, dict_expr in find_dict_mapping_assignments(exec_tree):
                    if var_name in _EXECUTOR_TABLE_NAMES and isinstance(dict_expr, ast.Dict):
                        self._executor_by_stage = parse_enum_to_name_dict(
                            dict_expr, enum_names, self._member_to_value,
                        )
        return True

    def _enum_names(self) -> set[str]:
        return {self._enum_class} if self._enum_class else set()

    def extract_stages(self, source_dir: Path) -> list[ExtractedStage]:
        if not self._bootstrap(source_dir):
            return []

        pipeline = self._pipeline_dir
        assert pipeline is not None
        stages_tree = parse_ast(pipeline / "stages.py")
        stage_enum_cls = None
        if stages_tree:
            for cls in find_enum_classes(stages_tree):
                if cls.name == self._enum_class:
                    stage_enum_cls = cls
                    break

        desc = extract_docstring_first_para(stage_enum_cls) if stage_enum_cls else ""
        stages: list[ExtractedStage] = []
        for name, value in self._member_order:
            entry_fn = self._executor_by_stage.get(value)
            stages.append(
                ExtractedStage(
                    id=value,
                    name=_to_kebab(name),
                    label=name,
                    source_class=self._enum_class,
                    source_value=value,
                    file_path=self._executor_rel,
                    entry_function=entry_fn,
                    description=desc,
                )
            )
        return stages

    def extract_transitions(self, source_dir: Path) -> list[Transition]:
        if not self._bootstrap(source_dir):
            return []

        pipeline = self._pipeline_dir
        assert pipeline is not None
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return []

        enum_names = self._enum_names()
        transitions: list[Transition] = []
        seen: set[tuple[int, int]] = set()

        for var_name, dict_expr in find_dict_mapping_assignments(stages_tree):
            if "NEXT_STAGE" in var_name.upper() or "PREVIOUS_STAGE" in var_name.upper():
                pairs = parse_enum_dict_mapping_from_expr(
                    dict_expr,
                    enum_names,
                    self._member_to_value,
                    stage_sequence=self._stage_sequence,
                )
                for from_id, to_id in pairs:
                    key = (from_id, to_id)
                    if key not in seen:
                        seen.add(key)
                        transitions.append(
                            Transition(
                                from_stage=from_id,
                                to_stage=to_id,
                                condition=var_name,
                                is_default=True,
                            )
                        )

        if not transitions and self._stage_sequence:
            for idx, sid in enumerate(self._stage_sequence):
                if idx + 1 < len(self._stage_sequence):
                    nxt = self._stage_sequence[idx + 1]
                    transitions.append(
                        Transition(
                            from_stage=sid,
                            to_stage=nxt,
                            condition="STAGE_SEQUENCE",
                            is_default=True,
                        )
                    )
        return transitions

    def extract_gates(self, source_dir: Path) -> dict[int, GateSpec]:
        if not self._bootstrap(source_dir):
            return {}

        pipeline = self._pipeline_dir
        assert pipeline is not None
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return {}

        gates: dict[int, GateSpec] = {}
        enum_names = self._enum_names()
        for var_name, value_expr in find_frozenset_assigns(stages_tree):
            stage_ids = parse_frozenset_members(
                value_expr, enum_names, self._member_to_value,
            )
            for sid in stage_ids:
                gates[sid] = GateSpec(
                    stage_id=sid,
                    approval_mode="manual",
                    description=f"Gate from {var_name}",
                    source_name=var_name,
                )
        return gates

    def extract_decisions(self, source_dir: Path) -> dict[int, DecisionSpec]:
        if not self._bootstrap(source_dir):
            return {}

        pipeline = self._pipeline_dir
        assert pipeline is not None
        stages_tree = parse_ast(pipeline / "stages.py")
        if stages_tree is None:
            return {}

        enum_names = self._enum_names()
        decisions: dict[int, DecisionSpec] = {}

        for var_name, dict_expr in find_dict_mapping_assignments(stages_tree):
            if not isinstance(dict_expr, ast.Dict):
                continue
            if "DECISION_ROLLBACK" not in var_name.upper():
                continue
            rollback = parse_string_to_stage_dict(
                dict_expr, enum_names, self._member_to_value,
            )
            decision_stage = self._member_to_value.get("RESEARCH_DECISION")
            if decision_stage is None:
                continue
            outcomes = {
                name: OutcomeSpec(next_stage=sid, max_times=2)
                for name, sid in rollback.items()
            }
            decisions[decision_stage] = DecisionSpec(
                stage_id=decision_stage,
                outcomes=outcomes,
                source_func=var_name,
                inferred=False,
            )
        return decisions

    def extract_contracts(self, source_dir: Path) -> dict[int, StageContract]:
        if not self._bootstrap(source_dir):
            return {}

        pipeline = self._pipeline_dir
        assert pipeline is not None
        contracts_path = pipeline / "contracts.py"
        tree = parse_ast(contracts_path)
        if tree is None:
            return {}

        enum_names = self._enum_names()
        contracts: dict[int, StageContract] = {}
        for var_name, dict_expr in find_dict_mapping_assignments(tree):
            if not isinstance(dict_expr, ast.Dict):
                continue
            if "CONTRACT" not in var_name.upper():
                continue
            parsed = parse_contracts_dict(
                dict_expr, enum_names, self._member_to_value,
            )
            for stage_id, (inp, out, call_name, dod) in parsed.items():
                contracts[stage_id] = StageContract(
                    stage_id=stage_id,
                    input_files=inp,
                    output_files=out,
                    dod=dod,
                    source_class=call_name,
                )
        return contracts

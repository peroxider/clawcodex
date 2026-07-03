"""Map WorkflowGraph stages to skills, agents, and capability profiles."""

from __future__ import annotations

import logging
from pathlib import Path

from extensions.sop_converter.skill_grouper import SkillSpec
from extensions.sop_converter.source_parser import SourceComponent

from ..extractors.adapters.arc import resolve_arc_pipeline_dir
from ..extractors.models import ExtractedStage, WorkflowGraph
from ..scan_context import SourceScanContext
from .analyzer import analyze_stage_sources
from .arc_mapper import (
    arc_stage_impl_rel_path,
    is_executor_module_path,
    resolve_arc_stage_impl_path,
)
from .models import StageAgentMap, StageCapabilityProfile

logger = logging.getLogger(__name__)


def _to_kebab(name: str) -> str:
    return name.replace("_", "-").lower()


def _stage_impl_path(
    source_dir: Path,
    stage: ExtractedStage,
    *,
    skip_executor: bool = False,
) -> Path | None:
    if stage.file_path and not (skip_executor and is_executor_module_path(stage.file_path)):
        p = source_dir / stage.file_path
        if p.is_file():
            return p
    for sub in ("stage_impls", "stages", "pipeline"):
        candidate = source_dir / sub / f"{stage.name.replace('-', '_')}.py"
        if candidate.is_file():
            return candidate
        candidate = source_dir / sub / f"{stage.name}.py"
        if candidate.is_file():
            return candidate
    return None


def _match_skill_by_stage_name(stage: ExtractedStage, skills: list[SkillSpec]) -> SkillSpec | None:
    if not stage.name:
        return None
    for skill in skills:
        if skill.name == stage.name or _to_kebab(skill.name) == stage.name:
            return skill
    return None


def _match_skill_by_filename(stage: ExtractedStage, skills: list[SkillSpec]) -> SkillSpec | None:
    if not stage.file_path:
        return None
    stem = Path(stage.file_path).stem.replace("_", "-").lower()
    for skill in skills:
        if skill.name == stem or _to_kebab(skill.name) == stem:
            return skill
    if stage.name:
        for skill in skills:
            if skill.name == stage.name or _to_kebab(skill.name) == stage.name:
                return skill
    return None


def _match_skill_by_operations(
    stage: ExtractedStage,
    components: list[SourceComponent],
    skills: list[SkillSpec],
    impl_path: Path | None,
) -> SkillSpec | None:
    if not impl_path or not impl_path.is_file():
        return None

    try:
        source = impl_path.read_text(encoding="utf-8")
    except OSError:
        return None

    func_names: set[str] = set()
    if stage.entry_function:
        func_names.add(stage.entry_function)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            name = stripped.split("(")[0].replace("def ", "").replace("async ", "").strip()
            if not name.startswith("_") or name == stage.entry_function:
                func_names.add(name)

    op_names: set[str] = set()
    for comp in components:
        for op in comp.operations:
            op_names.add(op.name)
            if op.class_name:
                op_names.add(f"{op.class_name}.{op.name}")

    best: SkillSpec | None = None
    best_score = 0
    for skill in skills:
        overlap = sum(1 for t in skill.allowed_tools if t.split(".")[-1] in func_names or t in func_names)
        if overlap > best_score:
            best_score = overlap
            best = skill
    return best if best_score > 0 else None


def _match_skill_by_io(
    stage: ExtractedStage,
    graph: WorkflowGraph,
    skills: list[SkillSpec],
    components: list[SourceComponent],
) -> SkillSpec | None:
    contract = graph.contracts.get(stage.id)
    if not contract or not contract.output_files:
        return None

    return_types: dict[str, str] = {}
    for comp in components:
        for op in comp.operations:
            if op.return_type:
                return_types[op.name] = op.return_type

    best: SkillSpec | None = None
    best_score = 0
    for skill in skills:
        score = 0
        for tool in skill.allowed_tools:
            op_key = tool.split(".")[-1]
            rt = return_types.get(op_key, "")
            for pattern in contract.output_files:
                if pattern in rt or rt in pattern:
                    score += 1
        if score > best_score:
            best_score = score
            best = skill
    return best if best_score > 0 else None


class StageCapabilityMapper:
    """Analyze stages and produce StageAgentMap."""

    def map(
        self,
        graph: WorkflowGraph,
        components: list[SourceComponent],
        skills: list[SkillSpec],
        *,
        scan: SourceScanContext | None = None,
    ) -> StageAgentMap:
        source_dir = Path(graph.source_dir)
        pipeline_dir = resolve_arc_pipeline_dir(source_dir)
        is_arc = pipeline_dir is not None
        by_stage_id: dict[int, StageCapabilityProfile] = {}
        skill_to_agent: dict[str, str] = {}

        for stage in graph.stages:
            impl_path: Path | None = None
            if is_arc and pipeline_dir is not None:
                impl_path = resolve_arc_stage_impl_path(source_dir, pipeline_dir, stage)
            if impl_path is None:
                impl_path = _stage_impl_path(
                    source_dir, stage, skip_executor=is_arc and bool(stage.entry_function),
                )

            paths = [impl_path] if impl_path else []
            profile = analyze_stage_sources(stage.id, paths, stage_name=stage.name)
            if stage.entry_function:
                profile.entry_function = stage.entry_function
            if is_arc and pipeline_dir is not None:
                impl_rel = arc_stage_impl_rel_path(source_dir, pipeline_dir, stage)
                if impl_rel:
                    profile.notes.append(f"impl: {impl_rel}")
            elif stage.file_path and not impl_path:
                profile.notes.append(f"executor: {stage.file_path}")

            matched = _match_skill_by_stage_name(stage, skills) if is_arc else None
            confidence = 0.95 if matched else 0.0

            if not matched:
                matched = _match_skill_by_filename(stage, skills)
                confidence = 0.9 if matched else 0.0

            if not matched:
                matched = _match_skill_by_operations(stage, components, skills, impl_path)
                if matched:
                    confidence = 0.8 if is_arc else 0.7

            if not matched:
                matched = _match_skill_by_io(stage, graph, skills, components)
                if matched:
                    confidence = 0.5

            if matched:
                profile.mapped_skill = matched.name
                profile.mapped_agent = f"{matched.name}-agent"
                profile.mapping_confidence = confidence
                profile.recommended_tools = list(matched.allowed_tools)
                skill_to_agent[matched.name] = profile.mapped_agent
            else:
                fallback_agent = f"{stage.name}-agent"
                profile.mapped_agent = fallback_agent
                profile.notes.append(f"TODO: unmapped stage {stage.id}")
                profile.mapping_confidence = 0.0

            stage.capability_profile = profile
            by_stage_id[stage.id] = profile

        return StageAgentMap(by_stage_id=by_stage_id, skill_to_agent=skill_to_agent)

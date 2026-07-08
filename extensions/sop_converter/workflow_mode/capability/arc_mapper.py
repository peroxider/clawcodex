"""ARC-specific stage implementation path helpers."""

from __future__ import annotations

from pathlib import Path

from extensions.sop_converter.skill_grouper import SkillSpec

from ..extractors.models import ExtractedStage
from ..extractors.models import WorkflowGraph


_EXECUTOR_MODULE_NAMES = {"executor.py", "pipeline.py", "runner.py", "workflow.py"}


def is_executor_module_path(path: str | Path | None) -> bool:
    """Return whether a stage path points at a shared executor module."""

    if path is None:
        return False
    return Path(path).name in _EXECUTOR_MODULE_NAMES


def resolve_arc_stage_impl_path(
    source_dir: Path,
    pipeline_dir: Path,
    stage: ExtractedStage,
) -> Path | None:
    """Resolve the concrete implementation file for an ARC stage."""

    candidates: list[Path] = []
    if stage.file_path and not is_executor_module_path(stage.file_path):
        candidates.append(source_dir / stage.file_path)

    stage_slug = stage.name.replace("-", "_")
    label_slug = (stage.label or stage.name).replace("-", "_").lower()
    for stem in dict.fromkeys((stage_slug, label_slug)):
        candidates.append(pipeline_dir / f"{stem}.py")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def arc_stage_impl_rel_path(
    source_dir: Path,
    pipeline_dir: Path,
    stage: ExtractedStage,
) -> str | None:
    """Return a display-friendly relative implementation path for an ARC stage."""

    impl = resolve_arc_stage_impl_path(source_dir, pipeline_dir, stage)
    if impl is None:
        return None
    try:
        return impl.relative_to(source_dir).as_posix()
    except ValueError:
        return impl.as_posix()


def ensure_arc_stage_skills(
    graph: WorkflowGraph,
    components: list[object],
    coarse_skills: list[SkillSpec],
    source_dir: Path,
) -> list[SkillSpec]:
    """Ensure ARC stages have stable stage-named skills."""

    skills = list(coarse_skills)
    existing = {skill.name for skill in skills}
    fallback_tools: list[str] = []
    for skill in coarse_skills:
        for tool in skill.allowed_tools:
            if tool not in fallback_tools:
                fallback_tools.append(tool)

    for stage in graph.stages:
        skill_name = f"{stage.name}-skill"
        if skill_name in existing:
            continue
        description = stage.description or f"Execute the {stage.label or stage.name} stage."
        skills.append(
            SkillSpec(
                name=skill_name,
                description=description,
                allowed_tools=list(fallback_tools),
                when_to_use=f"Use for the {stage.label or stage.name} workflow stage.",
            )
        )
        existing.add(skill_name)
    return skills

"""Composite Tools — macro-level tools that orchestrate multiple atomic operations.

A composite tool is a higher-level abstraction that bundles together multiple
atomic ``AgentToolSpec`` operations into a single registered tool with its own
workflow.yaml sidecar.

The builtin composite tools (``agent_teams``, ``pipeline_execute``, …) serve
as the macro orchestration layer that stage agents reference.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from clawcodex_ext.agent.tool_authoring.persistence import (
    bundle_tool_dir,
    save_spec,
)
from clawcodex_ext.agent.tool_authoring.spec import AgentToolSpec

from .builtin import builtin_composite_tools
from .models import CompositeStage, CompositeToolSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def to_kebab_case(name: str) -> str:
    """Convert a dotted or CamelCase name to kebab-case."""
    import re
    name = re.sub(r"([a-z])([A-Z])", r"\1-\2", name)
    name = re.sub(r"[._]+", "-", name)
    return name.lower()


def register_composite_tools(
    *,
    persist: bool = True,
    bundle_dir: Path | None = None,
    sdk_source_dir: str = "",
) -> dict[str, str]:
    """Register all built-in composite tools as ``AgentToolSpec`` specs.

    Args:
        persist: If True, save each spec to disk via ``save_spec()``.
        bundle_dir: Optional bundle directory for per-bundle tool storage.
        sdk_source_dir: Unused (reserved for future SDK introspection).

    Returns:
        A mapping from composite tool names to kebab-case registered names
        (e.g. ``{"AgentTeams": "agent-teams"}``).
    """
    tool_dir = bundle_tool_dir(bundle_dir) if bundle_dir is not None else None
    name_map: dict[str, str] = {}

    for spec in builtin_composite_tools():
        tool_spec = _composite_to_agent_tool_spec(spec, bundle_dir=bundle_dir)
        if persist:
            try:
                save_spec(tool_spec, tool_dir=tool_dir)
            except Exception as exc:
                logger.warning("Failed to persist composite tool %s: %s", spec.name, exc)
                continue
        name_map[spec.name] = tool_spec.name

    return name_map


def _composite_to_agent_tool_spec(
    spec: CompositeToolSpec,
    *,
    bundle_dir: Path | None = None,
) -> AgentToolSpec:
    """Convert a ``CompositeToolSpec`` into an ``AgentToolSpec``.

    The generated tool uses ``call_type="bash"`` and delegates to a helper
    script that prints the composite tool's stage list as JSON, allowing the
    agent to decide delegation order.
    """
    stages_json = json.dumps(
        [
            {
                "name": s.name,
                "description": s.description,
                "agent_ref": s.agent_ref,
                "expected_duration_s": s.expected_duration_s,
            }
            for s in spec.stages
        ],
        ensure_ascii=False,
    )

    # The call_impl is a bash one-liner that prints the stage manifest.
    # The agent reads this to understand the macro workflow.
    call_impl = (
        f"echo 'Composite tool: {spec.name}' && "
        f"echo 'Stages: {stages_json}'"
    )

    bundle_id = bundle_dir.name if bundle_dir else None

    return AgentToolSpec(
        name=to_kebab_case(spec.name),
        description=spec.description,
        input_schema=spec.input_schema,
        call_type="bash",
        call_impl=call_impl,
        tags=spec.tags,
        aliases=spec.aliases,
        source="composite-tool",
        bundle_id=bundle_id,
    )


# ---------------------------------------------------------------------------
# Workflow YAML emission
# ---------------------------------------------------------------------------


def emit_composite_workflow_yaml(
    spec: CompositeToolSpec,
    output_dir: str | Path,
    *,
    project_name: str = "",
) -> Path | None:
    """Emit a ``workflow.yaml`` sidecar for a composite tool.

    The generated YAML describes the composite tool as a linear sequence of
    stages suitable for the orchestrator engine.

    Args:
        spec: The composite tool spec.
        output_dir: Directory to write ``workflow.yaml`` into.
        project_name: Optional project name (used as workflow name prefix).

    Returns:
        The path to the written ``workflow.yaml``, or ``None`` if no stages
        are defined.
    """
    if not spec.stages:
        return None

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    workflow_name = project_name or spec.name
    stages_out: list[dict[str, Any]] = []

    for i, stage in enumerate(spec.stages):
        deps: list[int] = [i] if i > 0 else []
        stage_dict: dict[str, Any] = {
            "id": i + 1,
            "name": stage.name,
            "description": stage.description,
            "agent_ref": stage.agent_ref or to_kebab_case(stage.name),
            "depends_on": deps,
            "config": {"timeout_s": stage.expected_duration_s},
        }
        stages_out.append(stage_dict)

    data: dict[str, Any] = {
        "name": workflow_name,
        "version": "1.0",
        "description": spec.description,
        "stages": stages_out,
        "config": {"workspace": "."},
    }

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not available; writing workflow.yaml as JSON")
        out_path = out / "workflow.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Try to write a human-readable header
        f.write(f"# Composite tool: {spec.name}\n")
        return out_path

    import yaml
    out_path = out / "workflow.yaml"
    header = f"# Composite tool: {spec.name}\n"
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    out_path.write_text(header + body, encoding="utf-8")
    return out_path


__all__ = [
    "CompositeToolSpec",
    "CompositeStage",
    "register_composite_tools",
    "emit_composite_workflow_yaml",
    "to_kebab_case",
]

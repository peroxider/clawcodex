"""Validate MacroDefinition before convert persist/register."""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..composite_runtime import CompositeWorkflowSpec, CompositeWorkflowStep
from .errors import MacroConvertError
from .models import MacroDefinition

_INPUT_REF = re.compile(r"^\$input\.([A-Za-z_][\w]*)$")
_STEP_OUTPUT_REF = re.compile(
    r"^\$steps\.([A-Za-z_][\w]*)\.output(?:\.([A-Za-z_][\w]*))?$"
)
_FORBIDDEN_STEP_TOOLS = frozenset(
    {
        "register-macro-workflow",
        "RegisterMacroWorkflow",
    }
)


def workflow_dict_to_spec(macro: MacroDefinition) -> CompositeWorkflowSpec:
    """Convert MacroDefinition.workflow mapping into CompositeWorkflowSpec."""
    workflow = macro.workflow
    inputs = workflow.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise MacroConvertError(
            "macro_schema_invalid",
            "workflow.inputs must be a mapping",
            manifest=str(macro.provenance.get("manifest") or macro.name),
            field="workflow.inputs",
        )
    steps_raw = workflow.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise MacroConvertError(
            "macro_schema_invalid",
            "workflow.steps must be a non-empty list",
            manifest=str(macro.provenance.get("manifest") or macro.name),
            field="workflow.steps",
        )
    steps: list[CompositeWorkflowStep] = []
    for index, raw in enumerate(steps_raw):
        if not isinstance(raw, dict):
            raise MacroConvertError(
                "macro_schema_invalid",
                f"workflow.steps[{index}] must be a mapping",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                field=f"workflow.steps[{index}]",
            )
        step_id = str(raw.get("id") or "").strip()
        if not step_id:
            raise MacroConvertError(
                "macro_schema_invalid",
                "step id is required",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                field=f"workflow.steps[{index}].id",
            )
        kind = str(raw.get("kind") or "tool")
        if kind != "tool":
            raise MacroConvertError(
                "macro_step_kind_forbidden",
                "bundle macros may only contain kind=tool steps",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                step_id=step_id,
                field="kind",
            )
        callable_ref = str(raw.get("callable_ref") or "").strip()
        if not callable_ref:
            raise MacroConvertError(
                "macro_callable_missing",
                "callable_ref is required",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                step_id=step_id,
                field="callable_ref",
            )
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            raise MacroConvertError(
                "macro_schema_invalid",
                "step args must be a mapping",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                step_id=step_id,
                field="args",
            )
        output_schema = raw.get("output_schema")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise MacroConvertError(
                "macro_schema_invalid",
                "output_schema must be a mapping when present",
                manifest=str(macro.provenance.get("manifest") or macro.name),
                step_id=step_id,
                field="output_schema",
            )
        steps.append(
            CompositeWorkflowStep(
                id=step_id,
                kind="tool",
                callable_ref=callable_ref,
                args=dict(args),
                visibility="public",
                output_schema=output_schema,
            )
        )
    outputs = workflow.get("outputs") or {}
    if not isinstance(outputs, dict):
        raise MacroConvertError(
            "macro_schema_invalid",
            "workflow.outputs must be a mapping",
            manifest=str(macro.provenance.get("manifest") or macro.name),
            field="workflow.outputs",
        )
    normalized_inputs: dict[str, dict[str, Any]] = {}
    for key, schema in inputs.items():
        if isinstance(schema, dict):
            normalized_inputs[str(key)] = dict(schema)
        else:
            normalized_inputs[str(key)] = {"type": "string", "required": False}
    return CompositeWorkflowSpec(
        name=macro.name,
        description=macro.description or macro.name,
        inputs=normalized_inputs,
        steps=tuple(steps),
        outputs=dict(outputs),
        trusted=False,
    )


def _collect_binding_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, str) and value.startswith("$"):
        refs.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            refs.extend(_collect_binding_refs(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.extend(_collect_binding_refs(child))
    return refs


def validate_macro_definition(
    macro: MacroDefinition,
    *,
    tool_index: Iterable[str] | None = None,
) -> CompositeWorkflowSpec:
    """Validate and normalize a MacroDefinition; return executable workflow IR.

    Side effect: unverified ``selection=exclusive`` is downgraded to ``prefer``.
    """
    manifest = str(macro.provenance.get("manifest") or macro.name)
    if not macro.enabled:
        raise MacroConvertError(
            "macro_disabled",
            f"macro is disabled: {macro.name}",
            manifest=manifest,
        )
    if macro.scope != "bundle":
        raise MacroConvertError(
            "macro_scope_unsupported",
            "Phase 4 convert only accepts scope=bundle macros",
            manifest=manifest,
            field="scope",
        )

    # §6.3: exclusive requires verified, else prefer
    if macro.routing.selection == "exclusive" and not macro.routing.verified:
        macro.routing.selection = "prefer"

    if not macro.routing.target_tool:
        macro.routing.target_tool = macro.name
    macro.routing.scope = "bundle"

    # F-157: structural exclusive suppression needs a narrow intent and an
    # explicit atomic coverage relation.  Phrase-only exclusive routes are
    # still readable at runtime for compatibility, but new bundle manifests
    # must not claim verified exclusive without the structural contract.
    if macro.routing.selection == "exclusive":
        if not macro.routing.intent_key:
            raise MacroConvertError(
                "macro_retrieval_intent_missing",
                "verified exclusive macro requires routing.intent_key",
                manifest=manifest,
                field="routing.intent_key",
            )
        if not macro.routing.covered_tools:
            raise MacroConvertError(
                "macro_coverage_missing",
                "verified exclusive macro requires routing.covered_tools",
                manifest=manifest,
                field="routing.covered_tools",
            )

    if macro.routing.covered_tools and tool_index is not None:
        from ..tool_retrieval import resolve_tool_references

        try:
            covered = resolve_tool_references(
                macro.routing.covered_tools,
                tool_index,
                require_unique=True,
            )
        except ValueError as exc:
            raise MacroConvertError(
                "macro_coverage_unresolved",
                str(exc),
                manifest=manifest,
                field="routing.covered_tools",
            ) from exc
        target_norm = macro.routing.target_tool.replace("_", "-").replace(".", "-").lower()
        if any(
            name.replace("_", "-").replace(".", "-").lower() == target_norm
            for name in covered
        ):
            raise MacroConvertError(
                "macro_coverage_self_reference",
                "macro may not cover itself",
                manifest=manifest,
                field="routing.covered_tools",
            )

    spec = workflow_dict_to_spec(macro)
    if len(spec.steps) > 16:
        raise MacroConvertError(
            "macro_step_limit",
            "macro exceeds default max of 16 steps",
            manifest=manifest,
        )

    seen_ids: set[str] = set()
    available = {str(name) for name in (tool_index or [])}
    for step in spec.steps:
        if step.id in seen_ids:
            raise MacroConvertError(
                "macro_step_duplicate",
                f"duplicate step id: {step.id}",
                manifest=manifest,
                step_id=step.id,
            )
        seen_ids.add(step.id)
        if step.callable_ref in _FORBIDDEN_STEP_TOOLS:
            raise MacroConvertError(
                "macro_step_forbidden",
                f"step may not call macro-management tool: {step.callable_ref}",
                manifest=manifest,
                step_id=step.id,
                field="callable_ref",
            )
        if available and step.callable_ref not in available:
            raise MacroConvertError(
                "macro_callable_unresolved",
                f"callable_ref not in tool index: {step.callable_ref}",
                manifest=manifest,
                step_id=step.id,
                field="callable_ref",
            )

    # Forward-only binding checks
    completed: set[str] = set()
    input_names = set(spec.inputs)
    for step in spec.steps:
        for ref in _collect_binding_refs(step.args):
            input_match = _INPUT_REF.match(ref)
            if input_match:
                name = input_match.group(1)
                if name not in input_names:
                    raise MacroConvertError(
                        "macro_binding_invalid",
                        f"unknown input binding: {ref}",
                        manifest=manifest,
                        step_id=step.id,
                        field="args",
                    )
                continue
            step_match = _STEP_OUTPUT_REF.match(ref)
            if step_match:
                prior = step_match.group(1)
                if prior not in completed:
                    raise MacroConvertError(
                        "macro_binding_forward",
                        f"binding references unfinished step: {ref}",
                        manifest=manifest,
                        step_id=step.id,
                        field="args",
                    )
                continue
            if ref.startswith("$private."):
                raise MacroConvertError(
                    "macro_private_forbidden",
                    "bundle macros cannot use private bindings",
                    manifest=manifest,
                    step_id=step.id,
                    field="args",
                )
            if ref.startswith("$"):
                # Allow $resources.* without deep validation in Phase 4 MVP
                if ref.startswith("$resources."):
                    continue
                raise MacroConvertError(
                    "macro_binding_invalid",
                    f"unsupported binding: {ref}",
                    manifest=manifest,
                    step_id=step.id,
                    field="args",
                )
        completed.add(step.id)

    for ref in _collect_binding_refs(spec.outputs):
        if _INPUT_REF.match(ref):
            continue
        step_match = _STEP_OUTPUT_REF.match(ref)
        if step_match and step_match.group(1) in completed:
            continue
        if ref.startswith("$resources."):
            continue
        raise MacroConvertError(
            "macro_binding_invalid",
            f"invalid output binding: {ref}",
            manifest=manifest,
            field="workflow.outputs",
        )

    return spec

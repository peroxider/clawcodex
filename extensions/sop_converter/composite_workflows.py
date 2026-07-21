"""Standard executable composite workflow specifications."""

from __future__ import annotations

from .composite_runtime import CompositeWorkflowSpec, CompositeWorkflowStep


def invoke_existing_agent_workflow() -> CompositeWorkflowSpec:
    """Return the F-57 create-then-invoke recovery workflow."""
    return CompositeWorkflowSpec(
        name="invoke-existing-agent",
        description="Invoke an SOP-created agent from its F-56 catalog record by name or ID.",
        inputs={
            "agent_ref": {"type": "string", "required": False},
            "agent_id": {"type": "string", "required": False},
            "query": {"type": "string", "required": False},
            "inputs": {"type": "object", "required": False},
        },
        steps=(
            CompositeWorkflowStep(
                id="load_agent_record",
                kind="catalog",
                callable_ref="extensions.sop_converter.resource_catalog:get_agent_record",
                args={
                    "agent_ref": "$input.agent_ref",
                    "agent_id": "$input.agent_id",
                    "catalog_context": "$resources.catalog",
                },
                visibility="private",
            ),
            CompositeWorkflowStep(
                id="materialize_agent",
                kind="python",
                callable_ref="extensions.sop_converter.agent_runtime:materialize_agent",
                args={"record": "$private.load_agent_record.output"},
                visibility="private",
            ),
            CompositeWorkflowStep(
                id="invoke_agent",
                kind="python",
                callable_ref="extensions.sop_converter.agent_runtime:invoke_agent",
                args={
                    "agent": "$private.materialize_agent.output.agent",
                    "record": "$private.load_agent_record.output",
                    "query": "$input.query",
                    "inputs": "$input.inputs",
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "text": {"type": "string"},
                        "raw": {},
                        "output": {},
                        "method": {"type": "string"},
                    },
                    "required": ["agent_id", "text", "raw", "output", "method"],
                },
            ),
        ),
        outputs={
            "agent_id": "$steps.invoke_agent.output.agent_id",
            "output": "$steps.invoke_agent.output.output",
            "raw": "$steps.invoke_agent.output.raw",
            "text": "$steps.invoke_agent.output.text",
            "method": "$steps.invoke_agent.output.method",
        },
        trusted=True,
    )


__all__ = ["invoke_existing_agent_workflow"]

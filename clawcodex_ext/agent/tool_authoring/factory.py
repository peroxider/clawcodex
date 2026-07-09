"""Factory — builds a Tool from an AgentToolSpec, then registers it."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from src.tool_system.build_tool import Tool, build_tool
from src.tool_system.context import ToolContext
from clawcodex_ext.tool_system.protocol import ToolResult
from clawcodex_ext.agent.tool_authoring.spec import AgentToolSpec
from clawcodex_ext.agent.tool_authoring.validators import validate_spec, ValidationError
from clawcodex_ext.agent.tool_authoring.call_handlers import (
    BashCallError,
    execute_bash,
    parse_sop_wrapper_stdout,
    HttpCallError,
    execute_http,
    PythonCallError,
    execute_python,
    SdkWrapperCallError,
    execute_sdk_wrapper_in_process,
    parse_sdk_wrapper_call_impl,
    should_use_in_process_sdk_wrapper,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


def build_tool_from_spec(spec: AgentToolSpec) -> Tool:
    """Construct a ``Tool`` instance from an ``AgentToolSpec``.

    The tool is fully operational: ``tool.call`` dispatches to the appropriate
    ``call_handlers`` entry based on ``spec.call_type``, and all security
    constraints have already been validated by ``validate_spec``.

    Args:
        spec: A validated ``AgentToolSpec``.

    Returns:
        A ``Tool`` object that can be registered with a ``ToolRegistry``.
    """

    def _call_impl(input: dict[str, Any], _context: ToolContext) -> ToolResult:
        try:
            if should_use_in_process_sdk_wrapper(spec):
                parsed = parse_sdk_wrapper_call_impl(str(spec.call_impl))
                if parsed is None:
                    raise SdkWrapperCallError(
                        f"Cannot parse stateful wrapper call_impl for {spec.name}"
                    )
                script_path, method_name = parsed
                output = execute_sdk_wrapper_in_process(
                    script_path=script_path,
                    method_name=method_name,
                    kwargs=input,
                    session_id=_context.session_id,
                    agent_id=_context.agent_id,
                )
            elif spec.call_type == "bash":
                # Auto-inject {json_args} for sop-converter bridge tools
                # (and any other tool whose template uses this placeholder).
                # Harmless no-op when the template doesn't contain {json_args}.
                enriched = input
                if "{json_args}" in spec.call_impl and "json_args" not in enriched:
                    enriched = {**input, "json_args": json.dumps(input)}
                # Persisted specs use bare ``python``; on many Linux systems that
                # resolves to Python 2. Always run bridge scripts with the
                # current interpreter (the venv that loaded clawcodex).
                call_impl = spec.call_impl
                if call_impl.startswith("python ") or call_impl.startswith("python3 "):
                    call_impl = f"{sys.executable} {call_impl.split(' ', 1)[1]}"
                output = execute_bash(call_impl, enriched, context=_context)
                if "{json_args}" in spec.call_impl:
                    output = parse_sop_wrapper_stdout(output)
            elif spec.call_type == "http":
                output = execute_http(spec.call_impl, input)
            elif spec.call_type == "python":
                output = execute_python(spec.call_impl, input)
            else:
                output = f"Unknown call_type: {spec.call_type}"
        except (BashCallError, HttpCallError, PythonCallError, SdkWrapperCallError) as exc:
            return ToolResult(
                name=spec.name,
                output={"error": str(exc)},
                is_error=True,
            )

        return ToolResult(
            name=spec.name,
            output=output,
        )

    # SOP-converter tools are workflow-specific and numerous;
    # defer them so they load via ToolSearch on demand.
    should_defer = spec.source in {"sop-converter", "pos-converter"}

    return build_tool(
        name=spec.name,
        input_schema=spec.input_schema,
        call=_call_impl,
        prompt=f"Tool: {spec.name}\n\n{spec.description}",
        description=spec.description,
        aliases=spec.aliases,
        search_hint=" ".join(spec.tags) if spec.tags else None,
        should_defer=should_defer,
    )


def create_and_validate(spec: AgentToolSpec) -> Tool:
    """Validate a spec and build a ``Tool`` from it.

    This is the main entry point used by ``CreateAgentTool``.

    Raises:
        ValidationError: If the spec fails validation.
    """
    validate_spec(spec)
    return build_tool_from_spec(spec)

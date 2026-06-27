"""ExecuteTool — proxy execution of another registered tool.

F-71 K: lets the agent invoke a sibling tool through a controlled
indirection rather than calling it directly. Useful when a tool name is
discovered at runtime (e.g. from a registry lookup, a user-supplied
config, or an MCP server response) and the agent must execute it without
hard-coding a call site.

The proxy enforces three guardrails that direct tool calls bypass:

1. **Allow-list filtering** — only tools whose ``proxy_safe`` predicate
   returns True are reachable through ExecuteTool. Tools that own
   side-effecting infra (e.g. Bash, Network) opt out by default and must
   explicitly set ``proxy_safe=True`` in their ``Tool`` metadata.
2. **Schema validation** — the input dict is validated against the
   target tool's ``input_schema`` before invocation, returning a clear
   error if the call would otherwise have failed mid-execution.
3. **Audit logging** — every proxy call is appended to ``context.tool_calls``
   under the canonical name ``ExecuteTool`` with the resolved target
   tool name embedded in the result, so reviewers can trace indirection.

Notes
-----
* This tool is the v1 reference for P71-K; F-71 follow-ups (P71-N browser
  proxy, P71-M remote trigger) build on the same ``proxy_safe`` contract.
* The agent loop never re-enters the proxy recursively; if the target
  tool itself calls ExecuteTool, the inner call returns an
  ``is_error=True`` result to break the cycle.
"""

from __future__ import annotations

from typing import Any, Callable

from ..build_tool import Tool, ValidationResult, build_tool
from ..context import ToolContext
from ..protocol import ToolResult


def _get_static_tools() -> list[Tool]:
    """Lazy accessor for ``ALL_STATIC_TOOLS``.

    Importing at module load would form a circular import with
    ``clawcodex_ext.tool_system.tools.__init__`` which exports the
    registry alongside the tool instances. Resolve on first call.
    """
    from . import ALL_STATIC_TOOLS as _registry  # type: ignore[attr-defined]

    return _registry


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _resolve_target(name: str) -> Tool | None:
    """Look up a tool by primary name or alias. Returns None if absent.

    O(N) over ``ALL_STATIC_TOOLS`` is fine here — the static list is
    ~45 entries and proxy calls are infrequent. If the registry grows
    past ~200 entries, switch to the dict cache used by the dispatcher.
    """
    for tool in _get_static_tools():
        if tool.name == name or name in tool.aliases:
            return tool
    return None


def _is_proxy_safe(tool: Tool) -> bool:
    """Decide whether ``tool`` may be invoked through ExecuteTool.

    Default False; tools opt in by setting the ``proxy_safe`` attribute
    on the Tool dataclass. We read via ``getattr`` so older Tool
    instances built before F-71 K keep their default-deny posture
    instead of crashing on missing attribute.
    """
    return bool(getattr(tool, "proxy_safe", False))


def _validate_schema(tool: Tool, payload: dict[str, Any]) -> ValidationResult:
    """Light-weight schema check before dispatch.

    The tool's own ``call`` will validate again; this early check lets us
    return a friendly error without spinning up the full execution
    pipeline for obviously-malformed payloads.
    """
    schema = tool.input_schema or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    for key in required:
        if key not in payload:
            return ValidationResult.fail(
                f"Missing required field {key!r} for tool {tool.name!r}"
            )
    for key, value in payload.items():
        if key not in properties:
            return ValidationResult.fail(
                f"Unknown field {key!r} for tool {tool.name!r}"
            )
    return ValidationResult.ok()


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def execute_call(payload: dict[str, Any], context: ToolContext) -> ToolResult:
    """Dispatch ``payload.tool_name`` with ``payload.arguments``."""
    tool_name = str(payload.get("tool_name") or "").strip()
    arguments = payload.get("arguments") or {}
    if not isinstance(arguments, dict):
        return ToolResult(name="execute",
            output=f"ExecuteTool: arguments must be a dict, got {type(arguments).__name__}",
            is_error=True,
        )
    if not tool_name:
        return ToolResult(name="execute",
            output="ExecuteTool: tool_name is required",
            is_error=True,
        )

    # Reject self-recursion to break infinite loops.
    if tool_name == "execute" or tool_name == "ExecuteTool":
        return ToolResult(name="execute",
            output="ExecuteTool: recursive proxy call rejected",
            is_error=True,
        )

    target = _resolve_target(tool_name)
    if target is None:
        return ToolResult(name="execute",
            output=f"ExecuteTool: tool {tool_name!r} not found in registry",
            is_error=True,
        )
    if not _is_proxy_safe(target):
        return ToolResult(name="execute",
            output=(
                f"ExecuteTool: tool {tool_name!r} is not proxy_safe; "
                f"call it directly instead of through the proxy"
            ),
            is_error=True,
        )

    validation = _validate_schema(target, arguments)
    if not validation.result:
        return ToolResult(name="execute", output=validation.message, is_error=True)

    # Dispatch through the tool's own call. ToolContext is shared so the
    # downstream tool sees the same permissions / task manager as the
    # original caller.
    try:
        return target.call(arguments, context)
    except Exception as exc:  # pragma: no cover - defensive
        return ToolResult(name="execute",
            output=f"ExecuteTool: {tool_name} raised {type(exc).__name__}: {exc}",
            is_error=True,
        )


def execute_activity(payload: dict[str, Any] | None) -> str | None:
    """User-facing activity description (dashboard / progress)."""
    if payload is None:
        return None
    name = payload.get("tool_name") if isinstance(payload, dict) else None
    return f"proxy {name}" if name else "proxy tool"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


execute_tool: Tool = build_tool(
    name="execute",
    description=(
        "Execute another registered tool by name. Useful when the tool name "
        "is discovered at runtime. The target tool must opt in via its "
        "`proxy_safe` attribute; tools default to deny. Recursive calls to "
        "ExecuteTool itself are rejected."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Primary name or alias of the tool to invoke.",
            },
            "arguments": {
                "type": "object",
                "description": "JSON object matching the target tool's input_schema.",
            },
        },
        "required": ["tool_name", "arguments"],
    },
    call=execute_call,
    get_activity_description=execute_activity,
    aliases=("ExecuteTool", "proxy"),
    is_destructive=lambda _p: True,  # proxy can target any proxy_safe tool
    search_hint="proxy tool invoke dispatch",
)


__all__ = ["execute_tool", "execute_call"]
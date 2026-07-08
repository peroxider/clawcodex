from __future__ import annotations

import json
from typing import Any
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from ..registry import ToolRegistry
from ..build_tool import Tool, build_tool, tool_matches_name
from .tool_search_matching import (
    rank_tool_matches,
    resolve_select_tool_names,
    summarize_tool_match,
)


def _resolve_bundle_context(context: ToolContext) -> Any | None:
    bundle = getattr(context, "bundle_context", None)
    if bundle is not None:
        return bundle
    try:
        from extensions.sop_converter.bundle_context import get_active_bundle

        return get_active_bundle()
    except ImportError:
        return None


def _allowlist_search_stub(name: str) -> Tool:
    """Minimal deferred tool used only for ToolSearch indexing."""
    hint = name.replace("-", " ").replace("_", " ")

    def _unloaded_call(_input: dict[str, Any], _context: ToolContext) -> ToolResult:
        return ToolResult(
            name=name,
            output={"error": f"tool not loaded: {name}"},
            is_error=True,
        )

    return build_tool(
        name=name,
        input_schema={"type": "object", "properties": {}},
        call=_unloaded_call,
        prompt=hint,
        search_hint=hint,
        should_defer=True,
    )


def _bundle_scoped_tools(registry: ToolRegistry, context: ToolContext) -> list[Tool]:
    bundle = _resolve_bundle_context(context)

    try:
        from extensions.sop_converter.bundle_context import filter_tools_for_bundle

        filtered = filter_tools_for_bundle(registry.list_tools(), bundle)
    except ImportError:
        return registry.list_tools()

    if bundle is None:
        return filtered

    # Allowlisted bundle tools may not be registered yet (lazy persistence).
    # Include loaded tools and lightweight name stubs so exact ToolSearch
    # queries resolve to the intended deferred tool instead of base-tool noise.
    extras: list[Tool] = []
    for name in bundle.tool_names:
        if any(tool_matches_name(tool, name) for tool in filtered):
            continue
        loaded = registry.get(name)
        if loaded is not None:
            extras.append(loaded)
            continue
        extras.append(_allowlist_search_stub(name))
    return filtered + extras


def _activate_toolsearch_matches(
    registry: ToolRegistry,
    context: ToolContext,
    matches: list[str],
) -> None:
    """Register persisted bundle tools and expose them on the next API turn."""
    if not matches:
        return
    try:
        from extensions.sop_converter.bundle_context import (
            ensure_bundle_tools_registered,
            get_active_bundle,
        )
    except ImportError:
        return

    bundle = _resolve_bundle_context(context) or get_active_bundle()
    bundle_path = bundle.bundle_path if bundle is not None else None
    ensure_bundle_tools_registered(registry, matches, bundle_path=bundle_path)

    current = list(context.options.tools or [])
    present = {tool.name for tool in current}
    for name in matches:
        if name in present:
            continue
        tool = registry.get(name)
        if tool is not None:
            current.append(tool)
            present.add(name)
    if len(current) != len(context.options.tools or []):
        context.options.tools = current


def _find_tool_by_name(tools: list[Tool], name: str) -> Tool | None:
    for tool in tools:
        if tool_matches_name(tool, name):
            return tool
    return None


def _tool_search_output_payload(
    *,
    matches: list[str],
    query: str,
    registry: ToolRegistry,
    searchable_tools: list[Tool] | None = None,
) -> dict[str, Any]:
    deferred_count = sum(1 for t in registry.list_tools() if getattr(t, "should_defer", False))
    pool = searchable_tools or []
    match_details: list[dict[str, Any]] = []
    for name in matches:
        tool = _find_tool_by_name(pool, name) or registry.get(name)
        if tool is not None:
            match_details.append(summarize_tool_match(tool))
        else:
            match_details.append({"name": name})
    return {
        "matches": matches,
        "match_details": match_details,
        "query": query,
        "total_deferred_tools": deferred_count,
    }


def _tool_search_map_result_to_api(output: Any, tool_use_id: str) -> dict[str, Any]:
    """Map ToolSearch output to API blocks, including tool_reference entries."""
    matches: list[str] = []
    query = ""
    total_deferred = 0
    if isinstance(output, dict):
        raw_matches = output.get("matches")
        if isinstance(raw_matches, list):
            matches = [str(name) for name in raw_matches if name]
        query = str(output.get("query", "") or "")
        raw_total = output.get("total_deferred_tools")
        if isinstance(raw_total, int):
            total_deferred = raw_total

    summary = json.dumps(
        {
            "matches": matches,
            "query": query,
            "total_deferred_tools": total_deferred,
        },
        ensure_ascii=False,
    )
    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": summary}]
    for name in matches:
        content_blocks.append({"type": "tool_reference", "tool_name": name})

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content_blocks,
    }


def make_tool_search_tool(registry: ToolRegistry) -> Tool:
    def _tool_search_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        query = tool_input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolInputError("query must be a non-empty string")
        max_results = tool_input.get("max_results", 5)
        if not isinstance(max_results, int) or max_results < 1 or max_results > 50:
            raise ToolInputError("max_results must be an integer between 1 and 50")

        q = query.strip()
        lowered = q.lower()
        searchable_tools = _bundle_scoped_tools(registry, context)
        if lowered.startswith("select:"):
            name = q.split(":", 1)[1].strip()
            matches = resolve_select_tool_names(name, searchable_tools)
            _activate_toolsearch_matches(registry, context, matches)
            return ToolResult(
                name="ToolSearch",
                output=_tool_search_output_payload(
                    matches=matches,
                    query=query,
                    registry=registry,
                    searchable_tools=searchable_tools,
                ),
            )

        matches = rank_tool_matches(
            q,
            searchable_tools,
            max_results=max_results,
        )
        _activate_toolsearch_matches(registry, context, matches)
        return ToolResult(
            name="ToolSearch",
            output=_tool_search_output_payload(
                matches=matches,
                query=query,
                registry=registry,
                searchable_tools=searchable_tools,
            ),
        )

    return build_tool(
        name="ToolSearch",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
        call=_tool_search_call,
        prompt="Search for available tools by name or keywords.",
        description="Search for available tools by name or keywords.",
        map_result_to_api=_tool_search_map_result_to_api,
        strict=True,
        max_result_size_chars=100_000,
        is_read_only=lambda _input: True,
        is_concurrency_safe=lambda _input: True,
        # ToolSearch's classifier-input is the query the model wants
        # to search for -- already compact enough for the classifier.
        to_auto_classifier_input=lambda input_data: (input_data or {}).get("query", "") or "",
    )

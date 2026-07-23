"""lkb MCP server — exposes 4 tools: decompose_task, validate_task, explain, audit."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from lkb import (
    LogicalKanbanService,
    TaskDecomposer,
    get_audit_log,
    get_logical_kanban,
)
from lkb.types import FactsSnapshot

logger = logging.getLogger(__name__)

server = Server("lkb")


def create_server() -> Server:
    """Factory called by ``[project.entry-points.mcp_servers]``."""
    return server


# ── Tool definitions ────────────────────────────────────────────────────


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="decompose_task",
            description="Decompose a goal into a validated task plan (returns DecompositionPlan JSON)",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Natural-language goal to decompose",
                    },
                    "context": {
                        "type": "object",
                        "description": "Optional context snapshot (tasks, workspace_root, ...)",
                    },
                    "use_methods": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional method library refs to guide decomposition",
                    },
                },
                "required": ["goal"],
            },
        ),
        Tool(
            name="validate_task",
            description="Validate a proposed task state transition without committing",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to validate"},
                    "change": {
                        "type": "object",
                        "description": "Change specification (kind + payload)",
                    },
                },
                "required": ["task_id", "change"],
            },
        ),
        Tool(
            name="explain",
            description="Explain the reasoning chain for a task (proof trace, repair suggestions)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID to explain",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="audit",
            description="Return the audit log for a task (proposals, validations, commits, denials)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID to audit",
                    },
                    "since": {
                        "type": "string",
                        "format": "date-time",
                        "description": "Optional ISO 8601 timestamp filter",
                    },
                },
                "required": ["task_id"],
            },
        ),
    ]


# ── Tool call handlers ──────────────────────────────────────────────────


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch tool calls to the appropriate handler."""
    try:
        if name == "decompose_task":
            return [await _handle_decompose(arguments)]
        elif name == "validate_task":
            return [await _handle_validate(arguments)]
        elif name == "explain":
            return [await _handle_explain(arguments)]
        elif name == "audit":
            return [await _handle_audit(arguments)]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": f"Unknown tool: {name}"}, ensure_ascii=False
                    ),
                )
            ]
    except Exception as exc:
        logger.exception("MCP tool %s failed", name)
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": str(exc), "type": type(exc).__name__},
                    ensure_ascii=False,
                ),
            )
        ]


async def _handle_decompose(arguments: dict[str, Any]) -> TextContent:
    """Decompose a goal into a validated task plan."""
    goal = arguments["goal"]
    context = arguments.get("context", {})
    method_refs = tuple(arguments.get("use_methods", []))

    decomposer = TaskDecomposer()
    plan = decomposer.decompose(
        goal=goal,
        context=context,
        method_refs=method_refs,
    )
    return TextContent(
        type="text",
        text=plan.to_json(),
    )


async def _handle_validate(arguments: dict[str, Any]) -> TextContent:
    """Validate a proposed task state transition."""
    task_id = arguments["task_id"]
    change = arguments["change"]

    runtime = get_logical_kanban(None)  # creates a standalone runtime
    service = LogicalKanbanService(runtime)
    result = service.validate(
        task_id=task_id,
        proposed_change=change,
    )
    return TextContent(
        type="text",
        text=json.dumps(result.to_dict() if hasattr(result, "to_dict") else result, ensure_ascii=False, default=str),
    )


async def _handle_explain(arguments: dict[str, Any]) -> TextContent:
    """Explain the reasoning chain for a task."""
    task_id = arguments["task_id"]

    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)
    explanation = runtime.explain_task(task_id, audit_log)

    return TextContent(
        type="text",
        text=json.dumps(explanation, ensure_ascii=False, default=str),
    )


async def _handle_audit(arguments: dict[str, Any]) -> TextContent:
    """Return the audit log for a task."""
    task_id = arguments["task_id"]
    since = arguments.get("since")

    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)

    events = audit_log.get_events(task_id=task_id, since=since)
    serialized = [
        {
            "eventId": e.event_id if hasattr(e, "event_id") else str(idx),
            "timestamp": str(e.timestamp) if hasattr(e, "timestamp") else None,
            "type": e.type if hasattr(e, "type") else None,
            "taskId": e.task_id if hasattr(e, "task_id") else task_id,
            "details": e.details if hasattr(e, "details") else {},
        }
        for idx, e in enumerate(events)
    ]

    return TextContent(
        type="text",
        text=json.dumps(serialized, ensure_ascii=False, default=str),
    )
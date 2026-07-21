#!/usr/bin/env python3
"""F-57 executable macro for invoking an agent from an F-56 catalog record."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _bundle_path_from_argv(argv: list[str]) -> str:
    for index, item in enumerate(argv):
        if item == "--bundle-path" and index + 1 < len(argv):
            return argv[index + 1]
    return os.environ.get("CLAWCODEX_BUNDLE_PATH", "").strip()


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _trace_payload(trace: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "step_id": step.step_id,
            "kind": step.kind,
            "status": step.status,
            "error_code": step.error_code,
            "error": step.error,
        }
        for step in trace
    ]


def invoke_existing_agent(
    agent_ref: str = "",
    query: str = "",
    inputs: Any = None,
    bundle_path: str | None = None,
    resource_type: str = "",
    agent_id: str = "",
) -> dict[str, Any]:
    """Execute F-57: load record, materialize agent, invoke, return output.

    ``resource_type`` is accepted only for compatibility with pre-F-57
    generated fallback wrappers. ``agent_ref`` may be the stable ID or the
    persisted agent name; ``agent_id`` remains a backwards-compatible alias.
    """
    del resource_type
    reference = str(agent_ref or agent_id or "")
    from extensions.sop_converter.composite_runtime import CompositeWorkflowRunner
    from extensions.sop_converter.composite_workflows import invoke_existing_agent_workflow
    from extensions.sop_converter.resource_catalog import CatalogExecutionContext

    result = CompositeWorkflowRunner().run(
        invoke_existing_agent_workflow(),
        {
            "agent_ref": reference,
            "agent_id": str(agent_id or ""),
            "query": query,
            "inputs": inputs,
        },
        resources={
            "catalog": CatalogExecutionContext(
                bundle_path=Path(bundle_path).expanduser().resolve() if bundle_path else None,
                bundle_id=Path(bundle_path).name if bundle_path else "default",
            )
        },
    )
    trace = _trace_payload(result.trace)
    if result.is_error:
        failed_step = trace[-1]["step_id"] if trace else ""
        return {
            "error": result.error,
            "error_code": result.error_code or "workflow_step_failed",
            "step_id": failed_step,
            "agent_ref": reference,
            "agent_id": agent_id or reference,
            "trace": trace,
        }

    output = result.output
    return {
        "agent_ref": reference,
        "agent_id": output.get("agent_id", agent_id or reference),
        "output": output.get("output"),
        "raw": output.get("raw"),
        "text": output.get("text", ""),
        "method": output.get("method", ""),
        "trace": trace,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        _emit({"error": "usage: invoke_existing_agent '<json_args>' [--bundle-path <path>]", "error_code": "usage"})
        return 2
    if argv[1] != "invoke_existing_agent":
        _emit({"error": f"unknown method: {argv[1]}", "error_code": "unknown_method"})
        return 1
    try:
        args = json.loads(argv[2])
    except json.JSONDecodeError as exc:
        _emit({"error": f"invalid JSON args: {exc}", "error_code": "invalid_json"})
        return 1
    if not isinstance(args, dict):
        _emit({"error": "tool arguments must be a JSON object", "error_code": "invalid_input"})
        return 1
    bundle_path = _bundle_path_from_argv(argv)
    _emit(
        invoke_existing_agent(
            agent_ref=str(args.get("agent_ref", "") or args.get("name", "")),
            agent_id=str(args.get("agent_id", "")),
            query=str(args.get("query", "")),
            inputs=args.get("inputs"),
            bundle_path=bundle_path or None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

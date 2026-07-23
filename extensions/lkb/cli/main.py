"""lkb CLI — main entry point with 4 subcommands: decompose, validate, explain, audit."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lkb",
        description="Logical Kanban Boards — formal task decomposition with rule engines and ATP solvers",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── decompose ──
    p_decomp = sub.add_parser("decompose", help="Decompose a goal into a validated task plan")
    p_decomp.add_argument("goal", help="Natural-language goal to decompose")
    p_decomp.add_argument("--methods", nargs="*", default=[], help="Method library refs (e.g. tdd-red-green)")
    p_decomp.add_argument("--pretty", action="store_true", default=True, help="Pretty-print JSON output")

    # ── validate ──
    p_val = sub.add_parser("validate", help="Validate a proposed task state transition")
    p_val.add_argument("--task-id", required=True, help="Task ID to validate")
    p_val.add_argument("--change", required=True, help="JSON string: the proposed change specification")

    # ── explain ──
    p_explain = sub.add_parser("explain", help="Explain the reasoning chain for a task")
    p_explain.add_argument("task_id", help="Task ID to explain")

    # ── audit ──
    p_audit = sub.add_parser("audit", help="Return the audit log for a task")
    p_audit.add_argument("task_id", help="Task ID to audit")
    p_audit.add_argument("--since", help="ISO 8601 timestamp filter (e.g. 2026-07-20T00:00:00Z)")

    args = parser.parse_args()

    if args.command == "decompose":
        _run_decompose(args)
    elif args.command == "validate":
        _run_validate(args)
    elif args.command == "explain":
        _run_explain(args)
    elif args.command == "audit":
        _run_audit(args)
    else:
        parser.print_help()
        sys.exit(1)


def _run_decompose(args: argparse.Namespace) -> None:
    from lkb import TaskDecomposer

    decomposer = TaskDecomposer()
    plan = decomposer.decompose(
        goal=args.goal,
        context={},
        method_refs=tuple(args.methods or []),
    )
    indent = 2 if args.pretty else None
    print(plan.to_json(indent=indent))


def _run_validate(args: argparse.Namespace) -> None:
    from lkb import LogicalKanbanService, get_logical_kanban

    try:
        change = json.loads(args.change)
    except json.JSONDecodeError as exc:
        print(f"Error: --change must be valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    runtime = get_logical_kanban(None)
    service = LogicalKanbanService(runtime)
    result = service.validate(task_id=args.task_id, proposed_change=change)
    if hasattr(result, "to_dict"):
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def _run_explain(args: argparse.Namespace) -> None:
    from lkb import get_audit_log, get_logical_kanban

    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)
    explanation = runtime.explain_task(args.task_id, audit_log)
    print(json.dumps(explanation, ensure_ascii=False, indent=2, default=str))


def _run_audit(args: argparse.Namespace) -> None:
    from lkb import get_audit_log, get_logical_kanban

    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)
    events = audit_log.get_events(task_id=args.task_id, since=args.since)
    serialized = [
        {
            "eventId": getattr(e, "event_id", str(idx)),
            "timestamp": str(getattr(e, "timestamp", "")),
            "type": getattr(e, "type", None),
            "taskId": getattr(e, "task_id", args.task_id),
            "details": getattr(e, "details", {}),
        }
        for idx, e in enumerate(events)
    ]
    print(json.dumps(serialized, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
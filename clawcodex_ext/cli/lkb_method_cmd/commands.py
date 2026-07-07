"""LKB method CLI — list/show/propose/approve/reject/deprecate/coverage.

Subcommands
-----------
clawcodex-dev lkb method list [--status=<status>] [--pattern-prefix=<prefix>]
clawcodex-dev lkb method show <method_id>
clawcodex-dev lkb method propose --from-plan=<run_id> [--method-id=<id>] [--pattern=<p>]
clawcodex-dev lkb method approve <proposal_id> [--reviewer=<name>]
clawcodex-dev lkb method reject <proposal_id> --reason="..."
clawcodex-dev lkb method deprecate <method_id> [--replacement=<id>]
clawcodex-dev lkb method coverage [--golden-set=<path>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from clawcodex_ext.cli.subcommand_registry import register
from clawcodex_ext.logical_kanban.method_library import (
    EngineeringMethod,
    list_methods,
    get_method,
    get_all_methods,
    save_method_library,
    load_method_library,
)
from clawcodex_ext.logical_kanban.method_governance import (
    approve_method,
    deprecate_method,
    get_proposal,
    list_proposals,
    reject_method,
    submit_method,
    reset_proposals,
    load_proposals,
)
from clawcodex_ext.logical_kanban.method_proposer import (
    propose_method_from_plan,
)
from clawcodex_ext.logical_kanban.decomposer import TaskDecomposer

# ---------------------------------------------------------------------------
# USAGE string
# ---------------------------------------------------------------------------

_USAGE = (
    "usage: clawcodex-dev lkb method <subcommand> [options]\n\n"
    "Subcommands:\n"
    "  list [--status=STATUS] [--pattern-prefix=PREFIX]\n"
    "                         List methods (default: --status=approved).\n"
    "  show <method_id>       Show method details.\n"
    "  propose --from-plan=RUN_ID [--method-id=M-ID] [--pattern=PATTERN]\n"
    "                         Propose a new method from a decomposition run.\n"
    "  approve <proposal_id> [--reviewer=NAME]\n"
    "                         Approve a method proposal.\n"
    "  reject <proposal_id> --reason=TEXT\n"
    "                         Reject a method proposal.\n"
    "  deprecate <method_id> [--replacement=M-ID]\n"
    "                         Deprecate an approved method.\n"
    "  coverage [--golden-set=PATH]\n"
    "                         Run coverage evaluation against the golden set.\n"
    "  help, --help, -h       Print this help.\n"
)

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


@register("lkb")
def run_lkb_command(args: list[str]) -> int:
    """Handle ``clawcodex-dev lkb method <subcommand>``."""
    # Ensure proposals are loaded once
    load_proposals()

    if not args:
        print(_USAGE, file=sys.stderr)
        return 1

    if args[0] in ("help", "--help", "-h"):
        print(_USAGE)
        return 0

    # ``lkb`` entry — subcommand is ``method`` or something else.
    # The orchestrator CLI (``clawcodex-dev lkb``) dispatches
    # ``run_lkb_command(method, ...)`` via subcommand_registry.
    sub = args[0]
    rest = args[1:]

    if sub == "method":
        if not rest:
            print(_USAGE, file=sys.stderr)
            return 1
        return _dispatch_method(rest)

    # Unknown lkb subcommand — this module only handles ``method``.
    print(f"Unknown lkb subcommand: {sub}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


def _dispatch_method(args: list[str]) -> int:
    """Dispatch ``method`` sub-subcommands."""
    cmd = args[0]
    rest = args[1:]

    try:
        if cmd == "list":
            return _cmd_list(rest)
        if cmd == "show":
            return _cmd_show(rest)
        if cmd == "propose":
            return _cmd_propose(rest)
        if cmd == "approve":
            return _cmd_approve(rest)
        if cmd == "reject":
            return _cmd_reject(rest)
        if cmd == "deprecate":
            return _cmd_deprecate(rest)
        if cmd == "coverage":
            return _cmd_coverage(rest)
        if cmd in ("help", "--help", "-h"):
            print(_USAGE)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Unknown method subcommand: {cmd}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _cmd_list(args: list[str]) -> int:
    status = _parse_flag(args, "--status", "approved")
    pattern_prefix = _parse_flag(args, "--pattern-prefix", None)
    tag = _parse_flag(args, "--tag", None)

    methods = list_methods(
        status=status,
        pattern_prefix=pattern_prefix,
        tag=tag,
    )

    if not methods:
        print("(no methods match)")
        return 0

    rows = [
        f"  {m.method_id:20s} {m.pattern:30s} {m.version:10s} {m.status:12s} "
        f"({len(m.subtask_templates)} subtasks)"
        for m in methods
    ]
    print(f"Methods ({len(rows)}):")
    print("\n".join(rows))
    return 0


def _cmd_show(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb method show <method_id>", file=sys.stderr)
        return 1

    method_id = args[0]
    method = get_method(method_id)
    if method is None:
        print(f"Method {method_id!r} not found.", file=sys.stderr)
        return 1

    print(_format_method_detail(method))
    return 0


def _cmd_propose(args: list[str]) -> int:
    from_run_id = _parse_flag(args, "--from-plan", None)
    if not from_run_id:
        print("error: --from-plan=<run_id> is required", file=sys.stderr)
        return 1

    method_id = _parse_flag(args, "--method-id", None)
    pattern = _parse_flag(args, "--pattern", None)

    # Resolve the decomposition plan — try to get it from the decomposer
    # registry.  For now we look up the last cached plan by run ID.
    plan = _find_decomposition_plan(from_run_id)
    if plan is None:
        print(
            f"error: no decomposition plan found for run {from_run_id!r}",
            file=sys.stderr,
        )
        return 1

    if not method_id:
        method_id = f"M-{plan.decomposition_run_id.split('-')[-1]}"
    if not pattern:
        pattern = _infer_pattern_from_plan(plan)

    description = f"Auto-proposed from plan {plan.decomposition_run_id}: {plan.goal[:80]}"

    method = propose_method_from_plan(
        plan,
        method_id=method_id,
        pattern=pattern,
        description=description,
    )

    proposal_id = submit_method(method)
    print(f"Proposal {proposal_id} submitted for method {method.method_id!r}.")
    print(f"Method details:\n{_format_method_detail(method)}")
    return 0


def _cmd_approve(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb method approve <proposal_id> [--reviewer=...]",
              file=sys.stderr)
        return 1

    proposal_id = args[0]
    reviewer = _parse_flag(args, "--reviewer", "")

    approve_method(proposal_id, reviewer=reviewer)
    print(f"Proposal {proposal_id} approved.")
    return 0


def _cmd_reject(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb method reject <proposal_id> --reason=...",
              file=sys.stderr)
        return 1

    proposal_id = args[0]
    reason = _parse_flag(args, "--reason", None)
    if not reason:
        print("error: --reason is required for reject", file=sys.stderr)
        return 1

    reviewer = _parse_flag(args, "--reviewer", "")
    reject_method(proposal_id, reviewer=reviewer, reason=reason)
    print(f"Proposal {proposal_id} rejected (reason: {reason})")
    return 0


def _cmd_deprecate(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb method deprecate <method_id> [--replacement=...]",
              file=sys.stderr)
        return 1

    method_id = args[0]
    replacement = _parse_flag(args, "--replacement", None)
    reviewer = _parse_flag(args, "--reviewer", "")

    deprecate_method(method_id, replacement_id=replacement, reviewer=reviewer)
    msg = f"Method {method_id!r} deprecated."
    if replacement:
        msg += f" Replaced by {replacement}."
    print(msg)
    return 0


def _cmd_coverage(args: list[str]) -> int:
    from clawcodex_ext.logical_kanban.method_coverage import (
        MethodCoverageEvaluator,
    )

    golden_set_path = _parse_flag(args, "--golden-set", None)
    if golden_set_path:
        golden_set = json.loads(Path(golden_set_path).read_text(encoding="utf-8"))
    else:
        # Try default golden set path
        default_path = (
            Path("docs") / "feature_plan" / "09-logical-kanban" / "golden_set.json"
        )
        if default_path.is_file():
            golden_set = json.loads(default_path.read_text(encoding="utf-8"))
        else:
            print(
                "warning: no golden-set file found; using empty set",
                file=sys.stderr,
            )
            golden_set = []

    evaluator = MethodCoverageEvaluator()
    report = evaluator.evaluate(golden_set)

    print(_format_coverage_report(report))
    return 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_flag(args: list[str], name: str, default: Any = None) -> Any:
    """Extract ``--key=value`` (or ``--key value``) from *args*."""
    prefix = f"{name}="
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return default


def _format_method_detail(method: EngineeringMethod) -> str:
    lines = [
        f"  ID:          {method.method_id}",
        f"  Pattern:     {method.pattern}",
        f"  Description: {method.description}",
        f"  Version:     {method.version}",
        f"  Status:      {method.status}",
        f"  Preconditions: {len(method.preconditions)}",
        f"  Assumptions:   {len(method.assumptions)}",
        f"  Subtasks:      {len(method.subtask_templates)}",
    ]
    if method.acceptance_template:
        lines.append(f"  Acceptance:    assertion_template='{method.acceptance_template.assertion_template}'")
    if method.tags:
        lines.append(f"  Tags:        {', '.join(method.tags)}")
    lines.append("")
    for st in method.subtask_templates:
        lines.append(f"    * {st.template_id} ({st.role}): {st.subject_template}")
    return "\n".join(lines)


def _find_decomposition_plan(run_id: str) -> Any:
    """Find a cached decomposition plan by its run ID.

    This tries to load from the decomposer's internal cache or
    from the file system.
    """
    # First try the in-memory cache from F-149
    try:
        from clawcodex_ext.logical_kanban.decomposer import _DECOMPOSITION_CACHE
        return _DECOMPOSITION_CACHE.get(run_id)
    except (ImportError, AttributeError):
        pass
    # Fall back to filesystem cache
    cache_dir = Path.home() / ".cache" / "clawcodex" / "lkb" / "decompositions"
    path = cache_dir / f"{run_id}.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return _plan_from_dict(data, run_id)
    return None


def _plan_from_dict(data: dict[str, Any], run_id: str) -> Any:
    """Reconstruct a DecompositionPlan from a dict (best-effort).

    This is a simplified reconstruction — full deserialization may not
    capture all fields, but it's sufficient for method proposal.
    """
    from clawcodex_ext.logical_kanban.decomposer import (
        DecompositionPlan,
        ProposedTask,
    )
    from clawcodex_ext.logical_kanban.fuzzy_types import AmbiguityReport

    tasks = tuple(
        ProposedTask(
            proposed_task_id=t.get("proposedTaskId", f"T-{i}"),
            subject=t.get("subject", ""),
            description=t.get("description", ""),
            active_form=t.get("activeForm", ""),
            acceptance_criteria=tuple(t.get("acceptanceCriteria", [])),
            blocked_by=tuple(t.get("blockedBy", [])),
            lkb_metadata=t.get("lkbMetadata", {}),
        )
        for i, t in enumerate(data.get("tasks", []))
    )

    return DecompositionPlan(
        decomposition_run_id=run_id,
        goal=data.get("goal", ""),
        tasks=tasks,
        dependencies=tuple(
            tuple(d) for d in data.get("dependencies", [])
        ),
        assumptions=tuple(data.get("assumptions", [])),
        ambiguity_report=None,
        validation_run=None,
        method_references=tuple(data.get("methodReferences", [])),
    )


def _infer_pattern_from_plan(plan: Any) -> str:
    """Infer a method pattern from the plan's goal text."""
    goal_lower = (plan.goal or "").lower()
    for prefix in (
        "add", "fix", "refactor", "remove", "update", "migrate",
        "implement", "create", "configure", "optimize",
    ):
        if goal_lower.startswith(prefix):
            return f"{prefix}_{goal_lower.split()[0] if len(goal_lower.split()) > 1 else 'task'}"
    return "custom_task"


# ---------------------------------------------------------------------------
# Coverage report formatting
# ---------------------------------------------------------------------------


def _format_coverage_report(report: dict[str, Any]) -> str:
    lines = [
        "Coverage Report",
        "===============",
        f"  Golden-set size:     {report.get('golden_set_size', 0)}",
        f"  Hit rate:            {report.get('hit_rate', 0.0):.1%}",
        f"  Top method usage:    {json.dumps(report.get('top_method_usage', {}), indent=4)}",
        f"  Long-tail methods:   {report.get('long_tail_methods', 0)}",
        f"  Dead methods:        {report.get('dead_methods', 0)}",
    ]
    warnings = report.get("coverage_integrity_warnings", [])
    if warnings:
        lines.append("  Integrity warnings:")
        for w in warnings:
            lines.append(f"    - {w}")
    return "\n".join(lines)

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
    initialize_method_registry,
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
from clawcodex_ext.logical_kanban.acceptance_template import (
    get_acceptance_template,
    initialize_acceptance_template_registry,
    list_acceptance_templates,
)
from clawcodex_ext.logical_kanban.acceptance_template_governance import (
    approve_acceptance_template,
    deprecate_acceptance_template,
    load_acceptance_template_proposals,
    propose_acceptance_template_from_plan,
    reject_acceptance_template,
    submit_acceptance_template,
)
from clawcodex_ext.logical_kanban.method_proposer import (
    propose_method_from_plan,
)
from clawcodex_ext.logical_kanban.decomposer import TaskDecomposer

# ---------------------------------------------------------------------------
# USAGE string
# ---------------------------------------------------------------------------

_USAGE = (
    "usage: clawcodex-dev lkb <method|import|export|config> [options]\n\n"
    "Subcommands:\n"
    "  import <path|url|entry-point>... [--lint-only] [--recursive] [--force]\n"
    "                         Import external LKB configs.\n"
    "  import --list          List lkb.configs entry points.\n"
    "  export --format=json <output>\n"
    "                         Export active method/operation config as JSON.\n"
    "  config list            List loaded external config entities.\n"
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
    "  template list [--status=STATUS] [--role=ROLE]\n"
    "                         List acceptance templates.\n"
    "  template show <template_id>\n"
    "                         Show acceptance template details.\n"
    "  template propose --from-plan=RUN_ID --template-id=T-ID --description=TEXT\n"
    "                         Propose an acceptance template from a decomposition run.\n"
    "  template approve <proposal_id> [--reviewer=NAME]\n"
    "                         Approve an acceptance template proposal.\n"
    "  template reject <proposal_id> --reason=TEXT\n"
    "                         Reject an acceptance template proposal.\n"
    "  template deprecate <template_id> [--replacement=T-ID]\n"
    "                         Deprecate an acceptance template.\n"
    "  template coverage\n"
    "                         Report acceptance-template reference coverage.\n"
    "  help, --help, -h       Print this help.\n"
)

# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


@register("lkb")
def run_lkb_command(args: list[str]) -> int:
    """Handle ``clawcodex-dev lkb method <subcommand>``."""
    # Ensure the file-backed layers are loaded once at CLI startup.
    initialize_method_registry(project_dir=Path.cwd())
    initialize_acceptance_template_registry(project_dir=Path.cwd())
    load_proposals()
    load_acceptance_template_proposals()

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
    if sub == "template":
        if not rest:
            print(_USAGE, file=sys.stderr)
            return 1
        return _dispatch_template(rest)
    if sub == "import":
        return _cmd_import(rest)
    if sub == "export":
        return _cmd_export(rest)
    if sub == "config" and rest[:1] == ["list"]:
        return _cmd_config_list(rest[1:])

    # Unknown lkb subcommand — this module only handles ``method``.
    print(f"Unknown lkb subcommand: {sub}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


def _dispatch_template(args: list[str]) -> int:
    cmd = args[0]
    rest = args[1:]
    try:
        if cmd == "list":
            return _cmd_template_list(rest)
        if cmd == "show":
            return _cmd_template_show(rest)
        if cmd == "propose":
            return _cmd_template_propose(rest)
        if cmd == "approve":
            return _cmd_template_approve(rest)
        if cmd == "reject":
            return _cmd_template_reject(rest)
        if cmd == "deprecate":
            return _cmd_template_deprecate(rest)
        if cmd == "coverage":
            return _cmd_template_coverage(rest)
        if cmd in ("help", "--help", "-h"):
            print(_USAGE)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Unknown template subcommand: {cmd}", file=sys.stderr)
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
            Path("clawcodex_ext") / "logical_kanban" / "golden_set.json"
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


def _cmd_template_list(args: list[str]) -> int:
    status = _parse_flag(args, "--status", "approved")
    role = _parse_flag(args, "--role", None)
    templates = list_acceptance_templates(status=status, role=role)
    if not templates:
        print("(no acceptance templates match)")
        return 0
    rows = [
        f"  {template.template_id:35s} {template.version:8s} {template.status:12s} "
        f"roles={','.join(template.applies_to_roles) or 'any'}"
        for template in templates
    ]
    print(f"Acceptance templates ({len(rows)}):")
    print("\n".join(rows))
    return 0


def _cmd_template_show(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb template show <template_id>", file=sys.stderr)
        return 1
    template = get_acceptance_template(args[0])
    if template is None:
        print(f"Acceptance template {args[0]!r} not found.", file=sys.stderr)
        return 1
    print(_format_acceptance_template_detail(template))
    return 0


def _cmd_template_propose(args: list[str]) -> int:
    from_run_id = _parse_flag(args, "--from-plan", None)
    template_id = _parse_flag(args, "--template-id", None)
    description = _parse_flag(args, "--description", None)
    if not from_run_id or not template_id:
        print("error: --from-plan and --template-id are required", file=sys.stderr)
        return 1
    plan = _find_decomposition_plan(from_run_id)
    if plan is None:
        print(f"error: no decomposition plan found for run {from_run_id!r}", file=sys.stderr)
        return 1
    template = propose_acceptance_template_from_plan(
        plan,
        template_id=template_id,
        description=description or f"Auto-proposed from plan {from_run_id}",
    )
    proposal_id = submit_acceptance_template(template)
    print(f"Proposal {proposal_id} submitted for acceptance template {template.template_id!r}.")
    print(_format_acceptance_template_detail(template))
    return 0


def _cmd_template_approve(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb template approve <proposal_id> [--reviewer=...]", file=sys.stderr)
        return 1
    approve_acceptance_template(args[0], reviewer=_parse_flag(args, "--reviewer", ""))
    print(f"Acceptance template proposal {args[0]} approved.")
    return 0


def _cmd_template_reject(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb template reject <proposal_id> --reason=...", file=sys.stderr)
        return 1
    reason = _parse_flag(args, "--reason", None)
    if not reason:
        print("error: --reason is required for reject", file=sys.stderr)
        return 1
    reject_acceptance_template(
        args[0],
        reviewer=_parse_flag(args, "--reviewer", ""),
        reason=reason,
    )
    print(f"Acceptance template proposal {args[0]} rejected (reason: {reason})")
    return 0


def _cmd_template_deprecate(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        print("Usage: clawcodex-dev lkb template deprecate <template_id> [--replacement=...]", file=sys.stderr)
        return 1
    replacement = _parse_flag(args, "--replacement", None)
    deprecate_acceptance_template(
        args[0],
        replacement_id=replacement,
        reviewer=_parse_flag(args, "--reviewer", ""),
    )
    msg = f"Acceptance template {args[0]!r} deprecated."
    if replacement:
        msg += f" Replaced by {replacement}."
    print(msg)
    return 0


def _cmd_template_coverage(args: list[str]) -> int:
    templates = list_acceptance_templates(status=None)
    approved = [template for template in templates if template.status == "approved"]
    print("Acceptance Template Coverage")
    print("============================")
    print(f"  Registered templates: {len(templates)}")
    print(f"  Approved templates:   {len(approved)}")
    print("  Field layer:          DecompositionPlan.acceptance_template_references")
    print("  Event layer:          lkb_acceptance_template_referenced")
    return 0


def _cmd_import(args: list[str]) -> int:
    from clawcodex_ext.logical_kanban.external_config import ExternalConfigImporter

    if "--list" in args:
        entries = ExternalConfigImporter.list_entry_points()
        if entries:
            print("\n".join(entries))
        else:
            print("(no lkb.configs entry points)")
        return 0

    lint_only = "--lint-only" in args
    recursive = "--recursive" in args
    force = "--force" in args
    sources = [arg for arg in args if not arg.startswith("--")]
    if not sources:
        print("Usage: clawcodex-dev lkb import <path|url|entry-point>...", file=sys.stderr)
        return 1

    importer = ExternalConfigImporter(force=force, lint_only=lint_only)
    exit_code = 0
    for source in sources:
        try:
            if source.startswith("https://"):
                result = importer.import_url(source)
                results = [result]
            else:
                path = Path(source)
                if path.exists():
                    if path.is_dir():
                        results = importer.import_directory(path, recursive=recursive)
                    else:
                        results = [importer.import_file(path)]
                else:
                    results = [importer.import_package(source)]
        except Exception as exc:
            print(f"error: {source}: {exc}", file=sys.stderr)
            exit_code = 2
            continue
        for result in results:
            print(_format_import_result(result))
            if result.error_count:
                exit_code = max(exit_code, 2)
            elif result.lint_issues:
                exit_code = max(exit_code, 1)
    return exit_code if lint_only else (2 if exit_code == 2 else 0)


def _cmd_export(args: list[str]) -> int:
    from clawcodex_ext.logical_kanban.method_library import get_all_methods
    from clawcodex_ext.logical_kanban.operation_schema import get_all_operation_schemas
    from clawcodex_ext.logical_kanban.acceptance_template import get_all_acceptance_templates

    fmt = _parse_flag(args, "--format", "json")
    targets = [arg for arg in args if not arg.startswith("--") and arg != fmt]
    if fmt != "json":
        print("error: only --format=json is supported in this CLI", file=sys.stderr)
        return 1
    if not targets:
        print("Usage: clawcodex-dev lkb export --format=json <output>", file=sys.stderr)
        return 1
    output = Path(targets[-1])
    payload = {
        "schemaVersion": "1.0.0",
        "methods": [method.to_dict() for method in get_all_methods()],
        "acceptanceTemplates": [
            template.to_dict() for template in get_all_acceptance_templates()
        ],
        "operations": [op.to_dict() for op in get_all_operation_schemas()],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Exported LKB config to {output}")
    return 0


def _cmd_config_list(args: list[str]) -> int:
    from clawcodex_ext.logical_kanban.method_library import get_all_methods
    from clawcodex_ext.logical_kanban.operation_schema import get_all_operation_schemas
    from clawcodex_ext.logical_kanban.ontology_graph import get_registered_ontology
    from clawcodex_ext.logical_kanban.acceptance_template import get_all_acceptance_templates

    methods = get_all_methods()
    templates = get_all_acceptance_templates()
    operations = get_all_operation_schemas()
    ontology = get_registered_ontology()
    print("Kind              Count  Source")
    print(f"method_library    {len(methods):5d}  registry")
    print(f"acceptance_template {len(templates):3d}  registry")
    print(f"operation_schema  {len(operations):5d}  registry")
    if ontology is None:
        print("ontology              0  registry")
    else:
        print(f"ontology          {ontology.item_count:5d}  {ontology.source}")
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


def _format_acceptance_template_detail(template: Any) -> str:
    return "\n".join(
        [
            f"  ID:          {template.template_id}",
            f"  Description: {template.description}",
            f"  Version:     {template.version}",
            f"  Status:      {template.status}",
            f"  Roles:       {', '.join(template.applies_to_roles) or 'any'}",
            f"  Strict:      {template.strict_acceptance}",
            f"  Assertion:   {template.assertion_template}",
            f"  Proof:       {template.proof_template or '(optional)'}",
        ]
    )


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


def _format_import_result(result: Any) -> str:
    status = "ok" if result.success else "error"
    lines = [
        f"{status}: {result.kind} {result.item_count} item(s) from {result.source}",
    ]
    for issue in result.lint_issues:
        location = f" {issue.source}" if issue.source else ""
        field = f" {issue.field_path}" if issue.field_path else ""
        lines.append(f"  [{issue.severity}] {issue.code}:{location}{field} {issue.message}")
    return "\n".join(lines)

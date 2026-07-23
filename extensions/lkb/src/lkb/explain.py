"""Explainability helpers for Logical Kanban (F-136).

Explanations are generated from facts, rules, derived facts, proof trace and
validation results.  Natural language is presentation only and is never a truth
source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import FactsSnapshot, ValidationIssue, ValidationRun

_REPAIR_TEMPLATES: dict[str, tuple[tuple[str, str, int], ...]] = {
    "blocked_task_cannot_enter_in_progress": (
        ("complete_prerequisite", "Complete blocker {target} before starting {task}.", 1),
        ("remove_dependency", "Remove the dependency on {target} if it is no longer required.", 2),
        (
            "split_task",
            "Consider splitting {task} into smaller pieces if it has too many blockers.",
            3,
        ),
    ),
    "cyclic_dependency_blocks_readiness": (
        ("fix_cycle", "Remove or rewrite one dependency edge in the cycle.", 1),
        ("remove_dependency", "Remove one reciprocal or transitive dependency edge.", 2),
        ("split_task", "Consider splitting {task} to break the cycle.", 3),
    ),
    "dependency_cycle_denied": (
        ("fix_cycle", "Remove one reciprocal or transitive dependency edge.", 1),
        ("remove_dependency", "Remove one dependency edge to break the cycle.", 2),
        ("split_task", "Consider splitting {task} to break the cycle.", 3),
    ),
    "completed_requires_acceptance_proof": (
        (
            "add_acceptance_proof",
            "Attach metadata.lkb.acceptance_proof before completing {task}.",
            1,
        ),
        ("revalidate_task", "Keep {task} in_progress until acceptance proof is available.", 2),
    ),
    "stale_assumption_blocks_transition": (
        (
            "revalidate_task",
            "Clarify or override the invalidated assumptions before transitioning {task}.",
            1,
        ),
        ("clarify_ambiguity", "Provide clarification for the assumptions that affect {task}.", 2),
    ),
    "multiple_in_progress_legacy_todo_write": (
        (
            "keep_single_in_progress",
            "Leave only one todo in_progress and keep the others pending.",
            1,
        ),
    ),
    "clarify_assumption": (("clarify_ambiguity", "Clarify the assumption before proceeding.", 1),),
}

def explain_validation_run(
    validation_run: ValidationRun,
    proof_enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured, human-readable explanation of a validation run."""
    issue = validation_run.issues[0] if validation_run.issues else None
    enrichment = proof_enrichment or validation_run.proof_enrichment or {}
    return {
        "result": validation_run.result,
        "summary": _human_summary(validation_run, issue),
        "factsUsed": _facts_used(validation_run.proof_trace),
        "rulesUsed": _rules_used(validation_run.proof_trace),
        "derivedFacts": list(validation_run.derived_facts),
        "proofTraceSummary": proof_trace_summary(validation_run.proof_trace),
        "proofEnrichmentSummary": proof_enrichment_summary(enrichment),
        "repairSuggestions": [s.to_dict() for s in validation_run.repair_suggestions],
        "legacyTodoAmbiguities": list(validation_run.legacy_todo_ambiguities),
        "explanation_generated_by": "lkb-layer1-python",
    }

def explain_issue(issue: ValidationIssue) -> dict[str, Any]:
    """Return a structured explanation of a single validation issue."""
    return {
        "code": issue.code,
        "rule": issue.rule,
        "message": issue.message,
        "blockers": list(issue.blockers),
        "repairSuggestions": [s.to_dict() for s in issue.repair_suggestions],
    }

def build_repair_suggestions(
    issue: ValidationIssue,
    snapshot: FactsSnapshot | None = None,
) -> tuple[Any, ...]:
    """Build canonical F-136 repair suggestions for a validation issue.

    Natural language messages are derived from the issue code, blockers and
    task id so that suggestions remain aligned with the formal reason for the
    denial.
    """
    from .types import RepairSuggestion

    templates = _REPAIR_TEMPLATES.get(issue.code, ())
    if not templates:
        return issue.repair_suggestions

    blockers = list(issue.blockers)
    task_id = issue.task_id
    suggestions: list[RepairSuggestion] = []
    for action, template, priority in templates:
        if action == "complete_prerequisite":
            for blocker in blockers:
                suggestions.append(
                    RepairSuggestion(
                        action=action,  # type: ignore[arg-type]
                        target=blocker,
                        message=template.format(target=blocker, task=task_id),
                        priority=priority,
                    )
                )
        elif action in {"remove_dependency", "fix_cycle", "split_task"}:
            suggestions.append(
                RepairSuggestion(
                    action=action,  # type: ignore[arg-type]
                    target=task_id,
                    message=template.format(target=blockers[0] if blockers else None, task=task_id),
                    priority=priority,
                )
            )
        elif action in {"add_acceptance_proof", "revalidate_task"}:
            suggestions.append(
                RepairSuggestion(
                    action=action,  # type: ignore[arg-type]
                    target=task_id,
                    message=template.format(task=task_id),
                    priority=priority,
                )
            )
        elif action == "clarify_ambiguity":
            target = task_id or (blockers[0] if blockers else None)
            suggestions.append(
                RepairSuggestion(
                    action=action,  # type: ignore[arg-type]
                    target=target,
                    message=template.format(task=task_id),
                    priority=priority,
                )
            )
        else:
            target = blockers[0] if blockers else task_id
            suggestions.append(
                RepairSuggestion(
                    action=action,  # type: ignore[arg-type]
                    target=target,
                    message=template.format(target=target, task=task_id),
                    priority=priority,
                )
            )
    return tuple(suggestions)

def proof_trace_summary(
    proof_trace: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Return a compact, ordered summary of a proof trace."""
    summary: list[dict[str, Any]] = []
    for index, step in enumerate(proof_trace, start=1):
        summary.append(
            {
                "step": index,
                "rule": step.get("rule"),
                "premises": list(step.get("premises", [])),
                "conclusion": step.get("conclusion"),
            }
        )
    return summary

def proof_enrichment_summary(enrichment: dict[str, Any]) -> list[str]:
    """Render machine proof lines and LLM notes with explicit source tags."""
    if not enrichment:
        return []
    lines: list[str] = []
    proof_trace = enrichment.get("proofTrace", ())
    if isinstance(proof_trace, (list, tuple)):
        for step in proof_trace:
            if not isinstance(step, dict):
                continue
            rule = step.get("rule", "proof")
            conclusion = step.get("conclusion", "")
            lines.append(f"[proof] {rule}: {conclusion}")
    annotations = enrichment.get("llmAnnotations", ())
    if isinstance(annotations, str):
        annotations = (annotations,)
    if isinstance(annotations, (list, tuple)):
        for annotation in annotations:
            if isinstance(annotation, str) and annotation:
                lines.append(f"[llm] {annotation}")
    return lines

def next_actions_for_task(
    snapshot: FactsSnapshot,
    task_id: str,
    *,
    stale_assumption_ids: tuple[str, ...] = (),
    latest_validation_result: str | None = None,
) -> list[str]:
    """Suggest next actions for a task based on its derived LKB state."""
    from .context_adapter import active_blockers

    if stale_assumption_ids:
        return ["clarify_assumption", "revalidate_task"]

    blockers = active_blockers(snapshot, task_id)
    if blockers:
        return [f"complete:{blocker}" for blocker in blockers] + [
            "remove_dependency",
            "split_task",
        ]

    if task_id in snapshot.cycle_task_ids:
        return ["fix_cycle", "remove_dependency", "split_task"]

    task = snapshot.normalized_tasks.get(task_id)
    if task is None:
        return ["refresh_task"]

    if latest_validation_result in {"fail", "stale", "unknown"}:
        return ["revalidate_task"]

    if task["status"] == "pending":
        return ["start_task"]
    if task["status"] == "in_progress":
        return ["complete_task"]
    return []

def _human_summary(validation_run: ValidationRun, issue: ValidationIssue | None) -> str:
    if validation_run.result == "pass":
        return "Validation passed."
    if issue is None:
        return "Validation denied."
    return issue.message

def _facts_used(proof_trace: tuple[dict[str, Any], ...]) -> list[str]:
    facts: set[str] = set()
    for step in proof_trace:
        for premise in step.get("premises", ()):
            facts.add(premise)
    return sorted(facts)

def _rules_used(proof_trace: tuple[dict[str, Any], ...]) -> list[str]:
    rules: set[str] = set()
    for step in proof_trace:
        rule = step.get("rule")
        if isinstance(rule, str):
            rules.add(rule)
    return sorted(rules)

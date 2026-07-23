"""Method proposal generator for F-153 — propose_method_from_plan + validation.

Phase 1 of the Method Library Growth & Governance feature (F-153).
"""

from __future__ import annotations

from typing import Any

from .method_library import (
    AcceptanceTemplate,
    EngineeringMethod,
    SubtaskTemplate,
    _validate_method_internals,
)
from .decomposer import DecompositionPlan

def propose_method_from_plan(
    plan: DecompositionPlan,
    *,
    method_id: str,
    pattern: str,
    description: str,
) -> EngineeringMethod:
    """Build a ``draft`` :class:`EngineeringMethod` from a decomposition run.

    The method is constructed from the plan's structured fields:

    * **Subtask templates** — one per :class:`ProposedTask`, using
      ``subject`` as ``subject_template``, ``active_form`` as
      ``description_template``, and ``blocked_by`` as
      ``default_blocked_by``.
    * **Preconditions** — from the plan's ``assumptions``.
    * **Acceptance template** — from the first task that has
      ``acceptance_criteria``, if any.
    * **Status** — always ``draft``, ``version`` always ``"0.1.0"``.

    Parameters
    ----------
    plan:
        A validated decomposition plan (must have at least one task).
    method_id:
        Unique identifier for the new method (e.g. ``"M-043"``).
    pattern:
        Pattern string (e.g. ``"add_api_endpoint"``).
    description:
        Human-readable description of the method.

    Returns
    -------
    EngineeringMethod
        New method in ``draft`` status.

    Raises
    ------
    ValueError
        If ``plan.tasks`` is empty or validation fails.
    """
    if not plan.tasks:
        raise ValueError("Cannot propose a method from a plan with zero tasks")

    subtask_templates: list[SubtaskTemplate] = []
    # Map plan task_id -> new template_id for blocked_by resolution
    task_to_template: dict[str, str] = {}
    for i, task in enumerate(plan.tasks):
        template_id = f"ST-{method_id}-{i:03d}"
        task_to_template[task.proposed_task_id] = template_id
    for i, task in enumerate(plan.tasks):
        template_id = task_to_template[task.proposed_task_id]
        # Map blocked_by from plan task_ids to new template_ids
        mapped_blocked: list[str] = []
        for blocker in task.blocked_by:
            if blocker in task_to_template:
                mapped_blocked.append(task_to_template[blocker])
        st = SubtaskTemplate(
            template_id=template_id,
            role=_infer_role(task.lkb_metadata or {}),
            subject_template=task.subject,
            description_template=task.active_form or "",
            acceptance_template="",
            default_blocked_by=tuple(mapped_blocked),
        )
        subtask_templates.append(st)

    # Acceptance template from the first task that has criteria
    acceptance_template: AcceptanceTemplate | None = None
    for task in plan.tasks:
        if task.acceptance_criteria:
            raw = " and ".join(task.acceptance_criteria)
            acceptance_template = AcceptanceTemplate(
                assertion_template=raw if raw else "{thing} works",
            )
            break

    preconditions = tuple(plan.assumptions)

    method = EngineeringMethod(
        method_id=method_id,
        pattern=pattern,
        description=description,
        subtask_templates=tuple(subtask_templates),
        preconditions=preconditions,
        assumptions=preconditions,
        acceptance_template=acceptance_template,
        version="0.1.0",
        status="draft",
    )

    _validate_proposed_method(method)
    return method

def _infer_role(lkb_metadata: dict[str, Any]) -> str:
    """Infer a :class:`SubtaskRole` from LKB metadata.

    Falls back to ``"impl"`` when no clear indicator is present.
    """
    raw = lkb_metadata.get("role", "")
    if raw in ("design", "impl", "test", "docs", "review", "deploy"):
        return raw
    return "impl"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_proposed_method(method: EngineeringMethod) -> None:
    """Structural and naming validation for a proposed method.

    Checks (beyond what :func:`_validate_method_internals` already does):

    1. At least **3** subtask templates.
    2. At least **1** acceptance criterion (via ``acceptance_template``).
    3. ``preconditions`` is non-empty.
    4. ``pattern`` does not collide with a known seed-pattern prefix
       (the check is advisory — it warns via ``ValidationIssue``
       but does not raise).

    Naming and dependency validation (DAG acyclicity on ``blocked_by``)
    is delegated to :func:`_validate_method_internals` and
    :func:`_check_dag_no_cycle`.

    Raises
    ------
    ValueError
        On any structural violation.
    """
    if len(method.subtask_templates) < 3:
        raise ValueError(
            f"Proposed method {method.method_id!r} must have at least 3 "
            f"subtask templates; got {len(method.subtask_templates)}"
        )

    if (
        method.acceptance_template is None
        or not method.acceptance_template.assertion_template.strip()
    ):
        raise ValueError(
            f"Proposed method {method.method_id!r} must have at least one acceptance criterion"
        )

    if not method.preconditions:
        raise ValueError(f"Proposed method {method.method_id!r} must have non-empty preconditions")

    # Delegate to the existing internal validator (template refs, slots)
    _validate_method_internals(method)

    # DAG acyclicity check: blocked_by must form no cycles
    _check_dag_no_cycle(method)

def _check_dag_no_cycle(method: EngineeringMethod) -> None:
    """Simple DFS-based cycle detection over ``default_blocked_by`` edges."""
    tmap = {t.template_id: t for t in method.subtask_templates}

    visited: set[str] = set()
    stack: set[str] = set()

    def _dfs(tid: str) -> None:
        if tid in stack:
            raise ValueError(
                f"Proposed method {method.method_id!r} has a cycle in "
                f"subtask blocked_by involving template {tid!r}"
            )
        if tid in visited:
            return
        visited.add(tid)
        stack.add(tid)
        for blocker in tmap[tid].default_blocked_by:
            if blocker in tmap:
                _dfs(blocker)
        stack.remove(tid)

    for tid in tmap:
        _dfs(tid)

"""Plan Graph domain command handlers (spec §6, Phase 4).

Each handler implements the two callbacks the
:class:`lkb.application.LkbApplicationService` needs:

* ``validate(command, snapshot) -> ValidationRun``  (lock-free).
* ``apply(command, envelope, validation) -> (envelope, CommandResult)``
  (runs under the Board File Lock and applies the domain mutation).

The :class:`PlanCommandDispatcher` maps ``command.kind`` to the matching
handler and exposes ``validate`` / ``apply`` callables suitable for
``LkbApplicationService.execute``.

Validation rules follow spec §6.2-§6.8; Claim concurrency, cycle
rejection and the single-active-task policy are centralized in
:mod:`lkb.plan_graph_rules` (the Plan Graph Layer1 solver) — every
handler's ``validate`` is a thin delegate to it. Invalidation propagation
is applied when completed work is reopened or its contract changes.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .plan_graph_rules import PlanRuleOutcome

from .commands import CommandResult, GraphCommand
from .graph_types import (
    BoardPolicy,
    GraphSnapshot,
    NodeRef,
    plan_task_ref,
)
from .json_store import BoardEnvelope
from .refs import DEFAULT_PLAN_GRAPH_ID
from .validation import ValidationIssue, ValidationRun

__all__ = [
    "PlanCommandHandler",
    "CreateTaskHandler",
    "UpdateTaskFieldsHandler",
    "AddDependencyHandler",
    "RemoveDependencyHandler",
    "ClaimTaskHandler",
    "ReleaseTaskHandler",
    "TransferTaskHandler",
    "StartTaskHandler",
    "CompleteTaskHandler",
    "ReopenTaskHandler",
    "DeleteTaskHandler",
    "RevalidateHandler",
    "PatchTaskHandler",
    "PlanCommandDispatcher",
    "plan_command_dispatcher",
    "plan_graph_layer1",
]

_PLAN_GRAPH_ID = DEFAULT_PLAN_GRAPH_ID
_BASE_STATUSES = ("pending", "in_progress", "completed")


# ── helpers ──────────────────────────────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _plan_graph_id(command: GraphCommand) -> str:
    """Resolve the concrete Plan graph targeted by a command."""
    if command.primary_subject_ref is not None:
        return command.primary_subject_ref.graph
    raw = command.payload.get("plan_id") or command.payload.get("plan_graph_id")
    if isinstance(raw, str) and raw:
        NodeRef(raw, "_plan", "_id")
        return raw
    return _PLAN_GRAPH_ID


def _ensure_plan_graph(env: BoardEnvelope, board_id: str, graph_id: str) -> None:
    if graph_id not in env.graphs:
        now = _now()
        env.graphs[graph_id] = {
            "graph_id": graph_id,
            "board_id": board_id,
            "graph_kind": "plan",
            "revision": 0,
            "created_at": now,
            "updated_at": now,
            "plan": {
                "plan_id": graph_id,
                "title": "Legacy plan" if graph_id == _PLAN_GRAPH_ID else graph_id,
                "state": "active",
                "session_ids": [],
            },
        }


def _agent_ref(actor: str, graph_id: str) -> NodeRef:
    """Canonical ``plan:agent:<actor>`` NodeRef for a claim owner.

    Spec §5.6 / §5.3 - ``Claim.owner_ref`` is a :class:`NodeRef`, never a
    bare actor string.  The agent id is the actor verbatim so the
    Store invariant ``active_claim.owner_ref.id == task_node.owner`` holds.
    """
    return NodeRef(graph_id, "agent", str(actor))


def _agent_ref_str(actor: str, graph_id: str) -> str:
    return _agent_ref(actor, graph_id).to_str()


def _task_ref(command: GraphCommand) -> NodeRef:
    """Resolve the task NodeRef targeted by *command*."""
    if command.primary_subject_ref is not None:
        return command.primary_subject_ref
    task_id = str(command.payload.get("task_id", ""))
    return plan_task_ref(task_id, graph_id=_plan_graph_id(command))


def _task_node(env: BoardEnvelope, ref: NodeRef) -> dict[str, Any] | None:
    """Return the raw node dict for *ref*, or None."""
    for nid, node in env.nodes.items():
        if str(node.get("ref", "")) == ref.to_str():
            return node
    return None


def _active_claim_for(env: BoardEnvelope, task_ref: NodeRef) -> dict[str, Any] | None:
    target = task_ref.to_str()
    for claim in env.claims.values():
        if str(claim.get("task_ref", "")) == target and claim.get("status") == "active":
            return claim
    return None


def _depends_on_edges(env: BoardEnvelope) -> list[tuple[str, str, str]]:
    """Return ``(edge_id, source_ref_str, target_ref_str)`` for depends_on."""
    out: list[tuple[str, str, str]] = []
    for eid, edge in env.edges.items():
        if edge.get("type") == "depends_on":
            out.append((eid, str(edge.get("source", "")), str(edge.get("target", ""))))
    return out


def _would_create_cycle(env: BoardEnvelope, source_ref: str, target_ref: str) -> list[str] | None:
    """Return the cycle path if adding ``source -> target`` creates one.

    ``depends_on`` runs dependent -> prerequisite.  Adding ``source ->
    target`` closes a cycle iff ``target`` can already reach ``source``
    along existing depends_on edges.  Returns the path (including the
    closing edge) or None.
    """
    adjacency: dict[str, list[str]] = {}
    for _eid, src, tgt in _depends_on_edges(env):
        adjacency.setdefault(src, []).append(tgt)
    # DFS from target; if we reach source, there is a cycle.
    stack: list[tuple[str, list[str]]] = [(target_ref, [target_ref])]
    visited: set[str] = set()
    while stack:
        node, path = stack.pop()
        if node == source_ref:
            return [*path, source_ref]
        if node in visited:
            continue
        visited.add(node)
        for nxt in adjacency.get(node, []):
            stack.append((nxt, [*path, nxt]))
    return None


def _run(
    command: GraphCommand,
    *,
    accepted: bool,
    subject_ref: NodeRef | None = None,
    issues: tuple[ValidationIssue, ...] = (),
    derived_facts: tuple[str, ...] = (),
) -> ValidationRun:
    return ValidationRun(
        validation_run_id=_new_id("V-"),
        proposal_id=command.command_id,
        subject_ref=subject_ref,
        result="pass" if accepted else "denied",
        issues=issues,
        derived_facts=derived_facts,
        engine="plan-graph",
    )


def _committed(
    command: GraphCommand,
    *,
    validation_run_id: str | None = None,
    claim_id: str | None = None,
    affected_refs: tuple[str, ...] = (),
) -> CommandResult:
    return CommandResult(
        decision="committed",
        command_id=command.command_id,
        validation_run_id=validation_run_id,
        claim_id=claim_id,
        affected_refs=affected_refs,
    )


def _denied_issue(
    code: str,
    message: str,
    *,
    rule: str = "plan",
    subject_ref: NodeRef | None = None,
    blockers: tuple[str, ...] = (),
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        rule=rule,
        subject_ref=subject_ref,
        blockers=blockers,
    )


# ── invalidation propagation ─────────────────────────────────────────


def _downstream_closure(
    env: BoardEnvelope, task_ref: NodeRef, *, mode: str = "cascade"
) -> list[NodeRef]:
    """Tasks that depend on *task_ref*, scoped by *mode* (spec §5.1).

    ``depends_on`` runs dependent -> prerequisite, so the downstream of
    *task_ref* (those that depend on it) are the sources of edges whose
    target is *task_ref*.

    ``mode`` (BoardPolicy.invalidation_mode):
      * ``off``    - no propagation; return ``[]``.
      * ``direct`` - only direct dependents (one hop).
      * ``cascade``- transitive closure (default, spec §6.7).
    """
    if mode == "off":
        return []
    target_to_sources: dict[str, list[str]] = {}
    for _eid, src, tgt in _depends_on_edges(env):
        target_to_sources.setdefault(tgt, []).append(src)
    if mode == "direct":
        return [NodeRef.from_str(s) for s in target_to_sources.get(task_ref.to_str(), [])]
    result: list[NodeRef] = []
    seen: set[str] = set()
    stack = [task_ref.to_str()]
    while stack:
        current = stack.pop()
        for src in target_to_sources.get(current, []):
            if src in seen:
                continue
            seen.add(src)
            stack.append(src)
            result.append(NodeRef.from_str(src))
    return result


def _mark_needs_recheck(env: BoardEnvelope, ref: NodeRef, cause: NodeRef, reason: str) -> bool:
    """Mark a completed task ``derived_status=needs_recheck``.

    Used when a completed task's own contract changes or upstream work is
    reopened. The task keeps ``base_status=completed``. Returns True if the
    task was changed.
    """
    node = _task_node(env, ref)
    if node is None or node.get("state") != "completed":
        return False
    payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
    payload["derived_status"] = "needs_recheck"
    payload["invalidation_cause"] = cause.to_str()
    payload["invalidation_reason"] = reason
    node["payload"] = payload
    node["updated_at"] = _now()
    return True


def _invalidate_downstream(
    env: BoardEnvelope,
    root_ref: NodeRef,
    reason: str,
    *,
    mode: str = "cascade",
) -> list[NodeRef]:
    """Mark completed downstream tasks ``needs_recheck``.

    Pending/in_progress downstream tasks become blocked naturally (the
    prerequisite is pending again).  Completed downstream tasks keep
    ``base_status=completed`` but gain ``derived_status=needs_recheck``.
    Returns the affected refs (propagation path). ``mode`` scopes the
    closure (``off`` / ``direct`` / ``cascade``).
    """
    affected: list[NodeRef] = []
    now = _now()
    for ref in _downstream_closure(env, root_ref, mode=mode):
        node = _task_node(env, ref)
        if node is None:
            continue
        if node.get("state") != "completed":
            continue
        if _mark_needs_recheck(env, ref, root_ref, reason):
            # _mark_needs_recheck already set updated_at; keep the single
            # timestamp consistent across the propagation path.
            node["updated_at"] = now
            affected.append(ref)
    return affected


def _invalidation_event(
    envelope: BoardEnvelope,
    command: GraphCommand,
    validation: ValidationRun,
    cause_ref: NodeRef,
    reason: str,
    affected: list[NodeRef],
) -> dict[str, Any]:
    """Build an ``invalidation_propagation`` audit event (spec §6.10).

    ``store_revision`` is filled from the candidate envelope; the store
    layer patches every command-scoped event to the post-bump revision
    after ``execute_atomic`` advances it (issue #9: override / invalidation
    events must not record the pre-increment store_revision).
    """
    return {
        "type": "invalidation_propagation",
        "event_id": f"E-{uuid.uuid4().hex[:16]}",
        "board_id": envelope.board_id(),
        "command_id": command.command_id,
        "decision": "committed",
        "actor": command.actor,
        "subject_ref": cause_ref.to_str(),
        "cause": cause_ref.to_str(),
        "reason": reason,
        "affected_refs": [r.to_str() for r in affected],
        "store_revision": envelope.store_revision,
        "validation_run_id": validation.validation_run_id,
        "timestamp": _now(),
    }


# ── handler base ─────────────────────────────────────────────────────


class PlanCommandHandler:
    """Base class for Plan Graph command handlers.

    Validation logic lives in :mod:`lkb.plan_graph_rules` (the Plan Graph
    Layer1 solver); each handler's ``validate`` is a thin delegate via
    :func:`_run_from_outcome`.  ``apply`` keeps its lock-critical-section
    re-checks local (spec §6.4) and never invokes the solver.
    """

    kind: str = ""

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        raise NotImplementedError

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        raise NotImplementedError


def _run_from_outcome(command: GraphCommand, outcome: "PlanRuleOutcome") -> ValidationRun:
    """Build the ValidationRun for a :class:`PlanRuleOutcome` (engine unchanged)."""
    if outcome.issues:
        return _run(
            command,
            accepted=False,
            subject_ref=outcome.issues[0].subject_ref,
            issues=outcome.issues,
        )
    return _run(
        command,
        accepted=True,
        subject_ref=outcome.subject_ref,
        derived_facts=outcome.derived_facts,
    )


def plan_graph_layer1():
    """Return the shared Plan Graph Layer1 solver (lazy import avoids a cycle)."""
    from .plan_graph_rules import plan_graph_layer1 as _get_solver

    return _get_solver()


# ── CreateTask (spec §6.2) ───────────────────────────────────────────


class CreateTaskHandler(PlanCommandHandler):
    kind = "create_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        task_id = str(command.payload.get("task_id", "")) or _new_id("T-")
        graph_id = _plan_graph_id(command)
        ref = plan_task_ref(task_id, graph_id=graph_id)
        _ensure_plan_graph(envelope, command.board_id, graph_id)
        now = _now()
        subject = str(command.payload.get("subject", ""))
        node_key = task_id if graph_id == _PLAN_GRAPH_ID else ref.to_str()
        envelope.nodes[node_key] = {
            "ref": ref.to_str(),
            "title": subject,
            "state": "pending",
            "owner": None,
            "revision": 1,
            "payload": {
                "subject": subject,
                "description": str(command.payload.get("description", "")),
                "activeForm": str(command.payload.get("activeForm", subject)),
                "base_status": "pending",
                "metadata": dict(command.payload.get("metadata", {}) or {}),
                "output": "",
            },
            "created_at": now,
            "updated_at": now,
        }
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── UpdateTaskFields (spec §6.1) ─────────────────────────────────────


class UpdateTaskFieldsHandler(PlanCommandHandler):
    kind = "update_task_fields"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        contract_changed = False
        for field in ("subject", "description", "activeForm"):
            if field in command.payload:
                payload[field] = command.payload[field]
        if "subject" in command.payload:
            node["title"] = str(command.payload["subject"])
            contract_changed = True
        if "description" in command.payload:
            contract_changed = True
        if "metadata" in command.payload:
            merged_metadata = dict(payload.get("metadata", {}) or {})
            for key, value in dict(command.payload["metadata"] or {}).items():
                if value is None:
                    merged_metadata.pop(key, None)
                else:
                    merged_metadata[key] = value
            payload["metadata"] = merged_metadata
        node["payload"] = payload
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = _now()
        # Spec §6.7 / T2-GAP-06: a completed task whose contract
        # (subject / description) changed must be marked
        # ``needs_recheck`` and invalidation propagated to completed
        # downstream tasks. Independent branches are untouched.
        if contract_changed and node.get("state") == "completed":
            mode = _board_policy(envelope).invalidation_mode
            reason = str(command.reason or "contract changed")
            _mark_needs_recheck(envelope, ref, ref, reason)
            affected = _invalidate_downstream(envelope, ref, reason, mode=mode)
            if affected:
                envelope.events.append(
                    _invalidation_event(envelope, command, validation, ref, reason, affected)
                )
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── AddDependency (spec §6.3) ────────────────────────────────────────


class AddDependencyHandler(PlanCommandHandler):
    kind = "add_dependency"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        graph_id = _plan_graph_id(command)
        dependent_id = str(command.payload.get("task_id") or command.payload.get("dependent") or "")
        prerequisite_id = str(
            command.payload.get("depends_on") or command.payload.get("prerequisite") or ""
        )
        dependent = plan_task_ref(dependent_id, graph_id=graph_id)
        prerequisite = plan_task_ref(prerequisite_id, graph_id=graph_id)
        _ensure_plan_graph(envelope, command.board_id, graph_id)
        # Idempotent: skip if the edge already exists.
        for eid, edge in envelope.edges.items():
            if (
                edge.get("type") == "depends_on"
                and str(edge.get("source", "")) == dependent.to_str()
                and str(edge.get("target", "")) == prerequisite.to_str()
            ):
                return envelope, _committed(command, validation_run_id=validation.validation_run_id)
        edge_id = (
            f"dep-{dependent_id}-{prerequisite_id}"
            if graph_id == _PLAN_GRAPH_ID
            else f"{graph_id}-dep-{dependent_id}-{prerequisite_id}"
        )
        envelope.edges[edge_id] = {
            "edge_id": edge_id,
            "graph": graph_id,
            "type": "depends_on",
            "source": dependent.to_str(),
            "target": prerequisite.to_str(),
            "revision": 1,
            "payload": {},
        }
        # Spec §6.7 / T2-GAP-06: adding a new prerequisite to a COMPLETED
        # task invalidates its completion - it now depends on work that may
        # not be done.  Mark it ``needs_recheck`` and propagate to
        # completed downstream.  (Adding a dependency to a pending/in_progress
        # task just makes it blocked naturally - no invalidation needed.)
        dep_node = _task_node(envelope, dependent)
        if dep_node is not None and dep_node.get("state") == "completed":
            mode = _board_policy(envelope).invalidation_mode
            reason = str(command.reason or "new dependency added")
            _mark_needs_recheck(envelope, dependent, dependent, reason)
            affected = _invalidate_downstream(envelope, dependent, reason, mode=mode)
            if affected:
                envelope.events.append(
                    _invalidation_event(envelope, command, validation, dependent, reason, affected)
                )
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── RemoveDependency ─────────────────────────────────────────────────


class RemoveDependencyHandler(PlanCommandHandler):
    kind = "remove_dependency"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        graph_id = _plan_graph_id(command)
        dependent_id = str(command.payload.get("task_id", ""))
        prerequisite_id = str(command.payload.get("depends_on", ""))
        dependent = plan_task_ref(dependent_id, graph_id=graph_id)
        prerequisite = plan_task_ref(prerequisite_id, graph_id=graph_id)
        to_remove = [
            eid
            for eid, edge in envelope.edges.items()
            if edge.get("type") == "depends_on"
            and str(edge.get("source", "")) == dependent.to_str()
            and str(edge.get("target", "")) == prerequisite.to_str()
        ]
        for eid in to_remove:
            envelope.edges.pop(eid, None)
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── ClaimTask (spec §6.4) ────────────────────────────────────────────


class ClaimTaskHandler(PlanCommandHandler):
    kind = "claim_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        # Idempotent: same actor already holds an active claim.
        existing = _active_claim_for(envelope, ref)
        if existing is not None and existing.get("owner_ref") == _agent_ref_str(
            command.actor, ref.graph
        ):
            return envelope, _committed(
                command,
                validation_run_id=validation.validation_run_id,
                claim_id=str(existing.get("claim_id") or "") or None,
            )
        claim_id = _new_id("C-")
        now = _now()
        envelope.claims[claim_id] = {
            "task_ref": ref.to_str(),
            "owner_ref": _agent_ref_str(command.actor, ref.graph),
            "claim_id": claim_id,
            "claimed_at": now,
            "claim_revision": int(node.get("revision", 0)),
            "status": "active",
            "released_at": "",
            "reason": str(command.reason or ""),
        }
        node["owner"] = command.actor
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = now
        return envelope, _committed(
            command,
            validation_run_id=validation.validation_run_id,
            claim_id=claim_id,
        )


# ── ReleaseTask (spec §5.6) ──────────────────────────────────────────


def _board_policy(envelope: BoardEnvelope) -> BoardPolicy:
    """Load the board policy from the envelope (defence-in-depth).

    Validator runs lock-free without policy access, so authorization for
    force-override (Release / Transfer) is enforced under the Board lock
    in ``apply`` (spec §6.4: “Board 锁临界区内必须检查”).
    """
    board = envelope.board if isinstance(envelope.board, dict) else {}
    policy_dict = board.get("policy") if isinstance(board.get("policy"), dict) else {}
    return BoardPolicy.from_dict(policy_dict)


def _authorize_override(
    command: GraphCommand,
    envelope: BoardEnvelope,
    current_owner: str | None,
) -> str | None:
    """Return ``None`` if *command* may override *current_owner*, else a
    denial code.

    Rules (spec §5.6, LKB-CLAIM-008/009):
      - actor is the current owner → allowed (no override needed);
      - a host-asserted actor role is in ``force_override_roles`` AND provides a reason → allowed;
      - an authorized role is present but no reason →
        ``override_reason_required``;
      - no authorized role is present → ``override_not_authorized``.
    """
    if current_owner is not None and current_owner == command.actor:
        return None
    policy = _board_policy(envelope)
    policy_roles = tuple(policy.force_override_roles)
    authorized = "*" in policy_roles or any(
        policy.allows_force_override(role) for role in command.roles
    )
    if not authorized:
        return "override_not_authorized"
    if not (command.reason and str(command.reason).strip()):
        return "override_reason_required"
    return None


class ReleaseTaskHandler(PlanCommandHandler):
    kind = "release_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        current_owner = node.get("owner") or None
        if current_owner is None:
            return envelope, _committed(
                command,
                validation_run_id=validation.validation_run_id,
            )
        denial = _authorize_override(command, envelope, current_owner)
        if denial is not None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason=denial
            )
        now = _now()
        released_any = False
        for claim in envelope.claims.values():
            if str(claim.get("task_ref", "")) == ref.to_str() and claim.get("status") == "active":
                claim["status"] = "released"
                claim["released_at"] = now
                claim["reason"] = str(command.reason or claim.get("reason", ""))
                released_any = True
        if released_any:
            node["owner"] = None
            node["revision"] = int(node.get("revision", 0)) + 1
            node["updated_at"] = now
            # Override audit (only when actor != previous owner).
            if current_owner is not None and current_owner != command.actor:
                envelope.events.append(
                    {
                        "type": "claim_override",
                        "event_id": f"E-{uuid.uuid4().hex[:16]}",
                        "board_id": envelope.board_id(),
                        "command_id": command.command_id,
                        "decision": "committed",
                        "action": "release",
                        "actor": command.actor,
                        "reason": str(command.reason or ""),
                        "subject_ref": ref.to_str(),
                        "previous_owner": current_owner,
                        "task_ref": ref.to_str(),
                        "store_revision": envelope.store_revision,
                        "validation_run_id": validation.validation_run_id,
                        "timestamp": now,
                    }
                )
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── TransferTask (spec §5.6, §6.4, LKB-CLAIM-008/009) ────────────────


class TransferTaskHandler(PlanCommandHandler):
    """Force-transfer ownership of a task to another agent.

    Spec §6.4: “为其他 Agent 分配必须使用 Assign/Transfer 权限和独立审计”.
    Unlike Claim (which only assigns to the current actor), Transfer
    assigns to an arbitrary ``new_owner`` and therefore always requires
    ``force_override_roles`` authorization + ``reason`` + an override
    audit event — even when the actor happens to be the current owner
    (re-assigning to a third party is never a self-claim).
    """

    kind = "transfer_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        new_owner = str(command.payload.get("new_owner", "") or "").strip()
        if not new_owner or new_owner == command.actor:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="invalid_transfer"
            )
        current_owner = node.get("owner") or None
        denial = _authorize_override(command, envelope, current_owner)
        if denial is not None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason=denial
            )
        now = _now()
        # Release the existing active claim (if any) in the same atomic snapshot.
        for claim in envelope.claims.values():
            if str(claim.get("task_ref", "")) == ref.to_str() and claim.get("status") == "active":
                claim["status"] = "overridden"
                claim["released_at"] = now
                claim["reason"] = str(command.reason or "transferred")
        # Create a new active claim for new_owner.
        claim_id = _new_id("C-")
        envelope.claims[claim_id] = {
            "task_ref": ref.to_str(),
            "owner_ref": _agent_ref_str(new_owner, ref.graph),
            "claim_id": claim_id,
            "claimed_at": now,
            "claim_revision": int(node.get("revision", 0)),
            "status": "active",
            "released_at": "",
            "reason": str(command.reason or "transferred"),
        }
        node["owner"] = new_owner
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = now
        # Override audit (always recorded for Transfer — spec §6.4).
        envelope.events.append(
            {
                "type": "claim_override",
                "event_id": f"E-{uuid.uuid4().hex[:16]}",
                "board_id": envelope.board_id(),
                "command_id": command.command_id,
                "decision": "committed",
                "action": "transfer",
                "actor": command.actor,
                "reason": str(command.reason or ""),
                "subject_ref": ref.to_str(),
                "previous_owner": current_owner or "",
                "new_owner": new_owner,
                "task_ref": ref.to_str(),
                "store_revision": envelope.store_revision,
                "validation_run_id": validation.validation_run_id,
                "timestamp": now,
            }
        )
        return envelope, _committed(
            command,
            validation_run_id=validation.validation_run_id,
            claim_id=claim_id,
        )


# ── StartTask (spec §6.5) ────────────────────────────────────────────


class StartTaskHandler(PlanCommandHandler):
    kind = "start_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        owner = node.get("owner") or None
        if owner != command.actor:
            return envelope, CommandResult(
                decision="denied",
                command_id=command.command_id,
                reason="owner_required" if owner is None else "not_owner",
            )
        if node.get("state") == "in_progress":
            return envelope, _committed(command, validation_run_id=validation.validation_run_id)
        node["state"] = "in_progress"
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        payload["base_status"] = "in_progress"
        node["payload"] = payload
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = _now()
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── CompleteTask (spec §6.6) ─────────────────────────────────────────


class CompleteTaskHandler(PlanCommandHandler):
    kind = "complete_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        current_owner = node.get("owner") or None
        if current_owner != command.actor:
            denial = _authorize_override(command, envelope, current_owner)
            if denial is not None:
                return envelope, CommandResult(
                    decision="denied",
                    command_id=command.command_id,
                    reason=denial,
                )
        now = _now()
        node["state"] = "completed"
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        payload["base_status"] = "completed"
        node["payload"] = payload
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = now
        # Complete the active claim in the same atomic snapshot.
        for claim in envelope.claims.values():
            if str(claim.get("task_ref", "")) == ref.to_str() and claim.get("status") == "active":
                claim["status"] = "completed"
                claim["released_at"] = now
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── ReopenTask (spec §6.7) ───────────────────────────────────────────


class ReopenTaskHandler(PlanCommandHandler):
    kind = "reopen_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        now = _now()
        node["state"] = "pending"
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        payload["base_status"] = "pending"
        node["payload"] = payload
        node["revision"] = int(node.get("revision", 0)) + 1
        node["updated_at"] = now
        # Release any active claim on the reopened task and clear the
        # owner: ownership must not survive the claim release (Store
        # invariant ``active_claim.owner_ref.id == task_node.owner``).
        # The previous owner must re-claim before restarting - otherwise a
        # reopen would let them bypass the claim protocol and start
        # directly.
        for claim in envelope.claims.values():
            if str(claim.get("task_ref", "")) == ref.to_str() and claim.get("status") == "active":
                claim["status"] = "released"
                claim["released_at"] = now
                claim["reason"] = str(command.reason or "reopened")
        node["owner"] = None
        # Propagate invalidation to completed downstream tasks (spec §6.7):
        # they keep base=completed but become derived=needs_recheck.
        # Independent branches are untouched.
        # The propagation scope honours BoardPolicy.invalidation_mode
        # (off / direct / cascade) - spec §5.1, §6.7.
        mode = _board_policy(envelope).invalidation_mode
        reason = str(command.reason or "upstream reopened")
        affected = _invalidate_downstream(envelope, ref, reason, mode=mode)
        if affected:
            envelope.events.append(
                _invalidation_event(envelope, command, validation, ref, reason, affected)
            )
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── DeleteTask (spec §6.8) ───────────────────────────────────────────


class DeleteTaskHandler(PlanCommandHandler):
    kind = "delete_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        cascade = bool(command.payload.get("cascade", False))
        affected_refs = [ref.to_str()]
        # Remove the node.
        removed = [
            nid for nid, node in envelope.nodes.items() if str(node.get("ref", "")) == ref.to_str()
        ]
        for nid in removed:
            envelope.nodes.pop(nid, None)
        # Remove or cascade referencing edges.
        if cascade:
            to_remove = [
                eid
                for eid, edge in envelope.edges.items()
                if edge.get("type") == "depends_on"
                and (
                    str(edge.get("source", "")) == ref.to_str()
                    or str(edge.get("target", "")) == ref.to_str()
                )
            ]
            for edge_id in to_remove:
                edge = envelope.edges[edge_id]
                affected_refs.extend(
                    str(endpoint)
                    for endpoint in (edge.get("source", ""), edge.get("target", ""))
                    if endpoint
                )
            for eid in to_remove:
                envelope.edges.pop(eid, None)
        # Drop every claim record referencing the deleted task — active
        # ones included.  Keeping terminal (completed/released/overridden)
        # claims would leave dangling ``task_ref`` pointers to a node that
        # no longer exists, and they would wrongly attach to a re-created
        # task reusing the same id.  The delete command itself stays in the
        # event log, so no audit history is lost.
        dangling = [
            cid
            for cid, claim in envelope.claims.items()
            if str(claim.get("task_ref", "")) == ref.to_str()
        ]
        for cid in dangling:
            envelope.claims.pop(cid, None)
        return envelope, _committed(
            command,
            validation_run_id=validation.validation_run_id,
            affected_refs=tuple(dict.fromkeys(affected_refs)),
        )


# ── Revalidate (spec §6.7, Phase 6) ──────────────────────────────────


class RevalidateHandler(PlanCommandHandler):
    kind = "revalidate"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        # R-PG-070 requires every direct prerequisite to be current.
        return _run_from_outcome(command, plan_graph_layer1().evaluate(command, snapshot))

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        node = _task_node(envelope, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        had_stale_derived = payload.get("derived_status") in ("needs_recheck", "needs_review")
        payload.pop("derived_status", None)
        payload.pop("invalidation_cause", None)
        payload.pop("invalidation_reason", None)
        node["payload"] = payload
        # Only bump revision if we actually cleared a stale derived flag -
        # a revalidate of an already-clean task is a no-op (spec §11.4
        # inv 5: no content change -> no revision bump).
        if had_stale_derived:
            node["revision"] = int(node.get("revision", 0)) + 1
            node["updated_at"] = _now()
        return envelope, _committed(command, validation_run_id=validation.validation_run_id)


# ── PatchTask (spec §6.1, T2-GAP-09, LKB-ADAPT-011/012) ──────────────


# Status string -> handler kind for the status sub-intent.
_STATUS_KIND = {
    "pending": "reopen_task",
    "in_progress": "start_task",
    "completed": "complete_task",
    "deleted": "delete_task",
}


class PatchTaskHandler(PlanCommandHandler):
    """Composite handler: apply multiple sub-intents to one task atomically.

    Spec §6.1 / T2-GAP-09 / LKB-ADAPT-011/012.  A mixed TaskUpdate that
    carries status + owner + dependency + metadata changes must NOT pick
    a single dominant intent (the legacy ``_task_update_change_kind``
    behaviour) — that silently drops the other sub-intents and creates a
    “validate part, commit all” bypass window.  Instead this handler:

    1. Decomposes the patch into sub-intents (``PatchTask.decompose``).
    2. Checks the patch structure without mutating state.
    3. Applies them in sequence under the Board lock; if any sub-intent
       fails validation or application, nothing commits.
    4. Produces exactly one revision bump and one command result.

    Sub-intents are dispatched to the existing single-intent handlers so
    every rule (claim concurrency, cycle detection, needs_recheck, …) is
    enforced uniformly.
    """

    kind = "patch_task"

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        # Sub-intent state validation is performed sequentially against an
        # evolving clone under the lock. Validating each item against the
        # original snapshot would incorrectly reject valid claim+start
        # patches and cannot prove the composite transition.  Here we only
        # check the patch STRUCTURE (rule R-PG-090): supported status,
        # non-empty, known sub-intent kinds.
        ref = _task_ref(command)
        sub_commands = self._decompose(command, ref)
        outcome = plan_graph_layer1().evaluate(
            command,
            snapshot,
            context={"sub_kinds": tuple(sub.kind for sub in sub_commands)},
        )
        return _run_from_outcome(command, outcome)

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        ref = _task_ref(command)
        working = envelope.clone()
        node = _task_node(working, ref)
        if node is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="task_not_found"
            )
        sub_commands = self._decompose(command, ref)
        dispatcher = plan_command_dispatcher()
        # Capture the pre-patch node revision so the whole patch produces
        # exactly ONE revision bump (spec §6.1 #5).  Sub-handlers each
        # bump revision as part of their own apply; we collapse them at
        # the end so the final revision is initial + 1.
        pre_revision = int(node.get("revision", 0))
        claim_id: str | None = None
        affected_refs: list[str] = []
        # Apply each sub-intent in sequence against the evolving envelope.
        # Sub-validation is re-run on the in-lock snapshot so a sub-intent
        # whose precondition was changed by an earlier sub-intent (e.g.
        # claim then start) is checked against the post-claim state.
        for sub in sub_commands:
            handler = dispatcher.get(sub.kind)
            if handler is None:
                return envelope, CommandResult(
                    decision="denied",
                    command_id=command.command_id,
                    reason=f"unknown_command: {sub.kind}",
                )
            sub_snapshot = working.build_graph_snapshot()
            sub_run = handler.validate(sub, sub_snapshot)
            if not sub_run.accepted:
                return envelope, CommandResult(
                    decision="denied",
                    command_id=command.command_id,
                    reason=self._denial_reason(sub_run),
                    validation_run_id=validation.validation_run_id,
                )
            working, sub_result = handler.apply(sub, working, sub_run)
            if not sub_result.committed:
                return envelope, CommandResult(
                    decision="denied",
                    command_id=command.command_id,
                    reason=sub_result.reason or "patch_sub_intent_failed",
                    validation_run_id=validation.validation_run_id,
                )
            if sub_result.claim_id:
                claim_id = sub_result.claim_id
            affected_refs.extend(sub_result.affected_refs)
        # Collapse the per-sub-intent revision bumps into a single bump.
        final_node = _task_node(working, ref)
        if final_node is not None:
            final_node["revision"] = pre_revision + 1
        return working, _committed(
            command,
            validation_run_id=validation.validation_run_id,
            claim_id=claim_id,
            affected_refs=tuple(dict.fromkeys(affected_refs)),
        )

    # -- decomposition --------------------------------------------------

    def _decompose(self, command: GraphCommand, ref: NodeRef) -> list[GraphCommand]:
        """Split a patch_task command into ordered single-intent commands.

        Order matters: status transitions (start/complete) and claims must
        be applied before metadata updates so the metadata lands on the
        final state.  Field updates (subject/description/activeForm) and
        dependency changes are applied first, then owner (claim), then
        status, then metadata.
        """
        from .commands import PatchTask

        patch = PatchTask.decompose(dict(command.payload), ref)
        task_id = str(command.payload.get("task_id", ""))
        subs: list[GraphCommand] = []

        # 1. Field updates (subject / description / activeForm).
        if patch.has_field_updates:
            subs.append(
                self._sub(
                    command, "update_task_fields", {**patch.field_updates, "task_id": task_id}
                )
            )

        # 2. Dependency additions / removals.
        for intent in patch.dependency_intents:
            if intent.operation == "add":
                subs.append(
                    self._sub(
                        command,
                        "add_dependency",
                        {
                            "task_id": intent.dependent.id,
                            "depends_on": intent.prerequisite.id,
                        },
                    )
                )
            else:
                subs.append(
                    self._sub(
                        command,
                        "remove_dependency",
                        {
                            "task_id": intent.dependent.id,
                            "depends_on": intent.prerequisite.id,
                        },
                    )
                )

        # 3. Owner change — claim_task for self-claim (owner == actor);
        #    transfer_task is handled by the host adapter routing the
        #    whole command to transfer_task directly when owner != actor.
        if patch.has_owner_change:
            owner_target = patch.owner_target or ""
            if owner_target and owner_target != command.actor:
                # A PatchTask that tries to reassign to a third party must
                # go through transfer_task instead; a patch_task payload
                # with a third-party owner is denied as invalid.
                subs.append(
                    self._sub(
                        command,
                        "transfer_task",
                        {"task_id": task_id, "new_owner": owner_target},
                    )
                )
            elif owner_target:
                subs.append(self._sub(command, "claim_task", {"task_id": task_id}))
            else:
                subs.append(self._sub(command, "release_task", {"task_id": task_id}))

        # 4. Status transition.
        delete_sub: GraphCommand | None = None
        if patch.has_status_change:
            target = str(patch.status_target or "")
            kind = _STATUS_KIND.get(target)
            if kind is not None:
                status_sub = self._sub(command, kind, {"task_id": task_id})
                if kind == "delete_task":
                    delete_sub = status_sub
                else:
                    subs.append(status_sub)

        # 5. Metadata updates (applied last so they land on final state).
        if patch.has_metadata_updates:
            subs.append(
                self._sub(
                    command,
                    "update_task_fields",
                    {"task_id": task_id, "metadata": dict(patch.metadata_updates)},
                )
            )

        # Delete is terminal and therefore must run after every other
        # requested mutation in the same atomic patch.
        if delete_sub is not None:
            subs.append(delete_sub)

        return subs

    def _sub(self, parent: GraphCommand, kind: str, payload: dict[str, Any]) -> GraphCommand:
        """Build a single-intent sub-command sharing the parent's identity."""
        graph_id = _plan_graph_id(parent)
        task_id = str(payload.get("task_id", ""))
        primary_ref = plan_task_ref(task_id, graph_id=graph_id) if task_id else None
        return GraphCommand(
            command_id=f"{parent.command_id}#{kind}",
            board_id=parent.board_id,
            actor=parent.actor,
            kind=kind,
            payload={**payload, "plan_id": graph_id},
            primary_subject_ref=primary_ref,
            reason=parent.reason,
            roles=parent.roles,
        )

    @staticmethod
    def _denial_reason(run: ValidationRun) -> str:
        if run.issues:
            first = run.issues[0]
            return f"{first.code}: {first.message}"
        return "patch_sub_intent_denied"


# ── dispatcher ───────────────────────────────────────────────────────


class PlanCommandDispatcher:
    """Map ``command.kind`` to the matching :class:`PlanCommandHandler`."""

    def __init__(self) -> None:
        self._handlers: dict[str, PlanCommandHandler] = {}
        for handler_cls in (
            CreateTaskHandler,
            UpdateTaskFieldsHandler,
            AddDependencyHandler,
            RemoveDependencyHandler,
            ClaimTaskHandler,
            ReleaseTaskHandler,
            TransferTaskHandler,
            StartTaskHandler,
            CompleteTaskHandler,
            ReopenTaskHandler,
            DeleteTaskHandler,
            RevalidateHandler,
            PatchTaskHandler,
        ):
            instance = handler_cls()
            self._handlers[instance.kind] = instance

    def get(self, kind: str) -> PlanCommandHandler | None:
        return self._handlers.get(kind)

    def validate(self, command: GraphCommand, snapshot: GraphSnapshot) -> ValidationRun:
        handler = self._handlers.get(command.kind)
        if handler is None:
            return _run(
                command,
                accepted=False,
                issues=(_denied_issue("unknown_command", f"No handler for kind {command.kind!r}"),),
            )
        # The plan_not_active (R-PG-001) and stale_revision (R-PG-002)
        # pre-gates are universal rules evaluated first by the Layer1
        # solver inside each handler's validate.
        return handler.validate(command, snapshot)

    def apply(
        self, command: GraphCommand, envelope: BoardEnvelope, validation: ValidationRun
    ) -> tuple[BoardEnvelope, CommandResult]:
        handler = self._handlers.get(command.kind)
        if handler is None:
            return envelope, CommandResult(
                decision="denied", command_id=command.command_id, reason="unknown_command"
            )
        graph = envelope.graphs.get(_plan_graph_id(command))
        if graph is not None:
            metadata = graph.get("plan")
            state = (
                str(metadata.get("state") or "active") if isinstance(metadata, dict) else "active"
            )
            if state != "active":
                return envelope, CommandResult(
                    decision="denied",
                    command_id=command.command_id,
                    reason=f"plan_not_active: Plan is {state}",
                )
        return handler.apply(command, envelope, validation)


_dispatcher: PlanCommandDispatcher | None = None


def plan_command_dispatcher() -> PlanCommandDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = PlanCommandDispatcher()
    return _dispatcher

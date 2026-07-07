"""Governance workflow for F-155 acceptance templates."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .acceptance_template import (
    AcceptanceTemplate,
    AcceptanceTemplateStatus,
    default_lkb_cache_dir,
    get_acceptance_template,
    register_acceptance_template,
)

logger = logging.getLogger(__name__)

TemplateAction = Literal["approve", "reject", "deprecate"]
_ProposalStatus = AcceptanceTemplateStatus

_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "approve"): "approved",
    ("draft", "reject"): "rejected",
    ("approved", "deprecate"): "deprecated",
}

_FORBIDDEN: dict[tuple[str, ...], str] = {
    ("approved", "reject"): "An approved acceptance template cannot be rejected. Use deprecate.",
    ("approved", "draft"): "An approved acceptance template cannot be downgraded to draft.",
    ("rejected",): "A rejected acceptance template is a terminal state.",
    ("deprecated",): "A deprecated acceptance template is a terminal state.",
    ("draft", "deprecate"): "A draft acceptance template should be rejected, not deprecated.",
}


@dataclass(frozen=True)
class AcceptanceTemplateProposal:
    proposal_id: str
    template: AcceptanceTemplate
    status: _ProposalStatus = "draft"
    reviewer: str = ""
    reason: str = ""
    replacement_id: str = ""
    created_at: str = ""
    updated_at: str = ""


_proposals: dict[str, AcceptanceTemplateProposal] = {}


def propose_acceptance_template_from_plan(
    plan: object,
    *,
    template_id: str,
    description: str,
) -> AcceptanceTemplate:
    """Build a draft template from a decomposition plan."""
    tasks = tuple(getattr(plan, "tasks", ()) or ())
    assertion_template = ""
    proof_template = ""
    roles: list[str] = []
    for task in tasks:
        meta = getattr(task, "lkb_metadata", {}) or {}
        assertions = meta.get("assertions") or ()
        for assertion in assertions:
            if isinstance(assertion, str) and assertion:
                assertion_template = assertion
                break
        proof = meta.get("acceptance_proof")
        if isinstance(proof, str) and proof:
            proof_template = proof
        if assertion_template:
            break
    if not assertion_template:
        assertion_template = "AcceptanceSatisfied({task_id})"
    return AcceptanceTemplate(
        template_id=template_id,
        description=description,
        assertion_template=assertion_template,
        proof_template=proof_template,
        strict_acceptance=True,
        applies_to_roles=tuple(roles),
        version="1.0.0",
        status="draft",
    )


def submit_acceptance_template(template: AcceptanceTemplate) -> str:
    if template.status != "draft":
        raise ValueError(f"Only draft acceptance templates can be submitted; got {template.status!r}")
    if get_acceptance_template(template.template_id) is not None:
        raise ValueError(f"template_id {template.template_id!r} already exists in the registry")
    proposal_id = _new_proposal_id()
    proposal = AcceptanceTemplateProposal(
        proposal_id=proposal_id,
        template=template,
        status="draft",
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = proposal
    _persist_proposal(proposal)
    return proposal_id


def approve_acceptance_template(proposal_id: str, reviewer: str = "") -> None:
    proposal = _get_proposal(proposal_id)
    _transition(proposal.status, "approve")
    template = _replace_template_status(proposal.template, "approved")
    register_acceptance_template(template)
    updated = AcceptanceTemplateProposal(
        proposal_id=proposal.proposal_id,
        template=template,
        status="approved",
        reviewer=reviewer,
        created_at=proposal.created_at,
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = updated
    _persist_proposal(updated)


def reject_acceptance_template(
    proposal_id: str,
    *,
    reviewer: str = "",
    reason: str = "",
) -> None:
    if not reason:
        raise ValueError("reject_acceptance_template requires a non-empty reason")
    proposal = _get_proposal(proposal_id)
    _transition(proposal.status, "reject")
    template = _replace_template_status(proposal.template, "rejected")
    updated = AcceptanceTemplateProposal(
        proposal_id=proposal.proposal_id,
        template=template,
        status="rejected",
        reviewer=reviewer,
        reason=reason,
        created_at=proposal.created_at,
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = updated
    _persist_proposal(updated)


def deprecate_acceptance_template(
    template_id: str,
    replacement_id: str | None = None,
    reviewer: str = "",
) -> None:
    template = get_acceptance_template(template_id)
    if template is None:
        raise ValueError(f"template_id {template_id!r} not found in the registry")
    _transition(template.status, "deprecate")
    updated_template = _replace_template_status(template, "deprecated")
    register_acceptance_template(updated_template, force=True)
    proposal = _find_proposal_for_template(template_id)
    if proposal is not None:
        updated = AcceptanceTemplateProposal(
            proposal_id=proposal.proposal_id,
            template=updated_template,
            status="deprecated",
            reviewer=reviewer,
            reason=f"Replaced by {replacement_id}" if replacement_id else "Deprecated",
            replacement_id=replacement_id or "",
            created_at=proposal.created_at,
            updated_at=_utc_now(),
        )
        _proposals[proposal.proposal_id] = updated
        _persist_proposal(updated)


def list_acceptance_template_proposals(
    *,
    status: str | None = None,
    template_id: str | None = None,
) -> tuple[AcceptanceTemplateProposal, ...]:
    out = list(_proposals.values())
    if status is not None:
        out = [proposal for proposal in out if proposal.status == status]
    if template_id is not None:
        out = [proposal for proposal in out if proposal.template.template_id == template_id]
    out.sort(key=lambda proposal: proposal.created_at, reverse=True)
    return tuple(out)


def get_acceptance_template_proposal(
    proposal_id: str,
) -> AcceptanceTemplateProposal | None:
    return _proposals.get(proposal_id)


def default_template_proposal_dir() -> Path:
    return default_lkb_cache_dir() / "template_proposals"


def load_acceptance_template_proposals(proposal_dir: Path | None = None) -> None:
    root = proposal_dir or default_template_proposal_dir()
    if not root.is_dir():
        return
    from .acceptance_template import load_acceptance_template_data

    for fpath in sorted(root.glob("TP-*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            template = load_acceptance_template_data(data["template"], source=str(fpath))[0]
            proposal = AcceptanceTemplateProposal(
                proposal_id=data.get("proposalId", fpath.stem),
                template=template,
                status=data.get("status", template.status),
                reviewer=data.get("reviewer", ""),
                reason=data.get("reason", ""),
                replacement_id=data.get("replacementId", ""),
                created_at=data.get("createdAt", ""),
                updated_at=data.get("updatedAt", ""),
            )
            _proposals[proposal.proposal_id] = proposal
        except Exception as exc:
            logger.debug("Skipping invalid acceptance template proposal %s: %s", fpath, exc)


def reset_acceptance_template_proposals() -> None:
    _proposals.clear()


def _transition(status: str, action: str) -> None:
    if (status, action) in _TRANSITIONS:
        return
    for pattern, message in _FORBIDDEN.items():
        if len(pattern) == 2 and (status, action) == pattern:
            raise ValueError(message)
        if len(pattern) == 1 and status == pattern[0]:
            raise ValueError(message)
    raise ValueError(f"Illegal transition: {status!r} action {action!r}")


def _replace_template_status(
    template: AcceptanceTemplate,
    status: AcceptanceTemplateStatus,
) -> AcceptanceTemplate:
    return AcceptanceTemplate(
        template_id=template.template_id,
        description=template.description,
        assertion_template=template.assertion_template,
        proof_template=template.proof_template,
        strict_acceptance=template.strict_acceptance,
        applies_to_roles=template.applies_to_roles,
        version=template.version,
        status=status,
    )


def _get_proposal(proposal_id: str) -> AcceptanceTemplateProposal:
    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal {proposal_id!r} not found")
    return proposal


def _find_proposal_for_template(template_id: str) -> AcceptanceTemplateProposal | None:
    for proposal in _proposals.values():
        if proposal.template.template_id == template_id:
            return proposal
    return None


def _new_proposal_id() -> str:
    return f"TP-{uuid.uuid4().hex[:8].upper()}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist_proposal(proposal: AcceptanceTemplateProposal) -> None:
    root = default_template_proposal_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{proposal.proposal_id}.json"
    payload = {
        "proposalId": proposal.proposal_id,
        "template": proposal.template.to_dict(),
        "status": proposal.status,
        "reviewer": proposal.reviewer,
        "reason": proposal.reason,
        "replacementId": proposal.replacement_id,
        "createdAt": proposal.created_at,
        "updatedAt": proposal.updated_at,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


__all__ = [
    "AcceptanceTemplateProposal",
    "approve_acceptance_template",
    "default_template_proposal_dir",
    "deprecate_acceptance_template",
    "get_acceptance_template_proposal",
    "list_acceptance_template_proposals",
    "load_acceptance_template_proposals",
    "propose_acceptance_template_from_plan",
    "reject_acceptance_template",
    "reset_acceptance_template_proposals",
    "submit_acceptance_template",
]

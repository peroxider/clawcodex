"""Method governance workflow for F-153 — state machine + proposal lifecycle.

Phase 2 of the Method Library Growth & Governance feature.

State machine
-------------
``draft → approved``   (approve)
``draft → rejected``   (reject)
``approved → deprecated`` (deprecate)
``experimental → approved`` (upgrade — no transition API needed yet)
``experimental → deprecated`` (direct deprecate)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .method_library import (
    EngineeringMethod,
    MethodStatus,
    default_lkb_cache_dir,
    get_all_methods,
    get_method,
    register_method,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MethodAction = Literal["approve", "reject", "deprecate"]

# Allowed transitions: (current_status, action) -> target_status
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "approve"): "approved",
    ("draft", "reject"): "rejected",
    ("approved", "deprecate"): "deprecated",
    ("experimental", "deprecate"): "deprecated",
}

# Forbidden transitions that deserve an explicit error message
_FORBIDDEN: dict[tuple[str, str], str] = {
    ("approved", "reject"): ("An approved method cannot be rejected. Use 'deprecate' instead."),
    ("approved", "draft"): (
        "An approved method cannot be downgraded to draft. "
        "Deprecate it first, then create a new version."
    ),
    ("rejected",): ("A rejected method is a terminal state. Create a new method_id to restart."),
    ("deprecated",): (
        "A deprecated method is a terminal state. Create a new method_id to restart."
    ),
    ("draft", "deprecate"): ("A draft method should be 'reject'ed, not deprecated."),
}

# ---------------------------------------------------------------------------
# Proposal record
# ---------------------------------------------------------------------------

_MethodStatus = MethodStatus | Literal["rejected"]

@dataclass(frozen=True)
class MethodProposal:
    """A proposal to add a new method to the library."""

    proposal_id: str
    method: EngineeringMethod
    status: _MethodStatus = "draft"
    reviewer: str = ""
    reason: str = ""
    created_at: str = ""
    updated_at: str = ""

#: On-disk directory for proposals. Kept as a public-ish implementation
#: detail for older tests; path resolution uses ``default_proposal_dir()`` so
#: HOME overrides are honored after import too.
_DEFAULT_PROPOSAL_DIR = default_lkb_cache_dir() / "proposals"

# ---------------------------------------------------------------------------
# In-memory proposal store (module-level)
# ---------------------------------------------------------------------------

_proposals: dict[str, MethodProposal] = {}

def _new_proposal_id() -> str:
    return f"P-{uuid.uuid4().hex[:8].upper()}"

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def submit_method(method: EngineeringMethod) -> str:
    """Submit a draft method as a proposal.

    Parameters
    ----------
    method:
        The method to propose.  Must have ``status == "draft"``.

    Returns
    -------
    str
        The proposal ID.

    Raises
    ------
    ValueError
        If the method is not in ``draft`` status or if the method_id
        already exists in the registry.
    """
    if method.status != "draft":
        raise ValueError(f"Only draft methods can be submitted; got {method.status!r}")

    existing = get_method(method.method_id)
    if existing is not None:
        raise ValueError(f"method_id {method.method_id!r} already exists in the registry")

    proposal_id = _new_proposal_id()
    proposal = MethodProposal(
        proposal_id=proposal_id,
        method=method,
        status="draft",
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = proposal
    _persist_proposal(proposal)
    return proposal_id

def approve_method(proposal_id: str, reviewer: str = "") -> None:
    """Approve a draft proposal and register its method.

    Parameters
    ----------
    proposal_id:
        The proposal to approve.
    reviewer:
        Optional reviewer identifier.

    Raises
    ------
    ValueError
        If the proposal does not exist, is not in ``draft`` status,
        or the transition is illegal.
    """
    proposal = _get_proposal(proposal_id)
    _transition(proposal, "approve")

    # Register in the live library
    register_method(proposal.method)

    updated = MethodProposal(
        proposal_id=proposal.proposal_id,
        method=proposal.method,
        status="approved",
        reviewer=reviewer,
        reason="",
        created_at=proposal.created_at,
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = updated
    _persist_proposal(updated)

def reject_method(proposal_id: str, reviewer: str = "", reason: str = "") -> None:
    """Reject a draft proposal.

    Parameters
    ----------
    proposal_id:
        The proposal to reject.
    reviewer:
        Optional reviewer identifier.
    reason:
        Mandatory reason for rejection.

    Raises
    ------
    ValueError
        If the proposal does not exist, is not in ``draft`` status,
        or the transition is illegal.
    """
    if not reason:
        raise ValueError("reject_method requires a non-empty reason")

    proposal = _get_proposal(proposal_id)
    _transition(proposal, "reject")

    updated = MethodProposal(
        proposal_id=proposal.proposal_id,
        method=proposal.method,
        status="rejected",
        reviewer=reviewer,
        reason=reason,
        created_at=proposal.created_at,
        updated_at=_utc_now(),
    )
    _proposals[proposal_id] = updated
    _persist_proposal(updated)

def deprecate_method(
    method_id: str,
    replacement_id: str | None = None,
    reviewer: str = "",
) -> None:
    """Deprecate an approved method.

    Parameters
    ----------
    method_id:
        The method to deprecate.
    replacement_id:
        Optional method_id that replaces this one.
    reviewer:
        Optional reviewer identifier.

    Raises
    ------
    ValueError
        If the method does not exist, is not in a deprecable state,
        or the transition is illegal.
    """
    from .method_library import (
        _METHOD_REGISTRY,
    )

    method = get_method(method_id)
    if method is None:
        raise ValueError(f"method_id {method_id!r} not found in the registry")

    proposal = _find_proposal_for_method(method_id)
    if proposal:
        _transition(proposal, "deprecate")

    # Replace the method inline in the registry
    new_method = EngineeringMethod(
        method_id=method.method_id,
        pattern=method.pattern,
        description=method.description,
        subtask_templates=method.subtask_templates,
        preconditions=method.preconditions,
        assumptions=method.assumptions,
        acceptance_template=method.acceptance_template,
        version=method.version,
        status="deprecated",
        tags=method.tags,
    )

    # Find and replace in the mutable registry
    for i, m in enumerate(_METHOD_REGISTRY):
        if m.method_id == method_id:
            _METHOD_REGISTRY[i] = new_method
            break

    if proposal:
        updated = MethodProposal(
            proposal_id=proposal.proposal_id,
            method=new_method,
            status="deprecated",
            reviewer=reviewer,
            reason=f"Replaced by {replacement_id}" if replacement_id else "Deprecated",
            created_at=proposal.created_at,
            updated_at=_utc_now(),
        )
        _proposals[proposal.proposal_id] = updated
        _persist_proposal(updated)

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def list_proposals(
    *, status: str | None = None, method_id: str | None = None
) -> tuple[MethodProposal, ...]:
    """Return all proposals, optionally filtered."""
    out: list[MethodProposal] = list(_proposals.values())
    if status is not None:
        out = [p for p in out if p.status == status]
    if method_id is not None:
        out = [p for p in out if p.method.method_id == method_id]
    out.sort(key=lambda p: p.created_at, reverse=True)
    return tuple(out)

def get_proposal(proposal_id: str) -> MethodProposal | None:
    """Look up a proposal by ID."""
    return _proposals.get(proposal_id)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_proposal(proposal_id: str) -> MethodProposal:
    proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal {proposal_id!r} not found")
    return proposal

def _transition(proposal: MethodProposal, action: str) -> None:
    """Apply the transition or raise a clear error."""
    key = (proposal.status, action)

    if key in _TRANSITIONS:
        return  # allowed

    # Check forbidden patterns
    for pattern, msg in _FORBIDDEN.items():
        if len(pattern) == 2 and (proposal.status, action) == pattern:
            raise ValueError(msg)
        if len(pattern) == 1 and proposal.status == pattern[0]:
            raise ValueError(msg)

    raise ValueError(
        f"Illegal transition: {proposal.status!r} → action {action!r}. "
        f"Allowed transitions: {_format_allowed(proposal.status)}"
    )

def _format_allowed(status: str) -> str:
    """Return a human-readable list of allowed actions for *status*."""
    allowed: list[str] = []
    for s, a in _TRANSITIONS:
        if s == status:
            allowed.append(a)
    return ", ".join(allowed) if allowed else "(none)"

def _find_proposal_for_method(method_id: str) -> MethodProposal | None:
    for proposal in _proposals.values():
        if proposal.method.method_id == method_id:
            return proposal
    return None

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def default_proposal_dir() -> Path:
    """Return the default user-level proposal directory."""
    return default_lkb_cache_dir() / "proposals"

def _proposal_path(
    proposal_dir: Path | None = None,
    *,
    create: bool = True,
) -> Path:
    dir_path = proposal_dir or default_proposal_dir()
    if create:
        dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def _persist_proposal(proposal: MethodProposal) -> None:
    """Write a single proposal JSON file."""
    root = _proposal_path()
    path = root / f"{proposal.proposal_id}.json"
    data = {
        "proposalId": proposal.proposal_id,
        "method": proposal.method.to_dict(),
        "status": proposal.status,
        "reviewer": proposal.reviewer,
        "reason": proposal.reason,
        "createdAt": proposal.created_at,
        "updatedAt": proposal.updated_at,
    }
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")

def load_proposals(proposal_dir: Path | None = None) -> None:
    """Load all proposal JSON files from *proposal_dir* into memory."""
    root = _proposal_path(proposal_dir, create=False)
    if not root.is_dir():
        return
    for fpath in sorted(root.glob("P-*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            raw_method = data.get("method", {})
            from .method_library import (
                _deserialize_method,
            )

            method = _deserialize_method(raw_method)
            proposal = MethodProposal(
                proposal_id=data.get("proposalId", fpath.stem),
                method=method,
                status=data.get("status", "draft"),
                reviewer=data.get("reviewer", ""),
                reason=data.get("reason", ""),
                created_at=data.get("createdAt", ""),
                updated_at=data.get("updatedAt", ""),
            )
            _proposals[proposal.proposal_id] = proposal
        except Exception as exc:
            logger.debug("Skipping invalid LKB method proposal file %s: %s", fpath, exc)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def reset_proposals() -> None:
    """Clear the in-memory proposal store (test helper)."""
    _proposals.clear()

"""Deterministic maturity rules for crystal revisions.

The ledger remains the source of truth. Maturity values are derived from the parent chain
rebuilt from the current head, so rolling the head back to an earlier version also rolls back
its counters in sync. This module makes no model calls and stores no hidden state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from clawcodex_ext.latent_memory.server.lib.solidification.models import Revision


_EVIDENCE_OPS = frozenset({"create", "absorb"})
_TERMINAL_STATUSES = frozenset({"superseded", "retracted", "expired"})


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value: str | None, *, date_is_end_of_day: bool = False) -> datetime | None:
    """Parse an ISO-8601 value as UTC; invalid user data must not be fatal.

    ``date_is_end_of_day`` matters for closed boundaries. A date-only ``valid_to`` (e.g.
    ``2026-07-31``) means "valid for that entire day", but bare ``fromisoformat`` yields
    midnight, causing the crystal to expire before its last day even begins. Open boundaries
    keep the midnight semantics.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    date_only = bool(_DATE_ONLY.match(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if date_only and date_is_end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.astimezone(timezone.utc)


def _contradiction_delta(audit: dict[str, Any]) -> int:
    """Read the mechanical contradiction event convention used in phase four.

    The writer may place ``audit.maturity.contradiction_delta`` on a revision. A positive value
    records one contradiction, a negative value records its resolution. ``audit.contradiction=true``
    is accepted as a convenient shorthand for a single event.
    """
    maturity = audit.get("maturity") if isinstance(audit, dict) else None
    maturity = maturity if isinstance(maturity, dict) else {}
    value = maturity.get("contradiction_delta")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 1 if audit.get("contradiction") is True else 0


def _evidence_run_ids(revision: Revision) -> set[str]:
    values: set[str] = set()
    scope_run = str(revision.scope.get("run_id") or "").strip()
    if scope_run:
        values.add(scope_run)
    maturity = revision.audit.get("maturity") if isinstance(revision.audit, dict) else None
    maturity = maturity if isinstance(maturity, dict) else {}
    audit_runs = maturity.get("evidence_run_ids")
    if isinstance(audit_runs, (list, tuple)):
        values.update(str(value).strip() for value in audit_runs if str(value).strip())
    return values


@dataclass(frozen=True)
class MaturitySnapshot:
    crystal_id: str
    head_rev_id: int
    status: str
    confidence: float | None
    reinforcement_count: int
    distinct_run_count: int
    run_ids: tuple[str, ...]
    contradiction_count: int
    first_seen_at: str
    age_days: float
    valid_to: str | None
    valid_to_parse_error: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "crystal_id": self.crystal_id,
            "head_rev_id": self.head_rev_id,
            "status": self.status,
            "confidence": self.confidence,
            "reinforcement_count": self.reinforcement_count,
            "distinct_run_count": self.distinct_run_count,
            "run_ids": list(self.run_ids),
            "contradiction_count": self.contradiction_count,
            "first_seen_at": self.first_seen_at,
            "age_days": self.age_days,
            "valid_to": self.valid_to,
            "valid_to_parse_error": self.valid_to_parse_error,
        }


def derive_maturity(chain: Iterable[Revision], *, now: datetime | None = None) -> MaturitySnapshot:
    """Derive counters from the ordered parent chain from genesis to head."""
    revisions = list(chain)
    if not revisions:
        raise ValueError("maturity requires a non-empty revision chain")
    current = revisions[-1]
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    clock = clock.astimezone(timezone.utc)

    evidence = [revision for revision in revisions if revision.op in _EVIDENCE_OPS]
    run_ids = tuple(sorted(set().union(*(_evidence_run_ids(revision) for revision in evidence))))
    contradictions = max(0, sum(_contradiction_delta(revision.audit) for revision in revisions))
    first_seen = parse_datetime(revisions[0].recorded_at) or clock
    age_days = max(0.0, (clock - first_seen).total_seconds() / 86400.0)
    valid_to = parse_datetime(current.valid_to, date_is_end_of_day=True)
    return MaturitySnapshot(
        crystal_id=current.crystal_id,
        head_rev_id=current.rev_id,
        status=current.status,
        confidence=current.confidence,
        reinforcement_count=len(evidence),
        distinct_run_count=len(run_ids),
        run_ids=run_ids,
        contradiction_count=contradictions,
        first_seen_at=revisions[0].recorded_at,
        age_days=age_days,
        valid_to=current.valid_to,
        valid_to_parse_error=bool(current.valid_to and valid_to is None),
    )


def next_status(
    snapshot: MaturitySnapshot,
    *,
    now: datetime | None = None,
    active_min_confidence: float,
    active_min_reinforcement: int,
    canonical_min_runs: int,
    canonical_min_age_days: float,
) -> tuple[str | None, str | None]:
    """Return the next legal status and a machine-readable reason."""
    if snapshot.status in _TERMINAL_STATUSES:
        return None, None
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    expires = parse_datetime(snapshot.valid_to, date_is_end_of_day=True)
    if expires is not None and expires < clock.astimezone(timezone.utc):
        return "expired", "valid_to_elapsed"
    if snapshot.status == "candidate":
        confidence = snapshot.confidence if snapshot.confidence is not None else 0.0
        if (
            confidence >= active_min_confidence
            and snapshot.reinforcement_count >= active_min_reinforcement
            and snapshot.contradiction_count == 0
        ):
            return "active", "confidence_and_reinforcement"
    if snapshot.status == "active" and (
        snapshot.distinct_run_count >= canonical_min_runs
        and snapshot.age_days >= canonical_min_age_days
        and snapshot.contradiction_count == 0
    ):
        return "canonical", "runs_age_and_no_contradiction"
    return None, None

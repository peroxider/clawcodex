"""Truth Maintenance System (TMS) for Logical Kanban.

The TMS tracks assumptions, the assertions that depend on them, and the
derived assertions/facts that transitively rely on those assertions.  When an
assumption is invalidated or clarified, the system propagates ``stale`` status
through the dependency graph and can clear stale status again once all
supporting assumptions are active.

This is the F-135 MVP implementation: propagation is kept in-memory for a
single session.  Assumption IDs are mirrored in task metadata by consumers of
this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Callable

from .fuzzy_types import Assumption, Clarification


_AssumptionStatus = str  # active | invalid | superseded
_AssertionStatus = str  # active | stale

OnInvalidateCallback = Callable[[str, str, str], None]
"""Callback invoked when an assumption is invalidated: (assumption_id, assertion_id, reason)."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}{uuid.uuid4().hex[:12]}"


@dataclass
class AssumptionRecord:
    """Mutable, session-scoped record of one assumption."""

    assumption_id: str
    assertion_id: str
    field: str
    value: Any
    confidence: float
    source: str
    status: _AssumptionStatus = "active"
    dependent_assertions: set[str] = dc_field(default_factory=set)
    created_at: str = dc_field(default_factory=_utc_now)
    invalidated_at: str | None = None
    invalidated_reason: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "assumptionId": self.assumption_id,
            "assertionId": self.assertion_id,
            "field": self.field,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "status": self.status,
            "createdAt": self.created_at,
        }
        if self.invalidated_at is not None:
            out["invalidatedAt"] = self.invalidated_at
        if self.invalidated_reason is not None:
            out["invalidatedReason"] = self.invalidated_reason
        if self.superseded_by is not None:
            out["supersededBy"] = self.superseded_by
        return out


@dataclass
class AssertionRecord:
    """Mutable, session-scoped record of one assertion or derived fact."""

    assertion_id: str
    assumption_ids: set[str] = dc_field(default_factory=set)
    derived_from: set[str] = dc_field(default_factory=set)
    derived_to: set[str] = dc_field(default_factory=set)
    task_ids: set[str] = dc_field(default_factory=set)
    status: _AssertionStatus = "active"
    stale_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertionId": self.assertion_id,
            "assumptionIds": sorted(self.assumption_ids),
            "derivedFrom": sorted(self.derived_from),
            "taskIds": sorted(self.task_ids),
            "status": self.status,
            "staleReason": self.stale_reason,
        }


class TruthMaintenanceSystem:
    """In-session truth maintenance for LKB assumptions and derived facts."""

    def __init__(
        self,
        on_invalidate: OnInvalidateCallback | None = None,
    ) -> None:
        self._assumptions: dict[str, AssumptionRecord] = {}
        self._assertions: dict[str, AssertionRecord] = {}
        self._on_invalidate = on_invalidate

    @property
    def on_invalidate(self) -> OnInvalidateCallback | None:
        return self._on_invalidate

    @on_invalidate.setter
    def on_invalidate(self, callback: OnInvalidateCallback | None) -> None:
        self._on_invalidate = callback

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_assertion(
        self,
        assertion_id: str,
        *,
        assumptions: tuple[Assumption, ...] = (),
        derived_from: tuple[str, ...] = (),
        task_ids: tuple[str, ...] = (),
    ) -> AssertionRecord:
        """Register an assertion and the assumptions it depends on.

        If the assertion already exists, its dependency sets are extended.
        New assumptions are imported; existing assumptions are linked.
        """
        if assertion_id in self._assertions:
            record = self._assertions[assertion_id]
        else:
            record = AssertionRecord(assertion_id=assertion_id)
            self._assertions[assertion_id] = record

        for assumption in assumptions:
            self._import_assumption(assumption, record)

        for parent_id in derived_from:
            record.derived_from.add(parent_id)
            parent = self._assertions.setdefault(parent_id, AssertionRecord(assertion_id=parent_id))
            parent.derived_to.add(assertion_id)

        record.task_ids.update(task_ids)
        self._reevaluate_assertion_status(assertion_id)
        return record

    def register_derived_fact(
        self,
        assertion_id: str,
        *,
        derived_from: tuple[str, ...] = (),
        task_ids: tuple[str, ...] = (),
    ) -> AssertionRecord:
        """Register a derived fact that depends on other assertions.

        Convenience wrapper around :meth:`register_assertion` for facts that
        carry no direct assumptions but are derived from prior assertions.
        """
        return self.register_assertion(
            assertion_id,
            assumptions=(),
            derived_from=derived_from,
            task_ids=task_ids,
        )

    # ------------------------------------------------------------------
    # Invalidation / propagation
    # ------------------------------------------------------------------

    def invalidate_assumption(self, assumption_id: str, reason: str = "") -> AssumptionRecord:
        """Mark an assumption invalid and propagate stale status."""
        record = self._assumptions.get(assumption_id)
        if record is None:
            raise KeyError(f"Assumption {assumption_id} not found")
        if record.status == "invalid":
            return record

        record.status = "invalid"
        record.invalidated_at = _utc_now()
        record.invalidated_reason = reason or "assumption invalidated"

        if self._on_invalidate is not None:
            self._on_invalidate(
                assumption_id, record.assertion_id, reason or "assumption invalidated"
            )

        for assertion_id in list(record.dependent_assertions):
            self._mark_assertion_stale(
                assertion_id,
                reason=f"dependency assumption {assumption_id} invalidated",
            )
        return record

    def clarify_assumption(
        self,
        assumption_id: str,
        clarification: Clarification,
    ) -> tuple[AssumptionRecord, AssumptionRecord | None]:
        """Apply a user clarification to an assumption.

        Returns ``(updated_or_new_assumption, old_assumption)``.
        - ``confirm`` bumps confidence to 1.0 and clears invalidation.
        - ``override`` supersedes the old assumption and creates a new active one.
        - Other actions update the value and bump confidence to 1.0, keeping the
          same assumption identity.
        """
        old = self._assumptions.get(assumption_id)
        if old is None:
            raise KeyError(f"Assumption {assumption_id} not found")

        if clarification.action == "override":
            old.status = "superseded"
            old.invalidated_at = _utc_now()
            old.invalidated_reason = f"superseded by user clarification"
            old.superseded_by = _new_id("H-")

            new_record = AssumptionRecord(
                assumption_id=old.superseded_by,
                assertion_id=old.assertion_id,
                field=old.field,
                value=clarification.new_value,
                confidence=1.0,
                source="user_clarified",
                status="active",
            )
            self._assumptions[new_record.assumption_id] = new_record

            # Move dependent assertions to the new assumption.
            for dependent_id in list(old.dependent_assertions):
                old.dependent_assertions.discard(dependent_id)
                new_record.dependent_assertions.add(dependent_id)
                assertion = self._assertions.get(dependent_id)
                if assertion is not None:
                    assertion.assumption_ids.discard(assumption_id)
                    assertion.assumption_ids.add(new_record.assumption_id)

            self._reevaluate_subgraph({new_record.assumption_id})
            return new_record, old

        # confirm / provide_info / rephrase keep the same identity.
        old.status = "active"
        old.value = clarification.new_value or old.value
        old.confidence = 1.0
        old.source = "user_clarified"
        old.invalidated_at = None
        old.invalidated_reason = None
        old.superseded_by = None
        self._reevaluate_subgraph({assumption_id})
        return old, None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_assumption(self, assumption_id: str) -> AssumptionRecord | None:
        return self._assumptions.get(assumption_id)

    def get_assertion(self, assertion_id: str) -> AssertionRecord | None:
        return self._assertions.get(assertion_id)

    def is_assertion_stale(self, assertion_id: str) -> bool:
        record = self._assertions.get(assertion_id)
        return record is not None and record.status == "stale"

    def is_task_affected(self, task_id: str) -> bool:
        for record in self._assertions.values():
            if record.status == "stale" and task_id in record.task_ids:
                return True
        return False

    def get_stale_task_ids(self) -> frozenset[str]:
        return frozenset(
            task_id
            for record in self._assertions.values()
            if record.status == "stale"
            for task_id in record.task_ids
        )

    def get_stale_assertion_ids(self) -> frozenset[str]:
        return frozenset(
            assertion_id
            for assertion_id, record in self._assertions.items()
            if record.status == "stale"
        )

    @property
    def stale_assumption_count(self) -> int:
        """Number of assumptions that are invalid or superseded."""
        return sum(
            1 for record in self._assumptions.values() if record.status in ("invalid", "superseded")
        )

    def assumptions_for_task(self, task_id: str) -> tuple[AssumptionRecord, ...]:
        ids: set[str] = set()
        for assertion in self._assertions.values():
            if task_id in assertion.task_ids:
                ids.update(assertion.assumption_ids)
        return tuple(self._assumptions[i] for i in sorted(ids) if i in self._assumptions)

    def get_assertions_for_task(self, task_id: str) -> tuple[AssertionRecord, ...]:
        return tuple(
            assertion for assertion in self._assertions.values() if task_id in assertion.task_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [a.to_dict() for a in self._assumptions.values()],
            "assertions": [a.to_dict() for a in self._assertions.values()],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _import_assumption(
        self,
        assumption: Assumption,
        assertion: AssertionRecord,
    ) -> AssumptionRecord:
        if assumption.assumption_id in self._assumptions:
            record = self._assumptions[assumption.assumption_id]
        else:
            record = AssumptionRecord(
                assumption_id=assumption.assumption_id,
                assertion_id=assumption.assertion_id,
                field=assumption.field,
                value=assumption.assumed_value,
                confidence=assumption.confidence,
                source=assumption.source,
            )
            self._assumptions[record.assumption_id] = record
        record.dependent_assertions.add(assertion.assertion_id)
        assertion.assumption_ids.add(record.assumption_id)
        return record

    def _mark_assertion_stale(self, assertion_id: str, reason: str) -> None:
        record = self._assertions.get(assertion_id)
        if record is None:
            return
        if record.status == "stale":
            return
        record.status = "stale"
        record.stale_reason = reason
        for child_id in record.derived_to:
            self._mark_assertion_stale(
                child_id,
                reason=f"derived from stale assertion {assertion_id}",
            )

    def _reevaluate_assertion_status(self, assertion_id: str) -> None:
        record = self._assertions.get(assertion_id)
        if record is None:
            return
        if record.status != "stale":
            return
        if self._all_support_active(record):
            record.status = "active"
            record.stale_reason = None
            for child_id in record.derived_to:
                self._reevaluate_assertion_status(child_id)

    def _reevaluate_subgraph(self, assumption_ids: set[str]) -> None:
        # Collect all assertions that reference the changed assumptions.
        queue: list[str] = []
        for assumption_id in assumption_ids:
            assumption = self._assumptions.get(assumption_id)
            if assumption is None:
                continue
            queue.extend(assumption.dependent_assertions)

        seen: set[str] = set()
        while queue:
            assertion_id = queue.pop()
            if assertion_id in seen:
                continue
            seen.add(assertion_id)
            record = self._assertions.get(assertion_id)
            if record is None:
                continue
            old_status = record.status
            if record.status == "stale" and self._all_support_active(record):
                record.status = "active"
                record.stale_reason = None
            elif record.status == "active" and not self._all_support_active(record):
                self._mark_assertion_stale(
                    assertion_id,
                    reason="supporting assumption became invalid",
                )
            if record.status != old_status:
                queue.extend(record.derived_to)

    def _all_support_active(self, record: AssertionRecord) -> bool:
        for assumption_id in record.assumption_ids:
            assumption = self._assumptions.get(assumption_id)
            if assumption is None or assumption.status != "active":
                return False
        for parent_id in record.derived_from:
            parent = self._assertions.get(parent_id)
            if parent is None or parent.status != "active":
                return False
        return True


__all__ = [
    "AssumptionRecord",
    "AssertionRecord",
    "TruthMaintenanceSystem",
]

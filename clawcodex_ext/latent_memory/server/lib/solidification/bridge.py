"""Authoritative boundary between semantic crystallization and the ledger.

The ledger is the single source of truth for crystals. A ledger failure therefore fails the
crystallization operation; derived projections may still lag or fail independently after a
successful commit.
"""

from __future__ import annotations

from typing import Any, Protocol


class LedgerBridge(Protocol):
    @property
    def batch_id(self) -> str | None: ...

    def begin_batch(self) -> str: ...

    def end_batch(self) -> None: ...

    def create(
        self,
        merged: dict[str, Any],
        *,
        source_ids: list[str],
        user_id: str,
        audit: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def absorb(
        self,
        merged: dict[str, Any],
        *,
        source_ids: list[str],
        crystal_id: str,
        superseded_crystal_ids: list[str] | None,
        scope: dict[str, str],
        audit: dict[str, Any] | None,
    ) -> dict[str, Any]: ...

    def superseded(
        self, *, crystal_id: str, into_crystal_id: str | None, rationale: str
    ) -> dict[str, Any]: ...

    def current_crystals(self, *, user_id: str) -> list[dict[str, Any]]: ...

    def crystal_cluster_vectors(self, content_hashes: dict[str, str]) -> dict[str, list[float]]: ...

    def state(self) -> dict[str, Any]: ...


class SolidificationBridge:
    """Small, fail-closed interface used by the crystallizer."""

    def __init__(self, store: Any):
        if store is None:
            raise ValueError("authoritative SolidificationStore is required")
        self._store = store
        self._batch_id: str | None = None

    @property
    def store(self) -> Any:
        return self._store

    @property
    def batch_id(self) -> str | None:
        return self._batch_id

    def begin_batch(self) -> str:
        self._batch_id = self._store.new_batch_id()
        return self._batch_id

    def end_batch(self) -> None:
        self._batch_id = None

    def _ensure_batch(self) -> str:
        return self._batch_id or self.begin_batch()

    @staticmethod
    def _record(outcome: Any, operation: str) -> dict[str, Any]:
        if not outcome.ok:
            raise RuntimeError(outcome.error or f"ledger {operation} failed")
        return outcome.audit_record()

    def create(
        self,
        merged: dict[str, Any],
        *,
        source_ids: list[str],
        user_id: str,
        audit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        outcome = self._store.commit_create(
            merged,
            batch_id=self._ensure_batch(),
            source_ids=source_ids,
            user_id=user_id,
            audit=audit,
        )
        return self._record(outcome, "create")

    def absorb(
        self,
        merged: dict[str, Any],
        *,
        source_ids: list[str],
        crystal_id: str,
        superseded_crystal_ids: list[str] | None = None,
        scope: dict[str, str],
        audit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        outcome, superseded = self._store.commit_consolidation(
            merged,
            batch_id=self._ensure_batch(),
            source_ids=source_ids,
            crystal_id=crystal_id,
            superseded_crystal_ids=superseded_crystal_ids or [],
            user_id=scope.get("user_id"),
            agent_id=scope.get("agent_id"),
            run_id=scope.get("run_id"),
            audit=audit,
        )
        record = self._record(outcome, "absorb")
        record["superseded"] = [self._record(item, "supersede") for item in superseded]
        return record

    def superseded(
        self, *, crystal_id: str, into_crystal_id: str | None, rationale: str
    ) -> dict[str, Any]:
        outcome = self._store.commit_superseded(
            batch_id=self._ensure_batch(),
            crystal_id=crystal_id,
            into_crystal_id=into_crystal_id,
            rationale=rationale,
        )
        return self._record(outcome, "supersede")

    def current_crystals(self, *, user_id: str) -> list[dict[str, Any]]:
        return self._store.current_crystals(user_id=user_id)

    def crystal_cluster_vectors(self, content_hashes: dict[str, str]) -> dict[str, list[float]]:
        return self._store.crystal_cluster_vectors(content_hashes)

    def state(self) -> dict[str, Any]:
        return self._store.state()


def build_bridge(store: Any | None) -> LedgerBridge:
    if store is None:
        raise ValueError(
            "SemanticCrystallizer requires the solidification ledger (enable CRYSTALLIZE_ENABLED)"
        )
    return SolidificationBridge(store)

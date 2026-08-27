"""Authoritative crystal ledger and rebuildable derived projections.

Raw memory remains in the injected backend. Crystal create/absorb/supersede operations are
append-only ledger transactions. Qdrant, graph edges, and Markdown may fail or lag without
altering the committed truth.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, NoReturn

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import (
    AppendResult,
    CrystalLedger,
    LedgerError,
)
from clawcodex_ext.latent_memory.server.lib.solidification.maturity import (
    derive_maturity,
    next_status,
)
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    RevisionInput,
    build_scope,
    crystal_metadata_from_revision,
    new_batch_id,
    new_crystal_id,
)

logger = logging.getLogger("memory-server.solidification")


class CommitOutcome:
    """Result of one authoritative ledger commit."""

    __slots__ = ("ok", "crystal_id", "rev_id", "version", "skipped", "error")

    def __init__(
        self,
        *,
        ok: bool,
        crystal_id: str | None = None,
        rev_id: int | None = None,
        version: int | None = None,
        skipped: bool = False,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.crystal_id = crystal_id
        self.rev_id = rev_id
        self.version = version
        self.skipped = skipped
        self.error = error

    def audit_record(self) -> dict[str, Any]:
        """Compact form written to the crystallization audit JSONL."""
        record: dict[str, Any] = {"ok": self.ok}
        if self.crystal_id:
            record["crystal_id"] = self.crystal_id
        if self.rev_id is not None:
            record["rev_id"] = self.rev_id
        if self.version is not None:
            record["version"] = self.version
        if self.skipped:
            record["skipped"] = True
        if self.error:
            record["error"] = self.error
        return record

    def __repr__(self) -> str:
        return f"CommitOutcome({self.audit_record()})"


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _clean_source_ids(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


class SolidificationStore:
    """Solidification facade. The crystallizer only interacts with this class, not the ledger tables."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        ledger: CrystalLedger | None = None,
        *,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
        memory_config: dict[str, Any] | None = None,
        vector_client: Any | None = None,
    ):
        cfg = config or {}
        self._config = cfg
        self._db_path: str = cfg.get("db_path", "local_mem0/solidification.db")
        self._maturity_enabled: bool = bool(cfg.get("maturity_enabled", True))
        self._maturity_sweep_seconds = max(1.0, float(cfg.get("maturity_sweep_seconds", 60.0)))
        self._maturity_stop = threading.Event()
        self._maturity_thread: threading.Thread | None = None
        self._active_min_confidence = float(cfg.get("active_min_confidence", 0.65))
        self._active_min_reinforcement = int(cfg.get("active_min_reinforcement", 2))
        self._active_direct_confidence = float(cfg.get("active_direct_confidence", 0.85))
        self._canonical_min_runs = int(cfg.get("canonical_min_runs", 3))
        self._canonical_min_age_days = float(cfg.get("canonical_min_age_days", 7))
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {
            "commits": 0,
            "created": 0,
            "absorbed": 0,
            "superseded": 0,
            "retracted": 0,
            "provenance_invalidated": 0,
            "skipped": 0,
            "failures": 0,
            "maturity_evaluations": 0,
            "promoted_active": 0,
            "promoted_canonical": 0,
            "expired": 0,
            "rollbacks": 0,
        }
        self._ledger = ledger if ledger is not None else CrystalLedger(self._db_path)
        self._vector_projection: Any | None = None
        self._document_projection: Any | None = None
        self._graph_projection: Any | None = None
        self._validity: Any | None = None
        self._validity_requested = False
        self._validity_init_error: str | None = None
        self._projection_init_errors: dict[str, str] = {}
        if embed_fn is not None:
            try:
                from clawcodex_ext.latent_memory.server.lib.solidification.projection import (
                    VectorProjection,
                )

                self._vector_projection = VectorProjection(
                    self._ledger,
                    embed_fn=embed_fn,
                    collection_name=str(cfg.get("crystal_collection", "crystals")),
                    mode=str(cfg.get("projection_mode", "async")),
                    batch_size=int(cfg.get("projection_batch_size", 100)),
                    embedding_batch_size=int(cfg.get("embedding_batch_size", 32)),
                    memory_config=memory_config,
                    client=vector_client,
                )
                self._vector_projection.start()
            except Exception as exc:
                self._projection_init_errors["vector"] = str(exc)
                # Qdrant is derived state. A projection config failure must never disable the append-only ledger.
                logger.error("固化层: 向量投影初始化失败，保留账本模式: %s", exc, exc_info=True)
        if bool(cfg.get("document_enabled", False)):
            try:
                from clawcodex_ext.latent_memory.server.lib.solidification.document import (
                    DocumentProjection,
                )

                self._document_projection = DocumentProjection(
                    self._ledger,
                    repo_path=str(cfg.get("doc_repo_path", "local_mem0/crystal_docs")),
                    git_enabled=bool(cfg.get("doc_git_enabled", True)),
                    mode=str(cfg.get("projection_mode", "async")),
                    batch_size=int(cfg.get("projection_batch_size", 100)),
                )
                self._document_projection.start()
            except Exception as exc:
                self._projection_init_errors["document"] = str(exc)
                logger.error(
                    "固化层: 文档投影初始化失败，其他投影继续可用: %s",
                    exc,
                    exc_info=True,
                )
        if bool(cfg.get("graph_enabled", False)):
            try:
                from clawcodex_ext.latent_memory.server.lib.solidification.graph import (
                    GraphProjection,
                )

                self._graph_projection = GraphProjection(self._ledger)
                self._graph_projection.start()
                if self._ledger.max_rev_id() > int(
                    self._ledger.projection_state().get("graph", {}).get("through_rev", 0)
                ):
                    self._graph_projection.rebuild()
            except Exception as exc:
                self._projection_init_errors["graph"] = str(exc)
                logger.error(
                    "固化层: 图投影初始化失败，其他投影继续可用: %s",
                    exc,
                    exc_info=True,
                )
        logger.info(
            "固化层: 权威账本就绪 (db=%s, revisions=%d)",
            self._ledger.db_path,
            self._ledger.max_rev_id(),
        )
        if self._maturity_enabled:
            self._maturity_thread = threading.Thread(
                target=self._maturity_worker,
                name="solidification-maturity-sweeper",
                daemon=True,
            )
            self._maturity_thread.start()

    @property
    def ledger(self) -> CrystalLedger:
        return self._ledger

    @property
    def vector_projection_enabled(self) -> bool:
        return self._vector_projection is not None

    @property
    def document_projection_enabled(self) -> bool:
        return self._document_projection is not None

    @property
    def graph_projection_enabled(self) -> bool:
        return self._graph_projection is not None

    @property
    def validity_enabled(self) -> bool:
        return self._validity is not None

    def enable_validity(
        self,
        config: dict[str, Any],
        *,
        backend_accessor: Callable[[], Any],
        llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        if self._validity is not None:
            return
        self._validity_requested = True
        from clawcodex_ext.latent_memory.server.lib.validity.store import ValidityStore

        try:
            self._validity = ValidityStore(
                self._ledger,
                config,
                backend_accessor=backend_accessor,
                llm_fn=llm_fn,
                on_results=self._verification_results,
            )
        except Exception as exc:
            self._validity_init_error = str(exc)
            logger.error(
                "有效性验证初始化失败，Ledger 与 raw 服务继续运行: %s",
                exc,
                exc_info=True,
            )

    def _verification_results(self, results: list[AppendResult]) -> None:
        for result in results:
            self._outcome(result)
        eligible = [
            result.crystal_id
            for result in results
            if result.revision is not None and result.revision.status in ("candidate", "active")
        ]
        if self._maturity_enabled and eligible:
            try:
                self.evaluate_maturity(crystal_ids=eligible)
            except Exception:
                logger.error(
                    "有效性决策后的成熟度重算失败；保留已提交 Ledger revision",
                    exc_info=True,
                )
        if results:
            self._flush_safety_projections()

    @staticmethod
    def new_batch_id() -> str:
        return new_batch_id()

    def _bump(self, key: str, delta: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + delta

    # ── Commit entry points ──────────────────────────────────────────────

    def commit_create(
        self,
        merged: dict[str, Any],
        *,
        batch_id: str,
        source_ids: list[str],
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        audit: dict[str, Any] | None = None,
        rationale: str | None = None,
        status: str | None = None,
        op: str = "create",
        crystal_id: str | None = None,
    ) -> CommitOutcome:
        """Commit a newly crystallized crystal to the ledger. merged is the candidate produced by
        subtask two (already passed the retention judge).

        The initial status is graded by confidence:
          - confidence >= active_direct_confidence (default 0.85) → directly active
          - otherwise → candidate, promoted later after subsequent absorb confirmation
        """
        try:
            entry = self._revision_input(
                crystal_id=crystal_id or new_crystal_id(),
                batch_id=batch_id,
                op=op,
                status=status or self._initial_create_status(merged, op),
                merged=merged,
                source_ids=source_ids,
                scope=build_scope(user_id=user_id, agent_id=agent_id, run_id=run_id),
                audit=audit,
                rationale=rationale,
            )
            result = self._ledger.append_revision(entry)
            self._bump("created")
            outcome = self._outcome(result)
            if self._maturity_enabled and not result.skipped:
                self._evaluate_after_commit(entry.crystal_id, batch_id)
            return outcome
        except Exception as exc:
            return self._failure("commit_create", exc, crystal_id=crystal_id)

    def commit_absorb(
        self,
        merged: dict[str, Any],
        *,
        batch_id: str,
        source_ids: list[str],
        crystal_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        audit: dict[str, Any] | None = None,
        rationale: str | None = None,
        status: str | None = None,
    ) -> CommitOutcome:
        """Append an absorb revision to an existing stable crystal."""
        outcome, _ = self.commit_consolidation(
            merged,
            batch_id=batch_id,
            source_ids=source_ids,
            crystal_id=crystal_id,
            superseded_crystal_ids=[],
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            audit=audit,
            rationale=rationale,
            status=status,
        )
        return outcome

    def commit_consolidation(
        self,
        merged: dict[str, Any],
        *,
        batch_id: str,
        source_ids: list[str],
        crystal_id: str | None,
        superseded_crystal_ids: list[str],
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        audit: dict[str, Any] | None = None,
        rationale: str | None = None,
        status: str | None = None,
    ) -> tuple[CommitOutcome, list[CommitOutcome]]:
        """Atomically absorb data into one head and supersede the merged-away heads."""
        try:
            resolved = crystal_id
            if not resolved:
                raise LedgerError("commit_absorb requires a stable crystal_id")
            current = self._ledger.head(resolved)
            if current is None:
                raise LedgerError(f"crystal {resolved} does not have a current head")
            absorb_entry = self._revision_input(
                crystal_id=resolved,
                batch_id=batch_id,
                op="absorb",
                status=status or current.status,
                merged=merged,
                source_ids=source_ids,
                scope=build_scope(user_id=user_id, agent_id=agent_id, run_id=run_id),
                audit=audit,
                rationale=rationale,
            )
            obsolete_ids = list(
                dict.fromkeys(
                    value for value in superseded_crystal_ids if value and value != resolved
                )
            )
            entries = [absorb_entry]
            for obsolete_id in obsolete_ids:
                head = self._ledger.head(obsolete_id)
                if head is None:
                    raise LedgerError(f"crystal {obsolete_id} does not have a current head")
                entries.append(
                    RevisionInput(
                        crystal_id=obsolete_id,
                        batch_id=batch_id,
                        op="supersede",
                        status="superseded",
                        body=head.body,
                        asset=head.asset,
                        facets=head.facets,
                        knowledge_type=head.knowledge_type,
                        asset_type=head.asset_type,
                        subject=head.subject,
                        confidence=head.confidence,
                        source_ids=list(head.source_ids),
                        valid_from=head.valid_from,
                        valid_to=head.valid_to,
                        actor="crystallizer",
                        rationale=f"absorbed into {resolved}",
                        audit={
                            "consolidation": {
                                "target_crystal_id": resolved,
                                "atomic": True,
                            }
                        },
                        scope=dict(head.scope),
                        lineage=[(obsolete_id, resolved, "absorbed_into")],
                    )
                )
            results = self._ledger.append_revisions(entries)
            self._bump("absorbed")
            self._bump("superseded", len(obsolete_ids))
            outcomes = [self._outcome(result) for result in results]
            if self._maturity_enabled and not results[0].skipped:
                self._evaluate_after_commit(absorb_entry.crystal_id, batch_id)
            return outcomes[0], outcomes[1:]
        except Exception as exc:
            return self._failure("commit_absorb", exc, crystal_id=crystal_id)

    def commit_superseded(
        self,
        *,
        batch_id: str,
        into_crystal_id: str | None = None,
        crystal_id: str | None = None,
        rationale: str | None = None,
        audit: dict[str, Any] | None = None,
    ) -> CommitOutcome:
        """Mark an existing ledger crystal as superseded and append its lineage."""
        try:
            resolved = crystal_id
            if not resolved:
                raise LedgerError("commit_superseded requires a stable crystal_id")
            lineage: list[tuple[str, str, str]] = []
            if into_crystal_id and into_crystal_id != resolved:
                lineage.append((resolved, into_crystal_id, "absorbed_into"))
            result = self._ledger.mark_status(
                resolved,
                status="superseded",
                op="supersede",
                batch_id=batch_id,
                rationale=rationale,
                lineage=lineage,
                audit=audit or {},
            )
            self._bump("superseded")
            return self._outcome(result)
        except Exception as exc:
            return self._failure("commit_superseded", exc, crystal_id=crystal_id)

    def retract_for_delete(self, identifier: str) -> dict[str, Any]:
        """Retract a stable crystal, or invalidate every head referencing a raw source."""
        identifier = str(identifier or "").strip()
        if not identifier:
            raise ValueError("delete identifier cannot be empty")

        crystal_id = identifier if self._ledger.crystal_exists(identifier) else None
        if crystal_id is not None:
            heads = [self._ledger.head(crystal_id) or self._ledger.tip_revision(crystal_id)]
            kind = "crystal"
            rationale = "user requested crystal deletion"
            audit = {"deletion": {"kind": "crystal_retracted", "identifier": identifier}}
        else:
            heads = [
                head
                for head in self._ledger.heads_referencing_source(identifier)
                if head.status in ("candidate", "active", "canonical")
                or (
                    head.status == "retracted"
                    and (head.audit.get("deletion") or {}).get("kind") == "provenance_invalidated"
                    and (head.audit.get("deletion") or {}).get("source_id") == identifier
                )
            ]
            kind = "raw_source"
            rationale = f"source memory deleted: {identifier}"
            audit = {
                "deletion": {
                    "kind": "provenance_invalidated",
                    "source_id": identifier,
                }
            }

        batch_id = new_batch_id()
        affected: list[str] = []
        skipped: list[str] = []
        for head in heads:
            if head is None:
                continue
            if head.status == "retracted":
                skipped.append(head.crystal_id)
                continue
            result = self._ledger.mark_status(
                head.crystal_id,
                status="retracted",
                op="retract",
                batch_id=batch_id,
                actor="user",
                rationale=rationale,
                audit=audit,
            )
            self._outcome(result)
            self._bump("retracted")
            if kind == "raw_source":
                self._bump("provenance_invalidated")
            affected.append(head.crystal_id)

        projection_errors = self._flush_safety_projections()

        return {
            "kind": kind,
            "identifier": identifier,
            "batch_id": batch_id,
            "affected_crystal_ids": affected,
            "skipped_crystal_ids": skipped,
            "projection_errors": projection_errors,
        }

    def retract_scope(self, scope: dict[str, str]) -> dict[str, Any]:
        """Append a user retraction for every current crystal in a deleted scope."""
        clean_scope = {key: str(value) for key, value in scope.items() if value}
        if not clean_scope:
            raise ValueError("delete scope cannot be empty")
        heads = self._ledger.heads_matching_scope(clean_scope)
        batch_id = new_batch_id()
        affected: list[str] = []
        skipped: list[str] = []
        for head in heads:
            if head.status == "retracted":
                skipped.append(head.crystal_id)
                continue
            result = self._ledger.mark_status(
                head.crystal_id,
                status="retracted",
                op="retract",
                batch_id=batch_id,
                actor="user",
                rationale=f"all memories deleted for scope {clean_scope}",
                audit={"deletion": {"kind": "scope_retracted", "scope": clean_scope}},
            )
            self._outcome(result)
            self._bump("retracted")
            affected.append(head.crystal_id)
        projection_errors = self._flush_safety_projections()
        return {
            "kind": "scope",
            "scope": clean_scope,
            "batch_id": batch_id,
            "affected_crystal_ids": affected,
            "skipped_crystal_ids": skipped,
            "projection_errors": projection_errors,
        }

    def _flush_safety_projections(self) -> dict[str, str]:
        """Best-effort catch-up of projections after safety-critical ledger commits.

        Retrieval rejects lagging vector projections, so an outage in derived storage must never
        roll back or block authoritative delete/retract operations.
        """
        errors: dict[str, str] = {}
        for name, projection in (
            ("vector", self._vector_projection),
            ("document", self._document_projection),
        ):
            if projection is None:
                continue
            try:
                projection.flush()
            except Exception as exc:
                errors[name] = str(exc)
                logger.error("%s projection catch-up failed after retraction", name, exc_info=True)
        return errors

    # ── Reads (for the API and phase-two read path) ──────────────────────

    def history(self, crystal_id: str) -> list[dict[str, Any]]:
        return [rev.to_dict() for rev in self._ledger.history(crystal_id)]

    @staticmethod
    def _memory_item(revision: Any) -> dict[str, Any]:
        """Expose one ledger head in a backend-agnostic memory shape."""
        metadata = crystal_metadata_from_revision(revision)
        return {
            "id": revision.crystal_id,
            "memory": revision.body,
            "hash": revision.content_hash,
            "created_at": revision.recorded_at,
            **revision.scope,
            "metadata": metadata,
        }

    def current_crystals(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        statuses: tuple[str, ...] = ("candidate", "active", "canonical"),
    ) -> list[dict[str, Any]]:
        """Read the current crystal heads directly from the source of truth."""
        scope = {
            key: value
            for key, value in (
                ("user_id", user_id),
                ("agent_id", agent_id),
                ("run_id", run_id),
            )
            if value
        }
        revisions = self._ledger.heads(statuses=statuses)
        revisions = [revision for revision in revisions if revision.op != "dispute"]
        if scope:
            revisions = [
                revision
                for revision in revisions
                if all(revision.scope.get(key) == value for key, value in scope.items())
            ]
        return [self._memory_item(revision) for revision in revisions]

    def get_crystal(self, crystal_id: str) -> dict[str, Any] | None:
        revision = self._ledger.head(crystal_id)
        return self._memory_item(revision) if revision is not None else None

    def crystal_cluster_vectors(self, content_hashes: dict[str, str]) -> dict[str, list[float]]:
        """Read body-only cluster vectors from the rebuildable Qdrant projection."""
        if self._vector_projection is None:
            return {}
        return self._vector_projection.cluster_vectors_for(content_hashes)

    def crystals_as_of(
        self,
        *,
        rev_id: int | None = None,
        timestamp: str | None = None,
        user_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        if rev_id is None and timestamp is None:
            revisions = self._ledger.heads(user_id=user_id)
        else:
            revisions = self._ledger.as_of(rev_id=rev_id, timestamp=timestamp, user_id=user_id)
        if statuses:
            allowed = set(statuses)
            revisions = [revision for revision in revisions if revision.status in allowed]
        return [revision.to_dict() for revision in revisions]

    def maturity(self, crystal_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        chain = self._ledger.revision_chain(crystal_id)
        if not chain:
            raise LedgerError(f"crystal {crystal_id} does not have a current head")
        return derive_maturity(chain, now=now).to_dict()

    def evaluate_maturity(
        self,
        *,
        crystal_ids: list[str] | None = None,
        now: datetime | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the zero-LLM state machine and append every resulting state transition."""
        if not self._maturity_enabled:
            return {
                "enabled": False,
                "evaluated": 0,
                "transition_count": 0,
                "transitions": [],
                "invalid_valid_to": [],
            }
        clock = now or datetime.now(timezone.utc)
        targets = crystal_ids or [head.crystal_id for head in self._ledger.heads()]
        targets = list(dict.fromkeys(str(value) for value in targets if value))
        transition_batch = batch_id or new_batch_id()
        transitions: list[dict[str, Any]] = []
        parse_errors: list[dict[str, str]] = []
        for crystal_id in targets:
            # candidate -> active -> canonical may legitimately occur in sequence within one scan.
            for _ in range(2):
                chain = self._ledger.revision_chain(crystal_id)
                if not chain:
                    break
                snapshot = derive_maturity(chain, now=clock)
                if snapshot.valid_to_parse_error:
                    parse_errors.append(
                        {"crystal_id": crystal_id, "valid_to": str(snapshot.valid_to)}
                    )
                status, reason = next_status(
                    snapshot,
                    now=clock,
                    active_min_confidence=self._active_min_confidence,
                    active_min_reinforcement=self._active_min_reinforcement,
                    canonical_min_runs=self._canonical_min_runs,
                    canonical_min_age_days=self._canonical_min_age_days,
                )
                if status is None:
                    break
                op = "expire" if status == "expired" else "promote"
                result = self._ledger.mark_status(
                    crystal_id,
                    status=status,
                    op=op,
                    batch_id=transition_batch,
                    actor="maturity",
                    rationale=reason,
                    audit={"maturity": snapshot.to_dict(), "reason": reason},
                )
                self._outcome(result)
                transitions.append(
                    {
                        "crystal_id": crystal_id,
                        "from": snapshot.status,
                        "to": status,
                        "rev_id": result.rev_id,
                        "reason": reason,
                    }
                )
                self._bump(f"promoted_{status}" if status != "expired" else "expired")
                if status == "expired":
                    break
        self._bump("maturity_evaluations")
        return {
            "enabled": self._maturity_enabled,
            "batch_id": transition_batch,
            "evaluated": len(targets),
            "transition_count": len(transitions),
            "transitions": transitions,
            "invalid_valid_to": parse_errors,
        }

    def rollback_crystal(
        self,
        crystal_id: str,
        *,
        version: int | None = None,
        rev_id: int | None = None,
    ) -> dict[str, Any]:
        before = self._ledger.head(crystal_id)
        pointer = self._ledger.rollback_crystal(crystal_id, version=version, rev_id=rev_id)
        after = self._ledger.head(crystal_id)
        self._reconcile_after_pointer_change([crystal_id])
        self._bump("rollbacks")
        return {
            "kind": "crystal",
            "crystal_id": crystal_id,
            "from_rev_id": before.rev_id if before else None,
            "to_rev_id": pointer.rev_id,
            "version": after.version if after else None,
            "status": after.status if after else None,
            "projection_reconciled": any(
                projection is not None
                for projection in (self._vector_projection, self._document_projection)
            ),
        }

    def rollback_batch(self, batch_id: str) -> dict[str, Any]:
        report = self._ledger.rollback_batch(batch_id)
        affected = [item["crystal_id"] for item in report["reverted"]]
        affected.extend(report["detached"])
        self._reconcile_after_pointer_change(affected)
        self._bump("rollbacks")
        return {
            "kind": "batch",
            **report,
            "projection_reconciled": any(
                projection is not None
                for projection in (self._vector_projection, self._document_projection)
            ),
        }

    def _reconcile_after_pointer_change(self, crystal_ids: list[str]) -> None:
        if self._vector_projection is not None and crystal_ids:
            self._vector_projection.reconcile_crystals(crystal_ids)
        if self._document_projection is not None and crystal_ids:
            self._document_projection.reconcile_crystals(crystal_ids)

    def head_metadata(self, crystal_id: str) -> dict[str, Any] | None:
        """Rebuild the head revision into the existing crystal_metadata shape."""
        head = self._ledger.head(crystal_id)
        return crystal_metadata_from_revision(head) if head else None

    def state(self) -> dict[str, Any]:
        """Operational view of ledger integrity and projection state."""
        with self._lock:
            counters = dict(self._counters)
        result = {
            "enabled": True,
            "authority": "ledger",
            "counters": counters,
            "ledger": self._ledger.stats(),
            "head_check": self._ledger.verify_heads(),
            "maturity": {
                "enabled": self._maturity_enabled,
                "sweep_seconds": self._maturity_sweep_seconds,
                "sweeper_alive": bool(self._maturity_thread and self._maturity_thread.is_alive()),
                "thresholds": {
                    "active_min_confidence": self._active_min_confidence,
                    "active_min_reinforcement": self._active_min_reinforcement,
                    "active_direct_confidence": self._active_direct_confidence,
                    "canonical_min_runs": self._canonical_min_runs,
                    "canonical_min_age_days": self._canonical_min_age_days,
                },
            },
        }
        result["vector_projection"] = (
            self._vector_projection.state()
            if self._vector_projection is not None
            else {
                "enabled": False,
                "last_error": self._projection_init_errors.get("vector"),
            }
        )
        result["document_projection"] = (
            self._document_projection.state()
            if self._document_projection is not None
            else {
                "enabled": False,
                "last_error": self._projection_init_errors.get("document"),
            }
        )
        result["graph_projection"] = (
            self._graph_projection.state()
            if self._graph_projection is not None
            else {
                "enabled": False,
                "last_error": self._projection_init_errors.get("graph"),
            }
        )
        result["validity"] = self.verification_state()
        result["preflight"] = self.preflight()
        return result

    def preflight(self) -> dict[str, Any]:
        """Read-only readiness check of the authoritative boundary."""
        head_check = self._ledger.verify_heads()
        projections: dict[str, Any] = {}
        warnings: list[str] = []
        for name, projection in (
            ("vector", self._vector_projection),
            ("document", self._document_projection),
            ("graph", self._graph_projection),
        ):
            if projection is None:
                init_error = self._projection_init_errors.get(name)
                projections[name] = {"enabled": False, "last_error": init_error}
                if name == "vector":
                    warnings.append("vector projection unavailable; retrieval is raw-only")
                if init_error:
                    warnings.append(f"{name} projection failed to initialize: {init_error}")
                continue
            state = projection.state()
            projections[name] = state
            if state.get("last_error"):
                warnings.append(f"{name} projection error: {state['last_error']}")
            if int(state.get("lag", 0)) > 0:
                warnings.append(f"{name} projection lag: {state['lag']}")
        validity = self.verification_state()
        if validity.get("effective") and validity.get("last_error"):
            warnings.append(f"validity worker error: {validity['last_error']}")
        return {
            "ok": bool(head_check.get("consistent", False)),
            "authority": "ledger",
            "ledger": {
                "db_path": self._ledger.db_path,
                "max_rev_id": self._ledger.max_rev_id(),
                "head_consistent": bool(head_check.get("consistent", False)),
            },
            "projections": projections,
            "validity": validity,
            "warnings": warnings,
        }

    # ── Validity verification ────────────────────────────────────────────

    def verification_state(self) -> dict[str, Any]:
        if self._validity is None:
            return {
                "requested": self._validity_requested,
                "effective": False,
                "reason": ("initialization_failed" if self._validity_init_error else "disabled"),
                "last_error": self._validity_init_error,
            }
        return self._validity.state()

    def verification_cases(
        self,
        *,
        state: str | None = None,
        scope: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._validity is None:
            raise RuntimeError("validity verification is not enabled")
        return self._validity.list_cases(state=state, scope=scope, limit=limit)

    def verification_case(self, case_id: str) -> dict[str, Any] | None:
        if self._validity is None:
            raise RuntimeError("validity verification is not enabled")
        return self._validity.case_detail(case_id)

    def verification_scan(
        self,
        *,
        user_id: str | None = None,
        scope: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if self._validity is None:
            raise RuntimeError("validity verification is not enabled")
        return self._validity.scan(user_id=user_id, scope=scope)

    def verification_retry(self, case_id: str) -> dict[str, Any]:
        if self._validity is None:
            raise RuntimeError("validity verification is not enabled")
        return self._validity.retry(case_id)

    def commit_verification_decision(
        self, case_id: str, decision: dict[str, Any], *, actor: str = "user"
    ) -> dict[str, Any]:
        if self._validity is None:
            raise RuntimeError("validity verification is not enabled")
        return self._validity.apply_decision(case_id, decision, actor=actor)

    def prepare_source_update(self, source_id: str, new_data: str, old_record: Any) -> list[str]:
        if self._validity is None:
            return []
        return self._validity.prepare_source_update(source_id, new_data, old_record)

    def complete_source_update(self, case_ids: list[str], source_id: str, record: Any) -> None:
        if self._validity is not None and case_ids:
            self._validity.complete_source_update(case_ids, source_id, record)

    def compensate_source_update(self, case_ids: list[str], reason: str) -> None:
        if self._validity is not None and case_ids:
            self._validity.compensate_source_update(case_ids, reason)

    def verification_source_deleted(self, source_id: str, affected_crystal_ids: list[str]) -> None:
        if self._validity is not None and affected_crystal_ids:
            self._validity.source_deleted(source_id, affected_crystal_ids)

    def card(self, crystal_id: str) -> dict[str, Any] | None:
        if self._document_projection is None:
            raise RuntimeError("document projection is not enabled")
        return self._document_projection.card(crystal_id)

    def graph_traverse(
        self, subject: str, *, max_depth: int = 2, user_id: str | None = None
    ) -> dict[str, Any]:
        if self._graph_projection is None:
            raise RuntimeError("graph projection is not enabled")
        return self._graph_projection.traverse(subject, max_depth=max_depth, user_id=user_id)

    def graph_conflicts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if self._graph_projection is None:
            raise RuntimeError("graph projection is not enabled")
        return self._graph_projection.conflicts(
            subject=subject, predicate=predicate, user_id=user_id
        )

    def rebuild_projections(self, projections: list[str]) -> dict[str, Any]:
        requested = list(dict.fromkeys(str(value).strip() for value in projections if value))
        if not requested:
            requested = ["vector", "document", "graph"]
        unknown = sorted(set(requested) - {"vector", "document", "graph"})
        if unknown:
            raise ValueError(f"unknown projections: {', '.join(unknown)}")
        result: dict[str, Any] = {}
        for projection in requested:
            instance = getattr(self, f"_{projection}_projection")
            if instance is None:
                result[projection] = {"enabled": False}
            else:
                result[projection] = {"enabled": True, **instance.rebuild()}
        return result

    def search_crystals(
        self,
        query: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search the standalone crystal projection in a backend-agnostic shape."""
        if self._vector_projection is None:
            raise RuntimeError("vector projection is not enabled")
        projection_state = self._vector_projection.state()
        if projection_state.get("last_error") or int(projection_state.get("lag", 0)) > 0:
            raise RuntimeError(
                "vector projection is not authoritative-read-safe: "
                f"lag={projection_state.get('lag', 0)}, "
                f"error={projection_state.get('last_error') or '-'}"
            )
        return self._vector_projection.search(
            query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            filters=filters,
            limit=limit,
        )

    def flush_vector_projection(self) -> int:
        if self._vector_projection is None:
            raise RuntimeError("vector projection is not enabled")
        return self._vector_projection.flush()

    def rebuild_vector_projection(self) -> dict[str, int]:
        if self._vector_projection is None:
            raise RuntimeError("vector projection is not enabled")
        return self._vector_projection.rebuild()

    def reset_all_state(self) -> dict[str, Any]:
        """Factory reset: clear the ledger and zero the counters."""
        reset_ledger = (
            self._vector_projection.reset_with_ledger
            if self._vector_projection is not None
            else self._ledger.reset
        )
        summary = (
            self._document_projection.reset_with_ledger(reset_ledger)
            if self._document_projection is not None
            else reset_ledger()
        )
        with self._lock:
            for key in self._counters:
                self._counters[key] = 0
        return summary

    def close(self) -> None:
        """Stop async projectors before closing this thread's ledger handle."""
        self._maturity_stop.set()
        if self._maturity_thread and self._maturity_thread.is_alive():
            self._maturity_thread.join(timeout=2.0)
        if self._validity is not None:
            self._validity.close()
        if self._vector_projection is not None:
            self._vector_projection.close()
        if self._document_projection is not None:
            self._document_projection.close()
        if self._graph_projection is not None:
            self._graph_projection.close()
        self._ledger.close()

    def _maturity_worker(self) -> None:
        """Continuously enforce the deterministic valid_to and maturity transitions."""
        try:
            while not self._maturity_stop.wait(self._maturity_sweep_seconds):
                try:
                    self.evaluate_maturity()
                except Exception:
                    logger.error("background maturity sweep failed", exc_info=True)
        finally:
            self._ledger.close()

    # ── Internals ────────────────────────────────────────────────────────

    def _initial_create_status(self, merged: dict[str, Any], op: str) -> str:
        """Determine the initial ledger status of a new crystal.

        A high-confidence create (>= active_direct_confidence) skips the candidate observation
        period and becomes immediately searchable. A low-confidence create enters "candidate"
        and requires at least one absorb confirmation before being promoted to active.
        """
        if not self._maturity_enabled or op != "create":
            return "active"
        confidence = _as_float(merged.get("confidence"))
        if confidence is not None and confidence >= self._active_direct_confidence:
            return "active"
        return "candidate"

    def _evaluate_after_commit(self, crystal_id: str, batch_id: str) -> None:
        """Keep the committed ledger write successful even if derived maturity fails."""
        try:
            self.evaluate_maturity(crystal_ids=[crystal_id], batch_id=batch_id)
        except Exception as exc:
            self._bump("failures")
            logger.error(
                "固化层: 成熟度评估失败，保留已提交修订 (crystal=%s): %s",
                crystal_id,
                exc,
                exc_info=True,
            )

    def _revision_input(
        self,
        *,
        crystal_id: str,
        batch_id: str,
        op: str,
        status: str,
        merged: dict[str, Any],
        source_ids: list[str],
        scope: dict[str, str],
        audit: dict[str, Any] | None,
        rationale: str | None,
    ) -> RevisionInput:
        """Map the crystallizer's merged candidate into ledger input.

        Field names follow merged's existing conventions (text / type / asset_type / asset /
        facets) and map to ledger columns (body / knowledge_type / ...). asset.valid_from/valid_to
        are promoted to first-class columns in the ledger and take part in evaluation (the existing
        implementation only stores them as free strings).
        """
        asset = merged.get("asset") if isinstance(merged.get("asset"), dict) else {}
        return RevisionInput(
            crystal_id=crystal_id,
            batch_id=batch_id,
            op=op,
            status=status,
            body=str(merged.get("text") or "").strip(),
            asset=asset,
            facets=merged.get("facets") if isinstance(merged.get("facets"), dict) else {},
            knowledge_type=str(merged.get("type") or "") or None,
            asset_type=str(merged.get("asset_type") or "") or None,
            subject=str(merged.get("subject") or asset.get("subject") or "") or None,
            confidence=_as_float(merged.get("confidence")),
            source_ids=_clean_source_ids(source_ids),
            valid_from=str(asset.get("valid_from") or "").strip() or None,
            valid_to=str(asset.get("valid_to") or "").strip() or None,
            actor="crystallizer",
            rationale=rationale,
            audit=audit or {},
            scope=scope,
        )

    def _outcome(self, result: AppendResult) -> CommitOutcome:
        self._bump("commits")
        if result.skipped:
            self._bump("skipped")
        else:
            for name, projection in (
                ("vector", self._vector_projection),
                ("document", self._document_projection),
                ("graph", self._graph_projection),
            ):
                if projection is None:
                    continue
                try:
                    projection.notify(result.rev_id)
                except Exception as exc:
                    # The ledger transaction has already committed. A projection failure can be
                    # observed in state() and retried/rebuilt.
                    logger.error(
                        "固化层: %s 投影通知失败，等待重试: %s",
                        name,
                        exc,
                        exc_info=True,
                    )
        revision = result.revision
        return CommitOutcome(
            ok=True,
            crystal_id=result.crystal_id,
            rev_id=result.rev_id,
            version=revision.version if revision else None,
            skipped=result.skipped,
        )

    def _failure(self, where: str, exc: Exception, *, crystal_id: str | None) -> NoReturn:
        self._bump("failures")
        # Invalid input is a caller issue with no diagnostic value in the traceback; only
        # storage-layer failures need the full stack
        logger.error(
            "固化层: %s 失败 (crystal=%s): %s",
            where,
            crystal_id or "-",
            exc,
            exc_info=not isinstance(exc, ValueError),
        )
        raise exc

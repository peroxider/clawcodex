"""Persistent validity workflow orchestrator; the Ledger remains the source of truth."""

from __future__ import annotations

import logging
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import (
    AppendResult,
    CrystalLedger,
    LedgerError,
)
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    Revision,
    RevisionInput,
    new_batch_id,
)
from clawcodex_ext.latent_memory.server.lib.validity.arbiter import LLMArbiter
from clawcodex_ext.latent_memory.server.lib.validity.detector import ValidityDetector
from clawcodex_ext.latent_memory.server.lib.validity.evidence import EvidenceCollector
from clawcodex_ext.latent_memory.server.lib.validity.models import (
    CaseInput,
    VerificationCase,
    VerificationDecision,
    sha256_json,
)

logger = logging.getLogger("memory-server.validity")


def _snapshot(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _raw_hash(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("memory", value.get("data", value))
    return sha256_json({"data": value})


class ValidityStore:
    def __init__(
        self,
        ledger: CrystalLedger,
        config: dict[str, Any],
        *,
        backend_accessor: Callable[[], Any],
        llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        on_results: Callable[[list[AppendResult]], None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._backend_accessor = backend_accessor
        self._config = dict(config)
        self._policy_version = str(config.get("policy_version", "v1"))
        self._prompt_version = "validity-v2"
        self._model_id = str(config.get("model_id", "configured-crystallizer-llm"))
        self._scan_interval = max(1.0, float(config.get("scan_interval_seconds", 30)))
        self._full_audit_interval = max(
            self._scan_interval,
            float(config.get("full_audit_interval_seconds", 3600)),
        )
        self._max_cases = max(1, int(config.get("max_cases_per_run", 20)))
        self._lease_seconds = max(1.0, float(config.get("case_lease_seconds", 120)))
        self._max_attempts = max(1, int(config.get("max_attempts", 5)))
        self._llm_enabled = bool(config.get("llm_enabled", True) and llm_fn)
        self._llm_min_risk = int(config.get("llm_min_risk", 40))
        self._auto_apply_confidence = float(config.get("auto_apply_min_confidence", 0.85))
        self._on_results = on_results or (lambda _results: None)
        self._detector = ValidityDetector(
            ledger,
            policy_version=self._policy_version,
            batch_size=int(config.get("batch_size", 50)),
            on_results=self._on_results,
        )
        self._collector = EvidenceCollector(
            backend_accessor,
            max_per_crystal=int(config.get("max_evidence_per_crystal", 8)),
            max_chars=int(config.get("max_evidence_chars", 12000)),
        )
        self._arbiter = LLMArbiter(llm_fn) if self._llm_enabled and llm_fn else None
        self._owner = f"validity-{uuid.uuid4().hex[:12]}"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="validity-verifier", daemon=True)
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_run_at: str | None = None
        # The first full audit round is delayed by one full interval: time.monotonic() measures
        # time since system boot. If initialized to 0.0, a machine booted longer ago than the
        # interval would trigger a full audit immediately on the first run_once, colliding with
        # the service/storage warm-up period (higher backend flakiness), which is prone to false
        # positives. Measuring from process start matches the configuration semantics of "execute
        # once an interval has passed since the last audit".
        self._last_full_audit_monotonic = time.monotonic()
        self._llm_latencies_ms: list[float] = []
        self._counters = {
            "scans": 0,
            "detected": 0,
            "deduplicated": 0,
            "processed": 0,
            "llm_calls": 0,
            "cache_hits": 0,
            "auto_applied": 0,
            "manual_applied": 0,
            "needs_review": 0,
            "stale": 0,
            "failures": 0,
        }
        self._thread.start()

    def _bump(self, key: str, value: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def scan(
        self, *, user_id: str | None = None, scope: dict[str, str] | None = None
    ) -> dict[str, Any]:
        result = self._detector.scan(user_id=user_id, scope=scope, limit=self._max_cases)
        self._bump("scans")
        self._bump("detected", int(result["created"]))
        self._bump("deduplicated", int(result["deduplicated"]))
        return result

    def run_once(self) -> dict[str, Any]:
        recovered = self.recover_source_updates()
        scan = self.scan()
        source_audit = {"examined": 0, "probes": 0}
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_full_audit_monotonic >= self._full_audit_interval:
            source_audit = self._source_health_scan()
            self._last_full_audit_monotonic = now_monotonic
        cases = self._ledger.claim_verification_cases(
            owner=self._owner,
            limit=self._max_cases,
            lease_seconds=self._lease_seconds,
            max_attempts=self._max_attempts,
        )
        processed = 0
        for case in cases:
            self._process(case)
            processed += 1
        with self._lock:
            self._last_run_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None
        return {
            "recovered_source_updates": recovered,
            "source_audit": source_audit,
            "scan": scan,
            "claimed": len(cases),
            "processed": processed,
        }

    @staticmethod
    def _participants(case: VerificationCase) -> list[str]:
        return list(
            dict.fromkeys(value for value in (case.left_crystal_id, case.right_crystal_id) if value)
        )

    def _case_heads(self, case: VerificationCase) -> list[Revision]:
        return [
            head
            for crystal_id in self._participants(case)
            if (head := self._ledger.head(crystal_id)) is not None
        ]

    def _collect(self, case: VerificationCase) -> tuple[VerificationCase, list[Any]]:
        heads = self._case_heads(case)
        source_ids = list(
            dict.fromkeys(source_id for head in heads for source_id in head.source_ids)
        )
        evidence_input = self._collector.collect(source_ids)
        self._ledger.record_verification_evidence(
            case.case_id,
            evidence_input,
            prompt_version=self._prompt_version,
            model_id=self._model_id,
        )
        refreshed = self._ledger.verification_case(case.case_id)
        if refreshed is None:
            raise LedgerError(f"verification case disappeared: {case.case_id}")
        return refreshed, self._ledger.verification_evidence(case.case_id)

    def _process(self, case: VerificationCase) -> None:
        try:
            case, evidence = self._collect(case)
            self._bump("processed")
            if case.case_type == "source_probe":
                self._finish_source_probe(case, evidence)
                return
            usable = [item for item in evidence if item.source_kind == "raw"]
            if case.case_type in ("source_missing", "unsupported_claim", "source_deleted"):
                self._review(case, "deterministic_risk_requires_review")
                return
            if case.case_type == "graph_conflict":
                usable_refs = {item.source_ref for item in usable}
                if any(
                    not head.source_ids
                    or not any(source_id in usable_refs for source_id in head.source_ids)
                    for head in self._case_heads(case)
                ):
                    self._review(case, "both_sides_require_valid_evidence")
                    return
            if not usable or case.priority < self._llm_min_risk or self._arbiter is None:
                self._review(case, "evidence_or_arbiter_unavailable")
                return
            cached = (
                self._ledger.cached_verification_decision(case.decision_input_hash)
                if case.decision_input_hash
                else None
            )
            if cached is not None:
                decision = VerificationDecision.from_dict(cached)
                self._bump("cache_hits")
            else:
                started = time.perf_counter()
                decision = self._arbiter.decide(
                    case,
                    [head.to_dict() for head in self._case_heads(case)],
                    evidence,
                )
                latency = (time.perf_counter() - started) * 1000
                with self._lock:
                    self._llm_latencies_ms = [
                        *self._llm_latencies_ms[-199:],
                        round(latency, 3),
                    ]
                self._bump("llm_calls")
                if case.decision_input_hash:
                    self._ledger.cache_verification_decision(
                        case.decision_input_hash, decision.to_dict()
                    )
            if (
                decision.decision == "insufficient_evidence"
                or decision.confidence < self._auto_apply_confidence
            ):
                self._review(case, "insufficient_or_low_confidence", decision.to_dict())
                return
            self.apply_decision(case.case_id, decision, actor="validity_verifier")
            self._bump("auto_applied")
        except Exception as exc:
            self._handle_failure(case, exc)

    def _source_health_scan(self) -> dict[str, int]:
        heads = [
            head
            for head in self._ledger.heads(statuses=("candidate", "active", "canonical"))
            if head.op != "dispute" and head.source_ids
        ]
        source_ids = list(
            dict.fromkeys(source_id for head in heads for source_id in head.source_ids)
        )
        found: set[str] = set()
        backend = self._backend_accessor()
        batch_size = max(1, int(self._config.get("batch_size", 50)))
        try:
            for index in range(0, len(source_ids), batch_size):
                records = backend.get_memories_by_ids(source_ids[index : index + batch_size])
                found.update(
                    str(record.get("id"))
                    for record in records
                    if isinstance(record, dict) and record.get("id")
                )
        except Exception:
            logger.warning("source health audit skipped because backend is unavailable")
            return {"examined": len(heads), "probes": 0}

        probes = 0
        for head in heads:
            if probes >= self._max_cases:
                break
            missing = [source_id for source_id in head.source_ids if source_id not in found]
            if not missing:
                continue
            case, created, _ = self._ledger.open_verification_case(
                CaseInput(
                    case_type="source_probe",
                    scope=dict(head.scope),
                    subject=head.subject,
                    left_crystal_id=head.crystal_id,
                    left_head_rev=head.rev_id,
                    trigger_rev_id=head.rev_id,
                    trigger_payload={"missing_source_ids": missing},
                    policy_version=self._policy_version,
                    priority=45,
                ),
                dispute=False,
            )
            if created:
                probes += 1
                self._ledger.set_verification_case_state(
                    case.case_id,
                    "pending",
                    next_attempt_at=(
                        datetime.now(timezone.utc) + timedelta(seconds=self._scan_interval)
                    ).isoformat(),
                )
        return {"examined": len(heads), "probes": probes}

    def _finish_source_probe(self, case: VerificationCase, evidence: list[Any]) -> None:
        missing = [item.source_ref for item in evidence if item.source_kind == "missing_raw"]
        current = self._ledger.head(case.left_crystal_id or "")
        if current is None or current.rev_id != case.left_head_rev:
            self._ledger.set_verification_case_state(
                case.case_id, "stale", error="head_changed_during_source_probe"
            )
            self._bump("stale")
            return
        escalated_case_id = None
        if missing:
            escalated, created, results = self._ledger.open_verification_case(
                CaseInput(
                    case_type="source_missing",
                    scope=dict(current.scope),
                    subject=current.subject,
                    left_crystal_id=current.crystal_id,
                    left_head_rev=current.rev_id,
                    trigger_rev_id=current.rev_id,
                    trigger_payload={"missing_source_ids": missing},
                    policy_version=self._policy_version,
                    priority=70,
                )
            )
            escalated_case_id = escalated.case_id
            if created:
                self._on_results(results)
        self._ledger.set_verification_case_state(
            case.case_id,
            "resolved",
            error=None,
            result={
                "outcome": "confirmed_missing" if missing else "transient_missing",
                "missing_source_ids": missing,
                "escalated_case_id": escalated_case_id,
            },
        )

    def _review(
        self, case: VerificationCase, reason: str, result: dict[str, Any] | None = None
    ) -> None:
        self._ledger.set_verification_case_state(
            case.case_id,
            "needs_review",
            error=reason,
            result=result,
        )
        self._bump("needs_review")

    def _handle_failure(self, case: VerificationCase, exc: Exception) -> None:
        self._bump("failures")
        delay = min(300, 2 ** max(1, case.attempts))
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        state = "failed" if case.attempts >= self._max_attempts else "pending"
        self._ledger.set_verification_case_state(
            case.case_id, state, error=str(exc), next_attempt_at=retry_at
        )
        logger.error("validity case %s failed: %s", case.case_id, exc, exc_info=True)

    @staticmethod
    def _previous_status(head: Revision) -> str:
        value = (head.audit.get("verification") or {}).get("previous_status")
        if value == "candidate":
            return "candidate"
        return "active"

    def _audit(
        self,
        case: VerificationCase,
        decision: VerificationDecision,
        *,
        contradiction_delta: int,
        actor: str,
    ) -> dict[str, Any]:
        evidence = self._ledger.verification_evidence(case.case_id)
        return {
            "maturity": {"contradiction_delta": contradiction_delta},
            "verification": {
                "case_id": case.case_id,
                "case_type": case.case_type,
                "decision": decision.decision,
                "evidence_round": case.evidence_round,
                "evidence_hashes": [item.observed_hash for item in evidence],
                "decision_input_hash": case.decision_input_hash,
                "policy_version": case.policy_version,
                "model_id": self._model_id if actor == "validity_verifier" else None,
                "reason_codes": decision.reason_codes,
                "confidence": decision.confidence,
            },
        }

    def _entry(
        self,
        head: Revision,
        case: VerificationCase,
        decision: VerificationDecision,
        *,
        op: str,
        status: str,
        actor: str,
        contradiction_delta: int,
        batch_id: str,
        patch: dict[str, Any] | None = None,
        lineage: list[tuple[str, str, str]] | None = None,
    ) -> RevisionInput:
        patch = patch or {}
        asset = dict(head.asset)
        asset.update(dict(patch.get("asset") or {}))
        valid_from = patch.get("valid_from", head.valid_from)
        valid_to = patch.get("valid_to", head.valid_to)
        source_ids = patch.get("source_ids", head.source_ids)
        if not isinstance(source_ids, (list, tuple)):
            raise ValueError("repair source_ids must be a list")
        for field, value in (("valid_from", valid_from), ("valid_to", valid_to)):
            if field in patch and value is None:
                asset.pop(field, None)
            elif value is not None:
                asset[field] = value
        return RevisionInput(
            crystal_id=head.crystal_id,
            batch_id=batch_id,
            op=op,
            status=status,
            body=str(patch.get("body", head.body)),
            asset=asset,
            facets=dict(head.facets),
            knowledge_type=head.knowledge_type,
            asset_type=head.asset_type,
            subject=head.subject,
            confidence=head.confidence,
            source_ids=list(dict.fromkeys(str(value) for value in source_ids if value)),
            valid_from=valid_from,
            valid_to=valid_to,
            actor=actor,
            rationale=decision.rationale or decision.decision,
            audit=self._audit(case, decision, contradiction_delta=contradiction_delta, actor=actor),
            scope=dict(head.scope),
            lineage=lineage or [],
        )

    def _expected_heads(self, case: VerificationCase) -> dict[str, int]:
        participants = self._participants(case)
        rev_ids = case.opened_rev_ids or [
            value for value in (case.left_head_rev, case.right_head_rev) if value is not None
        ]
        return {crystal_id: int(rev_id) for crystal_id, rev_id in zip(participants, rev_ids)}

    @staticmethod
    def _resolution_delta(case: VerificationCase, head: Revision) -> int:
        return -1 if head.rev_id in case.opened_rev_ids else 0

    def _decision_entries(
        self, case: VerificationCase, decision: VerificationDecision, actor: str
    ) -> list[RevisionInput]:
        batch_id = new_batch_id()
        heads = {head.crystal_id: head for head in self._case_heads(case)}
        left = heads.get(case.left_crystal_id or "")
        right = heads.get(case.right_crystal_id or "")
        if left is None:
            raise LedgerError("verification left head is unavailable")

        if decision.decision in ("confirm_left", "confirm_right"):
            winner = left if decision.decision == "confirm_left" else right
            loser = right if winner is left else left
            if winner is None:
                raise ValueError("decision references a missing side")
            entries = [
                self._entry(
                    winner,
                    case,
                    decision,
                    op="verify",
                    status=self._previous_status(winner),
                    actor=actor,
                    contradiction_delta=self._resolution_delta(case, winner),
                    batch_id=batch_id,
                )
            ]
            if loser is not None:
                entries.append(
                    self._entry(
                        loser,
                        case,
                        decision,
                        op="supersede",
                        status="superseded",
                        actor=actor,
                        contradiction_delta=0,
                        batch_id=batch_id,
                        lineage=[(loser.crystal_id, winner.crystal_id, "superseded_by")],
                    )
                )
            return entries

        if decision.decision in ("coexist", "repair"):
            entries: list[RevisionInput] = []
            repair = decision.repair or {}
            for side, head in (("left", left), ("right", right)):
                if head is None:
                    continue
                patch = dict(repair.get(side) or {}) if isinstance(repair, dict) else {}
                validity = decision.validity
                for field in ("valid_from", "valid_to"):
                    key = f"{side}_{field}"
                    if key in validity:
                        patch[field] = validity[key]
                op = "repair" if patch else "verify"
                entries.append(
                    self._entry(
                        head,
                        case,
                        decision,
                        op=op,
                        status=self._previous_status(head),
                        actor=actor,
                        contradiction_delta=self._resolution_delta(case, head),
                        patch=patch,
                        batch_id=batch_id,
                    )
                )
            return entries
        raise ValueError("insufficient_evidence cannot be applied")

    def apply_decision(
        self,
        case_id: str,
        decision: VerificationDecision | dict[str, Any],
        *,
        actor: str = "user",
    ) -> dict[str, Any]:
        if isinstance(decision, dict):
            decision = VerificationDecision.from_dict(decision)
        case = self._ledger.verification_case(case_id)
        if case is None:
            raise LedgerError(f"verification case not found: {case_id}")
        if decision.decision == "insufficient_evidence":
            self._review(case, "manual_insufficient_evidence", decision.to_dict())
            return {"case_id": case_id, "state": "needs_review", "result_rev_ids": []}
        if case.case_type == "source_deleted":
            repair = decision.repair or {}
            left_patch = repair.get("left") if isinstance(repair, dict) else None
            source_ids = left_patch.get("source_ids") if isinstance(left_patch, dict) else None
            deleted_id = case.trigger_payload.get("source_id")
            if (
                decision.decision != "repair"
                or not isinstance(source_ids, list)
                or not source_ids
                or deleted_id in source_ids
            ):
                raise ValueError(
                    "source_deleted can only be repaired with non-empty remaining source_ids"
                )
        entries = self._decision_entries(case, decision, actor)
        state, results = self._ledger.append_verification_decision(
            case_id,
            self._expected_heads(case),
            entries,
            decision=decision.to_dict(),
        )
        if state == "stale":
            self._bump("stale")
        else:
            self._on_results(results)
            if actor != "validity_verifier":
                self._bump("manual_applied")
        return {
            "case_id": case_id,
            "state": state,
            "result_rev_ids": [result.rev_id for result in results if result.rev_id],
        }

    def prepare_source_update(self, source_id: str, new_data: str, old_record: Any) -> list[str]:
        old_snapshot = _snapshot(
            old_record if isinstance(old_record, dict) else {"value": old_record}
        )
        cases: list[str] = []
        for head in self._ledger.heads_referencing_source(
            source_id, statuses=("candidate", "active", "canonical")
        ):
            case, created, results = self._ledger.open_verification_case(
                CaseInput(
                    case_type="source_update",
                    scope=dict(head.scope),
                    subject=head.subject,
                    left_crystal_id=head.crystal_id,
                    left_head_rev=head.rev_id,
                    trigger_rev_id=head.rev_id,
                    trigger_payload={
                        "source_id": source_id,
                        "old_hash": _raw_hash(old_snapshot),
                        "expected_new_hash": _raw_hash(new_data),
                    },
                    policy_version=self._policy_version,
                    priority=65,
                    initial_state="waiting_evidence",
                )
            )
            cases.append(case.case_id)
            if created:
                self._on_results(results)
        return cases

    def complete_source_update(self, case_ids: list[str], source_id: str, record: Any) -> None:
        snapshot = _snapshot(record if isinstance(record, dict) else {"value": record})
        for case_id in case_ids:
            self._ledger.record_verification_evidence(
                case_id,
                [
                    {
                        "source_kind": "raw",
                        "source_ref": source_id,
                        "observed_hash": sha256_json(snapshot),
                        "snapshot": snapshot,
                    }
                ],
                prompt_version=self._prompt_version,
                model_id=self._model_id,
                make_pending=True,
            )

    def recover_source_updates(self) -> dict[str, int]:
        """Resolve the narrow crash window between the raw commit and evidence finalization."""
        recovered = compensated = review = 0
        cases = self._ledger.verification_cases(state="waiting_evidence", limit=self._max_cases)
        for case in cases:
            source_id = str(case.trigger_payload.get("source_id") or "")
            if case.case_type != "source_update" or not source_id:
                continue
            try:
                record = self._backend_accessor().get_memory(source_id)
            except Exception as exc:
                self._ledger.set_verification_case_state(
                    case.case_id,
                    "waiting_evidence",
                    error=f"source_recovery_read_failed: {exc}",
                )
                continue
            observed = _raw_hash(record)
            if observed == case.trigger_payload.get("expected_new_hash"):
                self.complete_source_update([case.case_id], source_id, record)
                recovered += 1
            elif observed == case.trigger_payload.get("old_hash"):
                self.compensate_source_update(
                    [case.case_id], "raw update did not commit; recovered prior validity"
                )
                compensated += 1
            else:
                self._ledger.set_verification_case_state(
                    case.case_id,
                    "needs_review",
                    error="source_recovery_hash_mismatch",
                )
                review += 1
        return {"completed": recovered, "compensated": compensated, "review": review}

    def compensate_source_update(self, case_ids: list[str], reason: str) -> None:
        for case_id in case_ids:
            case = self._ledger.verification_case(case_id)
            if case is None or case.state == "resolved":
                continue
            decision = VerificationDecision(
                decision="confirm_left",
                confidence=1.0,
                rationale=reason,
                reason_codes=["backend_update_failed_compensation"],
            )
            self.apply_decision(case_id, decision, actor="system")

    def source_deleted(self, source_id: str, affected_crystal_ids: list[str]) -> None:
        for crystal_id in affected_crystal_ids:
            head = self._ledger.head(crystal_id)
            if head is None:
                continue
            self._ledger.open_verification_case(
                CaseInput(
                    case_type="source_deleted",
                    scope=dict(head.scope),
                    subject=head.subject,
                    left_crystal_id=head.crystal_id,
                    left_head_rev=head.rev_id,
                    trigger_rev_id=head.rev_id,
                    trigger_payload={"source_id": source_id},
                    policy_version=self._policy_version,
                    priority=70,
                ),
                dispute=False,
            )

    def list_cases(
        self,
        *,
        state: str | None = None,
        scope: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return [
            case.to_dict()
            for case in self._ledger.verification_cases(state=state, scope=scope, limit=limit)
        ]

    def case_detail(self, case_id: str) -> dict[str, Any] | None:
        case = self._ledger.verification_case(case_id)
        if case is None:
            return None
        return {
            **case.to_dict(),
            "evidence": [item.to_dict() for item in self._ledger.verification_evidence(case_id)],
        }

    def retry(self, case_id: str) -> dict[str, Any]:
        return self._ledger.retry_verification_case(case_id).to_dict()

    def state(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            last_error = self._last_error
            last_run_at = self._last_run_at
            latencies = sorted(self._llm_latencies_ms)

        def percentile(fraction: float) -> float | None:
            if not latencies:
                return None
            return latencies[min(len(latencies) - 1, int((len(latencies) - 1) * fraction))]

        return {
            "requested": True,
            "effective": True,
            "worker_alive": self._thread.is_alive(),
            "scan_interval_seconds": self._scan_interval,
            "llm_enabled": self._llm_enabled,
            "last_run_at": last_run_at,
            "last_error": last_error,
            "llm_latency_ms": {"p50": percentile(0.50), "p95": percentile(0.95)},
            "counters": counters,
            **self._ledger.verification_stats(),
        }

    def _worker(self) -> None:
        try:
            while not self._stop.wait(self._scan_interval):
                try:
                    self.run_once()
                except Exception as exc:
                    with self._lock:
                        self._last_error = str(exc)
                    self._bump("failures")
                    logger.error("validity worker failed", exc_info=True)
        finally:
            self._ledger.close()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

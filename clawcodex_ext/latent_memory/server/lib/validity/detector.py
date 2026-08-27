"""Deterministic, zero-LLM validity candidate detection."""

from __future__ import annotations

from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import CrystalLedger, LedgerError
from clawcodex_ext.latent_memory.server.lib.validity.models import (
    CaseInput,
    graph_adjudication_fingerprint,
    sha256_json,
)


def _risk(left: dict[str, Any], right: dict[str, Any] | None = None) -> int:
    score = 20
    statuses = {str(left.get("status") or "")}
    if right:
        statuses.add(str(right.get("status") or ""))
    if "canonical" in statuses:
        score += 30
    elif "active" in statuses:
        score += 20
    return min(score, 100)


class ValidityDetector:
    def __init__(
        self,
        ledger: CrystalLedger,
        *,
        policy_version: str,
        batch_size: int = 50,
        on_results: Callable[[list[Any]], None] | None = None,
    ) -> None:
        self._ledger = ledger
        self._policy_version = policy_version
        self._batch_size = max(1, int(batch_size))
        self._on_results = on_results or (lambda _results: None)

    def scan(
        self,
        *,
        user_id: str | None = None,
        scope: dict[str, str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        scope_filter = {str(key): str(value) for key, value in (scope or {}).items() if value}
        if user_id is not None:
            scope_filter["user_id"] = user_id
        detector_key = f"scope:{sha256_json(scope_filter)[:24]}" if scope_filter else "default"
        remaining = max(1, int(limit))
        created = 0
        deduplicated = 0
        examined = 0

        through = self._ledger.verification_cursor(detector_key)
        page = self._ledger.revisions_after(through, limit=self._batch_size)
        scanned_through = through
        for revision in page:
            if created >= remaining:
                break
            scanned_through = revision.rev_id
            if revision.op in ("dispute", "verify", "retract", "supersede", "expire"):
                continue
            head = self._ledger.head(revision.crystal_id)
            if head is None or head.rev_id != revision.rev_id:
                continue
            if scope_filter and not all(
                head.scope.get(key) == value for key, value in scope_filter.items()
            ):
                continue
            examined += 1
            unsupported = (head.audit.get("retention") or {}).get("unsupported_claims")
            if head.source_ids and not unsupported:
                continue
            case_type = "unsupported_claim" if unsupported else "source_missing"
            priority = 50 if unsupported else 60
            try:
                _, was_created, results = self._ledger.open_verification_case(
                    CaseInput(
                        case_type=case_type,
                        scope=dict(head.scope),
                        subject=head.subject,
                        left_crystal_id=head.crystal_id,
                        left_head_rev=head.rev_id,
                        trigger_rev_id=head.rev_id,
                        trigger_payload={"unsupported_claims": unsupported or []},
                        policy_version=self._policy_version,
                        priority=priority,
                    )
                )
            except LedgerError:
                continue
            if was_created:
                created += 1
                self._on_results(results)
            else:
                deduplicated += 1

        if scanned_through > through:
            self._ledger.set_verification_cursor(scanned_through, detector_key)

        conflicts = [
            *self._ledger.graph_conflicts(user_id=scope_filter.get("user_id")),
            *self._ledger.candidate_graph_conflicts(user_id=scope_filter.get("user_id")),
        ]
        accepted_coexist_keys = self._ledger.resolved_graph_coexist_case_keys(self._policy_version)
        seen: set[tuple[int, int]] = set()
        for conflict in conflicts:
            if created >= remaining:
                break
            left = conflict["left"]
            right = conflict["right"]
            pair = tuple(sorted((int(left["rev_id"]), int(right["rev_id"]))))
            if pair in seen:
                continue
            seen.add(pair)
            left_head = self._ledger.revision(int(left["rev_id"]))
            right_head = self._ledger.revision(int(right["rev_id"]))
            if left_head is None or right_head is None:
                continue
            if scope_filter and not all(
                left_head.scope.get(key) == value for key, value in scope_filter.items()
            ):
                continue
            examined += 1
            adjudication_fingerprint = graph_adjudication_fingerprint(left_head, right_head)
            case_input = CaseInput(
                case_type="graph_conflict",
                scope=dict(left_head.scope),
                subject=conflict.get("subject"),
                predicate=conflict.get("predicate"),
                left_crystal_id=left["crystal_id"],
                left_head_rev=int(left["rev_id"]),
                right_crystal_id=right["crystal_id"],
                right_head_rev=int(right["rev_id"]),
                trigger_rev_id=max(pair),
                trigger_payload={
                    "edge_snapshot": conflict,
                    "adjudication_fingerprint": adjudication_fingerprint,
                },
                policy_version=self._policy_version,
                priority=_risk(left, right),
                adjudication_fingerprint=adjudication_fingerprint,
            )
            if case_input.case_key in accepted_coexist_keys:
                deduplicated += 1
                continue
            try:
                _, was_created, results = self._ledger.open_verification_case(case_input)
            except LedgerError:
                continue
            if was_created:
                created += 1
                self._on_results(results)
            else:
                deduplicated += 1
        return {
            "examined": examined,
            "created": created,
            "deduplicated": deduplicated,
            "cursor": detector_key,
            "cursor_through_rev": self._ledger.verification_cursor(detector_key),
        }

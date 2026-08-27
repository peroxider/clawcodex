"""Lightweight, serializable models for the validity workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

CASE_STATES = frozenset(
    {
        "waiting_evidence",
        "pending",
        "running",
        "needs_review",
        "resolved",
        "stale",
        "failed",
    }
)
DECISIONS = frozenset(
    {"confirm_left", "confirm_right", "coexist", "repair", "insufficient_evidence"}
)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def graph_adjudication_fingerprint(*heads: Any) -> str:
    """Hash the graph conflict inputs while deliberately excluding rev/op/status.

    Only state changes and the verify revisions for coexist must retain the accepted
    identity. Changes to claims, validity, sources, confidence, or types must not be retained.
    """
    participants = sorted(
        (
            {
                "crystal_id": head.crystal_id,
                "content_hash": head.content_hash,
                "knowledge_type": head.knowledge_type,
                "asset_type": head.asset_type,
                "subject": head.subject,
                "confidence": head.confidence,
                "source_ids": sorted(set(head.source_ids)),
                "valid_from": head.valid_from,
                "valid_to": head.valid_to,
            }
            for head in heads
        ),
        key=lambda value: value["crystal_id"],
    )
    return sha256_json({"participants": participants})


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def new_case_id() -> str:
    return f"vc_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class CaseInput:
    case_type: str
    scope: dict[str, str] = field(default_factory=dict)
    subject: str | None = None
    predicate: str | None = None
    left_crystal_id: str | None = None
    left_head_rev: int | None = None
    right_crystal_id: str | None = None
    right_head_rev: int | None = None
    trigger_rev_id: int | None = None
    trigger_payload: dict[str, Any] = field(default_factory=dict)
    policy_version: str = "v1"
    priority: int = 0
    initial_state: str = "pending"
    # The coexist/verify for a graph conflict creates a new head rev_id when content is unchanged.
    # The detector can provide a stable arbitration input fingerprint without a rev_id, preventing
    # case-closing actions from themselves triggering a reopen; other cases still use the head
    # rev_id as their idempotency identity.
    adjudication_fingerprint: str | None = None

    def validate(self) -> None:
        if not str(self.case_type or "").strip():
            raise ValueError("case_type cannot be empty")
        if self.initial_state not in CASE_STATES:
            raise ValueError(f"unknown verification case state: {self.initial_state}")
        if not self.left_head_rev and not self.trigger_rev_id:
            raise ValueError("a verification case requires a head or trigger revision")

    @property
    def case_key(self) -> str:
        head_revs = sorted(
            int(value) for value in (self.left_head_rev, self.right_head_rev) if value is not None
        )
        payload = {
            "case_type": _normalized(self.case_type),
            "scope": {str(k): str(v) for k, v in sorted(self.scope.items()) if v},
            "subject": _normalized(self.subject),
            "predicate": _normalized(self.predicate),
            "policy_version": str(self.policy_version),
        }
        if self.adjudication_fingerprint:
            payload["adjudication_fingerprint"] = str(self.adjudication_fingerprint)
        else:
            payload["head_rev_ids"] = head_revs
        return sha256_json(payload)


@dataclass(frozen=True)
class VerificationCase:
    case_id: str
    case_key: str
    case_type: str
    state: str
    priority: int
    scope: dict[str, str]
    subject: str | None
    predicate: str | None
    left_crystal_id: str | None
    left_head_rev: int | None
    right_crystal_id: str | None
    right_head_rev: int | None
    trigger_rev_id: int | None
    trigger_payload: dict[str, Any]
    policy_version: str
    evidence_round: int
    decision_input_hash: str | None
    attempts: int
    next_attempt_at: str | None
    lease_owner: str | None
    lease_until: str | None
    opened_rev_ids: list[int]
    result_rev_ids: list[int]
    result: dict[str, Any]
    last_error: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "VerificationCase":
        def load(name: str, default: Any) -> Any:
            try:
                value = json.loads(row[name] or "")
            except (TypeError, json.JSONDecodeError):
                return default
            return value

        return cls(
            case_id=row["case_id"],
            case_key=row["case_key"],
            case_type=row["case_type"],
            state=row["state"],
            priority=int(row["priority"]),
            scope=load("scope_json", {}),
            subject=row["subject"],
            predicate=row["predicate"],
            left_crystal_id=row["left_crystal_id"],
            left_head_rev=row["left_head_rev"],
            right_crystal_id=row["right_crystal_id"],
            right_head_rev=row["right_head_rev"],
            trigger_rev_id=row["trigger_rev_id"],
            trigger_payload=load("trigger_payload_json", {}),
            policy_version=row["policy_version"],
            evidence_round=int(row["evidence_round"]),
            decision_input_hash=row["decision_input_hash"],
            attempts=int(row["attempts"]),
            next_attempt_at=row["next_attempt_at"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            opened_rev_ids=[int(value) for value in load("opened_rev_ids_json", [])],
            result_rev_ids=[int(value) for value in load("result_rev_ids_json", [])],
            result=load("result_json", {}),
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class VerificationEvidence:
    evidence_id: int
    case_id: str
    collection_round: int
    source_kind: str
    source_ref: str
    observed_hash: str
    snapshot: dict[str, Any]
    recorded_at: str

    @classmethod
    def from_row(cls, row: Any) -> "VerificationEvidence":
        try:
            snapshot = json.loads(row["snapshot_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
        return cls(
            evidence_id=int(row["evidence_id"]),
            case_id=row["case_id"],
            collection_round=int(row["collection_round"]),
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            observed_hash=row["observed_hash"],
            snapshot=snapshot,
            recorded_at=row["recorded_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class VerificationDecision:
    decision: str
    confidence: float = 1.0
    rationale: str = ""
    reason_codes: list[str] = field(default_factory=list)
    validity: dict[str, Any] = field(default_factory=dict)
    repair: dict[str, Any] | None = None
    supported_claims: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationDecision":
        decision = cls(
            decision=str(value.get("decision") or ""),
            confidence=float(value.get("confidence", 0.0)),
            rationale=str(value.get("rationale") or ""),
            reason_codes=[str(item) for item in value.get("reason_codes") or []],
            validity=dict(value.get("validity") or {}),
            repair=dict(value["repair"]) if isinstance(value.get("repair"), dict) else None,
            supported_claims=[str(item) for item in value.get("supported_claims") or []],
            unsupported_claims=[str(item) for item in value.get("unsupported_claims") or []],
        )
        decision.validate()
        return decision

    def validate(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"unsupported verification decision: {self.decision}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("verification confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

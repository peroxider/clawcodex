"""Cost-effective structured LLM arbiter."""

from __future__ import annotations

import json
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.validity.models import (
    VerificationCase,
    VerificationDecision,
    VerificationEvidence,
)
from clawcodex_ext.latent_memory.server.lib.validity.prompts import (
    ARBITRATION_SCHEMA,
    SYSTEM_PROMPT,
)
from clawcodex_ext.latent_memory.server.token_usage import token_usage_tracker


class LLMArbiter:
    def __init__(self, llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]]) -> None:
        self._llm_fn = llm_fn

    def decide(
        self,
        case: VerificationCase,
        heads: list[dict[str, Any]],
        evidence: list[VerificationEvidence],
    ) -> VerificationDecision:
        heads_by_id = {
            str(head.get("crystal_id")): head for head in heads if head.get("crystal_id")
        }
        evidence_by_ref = {item.source_ref: item for item in evidence}
        sides: dict[str, dict[str, Any]] = {}
        for side, crystal_id in (
            ("left", case.left_crystal_id),
            ("right", case.right_crystal_id),
        ):
            head = heads_by_id.get(str(crystal_id or ""))
            if head is None:
                continue
            sides[side] = {
                "head": head,
                "evidence": [
                    evidence_by_ref[source_id].to_dict()
                    for source_id in head.get("source_ids") or []
                    if source_id in evidence_by_ref
                ],
            }
        payload = {
            "case": {
                "case_type": case.case_type,
                "subject": case.subject,
                "predicate": case.predicate,
                "scope": case.scope,
                "policy_version": case.policy_version,
            },
            "decision_semantics": {
                "confirm_left": "retain sides.left and supersede sides.right",
                "confirm_right": "retain sides.right and supersede sides.left",
                "coexist": "retain both sides.left and sides.right",
            },
            "sides": sides,
        }
        raw = self._llm_fn(
            SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ARBITRATION_SCHEMA,
        )
        response = raw.pop("_raw_response", None)
        if response is not None:
            token_usage_tracker.record_response(response, provider="validity")
        decision = VerificationDecision.from_dict(raw)
        if decision.decision == "confirm_right" and "right" not in sides:
            raise ValueError("confirm_right requires a right side")
        return decision

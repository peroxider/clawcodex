"""Quality admission and deterministic validation for crystallization candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.crystallization.models import (
    _clip_text,
    _display_text,
    asset_type_for_memory,
    find_context_dependent_references,
    find_relative_time_references,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.prompts import (
    CLUSTER_QUALITY_JSON_SCHEMA,
    CLUSTER_QUALITY_SYSTEM_PROMPT,
    CLUSTER_QUALITY_USER_TEMPLATE,
)


@dataclass(frozen=True)
class ClusterScreenResult:
    decision: str
    accepted_indices: tuple[int, ...]
    rejected_indices: tuple[int, ...]
    deferred_indices: tuple[int, ...]
    accepted_source_ids: tuple[str, ...]
    rejected_items: tuple[dict[str, str], ...]
    deferred_source_ids: tuple[str, ...]
    rationale: str
    min_required_items: int

    def audit_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "accepted_source_ids": list(self.accepted_source_ids),
            "rejected_items": [dict(item) for item in self.rejected_items],
            "deferred_source_ids": list(self.deferred_source_ids),
            "rationale": self.rationale,
            "min_required_items": self.min_required_items,
        }


class ClusterQualityFilter:
    def __init__(
        self,
        llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        *,
        enabled: bool,
        max_fact_chars: int,
        max_crystal_chars: int,
        min_crystal_confidence: float,
    ) -> None:
        self._llm_fn = llm_fn
        self._enabled = enabled
        self._max_fact_chars = max_fact_chars
        self._max_crystal_chars = max_crystal_chars
        self._min_crystal_confidence = max(0.0, min(1.0, float(min_crystal_confidence)))

    @staticmethod
    def _fact_observed_at(fact: dict[str, Any]) -> str:
        metadata = fact.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        candidates = (
            metadata.get("observation_date"),
            metadata.get("timestamp"),
            fact.get("observation_date"),
            fact.get("timestamp"),
            fact.get("created_at"),
        )
        for value in candidates:
            if isinstance(value, (int, float)):
                timestamp = float(value)
                if timestamp > 100_000_000_000:
                    timestamp /= 1000
                try:
                    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                except (OverflowError, OSError, ValueError):
                    continue
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def fact_records(self, facts: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "source_id": str(fact.get("id") or ""),
                "text": _clip_text(fact.get("memory", ""), self._max_fact_chars),
                "observed_at": self._fact_observed_at(fact),
            }
            for fact in facts
        ]

    def fact_context(self, facts: list[dict[str, Any]]) -> tuple[str, list[str]]:
        records = self.fact_records(facts)
        return (
            json.dumps(records, ensure_ascii=False, indent=2),
            [json.dumps(record, ensure_ascii=False) for record in records],
        )

    def screen(
        self,
        all_raw_facts: list[dict[str, Any]],
        raw_indices: list[int],
        existing_crystals: list[dict[str, Any]],
        *,
        min_required_items: int,
    ) -> ClusterScreenResult:
        raw_facts = [all_raw_facts[index] for index in raw_indices]
        raw_ids = [str(fact.get("id") or "") for fact in raw_facts]
        if not self._enabled:
            return ClusterScreenResult(
                "crystallize",
                tuple(raw_indices),
                (),
                (),
                tuple(raw_ids),
                (),
                (),
                "quality filter disabled",
                min_required_items,
            )

        crystal_context = []
        for crystal in existing_crystals:
            metadata = crystal.get("metadata", {}) or {}
            if not isinstance(metadata, dict):
                metadata = {}
            crystal_context.append(
                {
                    "crystal_id": str(crystal.get("id") or ""),
                    "text": _clip_text(_display_text(crystal), self._max_crystal_chars),
                    "asset_type": asset_type_for_memory(crystal),
                    "asset": metadata.get("asset", {}),
                }
            )

        result = self._llm_fn(
            CLUSTER_QUALITY_SYSTEM_PROMPT,
            CLUSTER_QUALITY_USER_TEMPLATE.format(
                json.dumps(crystal_context, ensure_ascii=False, indent=2),
                json.dumps(self.fact_records(raw_facts), ensure_ascii=False, indent=2),
                min_required_items,
            ),
            CLUSTER_QUALITY_JSON_SCHEMA,
        )
        if not isinstance(result, dict):
            raise ValueError("cluster quality screen returned a non-object result")
        decision = str(result.get("cluster_decision") or "").strip().lower()
        if decision not in {"crystallize", "defer", "reject"}:
            raise ValueError(f"invalid cluster quality decision: {decision or '(empty)'}")

        accepted_values = result.get("accepted_source_ids", [])
        rejected_values = result.get("rejected_items", [])
        if not isinstance(accepted_values, list):
            raise ValueError("cluster quality accepted_source_ids must be a list")
        if not isinstance(rejected_values, list):
            raise ValueError("cluster quality rejected_items must be a list")

        index_by_id = {source_id: index for source_id, index in zip(raw_ids, raw_indices)}
        valid_ids = set(index_by_id)
        accepted_ids = {
            str(source_id) for source_id in accepted_values if str(source_id) in valid_ids
        }
        rejected_by_id: dict[str, dict[str, str]] = {}
        for item in rejected_values:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "")
            if source_id in valid_ids:
                rejected_by_id[source_id] = {
                    "source_id": source_id,
                    "reason_code": str(item.get("reason_code") or "other"),
                    "reason": str(item.get("reason") or "Rejected by quality screen"),
                }

        rationale = str(result.get("rationale") or "")
        if decision == "reject":
            for source_id in raw_ids:
                rejected_by_id.setdefault(
                    source_id,
                    {
                        "source_id": source_id,
                        "reason_code": "no_reusable_value",
                        "reason": rationale or "Cluster has no reusable value",
                    },
                )
            accepted_ids.clear()

        accepted_ids.difference_update(rejected_by_id)
        deferred_ids = valid_ids - accepted_ids - set(rejected_by_id)
        if decision == "defer" or (
            decision == "crystallize" and len(accepted_ids) < min_required_items
        ):
            decision = "defer"
            deferred_ids.update(accepted_ids)
            accepted_ids.clear()

        return ClusterScreenResult(
            decision,
            tuple(index_by_id[source_id] for source_id in raw_ids if source_id in accepted_ids),
            tuple(index_by_id[source_id] for source_id in raw_ids if source_id in rejected_by_id),
            tuple(index_by_id[source_id] for source_id in raw_ids if source_id in deferred_ids),
            tuple(source_id for source_id in raw_ids if source_id in accepted_ids),
            tuple(
                rejected_by_id[source_id] for source_id in raw_ids if source_id in rejected_by_id
            ),
            tuple(source_id for source_id in raw_ids if source_id in deferred_ids),
            rationale,
            min_required_items,
        )

    def validate_candidate(self, merged: dict[str, Any]) -> None:
        confidence = float(merged.get("confidence", 0.0) or 0.0)
        if confidence < self._min_crystal_confidence:
            raise ValueError(
                f"crystal confidence {confidence:.3f} is below minimum "
                f"{self._min_crystal_confidence:.3f}"
            )
        candidate_fields = {
            "text": merged.get("text", ""),
            "facets": merged.get("facets", {}),
            "asset": merged.get("asset", {}),
        }
        context_references = find_context_dependent_references(candidate_fields)
        if context_references:
            raise ValueError(
                "crystal contains context-dependent references: " + ", ".join(context_references)
            )
        relative_time = find_relative_time_references(candidate_fields)
        if relative_time:
            raise ValueError(
                "crystal contains relative time references: " + ", ".join(relative_time)
            )

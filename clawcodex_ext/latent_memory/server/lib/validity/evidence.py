"""Solidify backend evidence into bounded, reproducible snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.validity.models import sha256_json


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


class EvidenceCollector:
    def __init__(
        self,
        backend_accessor: Callable[[], Any],
        *,
        max_per_crystal: int = 8,
        max_chars: int = 12000,
    ) -> None:
        self._backend_accessor = backend_accessor
        self._max_per_crystal = max(1, int(max_per_crystal))
        self._max_chars = max(100, int(max_chars))

    def collect(self, source_ids: list[str]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(str(value) for value in source_ids if value))[
            : self._max_per_crystal
        ]
        if not ids:
            return []
        records = self._backend_accessor().get_memories_by_ids(ids)
        by_id = {
            str(record.get("id")): record
            for record in records
            if isinstance(record, dict) and record.get("id")
        }
        evidence: list[dict[str, Any]] = []
        for source_id in ids:
            record = by_id.get(source_id)
            if record is None:
                snapshot = {"id": source_id, "missing": True}
                kind = "missing_raw"
            else:
                snapshot = _json_safe(record)
                text = str(snapshot.get("memory") or snapshot.get("data") or "")
                if len(text) > self._max_chars:
                    snapshot = dict(snapshot)
                    if "memory" in snapshot:
                        snapshot["memory"] = text[: self._max_chars]
                    elif "data" in snapshot:
                        snapshot["data"] = text[: self._max_chars]
                    snapshot["truncated"] = True
                kind = "raw"
            evidence.append(
                {
                    "source_kind": kind,
                    "source_ref": source_id,
                    "observed_hash": sha256_json(snapshot),
                    "snapshot": snapshot,
                }
            )
        return evidence

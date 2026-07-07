"""Method coverage evaluation for F-153 — golden set hit rate + metrics.

Phase 5 of the Method Library Growth & Governance feature.

Key metrics calculated:

- ``hit_rate`` — proportion of golden-set goals whose decomposition plan
  includes the expected method pattern.
- ``top_method_usage`` — top 10 methods by reference count (from
  ``lkb_method_referenced`` audit events or field-layer data).
- ``long_tail_methods`` — methods referenced fewer than 3 times.
- ``dead_methods`` — methods in ``approved`` status with zero references.

Dual-source cross-validation
----------------------------
Metrics are computed from TWO independent sources:

* **Field layer** — ``DecompositionPlan.method_references`` (authoritative).
* **Event layer** — audit events of type ``"lkb_method_referenced"``.

When the two sources disagree, a ``coverage_integrity_warning`` is recorded.
Field-layer values are authoritative for the report.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from clawcodex_ext.logical_kanban.method_library import (
    get_all_methods,
    get_method,
    list_methods,
)


class MethodCoverageEvaluator:
    """Evaluate method library coverage against a golden set.

    The evaluator operates in two modes:

    1. **Live mode** — the caller provides pre-computed reference counts
       and hit data (typically collected during a test suite run).
    2. **Stub mode** — :meth:`evaluate` accepts a simple list of goal
       strings and optionally a pre-computed stats dictionary.

    Parameters
    ----------
    method_reference_counts : dict[str, int] | None
        Pre-computed per-method reference counts (from field or event layer).
        If ``None``, the evaluator defaults to zero for all methods.
    method_hits : set[str] | None
        Set of method_ids that were *hit* by a golden-set goal (i.e.
        at least one decomposition plan produced a method reference that
        matched the expected pattern for some goal).  If ``None``, all
        methods are considered unhit.
    """

    def __init__(
        self,
        method_reference_counts: dict[str, int] | None = None,
        method_hits: set[str] | None = None,
    ) -> None:
        self._reference_counts = method_reference_counts or {}
        self._method_hits = method_hits or set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        golden_set: list[dict[str, Any]],
        *,
        field_references: list[tuple[str, str]] | None = None,
        event_references: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Run coverage evaluation against the golden set.

        Parameters
        ----------
        golden_set:
            List of golden-set entries.  Each entry has at least
            ``goal`` and ``expected_method_pattern`` keys.  Extra keys
            (``description``, ``tags``) are ignored.
        field_references:
            Optional list of ``(method_id, plan_run_id)`` tuples captured
            from the field layer (``DecompositionPlan.method_references``).
        event_references:
            Optional list of ``(method_id, plan_run_id)`` tuples captured
            from the event layer (``lkb_method_referenced`` audit events).

        Returns
        -------
        dict
            Coverage report with keys:
            ``golden_set_size``, ``hit_rate``, ``top_method_usage``,
            ``long_tail_methods``, ``dead_methods``,
            ``coverage_integrity_warnings``.
        """
        golden_set_size = len(golden_set)

        # ---- Compute hit rate from field-layer references ----
        field_counts: Counter[str] = Counter()
        event_counts: Counter[str] = Counter()
        field_hit_patterns: set[str] = set()
        event_hit_patterns: set[str] = set()

        if field_references:
            for mid, _run_id in field_references:
                field_counts[mid] += 1
                method = get_method(mid)
                if method:
                    field_hit_patterns.add(method.pattern)

        if event_references:
            for mid, _run_id in event_references:
                event_counts[mid] += 1
                method = get_method(mid)
                if method:
                    event_hit_patterns.add(method.pattern)

        # ---------- Dual-source cross-validation ----------
        warnings: list[str] = []

        if field_references is not None and event_references is not None:
            field_mids = {mid for mid, _ in field_references}
            event_mids = {mid for mid, _ in event_references}
            only_field = field_mids - event_mids
            only_event = event_mids - field_mids
            if only_field:
                warnings.append(
                    f"Field layer has method refs missing from event layer: "
                    f"{sorted(only_field)}"
                )
            if only_event:
                warnings.append(
                    f"Event layer has method refs missing from field layer: "
                    f"{sorted(only_event)}"
                )

        # ---------- Golden-set hit rate ----------
        hit_count = 0
        for entry in golden_set:
            expected_pattern = entry.get("expected_method_pattern", "")
            if not expected_pattern:
                continue
            # A hit occurs if any field-layer reference pattern matches
            if expected_pattern in field_hit_patterns:
                hit_count += 1

        hit_rate = hit_count / golden_set_size if golden_set_size > 0 else 0.0

        # ---------- Aggregate counts (field-layer authoritative) ----------
        aggregated: Counter[str] = Counter()
        aggregated.update(field_counts)
        # Fill in from event layer for methods unseen in the field layer
        for mid, cnt in event_counts.items():
            if mid not in aggregated:
                aggregated[mid] = cnt

        # Top 10
        top_10 = aggregated.most_common(10)
        top_method_usage = dict(top_10)

        # Long tail: referenced but < 3 times
        long_tail = sum(1 for c in aggregated.values() if c < 3)
        long_tail_methods = long_tail

        # Dead: approved but zero references
        dead_methods = 0
        all_approved = list_methods(status="approved")
        for m in all_approved:
            if m.method_id not in aggregated:
                dead_methods += 1

        return {
            "golden_set_size": golden_set_size,
            "hit_rate": round(hit_rate, 4),
            "top_method_usage": top_method_usage,
            "long_tail_methods": long_tail_methods,
            "dead_methods": dead_methods,
            "coverage_integrity_warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Convenience: load golden set from file
    # ------------------------------------------------------------------

    @staticmethod
    def load_golden_set(path: Path) -> list[dict[str, Any]]:
        """Load a golden-set JSON file and return its entries.

        The file should be a JSON array of objects with at least
        a ``goal`` and ``expected_method_pattern`` key.
        """
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            entries = raw.get("goals") or raw.get("entries") or raw.get("goldenSet")
            if isinstance(entries, list):
                return entries
        raise ValueError(
            f"Golden-set file {path} must be a JSON array or dict with "
            f"'goals' / 'entries' / 'goldenSet' list"
        )

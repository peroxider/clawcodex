"""ExperimentAssignment — stable hash-based variant assignment (P119-E).

Uses SHA-256 hashing of ``(experiment_id, session_id)`` to produce a
deterministic, sticky assignment — the same session always maps to the
same variant for the lifetime of the experiment.
"""

from __future__ import annotations

import hashlib

from .variants import VariantManager

__all__ = ["ExperimentAssignment"]


class ExperimentAssignment:
    """Stable hash-based variant assignment backed by a VariantManager.

    Usage::

        manager = VariantManager()
        manager.register("intro_v2", my_provider)
        assignment = ExperimentAssignment(manager)
        variant = assignment.assign("intro_v2", session_id="abc", query_source="main")
        # Same (experiment_id, session_id) always returns the same variant.
    """

    def __init__(self, manager: VariantManager) -> None:
        self._manager = manager

    def assign(
        self,
        experiment_id: str,
        session_id: str,
        query_source: str = "main",
    ) -> str:
        provider = self._manager._providers.get(experiment_id)
        if provider is None:
            return "control"

        variants = provider.list_variants()
        if not variants:
            return "control"

        key = f"{experiment_id}:{session_id}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % len(variants)
        return variants[bucket]
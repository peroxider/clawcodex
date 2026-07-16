"""VariantManager — manages prompt variant providers (P119-E).

A thin registry that maps experiment IDs to VariantProvider instances.
Resolving an unregistered experiment always returns ``"control"``.
"""

from __future__ import annotations

from .capabilities import VariantProvider

__all__ = ["VariantManager"]


class VariantManager:
    """Registry of VariantProvider instances keyed by experiment ID.

    Usage::

        manager = VariantManager()
        manager.register("intro_v2", my_provider)
        variant = manager.resolve("intro_v2", session_id="abc", query_source="main")
        # → "control" or "treatment_A" depending on provider
    """

    def __init__(self) -> None:
        self._providers: dict[str, VariantProvider] = {}

    def register(self, experiment_id: str, provider: VariantProvider) -> None:
        self._providers[experiment_id] = provider

    def resolve(
        self,
        experiment_id: str,
        session_id: str,
        query_source: str = "main",
    ) -> str:
        provider = self._providers.get(experiment_id)
        if provider is None:
            return "control"
        return provider.assign(session_id=session_id, query_source=query_source)

    def list_experiments(self) -> list[str]:
        return list(self._providers.keys())

    def unregister(self, experiment_id: str) -> None:
        self._providers.pop(experiment_id, None)
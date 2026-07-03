"""Failure recovery helpers for LLM-driven ultraplan generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerRecoveryHint:
    message: str
    can_retry: bool = True
    manual_mode_suggested: bool = True


def recovery_hint(error: Exception) -> PlannerRecoveryHint:
    return PlannerRecoveryHint(
        message=(
            "LLM planning failed. Try simplifying the goal or provide a manual "
            f"plan JSON. Last error: {error}"
        )
    )

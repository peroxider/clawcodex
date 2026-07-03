"""Models and display helpers for Intent Forecast."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ForecastSuggestion:
    id: str
    title: str
    prompt: str
    reason: str = ""
    confidence: float = 0.0
    source_refs: list[str] | None = None

    def refs(self) -> list[str]:
        return list(self.source_refs or [])


@dataclass(frozen=True)
class ForecastResult:
    generated: bool
    suggestions: list[ForecastSuggestion]
    reason: str = ""
    fingerprint: str = ""


def format_forecast_for_display(result: ForecastResult) -> str:
    if not result.generated or not result.suggestions:
        return result.reason or "Forecast has no suggestions right now."
    lines = ["Forecast"]
    for idx, suggestion in enumerate(result.suggestions, 1):
        lines.append("")
        lines.append(f"{idx}. {suggestion.title}")
        if suggestion.reason:
            lines.append(f"   {suggestion.reason}")
    lines.append("")
    lines.append("Use /forecast accept <number> to submit a suggestion, or /forecast dismiss.")
    return "\n".join(lines).strip()


def parse_selection(raw: str, suggestions: list[ForecastSuggestion]) -> ForecastSuggestion | None:
    token = raw.strip()
    if not token:
        token = "1"
    try:
        idx = int(token)
        if 1 <= idx <= len(suggestions):
            return suggestions[idx - 1]
    except ValueError:
        pass
    for suggestion in suggestions:
        if suggestion.id == token:
            return suggestion
    return None


def result_to_dict(result: ForecastResult) -> dict[str, Any]:
    return {
        "generated": result.generated,
        "reason": result.reason,
        "fingerprint": result.fingerprint,
        "suggestions": [
            {
                "id": s.id,
                "title": s.title,
                "prompt": s.prompt,
                "reason": s.reason,
                "confidence": s.confidence,
                "source_refs": s.refs(),
            }
            for s in result.suggestions
        ],
    }

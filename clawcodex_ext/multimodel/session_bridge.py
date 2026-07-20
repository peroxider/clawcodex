"""In-memory multi-model audit and cost accounting bridge."""

from __future__ import annotations

from dataclasses import dataclass, field

from clawcodex_ext.capabilities.multimodel_protocol import AggregatedOutput, MultiModelResult


@dataclass
class SessionBridge:
    """Retain per-slot outcomes for UI inspection and downstream persistence."""

    calls: list[list[MultiModelResult]] = field(default_factory=list)
    aggregated: list[AggregatedOutput | None] = field(default_factory=list)

    def record(self, results: list[MultiModelResult], output: AggregatedOutput | None = None) -> None:
        self.calls.append(list(results))
        self.aggregated.append(output)

    @property
    def total_tokens(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for call in self.calls:
            for result in call:
                for key, value in result.tokens.items():
                    if isinstance(value, int):
                        totals[key] = totals.get(key, 0) + value
        return totals

    @property
    def total_duration_ms(self) -> int:
        return sum(result.duration_ms for call in self.calls for result in call)

"""Protocol definitions for the prompt_lab subsystem (P119-E).

VariantProvider — assigns sessions to variants and retrieves variant content.
MetricsSink    — records prompt experiment events for analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["MetricsSink", "PromptEvent", "VariantProvider"]


class VariantProvider(Protocol):
    """Assigns a session to a variant and returns variant-specific content.

    Implementations can use hash-based assignment, remote feature flag
    services, or static configuration files.
    """

    def assign(self, session_id: str, query_source: str) -> str: ...

    def content_for(self, variant: str) -> str: ...

    def list_variants(self) -> list[str]: ...


@dataclass
class PromptEvent:
    """A single prompt experiment event for metrics recording.

    Captures metadata about which variant was used for a given session
    query, plus a SHA-256 fingerprint of the effective prompt for
    correlation with ``dump_effective_system_prompt`` output.
    """

    timestamp: str
    experiment_id: str
    variant: str
    session_id: str
    query_source: str
    prompt_sha256: str = ""
    section_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class MetricsSink(Protocol):
    """Records prompt experiment events.

    Implementations can write to NDJSON files, OTLP endpoints, Prometheus
    pushgateway, etc.
    """

    def record(self, event: PromptEvent) -> None: ...
"""NDJSONMetricsSink — writes prompt lab events to NDJSON files (P119-E).

Each event is appended as a single JSON line to a date-stamped file under
``output_dir``.  Default: ``.reports/prompt_lab/YYYY-MM-DD.ndjson``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ..capabilities import MetricsSink, PromptEvent

__all__ = ["NDJSONMetricsSink"]

_DEFAULT_OUTPUT_DIR = ".reports/prompt_lab"


class NDJSONMetricsSink:
    """A :class:`MetricsSink` that writes events to date-stamped NDJSON files.

    Usage::

        sink = NDJSONMetricsSink()
        sink.record(PromptEvent(
            timestamp="2026-07-14T10:00:00Z",
            experiment_id="intro_v2",
            variant="treatment_A",
            session_id="abc",
            query_source="main",
        ))
    """

    def __init__(self, output_dir: str | None = None) -> None:
        self._output_dir = output_dir or _DEFAULT_OUTPUT_DIR

    def record(self, event: PromptEvent) -> None:
        os.makedirs(self._output_dir, exist_ok=True)

        date_str = event.timestamp[:10]
        file_path = os.path.join(self._output_dir, f"{date_str}.ndjson")

        line = json.dumps(
            {
                "timestamp": event.timestamp,
                "experiment_id": event.experiment_id,
                "variant": event.variant,
                "session_id": event.session_id,
                "query_source": event.query_source,
                "prompt_sha256": event.prompt_sha256,
                "section_count": event.section_count,
                "metadata": event.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
"""prompt_lab — A/B variant framework skeleton.

Layer 2 subsystem providing prompt variant management, experiment assignment,
and metrics sinking for self-iteration optimization.  Zero third-party
dependencies; pure stdlib.
"""

from __future__ import annotations

from .capabilities import MetricsSink, VariantProvider
from .experiments import ExperimentAssignment
from .sinks.ndjson import NDJSONMetricsSink
from .variants import VariantManager

__all__ = [
    "ExperimentAssignment",
    "MetricsSink",
    "NDJSONMetricsSink",
    "VariantManager",
    "VariantProvider",
]
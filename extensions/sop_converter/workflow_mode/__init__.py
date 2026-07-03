"""F-50-A/B workflow mode package."""

from .discriminator import WorkflowDiscriminator
from .models import DiscriminationResult, HeuristicMatch, THRESHOLD_FWA, THRESHOLD_SDK
from .pipeline import discriminate_and_extract, extract_workflow
from .scan_context import SourceScanContext

__all__ = [
    "WorkflowDiscriminator",
    "DiscriminationResult",
    "HeuristicMatch",
    "THRESHOLD_SDK",
    "THRESHOLD_FWA",
    "SourceScanContext",
    "extract_workflow",
    "discriminate_and_extract",
]

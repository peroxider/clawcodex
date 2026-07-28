"""Compatibility re-exports for the production PatternExtractor implementation.

New code should import from
``extensions.sop_converter.workflow_mode.extractors.pattern``.
"""

from extensions.sop_converter.workflow_mode.extractors.pattern import (
    ARC_COMPAT_CONFIG,
    PatternExtractor,
    PipelineConfig,
    _resolve_pipeline_dir,
)

__all__ = [
    "ARC_COMPAT_CONFIG",
    "PatternExtractor",
    "PipelineConfig",
    "_resolve_pipeline_dir",
]

"""Compatibility namespace for the production SDK pattern extractor.

The implementation lives in
``extensions.sop_converter.workflow_mode.extractors.pattern``. This import
path remains available for users of the original reference example.

用法:
    from examples.sdk_extractor.pattern_extractor import PatternExtractor, PipelineConfig

    config = PipelineConfig(
        name="my-sdk",
        pipeline_marker_files=[("stages.py", "pipeline"), ("contracts.py", "pipeline")],
    )
    extractor = PatternExtractor(config=config, mode="fwa")
    graph = extractor.extract("/path/to/project")
"""

from .pattern_extractor import PatternExtractor, PipelineConfig

__all__ = ["PatternExtractor", "PipelineConfig"]

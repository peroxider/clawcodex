"""
此文件已被废弃 — ArcExtractor 已重构为配置驱动的参考设计示例。

请参见 ``examples/sdk-extractor/`` 下的 ``PatternExtractor`` 和
``PipelineConfig``，它们是 ``ArcExtractor`` 的解耦替代品。

旧 ``ArcExtractor`` 将 AutoResearchClaw 的所有约定硬编码在类中，
无法复用于其他 SDK/项目。新的 ``PatternExtractor`` 通过 ``PipelineConfig``
将所有 SDK 约定参数化，可适配任意项目。

迁移指南:
    from examples.sdk_extractor import PatternExtractor, PipelineConfig

    config = PipelineConfig(
        name="my-sdk",
        pipeline_marker_files=[("stages.py", "pipeline")],
    )
    extractor = PatternExtractor(config=config, mode="fwa")
    graph = extractor.extract("/path/to/project")

需要兼容旧 ``ArcExtractor`` 行为的项目，请使用 ``ARC_COMPAT_CONFIG``:

    from examples.sdk_extractor.pattern_extractor import ARC_COMPAT_CONFIG
    config = ARC_COMPAT_CONFIG  # 保留旧 AutoResearchClaw 路径/变量名约定
"""

from __future__ import annotations

import warnings
from pathlib import Path

from examples.sdk_extractor import PatternExtractor, PipelineConfig
from examples.sdk_extractor.pattern_extractor import ARC_COMPAT_CONFIG

warnings.warn(
    "ArcExtractor 已废弃，请使用 examples.sdk_extractor.PatternExtractor",
    DeprecationWarning,
    stacklevel=2,
)


def resolve_arc_pipeline_dir(source_dir: Path) -> Path | None:
    """兼容旧 ArcExtractor 的辅助函数 — 使用 ARC_COMPAT_CONFIG 查找 pipeline 目录。"""
    from examples.sdk_extractor.pattern_extractor import _resolve_pipeline_dir
    return _resolve_pipeline_dir(source_dir, ARC_COMPAT_CONFIG)


class ArcExtractor(PatternExtractor):
    """兼容旧 ArcExtractor 行为的包装类。

    内部使用 ``ARC_COMPAT_CONFIG`` 保持旧 AutoResearchClaw 的路径/变量名约定。
    建议新代码直接使用 ``PatternExtractor(config=...)``。
    """
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("config", ARC_COMPAT_CONFIG)
        super().__init__(*args, **kwargs)


__all__ = ["ArcExtractor", "resolve_arc_pipeline_dir"]
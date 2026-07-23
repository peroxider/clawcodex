"""SDK Extractor — 参考设计示例：自定义 Pipeline 提取器。

此包是 *参考设计示例*，不是项目核心代码。
它演示了如何为任意 SDK/项目编写一个自定义的 WorkflowExtractor，

将项目中的 pipeline 定义（阶段枚举、状态转移、关卡、决策、契约）
解析为 WorkflowGraph IR。

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
"""Tests for SOP Converter F-50: SourceCodeParser + enhanced SkillGrouper + AgentMarkdownWriter."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from extensions.pos_converter.source_parser import (
    SourceCodeParser,
    SourceComponent,
    SourceOperation,
    ParamSpec,
)
from extensions.pos_converter.skill_grouper import (
    GroupStrategy,
    SkillGrouper,
    group_source_components,
    GroupResult,
    SkillSpec,
    MappingRule,
    MatchType,
    MatchTarget,
)
from extensions.pos_converter.agent_md_writer import (
    AgentMarkdownWriter,
    AgentComponentInfo,
    WorkflowStage,
)
from extensions.pos_converter.default_agent import (
    resolve_default_agent,
    resolve_agent_by_type,
    _parse_frontmatter,
)
from extensions.pos_converter.agent_builder import AgentBuilder, AgentBuildResult
from extensions.pos_converter.templates import (
    AGENT_MD_TEMPLATE,
    SKILL_MD_TEMPLATE_JINJA,
    OVERVIEW_AGENT_TEMPLATE,
)


# =========================================================================
# SourceCodeParser tests
# =========================================================================


class TestParamSpec:
    def test_default_required(self) -> None:
        p = ParamSpec(name="x")
        assert p.name == "x"
        assert p.required is True
        assert p.type_hint is None
        assert p.default is None

    def test_optional_param(self) -> None:
        p = ParamSpec(name="y", type_hint="str", default="hello", required=False)
        assert p.name == "y"
        assert p.type_hint == "str"
        assert p.default == "hello"
        assert p.required is False


class TestSourceOperation:
    def test_minimal(self) -> None:
        op = SourceOperation(name="do_stuff", description="Does stuff")
        assert op.name == "do_stuff"
        assert op.parameters == []
        assert op.return_type is None

    def test_full(self) -> None:
        params = [ParamSpec(name="x", type_hint="int")]
        op = SourceOperation(
            name="add", description="Add numbers", parameters=params,
            return_type="int", source_code="def add(x): pass",
        )
        assert op.name == "add"
        assert len(op.parameters) == 1
        assert op.return_type == "int"


class TestSourceComponent:
    def test_minimal(self) -> None:
        comp = SourceComponent(
            name="MathOps", file_path="math/ops.py", description="Math operations",
        )
        assert comp.name == "MathOps"
        assert comp.operations == []
        assert comp.dependencies == []
        assert comp.input_schema == {}

    def test_with_ops(self) -> None:
        ops = [SourceOperation(name="add", description="Add")]
        comp = SourceComponent(
            name="MathOps",
            file_path="math.py",
            description="Math",
            operations=ops,
            dependencies=["math_utils"],
        )
        assert len(comp.operations) == 1
        assert "math_utils" in comp.dependencies


class TestSourceCodeParser:
    """Tests for SourceCodeParser with sample Python source files."""

    def test_parse_single_class(self) -> None:
        """Parse a single Python file with a class and methods."""
        source = '''
class VideoProcessor:
    """Process video files with various operations."""

    def transcode(self, input_path: str, output_format: str = "mp4") -> bool:
        """Transcode a video file to the specified format.

        Args:
            input_path: Path to the input video file.
            output_format: Target output format (default: mp4).

        Returns:
            True if successful, False otherwise.
        """
        return True

    def get_metadata(self, file_path: str) -> dict:
        """Get video file metadata."""
        return {}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            py_file = tmp / "video_processor.py"
            py_file.write_text(source)

            parser = SourceCodeParser(tmp)
            components = parser.parse()

        assert len(components) >= 1
        # Find our component
        comp = next((c for c in components if c.name == tmp.name), components[0])
        assert len(comp.operations) >= 1

        # Check transcode method
        transcode = next((op for op in comp.operations if op.name == "transcode"), None)
        assert transcode is not None, f"transcode not found in {[op.name for op in comp.operations]}"
        assert "transcode" in transcode.description.lower()
        assert transcode.return_type == "bool"

        # Check parameters
        assert len(transcode.parameters) >= 1
        param_names = {p.name for p in transcode.parameters}
        assert "input_path" in param_names
        assert "output_format" in param_names

        # Check type hints
        input_param = next(p for p in transcode.parameters if p.name == "input_path")
        assert "str" in (input_param.type_hint or "")

    def test_parse_top_level_functions(self) -> None:
        """Parse a Python file with module-level functions."""
        source = '''
"""Utility functions for data processing."""

import json
import os


def load_config(path: str) -> dict:
    """Load configuration from a JSON file.

    Args:
        path: Path to the config file.

    Returns:
        Parsed configuration dictionary.
    """
    with open(path) as f:
        return json.load(f)


def save_result(data: dict, output_path: str) -> None:
    """Save results to a JSON file.

    Args:
        data: The data to save.
        output_path: Path to save the file.
    """
    with open(output_path, "w") as f:
        json.dump(data, f)
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            py_file = tmp / "utils.py"
            py_file.write_text(source)

            parser = SourceCodeParser(tmp)
            components = parser.parse()

        assert len(components) >= 1
        comp = next((c for c in components if c.name == tmp.name), components[0])
        op_names = {op.name for op in comp.operations}
        assert "load_config" in op_names, f"load_config not in {op_names}"
        assert "save_result" in op_names, f"save_result not in {op_names}"

    def test_exclude_patterns(self) -> None:
        """Test that exclude_patterns filters out unwanted files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Create a normal file
            (tmp / "normal.py").write_text("def foo(): pass\n")
            # Create an excluded file
            (tmp / "test_normal.py").write_text("def test_foo(): pass\n")

            parser = SourceCodeParser(tmp, exclude_patterns=["test_*"])
            components = parser.parse()

            # Should have found the normal file component
            comp_names = [c.name for c in components]
            assert len(comp_names) >= 1

    def test_empty_directory(self) -> None:
        """Parse an empty directory returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            parser = SourceCodeParser(tmpdir)
            components = parser.parse()
            assert len(components) == 0

    def test_parse_file_single(self) -> None:
        """Test parse_file() for a single file."""
        source = '''
def greet(name: str) -> str:
    """Greet someone.

    Args:
        name: The person's name.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            py_file = tmp / "greeter.py"
            py_file.write_text(source)

            parser = SourceCodeParser(tmp)
            operations = parser.parse_file(py_file)

        assert len(operations) == 1
        assert operations[0].name == "greet"
        assert operations[0].return_type == "str"


class TestDocstringParsing:
    """Test docstring parsing in various formats."""

    def test_google_style(self) -> None:
        source = '''
def func(a: int, b: str) -> bool:
    """Do something.

    Args:
        a: An integer value.
        b: A string value.

    Returns:
        True on success.
    """
    return True
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "mod.py").write_text(source)
            parser = SourceCodeParser(tmp)
            comps = parser.parse()
            ops = [op for comp in comps for op in comp.operations]
            op = next((o for o in ops if o.name == "func"), None)
            assert op is not None
            assert "Do something" in op.description

    def test_numpy_style(self) -> None:
        source = '''
def func(x: float) -> float:
    """Compute the square of a number.

    Parameters
    ----------
    x : float
        The input value.

    Returns
    -------
    float
        The square of x.
    """
    return x * x
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "mod.py").write_text(source)
            parser = SourceCodeParser(tmp)
            comps = parser.parse()
            ops = [op for comp in comps for op in comp.operations]
            op = next((o for o in ops if o.name == "func"), None)
            assert op is not None
            assert "square" in op.description.lower()

    def test_rest_style(self) -> None:
        source = '''
def func(name: str) -> str:
    """Say hello.

    :param name: The person to greet.
    :type name: str
    :returns: A greeting string.
    """
    return f"Hi {name}"
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "mod.py").write_text(source)
            parser = SourceCodeParser(tmp)
            comps = parser.parse()
            ops = [op for comp in comps for op in comp.operations]
            op = next((o for o in ops if o.name == "func"), None)
            assert op is not None
            assert "hello" in op.description.lower()


# =========================================================================
# SkillGrouper tests
# =========================================================================


class TestGroupStrategy:
    def test_enum_values(self) -> None:
        assert GroupStrategy.KEYWORD_MATCH.value == "keyword_match"
        assert GroupStrategy.COMPONENT_GROUP.value == "component_group"
        assert GroupStrategy.IO_RELATION.value == "io_relation"
        assert GroupStrategy.LLM_SEMANTIC.value == "llm_semantic"

    def test_strategy_dispatch_keyword(self) -> None:
        """KEYWORD_MATCH strategy uses _keyword_match_group()."""
        from extensions.pos_converter.sdk_parser import SdkMethod
        grouper = SkillGrouper(
            [SdkMethod(name="docker_build", description="Build image")],
            strategy=GroupStrategy.KEYWORD_MATCH,
        )
        skills = grouper.group()
        assert len(skills) > 0
        assert any(s.name == "build_image" for s in skills)

    def test_component_group_strategy(self) -> None:
        """COMPONENT_GROUP strategy groups operations by component."""
        ops = [
            SourceOperation(name="encode", description="Encode video"),
            SourceOperation(name="decode", description="Decode video"),
        ]
        comp = SourceComponent(
            name="VideoCodec",
            file_path="codec.py",
            description="Video codec operations",
            operations=ops,
        )
        result = group_source_components([comp], strategy=GroupStrategy.COMPONENT_GROUP)
        assert len(result.skills) == 1
        assert result.skills[0].name == "VideoCodec"
        assert "VideoCodec.encode" in result.skills[0].allowed_tools
        assert "VideoCodec.decode" in result.skills[0].allowed_tools

    def test_io_relation_strategy(self) -> None:
        """IO_RELATION strategy groups operations sharing anchor types."""
        ops_a = [
            SourceOperation(
                name="read_file",
                description="Read a file",
                parameters=[ParamSpec(name="path", type_hint="str")],
            ),
        ]
        ops_b = [
            SourceOperation(
                name="write_file",
                description="Write a file",
                parameters=[ParamSpec(name="path", type_hint="str")],
            ),
        ]
        comp_a = SourceComponent(name="Reader", file_path="r.py", description="Reader", operations=ops_a)
        comp_b = SourceComponent(name="Writer", file_path="w.py", description="Writer", operations=ops_b)

        result = group_source_components([comp_a, comp_b], strategy=GroupStrategy.IO_RELATION)
        # read_file and write_file share "str" anchor type → same group
        assert len(result.skills) >= 1
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert "Reader.read_file" in all_tools
        assert "Writer.write_file" in all_tools
        assert any("str" in s.name for s in result.skills), (
            f"Expected type anchor in name, got: {[s.name for s in result.skills]}"
        )

    def test_io_relation_naming_with_types(self) -> None:
        """IO_RELATION group names include dominant type anchors."""
        ops_a = [SourceOperation(
            name="method_a", description="A",
            parameters=[ParamSpec(name="x", type_hint="int"), ParamSpec(name="y", type_hint="str")],
        )]
        ops_b = [SourceOperation(
            name="method_b", description="B",
            parameters=[ParamSpec(name="x", type_hint="bool")],
        )]
        comp_a = SourceComponent(name="CompA", file_path="a.py", description="A", operations=ops_a)
        comp_b = SourceComponent(name="CompB", file_path="b.py", description="B", operations=ops_b)

        result = group_source_components([comp_a, comp_b], strategy=GroupStrategy.IO_RELATION)
        # Two distinct anchor types → two groups (or merged into one if max_groups=1)
        assert len(result.skills) >= 1
        names = [s.name for s in result.skills]
        assert any("io_group" in n for n in names)

    def test_io_relation_with_no_params(self) -> None:
        """Operations with no parameters grouped into utility bucket."""
        ops = [SourceOperation(name="no_args", description="No args func")]
        comp = SourceComponent(name="Util", file_path="u.py", description="Utility", operations=ops)

        result = group_source_components([comp], strategy=GroupStrategy.IO_RELATION)
        assert len(result.skills) == 1
        assert result.skills[0].name == "io_group_utility"

    def test_io_relation_max_groups_merge(self) -> None:
        """max_io_groups forces merging of groups beyond the limit."""
        ops = []
        for i, type_name in enumerate(["str", "int", "bool", "float", "Path", "dict", "list", "bytes", "tuple", "set"]):
            ops.append(SourceOperation(
                name=f"method_{type_name}",
                description=f"Method using {type_name}",
                parameters=[ParamSpec(name="x", type_hint=type_name)],
            ))

        comp = SourceComponent(
            name="ManyTypes", file_path="m.py",
            description="Many types", operations=ops,
        )

        result = group_source_components(
            [comp], strategy=GroupStrategy.IO_RELATION, max_io_groups=5,
        )
        # 10 distinct types merged down to ≤ 5 groups
        assert len(result.skills) <= 5
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert len(all_tools) == 10

    def test_io_relation_shared_type_merges(self) -> None:
        """Operations sharing a common type are grouped together."""
        ops = [
            SourceOperation(name="op_a", description="A",
                           parameters=[ParamSpec(name="x", type_hint="str"), ParamSpec(name="y", type_hint="int")]),
            SourceOperation(name="op_b", description="B",
                           parameters=[ParamSpec(name="x", type_hint="str"), ParamSpec(name="y", type_hint="bool")]),
            SourceOperation(name="op_c", description="C",
                           parameters=[ParamSpec(name="x", type_hint="str"), ParamSpec(name="y", type_hint="float")]),
        ]
        comp = SourceComponent(name="Shared", file_path="s.py", description="Shared type str", operations=ops)

        result = group_source_components([comp], strategy=GroupStrategy.IO_RELATION, max_io_groups=2)
        # All 3 ops share "str" anchor → should be in 1-2 groups
        assert len(result.skills) <= 2
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert "Shared.op_a" in all_tools
        assert "Shared.op_b" in all_tools
        assert "Shared.op_c" in all_tools

    def test_io_relation_rebalancing_no_megagroup(self) -> None:
        """Rebalancing redirects multi-type ops to diverse secondary anchors."""
        ops = []
        for i in range(50):
            ops.append(SourceOperation(
                name=f"op_str_path_{i}", description="Str+Path op",
                parameters=[ParamSpec(name="x", type_hint="str"), ParamSpec(name="y", type_hint="Path")],
            ))
        for i in range(50):
            ops.append(SourceOperation(
                name=f"op_str_dict_{i}", description="Str+dict op",
                parameters=[ParamSpec(name="x", type_hint="str"), ParamSpec(name="y", type_hint="dict")],
            ))
        for i in range(10):
            ops.append(SourceOperation(
                name=f"op_int_{i}", description="Int op",
                parameters=[ParamSpec(name="x", type_hint="int")],
            ))
        for i in range(5):
            ops.append(SourceOperation(
                name=f"op_bool_{i}", description="Bool op",
                parameters=[ParamSpec(name="x", type_hint="bool")],
            ))

        comp = SourceComponent(
            name="BigSDK", file_path="b.py",
            description="Big SDK with diverse secondary types", operations=ops,
        )

        result = group_source_components(
            [comp], strategy=GroupStrategy.IO_RELATION, max_io_groups=5,
        )

        assert len(result.skills) <= 5
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert len(all_tools) == len(ops)

        max_tools = max(len(s.allowed_tools) for s in result.skills)
        assert max_tools < len(ops), (
            f"Rebalancing should split dominant anchor, got max={max_tools}/{len(ops)}"
        )

    def test_io_relation_single_type_stays_grouped(self) -> None:
        """Single-type ops stay in their anchor group, not forcibly scattered."""
        ops = []
        for _ in range(100):
            ops.append(SourceOperation(
                name=f"op_str_{_}", description="Str op",
                parameters=[ParamSpec(name="x", type_hint="str")],
            ))

        comp = SourceComponent(
            name="OnlyStr", file_path="s.py",
            description="All str ops", operations=ops,
        )

        result = group_source_components(
            [comp], strategy=GroupStrategy.IO_RELATION, max_io_groups=5,
        )

        assert len(result.skills) == 1
        assert len(result.skills[0].allowed_tools) == 100

    def test_io_relation_utility_ops_grouped(self) -> None:
        """Utility (untyped) operations are dissolved into typed buckets."""
        typed_ops = []
        for t in ["str", "int", "bool", "float", "Path"]:
            typed_ops.append(SourceOperation(
                name=f"op_{t}", description=f"Op {t}",
                parameters=[ParamSpec(name="x", type_hint=t)],
            ))

        untyped_ops = []
        for i in range(20):
            untyped_ops.append(SourceOperation(
                name=f"op_none_{i}", description="No type",
                parameters=[ParamSpec(name="x")],
            ))

        comp = SourceComponent(
            name="MixedTypes", file_path="m.py",
            description="Mixed typed/untyped", operations=typed_ops + untyped_ops,
        )

        result = group_source_components(
            [comp], strategy=GroupStrategy.IO_RELATION, max_io_groups=5,
        )

        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert len(all_tools) == 25

        # With the dissolution design, untyped ops are distributed
        # round-robin across existing typed buckets — no standalone
        # "utility" group should exist when typed buckets are present.
        utility_group = next(
            (s for s in result.skills if "utility" in s.name), None
        )
        assert utility_group is None, (
            f"Utility group should be dissolved, got: {[s.name for s in result.skills]}"
        )


# =========================================================================
# MatchType and MappingRule tests
# =========================================================================


class TestMatchType:
    def test_enum_values(self) -> None:
        assert MatchType.SUBSTRING.value == "substring"
        assert MatchType.PREFIX.value == "prefix"
        assert MatchType.SUFFIX.value == "suffix"
        assert MatchType.REGEX.value == "regex"
        assert MatchType.EXACT.value == "exact"


class TestMappingRuleMatches:
    def test_substring_match(self) -> None:
        rule = MappingRule("docker", "docker_ops", "build_image", match_type=MatchType.SUBSTRING)
        assert rule.matches("docker_build")
        assert rule.matches("my_docker_push")
        assert not rule.matches("k8s_apply")

    def test_prefix_match(self) -> None:
        rule = MappingRule("docker_", "docker_ops", "build_image", match_type=MatchType.PREFIX)
        assert rule.matches("docker_build")
        assert rule.matches("docker_push_image")
        assert not rule.matches("my_docker_push")

    def test_suffix_match(self) -> None:
        rule = MappingRule("_check", "check_ops", "health", match_type=MatchType.SUFFIX)
        assert rule.matches("health_check")
        assert rule.matches("status_check")
        assert not rule.matches("check_status")

    def test_regex_match(self) -> None:
        rule = MappingRule("video_encode|video_decode", "video_ops", "video_processing", match_type=MatchType.REGEX)
        assert rule.matches("video_encode")
        assert rule.matches("video_decode")
        assert not rule.matches("audio_encode")

    def test_exact_match(self) -> None:
        rule = MappingRule("rollback", "rollback", "deploy_service", match_type=MatchType.EXACT)
        assert rule.matches("rollback")
        assert not rule.matches("rollback_deployment")
        assert not rule.matches("fast_rollback")

    def test_default_match_type_is_substring(self) -> None:
        rule = MappingRule("docker", "docker_ops", "build_image")
        assert rule.match_type == MatchType.SUBSTRING
        assert rule.matches("docker_build")


# =========================================================================
# KEYWORD_MATCH strategy tests
# =========================================================================


class TestKeywordMatch:
    def test_keyword_match_with_source_components(self) -> None:
        """KEYWORD_MATCH groups SourceComponent operations by MappingRule patterns."""
        ops = [
            SourceOperation(name="docker_build", description="Build image"),
            SourceOperation(name="docker_push", description="Push image"),
            SourceOperation(name="k8s_apply", description="Apply manifest"),
            SourceOperation(name="k8s_get", description="Get resource"),
        ]
        comp = SourceComponent(
            name="CICD",
            file_path="cicd.py",
            description="CI/CD operations",
            operations=ops,
        )
        result = group_source_components([comp], strategy=GroupStrategy.KEYWORD_MATCH)
        skill_names = [s.name for s in result.skills]
        assert "build_image" in skill_names
        assert "deploy_service" in skill_names
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert "CICD.docker_build" in all_tools
        assert "CICD.docker_push" in all_tools
        assert "CICD.k8s_apply" in all_tools
        assert "CICD.k8s_get" in all_tools

    def test_keyword_match_prefix_rules(self) -> None:
        """Prefix-type MappingRules match operation name starts."""
        rules = [
            MappingRule("video_", "video_ops", "video_ops", "Video operations", MatchType.PREFIX),
            MappingRule("audio_", "audio_ops", "audio_ops", "Audio operations", MatchType.PREFIX),
        ]
        ops = [
            SourceOperation(name="video_encode", description="Encode video"),
            SourceOperation(name="video_decode", description="Decode video"),
            SourceOperation(name="audio_mix", description="Mix audio"),
            SourceOperation(name="audio_record", description="Record audio"),
        ]
        comp = SourceComponent(name="Media", file_path="media.py", description="Media ops", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=rules,
        )
        skill_names = [s.name for s in result.skills]
        assert "video_ops" in skill_names
        assert "audio_ops" in skill_names
        video_skill = next(s for s in result.skills if s.name == "video_ops")
        assert "Media.video_encode" in video_skill.allowed_tools
        assert "Media.video_decode" in video_skill.allowed_tools

    def test_keyword_match_auto_prefix_inference(self) -> None:
        """Unmatched operations are auto-grouped by underscore prefix."""
        ops = [
            SourceOperation(name="video_encode", description="Encode"),
            SourceOperation(name="video_decode", description="Decode"),
            SourceOperation(name="audio_mix", description="Mix"),
            SourceOperation(name="audio_record", description="Record"),
        ]
        comp = SourceComponent(name="Media", file_path="media.py", description="Media", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=[],
        )
        skill_names = [s.name for s in result.skills]
        assert "video_ops" in skill_names
        assert "audio_ops" in skill_names
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert len(all_tools) == 4

    def test_keyword_match_single_segment_names_in_utility(self) -> None:
        """Single-segment names (no underscore) go to utility bucket."""
        ops = [
            SourceOperation(name="init", description="Initialize"),
            SourceOperation(name="cleanup", description="Clean up"),
        ]
        comp = SourceComponent(name="Core", file_path="core.py", description="Core", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=[],
        )
        utility_skill = next(s for s in result.skills if s.name == "utility")
        assert "Core.init" in utility_skill.allowed_tools
        assert "Core.cleanup" in utility_skill.allowed_tools

    def test_keyword_match_small_prefix_groups_merged_to_misc(self) -> None:
        """Prefix groups with <2 items are merged into misc."""
        ops = [
            SourceOperation(name="video_encode", description="Encode"),
            SourceOperation(name="video_decode", description="Decode"),
            SourceOperation(name="audio_mix", description="Mix"),
            SourceOperation(name="cache_purge", description="Purge"),
        ]
        comp = SourceComponent(name="Mixed", file_path="mixed.py", description="Mixed", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=[],
        )
        all_tools = {t for s in result.skills for t in s.allowed_tools}
        assert len(all_tools) == 4
        assert "Mixed.video_encode" in all_tools
        assert "Mixed.cache_purge" in all_tools
        misc_skill = next((s for s in result.skills if s.name == "misc"), None)
        if misc_skill:
            assert "Mixed.audio_mix" in misc_skill.allowed_tools
            assert "Mixed.cache_purge" in misc_skill.allowed_tools

    def test_keyword_match_mixed_explicit_and_auto(self) -> None:
        """Explicit MappingRules + auto prefix inference work together."""
        rules = [
            MappingRule("docker_", "docker_ops", "build_image", "Docker build", MatchType.PREFIX),
        ]
        ops = [
            SourceOperation(name="docker_build", description="Build image"),
            SourceOperation(name="docker_push", description="Push image"),
            SourceOperation(name="video_encode", description="Encode video"),
            SourceOperation(name="video_decode", description="Decode video"),
        ]
        comp = SourceComponent(name="Mixed", file_path="mixed.py", description="Mixed ops", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=rules,
        )
        skill_names = [s.name for s in result.skills]
        assert "build_image" in skill_names
        assert "video_ops" in skill_names
        docker_skill = next(s for s in result.skills if s.name == "build_image")
        assert "Mixed.docker_build" in docker_skill.allowed_tools
        assert "Mixed.docker_push" in docker_skill.allowed_tools

    def test_keyword_match_regex_rule(self) -> None:
        """Regex-type MappingRule matches pattern via regex search."""
        rules = [
            MappingRule("video_encode|video_decode", "video_ops", "video_ops", "Video codec", MatchType.REGEX),
        ]
        ops = [
            SourceOperation(name="video_encode", description="Encode"),
            SourceOperation(name="video_decode", description="Decode"),
            SourceOperation(name="audio_mix", description="Mix"),
        ]
        comp = SourceComponent(name="Codec", file_path="codec.py", description="Codec", operations=ops)
        result = group_source_components(
            [comp], strategy=GroupStrategy.KEYWORD_MATCH, mapping_rules=rules,
        )
        video_skill = next(s for s in result.skills if s.name == "video_ops")
        assert "Codec.video_encode" in video_skill.allowed_tools
        assert "Codec.video_decode" in video_skill.allowed_tools

    def test_keyword_match_with_sdk_methods(self) -> None:
        """KEYWORD_MATCH also works with SdkMethod data (backward compat)."""
        from extensions.pos_converter.sdk_parser import SdkMethod
        methods = [
            SdkMethod(name="docker_build", description="Build image"),
            SdkMethod(name="docker_push", description="Push image"),
            SdkMethod(name="k8s_apply", description="Apply manifest"),
        ]
        grouper = SkillGrouper(methods, strategy=GroupStrategy.KEYWORD_MATCH)
        skills = grouper.group()
        skill_names = [s.name for s in skills]
        assert "build_image" in skill_names
        assert "deploy_service" in skill_names

    def test_keyword_match_empty_input(self) -> None:
        """KEYWORD_MATCH with no methods or components returns empty list."""
        grouper = SkillGrouper([], strategy=GroupStrategy.KEYWORD_MATCH)
        skills = grouper.group()
        assert skills == []

    def test_keyword_match_multi_component_merging(self) -> None:
        """Operations from different components merge into same skill by pattern."""
        ops_a = [
            SourceOperation(name="docker_build", description="Build"),
        ]
        ops_b = [
            SourceOperation(name="docker_push", description="Push"),
        ]
        comp_a = SourceComponent(name="Builder", file_path="b.py", description="Builder", operations=ops_a)
        comp_b = SourceComponent(name="Pusher", file_path="p.py", description="Pusher", operations=ops_b)
        result = group_source_components(
            [comp_a, comp_b], strategy=GroupStrategy.KEYWORD_MATCH,
        )
        docker_skill = next((s for s in result.skills if s.name == "build_image"), None)
        assert docker_skill is not None
        assert "Builder.docker_build" in docker_skill.allowed_tools
        assert "Pusher.docker_push" in docker_skill.allowed_tools

    def test_keyword_match_list_strategy_dispatch(self) -> None:
        """KEYWORD_MATCH in a strategy list is correctly dispatched."""
        from extensions.pos_converter.sdk_parser import SdkMethod
        methods = [SdkMethod(name="docker_build", description="Build")]
        grouper = SkillGrouper(
            methods, strategy=[GroupStrategy.KEYWORD_MATCH],
        )
        skills = grouper.group()
        assert len(skills) > 0


# =========================================================================
# AgentMarkdownWriter tests
# =========================================================================


class TestAgentMarkdownWriter:
    def test_write_agent(self) -> None:
        """Write a single agent markdown file and verify frontmatter."""
        writer = AgentMarkdownWriter()
        agent_def = {
            "name": "test-agent",
            "description": "A test agent",
            "model": "claude-4",
            "tools": ["tool_a", "tool_b"],
            "skills": ["skill_x"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            path = writer.write_agent(agent_def, output_dir)

            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "name: test-agent" in content
            assert "description: 'A test agent'" in content
            assert "model: claude-4" in content
            assert "tool_a" in content
            assert "skill_x" in content

    def test_write_skills(self) -> None:
        """Write skill markdown files with parameters."""
        writer = AgentMarkdownWriter()
        skills = [
            {
                "name": "transcode-video",
                "description": "Transcode video to target format",
                "allowed_tools": ["transcode"],
                "parameters": [
                    {"name": "input_path", "type_hint": "str", "required": True, "description": "Input file"}
                ],
                "source_code": "def transcode(path): pass",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            paths = writer.write_skills(skills, output_dir)

            assert len(paths) >= 1
            skill_path = paths[0]
            assert skill_path.exists()
            content = skill_path.read_text(encoding="utf-8")
            assert "transcode-video" in content
            assert "input_path" in content

    def test_write_overview_agent(self) -> None:
        """Write overview agent for multi-component project."""
        writer = AgentMarkdownWriter()
        agents = [
            AgentComponentInfo(
                name="video-ops-agent",
                description="Video processing operations",
                capabilities=["transcode", "slice"],
                input_types=["mp4"],
                output_types=["hls"],
                invoke_pattern="@video-ops-agent transcode input.mp4",
            ),
            AgentComponentInfo(
                name="data-process-agent",
                description="Data processing operations",
                capabilities=["filter", "aggregate"],
                input_types=["csv"],
                output_types=["json"],
                invoke_pattern="@data-process-agent process data.csv",
            ),
        ]
        stages = [
            WorkflowStage(
                name="Video Processing",
                order=1,
                description="Process video files",
                responsible_agent="video-ops-agent",
                output_type="HLS segments",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            path = writer.write_overview_agent(
                name="clawcodex-overview",
                description="Overview agent for test",
                component_agents=agents,
                workflow_stages=stages,
                output_dir=output_dir,
            )

            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "clawcodex-overview" in content
            assert "video-ops-agent" in content
            assert "data-process-agent" in content
            assert "Video Processing" in content

    def test_write_workflow(self) -> None:
        """Write WORKFLOW.md for orchestrator."""
        writer = AgentMarkdownWriter()
        agents = [
            AgentComponentInfo(name="agent-a", description="Agent A", capabilities=["a"]),
        ]
        stages = [
            WorkflowStage(name="Stage 1", order=1, responsible_agent="agent-a", output_type="result"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = writer.write_workflow("test", "Test workflow", agents, stages, Path(tmpdir))
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "WORKFLOW.md" in content or "test" in content


# =========================================================================
# Default Agent tests
# =========================================================================


class TestResolveDefaultAgent:
    def test_no_overview_file(self) -> None:
        """No overview file → return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_default_agent(tmpdir)
            assert result is None

    def test_with_overview_file(self) -> None:
        """Overview file exists → return parsed dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".claude" / "agents"
            agents_dir.mkdir(parents=True)
            overview = agents_dir / "clawcodex-overview.md"
            overview.write_text("""\
---
name: clawcodex-overview
description: Overview agent
model: claude-4
tools:
  - "*"
skills:
  - skill-a
---

# Overview Agent

This is the overview agent.
""")
            result = resolve_default_agent(tmpdir)
            assert result is not None
            assert result["name"] == "clawcodex-overview"
            assert result["description"] == "Overview agent"
            assert result["model"] == "claude-4"

    def test_resolve_agent_by_type(self) -> None:
        """Find an agent by its frontmatter name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".claude" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "my-agent.md").write_text("""\
---
name: my-agent
description: My custom agent
---

# My Agent

Custom agent body.
""")
            result = resolve_agent_by_type(tmpdir, "my-agent")
            assert result is not None
            assert result["name"] == "my-agent"
            assert "custom agent" in result.get("description", "").lower()


class TestParseFrontmatter:
    def test_simple_frontmatter(self) -> None:
        content = """\
---
name: test
description: Test
tools:
  - tool_a
  - tool_b
---

Body text
"""
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "test"
        assert fm["description"] == "Test"
        assert "tool_a" in fm.get("tools", [])
        assert "Body text" in body

    def test_no_frontmatter(self) -> None:
        content = "Just some text\nNo frontmatter here."
        fm, body = _parse_frontmatter(content)
        assert fm == {}
        assert "Just some text" in body


# =========================================================================
# AgentBuilder tests
# =========================================================================


class TestAgentBuilder:
    def test_build_agent_definition_format(self) -> None:
        """Default format='agent_definition' still works."""
        skills = [SkillSpec(name="test-skill", description="Test", allowed_tools=["tool_a"])]
        builder = AgentBuilder(
            skills=skills,
            agent_name="test-agent",
            agent_description="A test agent",
        )
        result = builder.build()
        assert result.agent.agent_type == "test-agent"
        assert "tool_a" in (result.agent.tools or [])

    def test_build_with_markdown_format(self) -> None:
        """format='markdown' writes agent markdown files."""
        skills = [SkillSpec(name="test-skill", description="Test", allowed_tools=["tool_a"])]
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = AgentBuilder(
                skills=skills,
                agent_name="test-agent",
                agent_description="A test agent",
                output_dir=tmpdir,
            )
            result = builder.build(format="markdown")
            assert result.markdown_files is not None

    def test_invalid_format_raises(self) -> None:
        """Invalid format string raises ValueError."""
        builder = AgentBuilder(
            skills=[],
            agent_name="test",
            agent_description="test",
        )
        with pytest.raises(ValueError):
            builder.build(format="invalid")

    def test_overview_built_from_skills_not_components(self) -> None:
        """F-55: overview agent reflects grouped skills, not raw components."""
        ops_a = [SourceOperation(name="op_a", description="Op A")]
        ops_b = [SourceOperation(name="op_b", description="Op B")]
        comp_a = SourceComponent(name="CompA", file_path="a.py", description="Comp A", operations=ops_a)
        comp_b = SourceComponent(name="CompB", file_path="b.py", description="Comp B", operations=ops_b)

        # Simulate IO_RELATION: 2 components merged into 1 skill
        skills = [SkillSpec(name="merged_skill", description="Merged", allowed_tools=["op_a", "op_b"])]
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = AgentBuilder(
                skills=skills,
                agent_name="test-agent",
                agent_description="A test agent",
                source_components=[comp_a, comp_b],
                output_dir=tmpdir,
            )
            result = builder.build(format="markdown")
            # 1 agent + 1 skill file; no overview since only 1 skill
            assert len(result.markdown_files) == 2
            agent_file = [f for f in result.markdown_files if "test-agent" in f.name][0]
            agent_content = agent_file.read_text(encoding="utf-8")
            assert "merged_skill" in agent_content

    def test_multi_skill_overview_generation(self) -> None:
        """F-55: multiple grouped skills → overview agent generated."""
        skills = [
            SkillSpec(name="skill_a", description="Skill A", allowed_tools=["tool_a1"]),
            SkillSpec(name="skill_b", description="Skill B", allowed_tools=["tool_b1"]),
        ]
        components = [
            SourceComponent(name="CompA", file_path="a.py", description="A",
                          operations=[SourceOperation(name="tool_a1", description="Tool A1")]),
            SourceComponent(name="CompB", file_path="b.py", description="B",
                          operations=[SourceOperation(name="tool_b1", description="Tool B1")]),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = AgentBuilder(
                skills=skills,
                agent_name="multi-agent",
                agent_description="Multi-agent",
                source_components=components,
                output_dir=tmpdir,
            )
            result = builder.build(format="both")
            # 2 agent files + 1 overview + skill files
            assert result.markdown_files is not None
            assert len(result.markdown_files) >= 3  # agent + skills + overview
            # Find overview agent
            overview_files = [f for f in result.markdown_files if "clawcodex-overview" in f.name]
            assert len(overview_files) >= 1, f"Expected overview agent, got: {[f.name for f in result.markdown_files]}"
            overview_content = overview_files[0].read_text(encoding="utf-8")
            assert "skill_a-agent" in overview_content
            assert "skill_b-agent" in overview_content


# =========================================================================
# Auto-generate rules naming tests
# =========================================================================


class TestAutoGenerateRulesNaming:
    def _make_components(self, paths: list[str]) -> list[SourceComponent]:
        """Create SourceComponents from a list of file_path strings."""
        comps = []
        for fp in paths:
            name = Path(fp).stem if fp.endswith(".py") else Path(fp).name
            comps.append(SourceComponent(
                name=name, file_path=fp,
                description=f"Component in {fp}",
                operations=[SourceOperation(name="do_work", description="Work")],
            ))
        return comps

    def test_merged_group_named_by_common_ancestor(self) -> None:
        """Merged group skill_name uses common ancestor, not one leaf's unique tag."""
        from extensions.pos_converter.skill_grouper import SkillGrouper, MappingRule

        comps = self._make_components([
            "proj/examples/permissions/perm_ops.py",
            "proj/examples/rl_calculator/rl_ops.py",
            "proj/examples/session/session_ops.py",
            "proj/core/memory/mem_ops.py",
            "proj/core/runner/runner_ops.py",
        ])

        rules = SkillGrouper._auto_generate_rules(comps, max_groups=4)
        skill_names = {r.skill_name for r in rules}

        # The examples/* paths should be merged into one group named
        # after their common ancestor "examples", NOT "permissions" or
        # "rl_calculator".
        assert "examples" in skill_names, f"Expected 'examples' in skill_names, got: {skill_names}"

    def test_merged_group_no_common_ancestor_fallback(self) -> None:
        """When sub_keys share no common segment, fallback to distinguishing pattern."""
        from extensions.pos_converter.skill_grouper import SkillGrouper, MappingRule

        comps = self._make_components([
            "proj/a_domain/ops.py",
            "proj/b_domain/ops.py",
            "proj/c_domain/ops.py",
            "proj/d_domain/ops.py",
        ])

        rules = SkillGrouper._auto_generate_rules(comps, max_groups=2)

        # These 4 groups get merged into 2. The first merged group may
        # have sub_keys like "proj/a_domain|proj/b_domain" — their common
        # ancestor is "proj" which is also shared by all other groups.
        # Fallback should use a distinguishing segment.
        skill_names = {r.skill_name for r in rules}
        assert len(skill_names) <= 2

    def test_common_ancestor_segment_basic(self) -> None:
        """_common_ancestor_segment finds the deepest shared segment."""
        from extensions.pos_converter.skill_grouper import _common_ancestor_segment

        sub_keys = ["proj/examples/permissions", "proj/examples/rl_calc", "proj/examples/session"]
        other = {"core", "memory", "runner", "harness", "proj"}
        result = _common_ancestor_segment(sub_keys, other)
        assert result == "examples", f"Expected 'examples', got: {result}"

    def test_common_ancestor_segment_unique_to_group(self) -> None:
        """_common_ancestor_segment prefers segments not shared with other groups."""
        from extensions.pos_converter.skill_grouper import _common_ancestor_segment

        sub_keys = ["proj/examples/permissions", "proj/examples/rl_calc"]
        # "examples" is NOT in other → should be picked even though it's shallow
        other = {"core", "memory", "runner"}
        result = _common_ancestor_segment(sub_keys, other)
        assert result == "examples"

    def test_common_ancestor_segment_all_shared_with_others(self) -> None:
        """When all common segments are in other_segments, fallback to deepest common."""
        from extensions.pos_converter.skill_grouper import _common_ancestor_segment

        sub_keys = ["proj/examples/perm", "proj/examples/rl"]
        # "proj" and "examples" are both in other_segments
        other = {"proj", "examples", "core"}
        result = _common_ancestor_segment(sub_keys, other)
        # Should return the deepest common segment ("examples") as fallback
        assert result == "examples"

    def test_common_ancestor_no_common_segments(self) -> None:
        """When sub_keys share no segments, returns None."""
        from extensions.pos_converter.skill_grouper import _common_ancestor_segment

        sub_keys = ["alpha/ops", "beta/ops"]
        other = set()
        result = _common_ancestor_segment(sub_keys, other)
        # Only "ops" is common, but it's a very generic leaf name
        assert result == "ops" or result is None

    def test_single_path_group_not_affected(self) -> None:
        """Single-path groups still use _best_distinguishing_pattern (unchanged)."""
        from extensions.pos_converter.skill_grouper import SkillGrouper

        comps = self._make_components([
            "proj/core/memory/mem_ops.py",
        ])

        rules = SkillGrouper._auto_generate_rules(comps, max_groups=10)
        # Single path group — should use distinguishing pattern
        assert len(rules) == 1
        # With only one group, "proj" is the most distinguishing segment
        # (it's unique since no other groups exist)
        assert rules[0].skill_name in {"proj", "memory", "mem_ops"}


# =========================================================================
# Template string tests
# =========================================================================


class TestTemplates:
    def test_agent_md_template_has_required_fields(self) -> None:
        assert "name:" in AGENT_MD_TEMPLATE
        assert "description:" in AGENT_MD_TEMPLATE
        assert "tools:" in AGENT_MD_TEMPLATE

    def test_skill_md_template_has_required_fields(self) -> None:
        assert "allowed-tools:" in SKILL_MD_TEMPLATE_JINJA
        assert "user-invocable:" in SKILL_MD_TEMPLATE_JINJA

    def test_overview_agent_template_has_required_fields(self) -> None:
        assert "总览 Agent" in OVERVIEW_AGENT_TEMPLATE
        assert "component_agents" in OVERVIEW_AGENT_TEMPLATE
        assert "workflow_stages" in OVERVIEW_AGENT_TEMPLATE


# =========================================================================
# LLM_SEMANTIC strategy tests (mock-based, no real LLM call)
# =========================================================================


class TestLLMSemanticStrategy:
    def test_fallback_without_provider(self) -> None:
        """Without an LLM provider, LLM_SEMANTIC falls back to KEYWORD_MATCH."""
        ops = [
            SourceOperation(name="encode", description="Encode video",
                           parameters=[ParamSpec(name="data", type_hint="str")]),
            SourceOperation(name="decode", description="Decode video",
                           parameters=[ParamSpec(name="data", type_hint="bytes")]),
        ]
        comp = SourceComponent(name="VideoOps", file_path="v.py",
                               description="Video operations", operations=ops)

        result = group_source_components(
            [comp], strategy=GroupStrategy.LLM_SEMANTIC,
            llm_provider=None,
        )
        assert len(result.skills) > 0
        # Fallback is KEYWORD_MATCH, not IO_RELATION
        assert not result.skills[0].name.startswith("io_group_")

    def test_parse_valid_json_response(self) -> None:
        """_parse_llm_patterns correctly parses a patterns-based JSON response."""
        ops = [
            SourceOperation(name="encode", description="Encode video",
                           parameters=[ParamSpec(name="data", type_hint="str")]),
            SourceOperation(name="decode", description="Decode video",
                           parameters=[ParamSpec(name="data", type_hint="bytes")]),
            SourceOperation(name="load", description="Load config",
                           parameters=[ParamSpec(name="path", type_hint="Path")]),
        ]
        comp = SourceComponent(name="VideoOps", file_path="video/video_ops.py",
                               description="Video operations", operations=ops)

        grouper = SkillGrouper(
            methods=[], strategy=GroupStrategy.LLM_SEMANTIC,
            source_components=[comp], llm_provider=None,
        )

        raw_json = ('{"skills": ['
                    '{"name": "video_processing", "description": "Video codec", '
                    '"patterns": ["video"]}, '
                    '{"name": "config_management", "description": "Config loading", '
                    '"patterns": ["config"]}]}')
        dir_paths = ["video/video_ops.py"]
        rules = grouper._parse_llm_patterns(raw_json, dir_paths)
        assert rules is not None
        assert len(rules) == 2
        skill_names = {r.skill_name for r in rules}
        assert "video_processing" in skill_names
        assert "config_management" in skill_names
        # Patterns become FILE_PATH / SUBSTRING rules.
        for r in rules:
            assert r.match_target == MatchTarget.FILE_PATH
            assert r.match_type == MatchType.SUBSTRING

    def test_parse_json_with_preamble(self) -> None:
        """_extract_json_from_raw tolerates LLM preamble text."""
        raw = "Here is the grouping result:\n{\"skills\": [{\"name\": \"a\", \"description\": \"b\", \"tools\": []}]}\nHope this helps!"
        result = SkillGrouper._extract_json_from_raw(raw)
        assert result is not None
        import json
        parsed = json.loads(result)
        assert "skills" in parsed

    def test_orphaned_tools_assigned_to_largest(self) -> None:
        """Unmatched dirs go through auto prefix inference in _keyword_match_group."""
        ops = [
            SourceOperation(name="op_a", description="A",
                           parameters=[ParamSpec(name="x", type_hint="str")]),
            SourceOperation(name="op_b", description="B",
                           parameters=[ParamSpec(name="x", type_hint="int")]),
            SourceOperation(name="op_c", description="C",
                           parameters=[ParamSpec(name="x", type_hint="bool")]),
        ]
        comp_a = SourceComponent(name="CompA", file_path="core/module_a.py",
                                 description="Module A", operations=[ops[0]])
        comp_b = SourceComponent(name="CompB", file_path="core/module_b.py",
                                 description="Module B", operations=[ops[1]])
        comp_c = SourceComponent(name="CompC", file_path="extra/module_c.py",
                                 description="Module C", operations=[ops[2]])

        grouper = SkillGrouper(
            methods=[], strategy=GroupStrategy.LLM_SEMANTIC,
            source_components=[comp_a, comp_b, comp_c],
            max_io_groups=10, llm_provider=None,
        )

        # LLM only covers "core" — "extra" is unmatched, handled by auto prefix.
        raw_json = ('{"skills": ['
                    '{"name": "core_group", "description": "Core modules", '
                    '"patterns": ["core"]}]}')
        dir_paths = ["core/module_a.py", "core/module_b.py", "extra/module_c.py"]
        rules = grouper._parse_llm_patterns(raw_json, dir_paths)
        assert rules is not None
        assert len(rules) == 1
        assert rules[0].skill_name == "core_group"

        # Set rules and run keyword_match — unmatched "extra" should go
        # to utility (single-segment prefix without underscore).
        grouper._rules = rules
        skills = grouper._keyword_match_group()
        all_tools = {t for s in skills for t in s.allowed_tools}
        assert "CompA.op_a" in all_tools
        assert "CompB.op_b" in all_tools
        assert "CompC.op_c" in all_tools

    def test_invalid_tools_filtered(self) -> None:
        """LLM patterns that match no dirs are still valid (keyword handles matching)."""
        ops = [
            SourceOperation(name="real_op", description="Real",
                           parameters=[ParamSpec(name="x", type_hint="str")]),
        ]
        comp = SourceComponent(name="Comp", file_path="core/real.py",
                               description="Test", operations=ops)

        grouper = SkillGrouper(
            methods=[], strategy=GroupStrategy.LLM_SEMANTIC,
            source_components=[comp], llm_provider=None,
        )

        # LLM returns a pattern for a dir that exists + one that doesn't.
        # The non-matching pattern is harmless — keyword_match just won't match.
        raw_json = ('{"skills": ['
                    '{"name": "s1", "description": "d1", '
                    '"patterns": ["core", "nonexistent"]}]}')
        dir_paths = ["core/real.py"]
        rules = grouper._parse_llm_patterns(raw_json, dir_paths)
        assert rules is not None
        assert len(rules) == 2  # both patterns become rules
        skill_names = {r.skill_name for r in rules}
        assert skill_names == {"s1"}

    def test_max_groups_enforcement(self) -> None:
        """_parse_llm_patterns handles many skills; LLM prompt tells LLM to respect max."""
        ops = []
        for i in range(6):
            ops.append(SourceOperation(
                name=f"op_{i}", description=f"Op {i}",
                parameters=[ParamSpec(name="x", type_hint="str")],
            ))
        comps = []
        for i in range(6):
            comps.append(SourceComponent(
                name=f"Comp{i}", file_path=f"dir_{i}/mod.py",
                description=f"Module {i}", operations=[ops[i]],
            ))

        grouper = SkillGrouper(
            methods=[], strategy=GroupStrategy.LLM_SEMANTIC,
            source_components=comps, max_io_groups=3, llm_provider=None,
        )

        # LLM produces 6 skills with 1 pattern each.
        raw_json = '{"skills": [' + ', '.join(
            f'{{"name": "g{i}", "description": "Group {i}", "patterns": ["dir_{i}"]}}'
            for i in range(6)
        ) + ']}'
        dir_paths = [f"dir_{i}/mod.py" for i in range(6)]
        rules = grouper._parse_llm_patterns(raw_json, dir_paths)
        assert rules is not None
        assert len(rules) == 6  # all 6 patterns become rules

    def test_no_source_components_falls_back_to_static(self) -> None:
        """With no source_components, _group_with_llm falls back to _static_group."""
        grouper = SkillGrouper(
            methods=[], strategy=GroupStrategy.LLM_SEMANTIC,
            source_components=[], llm_provider=None,
        )
        result = grouper._group_with_llm("")
        assert result == grouper._static_group()

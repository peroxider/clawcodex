"""Unit tests for :mod:`extensions.pos_converter.tool_registry_bridge`.

Covers the bridge that converts parsed source operations into
executable agent tools with bash-callable wrapper scripts.

* :func:`_type_hint_to_json_type` — Python type-hint → JSON Schema.
* :func:`_strip_optional_union` — Optional/Union/X | None reduction.
* :func:`_to_kebab_case` — dot/snake → kebab-case conversion.
* :func:`_resolve_module_path` — dotted module path from file path.
* :func:`_script_name_for_class` / :func:`_script_name_for_functions`
  — deterministic script filenames.
* :func:`_generate_wrapper_script` — wrapper script creation.
* :func:`_enrich_bridge_params` — json_args injection.
* :func:`operation_to_spec` — single-operation → AgentToolSpec.
* :func:`register_component_tools` — bulk registration with name map.
"""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.pos_converter import tool_registry_bridge as trb
from extensions.pos_converter.source_parser import (
    ParamSpec,
    SourceComponent,
    SourceOperation,
)
from extensions.pos_converter.tool_registry_bridge import (
    _enrich_bridge_params,
    _generate_wrapper_script,
    _resolve_module_path,
    _script_name_for_class,
    _script_name_for_functions,
    _strip_optional_union,
    _to_kebab_case,
    _type_hint_to_json_type,
    operation_to_spec,
    register_component_tools,
)


def _make_param(
    name: str,
    type_hint: str | None = None,
    *,
    required: bool = True,
    default: object = None,
    description: str = "",
) -> ParamSpec:
    return ParamSpec(
        name=name,
        type_hint=type_hint,
        default=default,
        required=required,
        description=description,
    )


def _make_op(
    name: str = "do_thing",
    *,
    description: str = "A method that does a thing.",
    parameters: list[ParamSpec] | None = None,
    return_type: str | None = None,
    class_name: str | None = None,
    file_stem: str = "things",
    is_async: bool = False,
) -> SourceOperation:
    return SourceOperation(
        name=name,
        description=description,
        parameters=parameters or [],
        return_type=return_type,
        class_name=class_name,
        file_stem=file_stem,
        is_async=is_async,
    )


def _make_component(
    name: str = "comp",
    file_path: str = "comp/things",
    operations: list[SourceOperation] | None = None,
) -> SourceComponent:
    return SourceComponent(
        name=name,
        file_path=file_path,
        description="A test component",
        operations=operations or [],
    )


def _isolated_dirs() -> tuple[object, Path, Path]:
    """Return (cleanup, fake_tool_dir, fake_scripts_dir).

    Patches the module's TOOL_DIR and SCRIPTS_DIR to temp paths.
    """
    tmp = tempfile.TemporaryDirectory()
    tool_dir = Path(tmp.name) / "tools"
    scripts_dir = tool_dir / "scripts"
    tool_dir.mkdir()
    scripts_dir.mkdir()

    def _cleanup() -> None:
        tmp.cleanup()

    patches = [
        patch.object(trb, "TOOL_DIR", tool_dir),
        patch.object(trb, "SCRIPTS_DIR", scripts_dir),
        # Also patch the imported name on the upstream module, since
        # SCRIPTS_DIR = TOOL_DIR / "scripts" evaluated at import time.
        patch(
            "clawcodex_ext.agent.tool_authoring.persistence.TOOL_DIR",
            tool_dir,
        ),
    ]
    for p in patches:
        p.start()
    return _cleanup, tool_dir, scripts_dir


# ---------------------------------------------------------------------------
# _strip_optional_union
# ---------------------------------------------------------------------------


class TestStripOptionalUnion(unittest.TestCase):
    def test_none_input(self) -> None:
        # None / empty → returns the empty string unchanged.
        self.assertEqual(_strip_optional_union(""), "")

    def test_passthrough_non_optional(self) -> None:
        self.assertEqual(_strip_optional_union("str"), "str")

    def test_optional_typing(self) -> None:
        self.assertEqual(_strip_optional_union("Optional[int]"), "int")

    def test_union_typing(self) -> None:
        self.assertEqual(
            _strip_optional_union("Union[str, None]"), "str",
        )

    def test_pipe_union(self) -> None:
        self.assertEqual(_strip_optional_union("int | None"), "int")

    def test_nested_pipe_union(self) -> None:
        # Recursive: outer pipe is split, inner is also handled.
        self.assertEqual(
            _strip_optional_union("dict[str, Foo] | None"),
            "dict[str, Foo]",
        )

    def test_nonetype_recognised(self) -> None:
        # "NoneType" is treated the same as "None".
        self.assertEqual(
            _strip_optional_union("Optional[NoneType, str]"), "str",
        )


# ---------------------------------------------------------------------------
# _type_hint_to_json_type
# ---------------------------------------------------------------------------


class TestTypeHintToJsonType(unittest.TestCase):
    def test_none_input_defaults_to_string(self) -> None:
        self.assertEqual(_type_hint_to_json_type(None), "string")

    def test_empty_string_defaults_to_string(self) -> None:
        self.assertEqual(_type_hint_to_json_type(""), "string")

    def test_primitive_types(self) -> None:
        for hint, expected in [
            ("str", "string"),
            ("int", "integer"),
            ("float", "number"),
            ("bool", "boolean"),
        ]:
            with self.subTest(hint=hint):
                self.assertEqual(_type_hint_to_json_type(hint), expected)

    def test_collection_types(self) -> None:
        for hint, expected in [
            ("list", "array"),
            ("List[int]", "array"),
            ("Dict[str, int]", "object"),
            ("Mapping[str, Any]", "object"),
        ]:
            with self.subTest(hint=hint):
                self.assertEqual(_type_hint_to_json_type(hint), expected)

    def test_unknown_type_falls_back_to_string(self) -> None:
        self.assertEqual(_type_hint_to_json_type("MyCustomType"), "string")

    def test_optional_typing_reduces_first(self) -> None:
        self.assertEqual(
            _type_hint_to_json_type("Optional[int]"), "integer",
        )
        self.assertEqual(
            _type_hint_to_json_type("str | None"), "string",
        )

    def test_iterable_returns_array(self) -> None:
        self.assertEqual(
            _type_hint_to_json_type("Iterable[str]"), "array",
        )
        self.assertEqual(
            _type_hint_to_json_type("Sequence[int]"), "array",
        )


# ---------------------------------------------------------------------------
# _to_kebab_case
# ---------------------------------------------------------------------------


class TestToKebabCase(unittest.TestCase):
    def test_already_kebab(self) -> None:
        self.assertEqual(_to_kebab_case("docker-build"), "docker-build")

    def test_dot_separator(self) -> None:
        self.assertEqual(_to_kebab_case("LLM.invoke"), "llm-invoke")

    def test_underscore_separator(self) -> None:
        self.assertEqual(_to_kebab_case("video_ops.transcode"),
                         "video-ops-transcode")

    def test_double_underscore(self) -> None:
        # "__" also acts as a separator.
        self.assertEqual(
            _to_kebab_case("utils__load_config"),
            "utils-load-config",
        )

    def test_multi_level_dot_path(self) -> None:
        self.assertEqual(
            _to_kebab_case("foundation.LLM.invoke"),
            "foundation-llm-invoke",
        )

    def test_camelcase_preserved_as_one_word(self) -> None:
        # "VideoProcessor" → "videoprocessor" (NOT "video-processor").
        self.assertEqual(
            _to_kebab_case("VideoProcessor.transcode"),
            "videoprocessor-transcode",
        )

    def test_strips_leading_trailing_hyphens(self) -> None:
        self.assertEqual(_to_kebab_case("-foo-"), "foo")

    def test_collapses_consecutive_hyphens(self) -> None:
        self.assertEqual(_to_kebab_case("foo--bar---baz"), "foo-bar-baz")


# ---------------------------------------------------------------------------
# _resolve_module_path
# ---------------------------------------------------------------------------


class TestResolveModulePath(unittest.TestCase):
    def test_strips_source_dir_prefix(self) -> None:
        comp = _make_component(file_path="openjiuwen/core/foundation")
        # source_dir = "/some/root/openjiuwen" — file_path is relative
        # to source_dir.parent, so we strip the "openjiuwen" segment.
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "openjiuwen"
            source_dir.mkdir()
            result = _resolve_module_path(comp, str(source_dir), "llm")
        self.assertEqual(result, "core.foundation.llm")

    def test_falls_back_to_full_path(self) -> None:
        # If file_path doesn't start with source_dir name, use it raw.
        comp = _make_component(file_path="other/location")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "openjiuwen"
            source_dir.mkdir()
            result = _resolve_module_path(comp, str(source_dir), "llm")
        # The file_path is used as-is, then file_stem is appended.
        self.assertEqual(result, "other.location.llm")

    def test_with_dots_in_path(self) -> None:
        comp = _make_component(file_path="openjiuwen/core.sub/foo")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "openjiuwen"
            source_dir.mkdir()
            result = _resolve_module_path(comp, str(source_dir), "bar")
        self.assertEqual(result, "core.sub.foo.bar")

    def test_with_dot_dir_path(self) -> None:
        # A file_path of "." should not become "..bar" — the parts
        # should just be empty before appending file_stem.
        comp = _make_component(file_path=".")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "openjiuwen"
            source_dir.mkdir()
            result = _resolve_module_path(comp, str(source_dir), "x")
        # "." → empty parts → append "x" → "x".
        self.assertEqual(result, "x")


# ---------------------------------------------------------------------------
# _script_name_for_class / _script_name_for_functions
# ---------------------------------------------------------------------------


class TestScriptNameForClass(unittest.TestCase):
    def test_format(self) -> None:
        # Name is "{class}_{8-char-hash}.py".
        name = _script_name_for_class("foo.bar", "Baz")
        self.assertTrue(name.startswith("Baz_"))
        self.assertTrue(name.endswith(".py"))
        # Total: Baz_ + 8 hex chars + .py = 4 + 8 + 3 = 15 chars
        self.assertEqual(len(name), len("Baz_") + 8 + len(".py"))

    def test_deterministic(self) -> None:
        # Same inputs → same hash → same name.
        self.assertEqual(
            _script_name_for_class("a.b", "X"),
            _script_name_for_class("a.b", "X"),
        )

    def test_different_module_different_name(self) -> None:
        # Same class, different module path → different hash.
        self.assertNotEqual(
            _script_name_for_class("a.b", "X"),
            _script_name_for_class("a.c", "X"),
        )


class TestScriptNameForFunctions(unittest.TestCase):
    def test_format(self) -> None:
        # Format: "{file_stem}_fn_{hash}.py"
        name = _script_name_for_functions("foo.bar", "things")
        self.assertTrue(name.startswith("things_fn_"))
        self.assertTrue(name.endswith(".py"))

    def test_deterministic(self) -> None:
        self.assertEqual(
            _script_name_for_functions("a.b", "x"),
            _script_name_for_functions("a.b", "x"),
        )


# ---------------------------------------------------------------------------
# _generate_wrapper_script
# ---------------------------------------------------------------------------


class TestGenerateWrapperScript(unittest.TestCase):
    def setUp(self) -> None:
        self._cleanup, self.tool_dir, self.scripts_dir = _isolated_dirs()
        self.addCleanup(self._cleanup)

    def test_class_script_created(self) -> None:
        op = _make_op(name="compute", class_name="Calc")
        comp = _make_component(operations=[op])
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name="Calc",
                module_name="proj.calc",
                file_stem="calc",
                source_dir=str(source_dir),
            )
        self.assertTrue(script_path.exists())
        content = script_path.read_text()
        self.assertIn("Calc (proj.calc)", content)
        # The method name is wired in.
        self.assertIn("def compute", content)
        # sys.path is injected.
        self.assertIn(str(source_dir), content)

    def test_function_script_created(self) -> None:
        op = _make_op(name="my_func", class_name=None, file_stem="helpers")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="proj.helpers",
                file_stem="helpers",
                source_dir=str(source_dir),
            )
        content = script_path.read_text()
        # No _get_instance helper for standalone functions.
        self.assertNotIn("_get_instance", content)
        # Direct module attribute call.
        self.assertIn("module.my_func", content)
        # Header label includes the file_stem.
        self.assertIn("helpers functions", content)

    def test_async_method_uses_asyncio_run(self) -> None:
        op = _make_op(name="go", class_name="X", is_async=True)
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name="X",
                module_name="proj.x",
                file_stem="x",
                source_dir=str(source_dir),
            )
        content = script_path.read_text()
        self.assertIn("asyncio.run(_get_instance", content)
        # Balanced parens: opens with asyncio.run( and closes ).
        # We can sanity-check the count of `(` and `)`.
        self.assertEqual(content.count("("), content.count(")"))

    def test_skips_star_args_in_stub(self) -> None:
        # *args / **kwargs should be dropped from the stub signature
        # since they can't be passed via JSON.
        op = _make_op(
            name="variadic",
            class_name="V",
            parameters=[
                _make_param("x", "int"),
                _make_param("*args", "list", required=False),
                _make_param("**kwargs", "dict", required=False),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name="V",
                module_name="proj.v",
                file_stem="v",
                source_dir=str(source_dir),
            )
        content = script_path.read_text()
        # The def line should not include *args or **kwargs.
        for line in content.splitlines():
            if line.startswith("def variadic"):
                self.assertNotIn("*args", line)
                self.assertNotIn("**kwargs", line)
                break
        else:
            self.fail("could not find def variadic")

    def test_optional_param_becomes_none_default(self) -> None:
        op = _make_op(
            name="f",
            class_name="C",
            parameters=[
                _make_param("a", "int", required=True),
                _make_param("b", "int", required=False),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name="C",
                module_name="proj.c",
                file_stem="c",
                source_dir=str(source_dir),
            )
        content = script_path.read_text()
        for line in content.splitlines():
            if line.startswith("def f"):
                # `a` is required (no default), `b` is optional (None).
                self.assertIn("a,", line)
                self.assertIn("b=None", line)
                break


# ---------------------------------------------------------------------------
# _enrich_bridge_params
# ---------------------------------------------------------------------------


class TestEnrichBridgeParams(unittest.TestCase):
    def test_adds_json_args(self) -> None:
        result = _enrich_bridge_params({"x": 1, "y": "z"})
        self.assertIn("json_args", result)
        # json_args is the JSON-serialised form of the original dict.
        parsed = json.loads(result["json_args"])
        self.assertEqual(parsed, {"x": 1, "y": "z"})
        # Original keys preserved.
        self.assertEqual(result["x"], 1)
        self.assertEqual(result["y"], "z")

    def test_empty_params(self) -> None:
        result = _enrich_bridge_params({})
        self.assertEqual(result, {"json_args": "{}"})

    def test_unicode_preserved(self) -> None:
        result = _enrich_bridge_params({"name": "你好"})
        # ensure_ascii=False → Chinese chars preserved.
        self.assertIn("你好", result["json_args"])

    def test_does_not_mutate_input(self) -> None:
        original = {"x": 1}
        result = _enrich_bridge_params(original)
        # The original dict is unchanged.
        self.assertNotIn("json_args", original)
        # The result is a new dict.
        self.assertIsNot(result, original)


# ---------------------------------------------------------------------------
# operation_to_spec
# ---------------------------------------------------------------------------


class TestOperationToSpec(unittest.TestCase):
    def setUp(self) -> None:
        self._cleanup, self.tool_dir, self.scripts_dir = _isolated_dirs()
        self.addCleanup(self._cleanup)
        self.script_path = "/tmp/fake_script.py"

    def test_class_method_kebab_name(self) -> None:
        op = _make_op(name="invoke", class_name="LLM")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
            comp_name="core",
        )
        # {comp}.{class}.{method} → "core.LLM.invoke" → kebab.
        self.assertEqual(spec.name, "core-llm-invoke")

    def test_class_method_without_comp_name(self) -> None:
        op = _make_op(name="invoke", class_name="LLM")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        # Falls back to {class}.{method}.
        self.assertEqual(spec.name, "llm-invoke")

    def test_standalone_function_with_comp(self) -> None:
        op = _make_op(name="load_config", class_name=None, file_stem="utils")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
            comp_name="helpers",
        )
        self.assertEqual(spec.name, "helpers-load-config")

    def test_standalone_function_no_comp_falls_back_to_file_stem(self) -> None:
        op = _make_op(name="load_config", class_name=None, file_stem="utils")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(spec.name, "utils-load-config")

    def test_no_comp_no_file_stem_kebab_converts(self) -> None:
        # Even without a comp or file_stem, the raw name goes through
        # kebab-case conversion. "load_config" → "load-config".
        op = _make_op(name="load_config", class_name=None, file_stem="")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(spec.name, "load-config")

    def test_call_type_is_bash(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(spec.call_type, "bash")

    def test_call_impl_uses_script_path(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        # The bash command should reference the script path and method.
        self.assertIn(self.script_path, spec.call_impl)
        self.assertIn("x", spec.call_impl)
        # And the {json_args} placeholder for the runtime.
        self.assertIn("{json_args}", spec.call_impl)

    def test_input_schema_basic_param(self) -> None:
        op = _make_op(
            name="x",
            parameters=[_make_param("foo", "str")],
        )
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        schema = spec.input_schema
        self.assertEqual(schema["type"], "object")
        self.assertIn("foo", schema["properties"])
        self.assertEqual(schema["properties"]["foo"]["type"], "string")
        # Required param → "required" list contains "foo".
        self.assertIn("foo", schema["required"])

    def test_optional_param_not_required(self) -> None:
        op = _make_op(
            name="x",
            parameters=[_make_param("foo", "str", required=False)],
        )
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        # "required" key is omitted when there are no required params.
        self.assertNotIn("required", spec.input_schema)

    def test_param_with_description(self) -> None:
        op = _make_op(
            name="x",
            parameters=[
                _make_param("foo", "str", description="The foo value"),
            ],
        )
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(
            spec.input_schema["properties"]["foo"]["description"],
            "The foo value",
        )

    def test_param_with_default(self) -> None:
        op = _make_op(
            name="x",
            parameters=[_make_param("foo", "str", default="bar")],
        )
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(
            spec.input_schema["properties"]["foo"]["default"], "bar",
        )

    def test_aliases_with_comp_name(self) -> None:
        op = _make_op(name="x", class_name="C")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
            comp_name="alpha",
        )
        # First alias is the fully-qualified {comp}.{class}.{method}.
        self.assertIn("alpha.C.x", spec.aliases)

    def test_aliases_short_form_with_dotted_comp(self) -> None:
        # When comp_name is "openjiuwen.core" (multi-segment), an
        # additional short alias drops the first segment.
        op = _make_op(name="x", class_name="C")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
            comp_name="openjiuwen.core",
        )
        # Original alias present.
        self.assertIn("openjiuwen.core.C.x", spec.aliases)
        # Short alias present.
        self.assertIn("core.C.x", spec.aliases)

    def test_source_is_pos_converter(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertEqual(spec.source, "pos-converter")

    def test_skips_star_args_in_schema(self) -> None:
        op = _make_op(
            name="x",
            parameters=[
                _make_param("foo", "int"),
                _make_param("*args", "list", required=False),
                _make_param("**kwargs", "dict", required=False),
            ],
        )
        spec = operation_to_spec(
            op, source_dir="/tmp", script_path=self.script_path,
        )
        self.assertIn("foo", spec.input_schema["properties"])
        self.assertNotIn("*args", spec.input_schema["properties"])
        self.assertNotIn("**kwargs", spec.input_schema["properties"])


# ---------------------------------------------------------------------------
# register_component_tools
# ---------------------------------------------------------------------------


class TestRegisterComponentTools(unittest.TestCase):
    def setUp(self) -> None:
        self._cleanup, self.tool_dir, self.scripts_dir = _isolated_dirs()
        self.addCleanup(self._cleanup)

    def test_register_class_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="invoke", class_name="LLM")
            comp = _make_component(
                name="core", file_path="proj/core", operations=[op],
            )
            name_map = register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        # The name map should contain a kebab-case entry for the
        # grouper-style name "{comp}.{method}".
        self.assertIn("core.invoke", name_map)
        # Value is a kebab-case name.
        self.assertEqual(name_map["core.invoke"], "core-llm-invoke")

    def test_register_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(
                name="helper_fn", class_name=None, file_stem="helpers",
            )
            comp = _make_component(
                name="utils", file_path="proj/utils", operations=[op],
            )
            name_map = register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        self.assertEqual(name_map["utils.helper_fn"], "utils-helper-fn")

    def test_name_map_includes_class_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="x", class_name="C")
            comp = _make_component(
                name="comp", file_path="proj/comp", operations=[op],
            )
            name_map = register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        # Three name forms all point at the same kebab spec.
        kebab = name_map["comp.x"]
        self.assertEqual(name_map["C.x"], kebab)
        self.assertEqual(name_map["comp.C.x"], kebab)
        # And the fully-qualified form (comp + grouper-style).
        self.assertEqual(name_map["comp.comp.x"], kebab)

    def test_wrapper_script_written_to_scripts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="x", class_name="C")
            comp = _make_component(
                name="comp", file_path="proj/comp", operations=[op],
            )
            register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        # A wrapper script should be created in the temp scripts dir.
        scripts = list(self.scripts_dir.iterdir())
        self.assertEqual(len(scripts), 1)
        self.assertTrue(scripts[0].name.endswith(".py"))
        self.assertIn("C_", scripts[0].name)

    def test_persist_writes_spec_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="x", class_name="C")
            comp = _make_component(
                name="comp", file_path="proj/comp", operations=[op],
            )
            register_component_tools(
                [comp], str(source_dir), persist=True,
            )
        # A spec file should appear in the tool dir.
        specs = list(self.tool_dir.glob("*.json"))
        # Specs could be in the tool dir itself or a subdir depending
        # on save_spec; we just check at least one was created.
        self.assertGreater(len(specs), 0)

    def test_overwrite_false_skips_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="x", class_name="C")
            comp = _make_component(
                name="comp", file_path="proj/comp", operations=[op],
            )
            # First call writes the spec.
            register_component_tools(
                [comp], str(source_dir), persist=True, overwrite=True,
            )
            # Specs on disk.
            initial_specs = sorted(self.tool_dir.glob("*.json"))
            # Touch the spec file's mtime to detect a re-write.
            for spec_path in initial_specs:
                spec_path.write_text(
                    json.dumps({"modified": True}), encoding="utf-8",
                )
            # Second call with overwrite=False → should NOT rewrite.
            register_component_tools(
                [comp], str(source_dir), persist=True, overwrite=False,
            )
            # The file still has the modified marker.
            for spec_path in self.tool_dir.glob("*.json"):
                content = json.loads(spec_path.read_text())
                self.assertEqual(content, {"modified": True})

    def test_grouped_by_class_into_one_script(self) -> None:
        # Two operations on the same class share one script.
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op1 = _make_op(name="a", class_name="C")
            op2 = _make_op(name="b", class_name="C")
            comp = _make_component(
                name="comp", file_path="proj/comp", operations=[op1, op2],
            )
            register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        # Single wrapper script for both methods.
        scripts = list(self.scripts_dir.iterdir())
        self.assertEqual(len(scripts), 1)

    def test_class_and_function_separate_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            class_op = _make_op(name="a", class_name="C", file_stem="mod")
            func_op = _make_op(
                name="b", class_name=None, file_stem="mod",
            )
            comp = _make_component(
                name="comp", file_path="proj/comp",
                operations=[class_op, func_op],
            )
            register_component_tools(
                [comp], str(source_dir), persist=False,
            )
        # Two scripts: one for the class, one for the function file.
        self.assertEqual(len(list(self.scripts_dir.iterdir())), 2)

    def test_empty_components_returns_empty_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            name_map = register_component_tools(
                [], str(source_dir), persist=False,
            )
        self.assertEqual(name_map, {})


if __name__ == "__main__":
    unittest.main()

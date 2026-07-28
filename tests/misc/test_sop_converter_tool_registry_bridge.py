"""Unit tests for :mod:`extensions.sop_converter.tool_registry_bridge`.

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
import os
import shlex
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from clawcodex_ext.agent.tool_authoring.call_handlers.bash import execute_bash
from extensions.sop_converter import tool_registry_bridge as trb
from extensions.sop_converter.agent_catalog_resolver import HOME_ROOT_ENV
from extensions.sop_converter.resource_catalog import (
    DUAL_WRITE_ENV,
    PAYLOAD_REF_ENV,
    SESSION_ID_ENV,
    ResourceCatalog,
)
from extensions.sop_converter.source_parser import (
    ParamSpec,
    SourceComponent,
    SourceOperation,
    SourceCodeParser,
)
from extensions.sop_converter.tool_registry_bridge import (
    _coerce_param_expression,
    _enrich_bridge_params,
    _generate_cli_handler_stub,
    _generate_method_stub,
    _generate_wrapper_script,
    _infer_extra_sys_path_entries,
    _is_cli_handler_op,
    _merge_init_and_method_params,
    _param_signature_parts,
    _parse_cli_dispatch_map,
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
    is_async_generator: bool = False,
) -> SourceOperation:
    return SourceOperation(
        name=name,
        description=description,
        parameters=parameters or [],
        return_type=return_type,
        class_name=class_name,
        file_stem=file_stem,
        is_async=is_async,
        is_async_generator=is_async_generator,
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


def _catalog_payload(call_impl: str, flag: str) -> dict:
    parts = shlex.split(call_impl)
    idx = parts.index(flag)
    return json.loads(parts[idx + 1])


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
            _strip_optional_union("Union[str, None]"),
            "str",
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
            _strip_optional_union("Optional[NoneType, str]"),
            "str",
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

    def test_uuid_types_map_to_string(self) -> None:
        for hint in ["UUID", "UUID4", "Optional[UUID]", "UUID | None"]:
            with self.subTest(hint=hint):
                self.assertEqual(_type_hint_to_json_type(hint), "string")

    def test_optional_typing_reduces_first(self) -> None:
        self.assertEqual(
            _type_hint_to_json_type("Optional[int]"),
            "integer",
        )
        self.assertEqual(
            _type_hint_to_json_type("str | None"),
            "string",
        )

    def test_iterable_returns_array(self) -> None:
        self.assertEqual(
            _type_hint_to_json_type("Iterable[str]"),
            "array",
        )
        self.assertEqual(
            _type_hint_to_json_type("Sequence[int]"),
            "array",
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
        self.assertEqual(_to_kebab_case("video_ops.transcode"), "video-ops-transcode")

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
# _infer_extra_sys_path_entries (backend subproject imports)
# ---------------------------------------------------------------------------


class TestBackendSubprojectSysPath(unittest.TestCase):
    def test_detects_backend_subproject_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_root = root / "AgentSDK" / "data_generation_platform"
            utils_dir = app_root / "backend" / "utils"
            models_dir = app_root / "backend" / "models"
            utils_dir.mkdir(parents=True)
            models_dir.mkdir(parents=True)
            (models_dir / "constants.py").write_text(
                "DEFAULT_CHUNK_SIZE = 500\n",
                encoding="utf-8",
            )
            (utils_dir / "text_utils.py").write_text(
                textwrap.dedent(
                    """\
                    from backend.models.constants import DEFAULT_CHUNK_SIZE

                    def split_text(text: str) -> list[str]:
                        return [text[:DEFAULT_CHUNK_SIZE]]
                    """
                ),
                encoding="utf-8",
            )
            module_name = (
                "AgentSDK.data_generation_platform.backend.utils.text_utils"
            )
            entries = _infer_extra_sys_path_entries(str(root), module_name)
            self.assertEqual(entries, [str(app_root.resolve())])

    def test_skips_openjiuwen_style_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pkg = root / "openjiuwen" / "core" / "demo"
            pkg.mkdir(parents=True)
            (pkg / "demo.py").write_text(
                textwrap.dedent(
                    """\
                    def run() -> str:
                        return "ok"
                    """
                ),
                encoding="utf-8",
            )
            entries = _infer_extra_sys_path_entries(
                str(root), "openjiuwen.core.demo.demo"
            )
            self.assertEqual(entries, [])

    def test_detects_sibling_src_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            demo = root / "llm_finetuning_demo"
            src = demo / "src"
            src.mkdir(parents=True)
            (src / "run_data_pipeline.py").write_text(
                "def run_data_pipeline():\n    return {}\n",
                encoding="utf-8",
            )
            (demo / "run_full_pipeline.py").write_text(
                textwrap.dedent(
                    """\
                    import os, sys
                    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                    from run_data_pipeline import run_data_pipeline

                    def main():
                        run_data_pipeline()
                    """
                ),
                encoding="utf-8",
            )
            entries = _infer_extra_sys_path_entries(
                str(root), "llm_finetuning_demo.run_full_pipeline"
            )
            self.assertEqual(entries, [str(src.resolve())])

    def test_no_sibling_src_means_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pkg = root / "flat_sdk"
            pkg.mkdir()
            (pkg / "api.py").write_text("def ping():\n    return 1\n", encoding="utf-8")
            entries = _infer_extra_sys_path_entries(str(root), "flat_sdk.api")
            self.assertEqual(entries, [])


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
        content = script_path.read_text(encoding="utf-8")
        self.assertIn("Calc (proj.calc)", content)
        # The method name is wired in.
        self.assertIn("def compute", content)
        # sys.path is injected.
        self.assertIn(str(source_dir), content)

    def test_bundle_venv_metadata_injected_when_requested(self) -> None:
        op = _make_op(name="compute", class_name="Calc")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            bundle_dir = root / "bundle"
            source_dir.mkdir()
            bundle_dir.mkdir()
            script_path = _generate_wrapper_script(
                [op],
                class_name="Calc",
                module_name="proj.calc",
                file_stem="calc",
                source_dir=str(source_dir),
                bundle_dir=bundle_dir,
                bundle_venv_python=str(bundle_dir / ".venv" / "bin" / "python"),
                sdk_requirements=("openai>=1", "pydantic>=2"),
                repo_root=str(root),
            )
        content = script_path.read_text(encoding="utf-8")
        self.assertIn("_BUNDLE_DIR", content)
        self.assertIn("_normalize_bootstrap_path", content)
        self.assertIn("target = bundle_venv_python(bundle_dir).resolve()", content)
        self.assertIn("ensure_bundle_venv_and_reexec", content)
        self.assertIn("openai>=1", content)
        self.assertIn(str(bundle_dir.resolve()), content)

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
        content = script_path.read_text(encoding="utf-8")
        self.assertNotIn("openjiuwen", content)
        self.assertNotIn("_suppress_sdk_logging", content)
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

    def test_async_generator_uses_run_async_iter(self) -> None:
        op = _make_op(
            name="stream_go",
            class_name="X",
            is_async=True,
            is_async_generator=True,
            return_type="AsyncIterator[Any]",
            parameters=[_make_param("agent_team", "str"), _make_param("inputs", "Any")],
        )
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
        self.assertIn("def _run_async_iter(make_gen):", content)
        self.assertIn("async for item in make_gen():", content)
        self.assertIn("return _run_async_iter(lambda: _get_instance", content)
        self.assertIn(".stream_go(", content)
        self.assertNotIn("asyncio.run(_get_instance", content.split("def stream_go")[1])

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

    def test_wrapper_emits_imports_for_sdk_default_symbols(self) -> None:
        source = textwrap.dedent(
            """\
            from demo_pkg.enums import WidgetMode, WidgetStatus

            class Handler:
                def __init__(
                    self,
                    name: str,
                    teammate_mode=WidgetMode.BUILD_MODE,
                ) -> None:
                    self.name = name
                    self.teammate_mode = teammate_mode

                def run(self, status=WidgetStatus.IDLE):
                    \"\"\"Run handler.\"\"\"
                    return status
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "enums.py").write_text(
                textwrap.dedent(
                    """\
                    from enum import Enum

                    class WidgetMode(str, Enum):
                        BUILD_MODE = "build"

                    class WidgetStatus(str, Enum):
                        IDLE = "idle"
                    """
                )
            )
            (pkg / "handler.py").write_text(source)

            init_params = [
                _make_param("name", "str", required=True),
                _make_param(
                    "teammate_mode", "WidgetMode", required=False, default="WidgetMode.BUILD_MODE"
                ),
            ]
            op = SourceOperation(
                name="run",
                description="Run handler.",
                class_name="Handler",
                file_stem="handler",
                parameters=[
                    _make_param(
                        "status", "WidgetStatus", required=False, default="WidgetStatus.IDLE"
                    ),
                ],
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name="Handler",
                module_name="demo_pkg.handler",
                file_stem="handler",
                source_dir=str(tmp),
                init_params=init_params,
            )

            content = script_path.read_text()
            self.assertIn("from demo_pkg.enums import WidgetMode, WidgetStatus", content)
            path_idx = content.index("sys.path.insert(0, _SOURCE_DIR)")
            import_idx = content.index("from demo_pkg.enums import WidgetMode, WidgetStatus")
            self.assertLess(path_idx, import_idx)

            compile(content, str(script_path), "exec")

    def test_wrapper_injects_backend_subproject_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app_root = root / "AgentSDK" / "data_generation_platform"
            utils_dir = app_root / "backend" / "utils"
            utils_dir.mkdir(parents=True)
            models_dir = app_root / "backend" / "models"
            models_dir.mkdir(parents=True)
            (models_dir / "constants.py").write_text(
                textwrap.dedent(
                    """\
                    DEFAULT_CHUNK_SIZE = 100
                    DEFAULT_CHUNK_OVERLAP = 10
                    SPLIT_METHOD_SENTENCE = "sentence"
                    """
                ),
                encoding="utf-8",
            )
            (utils_dir / "text_utils.py").write_text(
                textwrap.dedent(
                    """\
                    from backend.models.constants import DEFAULT_CHUNK_SIZE

                    def split_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[str]:
                        return [text[:chunk_size]]
                    """
                ),
                encoding="utf-8",
            )

            op = SourceOperation(
                name="split_text",
                description="Split text.",
                parameters=[
                    _make_param("text", "str", required=True),
                    _make_param(
                        "chunk_size",
                        "int",
                        required=False,
                        default="DEFAULT_CHUNK_SIZE",
                    ),
                ],
                file_stem="text_utils",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name=(
                    "AgentSDK.data_generation_platform.backend.utils.text_utils"
                ),
                file_stem="text_utils",
                source_dir=str(root),
                scripts_dir=self.scripts_dir,
            )
            content = script_path.read_text(encoding="utf-8")
            self.assertIn(str(app_root.resolve()), content)
            path_idx = content.index("sys.path.insert(0, _SOURCE_DIR)")
            extra_idx = content.index(
                f"sys.path.insert(0, _normalize_bootstrap_path({str(app_root.resolve())!r}))"
            )
            self.assertLess(extra_idx, path_idx)
            if (
                "from AgentSDK.data_generation_platform.backend.utils.text_utils import"
                in content
            ):
                import_idx = content.index(
                    "from AgentSDK.data_generation_platform.backend.utils.text_utils import"
                )
                self.assertLess(path_idx, import_idx)

            args = json.dumps({"text": "hello world from backend subproject test"})
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "split_text", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()), ["hello world from backend subproject test"])

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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
            comp_name="core",
        )
        # {comp}.{class}.{method} → "core.LLM.invoke" → kebab.
        self.assertEqual(spec.name, "core-llm-invoke")

    def test_class_method_without_comp_name(self) -> None:
        op = _make_op(name="invoke", class_name="LLM")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        # Falls back to {class}.{method}.
        self.assertEqual(spec.name, "llm-invoke")

    def test_standalone_function_with_comp(self) -> None:
        op = _make_op(name="load_config", class_name=None, file_stem="utils")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
            comp_name="helpers",
        )
        self.assertEqual(spec.name, "helpers-load-config")

    def test_standalone_function_no_comp_falls_back_to_file_stem(self) -> None:
        op = _make_op(name="load_config", class_name=None, file_stem="utils")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        self.assertEqual(spec.name, "utils-load-config")

    def test_no_comp_no_file_stem_kebab_converts(self) -> None:
        # Even without a comp or file_stem, the raw name goes through
        # kebab-case conversion. "load_config" → "load-config".
        op = _make_op(name="load_config", class_name=None, file_stem="")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        self.assertEqual(spec.name, "load-config")

    def test_call_type_is_bash(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        self.assertEqual(spec.call_type, "bash")

    def test_call_impl_uses_script_path(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        self.assertEqual(
            spec.input_schema["properties"]["foo"]["default"],
            "bar",
        )

    def test_aliases_with_comp_name(self) -> None:
        op = _make_op(name="x", class_name="C")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
            comp_name="alpha",
        )
        # First alias is the fully-qualified {comp}.{class}.{method}.
        self.assertIn("alpha.C.x", spec.aliases)

    def test_aliases_short_form_with_dotted_comp(self) -> None:
        # When comp_name is "openjiuwen.core" (multi-segment), an
        # additional short alias drops the first segment.
        op = _make_op(name="x", class_name="C")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
            comp_name="openjiuwen.core",
        )
        # Original alias present.
        self.assertIn("openjiuwen.core.C.x", spec.aliases)
        # Short alias present.
        self.assertIn("core.C.x", spec.aliases)

    def test_source_is_sop_converter(self) -> None:
        op = _make_op(name="x")
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
        )
        self.assertEqual(spec.source, "sop-converter")

    def test_generates_search_tags(self) -> None:
        op = _make_op(
            name="run_team_cli",
            description="Bring up the Team CLI.",
            class_name=None,
        )
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path=self.script_path,
            comp_name="openjiuwen.agent_teams.cli",
        )
        self.assertTrue(spec.tags)
        self.assertIn("run team cli", spec.tags)
        self.assertIn("run_team_cli", spec.tags)
        self.assertIn("cli", spec.tags)

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
            op,
            source_dir="/tmp",
            script_path=self.script_path,
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
                name="core",
                file_path="proj/core",
                operations=[op],
            )
            name_map = register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
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
                name="helper_fn",
                class_name=None,
                file_stem="helpers",
            )
            comp = _make_component(
                name="utils",
                file_path="proj/utils",
                operations=[op],
            )
            name_map = register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
            )
        self.assertEqual(name_map["utils.helper_fn"], "utils-helper-fn")

    def test_name_map_includes_class_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            op = _make_op(name="x", class_name="C")
            comp = _make_component(
                name="comp",
                file_path="proj/comp",
                operations=[op],
            )
            name_map = register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
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
                name="comp",
                file_path="proj/comp",
                operations=[op],
            )
            register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
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
                name="comp",
                file_path="proj/comp",
                operations=[op],
            )
            register_component_tools(
                [comp],
                str(source_dir),
                persist=True,
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
                name="comp",
                file_path="proj/comp",
                operations=[op],
            )
            # First call writes the spec.
            register_component_tools(
                [comp],
                str(source_dir),
                persist=True,
                overwrite=True,
            )
            # Specs on disk.
            initial_specs = sorted(self.tool_dir.glob("*.json"))
            # Touch the spec file's mtime to detect a re-write.
            for spec_path in initial_specs:
                spec_path.write_text(
                    json.dumps({"modified": True}),
                    encoding="utf-8",
                )
            # Second call with overwrite=False → should NOT rewrite.
            register_component_tools(
                [comp],
                str(source_dir),
                persist=True,
                overwrite=False,
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
                name="comp",
                file_path="proj/comp",
                operations=[op1, op2],
            )
            register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
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
                name="b",
                class_name=None,
                file_stem="mod",
            )
            comp = _make_component(
                name="comp",
                file_path="proj/comp",
                operations=[class_op, func_op],
            )
            register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
            )
        # Two scripts: one for the class, one for the function file.
        self.assertEqual(len(list(self.scripts_dir.iterdir())), 2)

    def test_register_create_kind_tool_enriches_call_impl(self) -> None:
        """F-55 L1: create-kind ops get --catalog-metadata + bundle env prefix."""
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            bundle_dir = Path(tmp) / "bundle"
            bundle_dir.mkdir()
            op = _make_op(
                name="build_agent",
                class_name="AgentBuilder",
                return_type="Dict[str, Any]",
            )
            comp = _make_component(
                name="agentbuilder",
                file_path="proj/agentbuilder",
                operations=[op],
            )
            name_map = register_component_tools(
                [comp],
                str(source_dir),
                persist=False,
                bundle_dir=bundle_dir,
                bundle_id="test-bundle",
            )
        self.assertIn("agentbuilder.build_agent", name_map)

    def test_lifecycle_catalog_payload_uses_alias_aware_resource_type(self) -> None:
        """Create/invoke pairs match by type identity, not SDK-specific field names."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "generic_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "types.py").write_text(
                textwrap.dedent(
                    """
                    from dataclasses import dataclass

                    @dataclass
                    class WidgetConfig:
                        name: str
                    """
                ).strip(),
                encoding="utf-8",
            )
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    from .types import WidgetConfig

                    def create_widget(name: str) -> WidgetConfig:
                        \"\"\"Create a reusable widget configuration.\"\"\"
                        return WidgetConfig(name=name)
                    """
                ).strip(),
                encoding="utf-8",
            )
            (sdk_dir / "runner.py").write_text(
                textwrap.dedent(
                    """
                    from .types import WidgetConfig as PublicConfig

                    class WidgetRunner:
                        def invoke(self, widget: PublicConfig, query: str) -> dict:
                            \"\"\"Invoke a previously created widget.\"\"\"
                            return {"error_code": "resource_not_found", "query": query}
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            components = parser.parse()
            name_map = register_component_tools(
                components,
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="generic-bundle",
            )

            create_tool = name_map["generic_sdk.create_widget"]
            invoke_tool = name_map["generic_sdk.WidgetRunner.invoke"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(create_spec["output_schema"]["type"], "object")
            self.assertEqual(
                create_spec["output_schema"]["properties"]["created_persisted"],
                {"const": True},
            )
            self.assertEqual(
                set(create_spec["output_schema"]["required"]),
                {
                    "resource_ref",
                    "resource_type",
                    "created_persisted",
                    "resource_catalog_path",
                },
            )
            invoke_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{invoke_tool}.json").read_text(
                    encoding="utf-8"
                )
            )

            create_meta = _catalog_payload(create_spec["call_impl"], "--catalog-metadata")
            fallback_meta = _catalog_payload(invoke_spec["call_impl"], "--catalog-fallback")
            expected_type = "generic_sdk_types_widgetconfig"
            self.assertEqual(create_meta["resource_type"], expected_type)
            self.assertEqual(fallback_meta["resource_type"], expected_type)
            self.assertEqual(fallback_meta["handle_field"], "widget")
            self.assertEqual(fallback_meta["query_arg"], "query")

    def test_create_catalog_write_accepts_generic_name_handle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "generic_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    def create_widget(name: str) -> dict:
                        \"\"\"Create a reusable widget by name.\"\"\"
                        return {"name": name, "status": "created"}
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            name_map = register_component_tools(
                parser.parse(),
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="generic-bundle",
            )

            create_tool = name_map["generic_sdk.create_widget"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            stdout = execute_bash(
                create_spec["call_impl"],
                {"json_args": json.dumps({"name": "verify-bot"})},
            )
            created = json.loads(stdout.strip().splitlines()[-1])
            self.assertEqual(created["agent_id"], "verify-bot")
            self.assertEqual(created["resource_ref"], "verify-bot")
            self.assertTrue(created["created_persisted"])

            catalog = ResourceCatalog.load(
                bundle_dir / ".clawcodex" / "resource-catalog.json"
            )
            records = catalog.find_by_resource_id("verify-bot")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].resource_id, "verify-bot")
            self.assertEqual(records[0].payload["handle_field"], "name")

    def test_create_catalog_callable_without_handle_is_resource_handle_missing(
        self,
    ) -> None:
        """Opaque callables with empty config must not recurse or catalog_write_failed.

        Regression: ``config: {}`` made ``_to_jsonable({}) is not {}`` always true,
        so ``_extract_resource_handle`` looped until max recursion instead of
        returning ``resource_handle_missing``.
        """
        from clawcodex_ext.agent.tool_authoring.call_handlers.bash import BashCallError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "callable_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    from typing import Any, Callable, Dict

                    def create_opaque_loader(config: Dict[str, Any]) -> Callable:
                        \"\"\"Return a nested loader function with no stable id.\"\"\"
                        def loader():
                            return config.get("data_paths", [])
                        return loader
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            name_map = register_component_tools(
                parser.parse(),
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="callable-bundle",
            )
            create_tool = name_map["callable_sdk.create_opaque_loader"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.assertRaises(BashCallError) as raised:
                execute_bash(
                    create_spec["call_impl"],
                    {"json_args": json.dumps({"config": {}})},
                )
            blob = (raised.exception.stderr or "") + (raised.exception.stdout or "")
            payload = None
            for line in reversed(blob.splitlines()):
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
            self.assertIsNotNone(payload, f"no JSON payload in output: {blob[-2000:]}")
            assert payload is not None
            self.assertEqual(payload.get("error_code"), "resource_handle_missing")
            self.assertIs(payload.get("created_persisted"), False)
            self.assertNotIn(
                "maximum recursion depth exceeded",
                str(payload.get("error", "")),
            )
            self.assertNotEqual(payload.get("error_code"), "catalog_write_failed")
            catalog_path = bundle_dir / ".clawcodex" / "resource-catalog.json"
            self.assertFalse(
                catalog_path.exists(),
                "opaque callable must not write a catalog record",
            )

    def test_create_catalog_dual_write_writes_bundle_and_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "generic_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    def create_widget(name: str) -> dict:
                        \"\"\"Create a reusable widget by name.\"\"\"
                        return {"name": name, "status": "created"}
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()
            home = root / "clawcodex-home"
            home.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            name_map = register_component_tools(
                parser.parse(),
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="generic-bundle",
            )
            create_tool = name_map["generic_sdk.create_widget"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            with patch.dict(
                os.environ,
                {DUAL_WRITE_ENV: "1", HOME_ROOT_ENV: str(home)},
            ):
                stdout = execute_bash(
                    create_spec["call_impl"],
                    {"json_args": json.dumps({"name": "dual-bot"})},
                )
            created = json.loads(stdout.strip().splitlines()[-1])
            self.assertTrue(created["created_persisted"])
            self.assertEqual(sorted(created["written_layers"]), ["bundle", "user"])
            self.assertIn("bundle", created["catalog_paths"])
            self.assertIn("user", created["catalog_paths"])
            bundle_catalog = Path(created["catalog_paths"]["bundle"])
            user_catalog = Path(created["catalog_paths"]["user"])
            self.assertTrue(bundle_catalog.is_file())
            self.assertTrue(user_catalog.is_file())
            self.assertEqual(
                created["resource_catalog_path"],
                str(bundle_catalog),
            )
            self.assertTrue(
                ResourceCatalog.load(bundle_catalog).find_by_resource_id("dual-bot")
            )
            self.assertTrue(
                ResourceCatalog.load(user_catalog).find_by_resource_id("dual-bot")
            )

    def test_create_catalog_payload_ref_env_spills_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "generic_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    def create_widget(name: str) -> dict:
                        \"\"\"Create a reusable widget by name.\"\"\"
                        return {"name": name, "status": "created", "blob": "x" * 100}
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            name_map = register_component_tools(
                parser.parse(),
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="generic-bundle",
            )
            create_tool = name_map["generic_sdk.create_widget"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            with patch.dict(os.environ, {PAYLOAD_REF_ENV: "1"}, clear=False):
                stdout = execute_bash(
                    create_spec["call_impl"],
                    {"json_args": json.dumps({"name": "spill-bot"})},
                )
            created = json.loads(stdout.strip().splitlines()[-1])
            self.assertTrue(created["created_persisted"])
            catalog_path = Path(created["resource_catalog_path"])
            matches = ResourceCatalog.load(catalog_path).find_by_resource_id("spill-bot")
            self.assertTrue(matches)
            stored = ResourceCatalog.load(catalog_path).get_stored(
                matches[0].resource_type, "spill-bot"
            )
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.payload["kind"], "payload_ref")
            self.assertTrue(stored.payload.get("ref") or stored.payload.get("path"))

    def test_create_catalog_session_id_writes_session_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "proj"
            sdk_dir = source_dir / "generic_sdk"
            sdk_dir.mkdir(parents=True)
            (sdk_dir / "__init__.py").write_text("", encoding="utf-8")
            (sdk_dir / "factory.py").write_text(
                textwrap.dedent(
                    """
                    def create_widget(name: str) -> dict:
                        \"\"\"Create a reusable widget by name.\"\"\"
                        return {"name": name, "status": "created"}
                    """
                ).strip(),
                encoding="utf-8",
            )
            bundle_dir = root / "bundle"
            bundle_dir.mkdir()
            home = root / "clawcodex-home"
            home.mkdir()

            parser = SourceCodeParser(str(source_dir), extern_only=True)
            name_map = register_component_tools(
                parser.parse(),
                str(source_dir),
                persist=True,
                bundle_dir=bundle_dir,
                bundle_id="generic-bundle",
            )
            create_tool = name_map["generic_sdk.create_widget"]
            create_spec = json.loads(
                (bundle_dir / "agent-tools" / f"{create_tool}.json").read_text(
                    encoding="utf-8"
                )
            )
            with patch.dict(
                os.environ,
                {SESSION_ID_ENV: "sess-create-1", HOME_ROOT_ENV: str(home)},
            ):
                stdout = execute_bash(
                    create_spec["call_impl"],
                    {"json_args": json.dumps({"name": "session-bot"})},
                )
            created = json.loads(stdout.strip().splitlines()[-1])
            self.assertTrue(created["created_persisted"])
            self.assertIn("session", created["written_layers"])
            self.assertIn("session", created["catalog_paths"])
            session_catalog = Path(created["catalog_paths"]["session"])
            self.assertTrue(session_catalog.is_file())
            self.assertEqual(
                session_catalog,
                home / "sessions" / "sess-create-1" / "sop-resources.json",
            )
            self.assertTrue(
                ResourceCatalog.load(session_catalog).find_by_resource_id("session-bot")
            )
            # Session is additive; default base layer (bundle) is also written.
            self.assertIn("bundle", created["written_layers"])
            self.assertTrue(
                (bundle_dir / ".clawcodex" / "resource-catalog.json").is_file()
            )

    def test_empty_components_returns_empty_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            name_map = register_component_tools(
                [],
                str(source_dir),
                persist=False,
            )
        self.assertEqual(name_map, {})


class TestClassInitParamsWrapper(unittest.TestCase):
    def test_wrapper_passes_init_kwargs_to_constructor(self) -> None:
        source = '''
def team_memory_dir(team_name: str = "team") -> str:
    """Resolve team memory directory path."""
    return f"/tmp/{team_name}/team-memory"

class SharedMemoryManager:
    """Team shared memory."""

    def __init__(self, team_memory_dir: str) -> None:
        self.team_memory_dir = team_memory_dir

    def ensure_dir(self) -> str:
        """Ensure team-memory directory exists."""
        import os
        os.makedirs(self.team_memory_dir, exist_ok=True)
        return self.team_memory_dir
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            py_file = pkg / "memory.py"
            py_file.write_text(source)

            init_params = [ParamSpec(name="team_memory_dir", type_hint="str", required=True)]
            op = SourceOperation(
                name="ensure_dir",
                description="Ensure team-memory directory exists.",
                class_name="SharedMemoryManager",
                file_stem="memory",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name="SharedMemoryManager",
                module_name="demo_pkg.memory",
                file_stem="memory",
                source_dir=str(tmp),
                init_params=init_params,
            )

            args = json.dumps({"team_memory_dir": "/tmp/my-team/team-memory"})
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "ensure_dir", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout.strip()),
                "/tmp/my-team/team-memory",
            )
            self.assertTrue(Path("/tmp/my-team/team-memory").is_dir())

    def test_operation_to_spec_merges_init_params(self) -> None:
        op = SourceOperation(
            name="ensure_dir",
            description="Ensure dir.",
            class_name="SharedMemoryManager",
        )
        init_params = [ParamSpec(name="team_memory_dir", type_hint="str", required=True)]
        spec = operation_to_spec(
            op,
            source_dir="/tmp",
            script_path="/tmp/wrapper.py",
            comp_name="memory",
            init_params=init_params,
        )
        self.assertIn("team_memory_dir", spec.input_schema["properties"])
        self.assertIn("team_memory_dir", spec.input_schema.get("required", []))

    def test_merge_puts_required_init_params_before_optional(self) -> None:
        init_params = [
            ParamSpec(name="team_memory_dir", type_hint="str", required=True),
            ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
        ]
        merged = _merge_init_and_method_params(init_params, [])
        self.assertEqual([p.name for p in merged], ["team_memory_dir", "sys_operation"])
        signature = ", ".join(_param_signature_parts(merged))
        self.assertEqual(signature, "team_memory_dir, sys_operation=None")

    def test_generated_stub_is_valid_python(self) -> None:
        import ast

        init_params = [
            ParamSpec(name="team_memory_dir", type_hint="str", required=True),
            ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
        ]
        op = SourceOperation(
            name="ensure_dir",
            description="Ensure team-memory directory exists.",
            class_name="SharedMemoryManager",
        )
        stub, _imports = _generate_method_stub(
            op,
            is_class_method=True,
            module_name="openjiuwen.agent_teams.memory.shared_memory",
            init_params=init_params,
        )
        ast.parse(stub)
        self.assertIn("def ensure_dir(team_memory_dir, sys_operation=None)", stub)

    def test_wrapper_with_optional_init_param_is_runnable(self) -> None:
        source = """
class SharedMemoryManager:
    def __init__(self, team_memory_dir: str, sys_operation=None) -> None:
        self.team_memory_dir = team_memory_dir

    def ensure_dir(self) -> str:
        import os
        os.makedirs(self.team_memory_dir, exist_ok=True)
        return self.team_memory_dir
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "memory.py").write_text(source)

            init_params = [
                ParamSpec(name="team_memory_dir", type_hint="str", required=True),
                ParamSpec(name="sys_operation", type_hint="str", required=False, default="None"),
            ]
            op = SourceOperation(
                name="ensure_dir",
                description="Ensure.",
                class_name="SharedMemoryManager",
                file_stem="memory",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name="SharedMemoryManager",
                module_name="demo_pkg.memory",
                file_stem="memory",
                source_dir=str(tmp),
                init_params=init_params,
            )
            import ast

            ast.parse(script_path.read_text(encoding="utf-8"))

            args = json.dumps({"team_memory_dir": "/tmp/p0-fix-team-memory"})
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "ensure_dir", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(Path("/tmp/p0-fix-team-memory").is_dir())


# ---------------------------------------------------------------------------
# Pydantic / dataclass parameter coercion (wrapper runtime)
# ---------------------------------------------------------------------------


class TestPydanticParamCoercion(unittest.TestCase):
    """JSON dict tool args must be coerced back to SDK model instances."""

    def setUp(self) -> None:
        self._cleanup, self.tool_dir, self.scripts_dir = _isolated_dirs()
        self.addCleanup(self._cleanup)

    def test_stub_includes_model_coercion(self) -> None:
        op = SourceOperation(
            name="create_llm_agent",
            description="Create an LLM agent.",
            parameters=[
                ParamSpec(
                    name="agent_config",
                    type_hint="AgentConfig",
                    required=True,
                ),
            ],
            file_stem="agent",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "agent.py").write_text(
                textwrap.dedent(
                    '''
                    from pydantic import BaseModel


                    class AgentConfig(BaseModel):
                        controller_type: str = "react"
                        model: str = "gpt-4"
                    '''
                ),
                encoding="utf-8",
            )
            stub, imports = _generate_method_stub(
                op,
                is_class_method=False,
                module_name="demo_pkg.agent",
                source_dir=str(tmp),
            )
            self.assertIn("_coerce_sdk_type(AgentConfig, agent_config)", stub)
            self.assertIn(("demo_pkg.agent", "AgentConfig"), imports)

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("pydantic") is not None,
        "pydantic not installed",
    )
    def test_wrapper_coerces_pydantic_dict_at_runtime(self) -> None:
        source = textwrap.dedent(
            '''
            from pydantic import BaseModel


            class AgentConfig(BaseModel):
                controller_type: str = "react"
                model: str = "gpt-4"


            def create_llm_agent(agent_config: AgentConfig) -> str:
                """Create agent and return controller type."""
                return agent_config.controller_type
            '''
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "agent.py").write_text(source, encoding="utf-8")

            op = SourceOperation(
                name="create_llm_agent",
                description="Create agent.",
                parameters=[
                    ParamSpec(
                        name="agent_config",
                        type_hint="AgentConfig",
                        required=True,
                    ),
                ],
                file_stem="agent",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="demo_pkg.agent",
                file_stem="agent",
                source_dir=str(tmp),
                scripts_dir=self.scripts_dir,
            )
            content = script_path.read_text(encoding="utf-8")
            path_idx = content.index("sys.path.insert(0, _SOURCE_DIR)")
            import_idx = content.index("from demo_pkg.agent import AgentConfig")
            self.assertLess(path_idx, import_idx)

            args = json.dumps(
                {"agent_config": {"controller_type": "react", "model": "gpt-4"}}
            )
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "create_llm_agent", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()), "react")

    def test_wrapper_coerces_dataclass_init_param(self) -> None:
        source = textwrap.dedent(
            '''
            from dataclasses import dataclass


            @dataclass
            class Settings:
                mode: str


            class Service:
                def __init__(self, settings: Settings) -> None:
                    self.settings = settings

                def mode(self) -> str:
                    return self.settings.mode
            '''
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "service.py").write_text(source, encoding="utf-8")

            init_params = [
                ParamSpec(name="settings", type_hint="Settings", required=True),
            ]
            op = SourceOperation(
                name="mode",
                description="Return settings mode.",
                class_name="Service",
                file_stem="service",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name="Service",
                module_name="demo_pkg.service",
                file_stem="service",
                source_dir=str(tmp),
                init_params=init_params,
                scripts_dir=self.scripts_dir,
            )
            args = json.dumps({"settings": {"mode": "debug"}})
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "mode", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()), "debug")

    def test_wrapper_resolves_model_alias_from_import_context(self) -> None:
        """When two modules define the same name, coercion uses the imported alias."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pkg = tmp / "demo_pkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "new_config.py").write_text(
                textwrap.dedent(
                    '''
                    from dataclasses import dataclass


                    @dataclass
                    class ReActAgentConfig:
                        model: str = "gpt-4"
                    '''
                ),
                encoding="utf-8",
            )
            (pkg / "legacy_config.py").write_text(
                textwrap.dedent(
                    '''
                    from dataclasses import dataclass


                    @dataclass
                    class LegacyReActAgentConfig:
                        controller_type: str = "react"
                        model: str = "gpt-4"


                    ReActAgentConfig = LegacyReActAgentConfig
                    '''
                ),
                encoding="utf-8",
            )
            (pkg / "agent.py").write_text(
                textwrap.dedent(
                    '''
                    from demo_pkg.legacy_config import ReActAgentConfig


                    def create_llm_agent(agent_config: ReActAgentConfig) -> str:
                        """Create agent and return controller type."""
                        return agent_config.controller_type
                    '''
                ),
                encoding="utf-8",
            )

            op = SourceOperation(
                name="create_llm_agent",
                description="Create agent.",
                parameters=[
                    ParamSpec(
                        name="agent_config",
                        type_hint="ReActAgentConfig",
                        required=True,
                    ),
                ],
                file_stem="agent",
            )
            script_path = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="demo_pkg.agent",
                file_stem="agent",
                source_dir=str(tmp),
                scripts_dir=self.scripts_dir,
            )
            content = script_path.read_text(encoding="utf-8")
            # The wrapper must import the legacy class, not the new one.
            self.assertIn("from demo_pkg.legacy_config import LegacyReActAgentConfig", content)
            self.assertNotIn("from demo_pkg.new_config import ReActAgentConfig", content)

            args = json.dumps({"agent_config": {"controller_type": "react", "model": "gpt-4"}})
            result = __import__("subprocess").run(
                [__import__("sys").executable, str(script_path), "create_llm_agent", args],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.strip()), "react")

        jiouwen_root = Path("D:/projects/JiuwenAgent")
        llm_agent_py = (
            jiouwen_root
            / "openjiuwen"
            / "core"
            / "application"
            / "llm_agent"
            / "llm_agent.py"
        )
        if not llm_agent_py.is_file():
            self.skipTest("JiuwenAgent source tree not available")

        from extensions.sop_converter.source_parser import SourceCodeParser

        parser = SourceCodeParser(str(jiouwen_root / "openjiuwen"))
        components = parser.parse()
        llm_ops = [
            op
            for comp in components
            for op in comp.operations
            if op.file_stem == "llm_agent" and op.name == "create_llm_agent"
        ]
        self.assertTrue(llm_ops, "create_llm_agent operation not found in SDK parse")
        op = llm_ops[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="openjiuwen.core.application.llm_agent.llm_agent",
                file_stem="llm_agent",
                source_dir=str(jiouwen_root),
                scripts_dir=Path(tmpdir),
            )
            content = script_path.read_text(encoding="utf-8")
            self.assertIn(
                "from openjiuwen.core.single_agent.legacy.config import LegacyReActAgentConfig",
                content,
            )
            self.assertNotIn(
                "from openjiuwen.core.single_agent.agents.react_agent import ReActAgentConfig",
                content,
            )
            self.assertIn(
                "_coerce_sdk_type(LegacyReActAgentConfig, agent_config)",
                content,
            )
            compile(content, str(script_path), "exec")


# ---------------------------------------------------------------------------
# CLI handler subprocess bridge (F-52)
# ---------------------------------------------------------------------------


_SAMPLE_CLI = textwrap.dedent(
    '''\
    """Sample CLI module."""
    import argparse


    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="sample")
        sub = parser.add_subparsers(dest="command")
        proj = sub.add_parser("project", help="Multi-project management")
        proj.add_argument(
            "project_action",
            choices=["list", "create"],
            help="Project action",
        )
        return parser


    def cmd_project(args: argparse.Namespace) -> int:
        """C1: Multi-project management commands."""
        if args.project_action == "list":
            print("no projects")
            return 0
        print(f"created:{getattr(args, 'name', '')}")
        return 0


    def main(argv=None) -> int:
        parser = build_parser()
        args = parser.parse_args(argv)
        command = args.command
        if command == "project":
            return cmd_project(args)
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
)


class TestCliHandlerBridge(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        pkg = self.tmp / "samplepkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        self.cli_path = pkg / "cli.py"
        self.cli_path.write_text(_SAMPLE_CLI, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_parse_cli_dispatch_map(self) -> None:
        dispatch = _parse_cli_dispatch_map(self.cli_path)
        self.assertEqual(dispatch.get("cmd_project"), "project")

    def test_is_cli_handler_op(self) -> None:
        dispatch = {"cmd_project": "project"}
        op = _make_op(
            "cmd_project",
            parameters=[_make_param("args", "argparse.Namespace")],
            file_stem="cli",
        )
        self.assertTrue(_is_cli_handler_op(op, dispatch))
        self.assertFalse(_is_cli_handler_op(_make_op("build_parser"), dispatch))
        self.assertFalse(
            _is_cli_handler_op(
                _make_op("cmd_project", class_name="Helper"),
                dispatch,
            )
        )

    def test_generate_cli_handler_stub_uses_subprocess(self) -> None:
        op = _make_op("cmd_project", description="Manage projects.")
        stub = _generate_cli_handler_stub(op, subcommand="project")
        self.assertIn("subprocess.run", stub)
        self.assertIn("'project'", stub)
        self.assertNotIn("importlib.import_module", stub)

    def test_wrapper_cli_handler_runs_subprocess(self) -> None:
        import ast
        import subprocess
        import sys

        op = _make_op(
            "cmd_project",
            description="C1: Multi-project management commands.",
            parameters=[_make_param("args", "argparse.Namespace")],
            file_stem="cli",
        )
        script_path = _generate_wrapper_script(
            [op],
            class_name=None,
            module_name="samplepkg.cli",
            file_stem="cli",
            source_dir=str(self.tmp),
            cli_dispatch_map={"cmd_project": "project"},
        )
        content = script_path.read_text(encoding="utf-8")
        ast.parse(content)
        self.assertIn("CLI_PREFIX:", content)
        self.assertIn("subprocess.run", content)
        self.assertNotIn("module.cmd_project", content)

        args = json.dumps({"args": "list"})
        result = subprocess.run(
            [sys.executable, str(script_path), "cmd_project", args],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["returncode"], 0)
        self.assertIn("no projects", payload["stdout"])

    def test_operation_to_spec_cli_subcommand_schema(self) -> None:
        op = _make_op(
            "cmd_project",
            parameters=[_make_param("args", "argparse.Namespace")],
            file_stem="cli",
        )
        spec = operation_to_spec(
            op,
            source_dir=str(self.tmp),
            script_path="/tmp/fake.py",
            comp_name="samplepkg.cli",
            cli_subcommand="project",
        )
        self.assertEqual(spec.input_schema["properties"]["args"]["type"], "string")
        self.assertIn("project", spec.input_schema["properties"]["args"]["description"])


from extensions.sop_converter.sdk_serialization import (
    coerce_mapping_value,
    normalize_mapping_inputs,
)


class TestMappingInputsCoercion(unittest.TestCase):
    def test_normalize_mapping_inputs_string(self) -> None:
        self.assertEqual(normalize_mapping_inputs("ping"), {"query": "ping"})

    def test_normalize_mapping_inputs_json_string(self) -> None:
        self.assertEqual(
            normalize_mapping_inputs('{"query": "ping", "conversation_id": "s1"}'),
            {"query": "ping", "conversation_id": "s1"},
        )

    def test_normalize_mapping_inputs_dict_passthrough(self) -> None:
        payload = {"query": "hello"}
        self.assertIs(normalize_mapping_inputs(payload), payload)

    def test_coerce_mapping_value_dict_passthrough(self) -> None:
        payload = {"subject": "hi", "body": "there"}
        self.assertIs(coerce_mapping_value(payload), payload)

    def test_coerce_mapping_value_json_string(self) -> None:
        self.assertEqual(
            coerce_mapping_value('{"subject": "hi", "body": "there"}'),
            {"subject": "hi", "body": "there"},
        )

    def test_coerce_mapping_value_rejects_plain_string(self) -> None:
        with self.assertRaises(TypeError):
            coerce_mapping_value("plain email body")

    def test_coerce_inputs_any_uses_wrapper_helper(self) -> None:
        expr, imports = _coerce_param_expression("inputs", "Any", "/tmp/sdk")
        self.assertEqual(expr, "_normalize_mapping_inputs(inputs)")
        self.assertEqual(imports, set())

    def test_coerce_inputs_dict_uses_wrapper_helper(self) -> None:
        expr, imports = _coerce_param_expression(
            "inputs", "dict[str, Any]", "/tmp/sdk"
        )
        self.assertEqual(expr, "_normalize_mapping_inputs(inputs)")
        self.assertEqual(imports, set())

    def test_coerce_inputs_str_is_not_wrapped(self) -> None:
        expr, imports = _coerce_param_expression("inputs", "str", "/tmp/sdk")
        self.assertIsNone(expr)
        self.assertEqual(imports, set())

    def test_coerce_other_param_any_is_not_wrapped(self) -> None:
        expr, imports = _coerce_param_expression("payload", "Any", "/tmp/sdk")
        self.assertIsNone(expr)
        self.assertEqual(imports, set())

    def test_coerce_dict_param_uses_mapping_helper(self) -> None:
        expr, imports = _coerce_param_expression("content", "dict", "/tmp/sdk")
        self.assertEqual(expr, "_coerce_mapping_value(content)")
        self.assertEqual(imports, set())

    def test_coerce_optional_dict_param_uses_mapping_helper(self) -> None:
        expr, imports = _coerce_param_expression(
            "smtp_config", "dict | None", "/tmp/sdk"
        )
        self.assertEqual(
            expr, "None if smtp_config is None else (_coerce_mapping_value(smtp_config))"
        )
        self.assertEqual(imports, set())

    def test_generated_stub_includes_coerce_mapping_for_dict_param(self) -> None:
        op = _make_op(
            "send_email",
            parameters=[
                _make_param("to_email", "str"),
                _make_param("content", "dict"),
            ],
        )
        body, _imports = _generate_method_stub(
            op,
            is_class_method=False,
            module_name="smtp_email_sender.scripts.send_email",
            source_dir="/tmp/sdk",
        )
        self.assertIn("_coerce_mapping_value(content)", body)

    def test_operation_to_spec_dict_param_is_object_schema(self) -> None:
        op = _make_op(
            "send_email",
            parameters=[
                _make_param("to_email", "str"),
                _make_param("content", "dict", description="邮件内容配置字典"),
            ],
        )
        spec = operation_to_spec(
            op,
            source_dir="/tmp/sdk",
            script_path="/tmp/wrapper.py",
            comp_name="smtp_email_sender.scripts",
        )
        self.assertEqual(spec.input_schema["properties"]["content"]["type"], "object")

    def test_generated_stub_includes_normalize_helper(self) -> None:
        op = _make_op(
            "run_agent",
            parameters=[
                _make_param("agent", "str"),
                _make_param("inputs", "Any"),
            ],
            class_name="Runner",
        )
        body, _imports = _generate_method_stub(
            op,
            is_class_method=True,
            module_name="openjiuwen.core.runner.runner",
            init_params=[],
            source_dir="/tmp/sdk",
        )
        self.assertIn("_normalize_mapping_inputs(inputs)", body)


class TestWrapperHelpersCompile(unittest.TestCase):
    def test_embedded_helpers_are_valid_python(self) -> None:
        import py_compile
        import tempfile

        from extensions.sop_converter.sdk_serialization import (
            WRAPPER_COERCION_HELPERS,
            WRAPPER_SERIALIZATION_HELPERS,
        )

        code = WRAPPER_SERIALIZATION_HELPERS + "\n" + WRAPPER_COERCION_HELPERS
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", encoding="utf-8", delete=False
        ) as handle:
            handle.write(code)
            path = handle.name
        py_compile.compile(path, doraise=True)

        namespace: dict = {}
        exec(code, namespace)
        coerce = namespace["_coerce_mapping_value"]
        self.assertEqual(
            coerce('{"subject": "hi", "body": "there"}'),
            {"subject": "hi", "body": "there"},
        )

    def test_promote_flat_llm_agent_config_in_embedded_helpers(self) -> None:
        from extensions.sop_converter.sdk_serialization import WRAPPER_COERCION_HELPERS

        namespace: dict = {}
        exec(WRAPPER_COERCION_HELPERS, namespace)
        promote = namespace["_promote_flat_llm_agent_config"]
        flat = {
            "id": "verify-bot-2",
            "provider": "deepseek",
            "api_key": "env:DEEPSEEK_API_KEY",
            "model": "deepseek-v4-flash",
            "api_base": "https://api.deepseek.com",
        }
        promoted = promote(flat)
        self.assertEqual(promoted["id"], "verify-bot-2")
        self.assertNotIn("provider", promoted)
        self.assertNotIn("api_key", promoted)
        self.assertEqual(
            promoted["model"],
            {
                "model_provider": "deepseek",
                "model_info": {
                    "model": "deepseek-v4-flash",
                    "api_key": "env:DEEPSEEK_API_KEY",
                    "api_base": "https://api.deepseek.com",
                },
            },
        )

    def test_runtime_coerce_accepts_flat_create_payload(self) -> None:
        from dataclasses import dataclass, field

        from pydantic import BaseModel, Field

        from extensions.sop_converter.sdk_serialization import coerce_sdk_type

        class EndpointInfo(BaseModel):
            api_key: str = Field(default="")
            api_base: str = Field(min_length=1)
            model_name: str = Field(default="", alias="model")

        @dataclass
        class ModelConfig:
            model_provider: str
            model_info: EndpointInfo = field(default_factory=EndpointInfo)

        class AgentConfig(BaseModel):
            id: str = ""
            model: ModelConfig | None = None

        cfg = coerce_sdk_type(
            AgentConfig,
            {
                "id": "verify-bot-2",
                "provider": "deepseek",
                "api_key": "secret",
                "model": "deepseek-v4-flash",
                "api_base": "https://api.deepseek.com",
            },
        )
        self.assertEqual(cfg.id, "verify-bot-2")
        self.assertEqual(cfg.model.model_provider, "deepseek")
        self.assertEqual(cfg.model.model_info.model_name, "deepseek-v4-flash")
        self.assertEqual(cfg.model.model_info.api_base, "https://api.deepseek.com")
        self.assertEqual(cfg.model.model_info.api_key, "secret")

    def test_list_dict_elements_not_coerced(self) -> None:
        expr, imports = _coerce_param_expression(
            "prompt_template",
            "List[Dict]",
            "/tmp/sdk",
            module_path="openjiuwen.core.application.llm_agent.llm_agent",
        )
        self.assertIsNone(expr)
        self.assertEqual(imports, set())

    def test_generated_wrapper_passes_py_compile(self) -> None:
        cleanup, _tool_dir, scripts_dir = _isolated_dirs()
        self.addCleanup(cleanup)
        with tempfile.TemporaryDirectory() as tmp:
            op = _make_op(
                "create_llm_agent",
                parameters=[_make_param("agent_config", "ReActAgentConfig")],
                file_stem="llm_agent",
            )
            script = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="demo.mod",
                file_stem="llm_agent",
                source_dir=tmp,
                scripts_dir=scripts_dir,
            )
            import py_compile

            py_compile.compile(str(script), doraise=True)


class TestToolSpecModulePathAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sdk_root = Path("D:/projects/JiuwenAgent")
        cls.llm_module = "openjiuwen.core.application.llm_agent.llm_agent"
        if not (cls.sdk_root / "openjiuwen" / "core" / "application" / "llm_agent" / "llm_agent.py").is_file():
            raise unittest.SkipTest("JiuwenAgent source tree not available")

    def test_create_llm_agent_spec_uses_legacy_react_config_title(self) -> None:
        from extensions.sop_converter.type_schema import pydantic_schema_for_type

        schema = pydantic_schema_for_type(
            str(self.sdk_root),
            "ReActAgentConfig",
            module_path=self.llm_module,
        )
        self.assertIsNotNone(schema)
        assert schema is not None
        self.assertEqual(schema.get("title"), "LegacyReActAgentConfig")
        props = schema.get("properties") or {}
        self.assertIn("id", props)
        self.assertIn("memory_scope_id", props)
        self.assertNotIn("mem_scope_id", props)


class TestPipelineExecuteStageSchema(unittest.TestCase):
    def test_execute_stage_schema_uses_object_and_optional_runtime_fields(self) -> None:
        op = _make_op(
            "execute_stage",
            parameters=[
                _make_param("stage", "Stage"),
                _make_param("run_dir", "Path"),
                _make_param("run_id", "str"),
                _make_param("config", "RCConfig"),
                _make_param("adapters", "AdapterBundle"),
                _make_param(
                    "auto_approve_gates",
                    "bool",
                    required=False,
                    default="False",
                ),
            ],
            file_stem="executor",
        )
        spec = operation_to_spec(
            op,
            source_dir="/tmp/sdk",
            script_path="/tmp/fake.py",
            comp_name="researchclaw.pipeline",
        )
        props = spec.input_schema["properties"]
        self.assertEqual(props["config"]["type"], "object")
        self.assertEqual(props["adapters"]["type"], "object")
        self.assertEqual(props["auto_approve_gates"]["default"], False)
        self.assertEqual(spec.input_schema["required"], ["stage", "run_dir"])


class TestInteractiveInputDetection(unittest.TestCase):
    def test_source_operation_with_getpass_detection(self) -> None:
        from extensions.sop_converter.source_parser import detect_interactive_input, _InteractiveInputDetector
        import ast

        source = """
def login():
    import getpass
    api_key = getpass.getpass("Enter API Key: ")
    return api_key
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        has_input, prompts = detect_interactive_input(func_def)
        self.assertTrue(has_input)
        self.assertEqual(prompts, ["Enter API Key: "])

    def test_source_operation_with_input_detection(self) -> None:
        from extensions.sop_converter.source_parser import detect_interactive_input
        import ast

        source = """
def get_name():
    name = input("What is your name? ")
    return name
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        has_input, prompts = detect_interactive_input(func_def)
        self.assertTrue(has_input)
        self.assertEqual(prompts, ["What is your name? "])

    def test_source_operation_with_sys_stdin_readline_detection(self) -> None:
        from extensions.sop_converter.source_parser import detect_interactive_input
        import ast

        source = """
import sys

def read_input():
    line = sys.stdin.readline()
    return line
"""
        tree = ast.parse(source)
        func_def = tree.body[1]
        has_input, prompts = detect_interactive_input(func_def)
        self.assertTrue(has_input)
        self.assertEqual(prompts, [""])

    def test_source_operation_with_sys_stdin_read_detection(self) -> None:
        from extensions.sop_converter.source_parser import detect_interactive_input
        import ast

        source = """
import sys

def read_api_key():
    key = sys.stdin.read().strip()
    return key
"""
        tree = ast.parse(source)
        func_def = tree.body[1]
        has_input, prompts = detect_interactive_input(func_def)
        self.assertTrue(has_input)
        self.assertEqual(prompts, [""])

    def test_source_operation_without_interactive_input(self) -> None:
        from extensions.sop_converter.source_parser import detect_interactive_input
        import ast

        source = """
def add(a, b):
    return a + b
"""
        tree = ast.parse(source)
        func_def = tree.body[0]
        has_input, prompts = detect_interactive_input(func_def)
        self.assertFalse(has_input)
        self.assertEqual(prompts, [])


class TestInteractiveInputWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self._cleanup, self.tool_dir, self.scripts_dir = _isolated_dirs()
        self.addCleanup(self._cleanup)

    def test_wrapper_with_interactive_input_includes_monkey_patch(self) -> None:
        source = textwrap.dedent(
            """\
            def login():
                import getpass
                api_key = getpass.getpass("Enter API Key: ")
                return api_key
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            source_file = source_dir / "auth.py"
            source_file.write_text(source, encoding="utf-8")

            op = _make_op(
                "login",
                file_stem="auth",
            )
            op.requires_interactive_input = True
            op.interactive_prompts = ["Enter API Key: "]

            script = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="proj.auth",
                file_stem="auth",
                source_dir=str(source_dir),
                scripts_dir=self.scripts_dir,
            )

            script_content = script.read_text(encoding="utf-8")
            self.assertIn("_set_interactive_inputs", script_content)
            self.assertIn("builtins.input = _interactive_input", script_content)
            self.assertIn("_getpass_module.getpass = _interactive_getpass", script_content)
            self.assertIn("_sys_module.stdin.read = _interactive_stdin_read", script_content)
            self.assertIn("_sys_module.stdin.readline = _interactive_stdin_readline", script_content)

    def test_wrapper_always_includes_interactive_input_preamble(self) -> None:
        """Preamble is always emitted so subprocess-launching stubs can
        forward _interactive_input_queue to nested subprocesses, even when
        the wrapped function does not directly contain input() calls."""
        source = textwrap.dedent(
            """\
            def add(a, b):
                return a + b
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "proj"
            source_dir.mkdir()
            source_file = source_dir / "math.py"
            source_file.write_text(source, encoding="utf-8")

            op = _make_op(
                "add",
                parameters=[_make_param("a", "int"), _make_param("b", "int")],
                file_stem="math",
            )
            op.requires_interactive_input = False
            op.interactive_prompts = []

            script = _generate_wrapper_script(
                [op],
                class_name=None,
                module_name="proj.math",
                file_stem="math",
                source_dir=str(source_dir),
                scripts_dir=self.scripts_dir,
            )

            script_content = script.read_text(encoding="utf-8")
            # preamble is always present now — the detection is shallow
            # (doesn't follow transitive calls), so CLI entrypoints that
            # delegate to helpers with input() calls need the preamble.
            self.assertIn("_interactive_input_queue", script_content)
            self.assertIn("_set_interactive_inputs", script_content)

    def test_operation_to_spec_adds_interactive_inputs_schema(self) -> None:
        op = _make_op(
            "login",
            file_stem="auth",
        )
        op.requires_interactive_input = True
        op.interactive_prompts = ["Enter API Key: "]

        spec = operation_to_spec(
            op,
            source_dir="/tmp/sdk",
            script_path="/tmp/fake.py",
            comp_name="demo",
        )

        props = spec.input_schema["properties"]
        self.assertIn("__interactive_inputs", props)
        self.assertEqual(props["__interactive_inputs"]["type"], "array")
        self.assertEqual(props["__interactive_inputs"]["items"], {"type": "string"})
        self.assertIn("Enter API Key", props["__interactive_inputs"]["description"])

    def test_operation_to_spec_without_interactive_input_omits_schema(self) -> None:
        op = _make_op(
            "add",
            parameters=[_make_param("a", "int"), _make_param("b", "int")],
            file_stem="math",
        )
        op.requires_interactive_input = False
        op.interactive_prompts = []

        spec = operation_to_spec(
            op,
            source_dir="/tmp/sdk",
            script_path="/tmp/fake.py",
            comp_name="demo",
        )

        props = spec.input_schema["properties"]
        self.assertNotIn("__interactive_inputs", props)


if __name__ == "__main__":
    unittest.main()

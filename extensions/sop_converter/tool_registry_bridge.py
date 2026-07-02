"""Tool Registry Bridge — bridges SourceOperation → AgentToolSpec → Tool Registry.

Converts parsed source operations into executable Agent tools with bash-callable
wrapper scripts.  Every operation — class method or standalone function — is
uniformly handled via ``call_type="bash"`` so that import / instantiation logic
lives inside an isolated subprocess rather than the main server process.

Key design decisions
--------------------
* **Unified bash call_type**: all operations use ``call_type="bash"``, even
  standalone functions.  This avoids the ``_PYTHON_FUNCTION_REGISTRY`` problem.
* **Wrapper scripts live in** ``~/.clawcodex/agent-tools/scripts/`` — alongside
  the persisted ``AgentToolSpec`` JSON files, *not* in the source directory.
* **Name normalization**: original tool names like ``LLM.invoke`` or
  ``Utils.load_config`` are converted to kebab-case (``llm-invoke``,
  ``utils-load-config``).  The returned name map allows the caller to update
  ``SkillSpec.allowed_tools`` so agent markdown can reference the registered
  kebab-case names directly.

Usage::

    from extensions.sop_converter.tool_registry_bridge import register_component_tools

    name_map = register_component_tools(components, str(source_dir), persist=True)
    # name_map: {"LLM.invoke": "llm-invoke", ...}
    # Update SkillSpec.allowed_tools with kebab-case names before writing markdown.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from clawcodex_ext.agent.tool_authoring.persistence import (
    TOOL_DIR,
    bundle_tool_dir,
    save_spec,
    scripts_dir_for,
)
from clawcodex_ext.agent.tool_authoring.spec import AgentToolSpec
from clawcodex_ext.agent.tool_authoring.validators import validate_spec

from .search_tags import generate_search_tags
from .source_parser import SourceComponent, SourceOperation, ParamSpec
from .type_schema import param_to_json_schema_property

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Legacy global script dir (used when no bundle_dir is supplied).
from clawcodex_ext.agent.tool_authoring.persistence import TOOL_DIR

SCRIPTS_DIR = TOOL_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Type hint → JSON Schema
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "None": "null",
    "NoneType": "null",
    "Path": "string",
    "RCConfig": "object",
    "AdapterBundle": "object",
    "Stage": "string",
    "StageResult": "object",
}

# Python identifiers from ast.unparse() that should become JSON literals.
_LITERAL_DEFAULT_MAP: dict[str, Any] = {
    "True": True,
    "False": False,
    "None": None,
}


def _strip_optional_union(type_hint: str) -> str:
    """Reduce ``Optional[X]``, ``Union[X, None]``, and ``X | None`` to ``X``."""
    cleaned = type_hint.strip()

    for prefix in ("Optional[", "Union["):
        if cleaned.startswith(prefix) and cleaned.endswith("]"):
            inner = cleaned[len(prefix) : -1]
            parts = [p.strip() for p in inner.split(",")]
            for part in parts:
                if part not in ("None", "NoneType"):
                    return _strip_optional_union(part)

    if "|" in cleaned:
        parts = [p.strip() for p in cleaned.split("|")]
        for part in parts:
            if part not in ("None", "NoneType"):
                return _strip_optional_union(part)

    return cleaned


def _type_hint_to_json_type(type_hint: str | None) -> str:
    """Map a Python type-hint string to a JSON Schema ``type`` value.

    >>> _type_hint_to_json_type("str")
    'string'
    >>> _type_hint_to_json_type("Optional[int]")
    'integer'
    >>> _type_hint_to_json_type("dict[str, TeamAgentSpec] | None")
    'object'
    >>> _type_hint_to_json_type("Iterable[str | Path] | None")
    'array'
    >>> _type_hint_to_json_type(None)
    'string'
    """
    if not type_hint:
        return "string"

    cleaned = _strip_optional_union(type_hint.strip())

    # Handle List[...], Sequence[...], Iterable[...] → array
    if cleaned.startswith(
        (
            "List[",
            "list[",
            "Sequence[",
            "sequence[",
            "Iterable[",
            "iterable[",
            "Set[",
            "set[",
            "FrozenSet[",
            "frozenset[",
        )
    ):
        return "array"

    # Handle Dict[...], Mapping[...] → object
    if cleaned.startswith(
        (
            "Dict[",
            "dict[",
            "Mapping[",
            "mapping[",
            "MutableMapping[",
        )
    ):
        return "object"

    # SDK / pathlib types (bare name or generic alias root)
    root = cleaned.split("[", 1)[0]
    if root in _TYPE_MAP:
        return _TYPE_MAP[root]

    # Direct lookup
    return _TYPE_MAP.get(cleaned, "string")


def _normalize_schema_default(default: Any, *, json_type: str) -> Any:
    """Coerce ast-unparsed Python literal defaults into JSON Schema values."""
    if isinstance(default, str) and default in _LITERAL_DEFAULT_MAP:
        return _LITERAL_DEFAULT_MAP[default]
    if json_type == "boolean" and isinstance(default, str):
        lowered = default.lower()
        if lowered in ("true", "false"):
            return lowered == "true"
    return default


def _adjust_pipeline_execute_stage_schema(
    op: SourceOperation,
    properties: dict[str, Any],
    required: list[str],
) -> None:
    """Relax pipeline executor tool schema for agent JSON tool calls."""
    if op.name != "execute_stage":
        return

    for key in ("config", "adapters", "run_id"):
        if key in properties:
            properties[key]["description"] = (
                properties[key].get("description")
                or (
                    "Optional; loads from run_dir/config.yaml when omitted"
                    if key == "config"
                    else (
                        "Optional; defaults to empty AdapterBundle"
                        if key == "adapters"
                        else "Optional; defaults to run_dir directory name"
                    )
                )
            )
            if key in required:
                required.remove(key)

    if "stage" in properties:
        properties["stage"]["description"] = (
            'Pipeline stage enum name, e.g. "TOPIC_INIT" or "topic-init"'
        )
    if "run_dir" in properties:
        properties["run_dir"]["description"] = "Absolute path to the pipeline run directory"


# ---------------------------------------------------------------------------
# Name conversion
# ---------------------------------------------------------------------------


def _to_kebab_case(name: str) -> str:
    """Convert dot.separated / snake_case → kebab-case.

    Only dots, double-underscores, and single underscores act as word
    separators.  CamelCase within a segment is preserved as one word:
    ``"VideoProcessor"`` → ``"videoprocessor"`` (not ``"video-processor"``).

    >>> _to_kebab_case("VideoProcessor.transcode")
    'videoprocessor-transcode'
    >>> _to_kebab_case("video_ops.transcode")
    'video-ops-transcode'
    >>> _to_kebab_case("utils__load_config")
    'utils-load-config'
    >>> _to_kebab_case("LLM.invoke")
    'llm-invoke'
    >>> _to_kebab_case("foundation.LLM.invoke")
    'foundation-llm-invoke'
    """
    import re

    # Replace dots and double-underscores with hyphens
    s = name.replace(".", "-").replace("__", "-")
    # Replace single underscores with hyphens
    s = s.replace("_", "-")
    # Collapse multiple consecutive hyphens
    s = re.sub(r"-+", "-", s)
    # Strip leading/trailing hyphens and lowercase
    return s.strip("-").lower()


# ---------------------------------------------------------------------------
# Module path resolution
# ---------------------------------------------------------------------------


def _resolve_module_path(
    component: SourceComponent,
    source_dir: str,
    file_stem: str,
) -> str:
    """Infer the Python import path for a specific source file within a component.

    ``SourceComponent.file_path`` is relative to ``source_dir.parent``
    (see :class:`SourceCodeParser._walk_module`).  Since the wrapper script
    injects *source_dir* into ``sys.path``, the import path must be relative
    to *source_dir*.

    Example::

        source_dir   = "/mnt/d/projects/AutoResearchClaw"
        component.file_path = "researchclaw/literature"
        file_stem    = "llm"
        → "core.foundation.llm"

    Returns:
        Dotted Python module path suitable for ``importlib.import_module()``.
    """
    source_dir_path = Path(source_dir).resolve()
    source_dir_name = source_dir_path.name
    comp_rel = Path(component.file_path)

    # Strip the source_dir name prefix from file_path (it's relative to parent)
    try:
        module_dir = comp_rel.relative_to(source_dir_name)
    except ValueError:
        # If file_path doesn't start with source_dir_name, use it as-is
        # (e.g. when source_dir itself is the repo root)
        module_dir = comp_rel

    parts = list(module_dir.parts) if module_dir.parts != (".",) else []
    parts.append(file_stem)
    return ".".join(parts)


def _script_name_for_class(module_path: str, class_name: str) -> str:
    """Build a unique script filename for a class within a module.

    Uses a short hash of the full module path to avoid collisions
    between identically-named classes from different projects/packages.
    """
    hash_hex = hashlib.sha256(module_path.encode()).hexdigest()[:8]
    return f"{class_name}_{hash_hex}.py"


def _script_name_for_functions(module_path: str, file_stem: str) -> str:
    """Build a unique script filename for standalone functions in a module."""
    hash_hex = hashlib.sha256(module_path.encode()).hexdigest()[:8]
    return f"{file_stem}_fn_{hash_hex}.py"


# ---------------------------------------------------------------------------
# Class constructor parameter handling
# ---------------------------------------------------------------------------


def _skip_variadic_params(params: list[ParamSpec]) -> list[ParamSpec]:
    return [p for p in params if not p.name.startswith("*")]


def _has_signature_default(param: ParamSpec) -> bool:
    """True when the generated stub should use ``name=...`` syntax."""
    return param.default is not None or not param.required


def _sort_params_for_python_signature(params: list[ParamSpec]) -> list[ParamSpec]:
    """Required positional params first, then params with defaults (Python syntax rule)."""
    positional = [p for p in params if not _has_signature_default(p)]
    defaulted = [p for p in params if _has_signature_default(p)]
    return positional + defaulted


def _merge_init_and_method_params(
    init_params: list[ParamSpec],
    method_params: list[ParamSpec],
) -> list[ParamSpec]:
    """Merge ``__init__`` params with method params; method wins on name clash."""
    method_skip = _skip_variadic_params(method_params)
    init_skip = _skip_variadic_params(init_params)
    method_names = {p.name for p in method_skip}

    by_name: dict[str, ParamSpec] = {}
    order: list[str] = []

    for param in init_skip:
        if param.name in method_names:
            continue
        by_name[param.name] = param
        order.append(param.name)

    for param in method_skip:
        if param.name not in by_name:
            order.append(param.name)
        by_name[param.name] = param

    merged = [by_name[name] for name in order]
    return _sort_params_for_python_signature(merged)


def _param_signature_parts(params: list[ParamSpec]) -> list[str]:
    parts: list[str] = []
    for param in params:
        if param.name.startswith("*"):
            continue
        if param.default is not None:
            parts.append(f"{param.name}={param.default}")
        elif not param.required:
            parts.append(f"{param.name}=None")
        else:
            parts.append(param.name)
    return parts


def _generate_get_instance_helper(init_params: list[ParamSpec] | None) -> str:
    """Generate ``_get_instance`` (and optional ``_resolve_init_kwargs``) helper."""
    callable_init = _skip_variadic_params(init_params or [])
    if not callable_init:
        return (
            "def _get_instance(class_name, module_name):\n"
            '    """Lazily create and cache a class instance."""\n'
            "    if class_name not in _instances:\n"
            "        module = importlib.import_module(module_name)\n"
            "        cls = getattr(module, class_name)\n"
            "        _instances[class_name] = cls()\n"
            "    return _instances[class_name]\n"
        )

    resolver_lines: list[str] = ["    kwargs = dict(provided)"]
    for param in callable_init:
        if param.default is not None:
            resolver_lines.append(f'    kwargs.setdefault("{param.name}", {param.default})')
        else:
            resolver_lines.append(f'    if "{param.name}" not in kwargs:')
            resolver_lines.append(f'        _fn = getattr(module, "{param.name}", None)')
            resolver_lines.append("        if callable(_fn):")
            resolver_lines.append("            try:")
            resolver_lines.append(f'                kwargs["{param.name}"] = _fn()')
            resolver_lines.append("            except TypeError:")
            resolver_lines.append(
                '                _team = os.environ.get("OPENJIUWEN_TEAM_NAME", "team")'
            )
            resolver_lines.append("                try:")
            resolver_lines.append(f'                    kwargs["{param.name}"] = _fn(team_name=_team)')
            resolver_lines.append("                except TypeError:")
            resolver_lines.append("                    pass")

    required = [p.name for p in callable_init if p.required and p.default is None]
    if required:
        missing_check = " or ".join(f'"{name}" not in kwargs' for name in required)
        resolver_lines.append(f"    if {missing_check}:")
        resolver_lines.append(f"        _missing = [n for n in {required!r} if n not in kwargs]")
        resolver_lines.append(
            '        raise TypeError("Missing constructor argument(s): " + ", ".join(_missing))'
        )
    resolver_lines.append("    return kwargs")

    resolver_body = "\n".join(resolver_lines)
    return (
        "def _resolve_init_kwargs(module, **provided):\n"
        f"{resolver_body}\n\n"
        "def _get_instance(class_name, module_name, **init_kwargs):\n"
        '    """Lazily create and cache a class instance keyed by constructor args."""\n'
        "    cache_key = (class_name, tuple(sorted(init_kwargs.items())))\n"
        "    if cache_key not in _instances:\n"
        "        module = importlib.import_module(module_name)\n"
        "        cls = getattr(module, class_name)\n"
        "        resolved = _resolve_init_kwargs(module, **init_kwargs)\n"
        "        _instances[cache_key] = cls(**resolved)\n"
        "    return _instances[cache_key]\n"
    )


# ---------------------------------------------------------------------------
# Wrapper script SDK symbol imports
# ---------------------------------------------------------------------------

_BUILTIN_DEFAULT_NAMES = frozenset({"True", "False", "None"})


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _resolve_relative_import(module_name: str, level: int, module: str | None) -> str:
    parts = module_name.split(".")
    if level > len(parts):
        base: list[str] = []
    else:
        base = parts[: len(parts) - level]
    if module:
        return ".".join([*base, *module.split(".")])
    return ".".join(base)


def _parse_import_map(source_file: Path, module_name: str) -> dict[str, str]:
    """Map local symbol names to importable modules from a source file."""
    if not source_file.is_file():
        return {}

    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}

    mapping: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                mapping[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            resolved_module = (
                _resolve_relative_import(module_name, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                mapping[local] = resolved_module
    return mapping


def _identifiers_in_default(default: str) -> set[str]:
    """Extract root names referenced by a default-value expression."""
    cleaned = default.strip()
    if not cleaned or cleaned in _BUILTIN_DEFAULT_NAMES:
        return set()

    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError:
        return set(re.findall(r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)(?=\.[A-Za-z_])", cleaned))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in _BUILTIN_DEFAULT_NAMES:
                names.add(node.id)
        elif isinstance(node, ast.Attribute):
            root: ast.AST = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id not in _BUILTIN_DEFAULT_NAMES:
                names.add(root.id)
    return names


def _collect_runtime_symbols(
    ops: list[SourceOperation],
    init_params: list[ParamSpec] | None,
) -> set[str]:
    """Collect symbols that must exist at wrapper import time (default values)."""
    symbols: set[str] = set()

    def _scan_params(params: list[ParamSpec]) -> None:
        for param in params:
            if param.default is not None:
                symbols.update(_identifiers_in_default(str(param.default)))

    if init_params:
        _scan_params(_skip_variadic_params(init_params))

    for op in ops:
        _scan_params(op.parameters)

    return symbols


def _resolve_source_file(source_dir: str, module_name: str) -> Path:
    return Path(source_dir) / Path(*module_name.split(".")).with_suffix(".py")


def _format_wrapper_imports(
    symbols: set[str],
    import_map: dict[str, str],
    module_name: str,
) -> str:
    """Render grouped ``from ... import ...`` lines for wrapper scripts."""
    if not symbols:
        return ""

    by_module: dict[str, list[str]] = {}
    for symbol in sorted(symbols):
        resolved_module = import_map.get(symbol) or module_name
        by_module.setdefault(resolved_module, []).append(symbol)

    lines: list[str] = []
    for resolved_module in sorted(by_module):
        names = ", ".join(sorted(by_module[resolved_module]))
        lines.append(f"from {resolved_module} import {names}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI handler detection (F-52 subprocess bridge — mirrors F-50-F CLI mode)
# ---------------------------------------------------------------------------

_CLI_EXCLUDED_HANDLER_NAMES = frozenset(
    {
        "main",
        "build_parser",
    }
)


def _is_namespace_args_param(param: ParamSpec) -> bool:
    if param.name != "args":
        return False
    if not param.type_hint:
        return False
    return "Namespace" in param.type_hint


def _is_cli_handler_op(op: SourceOperation, dispatch_map: dict[str, str]) -> bool:
    """True when *op* should run via CLI subprocess instead of importlib."""
    if op.class_name is not None:
        return False
    if op.name in _CLI_EXCLUDED_HANDLER_NAMES:
        return False
    if op.name not in dispatch_map:
        return False
    if op.name.startswith("cmd_"):
        return True
    return any(_is_namespace_args_param(p) for p in op.parameters)


def _extract_command_literal(test: ast.AST) -> str | None:
    """Extract subcommand from ``command == "foo"`` in ``main()`` dispatch."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    if not isinstance(test.ops[0], (ast.Eq, ast.Is)):
        return None
    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and left.id == "command":
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            return right.value
    return None


def _extract_cmd_handler_from_body(body: list[ast.stmt]) -> str | None:
    for stmt in body:
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            continue
        value = stmt.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            name = value.func.id
            if name.startswith("cmd_"):
                return name
    return None


def _walk_command_dispatch(node: ast.stmt, dispatch: dict[str, str]) -> None:
    if not isinstance(node, ast.If):
        return
    subcommand = _extract_command_literal(node.test)
    handler = _extract_cmd_handler_from_body(node.body)
    if subcommand and handler:
        dispatch[handler] = subcommand
    if not node.orelse:
        return
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        _walk_command_dispatch(node.orelse[0], dispatch)
        return
    for child in node.orelse:
        _walk_command_dispatch(child, dispatch)


def _parse_cli_dispatch_map(source_file: Path) -> dict[str, str]:
    """Map ``cmd_*`` handler names to CLI subcommand strings from ``main()``."""
    if not source_file.is_file():
        return {}
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        logger.debug("Cannot parse CLI dispatch from %s: %s", source_file, exc)
        return {}

    dispatch: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            for stmt in node.body:
                _walk_command_dispatch(stmt, dispatch)
    return dispatch


def _resolve_cli_argv_prefix(
    source_dir: str,
    source_file: Path,
    *,
    cli_prefix_override: str | None = None,
) -> list[str]:
    """CLI argv prefix for subprocess dispatch (reuses F-50 cli_discovery)."""
    import sys

    from extensions.sop_converter.workflow_mode.bridge.cli_discovery import (
        discover_cli_prefix,
        split_cli_prefix,
    )

    project_name = Path(source_dir).name
    discovered = discover_cli_prefix(
        Path(source_dir),
        project_name,
        override=cli_prefix_override,
    )
    if discovered:
        prefix = split_cli_prefix(discovered)
        if prefix:
            return prefix

    return [sys.executable, str(source_file.resolve())]


def _generate_cli_handler_stub(op: SourceOperation, *, subcommand: str) -> str:
    """Generate a subprocess-based stub for a CLI ``cmd_*`` handler."""
    docstring = op.description.replace('"', '\\"') if op.description else op.name
    return (
        f"def {op.name}(args: str) -> dict:\n"
        f'    """{docstring}"""\n'
        "    import shlex\n"
        "    import subprocess\n"
        "    tail = shlex.split(args) if args else []\n"
        f"    argv = [*CLI_PREFIX, {subcommand!r}, *tail]\n"
        "    proc = subprocess.run(\n"
        "        argv,\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        "        cwd=_SOURCE_DIR,\n"
        "    )\n"
        "    result = {\n"
        '        "returncode": proc.returncode,\n'
        '        "stdout": proc.stdout,\n'
        '        "stderr": proc.stderr,\n'
        "    }\n"
        "    if proc.returncode != 0:\n"
        "        err = proc.stderr.strip() or proc.stdout.strip()\n"
        "        if err:\n"
        '            result["error"] = err\n'
        "    return result"
    )


# ---------------------------------------------------------------------------
# Wrapper script generation
# ---------------------------------------------------------------------------

_WRAPPER_SCRIPT_TEMPLATE = r'''#!/usr/bin/env python3
"""Auto-generated wrapper for {header_label} - created by pos convert."""

from __future__ import annotations

import os
import sys
import json
import importlib
import asyncio
{extra_imports}
_SOURCE_DIR = r"{source_dir}"
sys.path.insert(0, _SOURCE_DIR)
{cli_prefix}

_instances = {{}}


def _run_async_iter(make_gen):
    """Drain an async iterator/generator into a JSON-serializable list."""

    async def _collect():
        result = []
        async for item in make_gen():
            result.append(item)
        return result

    return asyncio.run(_collect())

{body}

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python {script_name} <method> '<json_args>'", file=sys.stderr)
        sys.exit(1)
    method_name = sys.argv[1]
    try:
        args = json.loads(sys.argv[2])
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON args: {{exc}}", file=sys.stderr)
        sys.exit(1)
    fn = globals().get(method_name)
    if fn is None:
        print(f"Unknown method: {{method_name}}", file=sys.stderr)
        sys.exit(1)
    try:
        result = fn(**args)
        print(json.dumps(result, default=str, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({{"error": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
'''


def _generate_pipeline_execute_stage_stub(op: SourceOperation) -> str:
    """Wrapper stub that coerces JSON tool args into pipeline runtime objects."""
    docstring = op.description.replace('"', '\\"') if op.description else op.name
    return (
        f"def {op.name}(stage, run_dir, run_id=None, config=None, adapters=None, "
        f"auto_approve_gates=False){f' -> {op.return_type}' if op.return_type else ''}:\n"
        f'    """{docstring}"""\n'
        '    from pathlib import Path\n'
        '    module = importlib.import_module("researchclaw.pipeline.executor")\n'
        '    from researchclaw.config import load_config, RCConfig\n'
        '    from researchclaw.adapters import AdapterBundle\n'
        '    from researchclaw.pipeline.stages import Stage\n'
        '    run_path = Path(run_dir)\n'
        '    if not run_id:\n'
        '        run_id = run_path.name\n'
        '    if config is None:\n'
        '        config = load_config(run_path / "config.yaml", project_root=run_path)\n'
        '    elif isinstance(config, str):\n'
        '        config = load_config(Path(config), project_root=run_path)\n'
        '    elif isinstance(config, dict):\n'
        '        config = RCConfig.from_dict(config)\n'
        '    if adapters is None:\n'
        '        adapters = AdapterBundle()\n'
        '    elif isinstance(adapters, dict):\n'
        '        adapters = AdapterBundle()\n'
        '    if isinstance(stage, str):\n'
        '        stage_key = stage.upper().replace("-", "_")\n'
        '        stage = Stage[stage_key]\n'
        '    if not isinstance(run_dir, Path):\n'
        '        run_dir = Path(run_dir)\n'
        '    return module.execute_stage(\n'
        '        stage=stage,\n'
        '        run_dir=run_dir,\n'
        '        run_id=run_id,\n'
        '        config=config,\n'
        '        adapters=adapters,\n'
        '        auto_approve_gates=bool(auto_approve_gates),\n'
        '    )'
    )


def _generate_method_stub(
    op: SourceOperation,
    *,
    is_class_method: bool,
    module_name: str,
    init_params: list[ParamSpec] | None = None,
) -> str:
    """Generate a method stub for a single SourceOperation.

    Args:
        op: The source operation.
        is_class_method: True if this is a class method (needs _get_instance).
        module_name: Dotted Python module path.
        init_params: Required ``__init__`` parameters for the owning class.
    """
    effective_params = (
        _merge_init_and_method_params(init_params or [], op.parameters)
        if is_class_method
        else _sort_params_for_python_signature(op.parameters)
    )
    param_parts = _param_signature_parts(effective_params)
    params_str = ", ".join(param_parts)

    return_type = f" -> {op.return_type}" if op.return_type else ""

    docstring = op.description.replace('"', '\\"') if op.description else op.name

    call_kwargs = "".join(
        f"        {p.name}={p.name},\n" for p in op.parameters if not p.name.startswith("*")
    )

    if is_class_method:
        init_kw_names = [p.name for p in _skip_variadic_params(init_params or [])]
        get_instance_call = f'_get_instance("{op.class_name}", "{module_name}"'
        init_pass = ", ".join(f"{name}={name}" for name in init_kw_names)
        if init_pass:
            get_instance_call += f", {init_pass}"
        get_instance_call += ")"
        inner_call = f"{get_instance_call}.{op.name}(\n{call_kwargs}    )"
    else:
        inner_call = f'module.{op.name}(\n{call_kwargs}    )'

    if op.is_async_generator:
        if is_class_method:
            body_lines = (
                f"def {op.name}({params_str}){return_type}:\n"
                f'    """{docstring}"""\n'
                f"    return _run_async_iter(lambda: {inner_call})"
            )
        else:
            body_lines = (
                f"def {op.name}({params_str}){return_type}:\n"
                f'    """{docstring}"""\n'
                f'    module = importlib.import_module("{module_name}")\n'
                f"    return _run_async_iter(lambda: {inner_call})"
            )
        return body_lines

    async_prefix = "asyncio.run(" if op.is_async else ""
    async_suffix = ")" if op.is_async else ""

    if is_class_method:
        return (
            f"def {op.name}({params_str}){return_type}:\n"
            f'    """{docstring}"""\n'
            f"    return {async_prefix}{inner_call}{async_suffix}"
        )
    else:
        return (
            f"def {op.name}({params_str}){return_type}:\n"
            f'    """{docstring}"""\n'
            f'    module = importlib.import_module("{module_name}")\n'
            f"    return {async_prefix}{inner_call}{async_suffix}"
        )


def _generate_wrapper_script(
    ops: list[SourceOperation],
    *,
    class_name: str | None,
    module_name: str,
    file_stem: str,
    source_dir: str,
    scripts_dir: Path | None = None,
    init_params: list[ParamSpec] | None = None,
    cli_dispatch_map: dict[str, str] | None = None,
    cli_prefix_override: str | None = None,
) -> Path:
    """Generate a wrapper script for a group of related operations.

    All operations sharing the same *class_name* (or *file_stem* for standalone
    functions) are written into one script so that the class is instantiated
    only once per process.

    Args:
        ops: Operations to include in this script.
        class_name: The owning class name, or None for standalone functions.
        module_name: Dotted Python import path for the module.
        file_stem: The source file stem (used when class_name is None).
        source_dir: Absolute path to the source root (injected into sys.path).

    Returns:
        Path to the generated script file.
    """
    # Determine script filename
    if class_name:
        script_name = _script_name_for_class(module_name, class_name)
        header_label = f"{class_name} ({module_name})"
    else:
        script_name = _script_name_for_functions(module_name, file_stem)
        header_label = f"{file_stem} functions ({module_name})"

    script_path = (scripts_dir or SCRIPTS_DIR) / script_name
    script_path.parent.mkdir(parents=True, exist_ok=True)

    source_file = _resolve_source_file(source_dir, module_name)
    if cli_dispatch_map is not None:
        dispatch_map = cli_dispatch_map
    elif file_stem == "cli":
        dispatch_map = _parse_cli_dispatch_map(source_file)
    else:
        dispatch_map = {}
    use_cli_subprocess = class_name is None and any(
        _is_cli_handler_op(op, dispatch_map) for op in ops
    )
    cli_prefix_line = ""
    if use_cli_subprocess:
        prefix = _resolve_cli_argv_prefix(
            source_dir,
            source_file,
            cli_prefix_override=cli_prefix_override,
        )
        cli_prefix_line = f"CLI_PREFIX: list[str] = {prefix!r}"

    # Build body: helper(s) + method stubs
    body_parts: list[str] = []

    if class_name:
        body_parts.append(_generate_get_instance_helper(init_params))

    # Sort operations by name for deterministic output
    for op in sorted(ops, key=lambda o: o.name):
        body_parts.append("")
        subcommand = dispatch_map.get(op.name)
        if subcommand and _is_cli_handler_op(op, dispatch_map):
            body_parts.append(_generate_cli_handler_stub(op, subcommand=subcommand))
        elif op.name == "execute_stage" and class_name is None and file_stem == "executor":
            body_parts.append(_generate_pipeline_execute_stage_stub(op))
        else:
            body_parts.append(
                _generate_method_stub(
                    op,
                    is_class_method=class_name is not None,
                    module_name=module_name,
                    init_params=init_params if class_name is not None else None,
                )
            )

    runtime_symbols = _collect_runtime_symbols(ops, init_params)
    import_map = _parse_import_map(source_file, module_name)
    extra_imports = _format_wrapper_imports(runtime_symbols, import_map, module_name)
    if extra_imports:
        extra_imports = f"\n{extra_imports}\n"

    content = _WRAPPER_SCRIPT_TEMPLATE.format(
        header_label=header_label,
        source_dir=source_dir,
        cli_prefix=cli_prefix_line,
        extra_imports=extra_imports,
        body="\n".join(body_parts),
        script_name=script_name,
    )

    script_path.write_text(content, encoding="utf-8")
    logger.info("Generated wrapper script: %s (%d methods)", script_path, len(ops))
    return script_path


# ---------------------------------------------------------------------------
# Bridge params — json_args injection
# ---------------------------------------------------------------------------


def _enrich_bridge_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *params* with ``json_args`` injected.

    The generated wrapper scripts accept a single JSON blob as their second
    argument (``sys.argv[2]``).  This helper serialises the tool-call input
    dict into that blob so the ``call_impl`` template placeholder
    ``{json_args}`` is always satisfied, even for parameterless functions
    where *params* is empty.
    """
    import json

    return {**params, "json_args": json.dumps(params, ensure_ascii=False)}


# ---------------------------------------------------------------------------
# Spec generation
# ---------------------------------------------------------------------------


def operation_to_spec(
    op: SourceOperation,
    *,
    source_dir: str,
    script_path: str,
    comp_name: str = "",
    bundle_id: str | None = None,
    init_params: list[ParamSpec] | None = None,
    cli_subcommand: str | None = None,
) -> AgentToolSpec:
    """Convert a single SourceOperation into an AgentToolSpec.

    Args:
        op: The parsed source operation.
        source_dir: Absolute path to the source root (unused here but kept
            for API consistency — the path is embedded in the wrapper script).
        script_path: Absolute path to the generated wrapper script.
        comp_name: SourceComponent name for the primary naming prefix
            (e.g. ``"agent_teams"``).  Falls back to *file_stem* or
            *class_name* when empty.

    Returns:
        A validated ``AgentToolSpec`` ready for persistence.
    """
    # Compute kebab-case tool name.
    # All names are namespace-qualified to guarantee global uniqueness:
    #   Class method  → {comp}.{class}.{method}  (or {class}.{method} when
    #                    comp_name is unavailable — legacy SDK path).
    #   Standalone fn → {comp}.{method}
    #   Fallback      → {file_stem}.{method} or bare {method}
    if op.class_name:
        if comp_name:
            raw_name = f"{comp_name}.{op.class_name}.{op.name}"
        else:
            raw_name = f"{op.class_name}.{op.name}"
    elif comp_name:
        raw_name = f"{comp_name}.{op.name}"
    elif op.file_stem:
        raw_name = f"{op.file_stem}.{op.name}"
    else:
        raw_name = op.name

    tool_name = _to_kebab_case(raw_name)

    # Build JSON Schema properties (merge class ``__init__`` params for class methods).
    if cli_subcommand:
        properties = {
            "args": {
                "type": "string",
                "description": (
                    f"CLI arguments after the '{cli_subcommand}' subcommand "
                    f"(flags and positional args, excluding '{cli_subcommand}' itself)."
                ),
            }
        }
        required = ["args"]
    else:
        schema_params = (
            _merge_init_and_method_params(init_params or [], op.parameters)
            if op.class_name
            else op.parameters
        )
        properties = {}
        required = []

        for param in schema_params:
            # Skip *args and **kwargs
            if param.name.startswith("*"):
                continue

            json_type = _type_hint_to_json_type(param.type_hint)
            prop = param_to_json_schema_property(
                type_hint=param.type_hint,
                description=param.description,
                source_dir=source_dir,
                fallback_json_type=json_type,
            )
            if param.default is not None:
                prop["default"] = _normalize_schema_default(
                    param.default,
                    json_type=prop.get("type", json_type),
                )

            properties[param.name] = prop

            if param.required and param.default is None:
                required.append(param.name)

        _adjust_pipeline_execute_stage_schema(op, properties, required)

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = required

    # Build call_impl template — uses absolute script path.
    # {json_args} is a special placeholder resolved by _enrich_bridge_params()
    # at call time (NOT by the generic execute_bash).  Single-quoted so the
    # shell treats the JSON blob as one token even when it is "{}".
    call_impl = f"python3 \"{script_path}\" {op.name} '{{json_args}}'"

    # Build aliases so resolve_agent_tools() can find the tool under
    # alternative names.
    #
    # Every alias is component-scoped when a component name is
    # available.  Class methods ONLY get the fully-qualified
    # {comp}.{class}.{method} alias — the bare {comp}.{method} form
    # is reserved for standalone functions, avoiding collisions when
    # the same method name appears as both a class method and a
    # standalone function within the same component.
    alias_list: list[str] = []
    if comp_name:
        if op.class_name:
            # Class method: only the fully-qualified alias is unique.
            alias_list.append(f"{comp_name}.{op.class_name}.{op.name}")
        else:
            # Standalone function: {comp}.{method} is unambiguous.
            alias_list.append(f"{comp_name}.{op.name}")
    else:
        # Legacy SDK path: no component to scope against.
        alias_list.append(raw_name)

    # ------------------------------------------------------------------
    # Short-name suffix aliases (strip the project-root namespace).
    #
    # When *comp_name* is multi-segment (e.g. "openjiuwen.agent_teams"),
    # the first segment is the project-level namespace (derived from the
    # top-level directory under *source_dir*).  Runtimes built *within*
    # that project typically reference tools without this prefix
    # (e.g. "agent_teams.get_session_id") — they operate at module scope.
    #
    # We generate an extra set of aliases that drop the first segment,
    # so resolve_agent_tools() can find the tool by its short name
    # through the normal exact-match path:
    #     "agent_teams.get_session_id" → exact match → alias hit ✅
    #
    # Only the first segment is stripped — deeper projects can extend
    # this pattern if needed, but one level covers the common case
    # without introducing ambiguous short aliases.
    if comp_name and "." in comp_name:
        _short_comp = comp_name.split(".", 1)[1]  # strip first segment
        if op.class_name:
            alias_list.append(f"{_short_comp}.{op.class_name}.{op.name}")
        else:
            alias_list.append(f"{_short_comp}.{op.name}")

    aliases = tuple(alias_list)
    tags = generate_search_tags(op, comp_name=comp_name)

    return AgentToolSpec(
        name=tool_name,
        description=op.description or op.name,
        input_schema=input_schema,
        call_type="bash",
        call_impl=call_impl,
        tags=tags,
        aliases=aliases,
        source="sop-converter",
        bundle_id=bundle_id
    )


# ---------------------------------------------------------------------------
# Bulk registration
# ---------------------------------------------------------------------------


def register_component_tools(
    components: list[SourceComponent],
    source_dir: str,
    *,
    persist: bool = True,
    overwrite: bool = True,
    bundle_dir: str | Path | None = None,
    bundle_id: str | None = None,
    cli_prefix_override: str | None = None,
) -> dict[str, str]:
    """Bulk-register all operations from a list of SourceComponents as Tools.

    For each unique class (or source file for standalone functions), one
    wrapper script is generated.  Every ``SourceOperation`` becomes an
    ``AgentToolSpec``, which is optionally persisted to disk and validated.

    Args:
        components: Parsed source components from ``SourceCodeParser.parse()``.
        source_dir: Absolute path to the source root directory.
        persist: If True, persist each ``AgentToolSpec`` to
            ``~/.clawcodex/agent-tools/<name>.json``.
        overwrite: If True, overwrite existing specs and scripts with the
            same name (idempotent on repeated ``sop convert`` runs).

    Returns:
        A mapping from original tool names (``"LLM.invoke"``) to kebab-case
        tool names (``"llm-invoke"``).  Use this to update
        ``SkillSpec.allowed_tools`` before writing agent markdown.
    """
    source_dir_abs = str(Path(source_dir).resolve())
    bundle_path = Path(bundle_dir).resolve() if bundle_dir is not None else None
    effective_bundle_id = bundle_id or (bundle_path.name if bundle_path else None)
    tool_dir = bundle_tool_dir(bundle_path) if bundle_path is not None else None
    scripts_dir = scripts_dir_for(tool_dir) if tool_dir is not None else SCRIPTS_DIR

    # ── Phase 1: group operations by (class_name, module_path) ──
    # Each group → one wrapper script.
    # Module path is per-file (file_stem), not per-component, because a
    # single component can contain operations from multiple .py files.

    from collections import defaultdict

    # Key: (class_name_or_None, module_path_for_file)
    # Value: list of SourceOperation
    groups: dict[tuple[str | None, str], list[SourceOperation]] = defaultdict(list)
    # Per-operation module path cache
    op_module_map: dict[int, str] = {}

    # Maps (class_name, module_path) → init params for wrapper generation
    group_init_params: dict[tuple[str | None, str], list[ParamSpec]] = {}
    # Per-module ``cmd_*`` → CLI subcommand (from ``main()`` dispatch table)
    cli_dispatch_by_module: dict[str, dict[str, str]] = {}

    for comp in components:
        for op in comp.operations:
            module_path = _resolve_module_path(comp, source_dir_abs, op.file_stem or "unknown")
            key = (op.class_name, module_path)
            groups[key].append(op)
            op_module_map[id(op)] = module_path
            if op.class_name and op.class_name in comp.class_init_params:
                group_init_params.setdefault(key, comp.class_init_params[op.class_name])
            if op.class_name is None and (op.file_stem or "") == "cli":
                cli_dispatch_by_module.setdefault(
                    module_path,
                    _parse_cli_dispatch_map(_resolve_source_file(source_dir_abs, module_path)),
                )

    # ── Phase 2: generate wrapper scripts ──

    # Maps (class_name, module_path) → script absolute path
    script_paths: dict[tuple[str | None, str], str] = {}

    for (class_name, module_path), ops in groups.items():
        first_op = ops[0]
        file_stem = first_op.file_stem or "functions"

        script_path = _generate_wrapper_script(
            ops,
            class_name=class_name,
            module_name=module_path,
            file_stem=file_stem,
            source_dir=source_dir_abs,
            scripts_dir=scripts_dir,
            init_params=group_init_params.get((class_name, module_path)),
            cli_dispatch_map=cli_dispatch_by_module.get(module_path),
            cli_prefix_override=cli_prefix_override,
        )
        script_paths[(class_name, module_path)] = str(script_path.resolve())

    # ── Phase 3: create AgentToolSpec for each operation ──

    name_map: dict[str, str] = {}
    specs: list[AgentToolSpec] = []

    for comp in components:
        for op in comp.operations:
            module_path = op_module_map[id(op)]
            key = (op.class_name, module_path)
            script_path = script_paths[key]

            init_params = (
                comp.class_init_params.get(op.class_name, [])
                if op.class_name
                else None
            )
            dispatch_map = cli_dispatch_by_module.get(module_path, {})
            cli_subcommand = (
                dispatch_map.get(op.name)
                if _is_cli_handler_op(op, dispatch_map)
                else None
            )
            spec = operation_to_spec(
                op,
                source_dir=source_dir_abs,
                script_path=script_path,
                comp_name=comp.name,
                bundle_id=effective_bundle_id,
                init_params=init_params,
                cli_subcommand=cli_subcommand,
            )

            # Validate the spec
            validate_spec(spec)

            specs.append(spec)

            # Build name mapping (original → kebab-case).
            # Primary name: {comp_name}.{op_name} — matches grouper convention
            # and is used as the tool's registered name.
            grouper_name = f"{comp.name}.{op.name}"
            name_map[grouper_name] = spec.name

            # Also register fallback names for robust lookup
            if op.class_name:
                class_name_raw = f"{op.class_name}.{op.name}"
                name_map[class_name_raw] = spec.name
            if op.file_stem:
                file_stem_raw = f"{op.file_stem}.{op.name}"
                if file_stem_raw != grouper_name:
                    name_map[file_stem_raw] = spec.name
            # Class-qualified form: {comp}.{class}.{op} — used by
            # COMPONENT_GROUP / KEYWORD_MATCH strategies after the
            # skill_grouper fix that includes class_name in allowed_tools.
            if op.class_name:
                comp_class_name = f"{comp.name}.{op.class_name}.{op.name}"
                name_map[comp_class_name] = spec.name
            # Fully-qualified form used by IO_RELATION strategy
            full_name = f"{comp.name}.{grouper_name}"
            name_map[full_name] = spec.name

    # ── Phase 4: persist specs (JSON files) ──

    if persist:
        if tool_dir is not None:
            tool_dir.mkdir(parents=True, exist_ok=True)
        for spec in specs:
            target_dir = tool_dir or TOOL_DIR
            spec_path = target_dir / f"{spec.name}.json"
            if not overwrite and spec_path.exists():
                logger.debug("Tool spec already exists, skipping: %s", spec.name)
                continue
            save_spec(spec, tool_dir=tool_dir)
            logger.info("Persisted tool spec: %s -> %s", spec.name, spec_path.parent)

    logger.info(
        "Registered %d tools from %d components (%d wrapper scripts)",
        len(specs),
        len(components),
        len(script_paths),
    )

    return name_map

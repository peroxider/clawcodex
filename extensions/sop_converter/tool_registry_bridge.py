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

import hashlib
import logging
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

    # Direct lookup
    return _TYPE_MAP.get(cleaned, "string")


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

        source_dir   = "/mnt/d/projects/JiuwenAgent/openjiuwen"
        component.file_path = "openjiuwen/core/foundation"
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

_SOURCE_DIR = r"{source_dir}"
sys.path.insert(0, _SOURCE_DIR)

_instances = {{}}


def _suppress_sdk_logging() -> None:
    """Reduce noisy SDK init logs before importing openjiuwen modules."""
    import logging

    logging.basicConfig(level=logging.WARNING, force=True)
    try:
        from openjiuwen.core.common.logging.log_config import configure_log_config

        configure_log_config({{
            "backend": "default",
            "level": "WARNING",
            "output": [],
            "interface_output": [],
            "performance_output": [],
            "log_path": os.devnull,
        }})
    except Exception:
        pass


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
    _suppress_sdk_logging()
    try:
        result = fn(**args)
        print(json.dumps(result, default=str, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({{"error": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
'''


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
        else op.parameters
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

    # Build body: helper(s) + method stubs
    body_parts: list[str] = []

    if class_name:
        body_parts.append(_generate_get_instance_helper(init_params))

    # Sort operations by name for deterministic output
    for op in sorted(ops, key=lambda o: o.name):
        body_parts.append("")
        body_parts.append(
            _generate_method_stub(
                op,
                is_class_method=class_name is not None,
                module_name=module_name,
                init_params=init_params if class_name is not None else None,
            )
        )

    content = _WRAPPER_SCRIPT_TEMPLATE.format(
        header_label=header_label,
        source_dir=source_dir,
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
    schema_params = (
        _merge_init_and_method_params(init_params or [], op.parameters)
        if op.class_name
        else op.parameters
    )
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []

    for param in schema_params:
        # Skip *args and **kwargs
        if param.name.startswith("*"):
            continue

        prop: dict[str, Any] = {
            "type": _type_hint_to_json_type(param.type_hint),
        }
        if param.description:
            prop["description"] = param.description
        if param.default is not None:
            prop["default"] = param.default

        properties[param.name] = prop

        if param.required and param.default is None:
            required.append(param.name)

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

    for comp in components:
        for op in comp.operations:
            module_path = _resolve_module_path(comp, source_dir_abs, op.file_stem or "unknown")
            key = (op.class_name, module_path)
            groups[key].append(op)
            op_module_map[id(op)] = module_path
            if op.class_name and op.class_name in comp.class_init_params:
                group_init_params.setdefault(key, comp.class_init_params[op.class_name])

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
            spec = operation_to_spec(
                op,
                source_dir=source_dir_abs,
                script_path=script_path,
                comp_name=comp.name,
                bundle_id=effective_bundle_id,
                init_params=init_params,
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

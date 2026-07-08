"""Resolve Python type hints to rich JSON Schema for pos convert tool specs.

When a type hint refers to a Pydantic ``BaseModel`` or ``@dataclass`` defined
under *source_dir*, emit structured properties plus a minimal ``examples`` entry
instead of a bare ``{"type": "string"}`` / ``{"type": "object"}``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

_PRIMITIVE_JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "null", "array", "object"})


def _has_top_level_union(hint: str) -> bool:
    """True when ``|`` separates union members outside of brackets."""
    depth = 0
    for ch in hint:
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth = max(depth - 1, 0)
        elif ch == "|" and depth == 0:
            return True
    return False


def _split_union(type_hint: str) -> list[str]:
    """Split ``A | B | None`` / ``Union[A, B]`` into non-None member hints."""
    cleaned = type_hint.strip()
    if not cleaned:
        return []

    if cleaned.startswith("Union[") and cleaned.endswith("]"):
        inner = cleaned[len("Union[") : -1]
        parts = [p.strip() for p in inner.split(",")]
    elif _has_top_level_union(cleaned):
        parts = []
        current: list[str] = []
        depth = 0
        for ch in cleaned:
            if ch in "[({":
                depth += 1
            elif ch in "])}":
                depth = max(depth - 1, 0)
            if ch == "|" and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
            current.append(ch)
        parts.append("".join(current).strip())
    else:
        parts = [cleaned]

    out: list[str] = []
    for part in parts:
        if part in ("None", "NoneType"):
            continue
        if part.startswith("Optional[") and part.endswith("]"):
            out.extend(_split_union(part[len("Optional[") : -1]))
        else:
            out.append(part)
    return out


def _type_root(type_hint: str) -> str:
    cleaned = type_hint.strip()
    if cleaned.startswith(("Optional[", "Union[")):
        parts = _split_union(cleaned)
        return parts[0].split("[", 1)[0] if parts else cleaned
    return cleaned.split("[", 1)[0]


@lru_cache(maxsize=32)
def _build_class_index(source_dir: str) -> dict[str, str]:
    """Map class name → dotted module path under *source_dir*."""
    root = Path(source_dir).resolve()
    index: dict[str, str] = {}
    if not root.is_dir():
        return index

    for path in root.rglob("*.py"):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        module = ".".join(rel.with_suffix("").parts)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                index.setdefault(node.name, module)
    return index


def _import_type(source_dir: str, type_name: str) -> type[Any] | None:
    return _import_resolved_type(source_dir, type_name, module_path=None)


def _resolve_type_import(
    source_dir: str,
    type_hint: str,
    module_path: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a type hint to ``(module_path, class_name)`` via module import index."""
    from .import_alias_resolver import ModuleImportIndex

    root = _type_root(type_hint)
    if not root:
        return None
    if module_path:
        try:
            resolved = ModuleImportIndex(source_dir).resolve_import_path(module_path, root)
            if resolved:
                return resolved
        except Exception:
            pass
    index = _build_class_index(source_dir)
    indexed = index.get(root)
    if indexed:
        return indexed, root
    return None


def _import_resolved_type(
    source_dir: str,
    type_hint: str,
    module_path: str | None = None,
) -> type[Any] | None:
    resolved = _resolve_type_import(source_dir, type_hint, module_path)
    if not resolved:
        return None
    mp, class_name = resolved
    root = str(Path(source_dir).resolve())
    inserted = False
    if root not in sys.path:
        sys.path.insert(0, root)
        inserted = True
    try:
        module = importlib.import_module(mp)
        obj = getattr(module, class_name, None)
        return obj if isinstance(obj, type) else None
    except Exception as exc:  # pragma: no cover - import failures are expected
        logger.debug("Could not import %s from %s: %s", class_name, mp, exc)
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


def _is_pydantic_model(cls: type[Any]) -> bool:
    try:
        from pydantic import BaseModel
    except ImportError:
        return False
    return isinstance(cls, type) and issubclass(cls, BaseModel)


def _is_dataclass_type(cls: type[Any]) -> bool:
    return isinstance(cls, type) and dataclasses.is_dataclass(cls)


# ---------------------------------------------------------------------------
# Public helpers for wrapper generation (deserialization)
# ---------------------------------------------------------------------------


def import_type(source_dir: str, type_name: str) -> type[Any] | None:
    """Public wrapper around :func:`_import_type`."""
    return _import_type(source_dir, type_name)


def is_pydantic_model(cls: type[Any]) -> bool:
    """Public wrapper around :func:`_is_pydantic_model`."""
    return _is_pydantic_model(cls)


def is_dataclass_type(cls: type[Any]) -> bool:
    """Public wrapper around :func:`_is_dataclass_type`."""
    return _is_dataclass_type(cls)


def type_root(type_hint: str) -> str:
    """Public wrapper around :func:`_type_root`."""
    return _type_root(type_hint)


def split_union(type_hint: str) -> list[str]:
    """Public wrapper around :func:`_split_union`."""
    return _split_union(type_hint)


def get_type_module_path(source_dir: str, type_name: str) -> str | None:
    """Return the dotted module path where *type_name* is defined under *source_dir*."""
    index = _build_class_index(source_dir)
    return index.get(type_name)


def _class_node_from_ast(source_dir: str, type_name: str) -> ast.ClassDef | None:
    """Return the ``ClassDef`` AST node for *type_name* under *source_dir*, or None."""
    module_path = get_type_module_path(source_dir, type_name)
    if not module_path:
        return None
    root = Path(source_dir).resolve()
    rel = Path(*module_path.split(".")).with_suffix(".py")
    path = root / rel
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == type_name:
            return node
    return None


def get_model_class_info(
    source_dir: str, type_name: str, module_path: str | None = None
) -> tuple[str, str, str] | None:
    """Return ``(module_path, class_name, kind)`` when *type_name* is a model class.

    *kind* is ``"pydantic"`` for ``BaseModel`` subclasses or ``"dataclass"`` for
    decorated dataclasses.  When *module_path* is given, resolve through that
    module's import aliases (same as wrapper coercion).
    """
    resolved = _resolve_type_import(source_dir, type_name, module_path)
    if not resolved:
        return None
    module_path, class_name = resolved

    # Try runtime import first (more accurate).
    cls = _import_resolved_type(source_dir, type_name, module_path)
    if cls is not None:
        if _is_pydantic_model(cls):
            return module_path, class_name, "pydantic"
        if _is_dataclass_type(cls):
            return module_path, class_name, "dataclass"

    # Fallback to AST inspection.
    class_node = _class_node_from_module(source_dir, module_path, class_name)
    if class_node is None:
        return None

    root = Path(source_dir).resolve()
    rel = Path(*module_path.split(".")).with_suffix(".py")
    path = root / rel
    module_classes: dict[str, ast.ClassDef] = {}
    if path.is_file():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            module_classes = _module_class_index(tree)
        except (OSError, SyntaxError, UnicodeDecodeError):
            module_classes = {}

    if _ast_is_pydantic_class(class_node, module_classes):
        return module_path, class_name, "pydantic"

    if _has_dataclass_decorator(class_node):
        return module_path, class_name, "dataclass"

    return None


def _class_node_from_module(
    source_dir: str, module_path: str, class_name: str
) -> ast.ClassDef | None:
    """Return the ``ClassDef`` AST node for *class_name* in *module_path*."""
    root = Path(source_dir).resolve()
    rel = Path(*module_path.split(".")).with_suffix(".py")
    path = root / rel
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _annotation_to_hint(annotation: Any) -> str:
    """Best-effort stringify of a runtime type annotation for recursive schema lookup."""
    if isinstance(annotation, str):
        return annotation
    if annotation is type(None):
        return "None"

    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", None)
    if origin is not None and args:
        origin_name = getattr(origin, "__name__", str(origin))
        arg_hints = ", ".join(_annotation_to_hint(arg) for arg in args)
        return f"{origin_name}[{arg_hints}]"

    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation)


def _has_dataclass_decorator(class_node: ast.ClassDef) -> bool:
    for dec in class_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return True
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "dataclass":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            return True
    return False


def _dataclass_schema_from_cls(
    cls: type[Any],
    source_dir: str,
    *,
    module_path: str | None = None,
) -> dict[str, Any] | None:
    """Build JSON Schema from a runtime dataclass type."""
    if not _is_dataclass_type(cls):
        return None

    try:
        hints = get_type_hints(cls)
    except Exception as exc:  # pragma: no cover - forward refs / import issues
        logger.debug("get_type_hints failed for %s: %s", cls.__name__, exc)
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(cls):
        if not field.init:
            continue
        hint = hints.get(field.name, field.type)
        hint_str = _annotation_to_hint(hint) if hint is not None else "Any"
        properties[field.name] = param_to_json_schema_property(
            type_hint=hint_str,
            source_dir=source_dir,
            fallback_json_type="string",
            module_path=module_path,
        )
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)

    if not properties:
        return None

    schema: dict[str, Any] = {
        "type": "object",
        "title": cls.__name__,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    schema["examples"] = [_minimal_value_for_schema(schema)]
    return schema


def _minimal_value_for_schema(schema: dict[str, Any]) -> Any:
    """Build a minimal JSON value from a JSON Schema fragment."""
    if "$ref" in schema:
        return {}
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            if option.get("type") != "null":
                return _minimal_value_for_schema(option)
        return None
    if "oneOf" in schema:
        for option in schema["oneOf"]:
            if option.get("type") != "null":
                return _minimal_value_for_schema(option)
        return None

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        example: dict[str, Any] = {}
        for key, sub in props.items():
            if key in required or len(required) <= 3:
                example[key] = _minimal_value_for_schema(sub)
        return example
    if schema_type == "array":
        items = schema.get("items") or {"type": "string"}
        return [_minimal_value_for_schema(items)]
    if schema_type == "string":
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]
        return ""
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None
    return {}


def _ast_is_pydantic_class(class_node: ast.ClassDef, module_classes: dict[str, ast.ClassDef]) -> bool:
    """True when *class_node* is a Pydantic ``BaseModel`` subclass (direct or indirect)."""
    for base in class_node.bases:
        base_name = getattr(base, "id", None) or getattr(base, "attr", None)
        if base_name == "BaseModel":
            return True
        if isinstance(base, ast.Name) and base.id in module_classes:
            if _ast_is_pydantic_class(module_classes[base.id], module_classes):
                return True
    return False


def _module_class_index(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }


def _ast_model_schema(source_dir: str, type_name: str) -> dict[str, Any] | None:
    """Fallback: build object schema from ``class Name(BaseModel):`` AST."""
    index = _build_class_index(source_dir)
    import_module = index.get(type_name)
    if not import_module:
        return None
    return _ast_model_schema_for_module(source_dir, import_module, type_name)


def _ast_collect_pydantic_properties(
    class_node: ast.ClassDef,
    module_classes: dict[str, ast.ClassDef],
    *,
    source_dir: str,
    module_path: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Collect JSON Schema properties from a Pydantic class and its local bases."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id in module_classes:
            parent_props, parent_req = _ast_collect_pydantic_properties(
                module_classes[base.id],
                module_classes,
                source_dir=source_dir,
                module_path=module_path,
            )
            properties.update(parent_props)
            for name in parent_req:
                if name not in required:
                    required.append(name)

    for stmt in class_node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            field_name = stmt.target.id
            hint = ast.unparse(stmt.annotation) if stmt.annotation else "string"
            properties[field_name] = param_to_json_schema_property(
                type_hint=hint,
                source_dir=source_dir,
                fallback_json_type="string",
                module_path=module_path,
            )
            if stmt.value is None and field_name not in required:
                required.append(field_name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    field_name = target.id
                    properties.setdefault(field_name, {"type": "string"})

    return properties, required


def _ast_model_schema_for_module(
    source_dir: str,
    import_module: str,
    class_name: str,
    *,
    module_path: str | None = None,
) -> dict[str, Any] | None:
    """Build object schema from a resolved ``(import_module, class_name)`` pair."""
    class_node = _class_node_from_module(source_dir, import_module, class_name)
    if class_node is None:
        return None

    root = Path(source_dir).resolve()
    rel = Path(*import_module.split(".")).with_suffix(".py")
    path = root / rel
    module_classes: dict[str, ast.ClassDef] = {}
    if path.is_file():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            module_classes = _module_class_index(tree)
        except (OSError, SyntaxError, UnicodeDecodeError):
            module_classes = {}

    if not _ast_is_pydantic_class(class_node, module_classes):
        return None

    properties, required = _ast_collect_pydantic_properties(
        class_node,
        module_classes,
        source_dir=source_dir,
        module_path=module_path,
    )

    if not properties:
        return None

    schema: dict[str, Any] = {
        "type": "object",
        "title": class_name,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    schema["examples"] = [_minimal_value_for_schema(schema)]
    return schema


def _ast_dataclass_schema(source_dir: str, type_name: str) -> dict[str, Any] | None:
    """Fallback: build object schema from ``@dataclass class Name:`` AST."""
    index = _build_class_index(source_dir)
    import_module = index.get(type_name)
    if not import_module:
        return None
    return _ast_dataclass_schema_for_module(source_dir, import_module, type_name)


def _ast_dataclass_schema_for_module(
    source_dir: str,
    import_module: str,
    class_name: str,
    *,
    module_path: str | None = None,
) -> dict[str, Any] | None:
    """Build dataclass object schema from a resolved ``(import_module, class_name)`` pair."""
    class_node = _class_node_from_module(source_dir, import_module, class_name)
    if class_node is None or not _has_dataclass_decorator(class_node):
        return None

    properties: dict[str, Any] = {}
    required: list[str] = []
    for stmt in class_node.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        field_name = stmt.target.id
        hint = ast.unparse(stmt.annotation) if stmt.annotation else "string"
        properties[field_name] = param_to_json_schema_property(
            type_hint=hint,
            source_dir=source_dir,
            fallback_json_type="string",
            module_path=module_path,
        )
        if stmt.value is None:
            required.append(field_name)

    if not properties:
        return None

    schema: dict[str, Any] = {
        "type": "object",
        "title": class_name,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    schema["examples"] = [_minimal_value_for_schema(schema)]
    return schema


def pydantic_schema_for_type(
    source_dir: str,
    type_hint: str,
    *,
    module_path: str | None = None,
) -> dict[str, Any] | None:
    """Return a JSON Schema dict for a structured type *type_hint*, or None."""
    root = _type_root(type_hint)
    resolved = _resolve_type_import(source_dir, type_hint, module_path)
    cls = _import_resolved_type(source_dir, type_hint, module_path)
    if cls is not None and _is_pydantic_model(cls):
        try:
            schema = cls.model_json_schema(mode="validation")
        except Exception as exc:  # pragma: no cover
            logger.debug("model_json_schema failed for %s: %s", root, exc)
            schema = None
        if schema is not None:
            example = _minimal_value_for_schema(schema)
            out: dict[str, Any] = dict(schema)
            out["examples"] = [example]
            if resolved:
                out["title"] = resolved[1]
            return out

    if cls is not None:
        dataclass_schema = _dataclass_schema_from_cls(cls, source_dir, module_path=module_path)
        if dataclass_schema is not None:
            if resolved:
                dataclass_schema["title"] = resolved[1]
            return dataclass_schema

    if resolved:
        pydantic_ast = _ast_model_schema_for_module(source_dir, resolved[0], resolved[1], module_path=module_path)
        if pydantic_ast is not None:
            return pydantic_ast
        return _ast_dataclass_schema_for_module(source_dir, resolved[0], resolved[1], module_path=module_path)

    pydantic_ast = _ast_model_schema(source_dir, root)
    if pydantic_ast is not None:
        return pydantic_ast

    return _ast_dataclass_schema(source_dir, root)


def param_to_json_schema_property(
    *,
    type_hint: str | None,
    description: str = "",
    source_dir: str | None = None,
    fallback_json_type: str = "string",
    module_path: str | None = None,
) -> dict[str, Any]:
    """Convert a parameter type hint to a JSON Schema property dict."""
    if not type_hint:
        prop: dict[str, Any] = {"type": fallback_json_type}
        if description:
            prop["description"] = description
        return prop

    union_parts = _split_union(type_hint)
    if len(union_parts) > 1 and source_dir:
        variants: list[dict[str, Any]] = []
        for part in union_parts:
            sub = param_to_json_schema_property(
                type_hint=part,
                source_dir=source_dir,
                fallback_json_type=fallback_json_type,
                module_path=module_path,
            )
            variants.append(sub)
        prop = {"anyOf": variants}
        if description:
            prop["description"] = description
        return prop

    if source_dir:
        model_schema = pydantic_schema_for_type(
            source_dir, type_hint, module_path=module_path
        )
        if model_schema is not None:
            prop = dict(model_schema)
            if description and not prop.get("description"):
                prop["description"] = description
            return prop

    # Generic containers: preserve type but annotate inner model when possible.
    cleaned = type_hint.strip()
    if cleaned.startswith(("Dict[", "dict[", "Mapping[", "mapping[")) and source_dir:
        inner = cleaned.split("[", 1)[-1].rstrip("]").split(",")[-1].strip()
        inner_schema = pydantic_schema_for_type(
            source_dir, inner, module_path=module_path
        )
        prop = {"type": "object"}
        if inner_schema is not None:
            prop["additionalProperties"] = inner_schema
        if description:
            prop["description"] = description
        return prop

    if cleaned.startswith(
        ("List[", "list[", "Sequence[", "Iterable[", "Set[", "set[")
    ) and source_dir:
        inner = cleaned.split("[", 1)[-1].rstrip("]").split(",")[0].strip()
        inner_schema = pydantic_schema_for_type(
            source_dir, inner, module_path=module_path
        )
        prop: dict[str, Any] = {"type": "array"}
        if inner_schema is not None:
            prop["items"] = inner_schema
        elif inner:
            prop["items"] = param_to_json_schema_property(
                type_hint=inner,
                source_dir=source_dir,
                fallback_json_type=fallback_json_type,
                module_path=module_path,
            )
        if description:
            prop["description"] = description
        return prop

    prop = {"type": fallback_json_type}
    if description:
        prop["description"] = description
    return prop

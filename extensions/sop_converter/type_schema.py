"""Type Schema — Python type hints → JSON Schema property conversion.

Provides ``param_to_json_schema_property`` which is the user-facing entry
point for converting a parsed ``ParamSpec.type_hint`` string into a JSON
Schema property fragment.

Supported conversions
--------------------
*   ``Literal["a", "b"]``  → ``{"type": "string", "enum": ["a", "b"]}``
*   ``Annotated[X, ...]``  → unwrap inner type ``X``, recurse
*   ``Optional[X]`` / ``Union[X, None]`` / ``X | None`` → nullable object
*   Fallback                → ``{"type": <fallback_json_type>, "description": ...}``
"""

from __future__ import annotations

import ast
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_LITERAL_PATTERN = re.compile(r"^Literal\s*\[\s*(.*?)\s*\]\s*$", re.DOTALL)

_ANNOTATED_PATTERN = re.compile(r"^Annotated\s*\[\s*(.+?)\s*,", re.DOTALL)

_OPTIONAL_PATTERN = re.compile(r"^Optional\s*\[\s*(.+?)\s*\]\s*$", re.DOTALL)

_UNION_PATTERN = re.compile(r"^Union\s*\[\s*(.+?)\s*\]\s*$", re.DOTALL)


def _extract_literal_values(type_hint: str) -> list[Any] | None:
    """Extract enum values from a ``Literal[...]`` type hint.

    Returns ``None`` when *type_hint* is not a valid Literal.
    """
    m = _LITERAL_PATTERN.match(type_hint.strip())
    if not m:
        return None

    raw = m.group(1).strip()
    values: list[Any] = []
    for token in _split_literal_args(raw):
        values.append(_parse_literal_value(token))
    return values


def _split_literal_args(raw: str) -> list[str]:
    """Split Literal arguments on ``,`` respecting quoted strings and brackets."""
    args: list[str] = []
    depth = 0
    in_quote: str | None = None
    buf: list[str] = []
    for ch in raw:
        if in_quote:
            buf.append(ch)
            if ch == in_quote and (not buf or buf[-2] != "\\"):
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            buf.append(ch)
            continue
        if ch in ("[", "(", "{"):
            depth += 1
            buf.append(ch)
            continue
        if ch in ("]", ")", "}"):
            depth -= 1
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return args


def _parse_literal_value(token: str) -> Any:
    """Parse a single Literal argument into a Python value.

    Supports string literals, integers, booleans, and None.
    """
    t = token.strip()

    if t == "None":
        return None
    if t == "True":
        return True
    if t == "False":
        return False

    # String literal (single or double quotes)
    if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
        # ast.literal_eval is safe for simple string literals
        return t[1:-1]

    # Integer / float
    try:
        return ast.literal_eval(t)
    except (ValueError, SyntaxError):
        return t


def _unwrap_annotated(type_hint: str) -> str:
    """Strip ``Annotated[X, ...]`` wrapper, returning the inner type ``X``."""
    m = _ANNOTATED_PATTERN.match(type_hint.strip())
    if m:
        return m.group(1).strip()
    return type_hint


def _unwrap_optional(type_hint: str) -> str | None:
    """Strip ``Optional[X]`` / ``Union[X, None]`` / ``X | None`` wrapper.

    Returns the inner type string, or ``None`` if not optional.
    """
    cleaned = type_hint.strip()

    # Optional[X]
    m = _OPTIONAL_PATTERN.match(cleaned)
    if m:
        return m.group(1).strip()

    # Union[X, None] or Union[None, X]
    m = _UNION_PATTERN.match(cleaned)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        non_none = [p for p in parts if p not in ("None", "NoneType")]
        if len(non_none) == 1:
            return non_none[0]
        if len(non_none) > 1:
            # Multiple non-None types in a Union — treat as a multi-type union
            # (not a simple optional).  Return None so the caller falls through
            # to the fallback.
            return None
        return None

    # X | None (PEP 604)
    if "|" in cleaned:
        parts = [p.strip() for p in cleaned.split("|")]
        non_none = [p for p in parts if p not in ("None", "NoneType")]
        if len(non_none) == 1 and len(parts) - len(non_none) == 1:
            return non_none[0]
        # Multiple non-None types or no None at all

    return None


def _bare_type_to_json_type(type_hint: str) -> str:
    """Map a bare (stripped of Optional/Literal) type-hint to JSON Schema type.

    Mirrors ``_type_hint_to_json_type`` from ``tool_registry_bridge.py``
    to avoid circular imports.
    """
    _TYPE_MAP: dict[str, str] = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "None": "null",
        "NoneType": "null",
        "dict": "object",
        "Dict": "object",
        "Mapping": "object",
        "Any": "string",
        "Path": "string",
        "PurePath": "string",
        "datetime": "string",
        "date": "string",
        "UUID": "string",
        "Decimal": "number",
        "bytes": "string",
    }

    cleaned = type_hint.strip()
    # List/Iterable/Set → array
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
    # Dict/Mapping → object
    if cleaned.startswith(("Dict[", "dict[", "Mapping[", "mapping[", "TypedDict")):
        return "object"

    root = cleaned.split("[", 1)[0]
    return _TYPE_MAP.get(root, "string")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def param_to_json_schema_property(
    *,
    type_hint: str | None,
    description: str,
    source_dir: str,  # Kept for API compatibility; may be used in future for
    # custom type resolution via file scanning.
    fallback_json_type: str = "string",
) -> dict[str, Any]:
    """Convert a parsed ``ParamSpec.type_hint`` to a JSON Schema property dict.

    Parameters
    ----------
    type_hint:
        The raw type annotation string (e.g. ``"Literal['a', 'b']"``,
        ``"Optional[str]"``, ``"int"``).
    description:
        Human-readable parameter description.
    source_dir:
        Absolute path to the source root (reserved for future custom type /
        Pydantic model introspection).
    fallback_json_type:
        Default JSON Schema type when no richer structure is inferred.

    Returns
    -------
    dict
        A JSON Schema property fragment with at least ``"type"`` and
        ``"description"`` keys, and optionally ``"enum"``, ``"items"``,
        ``"properties"``, etc.
    """
    if not type_hint:
        return {"type": fallback_json_type, "description": description}

    hint = type_hint.strip()

    # 1. Unwrap Annotated[X, ...] → X
    hint = _unwrap_annotated(hint)

    # 2. Check for Optional / Union[T, None] / T | None
    is_nullable = False
    inner = _unwrap_optional(hint)
    if inner is not None:
        is_nullable = True
        hint = inner

    # 3. Literal → enum
    literal_values = _extract_literal_values(hint)
    if literal_values is not None:
        # Infer the JSON type from actual values.
        value_types = {type(v).__name__ for v in literal_values if v is not None}
        if "str" in value_types or not value_types:
            json_type = "string"
        elif "int" in value_types or "float" in value_types:
            json_type = "string"  # enum values are still strings in JSON Schema
        else:
            json_type = "string"

        prop: dict[str, Any] = {
            "type": json_type,
            "description": description,
            "enum": literal_values,
        }
        if is_nullable:
            prop["type"] = [json_type, "null"]
        return prop

    # 4. Basic type mapping
    json_type = _bare_type_to_json_type(hint) or fallback_json_type
    prop = {"type": json_type, "description": description}
    if is_nullable:
        prop["type"] = [json_type, "null"]

    return prop

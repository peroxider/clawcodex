"""External operation schema support for Logical Kanban (F-154)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_PREDICATE_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*\([^()]*\)$")

@dataclass(frozen=True)
class OperationSchema:
    """A declarative operation with preconditions and effects."""

    operation_id: str
    description: str
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    estimated_duration_minutes: int | None = None
    required_resources: tuple[str, ...] = ()
    version: str = "1.0.0"
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("OperationSchema.operation_id must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("OperationSchema.description must be a string")
        for field_name in ("preconditions", "effects", "required_resources"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"OperationSchema.{field_name} must be a tuple of strings")
        if self.estimated_duration_minutes is not None:
            if (
                not isinstance(self.estimated_duration_minutes, int)
                or self.estimated_duration_minutes < 1
            ):
                raise ValueError("OperationSchema.estimated_duration_minutes must be positive")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("OperationSchema.version must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "operation_id": self.operation_id,
            "description": self.description,
            "preconditions": list(self.preconditions),
            "effects": list(self.effects),
            "required_resources": list(self.required_resources),
            "version": self.version,
        }
        if self.estimated_duration_minutes is not None:
            out["estimated_duration_minutes"] = self.estimated_duration_minutes
        if self.source:
            out["source"] = self.source
        return out

_OPERATION_REGISTRY: dict[str, OperationSchema] = {}

def predicate_name(predicate: str) -> str | None:
    """Return the predicate/class name from ``Name(args)``."""

    if not isinstance(predicate, str):
        return None
    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*\(", predicate)
    return match.group(1) if match else None

def is_predicate_expression(value: str) -> bool:
    return bool(_PREDICATE_RE.match(value.strip()))

def load_operation_schema_data(data: Any, *, source: str = "") -> tuple[OperationSchema, ...]:
    """Deserialize an operation schema JSON/YAML document."""

    if isinstance(data, dict) and isinstance(data.get("operations"), list):
        raw_operations = data["operations"]
    elif isinstance(data, list):
        raw_operations = data
    elif isinstance(data, dict) and "operation_id" in data:
        raw_operations = [data]
    else:
        raise ValueError("operation schema must be an object with operations or a list")

    out: list[OperationSchema] = []
    for index, raw in enumerate(raw_operations):
        if not isinstance(raw, dict):
            raise ValueError(f"operations[{index}] must be an object")
        operation_id = raw.get("operation_id") or raw.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError(f"operations[{index}].operation_id must be a non-empty string")
        out.append(
            OperationSchema(
                operation_id=operation_id,
                description=str(raw.get("description", "")),
                preconditions=_tuple_of_strings(raw.get("preconditions", []), operation_id),
                effects=_tuple_of_strings(raw.get("effects", []), operation_id),
                estimated_duration_minutes=raw.get("estimated_duration_minutes")
                or raw.get("estimatedDurationMinutes"),
                required_resources=_tuple_of_strings(
                    raw.get("required_resources", raw.get("requiredResources", [])),
                    operation_id,
                    allow_empty=True,
                ),
                version=str(raw.get("version", "1.0.0")),
                source=source,
            )
        )
    return tuple(out)

def register_operation_schema(operation: OperationSchema, *, force: bool = False) -> None:
    existing = _OPERATION_REGISTRY.get(operation.operation_id)
    if existing is not None and not force:
        raise ValueError(
            f"operation_id {operation.operation_id!r} already registered from "
            f"{existing.source or '<memory>'}"
        )
    _OPERATION_REGISTRY[operation.operation_id] = operation

def register_operation_schemas(
    operations: tuple[OperationSchema, ...], *, force: bool = False
) -> None:
    for operation in operations:
        register_operation_schema(operation, force=force)

def get_operation_schema(operation_id: str) -> OperationSchema | None:
    return _OPERATION_REGISTRY.get(operation_id)

def get_all_operation_schemas() -> tuple[OperationSchema, ...]:
    return tuple(_OPERATION_REGISTRY.values())

def reset_operation_registry() -> None:
    _OPERATION_REGISTRY.clear()

def _tuple_of_strings(value: Any, owner: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"operation {owner!r}: expected a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"operation {owner!r}: list entries must be strings")
        if item or allow_empty:
            out.append(item)
    return tuple(out)

__all__ = [
    "OperationSchema",
    "get_all_operation_schemas",
    "get_operation_schema",
    "is_predicate_expression",
    "load_operation_schema_data",
    "predicate_name",
    "register_operation_schema",
    "register_operation_schemas",
    "reset_operation_registry",
]

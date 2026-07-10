"""JSON-serializable encoding for SDK wrapper return values."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

# Inlined into generated wrapper scripts (scripts only have SDK on sys.path).
WRAPPER_SERIALIZATION_HELPERS = '''
def _to_jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)


def _serialize_factory_result(instance):
    """Serialize factory function return value for JSON output.
    
    Attempts to extract meaningful configuration from complex objects
    that don't have model_dump or dataclass serialization.
    """
    result = _to_jsonable(instance)
    if isinstance(result, str):
        info = {}
        for attr_name in ["agent_config", "id", "name", "description", 
                          "model", "version", "controller_type", "config"]:
            if hasattr(instance, attr_name):
                attr_val = getattr(instance, attr_name)
                if attr_val is not None:
                    try:
                        info[attr_name] = _to_jsonable(attr_val)
                    except Exception:
                        pass
        if info:
            info["_repr"] = result
            return info
    return result


def _dumps_sdk_result(result):
    import dataclasses
    import json
    return json.dumps(_to_jsonable(result), ensure_ascii=False, default=str)


def _normalize_mapping_inputs(value, *, message_key="query"):
    """Coerce tool args into a mapping when an ``inputs`` param expects a dict.

    LLM tool calls often pass a bare user message string instead of a JSON
    object.  Applies to any SDK method whose ``inputs`` parameter is typed as
    ``Any``, ``dict``, or left untyped.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {message_key: value}
    raise TypeError(
        "inputs must be a dict, e.g. {" + message_key + ': "..."}; '
        "got " + type(value).__name__ + ": " + repr(value)
    )
'''.lstrip()

# Runtime type coercion for JSON args -> SDK Pydantic/dataclass instances.
WRAPPER_COERCION_HELPERS = '''
def _parse_json_config(value):
    """Parse JSON string or dict into a dict."""
    import json
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            return json.loads(text)
    return value


def _coerce_mapping_value(value):
    """Coerce JSON tool args into a dict for mapping-typed SDK parameters.

    Accepts inline dicts or JSON object strings.  Unlike ``_normalize_mapping_inputs``,
    bare non-JSON strings are rejected — mapping params must be structured objects.
    """
    import json

    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TypeError(
                    "expected a JSON object string for mapping parameter; "
                    f"invalid JSON: {exc}"
                ) from exc
            if isinstance(parsed, dict):
                return parsed
            raise TypeError(
                "expected a JSON object for mapping parameter; "
                f"got {type(parsed).__name__}"
            )
        raise TypeError(
            "expected a dict or JSON object string for mapping parameter; "
            f"got str: {value!r}"
        )
    raise TypeError(
        "expected a dict or JSON object string for mapping parameter; "
        f"got {type(value).__name__}: {value!r}"
    )


def _coerce_sdk_type(cls, value):
    """Coerce a JSON-decoded value into *cls* (Pydantic model, dataclass, or constructor)."""
    import dataclasses
    from typing import Any, Union, get_args, get_origin, get_type_hints

    if value is None:
        return None
    if isinstance(value, cls):
        return value

    origin = get_origin(cls)
    args = get_args(cls)

    if origin is Union:
        candidates = [a for a in args if a is not type(None) and a is not None]
        if len(candidates) == 1:
            return _coerce_sdk_type(candidates[0], value)
        for candidate in candidates:
            try:
                return _coerce_sdk_type(candidate, value)
            except (TypeError, ValueError):
                continue
        raise TypeError(f"Cannot coerce {value!r} to {cls}")

    if origin in (list, tuple, set, frozenset):
        inner = args[0] if args else Any
        coerced = [_coerce_sdk_type(inner, item) for item in (value or [])]
        if origin is tuple:
            return tuple(coerced)
        if origin is set:
            return set(coerced)
        if origin is frozenset:
            return frozenset(coerced)
        return coerced

    if origin is dict or cls in (dict,):
        return value

    if not isinstance(value, dict):
        return cls(value)

    if dataclasses.is_dataclass(cls) and isinstance(cls, type):
        hints = {}
        try:
            hints = get_type_hints(cls)
        except Exception:
            pass
        kwargs = {}
        for field in dataclasses.fields(cls):
            if field.name not in value:
                continue
            raw = value[field.name]
            ann = hints.get(field.name, field.type)
            if ann is Any or ann is None:
                kwargs[field.name] = raw
            else:
                kwargs[field.name] = _coerce_sdk_type(ann, raw)
        return cls(**kwargs)

    if hasattr(cls, "model_validate"):
        return cls.model_validate(value)

    return cls(**value)
'''.lstrip()


WRAPPER_TEAM_DATABASE_COERCION = '''
def _coerce_team_database(value):
    """Coerce JSON config into TeamDatabase instance.
    
    Handles both inline dict and JSON string inputs.
    Auto-initializes the database for synchronous wrapper context.
    """
    import asyncio
    from openjiuwen.agent_teams.tools.database import TeamDatabase
    from openjiuwen.agent_teams.tools.database.config import DatabaseConfig
    
    if isinstance(value, TeamDatabase):
        return value
    
    cfg = _parse_json_config(value)
    if isinstance(cfg, dict):
        if "config" in cfg:
            cfg = cfg["config"]
        if not cfg.get("connection_string"):
            cfg = {**cfg, "connection_string": ":memory:"}
        db = TeamDatabase(DatabaseConfig.model_validate(cfg))
        
        try:
            asyncio.run(db.initialize())
        except RuntimeError as e:
            if "Event loop is running" in str(e):
                loop = asyncio.get_running_loop()
                loop.run_until_complete(db.initialize())
            else:
                raise
        
        return db
    
    raise TypeError(f"Cannot coerce db from {type(value).__name__}")
'''.lstrip()


WRAPPER_MESSAGER_COERCION = '''
def _coerce_messager(value, *, team_name=None):
    """Coerce JSON config into Messager instance.
    
    Handles both inline dict and JSON string inputs.
    Uses create_messager factory for ABC types.
    """
    from openjiuwen.agent_teams.messager.base import (
        MessagerTransportConfig,
        create_messager,
    )
    from openjiuwen.agent_teams.messager.messager import Messager
    
    if isinstance(value, Messager):
        return value
    
    cfg = _parse_json_config(value)
    if isinstance(cfg, dict):
        if "backend" not in cfg:
            cfg = {**cfg, "backend": "inprocess"}
        if team_name and not cfg.get("team_name"):
            cfg = {**cfg, "team_name": team_name}
        return create_messager(MessagerTransportConfig.model_validate(cfg))
    
    raise TypeError(f"Cannot coerce messager from {type(value).__name__}")
'''.lstrip()


def normalize_mapping_inputs(value: Any, *, message_key: str = "query") -> dict[str, Any]:
    """Coerce tool args into a mapping when an ``inputs`` param expects a dict.

    Used by generated SDK wrapper scripts (see ``WRAPPER_SERIALIZATION_HELPERS``)
    and unit tests.  Generic rule: bare strings become ``{message_key: value}``.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {message_key: value}
    raise TypeError(
        f"inputs must be a dict, e.g. {{\"{message_key}\": \"...\"}}; "
        f"got {type(value).__name__}: {value!r}"
    )


def coerce_mapping_value(value: Any) -> dict[str, Any] | None:
    """Coerce tool args into a dict for mapping-typed SDK parameters."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            raise TypeError(
                f"expected a JSON object for mapping parameter; got {type(parsed).__name__}"
            )
        raise TypeError(
            "expected a dict or JSON object string for mapping parameter; "
            f"got str: {value!r}"
        )
    raise TypeError(
        "expected a dict or JSON object string for mapping parameter; "
        f"got {type(value).__name__}: {value!r}"
    )


def to_jsonable(obj: Any) -> Any:
    """Recursively convert SDK objects to JSON-compatible data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)

    return str(obj)


def dumps_sdk_result(result: Any) -> str:
    return json.dumps(to_jsonable(result), ensure_ascii=False, default=str)

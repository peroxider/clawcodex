"""JSON-serializable encoding for SDK wrapper return values."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

# Inlined into generated wrapper scripts (scripts only have SDK on sys.path).
WRAPPER_SERIALIZATION_HELPERS = '''
_RESOLVED_ENV_REFERENCES = {}


def _redact_sensitive_fields(value):
    """Keep factory output and catalog DSL safe for agent-facing transport."""
    sensitive_tokens = ("api_key", "apikey", "access_token", "secret", "password")
    if isinstance(value, dict):
        return {
            str(key): (
                _RESOLVED_ENV_REFERENCES.get(str(item), "<redacted>")
                if any(token in str(key).lower() for token in sensitive_tokens)
                else _redact_sensitive_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_fields(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive_fields(item) for item in value]
    return value


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
                        info[attr_name] = _redact_sensitive_fields(_to_jsonable(attr_val))
                    except Exception:
                        pass
        if info:
            info["_runtime_type"] = {
                "module": type(instance).__module__,
                "class_name": type(instance).__name__,
            }
            try:
                import inspect
                invoke = getattr(instance, "invoke", None)
                if callable(invoke):
                    params = list(inspect.signature(invoke).parameters)
                    if params:
                        info["_runtime_invoker"] = {
                            "method": "invoke",
                            "input_param": params[0],
                        }
            except (TypeError, ValueError):
                pass
            info["_repr"] = result
            return info
    return result


def _dumps_sdk_result(result):
    import dataclasses
    import json
    return json.dumps(_redact_sensitive_fields(_to_jsonable(result)), ensure_ascii=False, default=str)


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
def _resolve_env_references(value):
    """Resolve explicit ``env:NAME`` references without exposing their values."""
    import os
    import re

    if isinstance(value, str) and value.startswith("env:"):
        name = value[4:].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid environment-variable reference: {value!r}")
        resolved = os.environ.get(name)
        if resolved is None:
            raise ValueError(f"environment variable is not set: {name}")
        _RESOLVED_ENV_REFERENCES[str(resolved)] = f"env:{name}"
        return resolved
    if isinstance(value, dict):
        resolved_dict = {}
        for key, item in value.items():
            if (
                str(key).lower() in {"api_key", "apikey", "access_token"}
                and isinstance(item, str)
                and item.startswith("$")
            ):
                raise ValueError(
                    "shell-style secret references are unsupported; use env:NAME"
                )
            resolved_dict[key] = _resolve_env_references(item)
        return resolved_dict
    if isinstance(value, list):
        return [_resolve_env_references(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_env_references(item) for item in value)
    return value


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
    bare non-JSON strings are rejected; mapping params must be structured objects.
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


def _promote_flat_llm_agent_config(value):
    """Lift natural-language create payloads into nested ModelConfig shape.

    Agents often pass::

        {"id": "...", "provider": "deepseek", "model": "deepseek-v4-flash",
         "api_key": "env:...", "api_base": "https://..."}

    while LegacyReActAgentConfig expects::

        {"id": "...", "model": {"model_provider": "deepseek",
         "model_info": {"model": "...", "api_key": "...", "api_base": "..."}}}

    Leaf ``model_info`` dicts (string ``model`` + api_key/api_base, no agent
    identity fields) must not be rewritten.
    """
    if not isinstance(value, dict):
        return value
    # Agent-config markers — BaseModelInfo / model_info payloads lack these.
    if not any(
        key in value
        for key in ("provider", "id", "prompt_template", "controller_type")
    ):
        return value
    model = value.get("model")
    flat_keys = ("provider", "api_key", "api_base", "model_name", "model_provider")
    has_flat = any(key in value for key in flat_keys)
    if isinstance(model, dict) and not has_flat:
        return value
    if model is not None and not isinstance(model, str) and not has_flat:
        return value
    if isinstance(model, dict):
        model_obj = dict(model)
        raw_info = model_obj.get("model_info")
        info = dict(raw_info) if isinstance(raw_info, dict) else {}
    else:
        model_obj = {}
        info = {}
    provider = (
        model_obj.get("model_provider")
        or value.get("provider")
        or value.get("model_provider")
        or ""
    )
    if isinstance(model, str) and model.strip():
        info.setdefault("model", model.strip())
    model_name = value.get("model_name")
    if isinstance(model_name, str) and model_name.strip() and "model" not in info:
        info["model"] = model_name.strip()
    for src, dest in (("api_key", "api_key"), ("api_base", "api_base")):
        if src in value and dest not in info:
            info[dest] = value[src]
    if not provider and not info:
        return value
    promoted = dict(value)
    promoted["model"] = {"model_provider": provider, "model_info": info}
    for key in flat_keys:
        promoted.pop(key, None)
    return promoted


def _coerce_sdk_type(cls, value):
    """Coerce a JSON-decoded value into *cls* (Pydantic model, dataclass, or constructor)."""
    import dataclasses
    from typing import Any, Union, get_args, get_origin, get_type_hints

    value = _resolve_env_references(value)
    if value is None:
        return None
    if cls is Any or cls is object:
        return value
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
        if (
            dataclasses.is_dataclass(cls)
            and isinstance(cls, type)
            and isinstance(value, str)
        ):
            field_names = {field.name for field in dataclasses.fields(cls)}
            if "model_provider" in field_names and "model_info" in field_names:
                return _coerce_sdk_type(
                    cls,
                    {
                        "model_provider": "",
                        "model_info": {"model": value},
                    },
                )
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
        if isinstance(value, dict):
            value = _promote_flat_llm_agent_config(value)
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


def resolve_env_references(value: Any, *, environ: dict[str, str] | None = None) -> Any:
    """Resolve explicit ``env:NAME`` values recursively.

    Only the ``env:`` syntax is a supported reference. Shell-style forms such
    as ``$NAME`` remain ordinary strings so secrets are never implicitly
    expanded or printed by an agent-facing tool response.
    """
    import os
    import re

    environment = os.environ if environ is None else environ
    if isinstance(value, str) and value.startswith("env:"):
        name = value[4:].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid environment-variable reference: {value!r}")
        resolved = environment.get(name)
        if resolved is None:
            raise ValueError(f"environment variable is not set: {name}")
        return resolved
    if isinstance(value, dict):
        resolved_dict: dict[Any, Any] = {}
        for key, item in value.items():
            if (
                str(key).lower() in {"api_key", "apikey", "access_token"}
                and isinstance(item, str)
                and item.startswith("$")
            ):
                raise ValueError(
                    "shell-style secret references are unsupported; use env:NAME"
                )
            resolved_dict[key] = resolve_env_references(item, environ=environment)
        return resolved_dict
    if isinstance(value, list):
        return [resolve_env_references(item, environ=environment) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_env_references(item, environ=environment) for item in value)
    return value


def promote_flat_llm_agent_config(value: Any) -> Any:
    """Lift flat create payloads into nested ``ModelConfig`` shape.

    Mirrors the helper embedded in generated SDK wrappers so runtime factory
    calls (runtime materialize) accept the same natural-language ``agent_config`` form.

    Leaf ``model_info`` dicts (string ``model`` + credentials, no agent
    identity fields) must not be rewritten.
    """
    if not isinstance(value, dict):
        return value
    if not any(
        key in value
        for key in ("provider", "id", "prompt_template", "controller_type")
    ):
        return value
    model = value.get("model")
    flat_keys = ("provider", "api_key", "api_base", "model_name", "model_provider")
    has_flat = any(key in value for key in flat_keys)
    if isinstance(model, dict) and not has_flat:
        return value
    if model is not None and not isinstance(model, str) and not has_flat:
        return value
    if isinstance(model, dict):
        model_obj = dict(model)
        raw_info = model_obj.get("model_info")
        info = dict(raw_info) if isinstance(raw_info, dict) else {}
    else:
        model_obj = {}
        info = {}
    provider = (
        model_obj.get("model_provider")
        or value.get("provider")
        or value.get("model_provider")
        or ""
    )
    if isinstance(model, str) and model.strip():
        info.setdefault("model", model.strip())
    model_name = value.get("model_name")
    if isinstance(model_name, str) and model_name.strip() and "model" not in info:
        info["model"] = model_name.strip()
    for src, dest in (("api_key", "api_key"), ("api_base", "api_base")):
        if src in value and dest not in info:
            info[dest] = value[src]
    if not provider and not info:
        return value
    promoted = dict(value)
    promoted["model"] = {"model_provider": provider, "model_info": info}
    for key in flat_keys:
        promoted.pop(key, None)
    return promoted


def coerce_sdk_type(cls: Any, value: Any) -> Any:
    """Convert JSON-compatible *value* to an SDK annotation type.

    This is the runtime counterpart of the helper embedded into generated SDK
    wrappers. Runtime helpers use it before calling a saved factory directly.
    """
    import dataclasses
    from types import UnionType
    from typing import Any as TypingAny, Union, get_args, get_origin, get_type_hints

    value = resolve_env_references(value)
    if value is None or cls in (TypingAny, Any, object):
        return value
    try:
        if isinstance(value, cls):
            return value
    except TypeError:
        pass

    origin = get_origin(cls)
    args = get_args(cls)
    if origin in (Union, UnionType):
        candidates = [item for item in args if item is not type(None) and item is not None]
        if len(candidates) == 1:
            return coerce_sdk_type(candidates[0], value)
        for candidate in candidates:
            try:
                return coerce_sdk_type(candidate, value)
            except (TypeError, ValueError):
                continue
        raise TypeError(f"Cannot coerce {value!r} to {cls}")
    if origin in (list, tuple, set, frozenset):
        inner = args[0] if args else TypingAny
        coerced = [coerce_sdk_type(inner, item) for item in (value or [])]
        if origin is tuple:
            return tuple(coerced)
        if origin is set:
            return set(coerced)
        if origin is frozenset:
            return frozenset(coerced)
        return coerced
    if origin is dict or cls is dict:
        return value
    if not isinstance(value, dict):
        if (
            dataclasses.is_dataclass(cls)
            and isinstance(cls, type)
            and isinstance(value, str)
        ):
            field_names = {field.name for field in dataclasses.fields(cls)}
            if "model_provider" in field_names and "model_info" in field_names:
                return coerce_sdk_type(
                    cls,
                    {
                        "model_provider": "",
                        "model_info": {"model": value},
                    },
                )
        return cls(value)
    if dataclasses.is_dataclass(cls) and isinstance(cls, type):
        try:
            hints = get_type_hints(cls)
        except Exception:
            hints = {}
        kwargs: dict[str, Any] = {}
        for field in dataclasses.fields(cls):
            if field.name not in value:
                continue
            annotation = hints.get(field.name, field.type)
            kwargs[field.name] = (
                value[field.name]
                if annotation in (TypingAny, Any, None)
                else coerce_sdk_type(annotation, value[field.name])
            )
        return cls(**kwargs)
    if hasattr(cls, "model_validate"):
        if isinstance(value, dict):
            value = promote_flat_llm_agent_config(value)
        return cls.model_validate(value)
    return cls(**value)


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

#!/usr/bin/env python3
"""Auto-generated wrapper for the F-55 ``invoke-existing-agent`` macro tool.

This is the wrapper script the Agent tool spawns when an agent calls
``invoke-existing-agent(agent_id, query=...)``.  It is the
post-F-55-L1 replacement for the historic ``echo "Stages: ..."`` behaviour
that left the calling agent to re-discover the SDK.

The wrapper is intentionally self-contained: it imports
:mod:`agent_catalog` and :mod:`agent_catalog_resolver` from the SOP
converter package, and falls back gracefully with structured error JSON
when the catalog is missing, the DSL is incomplete, the SDK cannot be
imported, or the call raises.

Invocation contract (mirrors the bash call_impl emitted by
``register_composite_tools``)::

    python3 invoke_existing_agent_wrapper.py invoke_existing_agent '{json_args}'

Where ``json_args`` is a JSON object with::

    {
      "agent_id": "<id from the create step>",
      "query":    "<user input>"
    }

The wrapper tries ``agent.invoke(query=...)`` first and ``agent.run(...)``
as a fallback (matching the ``invoke_method`` field in the catalog row).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import traceback
from typing import Any

# Allow running this script standalone (``python3 invoke_existing_agent_wrapper.py``)
# from any cwd — the Agent tool's bash template invokes the script with its
# absolute path, so this is just a fallback for manual debugging.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))

# Allow imports from ``extensions/`` when the wrapper is invoked from an
# arbitrary working directory (the Agent tool's bash template may not run
# from the repository root).
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _emit(payload: dict[str, Any]) -> None:
    """Print JSON to stdout (the Agent tool's call_handlers/bash.py reads this)."""
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _emit_error(code: str, message: str, **extra: Any) -> None:
    payload = {"error": message, "error_code": code}
    payload.update(extra)
    _emit(payload)


def _resolve_call_kwargs(entry: Any, query: Any) -> tuple[str, dict[str, Any]]:
    """Pick the right method name and forward ``query`` to the right kwarg.

    The catalog row records the SDK's preferred ``invoke_method`` and
    ``query_arg``.  We honour both, falling back to the standard
    ``invoke(query=...)`` / ``run(query=...)`` conventions.
    """
    method = entry.invoke_method or "invoke"
    query_arg = entry.query_arg or "query"
    return method, {query_arg: query}


def _call_sync(agent: Any, method: str, kwargs: dict[str, Any]) -> Any:
    fn = getattr(agent, method, None)
    if fn is None:
        # Fallback chain: invoke -> run -> __call__
        for alt in ("run", "__call__"):
            fn = getattr(agent, alt, None)
            if fn is not None:
                method = alt
                break
    if fn is None:
        raise AttributeError(
            f"Agent {type(agent).__name__} exposes none of invoke/run/__call__"
        )
    result = fn(**kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


def _materialize(entry: Any) -> Any:
    """Import the SDK class and instantiate it with the recorded init kwargs.

    Sensitive fields in ``entry.init_kwargs`` are restored from
    environment variables by :class:`AgentCatalog.get` before reaching here.
    """
    if not entry.module_name or not entry.class_name:
        raise ValueError(
            f"catalog entry for {entry.agent_id!r} has no module/class; "
            "cannot materialize"
        )
    sdk_dir = entry.sdk_source_dir
    if sdk_dir and sdk_dir not in sys.path:
        sys.path.insert(0, sdk_dir)
    module = importlib.import_module(entry.module_name)
    cls = getattr(module, entry.class_name)
    try:
        return cls(**(entry.init_kwargs or {}))
    except TypeError as exc:
        # The catalog may have over-recorded kwargs if the SDK constructor
        # signature changed.  Retry with no kwargs to give a clearer error.
        if entry.init_kwargs:
            return cls()
        raise exc


def invoke_existing_agent(
    agent_id: str,
    query: str = "",
    inputs: Any = None,
    bundle_path: str | None = None,
) -> dict[str, Any]:
    """Recover an Agent from the catalog and invoke it on the user query.

    Returns a dict (not raising) on every failure path so the Agent tool
    can return a structured error rather than a stack trace.  The keys
    ``error`` / ``error_code`` are reserved; the rest of the payload is
    the SDK's return value, normalised to a dict when possible.

    NB: this function does **not** write to stdout — :func:`main` is the
    single point of output so we never double-emit a JSON blob.
    """
    from extensions.sop_converter.agent_catalog import AgentCatalog
    from extensions.sop_converter.agent_catalog_resolver import resolve_catalog_path

    if not agent_id:
        return {"error": "agent_id is required", "error_code": "invalid_input"}

    payload_query = inputs if inputs is not None else query

    # 1. Resolve catalog location.  The wrapper accepts an explicit
    #    ``bundle_path`` argument (preferred) or the optional
    #    ``CLAWCODEX_BUNDLE_PATH`` env var so the wrapper subprocess can find
    #    the same bundle-local catalog the create tool wrote.
    effective_bundle_path = bundle_path or os.environ.get("CLAWCODEX_BUNDLE_PATH", "").strip()
    try:
        loc = (
            resolve_catalog_path(effective_bundle_path)
            if effective_bundle_path
            else resolve_catalog_path()
        )
    except Exception as exc:  # pragma: no cover — defensive
        return {"error": str(exc), "error_code": "resolver_failed"}

    if not loc.path.exists():
        return {
            "error": (
                f"agent catalog not found at {loc.path} (reason={loc.reason}); "
                "did the create tool fail to persist?"
            ),
            "error_code": "agent_catalog_missing",
            "agent_id": agent_id,
            "catalog_path": str(loc.path),
        }

    # 2. Load + lookup.
    try:
        catalog = AgentCatalog.load(loc.path)
    except Exception as exc:
        return {
            "error": f"catalog_load_failed: {exc}",
            "error_code": "catalog_load_failed",
        }
    entry = catalog.get(agent_id)
    if entry is None:
        return {
            "error": f"agent {agent_id} not in catalog at {loc.path}",
            "error_code": "agent_not_in_catalog",
            "agent_id": agent_id,
        }

    # 3. Materialize.
    try:
        agent = _materialize(entry)
    except ModuleNotFoundError as exc:
        return {
            "error": f"materialize_failed: module not found: {exc}",
            "error_code": "materialize_failed",
            "agent_id": agent_id,
            "module_name": entry.module_name,
        }
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        return {
            "error": f"materialize_failed: {exc}",
            "error_code": "materialize_failed",
            "agent_id": agent_id,
        }

    # 4. Invoke.
    method, kwargs = _resolve_call_kwargs(entry, payload_query)
    try:
        result = _call_sync(agent, method, kwargs)
    except Exception as exc:
        return {
            "error": f"invoke_failed: {exc}",
            "error_code": "invoke_failed",
            "agent_id": agent_id,
            "method": method,
        }

    # 5. Normalise result.  SDKs return wildly different shapes; we
    #    serialise whatever we got and return it under a stable key.
    return {"agent_id": agent_id, "output": result}


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        _emit_error("usage", "usage: invoke_existing_agent '<json_args>' [ --bundle-path <path> ]")
        return 2
    method_name = argv[1]
    try:
        args = json.loads(argv[2])
    except json.JSONDecodeError as exc:
        _emit_error("invalid_json", f"invalid JSON args: {exc}")
        return 1
    bundle_path: str | None = None
    if len(argv) >= 5 and argv[3] == "--bundle-path":
        bundle_path = argv[4]
    if method_name != "invoke_existing_agent":
        _emit_error("unknown_method", f"unknown method: {method_name}")
        return 1
    payload = invoke_existing_agent(
        agent_id=str(args.get("agent_id", "")),
        query=str(args.get("query", "")),
        inputs=args.get("inputs"),
        bundle_path=bundle_path,
    )
    _emit(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

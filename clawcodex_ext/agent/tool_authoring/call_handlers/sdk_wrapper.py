"""In-process execution of pos-converter SDK wrapper scripts."""

from __future__ import annotations

import importlib.util
import re
import sys
import threading
from pathlib import Path
from typing import Any

from clawcodex_ext.agent.sdk_context_registry import (
    ContextKey,
    get_sdk_context_registry,
)
from clawcodex_ext.agent.sdk_instance_registry import (
    BucketKey,
    get_sdk_instance_registry,
)
from clawcodex_ext.agent.tool_authoring.persistence import (
    TOOL_DIR,
)
from extensions.sop_converter.sdk_serialization import to_jsonable

_WRAPPER_CALL_RE = re.compile(
    r'(?:python3?|[^\s]*python[^\s]*)\s+"([^"]+)"\s+(\w+)\s+\'\{json_args\}\''
)

_MODULE_CACHE: dict[str, Any] = {}
_MODULE_CACHE_LOCK = threading.Lock()

_SCRIPT_USES_INSTANCE_CACHE: dict[str, bool] = {}


class SdkWrapperCallError(Exception):
    pass


def parse_sdk_wrapper_call_impl(call_impl: str) -> tuple[Path, str] | None:
    """Return ``(script_path, method_name)`` when *call_impl* is a wrapper template."""
    match = _WRAPPER_CALL_RE.search(call_impl.strip())
    if not match:
        return None
    return Path(match.group(1)), match.group(2)


def wrapper_uses_instance_cache(script_path: Path) -> bool:
    """True when the wrapper defines ``_get_instance`` (stateful class methods)."""
    resolved = str(script_path.resolve())
    cached = _SCRIPT_USES_INSTANCE_CACHE.get(resolved)
    if cached is not None:
        return cached
    try:
        text = script_path.read_text(encoding="utf-8")
    except OSError:
        uses = False
    else:
        uses = "def _get_instance(" in text
    _SCRIPT_USES_INSTANCE_CACHE[resolved] = uses
    return uses


def is_allowed_wrapper_script(script_path: Path) -> bool:
    """Only execute wrappers from known agent-tools script directories."""
    try:
        resolved = script_path.resolve()
    except OSError:
        return False

    allowed_roots: list[Path] = [(TOOL_DIR / "scripts").resolve()]
    bundles_root = TOOL_DIR / "bundles"
    if bundles_root.is_dir():
        for child in bundles_root.iterdir():
            scripts = child / "scripts"
            if scripts.is_dir():
                allowed_roots.append(scripts.resolve())

    for parent in resolved.parents:
        if parent.name == "scripts" and parent.parent.name == "agent-tools":
            allowed_roots.append(parent.resolve())
            break

    return any(
        resolved == root or root in resolved.parents for root in allowed_roots
    )


def _load_wrapper_module(script_path: Path) -> Any:
    key = str(script_path.resolve())
    with _MODULE_CACHE_LOCK:
        module = _MODULE_CACHE.get(key)
        if module is not None:
            return module

        spec = importlib.util.spec_from_file_location(
            f"sop_wrapper_{abs(hash(key)) & 0xFFFFFFFF:08x}",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise SdkWrapperCallError(f"Cannot load wrapper module: {script_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _MODULE_CACHE[key] = module
        return module


def should_use_in_process_sdk_wrapper(spec: Any) -> bool:
    """Whether *spec* should run via session-scoped in-process wrapper dispatch."""
    if getattr(spec, "source", None) not in {"sop-converter", "pos-converter"}:
        return False
    parsed = parse_sdk_wrapper_call_impl(str(getattr(spec, "call_impl", "")))
    if parsed is None:
        return False
    script_path, _ = parsed
    if not script_path.is_file():
        return False
    if getattr(spec, "stateful_wrapper", False):
        return True
    # Legacy specs: class wrappers expose _get_instance; standalone wrappers
    # are enabled once the script exists (Plan A phase 2).
    return True


def execute_sdk_wrapper_in_process(
    *,
    script_path: Path,
    method_name: str,
    kwargs: dict[str, Any],
    session_id: str | None,
    agent_id: str | None,
) -> Any:
    if not is_allowed_wrapper_script(script_path):
        raise SdkWrapperCallError(
            f"Wrapper script outside allowed agent-tools directories: {script_path}"
        )

    module = _load_wrapper_module(script_path)
    fn = getattr(module, method_name, None)
    if fn is None or not callable(fn):
        raise SdkWrapperCallError(
            f"Wrapper {script_path.name} has no callable method {method_name!r}"
        )

    context_registry = get_sdk_context_registry()
    context_key: ContextKey = context_registry.context_key(
        session_id=session_id,
        agent_id=agent_id,
    )
    ctx = context_registry.get_context(context_key)
    ctx_lock = context_registry.lock_for(context_key)

    if wrapper_uses_instance_cache(script_path):
        instance_registry = get_sdk_instance_registry()
        bucket_key: BucketKey = instance_registry.bucket_key(
            session_id=session_id,
            agent_id=agent_id,
            script_path=script_path,
        )
        bucket_lock = instance_registry.lock_for(bucket_key)

        def _run_class_method() -> Any:
            module._instances = instance_registry.get_bucket(bucket_key)
            return to_jsonable(fn(**kwargs))

        with bucket_lock:
            with ctx_lock:
                return ctx.run(_run_class_method)

    def _run_standalone() -> Any:
        return to_jsonable(fn(**kwargs))

    with ctx_lock:
        return ctx.run(_run_standalone)

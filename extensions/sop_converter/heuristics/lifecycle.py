"""Lifecycle-kind inference for SOP-converted tools.

F-55 L1 — given a parsed :class:`SourceOperation`, decide whether it is
the *create* end of a lifecycle (e.g. ``build_agent`` / ``create_team_session``),
the *invoke* end (e.g. ``run_agent`` / ``invoke_existing_agent``), or neither.

The result drives two behaviours:

* **create** → the wrapper script's call_impl is augmented with a
  ``--catalog-metadata`` payload so the subprocess records the resulting
  ``agent_id`` into the :mod:`agent_catalog` for later retrieval.
* **invoke** → the wrapper script is left alone (callers will use the
  ``invoke-existing-agent`` macro tool, which itself is a separate composite
  tool that loads the catalog before importing the SDK class).
* **none** → no special treatment; the wrapper script is the default
  ``python3 <script> <method> '{json_args}'`` template.

Heuristics (F-55 §3.2.3 + design doc):

* ``create``  — name starts with ``build_`` / ``create_`` / ``init_`` /
  ``register_`` / ``ensure_``; AND return type contains ``Dict`` /
  ``Mapping`` (the SDK returns a config object the catalog can serialize).
* ``invoke``  — name starts with ``invoke_`` / ``run_`` / ``call_`` / ``send_``;
  AND at least one required parameter ends with ``_id`` / ``id`` (the tool
  consumes a stable identifier from a prior create step).
* otherwise — ``"none"``.

The function is intentionally a pure predicate: callers that need richer
metadata (e.g. the exact parameter name carrying the id) should layer that
on top using :func:`_invoke_id_param`.
"""

from __future__ import annotations

import re
from typing import Literal

from ..source_parser import SourceOperation

LifecycleKind = Literal["create", "invoke", "none"]


_CREATE_PREFIXES = ("build_", "create_", "init_", "register_", "ensure_", "load_")
_INVOKE_PREFIXES = ("invoke_", "run_", "call_", "send_")

# Return-type substrings that signal a "config/dict" return. Matched
# case-insensitively against the unparsed ast type hint.
_DICT_RETURN_HINTS = (
    "dict",
    "mapping",
    "mutabledict",
    "agentconfig",
    "agentbuilder",
    "config",
)

# Parameter-name suffix patterns that signal the tool consumes a stable
# identifier (and is therefore the "invoke" end of a create→invoke chain).
_ID_PARAM_RE = re.compile(r"^(?:[a-z]+_)?id$|^[a-z]+_id$", re.IGNORECASE)


def _looks_like_dict_return(return_type: str | None) -> bool:
    if not return_type:
        return False
    lowered = return_type.lower()
    return any(token in lowered for token in _DICT_RETURN_HINTS)


def _invoke_id_param(op: SourceOperation) -> str | None:
    """Return the parameter name that carries the agent/team/session id, if any."""
    for param in op.parameters:
        if not param.required:
            continue
        if _ID_PARAM_RE.match(param.name):
            return param.name
    return None


def infer_lifecycle_kind(op: SourceOperation) -> LifecycleKind:
    """Classify an op as ``"create"`` / ``"invoke"`` / ``"none"``.

    See module docstring for the heuristics.  Determinism matters: same
    input always yields the same classification so the catalog hook fires
    consistently across ``sop convert`` reruns.
    """
    name = op.name or ""
    if any(name.startswith(p) for p in _CREATE_PREFIXES):
        if _looks_like_dict_return(op.return_type):
            return "create"
    if any(name.startswith(p) for p in _INVOKE_PREFIXES):
        if _invoke_id_param(op) is not None:
            return "invoke"
    return "none"


def lifecycle_metadata_payload(
    op: SourceOperation,
    *,
    source_dir: str,
    bundle_id: str | None = None,
    module_name: str | None = None,
    class_name: str | None = None,
    tool_name: str | None = None,
    extra_metadata: dict | None = None,
) -> dict | None:
    """Build the JSON payload passed to the wrapper via ``--catalog-metadata``.

    Returns ``None`` for non-create ops (callers should not even attach the
    flag in that case).  The payload mirrors :class:`AgentCatalogEntry` minus
    ``agent_id`` and ``created_at``, which the wrapper fills in from the
    SDK's return value at call time.

    The wrapper is responsible for extracting the ``agent_id`` from the
    return value and for inserting it into the ``agent_id`` field of this
    payload before writing the catalog row.  This function therefore emits
    the *static* parts the wrapper cannot infer.
    """
    if infer_lifecycle_kind(op) != "create":
        return None
    metadata: dict = {
        "sdk_source_dir": source_dir,
        "model": "",
        "provider": "",
        "class_name": class_name or op.class_name or "",
        "module_name": module_name or "",
        "query_arg": "query",
        "invoke_method": _guess_invoke_method(op),
        "schema_version": 1,
    }
    if tool_name:
        metadata["source_tool"] = tool_name
    if extra_metadata:
        metadata.update(extra_metadata)
    return metadata


def _guess_invoke_method(op: SourceOperation) -> str:
    """Pick a sensible default ``invoke_method`` for the materialized Agent.

    The wrapper itself is the source of truth at call time — it tries
    ``invoke`` first, then ``run``.  This just supplies a hint for the
    catalog row's ``invoke_method`` field so consumers that don't try both
    have a reasonable starting point.
    """
    name = (op.name or "").lower()
    if name.startswith("run_"):
        return "run"
    return "invoke"


__all__ = [
    "LifecycleKind",
    "infer_lifecycle_kind",
    "lifecycle_metadata_payload",
]

"""Engineering Method Library for Logical Kanban (F-150).

A method is a *reusable decomposition template* that captures a common
engineering pattern ("add a middleware", "fix a bug", "refactor a module").
Each method references one or more :class:`SubtaskTemplate` entries that
the decomposer (F-149) and the Layer-1 rule engine (F-132 / F-150) can use
to validate that a generated :class:`ProposedTask` plan follows the canonical
shape for that pattern.

The library is intentionally domain-agnostic. Method ``subject_template`` and
``description_template`` strings use simple ``{slot}`` placeholders that
downstream code can fill in at render time. No method is bound to a specific
technology stack — see F-150 design note §"已拟定的设计决定".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from .method_seed import build_seed_methods

# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

MethodStatus = Literal["draft", "approved", "deprecated", "experimental"]

_ALLOWED_METHOD_STATUSES: frozenset[str] = frozenset(
    {"draft", "approved", "deprecated", "experimental"}
)

SubtaskRole = Literal["design", "impl", "test", "docs", "review", "deploy"]

_ALLOWED_SUBTASK_ROLES: frozenset[str] = frozenset(
    {"design", "impl", "test", "docs", "review", "deploy"}
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubtaskTemplate:
    """One reusable sub-task slot inside an engineering method."""

    template_id: str
    role: SubtaskRole
    subject_template: str
    description_template: str = ""
    acceptance_template: str = ""
    # ``default_blocked_by`` references other ``template_id`` values within
    # the same method. The method library does NOT enforce ordering at
    # construction time — that is the job of :class:`EngineeringMethod` and
    # the F-150 rule engine (R-METHOD-001).
    default_blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.template_id, str) or not self.template_id.strip():
            raise ValueError("SubtaskTemplate.template_id must be a non-empty string")
        if self.role not in _ALLOWED_SUBTASK_ROLES:
            raise ValueError(
                f"SubtaskTemplate.role must be one of "
                f"{sorted(_ALLOWED_SUBTASK_ROLES)}; got {self.role!r}"
            )
        if not isinstance(self.subject_template, str) or not self.subject_template.strip():
            raise ValueError(
                "SubtaskTemplate.subject_template must be a non-empty string"
            )
        if not isinstance(self.description_template, str):
            raise ValueError("SubtaskTemplate.description_template must be a string")
        if not isinstance(self.acceptance_template, str):
            raise ValueError("SubtaskTemplate.acceptance_template must be a string")
        if not isinstance(self.default_blocked_by, tuple):
            raise ValueError(
                "SubtaskTemplate.default_blocked_by must be a tuple of template_id strings"
            )
        for blocker in self.default_blocked_by:
            if not isinstance(blocker, str) or not blocker.strip():
                raise ValueError(
                    "SubtaskTemplate.default_blocked_by entries must be non-empty strings"
                )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "templateId": self.template_id,
            "role": self.role,
            "subjectTemplate": self.subject_template,
        }
        if self.description_template:
            out["descriptionTemplate"] = self.description_template
        if self.acceptance_template:
            out["acceptanceTemplate"] = self.acceptance_template
        if self.default_blocked_by:
            out["defaultBlockedBy"] = list(self.default_blocked_by)
        return out


@dataclass(frozen=True)
class AcceptanceTemplate:
    """Acceptance criteria template for a method or subtask.

    ``assertion_template`` is a string template with optional ``{slot}``
    placeholders. ``proof_template`` is rendered when an explicit
    acceptance proof is required (i.e. ``strict_acceptance`` is true).
    """

    assertion_template: str
    proof_template: str = ""
    strict_acceptance: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.assertion_template, str) or not self.assertion_template.strip():
            raise ValueError(
                "AcceptanceTemplate.assertion_template must be a non-empty string"
            )
        if not isinstance(self.proof_template, str):
            raise ValueError("AcceptanceTemplate.proof_template must be a string")
        if not isinstance(self.strict_acceptance, bool):
            raise ValueError("AcceptanceTemplate.strict_acceptance must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertionTemplate": self.assertion_template,
            "proofTemplate": self.proof_template,
            "strictAcceptance": self.strict_acceptance,
        }


@dataclass(frozen=True)
class EngineeringMethod:
    """Reusable engineering pattern: a decomposition template + metadata.

    ``pattern`` is a stable string identifier used to look up methods via
    ``list_methods(pattern_prefix=...)``.  Examples:
    ``"add_api_endpoint"``, ``"fix_performance"``, ``"refactor_module"``.

    ``preconditions`` and ``assumptions`` are free-form strings. The F-150
    rule engine (R-METHOD-002) checks that, if any precondition is listed,
    at least one matching assumption or environment context is also
    present. See method_library.register_method() for the reference check
    logic.
    """

    method_id: str
    pattern: str
    description: str
    subtask_templates: tuple[SubtaskTemplate, ...]
    preconditions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    acceptance_template: AcceptanceTemplate | None = None
    version: str = "1"
    status: MethodStatus = "approved"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.method_id, str) or not self.method_id.strip():
            raise ValueError("EngineeringMethod.method_id must be a non-empty string")
        if not isinstance(self.pattern, str) or not self.pattern.strip():
            raise ValueError("EngineeringMethod.pattern must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("EngineeringMethod.description must be a string")
        if not isinstance(self.subtask_templates, tuple):
            raise ValueError("EngineeringMethod.subtask_templates must be a tuple")
        if not self.subtask_templates:
            raise ValueError(
                "EngineeringMethod.subtask_templates must contain at least one entry"
            )
        if not isinstance(self.preconditions, tuple):
            raise ValueError("EngineeringMethod.preconditions must be a tuple of strings")
        if not isinstance(self.assumptions, tuple):
            raise ValueError("EngineeringMethod.assumptions must be a tuple of strings")
        if self.acceptance_template is not None and not isinstance(
            self.acceptance_template, AcceptanceTemplate
        ):
            raise ValueError(
                "EngineeringMethod.acceptance_template must be an AcceptanceTemplate or None"
            )
        if self.status not in _ALLOWED_METHOD_STATUSES:
            raise ValueError(
                f"EngineeringMethod.status must be one of "
                f"{sorted(_ALLOWED_METHOD_STATUSES)}; got {self.status!r}"
            )
        if not isinstance(self.tags, tuple):
            raise ValueError("EngineeringMethod.tags must be a tuple of strings")
        for tag in self.tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("EngineeringMethod.tags entries must be non-empty strings")

    # --- Convenience accessors ---------------------------------------------

    def subtask_by_template_id(self, template_id: str) -> SubtaskTemplate | None:
        for template in self.subtask_templates:
            if template.template_id == template_id:
                return template
        return None

    def roles(self) -> tuple[str, ...]:
        """Return the (ordered, unique) list of roles covered by this method."""
        seen: list[str] = []
        for template in self.subtask_templates:
            if template.role not in seen:
                seen.append(template.role)
        return tuple(seen)

    # --- (De)serialization --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "methodId": self.method_id,
            "pattern": self.pattern,
            "description": self.description,
            "subtaskTemplates": [t.to_dict() for t in self.subtask_templates],
            "preconditions": list(self.preconditions),
            "assumptions": list(self.assumptions),
            "version": self.version,
            "status": self.status,
            "tags": list(self.tags),
        }
        if self.acceptance_template is not None:
            out["acceptanceTemplate"] = self.acceptance_template.to_dict()
        return out


# ---------------------------------------------------------------------------
# Registry — mutable module-level state
# ---------------------------------------------------------------------------


_SLOT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

#: Immutable seed library.  Loaded into the in-memory registry at import time.
#: We delegate construction to :mod:`method_seed` to keep that file free of
#: the circular import — see ``method_seed.build_seed_methods``.
METHOD_LIBRARY: tuple[EngineeringMethod, ...] = build_seed_methods(
    EngineeringMethod, SubtaskTemplate, AcceptanceTemplate
)

#: Mutable registry — extended by :func:`register_method`.  Always contains
#: the seed library as a baseline; new registrations are appended.
_METHOD_REGISTRY: list[EngineeringMethod] = list(METHOD_LIBRARY)


def _validate_method_internals(method: EngineeringMethod) -> None:
    """Reject methods whose internal references do not resolve.

    * ``subtask_templates[*].default_blocked_by`` must point to existing
      ``template_id`` values inside the same method.
    * ``method_id`` must be unique within the registry.
    * The method's ``acceptance_template`` (if any) must be internally
      well-formed — that is enforced by ``AcceptanceTemplate.__post_init__``.
    """
    template_ids = {t.template_id for t in method.subtask_templates}
    for template in method.subtask_templates:
        unknown = set(template.default_blocked_by) - template_ids
        if unknown:
            raise ValueError(
                f"EngineeringMethod {method.method_id!r}: subtask "
                f"{template.template_id!r} default_blocked_by references "
                f"unknown template_id(s): {sorted(unknown)}"
            )
    # Slot sanity — make sure each {slot} in templates uses a valid Python
    # identifier.  This is a soft check; downstream rendering is what
    # actually substitutes the slot.
    for template in method.subtask_templates:
        for text in (template.subject_template, template.description_template,
                     template.acceptance_template):
            for match in _SLOT_PATTERN.finditer(text):
                pass  # Identifier check is implicit in the regex itself.
    if method.acceptance_template is not None:
        _SLOT_PATTERN.findall(method.acceptance_template.assertion_template)


def register_method(method: EngineeringMethod) -> None:
    """Register ``method`` in the in-memory method library.

    * The method must validate (see :func:`_validate_method_internals`).
    * ``method.method_id`` must be unique in the registry.

    Raises ``ValueError`` on either failure. The seed library is immutable
    in spirit — re-registering a seed ``method_id`` is rejected so that
    callers cannot silently override the canonical entries shipped with the
    package.  Use :func:`list_methods` + custom dispatch if you need to
    ship your own variants of a seed method.
    """
    if not isinstance(method, EngineeringMethod):
        raise ValueError("register_method expects an EngineeringMethod")
    _validate_method_internals(method)

    existing_ids = {m.method_id for m in _METHOD_REGISTRY}
    if method.method_id in existing_ids:
        raise ValueError(
            f"method_id {method.method_id!r} already registered; pick a unique id"
        )
    _METHOD_REGISTRY.append(method)


def get_method(method_id: str) -> EngineeringMethod | None:
    """Return the method with the given ``method_id``, or ``None``."""
    for method in _METHOD_REGISTRY:
        if method.method_id == method_id:
            return method
    return None


def list_methods(
    *,
    status: str | None = "approved",
    pattern_prefix: str | None = None,
    tag: str | None = None,
) -> tuple[EngineeringMethod, ...]:
    """Return a filtered, deterministically ordered list of methods.

    Parameters
    ----------
    status:
        If given, only methods whose ``status`` matches are returned.  Pass
        ``None`` to disable status filtering (e.g. for introspection).
    pattern_prefix:
        If given, only methods whose ``pattern`` starts with this prefix
        are returned.  Case-sensitive.
    tag:
        If given, only methods containing this tag are returned.
    """
    out: list[EngineeringMethod] = []
    for method in _METHOD_REGISTRY:
        if status is not None and method.status != status:
            continue
        if pattern_prefix is not None and not method.pattern.startswith(pattern_prefix):
            continue
        if tag is not None and tag not in method.tags:
            continue
        out.append(method)
    out.sort(key=lambda m: (m.pattern, m.method_id))
    return tuple(out)


def get_all_methods() -> tuple[EngineeringMethod, ...]:
    """Return the full registry (seed library + registered methods).

    This is the lookup pool used by :func:`validate_method_compliance`
    when no explicit ``method_library`` is supplied.  Unlike
    :data:`METHOD_LIBRARY` (which is the immutable seed library), this
    tuple reflects the latest set of methods including anything added via
    :func:`register_method`.
    """
    return tuple(_METHOD_REGISTRY)


def reset_method_registry(include_seeds: bool = True) -> None:
    """Reset the registry back to the seed library (test-only helper).

    ``include_seeds=True`` (default) restores the canonical seed library.
    ``include_seeds=False`` empties the registry entirely.

    Production code should never need to call this — it exists so unit
    tests can isolate themselves from previous :func:`register_method`
    calls.
    """
    if include_seeds:
        _METHOD_REGISTRY.clear()
        _METHOD_REGISTRY.extend(METHOD_LIBRARY)
    else:
        _METHOD_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def save_method_library(
    methods: Iterable[EngineeringMethod],
    path: Path,
) -> None:
    """Serialize ``methods`` to ``path`` as a single JSON document.

    The document is shaped as::

        {
          "schemaVersion": "1",
          "methods": [ <method.to_dict()>, ... ]
        }

    Existing files at ``path`` are overwritten.  Parents are created on
    demand.
    """
    payload = {
        "schemaVersion": "1",
        "methods": [m.to_dict() for m in methods],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_method_library(path: Path) -> tuple[EngineeringMethod, ...]:
    """Load methods from a JSON document previously written by :func:`save_method_library`.

    Missing optional fields fall back to the dataclass defaults so the
    loader is forward-compatible with new fields added by later versions
    of this module.  Unknown top-level fields are silently ignored.  An
    unknown ``subtask.role`` or invalid ``status`` still raises, since
    those are programmer errors rather than schema drift.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("method library file must contain a JSON object")
    raw_methods = data.get("methods")
    if not isinstance(raw_methods, list):
        raise ValueError("method library file must contain a 'methods' array")

    out: list[EngineeringMethod] = []
    for index, raw in enumerate(raw_methods):
        if not isinstance(raw, dict):
            raise ValueError(f"methods[{index}] must be a JSON object")
        out.append(_deserialize_method(raw))
    return tuple(out)


def _deserialize_method(raw: dict[str, Any]) -> EngineeringMethod:
    method_id = raw.get("methodId")
    pattern = raw.get("pattern")
    if not isinstance(method_id, str) or not method_id:
        raise ValueError("method.methodId must be a non-empty string")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("method.pattern must be a non-empty string")
    description = raw.get("description", "") or ""
    if not isinstance(description, str):
        raise ValueError("method.description must be a string")

    raw_templates = raw.get("subtaskTemplates") or raw.get("subtask_templates")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates must be a non-empty list"
        )

    templates: list[SubtaskTemplate] = []
    for t_index, t_raw in enumerate(raw_templates):
        if not isinstance(t_raw, dict):
            raise ValueError(f"method {method_id!r}: subtaskTemplates[{t_index}] must be a dict")
        templates.append(_deserialize_subtask_template(method_id, t_index, t_raw))

    preconditions = _tuple_of_strings(raw.get("preconditions"), "preconditions", method_id)
    assumptions = _tuple_of_strings(raw.get("assumptions"), "assumptions", method_id)
    tags = _tuple_of_strings(raw.get("tags", []), "tags", method_id, allow_empty=True)
    version = raw.get("version", "1")
    if not isinstance(version, str):
        raise ValueError(f"method {method_id!r}: version must be a string")
    status = raw.get("status", "approved")
    if status not in _ALLOWED_METHOD_STATUSES:
        raise ValueError(
            f"method {method_id!r}: status {status!r} not in "
            f"{sorted(_ALLOWED_METHOD_STATUSES)}"
        )

    raw_acceptance = raw.get("acceptanceTemplate") or raw.get("acceptance_template")
    acceptance: AcceptanceTemplate | None = None
    if raw_acceptance is not None:
        if not isinstance(raw_acceptance, dict):
            raise ValueError(
                f"method {method_id!r}: acceptanceTemplate must be a dict or null"
            )
        acceptance = _deserialize_acceptance_template(method_id, raw_acceptance)

    return EngineeringMethod(
        method_id=method_id,
        pattern=pattern,
        description=description,
        subtask_templates=tuple(templates),
        preconditions=preconditions,
        assumptions=assumptions,
        acceptance_template=acceptance,
        version=version,
        status=status,  # type: ignore[arg-type]
        tags=tags,
    )


def _deserialize_subtask_template(
    method_id: str, index: int, raw: dict[str, Any]
) -> SubtaskTemplate:
    template_id = raw.get("templateId") or raw.get("template_id")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].templateId must be a non-empty string"
        )
    role = raw.get("role")
    if role not in _ALLOWED_SUBTASK_ROLES:
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].role must be one of "
            f"{sorted(_ALLOWED_SUBTASK_ROLES)}; got {role!r}"
        )
    subject_template = raw.get("subjectTemplate") or raw.get("subject_template")
    if not isinstance(subject_template, str) or not subject_template:
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].subjectTemplate must be a non-empty string"
        )
    description_template = raw.get("descriptionTemplate") or raw.get("description_template") or ""
    if not isinstance(description_template, str):
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].descriptionTemplate must be a string"
        )
    acceptance_template = raw.get("acceptanceTemplate") or raw.get("acceptance_template") or ""
    if not isinstance(acceptance_template, str):
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].acceptanceTemplate must be a string"
        )
    default_blocked_by_raw = (
        raw.get("defaultBlockedBy") or raw.get("default_blocked_by") or []
    )
    if not isinstance(default_blocked_by_raw, list):
        raise ValueError(
            f"method {method_id!r}: subtaskTemplates[{index}].defaultBlockedBy must be a list"
        )
    default_blocked_by = tuple(
        str(item) for item in default_blocked_by_raw if isinstance(item, str) and item
    )
    return SubtaskTemplate(
        template_id=template_id,
        role=role,  # type: ignore[arg-type]
        subject_template=subject_template,
        description_template=description_template,
        acceptance_template=acceptance_template,
        default_blocked_by=default_blocked_by,
    )


def _deserialize_acceptance_template(
    method_id: str, raw: dict[str, Any]
) -> AcceptanceTemplate:
    assertion_template = raw.get("assertionTemplate") or raw.get("assertion_template")
    if not isinstance(assertion_template, str) or not assertion_template:
        raise ValueError(
            f"method {method_id!r}: acceptanceTemplate.assertionTemplate must be a non-empty string"
        )
    proof_template = raw.get("proofTemplate") or raw.get("proof_template") or ""
    if not isinstance(proof_template, str):
        raise ValueError(
            f"method {method_id!r}: acceptanceTemplate.proofTemplate must be a string"
        )
    strict_acceptance = raw.get("strictAcceptance", raw.get("strict_acceptance", False))
    if not isinstance(strict_acceptance, bool):
        raise ValueError(
            f"method {method_id!r}: acceptanceTemplate.strictAcceptance must be a boolean"
        )
    return AcceptanceTemplate(
        assertion_template=assertion_template,
        proof_template=proof_template,
        strict_acceptance=strict_acceptance,
    )


def _tuple_of_strings(
    value: Any, field_name: str, method_id: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"method {method_id!r}: {field_name} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"method {method_id!r}: {field_name} entries must be strings"
            )
        if not item and not allow_empty:
            raise ValueError(
                f"method {method_id!r}: {field_name} entries must be non-empty"
            )
        if item:
            out.append(item)
    return tuple(out)


__all__ = [
    "AcceptanceTemplate",
    "EngineeringMethod",
    "METHOD_LIBRARY",
    "MethodStatus",
    "SubtaskRole",
    "SubtaskTemplate",
    "get_all_methods",
    "get_method",
    "list_methods",
    "load_method_library",
    "register_method",
    "reset_method_registry",
    "save_method_library",
]
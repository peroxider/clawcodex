"""F-46.0: translate legacy ``permission_mode`` enum into the three orthogonal
fields (``interactive`` / ``default_decision`` / ``audit_log``).

The legacy ``permission_mode`` enum (`default` / `plan` /
`bypassPermissions` / `acceptEdits` / `dontAsk`) collapses three orthogonal
runtime concerns into a single string:

* Whether the runtime needs a TTY prompt (``interactive``)
* What to do when no policy rule matches (``default_decision``)
* How verbose per-tool decision logging should be (``audit_log``)

This module is the single source of truth for collapsing any of the four
shapes that may appear in a user-authored ``workflow.yaml`` into the
canonical three-field tuple:

1. The legacy ``permission_mode`` string only → 3-field tuple via a
   fixed mapping table (see :data:`LEGACY_MODE_TABLE`).
2. The three new fields explicit → use them as-is (no translation needed).
3. Mix of legacy + new fields → new fields win, legacy used to fill in any
   ``None`` slot (see :func:`resolve_orthogonal_fields`).
4. All ``None`` → fall back to ``permission_mode`` defaults (``interactive=True``,
   ``default_decision="ask"``, ``audit_log="minimal"``).

The module is intentionally side-effect-free so it can be unit-tested
without touching disk or network. The orchestration layer (AgentRunner /
ApprovalPolicy) imports :func:`resolve_orthogonal_fields` and reads the
three return values directly.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

AuditLogLevel = Literal["none", "minimal", "full"]
DefaultDecision = Literal["allow", "deny", "ask"]

# Allowed values, exported for schema validation.
AUDIT_LOG_VALUES: tuple[AuditLogLevel, ...] = ("none", "minimal", "full")
DEFAULT_DECISION_VALUES: tuple[DefaultDecision, ...] = ("allow", "deny", "ask")


@dataclass(frozen=True)
class OrthogonalPermission:
    """The canonical, post-F-46.0 representation of a workflow's permission
    posture. ``interactive`` / ``default_decision`` / ``audit_log`` are the
    three dimensions; legacy ``permission_mode`` strings are accepted as
    input but never emitted.
    """

    interactive: bool
    default_decision: DefaultDecision
    audit_log: AuditLogLevel

    def as_dict(self) -> dict[str, object]:
        """Render as a plain dict, suitable for logging / JSON serialisation."""
        return {
            "interactive": self.interactive,
            "default_decision": self.default_decision,
            "audit_log": self.audit_log,
        }


# ---------------------------------------------------------------------------
# Translation table
# ---------------------------------------------------------------------------

# Map every canonical legacy mode to its three orthogonal components. New
# modes added upstream (TS) should grow this table, not bypass it. Mode
# strings are normalised by ``_normalise_legacy_mode`` before lookup.
LEGACY_MODE_TABLE: dict[str, OrthogonalPermission] = {
    # default — nothing special, prompt the user, log denials only.
    "default": OrthogonalPermission(
        interactive=True,
        default_decision="ask",
        audit_log="minimal",
    ),
    # plan — interactive and read-only-by-default; deny writes.
    "plan": OrthogonalPermission(
        interactive=True,
        default_decision="deny",
        audit_log="minimal",
    ),
    # bypassPermissions — unattended; everything allowed; full audit.
    "bypasspermissions": OrthogonalPermission(
        interactive=False,
        default_decision="allow",
        audit_log="full",
    ),
    # acceptEdits — unattended for edits; ask for everything else; log edits.
    "acceptedits": OrthogonalPermission(
        interactive=False,
        default_decision="ask",
        audit_log="minimal",
    ),
    # dontAsk — explicit auto-decision; never prompt; log only denials.
    "dontask": OrthogonalPermission(
        interactive=False,
        default_decision="allow",
        audit_log="minimal",
    ),
}


def _normalise_legacy_mode(raw: str | None) -> str | None:
    """Canonicalise the legacy ``permission_mode`` string for table lookup.

    We accept mixed-case, surrounding whitespace, and snake_case aliases
    (``accept_edits`` ↔ ``acceptEdits``) since YAML authors frequently
    re-case enums depending on style. Unknown modes pass through unchanged
    so :func:`_resolve_from_legacy_mode` can raise a clear error.
    """
    if raw is None:
        return None
    cleaned = str(raw).strip().lower().replace("_", "")
    return cleaned or None


def _resolve_from_legacy_mode(
    permission_mode: str | None,
) -> OrthogonalPermission:
    """Collapse a legacy ``permission_mode`` string into three fields.

    Raises ``ValueError`` on unknown modes so the loader can surface a
    user-friendly error rather than silently falling back to ``default``.
    """
    canonical = _normalise_legacy_mode(permission_mode)
    if canonical is None:
        return OrthogonalPermission(
            interactive=True,
            default_decision="ask",
            audit_log="minimal",
        )
    if canonical not in LEGACY_MODE_TABLE:
        allowed = sorted({m for m in LEGACY_MODE_TABLE if m.isalpha()})
        raise ValueError(
            f"Unknown permission_mode: {permission_mode!r}. "
            f"Expected one of: {', '.join(sorted(allowed))}."
        )
    return LEGACY_MODE_TABLE[canonical]


def _coerce_audit_log(value: object) -> AuditLogLevel:
    """Validate an explicitly-supplied ``audit_log`` value.

    The schema layer accepts ``str | None``; this function narrows and
    validates before assignment to the frozen dataclass. Normalises
    surrounding whitespace and case before validating.
    """
    if value is None:
        raise ValueError("audit_log must not be None when explicitly provided")
    cleaned = str(value).strip().lower()
    if cleaned not in AUDIT_LOG_VALUES:
        raise ValueError(
            f"Invalid audit_log: {value!r}. "
            f"Expected one of: {', '.join(AUDIT_LOG_VALUES)}."
        )
    return cleaned  # type: ignore[return-value]


def _coerce_default_decision(value: object) -> DefaultDecision:
    """Validate an explicitly-supplied ``default_decision`` value.

    Normalises surrounding whitespace and case before validating.
    """
    if value is None:
        raise ValueError(
            "default_decision must not be None when explicitly provided"
        )
    cleaned = str(value).strip().lower()
    if cleaned not in DEFAULT_DECISION_VALUES:
        raise ValueError(
            f"Invalid default_decision: {value!r}. "
            f"Expected one of: {', '.join(DEFAULT_DECISION_VALUES)}."
        )
    return cleaned  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def translate_legacy_permission_mode(permission_mode: str | None) -> OrthogonalPermission:
    """Collapse a legacy ``permission_mode`` string into the three orthogonal
    fields. Pure function; never raises on a known mode.

    Use this when you only have the legacy enum in hand (e.g. backfilling
    an old registry entry). For new workflows prefer
    :func:`resolve_orthogonal_fields` which honours explicit new-field
    overrides.
    """
    return _resolve_from_legacy_mode(permission_mode)


def resolve_orthogonal_fields(
    *,
    permission_mode: str | None,
    interactive: bool | None = None,
    default_decision: str | None = None,
    audit_log: str | None = None,
) -> OrthogonalPermission:
    """Resolve the canonical three-field tuple from any combination of legacy
    and new inputs.

    Resolution rule: explicit new fields always win over the legacy enum.
    ``None`` new fields fall back to the legacy enum's mapping; if the legacy
    enum is also ``None``, the safe defaults
    (``interactive=True``, ``default_decision="ask"``, ``audit_log="minimal"``)
    apply.

    This is the function the orchestrator / AgentRunner should call when
    loading a workflow. The returned dataclass is the single source of
    truth at runtime; the legacy ``permission_mode`` string should be
    considered deprecated after F-46.0 and removed in F-46.2.
    """
    base = _resolve_from_legacy_mode(permission_mode)

    resolved_interactive = interactive if interactive is not None else base.interactive
    resolved_default = (
        _coerce_default_decision(default_decision)
        if default_decision is not None
        else base.default_decision
    )
    resolved_audit = (
        _coerce_audit_log(audit_log) if audit_log is not None else base.audit_log
    )

    return OrthogonalPermission(
        interactive=bool(resolved_interactive),
        default_decision=resolved_default,
        audit_log=resolved_audit,
    )


def is_legacy_permission_mode(value: object) -> bool:
    """Quick predicate: is ``value`` a known legacy ``permission_mode`` enum?

    Useful for the schema deprecation warning layer (F-46.2). Returns False
    for ``None`` and for the new orthogonal fields.
    """
    if value is None or not isinstance(value, str):
        return False
    return _normalise_legacy_mode(value) in LEGACY_MODE_TABLE


# ---------------------------------------------------------------------------
# F-46.2: deprecation warning for legacy permission_mode
# ---------------------------------------------------------------------------

_DEPRECATION_WARNING_SHOWN: set[str] = set()


def warn_deprecated_permission_mode(permission_mode: str | None) -> None:
    """Emit a single ``DeprecationWarning`` when a legacy ``permission_mode``
    value is encountered.

    The warning is deduplicated per-value so that repeated workflow parses
    (e.g. during CI) only produce one line per distinct mode.  Safe to call
    with ``None`` or unknown values — they produce no warning.
    """
    if permission_mode is None:
        return
    if is_legacy_permission_mode(permission_mode):
        key = permission_mode
        if key not in _DEPRECATION_WARNING_SHOWN:
            _DEPRECATION_WARNING_SHOWN.add(key)
            warnings.warn(
                f"permission_mode={permission_mode!r} is deprecated since F-46.2. "
                f"Use the orthogonal fields ``interactive``, ``default_decision``, "
                f"and ``audit_log`` on ``agent`` instead. "
                f"This warning is emitted once per distinct legacy value.",
                DeprecationWarning,
                stacklevel=3,
            )

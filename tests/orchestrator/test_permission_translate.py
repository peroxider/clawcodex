"""F-46.0 unit tests for ``extensions.orchestrator.permission_translate``.

Covers:
* Legacy enum → orthogonal translation (all 5 canonical modes).
* New explicit fields win over legacy.
* Mixed legacy + partial new → new wins per-slot, legacy fills gaps.
* All ``None`` → safe defaults.
* Case-insensitive legacy lookup, whitespace tolerance.
* Invalid values raise ``ValueError`` with helpful messages.
* ``is_legacy_permission_mode`` predicate covers known modes, unknowns,
  and non-str inputs.
"""

from __future__ import annotations

import pytest

from extensions.orchestrator.permission_translate import (
    AUDIT_LOG_VALUES,
    DEFAULT_DECISION_VALUES,
    LEGACY_MODE_TABLE,
    OrthogonalPermission,
    is_legacy_permission_mode,
    resolve_orthogonal_fields,
    translate_legacy_permission_mode,
)


# ---------------------------------------------------------------------------
# Legacy enum translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "legacy, expected",
    [
        (
            "default",
            OrthogonalPermission(interactive=True, default_decision="ask", audit_log="minimal"),
        ),
        (
            "plan",
            OrthogonalPermission(interactive=True, default_decision="deny", audit_log="minimal"),
        ),
        (
            "bypassPermissions",
            OrthogonalPermission(interactive=False, default_decision="allow", audit_log="full"),
        ),
        (
            "acceptEdits",
            OrthogonalPermission(interactive=False, default_decision="ask", audit_log="minimal"),
        ),
        (
            "dontAsk",
            OrthogonalPermission(interactive=False, default_decision="allow", audit_log="minimal"),
        ),
    ],
)
def test_translate_legacy_permission_mode_canonical(legacy: str, expected: OrthogonalPermission) -> None:
    assert translate_legacy_permission_mode(legacy) == expected


@pytest.mark.parametrize(
    "legacy, expected_mode",
    [
        ("  default  ", "default"),
        ("BYPASSPERMISSIONS", "bypassPermissions"),
        ("DontAsk", "dontAsk"),
        ("accept_edits", "acceptEdits"),
        ("\tplan\n", "plan"),
    ],
)
def test_translate_legacy_permission_mode_normalises_whitespace_and_case(
    legacy: str, expected_mode: str
) -> None:
    result = translate_legacy_permission_mode(legacy)
    assert result == LEGACY_MODE_TABLE[expected_mode.lower()]


def test_translate_legacy_permission_mode_none_returns_safe_defaults() -> None:
    assert translate_legacy_permission_mode(None) == OrthogonalPermission(
        interactive=True, default_decision="ask", audit_log="minimal"
    )


def test_translate_legacy_permission_mode_empty_string_returns_safe_defaults() -> None:
    assert translate_legacy_permission_mode("") == OrthogonalPermission(
        interactive=True, default_decision="ask", audit_log="minimal"
    )


def test_translate_legacy_permission_mode_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown permission_mode"):
        translate_legacy_permission_mode("semi-trusted")


# ---------------------------------------------------------------------------
# resolve_orthogonal_fields — new fields take precedence
# ---------------------------------------------------------------------------


def test_explicit_new_fields_override_legacy_completely() -> None:
    """When all three new fields are explicit, legacy is ignored entirely."""
    result = resolve_orthogonal_fields(
        permission_mode="bypassPermissions",
        interactive=True,
        default_decision="deny",
        audit_log="none",
    )
    assert result == OrthogonalPermission(
        interactive=True, default_decision="deny", audit_log="none"
    )


def test_partial_new_fields_fill_remainder_from_legacy() -> None:
    """One explicit field; the rest falls back to the legacy enum mapping."""
    # `audit_log=full` explicit; legacy "default" would otherwise give "minimal".
    result = resolve_orthogonal_fields(
        permission_mode="default",
        audit_log="full",
    )
    assert result == OrthogonalPermission(
        interactive=True,  # from default
        default_decision="ask",  # from default
        audit_log="full",  # explicit
    )


def test_per_slot_override_works() -> None:
    """Each slot is resolved independently."""
    result = resolve_orthogonal_fields(
        permission_mode="plan",
        interactive=False,  # override
        # default_decision falls through to plan -> "deny"
        audit_log="full",  # override
    )
    assert result == OrthogonalPermission(
        interactive=False,
        default_decision="deny",
        audit_log="full",
    )


def test_all_none_falls_back_to_safe_defaults() -> None:
    result = resolve_orthogonal_fields(
        permission_mode=None,
        interactive=None,
        default_decision=None,
        audit_log=None,
    )
    assert result == OrthogonalPermission(
        interactive=True, default_decision="ask", audit_log="minimal"
    )


# ---------------------------------------------------------------------------
# Validation of explicit new fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["yes", "minimalx", 1, True, ["full"]])
def test_invalid_audit_log_raises(bad_value: object) -> None:
    with pytest.raises(ValueError, match="Invalid audit_log"):
        resolve_orthogonal_fields(
            permission_mode=None,
            audit_log=bad_value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad_value", ["reject", 0, False, ["allow"]])
def test_invalid_default_decision_raises(bad_value: object) -> None:
    with pytest.raises(ValueError, match="Invalid default_decision"):
        resolve_orthogonal_fields(
            permission_mode=None,
            default_decision=bad_value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "normalised_input, expected",
    [
        ("  full  ", "full"),
        ("MINIMAL", "minimal"),
        ("none", "none"),
    ],
)
def test_audit_log_strips_and_lowercases(normalised_input: str, expected: str) -> None:
    """Whitespace + case are tolerated before validation."""
    result = resolve_orthogonal_fields(
        permission_mode=None, audit_log=normalised_input
    )
    assert result.audit_log == expected


@pytest.mark.parametrize(
    "normalised_input, expected",
    [
        ("  ALLOW  ", "allow"),
        ("Deny", "deny"),
        ("ask", "ask"),
    ],
)
def test_default_decision_strips_and_lowercases(
    normalised_input: str, expected: str
) -> None:
    result = resolve_orthogonal_fields(
        permission_mode=None, default_decision=normalised_input
    )
    assert result.default_decision == expected


def test_explicit_none_field_raises() -> None:
    """A non-None explicit field that fails coercion should raise, but a
    literal ``None`` slot should fall back to the legacy mapping."""
    with pytest.raises(ValueError, match="audit_log must not be None"):
        # This exercises the inner guard; in practice the public API uses
        # ``None`` to mean "fall back". The guard is defensive against
        # explicit ``None`` injection from internal callers.
        from extensions.orchestrator.permission_translate import _coerce_audit_log

        _coerce_audit_log(None)


# ---------------------------------------------------------------------------
# Allowed value exports
# ---------------------------------------------------------------------------


def test_audit_log_values_complete() -> None:
    assert set(AUDIT_LOG_VALUES) == {"none", "minimal", "full"}


def test_default_decision_values_complete() -> None:
    assert set(DEFAULT_DECISION_VALUES) == {"allow", "deny", "ask"}


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("default", True),
        ("BYPASSPERMISSIONS", True),
        ("DontAsk", True),
        ("acceptEdits", True),
        ("plan", True),
        ("  default  ", True),
        (None, False),
        ("", False),
        ("unknown-mode", False),
        (123, False),
        (["default"], False),
        ({"mode": "default"}, False),
    ],
)
def test_is_legacy_permission_mode(value: object, expected: bool) -> None:
    assert is_legacy_permission_mode(value) is expected


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


def test_orthogonal_permission_is_frozen() -> None:
    perm = OrthogonalPermission(interactive=False, default_decision="allow", audit_log="full")
    with pytest.raises(Exception):
        perm.interactive = True  # type: ignore[misc]


def test_orthogonal_permission_as_dict_roundtrip() -> None:
    perm = OrthogonalPermission(interactive=True, default_decision="deny", audit_log="minimal")
    assert perm.as_dict() == {
        "interactive": True,
        "default_decision": "deny",
        "audit_log": "minimal",
    }
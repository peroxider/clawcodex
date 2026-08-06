"""CCB-compatible ``CLAUDE_CODE_DISABLE_CRON`` env var fallback.

Pins the contract from
``docs/feature_plan/05-cron-system/f-22-cron-execution.md`` §Phase I:

- ``CLAWCODEX_DISABLE_CRON`` takes priority over the legacy CCB variable.
- ``CLAUDE_CODE_DISABLE_CRON`` is consulted as a fallback when the primary
  variable is unset, so users migrating from CCB do not need to edit their
  environment.
- Falsy values (``0``, ``false``, ``no``, ``off``, empty string, whitespace)
  must not disable cron — same semantics as the legacy implementation.
"""

from __future__ import annotations

import pytest

from clawcodex_ext.cron_system.models import (
    ENV_CLAUDE_CODE_DISABLE_CRON,
    ENV_CLAWCODEX_DISABLE_CRON,
    is_cron_disabled,
)


@pytest.mark.parametrize(
    "raw",
    ["1", "true", "TRUE", "True", "yes", "YES", "on", "On", " 1 ", " true"],
)
def test_primary_env_truthy_disables(raw: str) -> None:
    """Truthy values for ``CLAWCODEX_DISABLE_CRON`` disable cron."""
    env = {ENV_CLAWCODEX_DISABLE_CRON: raw}
    assert is_cron_disabled(env) is True


def test_primary_env_overrides_legacy_truthy() -> None:
    """Priority semantics: ``CLAWCODEX_DISABLE_CRON=false`` wins over CCB ``true``.

    The CCB variable is ignored whenever the native variable is set, even to
    a falsy value.
    """
    env = {
        ENV_CLAWCODEX_DISABLE_CRON: "false",
        ENV_CLAUDE_CODE_DISABLE_CRON: "true",
    }
    assert is_cron_disabled(env) is False


def test_legacy_env_disables_when_primary_missing() -> None:
    """CCB migration: legacy variable alone disables cron."""
    env = {ENV_CLAUDE_CODE_DISABLE_CRON: "true"}
    assert is_cron_disabled(env) is True


def test_legacy_env_truthy_variants() -> None:
    """All truthy string spellings are honoured on the CCB fallback."""
    for raw in ("1", "true", "yes", "on", "TRUE", " 1 "):
        assert is_cron_disabled({ENV_CLAUDE_CODE_DISABLE_CRON: raw}) is True, raw


def test_unset_returns_false() -> None:
    """No env vars at all → cron enabled."""
    assert is_cron_disabled({}) is False


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off", "", "   "])
def test_falsy_values_do_not_disable(raw: str) -> None:
    """Falsy values (including legacy variable) never disable cron."""
    env = {ENV_CLAUDE_CODE_DISABLE_CRON: raw}
    assert is_cron_disabled(env) is False


def test_priority_when_primary_empty_string() -> None:
    """Empty string for the primary variable must fall through to CCB.

    ``os.environ.get`` returns the empty string when set-but-empty, which
    is intentionally not the same as "unset" — but for cron disable
    semantics, an empty value should not disable cron. Both empty primary
    and truthy legacy are still falsy for cron (legacy truthy must NOT
    override the explicit empty primary).
    """
    # Priority semantics from spec: primary wins. Empty primary keeps cron
    # enabled even when CCB says disable.
    env = {
        ENV_CLAWCODEX_DISABLE_CRON: "",
        ENV_CLAUDE_CODE_DISABLE_CRON: "true",
    }
    assert is_cron_disabled(env) is False


def test_env_constants_defined() -> None:
    """Public env var constants are exported for downstream call sites."""
    assert ENV_CLAWCODEX_DISABLE_CRON == "CLAWCODEX_DISABLE_CRON"
    assert ENV_CLAUDE_CODE_DISABLE_CRON == "CLAUDE_CODE_DISABLE_CRON"
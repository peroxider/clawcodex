from __future__ import annotations

import pytest

from clawcodex_ext.cli.model_cmd.commands import format_model_current, run_model_command, use_model
from clawcodex_ext.cli.model_cmd.errors import UnknownModelError
from clawcodex_ext.cli.provider_cmd.commands import format_provider_current, run_provider_command


def test_provider_current_formats_resolution(monkeypatch) -> None:
    """``current`` output is a clean ``provider: …\nmodel: …`` with no source labels."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "glm")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "zai/glm-4"},
    )

    assert format_provider_current().splitlines() == [
        "provider: glm",
        "model: zai/glm-4",
    ]
    assert format_model_current().splitlines() == [
        "provider: glm",
        "model: zai/glm-4",
    ]


def test_provider_command_use_persists_default(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr("src.config.set_default_provider", calls.append)

    rc = run_provider_command(["use", "glm"])

    assert rc == 0
    assert calls == ["glm"]
    out = capsys.readouterr().out
    assert "Default provider set to: glm" in out
    # Restart hint also appears so the user doesn't think it took effect immediately.
    assert "next REPL launch" in out


def test_model_use_sets_provider_and_model(monkeypatch) -> None:
    provider_calls: list[str] = []
    model_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.store.ModelStore.set_default_provider",
        lambda self, provider, scope="user": provider_calls.append(provider),
    )
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.store.ModelStore.set_default_model",
        lambda self, provider, model, scope="user", allow_unknown=False: model_calls.append(
            (provider, model)
        ),
    )

    lines = use_model("zai/glm-4", provider="glm")

    assert provider_calls == ["glm"]
    assert model_calls == [("glm", "zai/glm-4")]
    # Three lines: two persistence lines + the "takes effect on next REPL launch" hint.
    assert lines[0] == "Default provider set to: glm"
    assert lines[1] == "Default model for glm set to: zai/glm-4"
    assert "next REPL launch" in lines[2]


def test_model_command_invalid_provider_returns_exit_2(capsys) -> None:
    rc = run_model_command(["list", "--provider", "missing"])

    assert rc == 2
    assert "Unknown provider" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CLI surface: dead --scope parameter removed
# ---------------------------------------------------------------------------


def test_model_use_rejects_scope_flag(capsys) -> None:
    """``--scope`` is no longer accepted by ``clawcodex model use``."""
    rc = run_model_command(["use", "zai/glm-4", "--scope", "project"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--scope" in err
    assert "Unknown argument" in err


def test_provider_use_rejects_scope_flag(capsys) -> None:
    """``--scope`` is no longer accepted by ``clawcodex provider use``."""
    rc = run_provider_command(["use", "glm", "--scope", "project"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--scope" in err
    assert "Unknown argument" in err


def test_provider_unset_rejects_scope_flag(capsys) -> None:
    """``clawcodex provider unset --scope …`` is also rejected."""
    rc = run_provider_command(["unset", "--scope", "project"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--scope" in err
    assert "Unknown argument" in err


# ---------------------------------------------------------------------------
# CLI surface: no-args = current (zero-arg query idiom)
# ---------------------------------------------------------------------------


def test_model_no_args_equals_current(monkeypatch, capsys) -> None:
    """``clawcodex model`` (no args) prints the same as ``clawcodex model current``."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "glm")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "zai/glm-4"},
    )

    rc = run_model_command([])

    assert rc == 0
    assert capsys.readouterr().out == format_model_current() + "\n"


def test_provider_no_args_equals_current(monkeypatch, capsys) -> None:
    """``clawcodex provider`` (no args) prints the same as ``clawcodex provider current``."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "glm")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "zai/glm-4"},
    )

    rc = run_provider_command([])

    assert rc == 0
    assert capsys.readouterr().out == format_provider_current() + "\n"


# ---------------------------------------------------------------------------
# Error message guidance: ``format_model_show`` points the user at --provider
# ---------------------------------------------------------------------------


def test_format_model_show_unknown_model_suggests_provider(capsys) -> None:
    """Unknown models point the user at ``--provider`` and ``model list``."""
    rc = run_model_command(["show", "nonexistent-model-xyz"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--provider" in err
    assert "model list" in err


def test_format_model_show_raises_with_provider_hint() -> None:
    """The underlying ``format_model_show`` raises with the new guidance message."""
    from clawcodex_ext.cli.model_cmd.commands import format_model_show

    with pytest.raises(UnknownModelError) as exc_info:
        format_model_show("nonexistent-model-xyz")

    msg = str(exc_info.value)
    assert "--provider" in msg
    assert "model list" in msg


# ---------------------------------------------------------------------------
# CLI surface: use/parse hardening (treats --bogus as unknown flag, not model name)
# ---------------------------------------------------------------------------


def test_model_use_rejects_bogus_flag(capsys) -> None:
    """``--bogus`` is rejected as an unknown flag instead of being treated as the model name."""
    rc = run_model_command(["use", "--bogus"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--bogus" in err
    assert "Unknown argument" in err


def test_model_use_requires_name(capsys) -> None:
    """``use`` with no NAME prints a focused "NAME is required" hint, not a menu dump."""
    rc = run_model_command(["use"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "NAME is required" in err
    assert "Example:" in err


def test_model_use_provider_requires_value(capsys) -> None:
    """``--provider`` alone (no value) is rejected with a clear message."""
    rc = run_model_command(["use", "zai/glm-4", "--provider"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--provider" in err
    assert "requires a value" in err


def test_model_show_rejects_bogus_flag(capsys) -> None:
    """``show --bogus`` is rejected as an unknown flag."""
    rc = run_model_command(["show", "--bogus"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--bogus" in err
    assert "Unknown argument" in err


def test_provider_use_rejects_bogus_flag(capsys) -> None:
    """``provider use --bogus`` is rejected as an unknown flag."""
    rc = run_provider_command(["use", "--bogus"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "--bogus" in err
    assert "Unknown argument" in err


def test_provider_use_requires_name(capsys) -> None:
    """``provider use`` with no NAME prints a focused "NAME is required" hint."""
    rc = run_provider_command(["use"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "NAME is required" in err
    assert "Example:" in err


# ---------------------------------------------------------------------------
# CLI surface: help subcommand (discoverability)
# ---------------------------------------------------------------------------


def test_model_help_subcommand_prints_usage(capsys) -> None:
    """``clawcodex model help`` exits 0 and prints the usage to stdout."""
    rc = run_model_command(["help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "usage: clawcodex model" in out
    assert "Subcommands:" in out
    for sub in ("list", "show", "current", "use", "help"):
        assert sub in out


def test_model_dash_help_flag_prints_usage(capsys) -> None:
    """``--help`` and ``-h`` are equivalent to the ``help`` subcommand."""
    for flag in ("--help", "-h"):
        rc = run_model_command([flag])
        assert rc == 0
        out = capsys.readouterr().out
        assert "usage: clawcodex model" in out


def test_provider_help_subcommand_prints_usage(capsys) -> None:
    """``clawcodex provider help`` exits 0 and prints the usage to stdout."""
    rc = run_provider_command(["help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "usage: clawcodex provider" in out
    assert "Subcommands:" in out
    for sub in ("list", "show", "current", "use", "unset", "help"):
        assert sub in out


def test_provider_dash_help_flag_prints_usage(capsys) -> None:
    """``provider --help`` and ``-h`` are equivalent to the ``help`` subcommand."""
    for flag in ("--help", "-h"):
        rc = run_provider_command([flag])
        assert rc == 0
        out = capsys.readouterr().out
        assert "usage: clawcodex provider" in out


# ---------------------------------------------------------------------------
# CLI surface: explore view (--list / ls for model, --all / ls for provider)
# ---------------------------------------------------------------------------


def test_model_list_flag_shows_explore_view(monkeypatch, capsys) -> None:
    """``clawcodex model --list`` and ``ls`` give current + full list (REPL-equivalent)."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "glm")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "zai/glm-4"},
    )

    for flag in ("--list", "ls"):
        rc = run_model_command([flag])
        assert rc == 0, f"{flag!r} should exit 0"
        out = capsys.readouterr().out
        assert "provider: glm" in out
        assert "model: zai/glm-4" in out
        assert "Models:" in out  # the REPL's `_format_configured_model_list` header


def test_provider_all_flag_shows_explore_view(monkeypatch, capsys) -> None:
    """``clawcodex provider --all`` and ``ls`` give current + list (REPL-equivalent)."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "glm")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "zai/glm-4"},
    )

    for flag in ("--all", "ls"):
        rc = run_provider_command([flag])
        assert rc == 0, f"{flag!r} should exit 0"
        out = capsys.readouterr().out
        assert "provider: glm" in out
        assert "Providers:" in out


# ---------------------------------------------------------------------------
# Output format unification: ``model show`` matches ``model current``
# ---------------------------------------------------------------------------


def test_model_show_uses_current_format(monkeypatch) -> None:
    """``model show NAME`` and ``model current`` produce the same canonical shape."""
    monkeypatch.delenv("CLAWCODEX_PROVIDER", raising=False)
    monkeypatch.delenv("CLAWCODEX_MODEL", raising=False)
    monkeypatch.setattr("clawcodex_ext.cli.model_cmd.resolver.get_default_provider", lambda: "anthropic")
    monkeypatch.setattr(
        "clawcodex_ext.cli.model_cmd.resolver.get_provider_config",
        lambda provider: {"default_model": "claude-sonnet-4-6"},
    )
    from clawcodex_ext.cli.model_cmd.commands import format_model_show

    # ``show sonnet`` resolves via registry; the canonical format is identical to current.
    out_show = format_model_show("claude-sonnet-4-6")
    out_current = format_model_current()
    assert out_show == out_current
    assert "[" not in out_show  # no source labels
    assert out_show.splitlines() == ["provider: anthropic", "model: claude-sonnet-4-6"]



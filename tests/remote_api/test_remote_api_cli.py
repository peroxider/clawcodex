from __future__ import annotations

from clawcodex_ext.cli.subcommand_registry import get_subcommand
from extensions.remote_api.cli import run_api


def test_api_subcommand_is_registered():
    assert get_subcommand("api") is not None


def test_api_serve_help(capsys):
    try:
        run_api(["serve", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert "clawcodex api serve" in output
    assert "--host" in output
    assert "--port" in output
    assert "--state-limit" in output

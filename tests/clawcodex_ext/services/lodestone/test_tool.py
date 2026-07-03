"""Tests for the LodestoneTool (agent-facing)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from clawcodex_ext.services.lodestone import (
    LodestoneConfig,
    reset_default_service,
)
from clawcodex_ext.tool_system.errors import ToolInputError
from clawcodex_ext.tool_system.tools.lodestone import LodestoneTool


def _ctx(workspace_root: Path | None = None):
    from clawcodex_ext.tool_system.context import ToolContext
    ws = workspace_root or Path("/abs").resolve()
    return ToolContext(workspace_root=ws, cwd=ws)


@pytest.fixture(autouse=True)
def _reset_lodestone_singleton():
    reset_default_service()
    yield
    reset_default_service()


def test_tool_registered_in_extension_tool_pool():
    from extensions.tool_system_ext.registration import EXTENSION_TOOLS
    assert LodestoneTool in EXTENSION_TOOLS


def test_tool_parse_returns_anchors():
    result = LodestoneTool.call({"action": "parse", "text": "src/foo.py:42"}, _ctx())
    assert not result.is_error
    kinds = [a["kind"] for a in result.output["anchors"]]
    assert "file_path" in kinds


def test_tool_resolve_returns_url_per_anchor():
    result = LodestoneTool.call(
        {"action": "resolve", "text": "src/foo.py:42", "sink": "markdown"},
        _ctx(),
    )
    assert not result.is_error
    assert "vscode://" in result.output["results"][0]["rendered"]


def test_tool_render_text():
    result = LodestoneTool.call(
        {"action": "render", "text": "see src/foo.py:42", "sink": "markdown"},
        _ctx(),
    )
    assert not result.is_error
    assert "[src/foo.py:42]" in result.output["rendered"]


def test_tool_config_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWCODEX_CONFIG_DIR", str(tmp_path))
    result = LodestoneTool.call(
        {"action": "config", "changes": {"default_editor": "cursor"}},
        _ctx(),
    )
    assert not result.is_error
    assert result.output["config"]["default_editor"] == "cursor"


def test_tool_open_dispatches_url(monkeypatch):
    from clawcodex_ext.services.lodestone import renderer as lodestone_renderer

    captured: list[str] = []
    monkeypatch.setattr(
        lodestone_renderer, "open_uri", lambda url: captured.append(url)
    )
    result = LodestoneTool.call(
        {"action": "open", "text": "src/foo.py:42", "sink": "markdown"},
        _ctx(),
    )
    assert not result.is_error
    assert any("vscode://" in u for u in captured)
    assert result.output["opened"]


def test_tool_open_errors_when_no_url(monkeypatch):
    """An anchor with no usable target should record an error."""
    from clawcodex_ext.services.lodestone.config import save_config
    cfg = LodestoneConfig(enabled=True, renderer="text", custom_targets=())
    save_config(cfg)
    result = LodestoneTool.call(
        {"action": "open", "text": "src/foo.py:42", "target": "nonexistent"},
        _ctx(),
    )
    # Should not raise; either opened list or errors list carries the
    # anchor.
    assert not result.is_error
    assert result.output["opened"] == [] or result.output["errors"]


def test_tool_rejects_unknown_action():
    with pytest.raises(ToolInputError):
        LodestoneTool.call({"action": "nonsense"}, _ctx())


def test_tool_rejects_bad_sink():
    with pytest.raises(ToolInputError):
        LodestoneTool.call(
            {"action": "render", "text": "x.py:1", "sink": "html"}, _ctx()
        )


def test_tool_disabled_returns_plain_text(monkeypatch):
    monkeypatch.setenv("LODESTONE", "off")
    reset_default_service()
    result = LodestoneTool.call(
        {"action": "render", "text": "see src/foo.py:42", "sink": "markdown"},
        _ctx(),
    )
    assert not result.is_error
    # When disabled, render should return the raw text.
    assert result.output["rendered"] == "see src/foo.py:42"

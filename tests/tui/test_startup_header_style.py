"""Visual contract for the Textual startup header."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from rich.console import Console

from clawcodex_ext.tui.widgets.header import StartupHeader


def _render_header(header: StartupHeader) -> str:
    stream = StringIO()
    console = Console(
        color_system=None,
        file=stream,
        force_terminal=False,
        width=120,
    )
    console.print(header._render_banner())
    return stream.getvalue()


def test_startup_header_uses_current_branding_without_a_mascot() -> None:
    rendered = _render_header(
        StartupHeader(
            version="1.2.3",
            model="test-model",
            provider="test-provider",
            workspace_root=Path("/workspace/project"),
            width_hint=120,
        )
    )

    assert "✦ clawcodex" in rendered
    assert "a coding agent in your terminal" in rendered
    assert "test-model" in rendered
    assert "TEST-PROVIDER Provider" in rendered
    assert "Session:" not in rendered
    assert "(\\/)" not in rendered
    assert "|======|" not in rendered

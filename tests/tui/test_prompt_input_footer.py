"""Unit tests for :class:`PromptInputFooter`.

Round 2 / WI-R2.3 of the ch13 refactor.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult

from src.tui.vim import VimState
from src.tui.widgets.prompt_input_footer import (
    FooterHint,
    PromptInputFooter,
    _MODE_BADGES,
    _SEPARATOR,
)
from src.tui.theme import get_palette


class _Host(App):
    def __init__(self, footer: PromptInputFooter) -> None:
        super().__init__()
        self._footer = footer

    def compose(self) -> ComposeResult:
        yield self._footer


class _LightHost(_Host):
    palette = get_palette("light")


# ---- pure-function tests ----


def test_separator_matches_status_line_style():
    """The separator must match the one ``StatusLine`` uses for visual rhythm."""
    assert _SEPARATOR == " · "


def test_footer_uses_adaptive_muted_text_color():
    assert "color: $text-muted" in PromptInputFooter.DEFAULT_CSS


def test_footer_hint_is_frozen_dataclass():
    """``FooterHint`` should be hashable so callers can use it in sets / dict keys."""
    hint = FooterHint(keys="Esc", label="cancel")
    assert hint.keys == "Esc"
    assert hint.label == "cancel"
    assert hint.when is None
    # Frozen dataclasses raise on attribute assignment.
    with pytest.raises(Exception):
        hint.keys = "x"  # type: ignore[misc]


# ---- widget tests ----


@pytest.mark.asyncio
async def test_default_hints_rendered_with_vim_off():
    vim = VimState(enabled=False)
    footer = PromptInputFooter(vim_state=vim)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        line = footer.last_line
        # Current Ink footer keeps the idle row intentionally terse; the
        # complete key map lives in the ``?`` shortcuts panel.
        assert line == "? for shortcuts"
        assert "i/esc vim" not in line


@pytest.mark.asyncio
async def test_vim_hint_appears_when_vim_on():
    vim = VimState(enabled=True)
    footer = PromptInputFooter(vim_state=vim)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        line = footer.last_line
        assert "i/esc vim" in line


@pytest.mark.asyncio
async def test_refresh_hints_picks_up_vim_toggle():
    """Toggling vim mode after mount must update the visible hints."""
    vim = VimState(enabled=False)
    footer = PromptInputFooter(vim_state=vim)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        assert "i/esc vim" not in footer.last_line
        vim.set_enabled(True)
        footer.refresh_hints()
        await pilot.pause()
        assert "i/esc vim" in footer.last_line


@pytest.mark.asyncio
async def test_permission_mode_badge_renders_on_footer_right():
    footer = PromptInputFooter()
    async with _Host(footer).run_test(size=(100, 8)) as pilot:
        footer.set_permission_mode("plan")
        await pilot.pause()
        line = footer.last_line
        assert line.startswith("? for shortcuts")
        assert line.endswith("⏸ plan mode on (shift+tab to cycle)")
        assert "  " in line


@pytest.mark.asyncio
async def test_bash_hint_keeps_permission_badge():
    footer = PromptInputFooter()
    async with _Host(footer).run_test(size=(100, 8)) as pilot:
        footer.set_permission_mode("acceptEdits")
        footer.set_bash_mode(True)
        await pilot.pause()
        assert footer.last_line.startswith("! for bash mode")
        assert footer.last_line.endswith("▶▶ accept edits on (shift+tab to cycle)")


@pytest.mark.asyncio
async def test_permission_badge_uses_light_theme_semantic_color():
    footer = PromptInputFooter()
    async with _LightHost(footer).run_test() as pilot:
        await pilot.pause()
        assert footer._badge_style(_MODE_BADGES["auto"]) == "bold #966C1E"


@pytest.mark.asyncio
async def test_custom_hints_provider_overrides_defaults():
    def provider() -> list[FooterHint]:
        return [FooterHint(keys="F1", label="help")]

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        assert footer.last_line == "F1 help"


@pytest.mark.asyncio
async def test_empty_hints_hides_widget():
    def provider() -> list[FooterHint]:
        return []

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        assert footer.has_class("-hidden")
        assert footer.last_line == ""


@pytest.mark.asyncio
async def test_when_predicate_filters_hints():
    def provider() -> list[FooterHint]:
        return [
            FooterHint(keys="A", label="always"),
            FooterHint(keys="N", label="never", when=lambda: False),
            FooterHint(keys="Y", label="yes", when=lambda: True),
        ]

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        line = footer.last_line
        assert "A always" in line
        assert "N never" not in line
        assert "Y yes" in line


@pytest.mark.asyncio
async def test_when_predicate_exception_filters_silently():
    """A throwing predicate should be treated as 'false', not propagated.

    Widgets that call into application state must not crash the input
    UI when state lookup throws.
    """

    def boom() -> bool:
        raise RuntimeError("predicate bug")

    def provider() -> list[FooterHint]:
        return [
            FooterHint(keys="A", label="ok"),
            FooterHint(keys="B", label="broken", when=boom),
        ]

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        line = footer.last_line
        assert "A ok" in line
        assert "B broken" not in line


@pytest.mark.asyncio
async def test_provider_exception_falls_back_to_empty():
    def provider() -> list[FooterHint]:
        raise RuntimeError("provider bug")

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        # Empty hint set hides the widget.
        assert footer.has_class("-hidden")
        assert footer.last_line == ""


@pytest.mark.asyncio
async def test_hints_use_dot_separator():
    def provider() -> list[FooterHint]:
        return [
            FooterHint(keys="A", label="alpha"),
            FooterHint(keys="B", label="beta"),
        ]

    footer = PromptInputFooter(hints_provider=provider)
    async with _Host(footer).run_test() as pilot:
        await pilot.pause()
        assert footer.last_line == "A alpha · B beta"

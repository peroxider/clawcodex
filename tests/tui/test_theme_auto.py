"""Unit tests for :func:`src.tui.theme.resolve_auto_theme`."""

from __future__ import annotations

import pytest

from src.tui.theme import (
    get_palette,
    list_theme_names,
    resolve_auto_theme,
    textual_css_overrides,
)


def test_list_theme_names_starts_with_auto():
    names = list_theme_names()
    assert names[0] == "auto"
    assert {"dark", "light", "claude"}.issubset(set(names))


def test_forced_env_wins():
    resolved = resolve_auto_theme(env={"CLAWCODEX_THEME": "light"})
    assert resolved == "light"


def test_forced_env_unknown_falls_through():
    resolved = resolve_auto_theme(env={"CLAWCODEX_THEME": "solarized"})
    # Unknown forced value must not short-circuit — fallback wins.
    assert resolved == "dark"


def test_colorfgbg_dark_detected():
    resolved = resolve_auto_theme(env={"COLORFGBG": "15;0"})
    assert resolved == "dark"


def test_colorfgbg_light_detected():
    resolved = resolve_auto_theme(env={"COLORFGBG": "0;15"})
    assert resolved == "light"


def test_empty_env_falls_back_to_dark():
    resolved = resolve_auto_theme(env={})
    assert resolved == "dark"


def test_get_palette_auto_honours_env():
    palette = get_palette("auto", env={"COLORFGBG": "0;15"})
    assert palette.name == "light"


def test_current_palette_uses_warm_brand_hue_and_neutral_transcript_roles():
    palette = get_palette("dark")
    assert palette.primary == "#D77757"
    assert palette.surface_alt == "#373737"
    assert palette.assistant == "#FFFFFF"
    assert palette.user == "#505050"


@pytest.mark.asyncio
async def test_current_palette_css_variables_parse_in_textual():
    from textual.app import App

    class _ThemeHarness(App):
        CSS = textual_css_overrides(get_palette("dark"))

    async with _ThemeHarness().run_test():
        pass

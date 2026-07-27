"""Theme palette for the Claw Codex Textual TUI.

Mirrors the palette keys defined in ``typescript/src/utils/theme.js`` so
widgets port 1-for-1 (``theme.primary``, ``theme.success`` etc.). Three
built-in palettes are exposed: ``dark``, ``light``, and ``claude`` — the
dark variant is the default and is tuned to match the ink reference.

The palette is deliberately plain-dataclass so Textual CSS references
like ``$primary`` continue to work via ``App.theme`` + ``ColorSystem``;
we expose the raw hex constants so Rich renderables inside widgets
(panels, markdown, etc.) can use the same colors as the CSS layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    # Foreground + background
    text: str
    text_muted: str
    background: str
    surface: str
    surface_alt: str
    border: str
    # Semantic colors (match typescript/src/utils/theme.js keys)
    primary: str
    secondary: str
    success: str
    warning: str
    error: str
    info: str
    # Role-specific
    user: str
    assistant: str
    tool: str
    tool_running: str
    tool_success: str
    tool_error: str
    system: str
    # Streaming / spinner
    spinner: str
    verb: str


DARK = Palette(
    name="dark",
    # Official 398b44f visual language: one warm brand hue, then neutral
    # grays.  The transcript uses ``surface_alt`` for the full-width user
    # message band and ``user`` for its deliberately subtle pointer.
    text="#FFFFFF",
    text_muted="#999999",
    background="#181818",
    surface="#1F1F1F",
    surface_alt="#373737",
    border="#505050",
    primary="#D77757",
    secondary="#FFFFFF",
    success="#4EBA65",
    warning="#FFC107",
    error="#FF6B80",
    info="#B1B9F9",
    user="#505050",
    assistant="#FFFFFF",
    tool="#4EBA65",
    tool_running="#999999",
    tool_success="#4EBA65",
    tool_error="#FF6B80",
    system="#999999",
    spinner="#D77757",
    verb="#FFFFFF",
)

LIGHT = Palette(
    name="light",
    text="#000000",
    text_muted="#666666",
    background="#FFFFFF",
    surface="#F5F5F5",
    surface_alt="#F0F0F0",
    border="#AFAFAF",
    primary="#D77757",
    secondary="#000000",
    success="#2C7A39",
    warning="#966C1E",
    error="#AB2B3F",
    info="#5769F7",
    user="#AFAFAF",
    assistant="#000000",
    tool="#2C7A39",
    tool_running="#666666",
    tool_success="#2C7A39",
    tool_error="#AB2B3F",
    system="#666666",
    spinner="#D77757",
    verb="#000000",
)

CLAUDE = Palette(
    name="claude",
    # Keep the historical selector as a compatibility alias while bringing
    # it onto the same current, neutral rendering system.
    text="#FFFFFF",
    text_muted="#999999",
    background="#181818",
    surface="#1F1F1F",
    surface_alt="#373737",
    border="#505050",
    primary="#D77757",
    secondary="#FFFFFF",
    success="#4EBA65",
    warning="#FFC107",
    error="#FF6B80",
    info="#B1B9F9",
    user="#505050",
    assistant="#FFFFFF",
    tool="#4EBA65",
    tool_running="#999999",
    tool_success="#4EBA65",
    tool_error="#FF6B80",
    system="#999999",
    spinner="#D77757",
    verb="#FFFFFF",
)


_PALETTES: dict[str, Palette] = {
    "dark": DARK,
    "light": LIGHT,
    "claude": CLAUDE,
}


def list_theme_names() -> list[str]:
    """Return every selectable theme id, including ``auto``."""

    return ["auto", *_PALETTES.keys()]


def resolve_auto_theme(*, env: dict[str, str] | None = None) -> str:
    """Best-effort OS appearance detection for ``auto``.

    Mirrors the behaviour of ``watchSystemTheme`` in
    ``typescript/src/utils/theme.js`` but does not attempt to install
    any system-level watcher — we snapshot once at boot. Detection
    order:

    1. ``CLAWCODEX_THEME`` env var — explicit override, returned verbatim
       if it names a known palette.
    2. ``COLORFGBG`` (VTE / iTerm2) — trailing digit; ``0``/``dark``
       means dark surface.
    3. macOS ``defaults read -g AppleInterfaceStyle`` via subprocess —
       returns ``"dark"`` when Dark Mode is on.
    4. Fallback: ``"dark"``.
    """

    import os
    import subprocess

    environment = env if env is not None else os.environ

    forced = environment.get("CLAWCODEX_THEME", "").strip().lower()
    if forced and forced != "auto" and forced in _PALETTES:
        return forced

    cfgbg = environment.get("COLORFGBG", "").strip()
    if cfgbg:
        try:
            trailing = cfgbg.split(";")[-1].strip()
            bg = int(trailing)
            # Low numbers (0-6) are generally dark; 7-15 bright.
            return "dark" if bg < 7 else "light"
        except (ValueError, IndexError):
            pass

    if environment.get("__CFBundleIdentifier") or environment.get("TERM_PROGRAM"):
        try:
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            if out.returncode == 0 and "dark" in out.stdout.lower():
                return "dark"
            if out.returncode != 0:
                # The key is absent when Light Mode is active.
                return "light"
        except Exception:
            pass

    return "dark"


def get_palette(name: str | None, *, env: dict[str, str] | None = None) -> Palette:
    """Return a palette by name with graceful fallback.

    ``auto`` runs :func:`resolve_auto_theme` to pick between ``dark``
    and ``light`` at boot. Unknown names fall back to ``dark``.
    """

    if not name:
        return DARK
    key = name.strip().lower()
    if key == "auto":
        return _PALETTES.get(resolve_auto_theme(env=env), DARK)
    return _PALETTES.get(key, DARK)


def textual_css_overrides(palette: Palette) -> str:
    """Textual ``App.CSS`` overrides that map the palette onto the theme
    variables referenced throughout the widget CSS.

    Textual exposes ``$primary``, ``$background`` etc. via
    ``ColorSystem``; for Phase 1 we keep this as a flat CSS block so the
    widgets can reference raw palette colors alongside built-ins without
    fighting ``textual.theme`` subclassing.
    """

    # Textual CSS variables MUST be defined at the stylesheet *top level*,
    # NOT inside a selector (otherwise the CSS parser rejects them).
    return f"""
$primary: {palette.primary};
$secondary: {palette.secondary};
$surface: {palette.surface};
$surface-alt: {palette.surface_alt};
$text: {palette.text};
$text-muted: {palette.text_muted};
$border: {palette.border};
$warning: {palette.warning};
$success: {palette.success};
$error: {palette.error};
Screen {{
    background: {palette.background};
    color: {palette.text};
}}
    """

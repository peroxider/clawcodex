"""Lazy entrypoint exports for legacy and current UI launchers."""

from __future__ import annotations

from importlib import import_module

_LAZY_NAMES = {
    "HeadlessOptions": ("clawcodex_ext.entrypoints.headless", "HeadlessOptions"),
    "run_headless": ("clawcodex_ext.entrypoints.headless", "run_headless"),
    "TUIOptions": ("clawcodex_ext.entrypoints.tui", "TUIOptions"),
    "run_tui": ("clawcodex_ext.entrypoints.tui", "run_tui"),
    "should_use_tui": ("clawcodex_ext.entrypoints.tui", "should_use_tui"),
    "launch_ink_tui": ("src.entrypoints.tui_launcher", "launch_ink_tui"),
    "run_tui_launcher": ("src.entrypoints.tui_launcher", "run_tui_launcher"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _LAZY_NAMES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = list(_LAZY_NAMES)

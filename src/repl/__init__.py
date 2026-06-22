"""REPL module for Claw Codex."""

from .background_escape import BackgroundEscape

__all__ = ["ClawcodexREPL", "BackgroundEscape"]


def __getattr__(name: str):
    if name == "ClawcodexREPL":
        from .core import ClawcodexREPL

        globals()[name] = ClawcodexREPL
        return ClawcodexREPL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

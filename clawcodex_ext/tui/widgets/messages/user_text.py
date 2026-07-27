"""User turn row.

Port of the 398b44f transcript treatment: a full-width, weak-gray band
carries the emphasis while a subtle ``❯`` pointer and plain body text keep
the row quieter than a traditional colored/bold chat bubble. Multi-line
prompts are preserved.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from .base import BaseRow


class UserTextMessage(BaseRow):
    """A user prompt shown in the transcript."""

    DEFAULT_CSS = """
    UserTextMessage {
        height: auto;
        width: 100%;
        background: #373737;
    }
    UserTextMessage > Static {
        padding: 0 1;
        width: 100%;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def on_mount(self) -> None:
        """Apply the active palette's user-band color.

        A literal dark fallback in ``DEFAULT_CSS`` keeps this standalone
        widget valid in small Textual test harnesses that do not install the
        application-level palette variables.
        """

        try:
            self.styles.background = self.app.palette.surface_alt
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Static(self._build_text(), markup=False)

    def _build_text(self) -> Text:
        try:
            pointer_color = self.app.palette.user
            body_color = self.app.palette.text
        except Exception:
            pointer_color = "#505050"
            body_color = "#FFFFFF"
        prefix = Text("❯ ", style=pointer_color)
        body = Text(self._text, style=body_color)
        return prefix + body

    def snapshot(self) -> Text:
        """Return a Rich :class:`Text` for post-exit scrollback dump."""

        return self._build_text()

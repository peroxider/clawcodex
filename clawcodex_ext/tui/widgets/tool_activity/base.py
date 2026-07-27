"""Base class for tool-activity widgets.

Parity note: in ink, ``renderToolActivity`` dispatches per tool kind and
each renderer is responsible for its own *in-flight* view
(e.g. ``ShellProgress`` for bash) and *completion* view
(``GroupedToolUseContent`` summary). We keep the same structure — the
base widget exposes :meth:`on_result` so the owning row can swap body
contents without re-mounting the widget tree.
"""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.padding import Padding
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class ToolActivity(Widget):
    """Baseline tool-activity widget.

    Subclasses typically override :meth:`inflight_text` and
    :meth:`result_body` to add tool-specific rendering; :meth:`compose`
    and :meth:`on_result` handle the lifecycle.
    """

    DEFAULT_CSS = """
    ToolActivity {
        layout: vertical;
        height: auto;
        padding: 0;
    }
    ToolActivity > Static.-inflight {
        color: $text-muted;
    }
    """

    def __init__(self, *, tool_name: str, tool_input: dict[str, Any]) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.tool_input = dict(tool_input or {})
        self._result_static: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            _with_trail_connector(self.inflight_text()),
            markup=False,
            classes="-inflight",
        )

    # ---- subclass hooks ----
    def inflight_text(self) -> Text:
        """Text shown while the tool is still running."""
        return Text("…", style="dim")

    def result_body(self, output: Any, *, is_error: bool) -> Any | None:
        """Return a Rich renderable for the completed body, or ``None``
        to leave the body empty (the row header already carries status).
        """
        return None

    # ---- lifecycle ----
    def on_result(
        self,
        output: Any,
        *,
        is_error: bool,
        error: str | None = None,
    ) -> None:
        try:
            for static in self.query(Static):
                if static.has_class("-inflight"):
                    static.remove()
                    break
        except Exception:
            pass
        body = self.result_body(output, is_error=is_error)
        if is_error and body is None and error:
            body = Text(error, style="red")
        if body is None:
            return
        result_widget = Static(_with_trail_connector(body), markup=False)
        self._result_static = result_widget
        try:
            self.mount(result_widget)
        except Exception:
            pass


_BODY_MAX_CHARS = 1500
_BODY_MAX_LINES = 20


def truncate_body(text: str) -> tuple[str, bool]:
    """``(shown, truncated)`` under the shared panel limits.

    THE single truncation implementation — ``truncated_panel`` and the
    transcript's bash/expandable paths all use it so the limits (and the
    trailing-newline rstrip) can never drift apart (C4 review m5).
    """

    s = (text or "").rstrip("\n")
    lines = s.split("\n")
    truncated = False
    if len(lines) > _BODY_MAX_LINES:
        lines = lines[:_BODY_MAX_LINES]
        truncated = True
    s = "\n".join(lines)
    if len(s) > _BODY_MAX_CHARS:
        s = s[:_BODY_MAX_CHARS]
        truncated = True
    return s, truncated


def truncated_panel(text: str, *, style: str = "green") -> Text:
    """Render ``text`` as a flat, truncated tool-detail block.

    The historical function name stays in place for renderer compatibility,
    but 398b44f's tool trail deliberately drops bordered panels. Successful
    details recede as dim neutral text; failures retain their red signal.
    """

    s, truncated = truncate_body(text)
    if truncated:
        s = f"{s}\n… (truncated)"
    tone = "red" if style.lower() == "red" else "dim"
    return Text(s, style=tone)


def _with_trail_connector(renderable: Any) -> Any:
    """Place a tool detail beneath its call using the flat ``⎿`` gutter.

    Text results keep their spans and share the connector's first line. More
    complex Rich renderables (structured diffs, LKB panels, groups) retain
    their original object and are introduced by a connector line. No tool
    metadata is discarded or rewritten.
    """

    connector = Text("  ⎿  ", style="dim")
    if isinstance(renderable, Text):
        lines = renderable.split("\n", allow_blank=True)
        out = Text()
        for index, line in enumerate(lines):
            out.append_text(connector.copy() if index == 0 else Text("     "))
            out.append_text(line)
            if index < len(lines) - 1:
                out.append("\n")
        return out
    return Group(Text("  ⎿", style="dim"), Padding(renderable, (0, 0, 0, 5)))

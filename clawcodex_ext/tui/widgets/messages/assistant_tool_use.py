"""Assistant tool-use row.

Port of ``typescript/src/components/messages/AssistantToolUseMessage.tsx``
and ``renderToolActivity`` in ``typescript/src/components/tasks/``. The
row is announced the moment the assistant emits a ``tool_use`` block
and its body is a per-tool :class:`ToolActivity` subclass that mutates
through ``requested → running → done / error`` as tool events arrive
from the agent loop.

Key behavioural parity points:

* The row is mounted **once** per tool-use id; subsequent events update
  the existing body instead of appending a new row.
* The flat ``⏺ Tool(args)`` call stays stable across lifecycle updates;
  status is carried by the bullet color while result rows sit under ``⎿``.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive

from .base import BaseRow, RowHeader
from ..lkb_proof import LKBProofWidget, extract_lkb_denial
from ..tool_activity import build_tool_activity, ToolActivity


class AssistantToolUseMessage(BaseRow):
    """Transcript row that owns a :class:`ToolActivity` child widget."""

    DEFAULT_CSS = """
    AssistantToolUseMessage {
        height: auto;
    }
    """

    status: reactive[str] = reactive("requested")

    def __init__(
        self,
        *,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict | None,
    ) -> None:
        super().__init__()
        self.tool_use_id = tool_use_id
        self.tool_name = tool_name
        self.tool_input = dict(tool_input or {})
        self._activity: ToolActivity | None = None

    # ---- composition ----
    def compose(self) -> ComposeResult:
        header = RowHeader(self._header_text(), markup=False)
        header.add_class("-tool")
        yield header
        self._activity = build_tool_activity(self.tool_name, self.tool_input)
        yield self._activity

    # ---- lifecycle updates ----
    def mark_running(self) -> None:
        self._set_status("running")

    def mark_done(self, output) -> None:
        self._set_status("done")
        if self._activity is not None:
            self._activity.on_result(output, is_error=False)
        # Mount LKB proof widget when the tool was denied by the commit gate.
        self._maybe_mount_lkb_denial(output)

    def mark_error(self, output, *, error: str | None = None) -> None:
        self._set_status("error")
        if self._activity is not None:
            self._activity.on_result(output, is_error=True, error=error)
        self._maybe_mount_lkb_denial(output)

    # ---- internals ----
    def _set_status(self, status: str) -> None:
        self.status = status
        header = self._header_widget()
        if header is None:
            return
        header.remove_class("-tool", "-tool-success", "-tool-error")
        if status in ("done",):
            header.add_class("-tool-success")
        elif status in ("error",):
            header.add_class("-tool-error")
        else:
            header.add_class("-tool")
        header.update(self._header_text())

    def _header_text(self) -> Text:
        try:
            palette = self.app.palette
            text_color = palette.text
            bullet_color = {
                "done": palette.tool_success,
                "error": palette.tool_error,
            }.get(self.status, palette.tool_running)
        except Exception:
            text_color = "#FFFFFF"
            bullet_color = {
                "done": "#4EBA65",
                "error": "#FF6B80",
            }.get(self.status, "#999999")

        summary = _summarise_input(self.tool_name, self.tool_input)
        header = Text("⏺ ", style=bullet_color)
        header.append(self.tool_name, style=f"bold {text_color}")
        if summary:
            header.append(f"({summary})", style=text_color)
        return header

    def snapshot(self) -> Text:
        """Return a Rich :class:`Text` for post-exit scrollback dump."""
        return self._header_text()

    def _header_widget(self) -> RowHeader | None:
        try:
            for header in self.query(RowHeader):
                return header
        except Exception:
            return None
        return None

    # ---- LKB denial detection ----

    def _maybe_mount_lkb_denial(self, output) -> None:
        """If *output* contains an LKB denial, mount a :class:`LKBProofWidget`."""
        try:
            denial = extract_lkb_denial(output)
            if denial is not None:
                self.mount(LKBProofWidget(denial))
        except Exception:
            pass  # best-effort; don't crash the transcript row


def _summarise_input(tool_name: str, tool_input: dict) -> str:
    """One-line summary for the tool-use header, e.g. ``Bash(ls)``.

    Delegates to :mod:`src.tool_system.renderers.summarize_tool_use` when
    available so the TUI, the legacy REPL, and the headless NDJSON path
    all agree on wording.
    """

    try:
        from src.tool_system.renderers import summarize_tool_use

        return summarize_tool_use(tool_name, tool_input or {}) or ""
    except Exception:
        return ""

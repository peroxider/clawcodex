from __future__ import annotations

from types import SimpleNamespace

from clawcodex_ext.intent_forecast.messages import ForecastResult, format_forecast_for_display
from clawcodex_ext.tui.app import ClawCodexTUI


class _Transcript:
    def __init__(self, *, is_mounted: bool) -> None:
        self.is_mounted = is_mounted
        self.rows: list[tuple[str, str, str | None]] = []

    def append_system(self, text: str, *, style: str = "muted", render: str | None = None) -> None:
        self.rows.append((text, style, render))


def test_tui_buffers_forecast_until_transcript_is_mounted() -> None:
    app = ClawCodexTUI.__new__(ClawCodexTUI)
    transcript = _Transcript(is_mounted=False)
    app._repl_screen = SimpleNamespace(transcript=transcript)
    app._pending_system_messages = []
    app.call_after_refresh = lambda callback: None  # type: ignore[method-assign]

    text = format_forecast_for_display(ForecastResult(generated=False, suggestions=[]))
    app._append_repl_system_message(text, style="light", render="markdown")

    assert transcript.rows == []
    assert app._pending_system_messages == [(text, "light", "markdown")]

    transcript.is_mounted = True
    app._flush_pending_system_messages()

    assert transcript.rows == [(text, "light", "markdown")]
    assert app._pending_system_messages == []

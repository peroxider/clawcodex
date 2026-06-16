"""In-memory reporter used for tests and the CLI ``preview`` subcommand."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Final

from .base import Reporter

_MAX_HISTORY: Final[int] = 32


@dataclass
class _RenderedRow:
    date: str
    text: str


class DryRunReporter(Reporter):
    """Records the last N rendered payloads in memory.

    No I/O, no secret scanning — but :meth:`scan_artifact` is exposed
    so the CLI ``preview`` subcommand can still run the secret scan
    over what *would* be uploaded.
    """

    def __init__(self, max_history: int = _MAX_HISTORY) -> None:
        self._history: deque[_RenderedRow] = deque(maxlen=max_history)
        self.last_rendered: str = ""
        self.last_date: str = ""

    def render(self, summary: dict[str, Any], date: str) -> str:
        return _render_markdown(summary, date)

    def emit(self, rendered: str, *, date: str) -> bool:
        self.last_rendered = rendered
        self.last_date = date
        self._history.append(_RenderedRow(date=date, text=rendered))
        return True

    # -- helpers --------------------------------------------------------

    def history(self) -> list[_RenderedRow]:
        return list(self._history)

    def clear(self) -> None:
        self._history.clear()
        self.last_rendered = ""
        self.last_date = ""


def _render_markdown(summary: dict[str, Any], date: str) -> str:
    """Render the F-97 daily summary as Markdown.

    Pure function. Mirrors the Issue body template in
    ``docs/FEATURE_PLAN.md`` §9.5 (issue body example) but is fully
    local-only — no issue creation, no remote upload.
    """
    version = summary.get("version", "unknown")
    sessions = summary.get("sessions", 0)
    commands = summary.get("commands", 0)
    platforms = summary.get("platforms", {}) or {}
    exit_status_counts = summary.get("exit_status_counts", {}) or {}
    duration = summary.get("duration_s", {}) or {}

    lines: list[str] = []
    lines.append(f"# ClawCodex Telemetry Summary — {date}")
    lines.append("")
    lines.append(f"- Version: {version}")
    lines.append(f"- Sessions: {sessions}")
    lines.append(f"- Command runs: {commands}")
    if duration:
        total = duration.get("total", 0)
        samples = duration.get("samples", 0)
        lines.append(f"- Duration total (s): {total} (samples: {samples})")
    if exit_status_counts:
        lines.append(
            "- Exit status counts: "
            + ", ".join(
                f"{key}={value}" for key, value in sorted(exit_status_counts.items())
            )
        )
    if platforms:
        lines.append(
            "- Platforms: "
            + ", ".join(f"{k} {v}" for k, v in sorted(platforms.items()))
        )
    providers = summary.get("providers", {}) or {}
    if providers:
        lines.append(
            "- Providers: "
            + ", ".join(f"{k} {v}" for k, v in sorted(providers.items()))
        )

    crashes = summary.get("crashes", {}) or {}
    top_crashes = crashes.get("top", []) if isinstance(crashes, dict) else []
    if top_crashes:
        lines.append("")
        lines.append("## Top error fingerprints")
        lines.append("")
        lines.append("| Fingerprint | Count | Error class | First seen | Last seen |")
        lines.append("|-------------|------:|-------------|------------|-----------|")
        for row in top_crashes:
            lines.append(
                "| {fp} | {count} | {cls} | {first} | {last} |".format(
                    fp=row.get("fingerprint", "?"),
                    count=row.get("count", 0),
                    cls=row.get("error_class", "?"),
                    first=row.get("first_seen_iso", "?"),
                    last=row.get("last_seen_iso", "?"),
                )
            )

    top_commands = summary.get("top_commands", []) or []
    if top_commands:
        lines.append("")
        lines.append("## Top commands")
        lines.append("")
        for entry in top_commands:
            lines.append(f"- {entry.get('name', '?')}: {entry.get('count', 0)}")

    tools = summary.get("tools", {}) or {}
    top_tools = tools.get("top", []) if isinstance(tools, dict) else []
    if top_tools:
        lines.append("")
        lines.append("## Top tools")
        for entry in top_tools:
            lines.append(f"- {entry.get('name', '?')}: {entry.get('count', 0)}")

    lines.append("")
    lines.append(
        "No prompts, outputs, file contents, API keys, environment variables, "
        "or absolute paths are included."
    )
    return "\n".join(lines) + "\n"

"""Render current Plan Graph denial payloads in the transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


@dataclass(frozen=True, slots=True)
class LkbDenialPayload:
    """Structured denial returned by the current TaskV2/LKB adapter."""

    decision: str
    reason: str
    validation_run_id: str | None = None
    next_actions: tuple[dict[str, Any], ...] = ()


def extract_lkb_denial(output: Any) -> LkbDenialPayload | None:
    """Return the first current-shape ``lkb.decision=denied`` payload."""

    found: list[Mapping[str, Any]] = []

    def _walk(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        payload = value.get("lkb")
        if isinstance(payload, Mapping) and payload.get("decision") == "denied":
            found.append(payload)
        for nested in value.values():
            _walk(nested)

    _walk(output)
    if not found:
        return None

    payload = found[0]
    actions = payload.get("nextActions")
    return LkbDenialPayload(
        decision="denied",
        reason=str(payload.get("reason") or "LKB validation denied this mutation"),
        validation_run_id=(
            str(payload["validationRunId"]) if payload.get("validationRunId") else None
        ),
        next_actions=tuple(dict(item) for item in actions if isinstance(item, Mapping))
        if isinstance(actions, list)
        else (),
    )


class LKBProofWidget(Static):
    """Render the denial reason and executable recovery actions."""

    DEFAULT_CSS = """
    LKBProofWidget {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, denial: LkbDenialPayload) -> None:
        self.denial = denial
        super().__init__(self._build_panel(), markup=False)

    def _build_panel(self) -> Panel:
        lines = [Text(self.denial.reason, style="red")]
        if self.denial.validation_run_id:
            lines.append(Text(f"Validation run: {self.denial.validation_run_id}", style="dim"))
        if self.denial.next_actions:
            lines.append(Text(""))
            lines.append(Text("Next actions:", style="bold"))
            for index, action in enumerate(self.denial.next_actions, 1):
                lines.append(self._render_action(index, action))
        body = Text("\n").join(lines)
        return Panel(body, title="❌ LKB mutation denied", border_style="red")

    @staticmethod
    def _render_action(index: int, action: Mapping[str, Any]) -> Text:
        label = str(action.get("description") or action.get("action") or "recover")
        tool = str(action.get("tool") or "")
        tool_input = action.get("input")
        text = Text(f"  [{index}] {label}", style="cyan")
        if tool:
            text.append(f"\n      {tool}", style="bold")
        if isinstance(tool_input, Mapping) and tool_input:
            args = ", ".join(f"{key}={value}" for key, value in tool_input.items())
            text.append(f"({args})", style="dim")
        return text


__all__ = ["LKBProofWidget", "LkbDenialPayload", "extract_lkb_denial"]

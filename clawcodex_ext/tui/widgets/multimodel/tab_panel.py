from __future__ import annotations

from textual.widgets import Static


class ModelTabPanel(Static):
    """Scrollable-content-compatible body for the selected model."""
    def set_content(self, slot: str, content: str) -> None:
        self.update(f"{slot} 输出中…\n\n{content}")

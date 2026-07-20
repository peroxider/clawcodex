from __future__ import annotations

from textual.widgets import Static


class MultiModelDiffPanel(Static):
    def set_diff(self, left_slot: str, right_slot: str, lines: list[str]) -> None:
        self.update(f"── Diff 模式: {left_slot} vs {right_slot} ──\n" + "\n".join(lines))

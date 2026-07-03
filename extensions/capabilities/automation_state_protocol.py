from __future__ import annotations

from typing import Any, Protocol


class AutomationStateReporter(Protocol):
    def automation_state(self) -> dict[str, Any]:
        """Return a JSON-serialisable automation state snapshot."""
        ...


__all__ = ["AutomationStateReporter"]

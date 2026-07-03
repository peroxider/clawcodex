from __future__ import annotations

from typing import Any

from clawcodex_ext.services.proactive import get_default_controller


class ProactiveAutomationStateReporter:
    def automation_state(self) -> dict[str, Any]:
        return get_default_controller().state.to_dict()


def current_automation_state() -> dict[str, Any]:
    return ProactiveAutomationStateReporter().automation_state()


def set_proactive_focus(level: str) -> dict[str, Any]:
    ctrl = get_default_controller()
    ctrl.set_focus(level)  # type: ignore[arg-type]
    return ctrl.state.to_dict()


__all__ = [
    "ProactiveAutomationStateReporter",
    "current_automation_state",
    "set_proactive_focus",
]

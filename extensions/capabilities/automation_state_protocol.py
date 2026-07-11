"""Automation-state protocols for the orchestrator and its observers.

There are three complementary contracts here:

* :class:`AutomationStateReporter` — pull model. Anyone implementing this
  can answer ``automation_state()`` with a JSON-serialisable snapshot.
  Useful for health checks, dashboards and debug endpoints.
* :class:`AutomationStateObserver` — push model. Subscribers receive an
  ``on_automation_state(snapshot)`` callback whenever the source pushes a
  new snapshot. Channels / external sinks (e.g. the Feishu activity sink
  at :class:`extensions.orchestrator.feishu_activity_sink.FeishuActivitySink`)
  implement this contract.
* :class:`AutomationStateSource` — combined contract. A source that both
  exposes the current snapshot and accepts new subscribers. The
  orchestrator's :class:`extensions.orchestrator.status_dashboard.StatusDashboard`
  conforms to this contract.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class AutomationStateReporter(Protocol):
    def automation_state(self) -> dict[str, Any]:
        """Return a JSON-serialisable automation state snapshot."""
        ...


@runtime_checkable
class AutomationStateObserver(Protocol):
    """Push-mode consumer of automation-state snapshots.

    Implementations are expected to be cheap and idempotent — the source
    may invoke ``on_automation_state`` rapidly during long-running
    sessions, and observers must not block the publisher.
    """

    def on_automation_state(self, snapshot: dict[str, Any]) -> None:
        """Receive a fresh automation-state snapshot from a source."""
        ...


@runtime_checkable
class AutomationStateSource(Protocol):
    """An automation-state object that supports both pull and subscribe.

    Concrete implementations: :class:`extensions.orchestrator.status_dashboard.StatusDashboard`
    exposes ``automation_state()`` and accepts observers via registration
    with the activity-sink wiring.
    """

    def automation_state(self) -> dict[str, Any]:
        """Return the current snapshot."""
        ...

    def subscribe(self, observer: AutomationStateObserver) -> None:
        """Register ``observer`` to receive future snapshots."""
        ...


__all__ = [
    "AutomationStateObserver",
    "AutomationStateReporter",
    "AutomationStateSource",
]

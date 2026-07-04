"""Orchestrator → IM event bridge (P3).

Defines the event types, the :class:`OrchestratorEventEmitter` (a
:class:`ProgressSink` that also exposes an explicit ``emit()``), the
event → IM text formatter, and :class:`ChannelProgressSink` that
delivers formatted events to the gateway. Per-sink exception isolation
is baked in so an IM failure never breaks the orchestrator main flow.
"""

from __future__ import annotations

from .emitter import OrchestratorEventEmitter
from .formatter import format_event
from .types import EventLevel, OrchestratorEvent

__all__ = [
    'EventLevel',
    'OrchestratorEvent',
    'OrchestratorEventEmitter',
    'format_event',
]

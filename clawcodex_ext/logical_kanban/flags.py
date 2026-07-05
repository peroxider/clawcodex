"""Feature-flag helpers for Logical Kanban."""

from __future__ import annotations

from clawcodex_ext.feature_gate import get_registry, register_defaults

FEATURE_NAME = "logical_kanban"


def is_logical_kanban_enabled() -> bool:
    register_defaults()
    return get_registry().is_enabled(FEATURE_NAME)

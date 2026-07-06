"""Feature-flag helpers for Logical Kanban."""

from __future__ import annotations

from clawcodex_ext.feature_gate import get_registry, register_defaults

FEATURE_NAME = "logical_kanban"
CAUSAL_FEATURE_NAME = "LKB_CAUSAL"


def is_logical_kanban_enabled() -> bool:
    register_defaults()
    return get_registry().is_enabled(FEATURE_NAME)


def is_causal_verification_enabled() -> bool:
    """Return True when the F-141 causal verification gate may run.

    The flag is opt-in and depends on the parent ``logical_kanban`` flag
    (F-126).  When the parent is off, the causal gate is treated as
    disabled regardless of its own override.
    """
    register_defaults()
    if not is_logical_kanban_enabled():
        return False
    return get_registry().is_enabled(CAUSAL_FEATURE_NAME)

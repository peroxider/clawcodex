"""Downstream permission extensions.

Registers the ``bypassPermissions → dontAsk`` cycle step so Shift+Tab
cycles through the downstream ``dontAsk`` mode after ``bypassPermissions``.

Auto Mode: LLM classifier + danger detector + cycle validation integration.
"""

from __future__ import annotations

from .classifier import (
    ClassificationCache,
    LLMClassificationResult,
    auto_mode_classify_with_llm,
    get_cache,
    llm_classify_tool_call,
)
from .danger_detector import detect_dangerous_tool_call
from .cycle import can_cycle_to_auto, get_auto_mode_availability_reason


def install_permission_extensions() -> None:
    """Register downstream permission cycle steps and auto mode classifier.

    Idempotent — safe to call more than once.
    """
    from src.permissions.cycle import register_cycle_step

    register_cycle_step("bypassPermissions", "dontAsk", after="bypassPermissions")

    try:
        from clawcodex_ext.agent.auto_mode_runner import install_llm_auto_mode_classifier

        success = install_llm_auto_mode_classifier(use_llm_for_uncertain=True)
        if not success:
            import logging

            log = logging.getLogger(__name__)
            log.warning("Auto mode LLM classifier installation returned False")
    except Exception as e:
        import logging
        import traceback

        log = logging.getLogger(__name__)
        log.warning("Auto mode LLM classifier not installed: %s", e)
        log.warning("Traceback: %s", traceback.format_exc())


__all__ = [
    "install_permission_extensions",
    "ClassificationCache",
    "LLMClassificationResult",
    "auto_mode_classify_with_llm",
    "get_cache",
    "llm_classify_tool_call",
    "detect_dangerous_tool_call",
    "can_cycle_to_auto",
    "get_auto_mode_availability_reason",
]

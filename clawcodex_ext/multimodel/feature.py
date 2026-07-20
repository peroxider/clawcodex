"""Single feature-gate chokepoint for F-157 multi-model dispatch."""

from __future__ import annotations


def is_multimodel_enabled() -> bool:
    from clawcodex_ext.feature_gate import get_registry

    return get_registry().is_enabled("MULTIMODEL")


def require_multimodel_enabled() -> None:
    if not is_multimodel_enabled():
        raise RuntimeError(
            "Multi-model mode is disabled. Enable it with "
            "`clawcodex-dev feature set MULTIMODEL --on`."
        )


def disabled_message() -> str:
    return (
        "Multi-model mode is disabled. Enable it with "
        "`clawcodex-dev feature set MULTIMODEL --on`."
    )


__all__ = ["disabled_message", "is_multimodel_enabled", "require_multimodel_enabled"]

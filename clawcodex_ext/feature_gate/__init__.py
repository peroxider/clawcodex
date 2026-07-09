"""Feature Gate — runtime feature toggle system.

Exports the singleton :class:`FeatureRegistry` and convenience helpers.

Usage::

    from clawcodex_ext.feature_gate import get_registry, FeatureFlag

    reg = get_registry()
    reg.register(FeatureFlag("my_feature", default=True))
    assert reg.is_enabled("my_feature")
"""

from __future__ import annotations

from .config import ConfigStore
from .decorators import (
    feature_gated,
    feature_gated_class,
    guarded_call,
    guarded_is_enabled,
)
from .registry import FeatureRegistry
from .types import FeatureFlag

# ---------------------------------------------------------------------------
# Singleton — defined BEFORE .cli import so that cli.py can import get_registry
# ---------------------------------------------------------------------------

_instance: FeatureRegistry | None = None


def get_registry() -> FeatureRegistry:
    """Return the process-global :class:`FeatureRegistry` singleton.

    Lazily creates the instance on first call.
    """
    global _instance
    if _instance is None:
        _instance = FeatureRegistry()
    return _instance


def reset_registry() -> FeatureRegistry:
    """Reset the singleton and return a fresh instance.

    Intended for testing only.
    """
    global _instance
    _instance = FeatureRegistry()
    return _instance


# Lazy import of CLI handler to avoid circular imports at module scope.
# The CLI handler imports get_registry(), which is now defined above.
def __getattr__(name: str):
    if name == "run_feature_command":
        from .cli import run_feature_command as _rfc

        globals()["run_feature_command"] = _rfc
        return _rfc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Default feature registration
# ---------------------------------------------------------------------------

# Core feature flags that ship with ClawCodex.
# These mirror the CCB FEATURE_* compile-time macros at runtime.
_DEFAULT_FLAGS: list[FeatureFlag] = [
    # --- Agent / orchestrator features ---
    FeatureFlag(
        name="AGENTIC_MODE",
        default=False,
        description="Enable agentic multi-step planning mode (F-70 plugin dependent)",
        deps=[],
    ),
    FeatureFlag(
        name="ORCHESTRATOR_LOOP",
        default=False,
        description="Enable the autonomous orchestrator agent loop",
        deps=["AGENTIC_MODE"],
    ),
    FeatureFlag(
        name="HOOK_PRE_LLM",
        default=True,
        description="Enable pre-LLM agent loop hooks (F-102 prerequisite)",
    ),
    FeatureFlag(
        name="HOOK_POST_LLM",
        default=True,
        description="Enable post-LLM agent loop hooks",
    ),
    # --- Plugin system ---
    FeatureFlag(
        name="PLUGIN_SYSTEM",
        default=False,
        description="Enable the F-70 plugin loading system",
    ),
    # --- Tool gap bridging ---
    FeatureFlag(
        name="TOOL_GAP_BRIDGE",
        default=False,
        description="Enable automatic tool-gap bridging for missing capabilities",
        deps=["PLUGIN_SYSTEM"],
    ),
    # --- Multi-API provider ---
    FeatureFlag(
        name="MULTI_API_PROVIDER",
        default=False,
        description="Enable multi-API provider routing (F-72)",
    ),
    # --- Sandbox ---
    FeatureFlag(
        name="SANDBOX_EXECUTION",
        default=False,
        description="Enable sandboxed command execution (F-74)",
    ),
    # --- Voice mode ---
    FeatureFlag(
        name="VOICE_MODE",
        default=False,
        description="Enable voice input/output mode (F-64)",
    ),
    # --- Budget mode ---
    FeatureFlag(
        name="BUDGET_MODE",
        default=False,
        description="Enable cost-aware budget-limited agent runs (F-69)",
    ),
    # --- Goal mode ---
    FeatureFlag(
        name="goals",
        default=True,
        description="Enable upstream-compatible /goal mode",
    ),
    # --- ACP protocol ---
    FeatureFlag(
        name="ACP_PROTOCOL",
        default=False,
        description="Enable ACP (Agent Communication Protocol) for inter-agent messaging (F-66)",
    ),
    # --- Native modules ---
    FeatureFlag(
        name="NATIVE_MODULES",
        default=False,
        description="Enable loading of compiled native extension modules (F-81)",
    ),
    # --- Remote control ---
    FeatureFlag(
        name="REMOTE_CONTROL",
        default=False,
        description="Enable remote CLI control via TCP/WebSocket (F-82)",
    ),
    # --- Daemon subsystem (F-84) ---
    # Defaults to False; enabling it registers the ``clawcodex-dev daemon``
    # CLI surface and allows supervisor + worker processes.
    FeatureFlag(
        name="DAEMON",
        default=False,
        description=(
            "Enable the long-running daemon supervisor that owns "
            "task_server / cron workers (F-84)"
        ),
    ),
    FeatureFlag(
        name="BRIDGE_MODE",
        default=False,
        description=(
            "Enable the multi-session bridge subsystem "
            "(F-84 P84-G, F-82 dependency)"
        ),
    ),
    # --- CI/CD ---
    FeatureFlag(
        name="CICD_MODE",
        default=False,
        description="Enable CI/CD-optimized mode (batch processing, no TTY) (F-73)",
    ),
    FeatureFlag(
        name="ULTRAPLAN_LLM_PLANNER",
        default=True,
        description="Enable LLM-backed /ultraplan plan generation (F-87)",
    ),
    FeatureFlag(
        name="ULTRAPLAN_REMOTE",
        default=False,
        description="Enable /ultraplan remote CCR execution (F-87)",
    ),
    FeatureFlag(
        name="ULTRAPLAN_RAINBOW",
        default=True,
        description="Enable /ultraplan trigger highlighting in prompt input (F-87)",
    ),
    FeatureFlag(
        name="KAIROS",
        default=False,
        description="Enable Kairos tick scheduling primitives (F-89)",
    ),
    FeatureFlag(
        name="PROACTIVE",
        default=False,
        description="Enable proactive tick-driven autonomous mode (F-89)",
    ),
    FeatureFlag(
        name="logical_kanban",
        default=False,
        description=(
            "Enable Logical Kanban propose/validate/commit gating for "
            "todo and task status mutations (F-126)"
        ),
    ),
    FeatureFlag(
        name="LKB_CAUSAL",
        default=False,
        description=(
            "Enable the F-141 causal verification layer (CAP-compatible "
            "in-process engine) that augments symbolic validation runs "
            "with a causal_weight, is_significant flag, and mechanism tag."
        ),
        deps=["logical_kanban"],
    ),
    FeatureFlag(
        name="LKB_LLM_FACTS",
        default=False,
        description=(
            "Enable F-143 runtime LLM-derived facts for Logical Kanban, "
            "allowing the agent loop to contribute facts at validation time."
        ),
        deps=["logical_kanban"],
    ),
]


def register_defaults(registry: FeatureRegistry | None = None) -> None:
    """Register all built-in default feature flags.

    Safe to call multiple times — duplicate registrations are no-ops.
    """
    reg = registry or get_registry()
    for flag in _DEFAULT_FLAGS:
        if flag.name not in reg._features:
            reg.register(flag)


# ---------------------------------------------------------------------------
# Eager bootstrap: register defaults so the singleton is ready on first use.
# ---------------------------------------------------------------------------

register_defaults()


# Re-export everything at package level for convenience.
__all__ = [
    "ConfigStore",
    "FeatureFlag",
    "FeatureRegistry",
    "feature_gated",
    "feature_gated_class",
    "guarded_call",
    "guarded_is_enabled",
    "get_registry",
    "register_defaults",
    "reset_registry",
    "run_feature_command",
]

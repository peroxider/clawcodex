"""Downstream ClawCodex extension layer."""

# Eagerly register downstream extensions that must be in place before any
# src/ code runs.  These registrations are idempotent.
#
# NOTE: ``_init_nested_transcript`` is intentionally NOT called here.
# Calling it would import ``src.agent.transcript`` while ``src.tool_system``
# is mid-load (via the ``src.permissions.cycle`` → ``clawcodex_ext`` lazy
# proxy path), which in turn imports ``src.agent.agent_tool_utils``,
# which imports ``src.tool_system.build_tool`` — completing the cycle and
# raising ``ImportError: cannot import name 'Tool' from partially
# initialized module 'src.tool_system.build_tool'`` at import time.
# The transcript resolver registration is therefore invoked lazily
# from the canonical per-process bootstrap — ``src/init.py:init()``,
# which is the documented "called from multiple entry points
# (each one calls it once; memoize handles dedup)" hook used by
# REPL, headless, bridge, TUI, SDK, and the CLI. By the time
# ``init()`` runs, every ``src/`` module is fully loaded, so the
# ``ensure_nested_transcript_initialized()`` wrapper below can
# safely import and register the resolver without re-triggering
# the partial-init cycle described above.
#
# ``clawcodex_ext/cli/main.py`` retains an explicit
# ``ensure_nested_transcript_initialized()`` call as a defensive
# double-check: the helper is flag-guarded, so the second
# registration is a no-op, but having the call there means the
# resolver is guaranteed to be live before the first transcript
# write even if a future caller forgets ``init()``.
from clawcodex_ext.permissions import install_permission_extensions  # noqa: F401
from clawcodex_ext.memory.scope_aware_prompt import install_memory_extension  # noqa: F401
from clawcodex_ext.providers import (  # noqa: F401 — registers model discovery hooks
    _codex_api_discovery,
)
from clawcodex_ext.providers.patches import install as _install_provider_patches  # noqa: F401
from clawcodex_ext.models import (  # noqa: F401 — registers extra model configs into MODEL_CONFIGS
    register_model_config,
)
from clawcodex_ext.agent.transcript import init as _init_nested_transcript  # noqa: F401
from clawcodex_ext.orchestrator import install_stale_registry_patch  # noqa: F401

install_permission_extensions()
install_memory_extension()
_install_provider_patches()
install_stale_registry_patch()

# Flag-guarded lazy initializer. Idempotent: a second call is a no-op
# so callers (CLI main, REPL launcher, tests) can invoke it freely
# without worrying about double-registration of the path resolver.
_nested_transcript_initialized: bool = False


def ensure_nested_transcript_initialized() -> None:
    """Register the nested-session transcript path resolver.

    Safe to call multiple times. Must be called from a context where
    ``src/`` modules are fully loaded (e.g. the CLI entry point or
    the REPL launcher) — invoking it during ``clawcodex_ext`` package
    import would re-trigger the circular import that this lazy
    wrapper exists to avoid.
    """
    global _nested_transcript_initialized
    if _nested_transcript_initialized:
        return
    _init_nested_transcript()
    _nested_transcript_initialized = True


__all__ = [
    "ensure_nested_transcript_initialized",
]

"""Passive memory plugin -- zero-intrusion integration via query lifecycle hooks.

After installation, two hooks are registered:
  - on_query_start: runs memory recall before query() starts and injects into system_prompt
  - on_query_end:   runs memory capture after query() ends, writing asynchronously to the MCP backend

All business logic is contained under clawcodex_ext/latent_memory/; the main project query pipeline
does not need to be aware of the memory system. Uninstalling the plugin (not calling install) makes
the memory system fully silent.

Usage::

    from clawcodex_ext.latent_memory.plugin import install_passive_memory_plugin
    install_passive_memory_plugin()  # called in ensure_eager_extensions_installed
"""

from __future__ import annotations

import atexit
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Whether the plugin is installed (idempotency guard, only prevents duplicate atexit registration)
_installed: bool = False

# The currently active PassiveMemoryRun, staged per query instance.
# query() is synchronous consumption (usually only one active query at a time per process),
# so using id(params) as the key is enough to distinguish concurrent scenarios.
_active_runs: dict[int, Any] = {}


def install_passive_memory_plugin() -> None:
    """Register passive-memory query lifecycle hooks and MCP arg interceptors.

    Idempotent — hooks and interceptors self-deduplicate.
    """
    global _installed

    from clawcodex_ext.query.hook_registry import register_loop_hook

    register_loop_hook(
        "passive_memory_recall",
        _on_query_start,
        "on_query_start",
        priority=-10,  # run early so later hooks see the full prompt
    )
    register_loop_hook(
        "passive_memory_capture",
        _on_query_end,
        "on_query_end",
        priority=10,  # run a bit later, after other hooks have processed
    )

    # Register MCP arg interceptor for user_id injection.
    # This keeps the MCP tool wrappers free of memory-specific imports.
    from clawcodex_ext.services.mcp.call_bridge import register_mcp_arg_interceptor

    register_mcp_arg_interceptor(_inject_user_id_interceptor)

    # Flush the write queue on process exit (daemon thread fallback) -- registered only once
    if not _installed:
        _installed = True
        atexit.register(_flush_on_exit)

    logger.debug(
        "Passive memory plugin installed "
        "(on_query_start + on_query_end hooks + MCP arg interceptor)"
    )


async def _on_query_start(params: Any) -> Any:
    """on_query_start hook: run memory recall and modify params.system_prompt.

    Returns the modified params (per the hook_registry contract, the return value replaces the
    passed-in args). Any exception is swallowed internally and never affects the main query flow.
    """
    try:
        from clawcodex_ext.latent_memory.passive import prepare_top_level_run

        messages = getattr(params, "messages", None) or []
        system_prompt = getattr(params, "system_prompt", None) or ""
        tool_context = getattr(params, "tool_use_context", None)

        new_prompt, run = await prepare_top_level_run(
            list(messages),
            system_prompt,
            tool_context,
        )

        # Stage the run for use by on_query_end
        _active_runs[id(params)] = run

        # Modify system_prompt (recall injection)
        if new_prompt is not system_prompt:
            params.system_prompt = new_prompt

        return params
    except Exception:
        logger.debug("passive_memory_recall hook failed", exc_info=True)
        return params


def _on_query_end(params: Any, terminal_holder: Any) -> None:
    """on_query_end hook: run memory capture.

    Gets the termination reason from terminal_holder.value and checks the last assistant
    message's stop_reason to decide whether to write.
    Any exception is swallowed internally.
    """
    try:
        from clawcodex_ext.latent_memory.passive import complete_top_level_run
        from clawcodex_ext.latent_memory.passive.lifecycle import is_completed_assistant_message

        run = _active_runs.pop(id(params), None)
        if run is None:
            return

        messages = getattr(params, "messages", None) or []
        terminal = getattr(terminal_holder, "value", None) if terminal_holder else None
        terminal_reason = getattr(terminal, "reason", None) or "incomplete"

        # Two-level check:
        # 1. Terminal.reason must be a normal end (not error/abort/max_turns)
        # 2. The last assistant message's stop_reason must be a completion one
        #    (excluding truncation cases like max_tokens)
        completed = False
        if terminal_reason in ("end_turn", "stop", "completed"):
            # Check the last assistant message
            from clawcodex_ext.types.messages import AssistantMessage

            last_assistant = None
            for msg in reversed(messages):
                if isinstance(msg, AssistantMessage):
                    last_assistant = msg
                    break
            if last_assistant is not None:
                completed = is_completed_assistant_message(last_assistant)
            else:
                completed = True  # default to complete when there is no assistant message

        complete_top_level_run(
            run,
            list(messages),
            terminal_reason="completed" if completed else "incomplete",
        )
    except Exception:
        logger.debug("passive_memory_capture hook failed", exc_info=True)


def _inject_user_id_interceptor(
    args: dict[str, Any],
    *,
    server_name: str,
    tool_name: str,
    input_schema: dict[str, Any] | None = None,
    context: Any = None,
) -> dict[str, Any]:
    """MCP arg interceptor: inject passive-memory project user_id.

    Registered via ``register_mcp_arg_interceptor`` so the MCP tool wrappers
    (``tools/mcp.py`` and ``tool_wrapper.py``) remain free of memory imports.
    """
    props = (input_schema or {}).get("properties") or {}
    accepts_user_id = None if input_schema is None else "user_id" in props
    from clawcodex_ext.latent_memory.passive.mcp_scope import inject_project_user_id

    return inject_project_user_id(
        args,
        context,
        server_name=server_name,
        tool_name=tool_name,
        accepts_user_id=accepts_user_id,
    )


def _flush_on_exit() -> None:
    """Flush pending writes on process exit."""
    try:
        from clawcodex_ext.latent_memory.passive import flush_pending_writes

        flush_pending_writes(10.0)
    except Exception:
        pass

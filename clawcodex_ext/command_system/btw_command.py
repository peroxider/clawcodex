"""/btw side-question command implementation.

Mirrors ``typescript/src/commands/btw/btw.tsx``.

Provides a context-zero-pollution side channel for users to ask quick
questions without interrupting the main agent work stream.
"""

from __future__ import annotations

import logging
from typing import Any

from clawcodex_ext.agent.side_question import run_side_question
from clawcodex_ext.agent.forked_agent import CacheSafeParams, get_last_cache_safe_params
from clawcodex_ext.command_system.types import (
    CommandContext,
    InteractiveCommand,
    InteractiveOutcome,
)

__all__ = ["BTW_COMMAND", "btw_command_run", "BtwCommand"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command implementation
# ---------------------------------------------------------------------------

async def btw_command_run(args: str, context: CommandContext) -> InteractiveOutcome:
    """Handle /btw command.

    Args:
        args: User's question text (everything after ``/btw``).
        context: Command execution context.

    Returns:
        InteractiveOutcome with the answer text or usage help.
    """
    question = args.strip()
    if not question:
        return InteractiveOutcome(
            message="Usage: /btw <your question> —— 在不中断工作会话的前提下快速询问",
            display="user",
        )

    # Build cache-safe params (cached or fallback)
    params = await _build_cache_safe_params(context)
    if params is None:
        return InteractiveOutcome(
            message="⚠️ 无法构建侧边询问上下文。请在主会话中直接提问。",
            display="user",
        )

    # Execute side question
    try:
        result = await run_side_question(question, params)
    except Exception as e:
        logger.exception("Side question failed")
        return InteractiveOutcome(
            message=f"⚠️ 侧边询问失败: {e}",
            display="user",
        )

    if result.response:
        return InteractiveOutcome(
            message=f"💡 {result.response}",
            display="user",
        )
    return InteractiveOutcome(
        message="⚠️ 侧边询问未能获取回答。请在主会话中直接提问。",
        display="user",
    )


# ---------------------------------------------------------------------------
# CacheSafeParams builder
# ---------------------------------------------------------------------------

async def _build_cache_safe_params(
    context: CommandContext,
) -> CacheSafeParams | None:
    """Build CacheSafeParams for the side question.

    Preferred path: read from the global cache populated by the main loop
    after each turn (prompt-cache hit).

    Fallback path: rebuild from scratch (prompt-cache miss, more expensive
    but functionally complete).
    """
    saved = get_last_cache_safe_params()
    if saved is not None:
        return saved

    # Fallback: rebuild from scratch
    tool_context = getattr(context, "tool_context", None)
    if tool_context is None:
        logger.warning("btw: no tool_context available for fallback rebuild")
        return None

    # Rebuild system prompt
    system_prompt = ""
    try:
        from clawcodex_ext.context_system.prompt_assembly import build_full_system_prompt

        system_prompt = build_full_system_prompt(
            cwd=str(context.cwd),
            tools=getattr(tool_context.options, "tools", None) if tool_context.options else None,
        )
    except Exception:
        logger.exception("btw: failed to rebuild system prompt")

    # Rebuild user / system context
    user_context: dict[str, str] | None = None
    system_context: dict[str, str] | None = None
    try:
        from clawcodex_ext.context_system.prompt_assembly import (
            get_system_context,
            get_user_context,
        )

        user_context = await get_user_context(cwd=str(context.cwd))
        system_context = await get_system_context(cwd=str(context.cwd))
    except Exception:
        logger.exception("btw: failed to rebuild context")

    # Fork context messages: use conversation messages if available
    fork_context_messages: list[Any] = []
    conversation = getattr(context, "conversation", None)
    if conversation is not None and hasattr(conversation, "messages"):
        fork_context_messages = list(conversation.messages)

    return CacheSafeParams(
        system_prompt=system_prompt,
        user_context=user_context,
        system_context=system_context,
        tool_use_context=tool_context,
        fork_context_messages=fork_context_messages,
    )


# ---------------------------------------------------------------------------
# Command definitions
# ---------------------------------------------------------------------------

class BtwCommand(InteractiveCommand):
    """/btw — side question without polluting the main conversation."""

    async def run(self, args: str, context: CommandContext) -> InteractiveOutcome:
        return await btw_command_run(args, context)


BTW_COMMAND = BtwCommand(
    name="btw",
    description="在不中断工作会话的前提下快速询问（侧边问题）",
    argument_hint="<your question>",
)

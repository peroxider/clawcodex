"""The /recap slash command."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.away_summary.config import load_away_summary_config
from clawcodex_ext.away_summary.messages import format_away_summary_for_display
from clawcodex_ext.away_summary.service import AwaySummaryService
from src.command_system.types import LocalCommand, LocalCommandResult


def build_recap_command() -> LocalCommand:
    command = LocalCommand(
        name="recap",
        description="Generate a short recap of the current session",
        argument_hint="",
        supports_non_interactive=False,
        run_in_thread=True,
        is_enabled=lambda: load_away_summary_config().recap_command_enabled,
    )
    command.set_call(_recap_call)
    return command


def _recap_call(args: str, context: Any) -> LocalCommandResult:
    del args
    provider = getattr(context, "provider", None)
    runtime = getattr(context, "runtime_context", None)
    if provider is None and runtime is not None:
        provider = getattr(runtime, "provider", None)
    if provider is None:
        return LocalCommandResult(type="text", value="Recap requires an active provider.")

    model = getattr(provider, "model", None)
    if runtime is not None:
        model = getattr(getattr(runtime, "options", None), "model", None) or model
    session = getattr(context, "session", None)
    if session is None and runtime is not None:
        session = getattr(runtime, "session", None)
    conversation = getattr(context, "conversation", None)
    if conversation is None:
        return LocalCommandResult(type="text", value="No conversation is available to recap.")

    cfg = load_away_summary_config(cwd=getattr(context, "cwd", None))
    try:
        result = AwaySummaryService(
            conversation=conversation,
            provider=provider,
            model=model,
            session=session,
            config=cfg,
        ).generate(trigger="manual")
    except Exception as exc:
        return LocalCommandResult(type="text", value=f"Recap failed: {exc}")

    if not result.generated:
        return LocalCommandResult(type="text", value=result.reason)
    return LocalCommandResult(
        type="text",
        value=format_away_summary_for_display(result.summary),
    )

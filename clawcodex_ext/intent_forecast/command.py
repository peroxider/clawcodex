"""The /forecast slash command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawcodex_ext.intent_forecast.config import load_intent_forecast_config
from clawcodex_ext.intent_forecast.learning import record_feedback
from clawcodex_ext.intent_forecast.messages import format_forecast_for_display, parse_selection
from clawcodex_ext.intent_forecast.settings_io import update_intent_forecast_settings
from clawcodex_ext.intent_forecast.service import IntentForecastService
from src.command_system.types import LocalCommand, LocalCommandResult

_LAST_RESULTS: dict[str, Any] = {}


def build_forecast_command() -> LocalCommand:
    command = LocalCommand(
        name="forecast",
        description="Predict likely next user tasks",
        argument_hint="[run|status|accept <n>|dismiss|on|off]",
        supports_non_interactive=False,
        run_in_thread=True,
        is_enabled=lambda: True,
    )
    command.set_call(_forecast_call)
    return command


def _forecast_call(args: str, context: Any) -> LocalCommandResult:
    parts = args.strip().split()
    action = parts[0].lower() if parts else "run"
    cwd = Path(str(getattr(context, "cwd", None) or getattr(context, "workspace_root", None) or Path.cwd()))
    key = str(cwd)

    if action == "status":
        cfg = load_intent_forecast_config(cwd=cwd)
        last = _LAST_RESULTS.get(key)
        return LocalCommandResult(
            type="text",
            value=(
                "Forecast\n"
                f"enabled={cfg.enabled} auto_display={cfg.auto_display} idle_seconds={cfg.idle_seconds}\n"
                f"last_suggestions={len(last.suggestions) if last else 0}"
            ),
        )
    if action in {"on", "off"}:
        enabled = action == "on"
        update_intent_forecast_settings({"enabled": enabled})
        return LocalCommandResult(
            type="text",
            value=f"Forecast {'enabled' if enabled else 'disabled'}.",
        )
    if action == "dismiss":
        controller = getattr(context, "intent_forecast_controller", None)
        if controller is not None:
            controller.dismiss()
            return LocalCommandResult(type="text", value="Forecast dismissed.")
        result = _LAST_RESULTS.pop(key, None)
        cfg = load_intent_forecast_config(cwd=cwd)
        if cfg.feedback_enabled:
            record_feedback("dismissed", cwd=cwd, fingerprint=getattr(result, "fingerprint", ""))
        return LocalCommandResult(type="text", value="Forecast dismissed.")
    if action == "accept":
        controller = getattr(context, "intent_forecast_controller", None)
        if controller is not None and getattr(controller, "last_result", None) is not None:
            selection = parts[1] if len(parts) > 1 else "1"
            result = controller.last_result
            suggestion = parse_selection(selection, result.suggestions)
            if suggestion is None:
                return LocalCommandResult(type="text", value=f"No forecast suggestion matches {selection!r}.")
            cfg = load_intent_forecast_config(cwd=cwd)
            if cfg.feedback_enabled:
                record_feedback("accepted", suggestion=suggestion, cwd=cwd, fingerprint=result.fingerprint)
            if hasattr(controller, "_last_result"):
                try:
                    controller._last_result = None
                except Exception:
                    pass
            return LocalCommandResult(type="prompt", value=suggestion.prompt)
        result = _LAST_RESULTS.get(key)
        if result is None:
            return LocalCommandResult(type="text", value="No forecast suggestion is available to accept.")
        selection = parts[1] if len(parts) > 1 else "1"
        suggestion = parse_selection(selection, result.suggestions)
        if suggestion is None:
            return LocalCommandResult(type="text", value=f"No forecast suggestion matches {selection!r}.")
        cfg = load_intent_forecast_config(cwd=cwd)
        if cfg.feedback_enabled:
            record_feedback("accepted", suggestion=suggestion, cwd=cwd, fingerprint=result.fingerprint)
        return LocalCommandResult(type="prompt", value=suggestion.prompt)
    if action != "run":
        return LocalCommandResult(type="text", value="Usage: /forecast [run|status|accept <n>|dismiss|on|off]")

    provider, model, session, conversation = _resolve_runtime(context)
    cfg = load_intent_forecast_config(cwd=cwd)
    try:
        result = IntentForecastService(
            conversation=conversation,
            provider=provider,
            model=model,
            workspace_root=cwd,
            config=cfg,
        ).generate(trigger="manual", force=True)
    except Exception as exc:
        return LocalCommandResult(type="text", value=f"Forecast failed: {exc}")
    if result.generated:
        _LAST_RESULTS[key] = result
    return LocalCommandResult(type="text", value=format_forecast_for_display(result))


def _resolve_runtime(context: Any) -> tuple[Any | None, str | None, Any | None, Any | None]:
    runtime = getattr(context, "runtime_context", None)
    provider = getattr(context, "provider", None) or getattr(runtime, "provider", None)
    model = getattr(provider, "model", None)
    if runtime is not None:
        model = getattr(getattr(runtime, "options", None), "model", None) or model
    session = getattr(context, "session", None) or getattr(runtime, "session", None)
    conversation = getattr(context, "conversation", None) or getattr(session, "conversation", None)
    return provider, model, session, conversation

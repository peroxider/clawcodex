"""Runtime slash commands for provider/model switching.

Both ``/provider`` and ``/model`` share a unified surface that mirrors the
CLI subcommands in :mod:`clawcodex_ext.cli.provider_cmd` and
:mod:`clawcodex_ext.cli.model_cmd`:

* ``/provider`` (no args)            — show current provider + list all
* ``/provider <NAME>``               — switch to ``<NAME>``
* ``/model``    (no args)            — show current provider/model + list all
* ``/model <NAME> [--provider P]``   — switch to ``<NAME>`` (inferred or
  explicit provider)

The legacy ``list`` / ``current`` / ``use <NAME>`` subcommand spellings are
no longer recognised — they were folded into the unified form so the
slash command behaves identically in REPL and TUI.
"""

from __future__ import annotations

from typing import Any

from clawcodex_ext.cli.model_cmd.registry import ModelRegistry
from clawcodex_ext.cli.model_cmd.store import ModelStore
from clawcodex_ext.cli.model_cmd.errors import UnknownModelError, ProviderMismatchError
from clawcodex_ext.cli.provider_cmd.commands import format_provider_list
from clawcodex_ext.cli.provider_cmd.errors import UnknownProviderError
from src.command_system.types import LocalCommand, LocalCommandResult


def register_runtime_commands(registry: Any | None = None) -> None:
    from src.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    for command in (_provider_command(), _model_command()):
        reg.register(command)


def _format_configured_model_list() -> str:
    """Show models only for providers with API keys in config.

    Reads ``~/.clawcodex/config.json`` and filters the full model list
    to only those providers the user has actually configured.  Falls
    back to all known providers when no config is available (e.g. in
    tests or CI).

    For each configured provider, the displayed model list is the *union*
    of:
    1. Models known to the built-in ``ModelRegistry`` (``available_models``)
    2. Models recorded in the config's ``models`` list (user's custom /
       previously-used models outside the built-in registry)
    """
    registry = ModelRegistry()
    try:
        from src.config import get_provider_config

        configured = [
            name
            for name in registry.provider_names()
            if get_provider_config(name)
        ]
        # Also include providers that exist only in config but aren't
        # known to ModelRegistry (e.g. completely custom providers).
        import json, os
        from src.config import get_global_config_path

        gp = get_global_config_path()
        if gp and gp.exists():
            raw = json.loads(gp.read_text())
            for p in (raw.get("providers") or {}):
                if p not in configured and p not in registry.provider_names():
                    configured.append(p)
    except Exception:
        configured = []

    if not configured:
        # No config or all empty — fall back to showing all known providers
        # so the user always sees something.
        configured = list(registry.provider_names())

    lines = ["Models:"]
    for provider_name in configured:
        try:
            registry.validate_provider(provider_name)
        except Exception:
            pass  # Custom provider not in registry — still show it.

        reg_models: list[str] = []
        try:
            reg_models = list(registry.available_models(provider_name) or [])
        except Exception:
            pass

        # Merge in models from config's ``models`` list
        cfg_models: list[str] = []
        try:
            from src.config import get_provider_config

            pc = get_provider_config(provider_name)
            if pc:
                cfg_models = list(pc.get("models", []) or [])
        except Exception:
            pass

        all_models = list(dict.fromkeys(reg_models + cfg_models))  # dedup, preserve order

        lines.append(f"  {provider_name}:")
        for model in all_models:
            marker = " *" if model == registry.provider_default_model(provider_name) else ""
            lines.append(f"    {model}{marker}")
    return "\n".join(lines)


def _provider_command() -> LocalCommand:
    command = LocalCommand(
        name="provider",
        description="Show current provider (and available list), or switch to a named provider",
        argument_hint="[NAME]",
    )
    command.set_call(_provider_call)
    return command


def _model_command() -> LocalCommand:
    command = LocalCommand(
        name="model",
        description="Show current model (and available list), or switch to a named model",
        argument_hint="[NAME [--provider NAME]]",
    )
    command.set_call(_model_call)
    return command


def _provider_call(args: str, context: Any) -> LocalCommandResult:
    tokens = args.split()

    if not tokens:
        current = _format_runtime_current(context)
        lines = [current, "", format_provider_list()] if current else [format_provider_list()]
        return _text("\n".join(lines))

    provider = tokens[0]
    runtime = _runtime(context)
    if runtime is None:
        return _text("Runtime context is not available — cannot switch provider.")

    warnings: list[str] = []
    try:
        ModelStore().set_default_provider(provider)
    except UnknownProviderError:
        warnings.append(f"Warning: unknown provider '{provider}' — proceeding anyway")
        from src.config import set_default_provider as _set_dp
        _set_dp(provider)

    runtime.swap_provider(provider)
    _sync_context(context, runtime)

    lines = [f"Provider switched to: {provider}"]
    lines.extend(warnings)
    lines.append("")
    current = _format_runtime_current(context)
    if current is not None:
        lines.append(current)
    return _text("\n".join(lines))


def _model_call(args: str, context: Any) -> LocalCommandResult:
    tokens = args.split()

    if not tokens:
        current = _format_runtime_current(context)
        lines = [current, "", _format_configured_model_list()] if current else [_format_configured_model_list()]
        return _text("\n".join(lines))

    try:
        model, provider = _parse_model_args(tokens)
    except ValueError as exc:
        return _text(f"usage: /model [NAME [--provider NAME]]\n{exc}")

    warnings: list[str] = []
    registry = ModelRegistry()

    # ---- Resolve provider ----
    if provider is None:
        # Use current runtime provider instead of infer_provider_for_model,
        # so /model switches models under the user's current provider rather
        # than silently jumping to whichever provider "owns" the model name.
        provider = _current_provider_name(context) or "anthropic"

    # ---- Check if the model is known for this provider ----
    model_known = True
    try:
        registry.validate_model(model, provider)
    except UnknownModelError:
        model_known = False
        warnings.append(f"Warning: unknown model '{model}' — proceeding anyway")
    except ProviderMismatchError:
        model_known = False
        warnings.append(
            f"Warning: model '{model}' not listed for provider '{provider}' "
            f"— proceeding anyway"
        )

    # ---- Persist unknown model to config so it's available next session ----
    if not model_known:
        try:
            ModelStore(registry).set_default_provider(provider)
        except Exception:
            from src.config import set_default_provider as _set_dp

            _set_dp(provider)
        try:
            ModelStore(registry).set_default_model(provider, model)
        except Exception:
            from src.config import get_provider_config, set_api_key

            current_cfg = get_provider_config(provider)
            base_url = current_cfg.get("base_url") if current_cfg else None
            if not base_url:
                try:
                    from src.providers import PROVIDER_INFO

                    base_url = PROVIDER_INFO[provider]["default_base_url"]
                except (KeyError, ImportError):
                    base_url = ""
            set_api_key(
                provider,
                api_key=(current_cfg or {}).get("api_key", ""),
                base_url=base_url,
                default_model=model,
            )

    # ---- Runtime switch (always, regardless of persistence) ----
    runtime = _runtime(context)
    runtime.swap_provider(provider, model)  # type: ignore[union-attr]
    _sync_context(context, runtime)
    lines = [f"Model switched to: {model} (provider: {provider})"]
    lines.extend(warnings)
    lines.append("")
    current = _format_runtime_current(context)
    if current is not None:
        lines.append(current)
    return _text("\n".join(lines))


def _parse_provider_flag(tokens: list[str]) -> str | None:
    provider = None
    idx = 0
    while idx < len(tokens):
        if tokens[idx] == "--provider" and idx + 1 < len(tokens):
            provider = tokens[idx + 1]
            idx += 2
            continue
        raise ValueError(f"Unknown argument: {tokens[idx]}")
    return provider


def _parse_model_args(tokens: list[str]) -> tuple[str, str | None]:
    model = tokens[0]
    provider = _parse_provider_flag(tokens[1:])
    return model, provider


def _runtime(context: Any) -> Any | None:
    """Return the runtime context, or *None* if not available.

    Callers that only *display* current state (no-arg ``/model`` /
    ``/provider``) should tolerate *None* and omit the current-state
    line.  Callers that *mutate* state (``/model <name>``) raise
    ``ValueError`` themselves when they need ``swap_provider``.
    """
    return getattr(context, "runtime_context", None)


def _current_provider_name(context: Any) -> str | None:
    """Return the current provider name from the runtime context, or *None*.

    Used as the fallback provider when ``infer_provider_for_model`` cannot
    identify a model — avoids resetting to a hardcoded default that may
    differ from the user's actual provider.
    """
    runtime = _runtime(context)
    if runtime is not None:
        return getattr(runtime, "provider_name", None)
    # Fallback: try the command context's own provider name.
    return getattr(context, "provider_name", None) or getattr(
        getattr(context, "provider", None), "provider_name", None
    )


def _sync_context(context: Any, runtime: Any) -> None:
    context.provider = runtime.provider
    context.tool_registry = runtime.tool_registry
    context.tool_context = runtime.tool_context


def _format_runtime_current(context: Any, *, prefix: str | None = None) -> str | None:
    """Return a ``"provider: …\nmodel: …"`` snippet, or *None* when the
    runtime context is missing (callers that tolerate absence should
    simply omit the block)."""
    runtime = _runtime(context)
    if runtime is None:
        return None
    lines = []
    if prefix:
        lines.append(prefix)
    lines.extend(
        [
            f"provider: {runtime.provider_name}",
            f"model: {getattr(runtime.provider, 'model', runtime.options.model)}",
        ]
    )
    return "\n".join(lines)


def _text(value: str) -> LocalCommandResult:
    return LocalCommandResult(type="text", value=value)

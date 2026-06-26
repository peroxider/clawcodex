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

import re
from typing import Any

from clawcodex_ext.cli.model_cmd.registry import ModelRegistry
from clawcodex_ext.cli.model_cmd.store import ModelStore
from clawcodex_ext.cli.model_cmd.errors import UnknownModelError, ProviderMismatchError
from clawcodex_ext.cli.provider_cmd.commands import format_provider_list
from clawcodex_ext.cli.provider_cmd.errors import UnknownProviderError
from src.command_system.types import LocalCommand, LocalCommandResult

# ── OKLCH-based markup helpers for REPL provider/model output ──────────
# Semantic names registered in clawcodex_ext/repl/color_scheme.py's
# build_rich_theme() — key_label (amber), value_text (purple),
# version_num (sky-blue), primary (blue).

_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _colorize_model_name(model: str | None) -> str:
    """Wrap version numbers in ``[version_num]…[/version_num]`` markup.

    Handles *None* gracefully (unknown provider case) so callers don't
    need to guard against ``re.sub`` ``TypeError``.
    """
    if model is None:
        return "[dim]unknown[/dim]"
    return _VERSION_RE.sub(r"[version_num]\1[/version_num]", model)


def _colorize_provider_list_text(plain: str) -> str:
    """Add Rich markup to ``format_provider_list()`` output.

    Transforms ``  name\\tlabel\\tmodel=X\\tconfigured=Y`` lines into
    OKLCH-coloured Rich markup using the theme from ``build_rich_theme()``.
    """
    lines = plain.split("\n")
    out: list[str] = []
    for line in lines:
        # "Providers:" header — keep as-is
        if not line.startswith(" "):
            out.append(line)
            continue
        # Data lines: "  name\\tlabel\\tmodel=value\\tconfigured=value"
        parts = line.split("\t")
        if len(parts) >= 4:
            # Provider name → primary (blue)
            name_col = f"[primary]{parts[0].strip()}[/primary]"
            label_col = parts[1]  # untouched
            # model=… key-label + value
            model_str = _colorize_model_name(parts[2])
            model_kv = re.sub(
                r"^(\w+)=(.+)$",
                r"[key_label]\1=[/key_label][value_text]\2[/value_text]",
                model_str,
            )
            # configured=yes/no
            configured_kv = re.sub(
                r"^(\w+)=(.+)$",
                r"[key_label]\1=[/key_label][value_text]\2[/value_text]",
                parts[3],
            )
            out.append(f"  {name_col}\t{label_col}\t{model_kv}\t{configured_kv}")
        else:
            out.append(line)
    return "\n".join(out)


def register_runtime_commands(registry: Any | None = None) -> None:
    from src.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    for command in (_provider_command(), _model_command()):
        reg.register(command)


def format_model_list(provider: str | None = None) -> str:
    return _format_configured_model_list(provider)


def _format_configured_model_list(provider: str | None = None) -> str:
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
            if (provider is None or name == provider) and get_provider_config(name)
        ]
        # Also include providers that exist only in config but aren't
        # known to ModelRegistry (e.g. completely custom providers).
        import json, os
        from src.config import get_global_config_path

        gp = get_global_config_path()
        if gp and gp.exists():
            raw = json.loads(gp.read_text())
            for p in raw.get("providers") or {}:
                if (
                    (provider is None or p == provider)
                    and p not in configured
                    and p not in registry.provider_names()
                ):
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


_MODEL_USAGE = (
    "Usage: /model [NAME [--provider NAME]]\n\n"
    "Modes:\n"
    "  (no args)              Show current provider/model + available models.\n"
    "  NAME                   Switch to model NAME. Unique short prefixes auto-\n"
    "                         match (e.g. 'gpt-4o-m' -> 'gpt-4o-mini'); ambiguous\n"
    "                         prefixes list candidates; on typo, suggests\n"
    "                         'Did you mean ...?'.\n"
    "  NAME --provider P      Switch to NAME under provider P (skip inference).\n"
    "  help, --help, -h       Print this help.\n\n"
    "Persistence:\n"
    "  Known model     runtime only - config unchanged.\n"
    "  Unknown model   saved to config.json; will survive restart.\n"
    "  If save fails   session only; not persisted.\n"
)


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
        plain_list = format_provider_list()
        colored_list = _colorize_provider_list_text(plain_list)
        lines = [current, "", colored_list] if current else [colored_list]
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

    try:
        runtime.swap_provider(provider)
    except Exception as exc:
        return _text(
            f"Failed to switch to provider '{provider}': {exc}\n"
            "Check that the provider is configured (api_key, base_url) "
            "and try again."
        )

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

    # Help subcommand - first-token check so /model --help still shows help.
    if tokens and tokens[0] in ("help", "--help", "-h"):
        return _text(_MODEL_USAGE)

    if not tokens:
        current = _format_runtime_current(context)
        current_provider = _current_provider_name(context)
        model_list = format_model_list(provider=current_provider)
        lines = [current, "", model_list] if current else [model_list]
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

    # ---- Try prefix matching / spelling suggestions on validation failure ----
    # Unique prefix matches are auto-corrected with a Note; multiple matches
    # are listed for the user to choose from; zero matches fall through to
    # ``Did you mean ...?`` suggestions from difflib.
    try:
        registry.validate_model(model, provider)
    except (UnknownModelError, ProviderMismatchError):
        prefix_matches = registry.find_prefix_matches(model, provider)
        if len(prefix_matches) == 1:
            resolved_model, resolved_provider = prefix_matches[0]
            warnings.append(f"Note: matched '{model}' by prefix to '{resolved_model}'")
            model = resolved_model
            provider = resolved_provider
        elif len(prefix_matches) > 1:
            options = ", ".join(m[0] for m in prefix_matches)
            warnings.append(
                f"Multiple models start with '{model}': {options} - please be more specific"
            )
        else:
            suggestions = registry.suggest_models(model, provider)
            if suggestions:
                warnings.append(f"Did you mean: {', '.join(suggestions)}?")

    # ---- Validate and warn about unknown models ----
    # /model is session-scoped only — it never modifies the persisted config.
    # For persistent changes, use ``clawcodex model use <name>`` from the CLI.
    try:
        registry.validate_model(model, provider)
    except (UnknownModelError, ProviderMismatchError):
        warnings.append(
            f"Unknown model '{model}' — proceeding anyway (session only; "
            "use 'clawcodex model use' to persist)"
        )

    # ---- Runtime switch (session-scoped only) ----
    runtime = _runtime(context)
    if runtime is None:
        return _text("Runtime context is not available — cannot switch model.")
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
    """Return an OKLCH-coloured ``"provider: …\nmodel: …"`` snippet with
    Rich markup, or *None* when the runtime context is missing."""
    runtime = _runtime(context)
    if runtime is None:
        return None
    lines = []
    if prefix:
        lines.append(prefix)
    raw_model = getattr(runtime.provider, "model", runtime.options.model)
    colored_model = _colorize_model_name(raw_model)
    lines.extend(
        [
            f"[primary]provider[/primary]: [value_text]{runtime.provider_name}[/value_text]",
            f"[primary]model[/primary]: {colored_model}",
        ]
    )
    return "\n".join(lines)


def _text(value: str) -> LocalCommandResult:
    return LocalCommandResult(type="text", value=value)

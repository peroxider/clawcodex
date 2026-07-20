"""The ``/multimodel`` REPL/TUI runtime command."""
from __future__ import annotations

import shlex
from typing import Any

from src.command_system.types import LocalCommand, LocalCommandResult
from .config import MultiModelConfigError, load_config, resolve_active_group

def register_multimodel_runtime_command(registry: Any | None = None) -> None:
    from src.command_system.registry import get_command_registry
    reg = registry or get_command_registry()
    command = LocalCommand(name="multimodel", description="Show or switch the active multi-model group", argument_hint="[use NAME|off|status]")
    command.set_call(_call); reg.register(command)

def _call(args: str, context: Any) -> LocalCommandResult:
    try: tokens = shlex.split(args); config = load_config()
    except (ValueError, MultiModelConfigError) as exc: return _text(f"error: {exc}")
    runtime = getattr(context, "runtime_context", None) or getattr(context, "runtime", None)
    selected = (
        getattr(runtime, "multimodel_group", None)
        if runtime is not None
        else getattr(context, "multimodel_group", None)
    )
    active = resolve_active_group(runtime_group=selected, config=config)
    if not tokens or tokens == ["status"]:
        if not active: return _text("当前: 未启用\n可用模型组: " + (", ".join(config.groups) or "(无)") + "\n输入 /multimodel use <name> 启用")
        group = config.groups.get(active)
        if group is None: return _text(f"当前模型组 '{active}' 不存在")
        return _text("状态: 已启用\n组:   " + active + "\n策略: " + group.strategy + "\n模型:\n" + "\n".join(f"  • {slot.model} ({slot.provider}) 权重: {slot.weight:g}" for slot in group.slots))
    if tokens[0] == "use" and len(tokens) == 2:
        name = tokens[1]
        if name not in config.groups: return _text(f"error: unknown model group '{name}'")
        if runtime is not None:
            try: runtime.swap_multimodel(name)
            except Exception as exc: return _text(f"error: cannot enable model group '{name}': {exc}")
        else: setattr(context, "multimodel_group", name)
        group = config.groups[name]
        return _text(f"✓ 已切换到多模型组 {name}\n策略: {group.strategy} | 模型: {', '.join(slot.name for slot in group.slots)}")
    if tokens == ["off"]:
        if runtime is not None:
            try: runtime.disable_multimodel()
            except Exception as exc: return _text(f"error: cannot disable multi-model mode: {exc}")
        else: setattr(context, "multimodel_group", "")
        return _text("✓ 已切换回单模型模式")
    return _text("Usage: /multimodel [status|use <name>|off]")

def _text(value: str) -> LocalCommandResult: return LocalCommandResult(type="text", value=value)

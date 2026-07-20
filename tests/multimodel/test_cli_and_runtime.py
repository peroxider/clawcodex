from __future__ import annotations

import asyncio
from pathlib import Path

from clawcodex_ext.command_system.registry import CommandRegistry
from clawcodex_ext.command_system.types import CommandContext
from clawcodex_ext.multimodel.cli import run_multimodel_command
from clawcodex_ext.multimodel.config import load_config, resolve_active_group
from clawcodex_ext.multimodel.runtime_command import register_multimodel_runtime_command


def test_group_lifecycle_and_persistence(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAWCODEX_CONFIG_DIR", str(tmp_path))
    assert run_multimodel_command([
        "group", "create", "review", "--slot", "sonnet:claude-sonnet-4-6@anthropic",
        "--slot", "gpt4o:gpt-4o@openai,weight=2", "--strategy", "voting",
        "--aggregator", "majority", "--min-votes", "2",
    ]) == 0
    assert run_multimodel_command(["use", "review"]) == 0
    config = load_config()
    assert config.default_group == "review"
    assert config.groups["review"].slots[1].weight == 2
    assert run_multimodel_command(["group", "update", "review", "--remove-slot", "gpt4o"]) == 0
    assert [slot.name for slot in load_config().groups["review"].slots] == ["sonnet"]


def test_runtime_selection_overrides_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLAWCODEX_CONFIG_DIR", str(tmp_path))
    assert run_multimodel_command(["preset", "quick-compare"]) == 0
    registry = CommandRegistry()
    register_multimodel_runtime_command(registry)
    command = registry.get("multimodel")
    assert command is not None
    context = CommandContext(workspace_root=Path.cwd(), cwd=Path.cwd())

    async def exercise() -> None:
        result = await command.call("use quick-compare", context)
        assert "已切换到多模型组" in result.value
        assert "状态: 已启用" in (await command.call("status", context)).value
        assert "单模型模式" in (await command.call("off", context)).value

    asyncio.run(exercise())
    assert resolve_active_group(cli_group="cli", runtime_group="runtime", config=load_config()) == "cli"

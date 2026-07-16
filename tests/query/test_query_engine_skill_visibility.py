from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import clawcodex_ext.query.engine as engine_module
from clawcodex_ext.query.engine import QueryEngine, QueryEngineConfig
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.registry import ToolRegistry


async def _build_prompt(
    monkeypatch,
    tmp_path,
    *,
    registered: bool = True,
    model_visible: bool = True,
    enabled: bool = True,
    denied: bool = False,
    denied_skill: bool = False,
):
    skill_tool = MagicMock()
    skill_tool.name = "Skill"
    skill_tool.aliases = ()
    skill_tool.is_enabled.return_value = enabled

    registry = ToolRegistry([skill_tool] if registered else [])
    context = ToolContext(workspace_root=tmp_path)
    if denied:
        context.permission_context.always_deny_rules = {"session": ["Skill"]}
    elif denied_skill:
        context.permission_context.always_deny_rules = {"session": ["Skill(visible-skill)"]}

    provider = MagicMock()
    provider.model = "test-model"
    config = QueryEngineConfig(
        cwd=tmp_path,
        provider=provider,
        tool_registry=registry,
        tools=[skill_tool] if registered and model_visible else [],
        tool_context=context,
    )

    command_module = ModuleType("clawcodex_ext.command_system")
    command_loader = MagicMock(return_value=["visible-skill"])
    command_module.get_skill_tool_commands = command_loader
    monkeypatch.setitem(sys.modules, "clawcodex_ext.command_system", command_module)

    monkeypatch.setattr(
        engine_module,
        "fetch_system_prompt_parts",
        AsyncMock(
            return_value=SimpleNamespace(
                user_context={},
                system_context={},
            )
        ),
    )
    prompt_builder = MagicMock(return_value=[{"type": "text", "text": "base"}])
    monkeypatch.setattr(engine_module, "build_full_system_prompt_blocks", prompt_builder)

    await QueryEngine(config)._build_system_prompt_parts()
    return command_loader, prompt_builder


@pytest.mark.asyncio
async def test_query_includes_skill_listing_when_skill_tool_is_available(
    monkeypatch,
    tmp_path,
):
    command_loader, prompt_builder = await _build_prompt(monkeypatch, tmp_path)

    command_loader.assert_called_once_with(str(tmp_path), None)
    assert prompt_builder.call_args.kwargs["skills"] == ["visible-skill"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("registered", "model_visible", "enabled", "denied"),
    [
        (False, False, True, False),
        (True, False, True, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
)
async def test_query_omits_skill_listing_when_skill_tool_is_unavailable(
    monkeypatch,
    tmp_path,
    registered,
    model_visible,
    enabled,
    denied,
):
    command_loader, prompt_builder = await _build_prompt(
        monkeypatch,
        tmp_path,
        registered=registered,
        model_visible=model_visible,
        enabled=enabled,
        denied=denied,
    )

    command_loader.assert_not_called()
    assert prompt_builder.call_args.kwargs["skills"] == []


@pytest.mark.asyncio
async def test_query_filters_canonical_skill_denied_by_permission(
    monkeypatch,
    tmp_path,
):
    command_loader, prompt_builder = await _build_prompt(
        monkeypatch,
        tmp_path,
        denied_skill=True,
    )

    command_loader.assert_called_once_with(str(tmp_path), None)
    assert prompt_builder.call_args.kwargs["skills"] == []

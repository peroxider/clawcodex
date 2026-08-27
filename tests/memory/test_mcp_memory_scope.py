from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from clawcodex_ext.latent_memory.passive.config import PassiveMemoryConfig
from clawcodex_ext.latent_memory.passive.mcp_scope import inject_project_user_id
from clawcodex_ext.latent_memory.passive.scope import build_memory_ids
from clawcodex_ext.latent_memory.plugin import _inject_user_id_interceptor
from clawcodex_ext.services.mcp.call_bridge import (
    register_mcp_arg_interceptor,
    unregister_mcp_arg_interceptor,
)
from clawcodex_ext.services.mcp.tool_wrapper import wrap_mcp_tool
from clawcodex_ext.services.mcp.types import McpToolSchema
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.tools.mcp import MCPTool


@pytest.fixture(autouse=True)
def _installed_memory_interceptor():
    register_mcp_arg_interceptor(_inject_user_id_interceptor)
    try:
        yield
    finally:
        unregister_mcp_arg_interceptor(_inject_user_id_interceptor)


def _context(tmp_path: Path) -> ToolContext:
    context = ToolContext(workspace_root=tmp_path)
    context.session_id = "scope-test"
    return context


def test_scope_helper_matches_passive_project_id_and_preserves_explicit(tmp_path: Path) -> None:
    context = _context(tmp_path)
    config = PassiveMemoryConfig(enabled=True, server_name="latent-memory", human_id="Chen")
    expected = build_memory_ids(config, context).user_id

    injected = inject_project_user_id(
        {"query": "policy"},
        context,
        server_name="latent-memory",
        tool_name="memory_search",
        config=config,
    )
    explicit = inject_project_user_id(
        {"query": "policy", "user_id": "explicit"},
        context,
        server_name="latent-memory",
        tool_name="memory_search",
        config=config,
    )
    unrelated = inject_project_user_id(
        {"query": "policy"},
        context,
        server_name="other",
        tool_name="memory_search",
        config=config,
    )

    assert injected["user_id"] == expected
    assert explicit["user_id"] == "explicit"
    assert "user_id" not in unrelated


def test_generic_dispatcher_injects_memory_scope_only_for_memory_server(tmp_path: Path) -> None:
    context = _context(tmp_path)
    calls: list[dict] = []

    class Client:
        def call_tool(self, _name: str, args: dict):
            calls.append(args)
            return {"ok": True}

    context.mcp_clients = {"latent-memory": Client(), "other": Client()}
    env = {
        "CLAWCODEX_PASSIVE_MEMORY": "true",
        "CLAWCODEX_PASSIVE_MEMORY_SERVER": "latent-memory",
        "CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID": "Chen",
    }
    with patch.dict("os.environ", env, clear=False):
        expected = build_memory_ids(PassiveMemoryConfig.from_env(), context).user_id
        MCPTool.call(
            {"server": "latent-memory", "tool": "memory_search", "input": {"query": "x"}},
            context,
        )
        MCPTool.call(
            {"server": "other", "tool": "memory_search", "input": {"query": "x"}},
            context,
        )

    assert calls[0]["user_id"] == expected
    assert "user_id" not in calls[1]


def test_per_server_wrapper_injects_omitted_scope(tmp_path: Path) -> None:
    context = _context(tmp_path)
    client = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(content=[], meta=None, structured_content=None)
        )
    )
    schema = McpToolSchema(
        name="memory_search",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "user_id": {"type": "string"}},
            "required": ["query"],
        },
    )
    wrapped = wrap_mcp_tool("latent-memory", schema, client)
    env = {
        "CLAWCODEX_PASSIVE_MEMORY": "true",
        "CLAWCODEX_PASSIVE_MEMORY_SERVER": "latent-memory",
        "CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID": "Chen",
    }
    with patch.dict("os.environ", env, clear=False):
        expected = build_memory_ids(PassiveMemoryConfig.from_env(), context).user_id
        result = wrapped.call({"query": "x"}, context)

    assert not result.is_error
    assert client.call_tool.await_args.args[1]["user_id"] == expected

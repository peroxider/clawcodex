from __future__ import annotations

import io
import json
import sys

from clawcodex_ext.latent_memory.server.mcp_server import StdioMcpServer, ToolSpec
from clawcodex_ext.latent_memory.server.schemas import (
    AddRequest,
    SearchRequest,
    UpdateRequest,
    sanitize_request_strings,
)


def test_sanitize_request_strings_recursively() -> None:
    value = {
        "bad\udcaekey": [
            "before\udcaeafter",
            {"nested": "value\ud800"},
            ("tuple\udfff",),
        ]
    }

    assert sanitize_request_strings(value) == {
        "badkey": ["beforeafter", {"nested": "value"}, ("tuple",)]
    }


def test_add_request_sanitizes_all_string_fields() -> None:
    request = AddRequest(
        messages=[
            {
                "role": "user\udcae",
                "content": "remember\udcae this",
                "nested": {"bad\udcaekey": "bad\ud800value"},
            }
        ],
        user_id="user\udcae",
        agent_id="agent\ud800",
        run_id="run\udfff",
        metadata={"source\udcae": "mcp\ud800"},
        observation_date="2026-07-16\udcae",
        custom_instructions="extract\udcae facts",
    )

    assert request.messages == [
        {
            "role": "user",
            "content": "remember this",
            "nested": {"badkey": "badvalue"},
        }
    ]
    assert request.user_id == "user"
    assert request.agent_id == "agent"
    assert request.run_id == "run"
    assert request.metadata == {"source": "mcp"}
    assert request.observation_date == "2026-07-16"
    assert request.custom_instructions == "extract facts"


def test_search_and_update_requests_sanitize_strings() -> None:
    search = SearchRequest(
        query="find\udcae memory",
        user_id="user\udcae",
        filters={"topic\udcae": ["code\ud800"]},
    )
    update = UpdateRequest(data="updated\udfff memory")

    assert search.query == "find memory"
    assert search.user_id == "user"
    assert search.filters == {"topic": ["code"]}
    assert update.data == "updated memory"


def test_mcp_entry_sanitizes_json_rpc_message(monkeypatch) -> None:
    captured: dict = {}

    def handler(arguments: dict) -> dict:
        captured.update(arguments)
        return {"ok": True}

    tool = ToolSpec(
        name="capture",
        description="capture arguments",
        input_schema={"type": "object"},
        handler=handler,
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "capture",
            "arguments": {
                "text": "before\udcaeafter",
                "metadata": {"bad\udcaekey": "bad\ud800value"},
            },
        },
    }
    stdin = io.StringIO(json.dumps(request) + "\n")
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    StdioMcpServer({"capture": tool}).serve()

    assert captured == {
        "text": "beforeafter",
        "metadata": {"badkey": "badvalue"},
    }

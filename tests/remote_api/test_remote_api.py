from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
TestClient = testclient.TestClient

from extensions.remote_api.core import RemoteAPIConfig, RemoteAPIService
from extensions.remote_api.runner import (
    RemoteAgentRunner,
    RemoteRunConfig,
    RemoteRunComplete,
    RemoteRunResult,
    RemoteTextDelta,
    RemoteToolCall,
    RemoteToolResult,
)
from extensions.remote_api.server import create_app
from src.types.content_blocks import ToolResultBlock, ToolUseBlock
from src.types.messages import AssistantMessage, UserMessage


class _RunnerStub:
    calls = []
    response_text = "final answer"
    usage = {"input_tokens": 5, "output_tokens": 7}
    events = [RemoteTextDelta("final answer")]
    delay = 0.0
    error: Exception | None = None
    reason = "success"

    def __init__(self, config, *, messages, instructions="", run_id=None):
        self.config = config
        self.messages = list(messages)
        self.instructions = instructions
        self.run_id = run_id
        self.__class__.calls.append(
            SimpleNamespace(
                config=config,
                messages=self.messages,
                instructions=instructions,
                run_id=run_id,
            )
        )

    async def run(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return RemoteRunResult(
            text=self.response_text,
            reason=self.reason,
            usage=dict(self.usage),
            messages=[*self.messages, AssistantMessage(content=self.response_text)],
            events=list(self.events),
        )

    async def stream(self):
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event
        if self.delay:
            await asyncio.sleep(self.delay)
        yield RemoteRunComplete(
            reason=self.reason,
            response_text=self.response_text,
            usage=dict(self.usage),
            messages=[*self.messages, AssistantMessage(content=self.response_text)],
        )


def _reset_runner() -> None:
    _RunnerStub.calls = []
    _RunnerStub.response_text = "final answer"
    _RunnerStub.usage = {"input_tokens": 5, "output_tokens": 7}
    _RunnerStub.events = [RemoteTextDelta("final answer")]
    _RunnerStub.delay = 0.0
    _RunnerStub.error = None
    _RunnerStub.reason = "success"


def _client(tmp_path: Path, **config_kwargs) -> TestClient:
    app = create_app(RemoteAPIConfig(workspace=tmp_path, **config_kwargs))
    return TestClient(app)


def _sse_json_payloads(text: str) -> list[dict]:
    payloads: list[dict] = []
    for frame in text.split("\n\n"):
        data_lines = [
            line.removeprefix("data: ") for line in frame.splitlines() if line.startswith("data: ")
        ]
        if not data_lines or data_lines == ["[DONE]"]:
            continue
        payloads.append(json.loads("\n".join(data_lines)))
    return payloads


def test_health_reports_workspace(tmp_path):
    client = _client(tmp_path, api_key="")

    response = client.get("/health")
    v1_response = client.get("/v1/health")

    assert response.status_code == 200
    assert v1_response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["workspace"] == str(tmp_path)
    assert data["model"] == "clawcodex-agent"
    assert data["provider"] == "default"


def test_remote_runs_default_to_bypassing_interactive_approvals(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post("/v1/responses", json={"input": "Hello"})

    assert response.status_code == 200
    assert _RunnerStub.calls[0].config.permission_mode == "bypassPermissions"


def test_remote_permission_mode_can_deny_unapproved_tools(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="", permission_mode="dontAsk")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post("/v1/responses", json={"input": "Hello"})

    assert response.status_code == 200
    assert _RunnerStub.calls[0].config.permission_mode == "dontAsk"


def test_models_capabilities_and_detailed_health(tmp_path):
    client = _client(tmp_path, api_key="", model="service-model", state_limit=3)

    assert client.get("/v1/models").json()["data"][0]["id"] == "service-model"
    caps = client.get("/v1/capabilities").json()
    assert caps["features"]["chat_completions"] is True
    assert caps["features"]["responses_api"] is True
    assert caps["features"]["remote_image_input"] is False
    detailed = client.get("/health/detailed").json()
    assert detailed["auth"]["required"] is False
    assert detailed["state_limit"] == 3


def test_optional_bearer_auth_protects_non_health_routes(tmp_path):
    client = _client(tmp_path, api_key="secret")

    assert client.get("/health").status_code == 200
    missing = client.get("/v1/models")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert (
        client.get(
            "/v1/models",
            headers={"Authorization": "Bearer secret"},
        ).status_code
        == 200
    )


def test_unknown_route_uses_compatible_error_payload(tmp_path):
    client = _client(tmp_path, api_key="")

    response = client.get("/v1/not-a-route")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Not Found"
    assert data["error"]["code"] == "not_found"


def test_chat_completion_runs_normalized_history(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "clawcodex-agent",
                "messages": [
                    {"role": "system", "content": "You are concise."},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "user", "content": "final prompt"},
                ],
                "stream": False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "clawcodex-agent"
    assert data["choices"][0]["message"]["content"] == "final answer"
    assert data["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
    }
    call = _RunnerStub.calls[0]
    assert call.instructions == "You are concise."
    assert [message.role for message in call.messages] == ["user", "assistant", "user"]
    assert call.config.workspace == tmp_path
    assert call.config.model is None


def test_request_model_overrides_query_model(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="", model="service-model")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "real-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert _RunnerStub.calls[0].config.model == "real-model"


def test_default_provider_defers_to_clawcodex_config(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    assert _RunnerStub.calls[0].config.provider is None


def test_advertised_agent_model_defers_to_provider_default(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="", model="clawcodex-agent")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/responses",
            json={"model": "clawcodex-agent", "input": "hello"},
        )

    assert response.status_code == 200
    assert response.json()["model"] == "clawcodex-agent"
    assert _RunnerStub.calls[0].config.model is None


def test_chat_stream_returns_openai_sse_chunks_without_tool_progress(tmp_path):
    _reset_runner()
    _RunnerStub.events = [
        RemoteToolCall("Bash", {"command": "pwd"}, "tool-1"),
        RemoteTextDelta("hello"),
        RemoteToolResult("Bash", {"output": "ok", "is_error": False}, "tool-1"),
    ]
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "stream": True,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    payloads = _sse_json_payloads(text)
    assert payloads
    assert all(payload["object"] == "chat.completion.chunk" for payload in payloads)
    assert payloads[0]["choices"][0]["delta"] == {
        "role": "assistant",
        "content": "",
    }
    assert any(payload["choices"][0]["delta"].get("content") == "hello" for payload in payloads)
    assert payloads[-1]["choices"][0]["finish_reason"] == "stop"
    assert "event: hermes.tool.progress" not in text
    assert "data: [DONE]" in text


def test_chat_stream_include_usage_emits_final_usage_only_chunk(tmp_path):
    _reset_runner()
    _RunnerStub.events = [RemoteTextDelta("hello")]
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    payloads = _sse_json_payloads(response.text)
    assert response.status_code == 200
    assert all("usage" in payload for payload in payloads)
    assert all(payload["usage"] is None for payload in payloads[:-1])
    assert payloads[-1]["choices"] == []
    assert payloads[-1]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
    }
    assert response.text.rstrip().endswith("data: [DONE]")


def test_stream_requests_are_validated_before_sse_headers(tmp_path):
    client = _client(tmp_path, api_key="")

    chat = client.post(
        "/v1/chat/completions",
        json={"stream": True, "messages": []},
    )
    responses = client.post(
        "/v1/responses",
        json={"stream": True, "input": "hello", "previous_response_id": "missing"},
    )

    assert chat.status_code == 400
    assert chat.headers["content-type"].startswith("application/json")
    assert responses.status_code == 404
    assert responses.headers["content-type"].startswith("application/json")


def test_chat_history_preserves_developer_and_tool_messages(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "developer", "content": "Be concise."},
                    {"role": "user", "content": "List files"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "terminal",
                                    "arguments": '{"command":"dir"}',
                                },
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_1", "content": "README.md"},
                    {"role": "user", "content": "Summarize"},
                ]
            },
        )

    assert response.status_code == 200
    call = _RunnerStub.calls[0]
    assert call.instructions == "Be concise."
    assert isinstance(call.messages[1].content[0], ToolUseBlock)
    assert call.messages[1].content[0].id == "call_1"
    assert isinstance(call.messages[2].content[0], ToolResultBlock)
    assert call.messages[2].content[0].tool_use_id == "call_1"


def test_rejects_empty_prompt_workspace_override_and_unsupported_content(tmp_path):
    client = _client(tmp_path, api_key="")

    assert (
        client.post(
            "/v1/chat/completions",
            json={"messages": []},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/chat/completions",
            json={"cwd": "/tmp/other", "messages": [{"role": "user", "content": "hi"}]},
        ).status_code
        == 400
    )
    remote_image = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                    ],
                }
            ]
        },
    )
    assert remote_image.status_code == 400
    assert remote_image.json()["error"]["code"] == "unsupported_content_type"
    input_file = client.post(
        "/v1/responses",
        json={"input": [{"type": "input_file", "file_id": "file_1"}]},
    )
    assert input_file.status_code == 400
    assert input_file.json()["error"]["code"] == "unsupported_content_type"
    mixed_continuity = client.post(
        "/v1/responses",
        json={
            "input": "hello",
            "previous_response_id": "resp_previous",
            "conversation": "thread",
        },
    )
    assert mixed_continuity.status_code == 400


def test_data_image_input_is_converted_to_image_block(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,QUJD"},
                            },
                        ],
                    }
                ]
            },
        )

    assert response.status_code == 200
    content = _RunnerStub.calls[0].messages[0].content
    assert isinstance(content, list)
    assert content[1].type == "image"
    assert content[1].source["media_type"] == "image/png"
    assert content[1].source["data"] == "QUJD"


def test_agent_failure_system_exit_and_timeout(tmp_path):
    client = _client(tmp_path, api_key="")

    _reset_runner()
    _RunnerStub.reason = "exit_code=1"
    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 500

    _reset_runner()
    _RunnerStub.error = SystemExit(2)
    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 500

    _reset_runner()
    _RunnerStub.delay = 0.05
    timeout_client = _client(tmp_path, api_key="", timeout_seconds=0.001)
    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = timeout_client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 504


def test_responses_api_store_get_delete_previous_and_conversation(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        first = client.post(
            "/v1/responses",
            json={
                "input": "Hello",
                "instructions": "Be helpful",
                "conversation": "project",
            },
        )
        second = client.post(
            "/v1/responses",
            json={
                "input": "Continue",
                "previous_response_id": first.json()["id"],
            },
        )
        third = client.post(
            "/v1/responses",
            json={
                "input": "Use named conversation",
                "conversation": "project",
            },
        )

    assert first.status_code == 200
    first_data = first.json()
    assert first_data["object"] == "response"
    assert first_data["status"] == "completed"
    assert first_data["completed_at"] >= first_data["created_at"]
    assert first_data["error"] is None
    assert first_data["incomplete_details"] is None
    assert first_data["previous_response_id"] is None
    assert first_data["conversation"] == {"id": "project"}
    assert first_data["output_text"] == "final answer"
    assert first_data["text"] == {"format": {"type": "text"}}
    assert first_data["tools"] == []
    assert first_data["store"] is True
    message = first_data["output"][-1]
    assert message["id"].startswith("msg_")
    assert message["status"] == "completed"
    assert message["role"] == "assistant"
    assert message["content"][0]["type"] == "output_text"
    assert message["content"][0]["annotations"] == []
    assert first_data["output"][-1]["content"][0]["text"] == "final answer"
    assert first_data["usage"]["total_tokens"] == 12
    assert client.get(f"/v1/responses/{first_data['id']}").status_code == 200
    input_items = client.get(f"/v1/responses/{first_data['id']}/input_items")
    assert input_items.status_code == 200
    input_items_data = input_items.json()
    assert input_items_data["object"] == "list"
    assert input_items_data["has_more"] is False
    assert input_items_data["data"][0]["role"] == "user"
    assert input_items_data["data"][0]["content"][0] == {
        "type": "input_text",
        "text": "Hello",
    }
    assert second.status_code == 200
    assert second.json()["previous_response_id"] == first_data["id"]
    assert third.status_code == 200
    assert _RunnerStub.calls[0].config.session_id == first_data["id"]
    assert _RunnerStub.calls[1].config.session_id == first_data["id"]
    assert _RunnerStub.calls[2].config.session_id == first_data["id"]
    assert _RunnerStub.calls[2].messages[0].content == "Hello"
    deleted = client.delete(f"/v1/responses/{first_data['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/v1/responses/{first_data['id']}").status_code == 404


async def test_responses_allows_ten_concurrent_independent_conversations(tmp_path):
    class EchoRunner(_RunnerStub):
        calls = []

        async def run(self):
            await asyncio.sleep(0.01)
            prompt = self.messages[-1].content
            text = f"answer:{prompt}"
            return RemoteRunResult(
                text=text,
                reason="success",
                usage={"input_tokens": 1, "output_tokens": 1},
                messages=[*self.messages, AssistantMessage(content=text)],
                events=[RemoteTextDelta(text)],
            )

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", EchoRunner):
        results = await asyncio.gather(
            *(
                service.responses({"input": f"turn-{index}", "conversation": f"thread-{index}"})
                for index in range(10)
            )
        )

    assert service.active_runs == 0
    assert [result["output_text"] for result in results] == [
        f"answer:turn-{index}" for index in range(10)
    ]
    assert [call.messages[-1].content for call in EchoRunner.calls] == [
        f"turn-{index}" for index in range(10)
    ]


async def test_openwebui_background_chat_requests_do_not_block_or_share_history(tmp_path):
    class ConcurrentRunner(_RunnerStub):
        calls = []
        active = 0
        max_active = 0

        async def run(self):
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            try:
                await asyncio.sleep(0.03)
                prompt = self.messages[-1].content
                return RemoteRunResult(
                    text=f"answer:{prompt}",
                    reason="success",
                    usage={"input_tokens": 1, "output_tokens": 1},
                    messages=[*self.messages, AssistantMessage(content=f"answer:{prompt}")],
                    events=[RemoteTextDelta(f"answer:{prompt}")],
                )
            finally:
                type(self).active -= 1

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))
    prompts = [
        "main answer",
        "generate a title",
        "generate follow-up suggestions",
        "next user turn",
    ]

    with patch("extensions.remote_api.core.RemoteAgentRunner", ConcurrentRunner):
        results = await asyncio.gather(
            *(
                service.chat_completion({"messages": [{"role": "user", "content": prompt}]})
                for prompt in prompts
            )
        )

    assert ConcurrentRunner.max_active == 4
    assert [result["choices"][0]["message"]["content"] for result in results] == [
        f"answer:{prompt}" for prompt in prompts
    ]
    assert [call.messages[-1].content for call in ConcurrentRunner.calls] == prompts
    assert service.active_runs == 0
    assert service.detailed_health()["stored_responses"] == 0
    assert service.detailed_health()["conversations"] == 0


async def test_twelve_concurrent_chat_streams_keep_chunks_isolated_and_ordered(tmp_path):
    class StreamingRunner(_RunnerStub):
        calls = []
        active = 0
        max_active = 0

        async def stream(self):
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            prompt = self.messages[-1].content
            try:
                yield RemoteTextDelta(f"{prompt}:a")
                await asyncio.sleep(0.02)
                yield RemoteTextDelta(":b")
                yield RemoteRunComplete(
                    reason="success",
                    response_text=f"{prompt}:a:b",
                    usage={"input_tokens": 1, "output_tokens": 1},
                    messages=[*self.messages, AssistantMessage(content=f"{prompt}:a:b")],
                )
            finally:
                type(self).active -= 1

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    async def collect(index: int) -> str:
        frames = [
            frame
            async for frame in service.chat_completion_sse_events(
                {
                    "stream": True,
                    "messages": [{"role": "user", "content": f"stream-{index}"}],
                }
            )
        ]
        payloads = _sse_json_payloads("".join(frames))
        return "".join(
            payload["choices"][0]["delta"].get("content", "")
            for payload in payloads
            if payload["choices"]
        )

    with patch("extensions.remote_api.core.RemoteAgentRunner", StreamingRunner):
        texts = await asyncio.gather(*(collect(index) for index in range(12)))

    assert StreamingRunner.max_active == 12
    assert texts == [f"stream-{index}:a:b" for index in range(12)]
    assert service.active_runs == 0


async def test_concurrent_same_conversation_serializes_history(tmp_path):
    class SlowEchoRunner(_RunnerStub):
        calls = []

        async def run(self):
            prompt = self.messages[-1].content
            if prompt == "first":
                await asyncio.sleep(0.05)
            text = f"answer:{prompt}"
            return RemoteRunResult(
                text=text,
                reason="success",
                usage={"input_tokens": 1, "output_tokens": 1},
                messages=[*self.messages, AssistantMessage(content=text)],
                events=[RemoteTextDelta(text)],
            )

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", SlowEchoRunner):
        first = asyncio.create_task(service.responses({"input": "first", "conversation": "shared"}))
        await asyncio.sleep(0.005)
        second = asyncio.create_task(
            service.responses({"input": "second", "conversation": "shared"})
        )
        first_result, second_result = await asyncio.gather(first, second)

    assert first_result["output_text"] == "answer:first"
    assert second_result["output_text"] == "answer:second"
    assert SlowEchoRunner.calls[1].messages[0].content == "first"
    assert SlowEchoRunner.calls[1].messages[1].content == "answer:first"
    assert SlowEchoRunner.calls[1].messages[-1].content == "second"


async def test_conversation_state_and_lock_maps_remain_bounded(tmp_path):
    class EchoRunner(_RunnerStub):
        calls = []

        async def run(self):
            prompt = self.messages[-1].content
            return RemoteRunResult(
                text=prompt,
                reason="success",
                usage={"input_tokens": 1, "output_tokens": 1},
                messages=[*self.messages, AssistantMessage(content=prompt)],
                events=[RemoteTextDelta(prompt)],
            )

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key="", state_limit=3))

    with patch("extensions.remote_api.core.RemoteAgentRunner", EchoRunner):
        for index in range(40):
            await service.responses({"input": f"turn-{index}", "conversation": f"thread-{index}"})

    health = service.detailed_health()
    assert health["stored_responses"] == 3
    assert health["conversations"] == 3
    assert len(service._conversation_locks) <= 16


def test_responses_store_false_is_not_retrievable(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/responses",
            json={"input": "Hello", "store": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["store"] is False
    assert client.get(f"/v1/responses/{data['id']}").status_code == 404


def test_responses_state_limit_evicts_oldest_response_and_alias(tmp_path):
    _reset_runner()
    client = _client(tmp_path, api_key="", state_limit=1)

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        first = client.post(
            "/v1/responses",
            json={"input": "first", "conversation": "alpha"},
        )
        second = client.post(
            "/v1/responses",
            json={"input": "second", "conversation": "beta"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get(f"/v1/responses/{first.json()['id']}").status_code == 404
    assert client.get(f"/v1/responses/{second.json()['id']}").status_code == 200
    detailed = client.get("/health/detailed").json()
    assert detailed["stored_responses"] == 1
    assert detailed["conversations"] == 1


def test_responses_stream_returns_sse(tmp_path):
    _reset_runner()
    _RunnerStub.events = [
        RemoteToolCall("Read", {"file_path": "README.md"}, "tool-1"),
        RemoteTextDelta("answer"),
        RemoteToolResult("Read", {"output": "ok", "is_error": False}, "tool-1"),
    ]
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post(
            "/v1/responses",
            json={"input": "Hello", "stream": True},
        )

    assert response.status_code == 200
    text = response.text
    assert "event: response.created" in text
    assert "event: response.in_progress" in text
    assert "event: response.output_item.added" in text
    assert "event: response.function_call_arguments.delta" in text
    assert "event: response.function_call_arguments.done" in text
    assert "event: response.content_part.added" in text
    assert "event: hermes.tool.progress" not in text
    assert "event: response.output_text.delta" in text
    assert "event: response.output_text.done" in text
    assert "event: response.content_part.done" in text
    assert '"item_id": "msg_' in text
    assert '"output_index": 0' in text
    assert '"content_index": 0' in text
    assert '"sequence_number":' in text
    assert "event: response.completed" in text
    payloads = _sse_json_payloads(text)
    assert any(
        payload.get("type") == "response.output_item.done"
        and payload["item"]["type"] == "function_call"
        for payload in payloads
    )
    assert any(
        payload.get("type") == "response.output_item.done"
        and payload["item"]["type"] == "function_call_output"
        for payload in payloads
    )
    completed = next(frame for frame in text.split("\n\n") if "event: response.completed" in frame)
    assert '"type": "function_call"' in completed
    assert '"type": "function_call_output"' in completed
    assert "data: [DONE]" not in text

    sequenced = [payload for payload in payloads if "sequence_number" in payload]
    assert [payload["sequence_number"] for payload in sequenced] == list(
        range(1, len(sequenced) + 1)
    )
    added_items = {
        payload["item"]["id"]: payload["output_index"]
        for payload in payloads
        if payload.get("type") == "response.output_item.added"
    }
    completed_payload = next(
        payload for payload in payloads if payload.get("type") == "response.completed"
    )
    created_payload = next(
        payload for payload in payloads if payload.get("type") == "response.created"
    )
    assert completed_payload["response"]["created_at"] == created_payload["response"]["created_at"]
    assert (
        completed_payload["response"]["completed_at"] >= created_payload["response"]["created_at"]
    )
    completed_items = completed_payload["response"]["output"]
    assert [item["type"] for item in completed_items] == [
        "function_call",
        "message",
        "function_call_output",
    ]
    assert [added_items[item["id"]] for item in completed_items] == [0, 1, 2]
    assert completed_items[2]["call_id"] == completed_items[0]["call_id"]
    assert completed_items[2]["output"] == [{"type": "input_text", "text": "ok"}]
    assert completed_payload["response"]["usage"]["input_tokens_details"] == {"cached_tokens": 0}
    assert completed_payload["response"]["usage"]["output_tokens_details"] == {
        "reasoning_tokens": 0
    }


def test_responses_pairs_tool_result_without_id_by_tool_name(tmp_path):
    _reset_runner()
    _RunnerStub.events = [
        RemoteToolCall("Read", {"file_path": "README.md"}, "tool-1"),
        RemoteToolResult("Read", {"output": "ok", "is_error": False}),
    ]
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post("/v1/responses", json={"input": "Hello"})

    assert response.status_code == 200
    function_call = next(
        item for item in response.json()["output"] if item["type"] == "function_call"
    )
    function_output = next(
        item for item in response.json()["output"] if item["type"] == "function_call_output"
    )
    assert function_output["call_id"] == function_call["call_id"] == "tool-1"


def test_responses_accepts_plain_string_tool_result(tmp_path):
    _reset_runner()
    _RunnerStub.events = [
        RemoteToolCall("Read", {"file_path": "README.md"}, "tool-1"),
        RemoteToolResult("Read", "README contents", "tool-1"),
    ]
    client = _client(tmp_path, api_key="")

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        response = client.post("/v1/responses", json={"input": "Hello"})

    assert response.status_code == 200
    function_output = next(
        item for item in response.json()["output"] if item["type"] == "function_call_output"
    )
    assert function_output["call_id"] == "tool-1"
    assert function_output["output"] == [{"type": "input_text", "text": "README contents"}]

    # Open WebUI 0.9.6 iterates these parts and calls ``get`` on each one.
    # Keeping every part object-shaped prevents the next-turn parser crash.
    assert (
        "".join(
            part.get("text", "")
            for part in function_output["output"]
            if part.get("type") == "input_text"
        )
        == "README contents"
    )


async def test_streaming_conversation_can_continue_on_second_turn(tmp_path):
    _reset_runner()
    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        first_frames = [
            frame
            async for frame in service.responses_sse_events(
                {"input": "first", "conversation": "thread"}
            )
        ]
        second_frames = [
            frame
            async for frame in service.responses_sse_events(
                {"input": "second", "conversation": "thread"}
            )
        ]

    assert any("response.completed" in frame for frame in first_frames)
    assert any("response.completed" in frame for frame in second_frames)
    assert not any("data: [DONE]" in frame for frame in first_frames + second_frames)
    assert _RunnerStub.calls[1].messages[0].content == "first"
    assert _RunnerStub.calls[1].messages[-1].content == "second"
    assert _RunnerStub.calls[0].config.session_id == _RunnerStub.calls[1].config.session_id
    assert service.active_runs == 0


async def test_runner_stream_emits_text_while_agent_loop_blocks(tmp_path):
    from src.utils.abort_controller import AbortController

    def fake_runtime(config):
        return {
            "provider": object(),
            "tool_registry": object(),
            "tool_context": SimpleNamespace(
                output_style_name=None,
                output_style_dir=None,
                team=None,
                session_id=None,
                outbox=[],
            ),
            "abort_controller": AbortController(),
        }

    async def fake_agent_loop(**kwargs):
        on_text_chunk = kwargs.get("on_text_chunk")
        if on_text_chunk is not None:
            on_text_chunk("early")
        time.sleep(0.4)
        message = AssistantMessage(content="early done")
        on_message = kwargs.get("on_message")
        if on_message is not None:
            on_message(message)
        return SimpleNamespace(
            response_text="early done",
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    runner = RemoteAgentRunner(
        RemoteRunConfig(workspace=tmp_path),
        messages=[UserMessage(content="hello")],
        run_id="test-run",
    )

    with (
        patch("extensions.remote_api.runner._build_runtime", fake_runtime),
        patch(
            "src.outputStyles.resolve_output_style",
            lambda *_args, **_kwargs: SimpleNamespace(prompt="style"),
        ),
        patch(
            "src.query.agent_loop_compat.build_effective_system_prompt",
            lambda _style, _context: "system",
        ),
        patch("src.query.agent_loop_compat.run_query_as_agent_loop", fake_agent_loop),
    ):
        stream = runner.stream()
        first = await asyncio.wait_for(anext(stream), timeout=0.2)
        remaining = [event async for event in stream]

    assert isinstance(first, RemoteTextDelta)
    assert first.content == "early"
    complete = next(event for event in remaining if isinstance(event, RemoteRunComplete))
    assert complete.response_text == "early done"
    assert complete.messages[-1].content == "early done"


async def test_runner_backpressure_preserves_more_chunks_than_queue_capacity(tmp_path):
    from src.utils.abort_controller import AbortController

    chunk_count = 400

    def fake_runtime(config):
        return {
            "provider": object(),
            "tool_registry": object(),
            "tool_context": SimpleNamespace(
                output_style_name=None,
                output_style_dir=None,
                team=None,
                session_id=None,
                outbox=[],
            ),
            "abort_controller": AbortController(),
        }

    async def fake_agent_loop(**kwargs):
        on_text_chunk = kwargs["on_text_chunk"]
        for index in range(chunk_count):
            on_text_chunk(f"{index},")
        return SimpleNamespace(
            response_text="".join(f"{index}," for index in range(chunk_count)),
            usage={"input_tokens": 1, "output_tokens": chunk_count},
        )

    runner = RemoteAgentRunner(
        RemoteRunConfig(workspace=tmp_path),
        messages=[UserMessage(content="hello")],
        run_id="backpressure",
    )

    with (
        patch("extensions.remote_api.runner._build_runtime", fake_runtime),
        patch(
            "src.outputStyles.resolve_output_style",
            lambda *_args, **_kwargs: SimpleNamespace(prompt="style"),
        ),
        patch(
            "src.query.agent_loop_compat.build_effective_system_prompt",
            lambda _style, _context: "system",
        ),
        patch("src.query.agent_loop_compat.run_query_as_agent_loop", fake_agent_loop),
    ):
        events = [event async for event in runner.stream()]

    deltas = [event.content for event in events if isinstance(event, RemoteTextDelta)]
    assert deltas == [f"{index}," for index in range(chunk_count)]
    assert isinstance(events[-1], RemoteRunComplete)


async def test_runner_stream_close_aborts_inflight_agent(tmp_path):
    from src.utils.abort_controller import AbortController

    abort_controller = AbortController()

    def fake_runtime(config):
        return {
            "provider": object(),
            "tool_registry": object(),
            "tool_context": SimpleNamespace(
                output_style_name=None,
                output_style_dir=None,
                team=None,
                session_id=None,
                outbox=[],
            ),
            "abort_controller": abort_controller,
        }

    async def fake_agent_loop(**kwargs):
        kwargs["on_text_chunk"]("early")
        while not abort_controller.signal.aborted:
            await asyncio.sleep(0.01)
        return SimpleNamespace(response_text="early", usage={})

    runner = RemoteAgentRunner(
        RemoteRunConfig(workspace=tmp_path),
        messages=[UserMessage(content="hello")],
        run_id="disconnect",
    )

    with (
        patch("extensions.remote_api.runner._build_runtime", fake_runtime),
        patch(
            "src.outputStyles.resolve_output_style",
            lambda *_args, **_kwargs: SimpleNamespace(prompt="style"),
        ),
        patch(
            "src.query.agent_loop_compat.build_effective_system_prompt",
            lambda _style, _context: "system",
        ),
        patch("src.query.agent_loop_compat.run_query_as_agent_loop", fake_agent_loop),
    ):
        stream = runner.stream()
        first = await asyncio.wait_for(anext(stream), timeout=0.2)
        await stream.aclose()

    assert isinstance(first, RemoteTextDelta)
    assert abort_controller.signal.aborted is True


async def test_responses_stream_yields_delta_before_run_completes(tmp_path):
    _reset_runner()
    _RunnerStub.events = [RemoteTextDelta("early")]
    _RunnerStub.delay = 0.05
    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        stream = service.responses_sse_events({"input": "Hello"})
        try:
            frames = []
            while not any("response.output_text.delta" in frame for frame in frames):
                frames.append(await asyncio.wait_for(anext(stream), timeout=0.01))
        finally:
            await stream.aclose()

    assert any("response.output_text.delta" in frame and "early" in frame for frame in frames)


async def test_closing_stream_cleans_up_active_run(tmp_path):
    _reset_runner()
    _RunnerStub.events = [RemoteTextDelta("early")]
    _RunnerStub.delay = 0.05
    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", _RunnerStub):
        stream = service.responses_sse_events({"input": "first"})
        try:
            await asyncio.wait_for(anext(stream), timeout=0.01)
        finally:
            await stream.aclose()

        frames = [frame async for frame in service.responses_sse_events({"input": "second"})]

    assert service.active_runs == 0
    assert any("response.completed" in frame for frame in frames)


async def test_responses_stream_completed_uses_final_agent_text(tmp_path):
    class MismatchedStreamRunner(_RunnerStub):
        async def stream(self):
            yield RemoteTextDelta("12\n\n3")
            yield RemoteTextDelta("\n\n4\n\n5")
            yield RemoteRunComplete(
                reason="success",
                response_text="1\n2\n3\n4\n5",
                usage=dict(self.usage),
                messages=[*self.messages, AssistantMessage(content="1\n2\n3\n4\n5")],
            )

    service = RemoteAPIService(RemoteAPIConfig(workspace=tmp_path, api_key=""))

    with patch("extensions.remote_api.core.RemoteAgentRunner", MismatchedStreamRunner):
        frames = [frame async for frame in service.responses_sse_events({"input": "count"})]

    completed = next(frame for frame in frames if "event: response.completed" in frame)
    assert '"output_text": "1\\n2\\n3\\n4\\n5"' in completed
    assert '"text": "1\\n2\\n3\\n4\\n5"' in completed
    assert '"output_text": "12\\n\\n3\\n\\n4\\n\\n5"' not in completed

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi")
testclient = pytest.importorskip("fastapi.testclient")
TestClient = testclient.TestClient

from extensions.remote_api.server import RemoteAPIConfig, create_app


class _QueryRunnerStub:
    calls = []
    response = {"text": "final answer", "reason": "success", "tool_calls": []}

    def __init__(self, config):
        self.config = config
        self.__class__.calls.append(config)

    async def run(self):
        return self.response


def _client(tmp_path: Path) -> TestClient:
    app = create_app(RemoteAPIConfig(workspace=tmp_path))
    return TestClient(app)


def test_health_reports_workspace(tmp_path):
    client = _client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["workspace"] == str(tmp_path)
    assert data["model"] == "clawcodex-agent"
    assert data["provider"] == "default"


def test_chat_completion_runs_last_user_prompt(tmp_path):
    _QueryRunnerStub.calls = []
    client = _client(tmp_path)

    with patch("extensions.remote_api.core.QueryRunner", _QueryRunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "clawcodex-agent",
                "messages": [
                    {"role": "system", "content": "ignore"},
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
    assert _QueryRunnerStub.calls[0].prompt == "final prompt"
    assert _QueryRunnerStub.calls[0].workspace == tmp_path
    assert _QueryRunnerStub.calls[0].model is None


def test_request_model_overrides_query_model(tmp_path):
    _QueryRunnerStub.calls = []
    app = create_app(RemoteAPIConfig(workspace=tmp_path, model="service-model"))
    client = TestClient(app)

    with patch("extensions.remote_api.core.QueryRunner", _QueryRunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "real-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert _QueryRunnerStub.calls[0].model == "real-model"


def test_default_provider_defers_to_headless_config(tmp_path):
    _QueryRunnerStub.calls = []
    client = _client(tmp_path)

    with patch("extensions.remote_api.core.QueryRunner", _QueryRunnerStub):
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert _QueryRunnerStub.calls[0].provider is None


def test_rejects_streaming_empty_prompt_and_workspace_override(tmp_path):
    client = _client(tmp_path)

    assert client.post(
        "/v1/chat/completions",
        json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
    ).status_code == 400
    assert client.post(
        "/v1/chat/completions",
        json={"messages": []},
    ).status_code == 400
    assert client.post(
        "/v1/chat/completions",
        json={"cwd": "/tmp/other", "messages": [{"role": "user", "content": "hi"}]},
    ).status_code == 400


def test_agent_failure_returns_500(tmp_path):
    class FailingRunner(_QueryRunnerStub):
        async def run(self):
            return {"text": "", "reason": "exit_code=1", "tool_calls": []}

    client = _client(tmp_path)

    with patch("extensions.remote_api.core.QueryRunner", FailingRunner):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 500


def test_agent_system_exit_returns_500_without_escaping(tmp_path):
    class ExitingRunner(_QueryRunnerStub):
        async def run(self):
            raise SystemExit(2)

    client = _client(tmp_path)

    with patch("extensions.remote_api.core.QueryRunner", ExitingRunner):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 500


def test_busy_server_returns_429(tmp_path):
    client = _client(tmp_path)
    service = client.app.state.remote_api_service
    assert service._busy_lock.acquire(blocking=False)

    try:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
    finally:
        service._busy_lock.release()

    assert response.status_code == 429


def test_agent_timeout_returns_504(tmp_path):
    class SlowRunner(_QueryRunnerStub):
        async def run(self):
            await asyncio.sleep(0.05)
            return {"text": "late", "reason": "success", "tool_calls": []}

    app = create_app(RemoteAPIConfig(workspace=tmp_path, timeout_seconds=0.001))
    client = TestClient(app)

    with patch("extensions.remote_api.core.QueryRunner", SlowRunner):
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 504

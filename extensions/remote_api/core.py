"""Core request handling for the Remote Single-Run Agent API."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extensions.api.query import QueryConfig, QueryRunner


API_MODEL_NAME = "clawcodex-agent"
FORBIDDEN_WORKSPACE_FIELDS = {"cwd", "workspace", "workdir", "working_dir", "root_dir"}


@dataclass(frozen=True)
class RemoteAPIConfig:
    """Runtime configuration for the single-run API server."""

    workspace: Path
    host: str = "127.0.0.1"
    port: int = 8642
    provider: str | None = None
    model: str | None = None
    max_turns: int = 20
    timeout_seconds: float = 600.0


class RemoteAPIError(Exception):
    """HTTP-shaped API error."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RemoteAPIService:
    """Single-run Agent API service with process-local busy limiting."""

    def __init__(self, config: RemoteAPIConfig) -> None:
        self.config = config
        self._busy_lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        version = "unknown"
        try:
            from src import __version__

            version = __version__
        except Exception:
            pass
        return {
            "status": "ok",
            "version": version,
            "workspace": str(self.config.workspace),
            "model": self.config.model or API_MODEL_NAME,
            "provider": self.config.provider or "default",
        }

    async def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        _reject_workspace_override(body)
        if body.get("stream", False) is True:
            raise RemoteAPIError(400, "stream=true is not supported in v1")

        prompt = _extract_last_user_prompt(body.get("messages"))
        if not prompt:
            raise RemoteAPIError(400, "messages must include a non-empty user prompt")

        if not self._busy_lock.acquire(blocking=False):
            raise RemoteAPIError(429, "agent is already running")

        run_id = f"run_{uuid.uuid4().hex}"
        response_model = str(body.get("model") or self.config.model or API_MODEL_NAME)
        query_model = _resolve_query_model(body.get("model"), self.config.model)
        try:
            runner = QueryRunner(
                QueryConfig(
                    prompt=prompt,
                    workspace=self.config.workspace,
                    provider=self.config.provider,
                    model=query_model,
                    max_turns=self.config.max_turns,
                    permission_mode="dontAsk",
                    run_id=run_id,
                )
            )
            try:
                result = await asyncio.wait_for(
                    runner.run(),
                    timeout=self.config.timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise RemoteAPIError(504, "agent run timed out") from exc
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                raise RemoteAPIError(500, f"agent run failed: exit_code={code}") from exc
            except Exception as exc:
                raise RemoteAPIError(500, f"agent run failed: {exc}") from exc
        finally:
            self._busy_lock.release()

        reason = str(result.get("reason", "stop"))
        if reason != "success":
            raise RemoteAPIError(500, f"agent run failed: {reason}")

        return {
            "id": run_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": str(result.get("text", "")),
                    },
                    "finish_reason": "stop",
                }
            ],
        }


def _reject_workspace_override(body: dict[str, Any]) -> None:
    forbidden = sorted(FORBIDDEN_WORKSPACE_FIELDS.intersection(body))
    if forbidden:
        fields = ", ".join(forbidden)
        raise RemoteAPIError(400, f"workspace override is not supported: {fields}")


def _extract_last_user_prompt(messages: Any) -> str:
    if not isinstance(messages, list) or not messages:
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        return ""
    return ""


def _resolve_query_model(request_model: Any, service_model: str | None) -> str | None:
    if isinstance(request_model, str) and request_model and request_model != API_MODEL_NAME:
        return request_model
    if service_model:
        return service_model
    return None

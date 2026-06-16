"""FastAPI app for the Remote Single-Run Agent API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from .core import RemoteAPIConfig, RemoteAPIError, RemoteAPIService


def create_app(config: RemoteAPIConfig) -> FastAPI:
    """Create the Remote Single-Run Agent API app."""

    app = FastAPI(title="ClawCodex Remote Agent API", version="0.1.0")
    app.state.remote_api_config = config
    app.state.remote_api_service = RemoteAPIService(config)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return app.state.remote_api_service.health()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> dict[str, Any]:
        body = await _read_json_object(request)
        try:
            return await app.state.remote_api_service.chat_completion(body)
        except RemoteAPIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return app


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body

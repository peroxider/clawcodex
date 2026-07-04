"""FastAPI app for the Hermes-compatible remote API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .core import RemoteAPIConfig, RemoteAPIError, RemoteAPIService


def create_app(config: RemoteAPIConfig) -> FastAPI:
    """Create the remote API app."""

    app = FastAPI(title="ClawCodex Remote Agent API", version="0.2.0")
    app.state.remote_api_config = config
    app.state.remote_api_service = RemoteAPIService(config)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _error_response(RemoteAPIError(exc.status_code, detail))

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return app.state.remote_api_service.health()

    @app.get("/v1/health")
    async def v1_health() -> dict[str, Any]:
        return app.state.remote_api_service.health()

    @app.get("/health/detailed")
    async def health_detailed(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.detailed_health()
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.get("/v1/models")
    async def models(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.models()
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.get("/v1/capabilities")
    async def capabilities(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.capabilities()
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.post("/proactive/focus")
    async def proactive_focus(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            body = await _read_json_object(request)
            level = body.get("level")
            if not isinstance(level, str):
                raise RemoteAPIError(400, "level must be a string")
            from .state_reporter import set_proactive_focus

            try:
                return {"automation_state": set_proactive_focus(level)}
            except ValueError as exc:
                raise RemoteAPIError(400, str(exc)) from exc
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            body = await _read_json_object(request)
            if body.get("stream") is True:
                prepared = app.state.remote_api_service.prepare_chat_completion(body)
                return _sse_response(
                    app.state.remote_api_service.chat_completion_sse_events(
                        body,
                        prepared=prepared,
                    ),
                )
            return await app.state.remote_api_service.chat_completion(body)
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.post("/v1/responses")
    async def responses(request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            body = await _read_json_object(request)
            if body.get("stream") is True:
                app.state.remote_api_service.validate_responses_request(body)
                return _sse_response(
                    app.state.remote_api_service.responses_sse_events(body),
                )
            return await app.state.remote_api_service.responses(body)
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.get("/v1/responses/{response_id}/input_items")
    async def get_response_input_items(response_id: str, request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.get_response_input_items(response_id)
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.get("/v1/responses/{response_id}")
    async def get_response(response_id: str, request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.get_response(response_id)
        except RemoteAPIError as exc:
            return _error_response(exc)

    @app.delete("/v1/responses/{response_id}")
    async def delete_response(response_id: str, request: Request):
        try:
            _require_auth(app.state.remote_api_service, request)
            return app.state.remote_api_service.delete_response(response_id)
        except RemoteAPIError as exc:
            return _error_response(exc)

    return app


def _require_auth(service: RemoteAPIService, request: Request) -> None:
    service.require_auth(request.headers.get("authorization"))


async def _read_json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise RemoteAPIError(400, "request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise RemoteAPIError(400, "request body must be a JSON object")
    return body


def _error_response(exc: RemoteAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


def _sse_response(iterator: Any) -> StreamingResponse:
    return StreamingResponse(
        iterator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

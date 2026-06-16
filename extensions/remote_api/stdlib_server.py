"""Standard-library HTTP server for ``clawcodex api serve``."""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .core import RemoteAPIConfig, RemoteAPIError, RemoteAPIService


def serve(config: RemoteAPIConfig) -> None:
    """Run the blocking HTTP server."""

    service = RemoteAPIService(config)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ClawCodexRemoteAPI/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path != "/health":
                self._write_error(404, "not found")
                return
            self._write_json(200, service.health())

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self._write_error(404, "not found")
                return
            try:
                body = self._read_json_object()
                response = asyncio.run(service.chat_completion(body))
            except RemoteAPIError as exc:
                self._write_error(exc.status_code, exc.detail)
                return
            except Exception as exc:
                self._write_error(500, f"internal server error: {exc}")
                return
            self._write_json(200, response)

        def _read_json_object(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise RemoteAPIError(400, "invalid Content-Length") from exc
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise RemoteAPIError(400, "request body must be valid JSON") from exc
            if not isinstance(body, dict):
                raise RemoteAPIError(400, "request body must be a JSON object")
            return body

        def _write_error(self, status_code: int, detail: str) -> None:
            self._write_json(status_code, {"detail": detail})

        def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer((config.host, config.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

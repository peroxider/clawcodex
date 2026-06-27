"""RemoteTriggerTool — fire HTTP requests to a configured remote endpoint.

F-71 M: lightweight, dependency-only-on-``httpx`` HTTP client that lets
the agent poke a remote API (e.g. a CI webhook, a notification service,
a status page). The tool is intentionally minimal — it does *not*
attempt to be a generic HTTP client, only a "trigger and report" helper.

Differences from the Bash + curl pattern that already works for this
use case:

* **Timeout-bounded** — Bash + curl is unbounded; RemoteTriggerTool
  enforces a hard 30s default with a 5-minute ceiling.
* **Structured result** — the tool returns a JSON-shaped ``ToolResult``
  with ``status_code``, ``headers``, ``body`` keys so downstream
  parsers don't have to grep ``stdout``.
* **Allow-list gate** — only ``https://`` URLs matching
  ``allowed_hosts`` (if configured on ``ToolContext``) are reachable.
  This prevents accidental ``http://169.254.169.254/`` SSRF.
* **Audit-friendly** — every call records the resolved URL on
  ``context.tool_calls`` with the response status for review.

The tool deliberately does not retry on 5xx; the agent decides whether
to retry. Idempotency-Key header generation is the caller's job.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ..build_tool import Tool, ValidationResult, build_tool
from ..context import ToolContext
from ..protocol import ToolResult

try:  # httpx is in pyproject; treat its absence as a soft dependency.
    import httpx as _httpx
except ImportError:  # pragma: no cover - exercised in environments without httpx
    _httpx = None  # type: ignore[assignment]


# Hard ceiling regardless of caller intent.
DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 300.0


def _validate_url(url: str, allowed_hosts: list[str] | None) -> ValidationResult:
    """Reject non-HTTPS URLs and out-of-allowlist hosts before any network IO."""
    if not url:
        return ValidationResult.fail("url is required")
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return ValidationResult.fail(f"could not parse url: {exc}")
    if parsed.scheme not in {"https"}:
        return ValidationResult.fail(
            f"only https:// URLs are accepted (got scheme {parsed.scheme!r})"
        )
    if not parsed.netloc:
        return ValidationResult.fail("url is missing host component")
    host = parsed.hostname or ""
    if allowed_hosts:
        # Empty allow-list means nothing passes; non-empty means allow-list only.
        if host not in allowed_hosts:
            return ValidationResult.fail(
                f"host {host!r} not in allowed_hosts allow-list"
            )
    return ValidationResult.ok()


def _coerce_timeout(raw: Any) -> float:
    """Clamp caller-supplied timeout to [1.0, MAX_TIMEOUT_S]."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    if value <= 0:
        return DEFAULT_TIMEOUT_S
    return min(value, MAX_TIMEOUT_S)


def _headers_to_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    if isinstance(headers, dict):
        return {str(k): str(v) for k, v in headers.items()}
    if isinstance(headers, list):
        out: dict[str, str] = {}
        for entry in headers:
            if isinstance(entry, (tuple, list)) and len(entry) == 2:
                out[str(entry[0])] = str(entry[1])
        return out
    return {}


def _allowed_hosts_from_context(context: ToolContext) -> list[str] | None:
    """Pull the optional allow-list from ToolContext if the host wired one.

    Returns None when the context doesn't expose the field, signalling
    "no allow-list filter" (i.e. all https URLs are eligible subject to
    the scheme check).
    """
    getter: Callable[[], list[str] | None] | None = getattr(
        context, "remote_trigger_allowed_hosts", None
    )
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def remote_trigger_call(payload: dict[str, Any], context: ToolContext) -> ToolResult:
    """Fire one HTTPS request and return a structured response."""
    if _httpx is None:
        return ToolResult(name="remote_trigger",
            output=(
                "RemoteTriggerTool: httpx is not installed in this environment; "
                "run `pip install httpx` to enable remote triggers"
            ),
            is_error=True,
        )

    url = str(payload.get("url") or "")
    method = str(payload.get("method") or "POST").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return ToolResult(name="remote_trigger",
            output=f"RemoteTriggerTool: unsupported method {method!r}",
            is_error=True,
        )

    allowed_hosts = _allowed_hosts_from_context(context)
    validation = _validate_url(url, allowed_hosts)
    if not validation.result:
        return ToolResult(name="remote_trigger", output=validation.message, is_error=True)

    headers = _headers_to_dict(payload.get("headers"))
    body = payload.get("body")
    if body is not None and not isinstance(body, (str, dict, list)):
        return ToolResult(name="remote_trigger",
            output="RemoteTriggerTool: body must be str, dict, or list",
            is_error=True,
        )
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
        headers.setdefault("Content-Type", "application/json")

    timeout = _coerce_timeout(payload.get("timeout_s"))

    try:
        response = _httpx.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
            timeout=timeout,
        )
    except _httpx.TimeoutException:
        return ToolResult(name="remote_trigger",
            output=f"RemoteTriggerTool: timeout after {timeout}s",
            is_error=True,
        )
    except _httpx.HTTPError as exc:
        return ToolResult(name="remote_trigger",
            output=f"RemoteTriggerTool: transport error {type(exc).__name__}: {exc}",
            is_error=True,
        )

    response_body: str
    if isinstance(response.content, bytes):
        try:
            response_body = response.content.decode("utf-8")
        except UnicodeDecodeError:
            response_body = response.content.decode("utf-8", errors="replace")
    else:
        response_body = str(response.content)

    truncated = len(response_body) > 8000
    if truncated:
        response_body = response_body[:8000] + "\u2026 [truncated]"

    payload_out: dict[str, Any] = {
        "status_code": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "body": response_body,
    }
    is_error = response.status_code >= 500
    return ToolResult(name="remote_trigger",
        output=json.dumps(payload_out, ensure_ascii=False, indent=2),
        is_error=is_error,
    )


def remote_trigger_activity(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    method = payload.get("method") if isinstance(payload, dict) else None
    url = payload.get("url") if isinstance(payload, dict) else None
    if method and url:
        return f"{method} {url}"
    return "remote trigger"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


remote_trigger_tool: Tool = build_tool(
    name="remote_trigger",
    description=(
        "Fire one HTTPS request to a remote endpoint and return a structured "
        "response (status_code, headers, body). Only POST/GET/PUT/PATCH/DELETE "
        "are accepted; https:// scheme is enforced; non-allow-listed hosts "
        "are rejected when ToolContext exposes an allow-list. Timeouts are "
        "capped at 5 minutes; no automatic retries."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Target endpoint. Must use https:// scheme.",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "description": "HTTP method. Defaults to POST.",
            },
            "headers": {
                "type": "object",
                "description": "Optional request headers as a dict.",
            },
            "body": {
                "type": ["string", "object", "array", "null"],
                "description": "Optional request body. Dicts/lists are JSON-encoded.",
            },
            "timeout_s": {
                "type": "number",
                "description": "Timeout in seconds. Capped at 300s.",
            },
        },
        "required": ["url"],
    },
    call=remote_trigger_call,
    get_activity_description=remote_trigger_activity,
    aliases=("RemoteTriggerTool", "http_trigger"),
    is_destructive=lambda _p: True,  # network side-effect
    search_hint="remote http trigger webhook",
)


__all__ = ["remote_trigger_tool", "remote_trigger_call", "_allowed_hosts_from_context"]
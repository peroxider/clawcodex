"""MCP stdio adapter for the latent memory server.

This adapter is deliberately thin: the MCP client communicates with this process over stdin/stdout,
and this process forwards tool calls to the existing REST API exposed by
``clawcodex_ext.latent_memory.server.app``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable

import requests

from clawcodex_ext.latent_memory.server.schemas import sanitize_request_strings

SERVER_NAME = "latent-memory"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_MEM0_HOST = "http://127.0.0.1:8888"
DEFAULT_TIMEOUT_SECONDS = 60.0


def _configure_stdio_utf8() -> None:
    """Use the UTF-8 encoding required by MCP for stdin and stdout."""
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


class MemoryServerError(RuntimeError):
    """Raised when the underlying REST memory service cannot fulfill a request."""


def _load_env_file(path: str | None) -> None:
    """Load simple KEY=VALUE pairs without overwriting existing environment variables."""
    if not path or not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            name = name.strip()
            value = raw_value.strip()
            if not (value.startswith('"') or value.startswith("'")) and "#" in value:
                value = value.split("#", 1)[0].strip()
            value = value.strip('"').strip("'")
            os.environ.setdefault(name, value)


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _as_object(value: Any, *, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"{name} must be a JSON object")


def _as_messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("messages must be a list of message objects")
    messages: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"messages[{index}] must be an object")
        role = item.get("role")
        content = item.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"messages[{index}] must contain string role and content")
        messages.append(dict(item))
    return messages


def _scope_from_args(args: dict[str, Any]) -> dict[str, str]:
    return _drop_none(
        {
            "user_id": args.get("user_id"),
            "agent_id": args.get("agent_id"),
            "run_id": args.get("run_id"),
        }
    )


class MemoryHttpClient:
    """A small REST client for the existing improved memory HTTP service."""

    def __init__(self, base_url: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=timeout_seconds or self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise MemoryServerError(
                f"{method} {url} failed: {exc}. "
                "Enable the bundled service with `clawcodex-dev memory enable`."
            ) from exc

        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise MemoryServerError(
                f"{method} {url} returned HTTP {response.status_code}: {detail}"
            )

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        return self.request(
            "POST",
            path,
            params=params,
            json_body=json_body,
            timeout_seconds=timeout_seconds,
        )

    def put(self, path: str, *, json_body: Any | None = None) -> Any:
        return self.request("PUT", path, json_body=json_body)

    def delete(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, params=params)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def as_mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _scope_properties() -> dict[str, Any]:
    return {
        "user_id": {
            "type": "string",
            "description": "User scope to filter memories. Omit to use the server default.",
        },
        "agent_id": {
            "type": "string",
            "description": "Agent scope to filter memories. Omit unless scoping to a specific agent.",
        },
        "run_id": {
            "type": "string",
            "description": "Run/session scope to filter memories. Omit unless scoping to a specific session.",
        },
    }


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def build_tools(
    client: MemoryHttpClient,
    default_user_id: str | None = None,
    add_early_return_seconds: float = 8.0,
) -> dict[str, ToolSpec]:
    scope = _scope_properties()

    def _resolve_user_id(args: dict[str, Any]) -> str | None:
        """Return the explicit user_id from args, otherwise fall back to default_user_id."""
        return args.get("user_id") or default_user_id

    def _require_scope(args: dict[str, Any]) -> None:
        """Ensure at least one scope is available; raise if neither specified nor a default exists."""
        if not (
            args.get("user_id") or args.get("agent_id") or args.get("run_id") or default_user_id
        ):
            raise ValueError(
                "At least one of user_id, agent_id, or run_id is required to scope the memory"
            )

    def _add_with_early_return(payload: dict[str, Any]) -> Any:
        """POST /memories, returning early when the REST service is slow.

        For long text, mem0's LLM extraction + embedding + Qdrant write can take 30-60+ seconds.
        MCP clients (opencode, Claude Desktop) often time out before that. This function makes the
        HTTP call in a daemon thread and waits at most *add_early_return_seconds*. If REST responds
        in time, it returns the full result; otherwise it returns a "processing" response so the agent
        knows the add was submitted and can search again later.
        """
        if add_early_return_seconds <= 0:
            return client.post("/memories", json_body=payload, timeout_seconds=180)

        result_q: Queue = Queue()

        def _do_post() -> None:
            try:
                result_q.put(
                    ("ok", client.post("/memories", json_body=payload, timeout_seconds=180))
                )
            except Exception as exc:  # noqa: BLE001 - propagate to caller
                result_q.put(("error", exc))

        worker = threading.Thread(target=_do_post, daemon=True)
        worker.start()

        try:
            status, value = result_q.get(timeout=add_early_return_seconds)
            if status == "ok":
                return value
            raise value
        except Empty:
            return {
                "status": "processing",
                "message": (
                    "Memory add is being processed in the background (LLM extraction takes time). "
                    "Use memory_search or memory_list to retrieve stored memories later."
                ),
                "user_id": payload.get("user_id"),
                "agent_id": payload.get("agent_id"),
                "run_id": payload.get("run_id"),
            }

    def health(_: dict[str, Any]) -> Any:
        return client.get("/health")

    def add_text(args: dict[str, Any]) -> Any:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text is required")
        _require_scope(args)
        role = args.get("role") or "user"
        if role not in {"user", "assistant", "system"}:
            raise ValueError("role must be one of: user, assistant, system")
        metadata = _as_object(args.get("metadata"), name="metadata")
        payload = _drop_none(
            {
                "messages": [{"role": role, "content": text}],
                "user_id": _resolve_user_id(args),
                "agent_id": args.get("agent_id"),
                "run_id": args.get("run_id"),
                "metadata": metadata,
                "timestamp": args.get("timestamp"),
                "observation_date": args.get("observation_date"),
                "custom_instructions": args.get("custom_instructions"),
            }
        )
        return _add_with_early_return(payload)

    def add_messages(args: dict[str, Any]) -> Any:
        messages = _as_messages(args.get("messages"))
        _require_scope(args)
        metadata = _as_object(args.get("metadata"), name="metadata")
        payload = _drop_none(
            {
                "messages": messages,
                "user_id": _resolve_user_id(args),
                "agent_id": args.get("agent_id"),
                "run_id": args.get("run_id"),
                "metadata": metadata,
                "timestamp": args.get("timestamp"),
                "observation_date": args.get("observation_date"),
                "custom_instructions": args.get("custom_instructions"),
            }
        )
        return _add_with_early_return(payload)

    def search(args: dict[str, Any]) -> Any:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required")
        filters = _as_object(args.get("filters"), name="filters")
        payload = _drop_none(
            {
                "query": query,
                "user_id": _resolve_user_id(args),
                "agent_id": args.get("agent_id"),
                "run_id": args.get("run_id"),
                "limit": args.get("limit", 10),
                "filters": filters,
                "rerank": args.get("rerank"),
                "search_strategy": args.get("search_strategy"),
            }
        )
        return client.post("/search", json_body=payload)

    def list_memories(args: dict[str, Any]) -> Any:
        params = _scope_from_args(args)
        if not params:
            if default_user_id:
                params = {"user_id": default_user_id}
            else:
                raise ValueError("Provide at least one of user_id, agent_id, or run_id")
        return client.get("/memories", params=params)

    def get_memory(args: dict[str, Any]) -> Any:
        memory_id = args.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id is required")
        return client.get(f"/memories/{memory_id}")

    def update_memory(args: dict[str, Any]) -> Any:
        memory_id = args.get("memory_id")
        data = args.get("data")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id is required")
        if not isinstance(data, str) or not data.strip():
            raise ValueError("data is required")
        return client.put(f"/memories/{memory_id}", json_body={"data": data})

    def delete_memory(args: dict[str, Any]) -> Any:
        memory_id = args.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id is required")
        return client.delete(f"/memories/{memory_id}")

    def delete_all(args: dict[str, Any]) -> Any:
        if args.get("confirm") is not True:
            raise ValueError("Set confirm=true to delete all memories in the requested scope")
        params = _scope_from_args(args)
        if not params:
            if default_user_id:
                params = {"user_id": default_user_id}
            else:
                raise ValueError("Provide at least one of user_id, agent_id, or run_id")
        return client.delete("/memories", params=params)

    def history(args: dict[str, Any]) -> Any:
        memory_id = args.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValueError("memory_id is required")
        return client.get(f"/memories/{memory_id}/history")

    def crystallize(args: dict[str, Any]) -> Any:
        user_id = _resolve_user_id(args)
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id is required")
        params = {"user_id": user_id, "force": bool(args.get("force", False))}
        return client.post("/crystallize", params=params, timeout_seconds=180)

    def crystallize_status(_: dict[str, Any]) -> Any:
        return client.get("/crystallize/status")

    def crystallize_audit(args: dict[str, Any]) -> Any:
        return client.get("/crystallize/audit", params={"limit": args.get("limit", 10)})

    def crystallizer_stats(_: dict[str, Any]) -> Any:
        return client.get("/metrics/crystallizer-stats")

    def crystallizer_composition(args: dict[str, Any]) -> Any:
        user_id = _resolve_user_id(args)
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("user_id is required")
        return client.get("/metrics/crystallizer-composition", params={"user_id": user_id})

    schemas = {
        "add_common": {
            **scope,
            "metadata": {
                "type": "object",
                "description": "Optional metadata attached to the write.",
            },
            "timestamp": {"type": "integer", "description": "Optional Unix timestamp."},
            "observation_date": {
                "type": "string",
                "description": "Optional human-readable observation date.",
            },
            "custom_instructions": {
                "type": "string",
                "description": "Optional extraction instructions forwarded to the memory backend.",
            },
        }
    }

    tools = [
        ToolSpec(
            "memory_health",
            "Check whether the backing improved memory REST service is healthy.",
            _empty_schema(),
            health,
        ),
        ToolSpec(
            "memory_add_text",
            "Add one text message to long-term memory via POST /memories. Uses the default shared user scope if no user_id/agent_id/run_id is provided. Returns a 'processing' response if the LLM extraction takes too long; use memory_search to retrieve results later.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message text to store."},
                    "role": {
                        "type": "string",
                        "enum": ["user", "assistant", "system"],
                        "default": "user",
                        "description": "Who produced this message.",
                    },
                    **schemas["add_common"],
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            add_text,
        ),
        ToolSpec(
            "memory_add_messages",
            "Add a conversation message list to long-term memory via POST /memories. Uses the default shared user scope if no user_id/agent_id/run_id is provided. Returns a 'processing' response if the LLM extraction takes too long; use memory_search to retrieve results later.",
            {
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "description": "Conversation messages to ingest. The server extracts facts from them.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {
                                    "type": "string",
                                    "enum": ["user", "assistant", "system"],
                                    "description": "Who produced this message.",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "The message text.",
                                },
                            },
                            "required": ["role", "content"],
                            "additionalProperties": True,
                        },
                    },
                    **schemas["add_common"],
                },
                "required": ["messages"],
                "additionalProperties": False,
            },
            add_messages,
        ),
        ToolSpec(
            "memory_search",
            "Search memories semantically via POST /search.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    **scope,
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 1000,
                    },
                    "filters": {"type": "object", "description": "Optional metadata filters."},
                    "rerank": {"type": "boolean", "default": False},
                    "search_strategy": {
                        "type": "string",
                        "enum": ["layered", "crystal_boost"],
                        "description": "Optional crystallizer-aware search strategy.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            search,
        ),
        ToolSpec(
            "memory_list",
            "List memories via GET /memories, filtered by user_id / agent_id / run_id. Provide at least one of these fields; if none is given, the server's default user scope is used.",
            {
                "type": "object",
                "properties": scope,
                "additionalProperties": False,
            },
            list_memories,
        ),
        ToolSpec(
            "memory_get",
            "Read one memory by id via GET /memories/{memory_id}.",
            {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "ID of the target memory, as returned by memory_list or memory_search.",
                    }
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
            get_memory,
        ),
        ToolSpec(
            "memory_update",
            "Update one memory by id via PUT /memories/{memory_id}.",
            {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "ID of the memory to update."},
                    "data": {
                        "type": "string",
                        "description": "New memory text that replaces the existing content.",
                    },
                },
                "required": ["memory_id", "data"],
                "additionalProperties": False,
            },
            update_memory,
        ),
        ToolSpec(
            "memory_delete",
            "Delete one memory by id via DELETE /memories/{memory_id}.",
            {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "ID of the target memory, as returned by memory_list or memory_search.",
                    }
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
            delete_memory,
        ),
        ToolSpec(
            "memory_delete_all",
            "Delete all memories via DELETE /memories, filtered by user_id / agent_id / run_id. Requires confirm=true. Provide at least one scope field; if none is given, the server's default user scope is used.",
            {
                "type": "object",
                "properties": {
                    **scope,
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to perform the deletion.",
                    },
                },
                "required": ["confirm"],
                "additionalProperties": False,
            },
            delete_all,
        ),
        ToolSpec(
            "memory_history",
            "Read history for one memory via GET /memories/{memory_id}/history.",
            {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "ID of the target memory, as returned by memory_list or memory_search.",
                    }
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
            history,
        ),
        ToolSpec(
            "memory_crystallize",
            "Trigger semantic crystallization for a user via POST /crystallize.",
            {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User scope to crystallize."},
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, rerun crystallization even if no new memories were added since the last run.",
                    },
                },
                "required": ["user_id"],
                "additionalProperties": False,
            },
            crystallize,
        ),
        ToolSpec(
            "memory_crystallize_status",
            "Inspect semantic crystallizer status.",
            _empty_schema(),
            crystallize_status,
        ),
        ToolSpec(
            "memory_crystallize_audit",
            "Read recent semantic crystallizer audit records.",
            {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100}
                },
                "additionalProperties": False,
            },
            crystallize_audit,
        ),
        ToolSpec(
            "memory_crystallizer_stats",
            "Read semantic crystallizer aggregate metrics.",
            _empty_schema(),
            crystallizer_stats,
        ),
        ToolSpec(
            "memory_crystallizer_composition",
            "Read raw/crystallized memory composition for a user.",
            {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User scope to report composition for.",
                    }
                },
                "required": ["user_id"],
                "additionalProperties": False,
            },
            crystallizer_composition,
        ),
    ]
    return {tool.name: tool for tool in tools}


class StdioMcpServer:
    """A minimal MCP server based on newline-delimited JSON-RPC over stdio."""

    def __init__(self, tools: dict[str, ToolSpec]):
        self.tools = tools
        self.protocol_version = DEFAULT_PROTOCOL_VERSION

    def serve(self) -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write_error(None, -32700, f"Parse error: {exc}")
                continue
            message = sanitize_request_strings(message)

            if isinstance(message, list):
                for item in message:
                    self._handle(item)
            else:
                self._handle(message)

    def _handle(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._write_error(None, -32600, "Invalid Request")
            return

        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if not method:
            return
        if method.startswith("notifications/"):
            return

        try:
            result = self._dispatch(method, params if isinstance(params, dict) else {})
        except Exception as exc:
            self._write_error(request_id, -32603, str(exc))
            return

        if request_id is not None:
            self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            requested_version = params.get("protocolVersion")
            if isinstance(requested_version, str) and requested_version:
                self.protocol_version = requested_version
            return {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }

        if method == "ping":
            return {}

        if method == "tools/list":
            return {"tools": [tool.as_mcp_tool() for tool in self.tools.values()]}

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or name not in self.tools:
                raise ValueError(f"Unknown tool: {name}")
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            try:
                payload = self.tools[name].handler(arguments)
                return {"content": [{"type": "text", "text": _json_text(payload)}]}
            except Exception as exc:
                return {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                }

        if method == "resources/list":
            return {"resources": []}

        if method == "prompts/list":
            return {"prompts": []}

        raise ValueError(f"Unsupported MCP method: {method}")

    def _write(self, message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def _write_error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self._write({"jsonrpc": "2.0", "id": request_id, "error": error})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MCP stdio adapter for clawcodex_ext.latent_memory.server"
    )
    parser.add_argument(
        "--env-file",
        default=os.getenv("MEMORY_MCP_ENV_FILE"),
        help="Optional env file to read before connecting to the REST memory service.",
    )
    parser.add_argument(
        "--mem0-host",
        default=None,
        help="Backing REST memory service URL. Defaults to MEM0_HOST or http://127.0.0.1:8888.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("MEMORY_MCP_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        help="HTTP timeout in seconds for normal memory calls.",
    )
    parser.add_argument(
        "--default-user-id",
        default=os.getenv("MEMORY_MCP_DEFAULT_USER_ID"),
        help="Fallback user_id when the caller omits user_id/agent_id/run_id. "
        "Enables a shared memory scope across sessions. "
        "Defaults to env MEMORY_MCP_DEFAULT_USER_ID.",
    )
    parser.add_argument(
        "--add-early-return-seconds",
        type=float,
        default=float(os.getenv("MEMORY_MCP_ADD_EARLY_RETURN_SECONDS", "8")),
        help="Seconds to wait for POST /memories before returning a 'processing' "
        "response. mem0's LLM extraction can take 30-60+ seconds; this lets the "
        "MCP client get a quick response while the REST service continues in the "
        "background. Set to 0 to disable early return (wait up to 180s). "
        "Must be shorter than the MCP client's tool-call timeout (opencode default 30s). "
        "Defaults to env MEMORY_MCP_ADD_EARLY_RETURN_SECONDS (8).",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the MCP tool list and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Call the backing /health endpoint and print the result.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
    args = _parse_args(argv)
    _load_env_file(args.env_file)
    host = (args.mem0_host or os.getenv("MEM0_HOST") or DEFAULT_MEM0_HOST).rstrip("/")
    client = MemoryHttpClient(host, timeout_seconds=args.timeout)
    tools = build_tools(
        client,
        default_user_id=args.default_user_id,
        add_early_return_seconds=args.add_early_return_seconds,
    )

    if args.list_tools:
        print(_json_text({"tools": [tool.as_mcp_tool() for tool in tools.values()]}))
        return 0

    if args.self_test:
        print(_json_text({"mem0_host": host, "health": client.get("/health")}))
        return 0

    StdioMcpServer(tools).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

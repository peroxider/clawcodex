"""Core request handling for the Hermes-compatible remote API."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auth import require_bearer_auth, resolve_api_key
from .errors import RemoteAPIError
from .normalization import (
    merge_instructions,
    normalize_chat_messages,
    normalize_responses_input,
    reject_workspace_override,
)
from .runner import (
    RemoteAgentRunner,
    RemotePermissionMode,
    RemoteRunConfig,
    RemoteRunComplete,
    RemoteRunResult,
    RemoteTextDelta,
    RemoteToolCall,
    RemoteToolResult,
)
from .sse import chat_chunk, chat_usage_chunk, encode_done, encode_sse
from .state import ResponseStore, StoredResponse
from clawcodex_ext.types.content_blocks import ImageBlock, TextBlock


API_MODEL_NAME = "clawcodex-agent"


class _ConversationLock:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.refs = 0


@dataclass(frozen=True)
class RemoteAPIConfig:
    """Runtime configuration for the remote API server."""

    workspace: Path
    host: str = "127.0.0.1"
    port: int = 8642
    provider: str | None = None
    model: str | None = None
    max_turns: int = 20
    permission_mode: RemotePermissionMode = "bypassPermissions"
    timeout_seconds: float = 600.0
    state_limit: int = 128
    api_key: str | None = None


class RemoteAPIService:
    """Hermes-compatible API service with process-local state."""

    def __init__(self, config: RemoteAPIConfig) -> None:
        self.config = config
        self._active_lock = threading.Lock()
        self._active_runs = 0
        self._started_at = time.time()
        self._api_key = resolve_api_key(config.api_key)
        self._responses = ResponseStore(config.state_limit)
        self._conversation_locks_guard = threading.Lock()
        self._conversation_locks: dict[str, _ConversationLock] = {}

    @property
    def auth_required(self) -> bool:
        return bool(self._api_key)

    def require_auth(self, authorization: str | None) -> None:
        require_bearer_auth(self._api_key, authorization)

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
            "model": self.advertised_model(),
            "provider": self.config.provider or "default",
        }

    def detailed_health(self) -> dict[str, Any]:
        counts = self._responses.counts()
        return {
            **self.health(),
            "uptime_seconds": max(0, int(time.time() - self._started_at)),
            "auth": {
                "type": "bearer",
                "required": self.auth_required,
            },
            "active_runs": self.active_runs,
            "stored_responses": counts["responses"],
            "conversations": counts["conversations"],
            "state_limit": counts["limit"],
        }

    @property
    def active_runs(self) -> int:
        with self._active_lock:
            return self._active_runs

    def advertised_model(self) -> str:
        return self.config.model or API_MODEL_NAME

    def models(self) -> dict[str, Any]:
        model = self.advertised_model()
        return {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": int(self._started_at),
                    "owned_by": "clawcodex",
                }
            ],
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "object": "hermes.api_server.capabilities",
            "platform": "clawcodex",
            "model": self.advertised_model(),
            "auth": {
                "type": "bearer",
                "required": self.auth_required,
            },
            "features": {
                "chat_completions": True,
                "responses_api": True,
                "chat_streaming": True,
                "responses_streaming": True,
                "data_image_input": True,
                "remote_image_input": False,
                "run_submission": False,
                "run_status": False,
                "run_events_sse": False,
                "run_stop": False,
                "sessions_api": False,
                "cron_jobs": False,
            },
        }

    async def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        prepared = self.prepare_chat_completion(body)

        result = await self._run_agent(
            messages=prepared["messages"],
            instructions=prepared["instructions"],
            model=prepared["query_model"],
            run_id=prepared["run_id"],
        )
        return _chat_completion_payload(
            prepared["run_id"],
            prepared["response_model"],
            result,
        )

    def prepare_chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize a chat request before HTTP streaming starts."""

        reject_workspace_override(body)
        _validate_common_request_fields(body)
        normalized = normalize_chat_messages(body.get("messages"))
        return {
            "messages": normalized.messages,
            "instructions": normalized.instructions,
            "response_model": str(body.get("model") or self.advertised_model()),
            "query_model": _resolve_query_model(body.get("model"), self.config.model),
            "run_id": f"chatcmpl_{uuid.uuid4().hex}",
            "include_usage": _chat_include_usage(body),
        }

    async def chat_completion_sse(self, body: dict[str, Any]) -> list[str]:
        return [frame async for frame in self.chat_completion_sse_events(body)]

    async def chat_completion_sse_events(
        self,
        body: dict[str, Any],
        *,
        prepared: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        prepared = prepared or self.prepare_chat_completion(body)
        response_model = prepared["response_model"]
        run_id = prepared["run_id"]
        include_usage = prepared["include_usage"]
        created = int(time.time())

        failed = False
        complete: RemoteRunComplete | None = None
        yield encode_sse(
            chat_chunk(
                chunk_id=run_id,
                created=created,
                model=response_model,
                delta={"role": "assistant", "content": ""},
                include_usage=include_usage,
            )
        )
        try:
            async for event in self._stream_agent(
                messages=prepared["messages"],
                instructions=prepared["instructions"],
                model=prepared["query_model"],
                run_id=run_id,
            ):
                if isinstance(event, RemoteTextDelta) and event.content:
                    yield encode_sse(
                        chat_chunk(
                            chunk_id=run_id,
                            created=created,
                            model=response_model,
                            delta={"content": event.content},
                            include_usage=include_usage,
                        )
                    )
                elif isinstance(event, RemoteRunComplete):
                    complete = event
        except RemoteAPIError as exc:
            failed = True
            yield encode_sse(_stream_error_payload(exc), event="error")
        if not failed:
            yield encode_sse(
                chat_chunk(
                    chunk_id=run_id,
                    created=created,
                    model=response_model,
                    delta={},
                    finish_reason="stop",
                    include_usage=include_usage,
                )
            )
            if include_usage:
                yield encode_sse(
                    chat_usage_chunk(
                        chunk_id=run_id,
                        created=created,
                        model=response_model,
                        usage=_openai_usage(complete.usage if complete else {}),
                    )
                )
        yield encode_done()

    def validate_responses_request(self, body: dict[str, Any]) -> None:
        """Reject malformed Responses requests before sending SSE headers."""

        reject_workspace_override(body)
        _validate_common_request_fields(body)
        previous_response_id = _optional_string_field(body, "previous_response_id")
        conversation = _optional_conversation_id(body.get("conversation"))
        if previous_response_id and conversation:
            raise RemoteAPIError(400, "previous_response_id and conversation cannot both be set")
        _optional_string_field(body, "instructions")
        normalize_responses_input(body.get("input"))
        if previous_response_id and self._responses.get(previous_response_id) is None:
            raise RemoteAPIError(404, f"response not found: {previous_response_id}")

    async def responses(self, body: dict[str, Any]) -> dict[str, Any]:
        conversation = _optional_conversation_id(body.get("conversation"))
        async with self._conversation_scope(conversation):
            response, _result = await self._responses_impl(body)
            return response

    async def responses_sse(self, body: dict[str, Any]) -> list[str]:
        return [frame async for frame in self.responses_sse_events(body)]

    async def responses_sse_events(self, body: dict[str, Any]) -> AsyncIterator[str]:
        try:
            conversation = _optional_conversation_id(body.get("conversation"))
        except RemoteAPIError as exc:
            yield encode_sse(_stream_error_payload(exc), event="error")
            return
        async with self._conversation_scope(conversation):
            try:
                prepared = self._prepare_responses_run(body)
            except RemoteAPIError as exc:
                yield encode_sse(_stream_error_payload(exc), event="error")
                return

            message_item = _response_message_item(prepared["response_id"], "")
            response_created = _responses_base_payload(
                response_id=prepared["response_id"],
                model=prepared["response_model"],
                previous_response_id=prepared["previous_response_id"],
                conversation=prepared["conversation"],
                store=prepared["should_store"],
                status="in_progress",
                completed_at=None,
                output=[],
                output_text="",
                usage=None,
                instructions=prepared["instructions"] or None,
                created_at=prepared["created_at"],
            )
            sequence_number = 1
            yield encode_sse(
                {
                    "type": "response.created",
                    "response": response_created,
                    "sequence_number": sequence_number,
                },
                event="response.created",
            )
            sequence_number += 1
            yield encode_sse(
                {
                    "type": "response.in_progress",
                    "response": response_created,
                    "sequence_number": sequence_number,
                },
                event="response.in_progress",
            )
            sequence_number += 1

            text_parts: list[str] = []
            events: list[Any] = []
            output_items: list[dict[str, Any]] = []
            pending_call_ids: dict[str, list[str]] = {}
            next_output_index = 0
            message_output_index: int | None = None
            complete: RemoteRunComplete | None = None
            try:
                async for event in self._stream_agent(
                    messages=prepared["messages"],
                    instructions=prepared["instructions"],
                    model=prepared["query_model"],
                    run_id=prepared["response_id"],
                    session_id=prepared["session_id"],
                ):
                    events.append(event)
                    if isinstance(event, RemoteTextDelta) and event.content:
                        if message_output_index is None:
                            message_output_index = next_output_index
                            next_output_index += 1
                            output_items.append(message_item)
                            yield encode_sse(
                                {
                                    "type": "response.output_item.added",
                                    "output_index": message_output_index,
                                    "item": {
                                        **message_item,
                                        "status": "in_progress",
                                        "content": [],
                                    },
                                    "sequence_number": sequence_number,
                                },
                                event="response.output_item.added",
                            )
                            sequence_number += 1
                            yield encode_sse(
                                {
                                    "type": "response.content_part.added",
                                    "item_id": message_item["id"],
                                    "output_index": message_output_index,
                                    "content_index": 0,
                                    "part": {
                                        "type": "output_text",
                                        "text": "",
                                        "annotations": [],
                                    },
                                    "sequence_number": sequence_number,
                                },
                                event="response.content_part.added",
                            )
                            sequence_number += 1
                        text_parts.append(event.content)
                        yield encode_sse(
                            {
                                "type": "response.output_text.delta",
                                "item_id": message_item["id"],
                                "output_index": message_output_index,
                                "content_index": 0,
                                "delta": event.content,
                                "sequence_number": sequence_number,
                            },
                            event="response.output_text.delta",
                        )
                        sequence_number += 1
                    elif isinstance(event, RemoteToolCall):
                        item = _response_tool_call_item(
                            event,
                            prepared["response_id"],
                            next_output_index,
                        )
                        output_items.append(item)
                        _remember_pending_call(pending_call_ids, event, item["call_id"])
                        async for frame in self._response_output_item_frames(
                            item=item,
                            output_index=next_output_index,
                            sequence_number=sequence_number,
                        ):
                            yield frame
                            sequence_number += 1
                        next_output_index += 1
                    elif isinstance(event, RemoteToolResult):
                        fallback_call_id = _take_pending_call(pending_call_ids, event)
                        item = _response_tool_result_item(
                            event,
                            prepared["response_id"],
                            next_output_index,
                            fallback_call_id=fallback_call_id,
                        )
                        output_items.append(item)
                        async for frame in self._response_output_item_frames(
                            item=item,
                            output_index=next_output_index,
                            sequence_number=sequence_number,
                        ):
                            yield frame
                            sequence_number += 1
                        next_output_index += 1
                    elif isinstance(event, RemoteRunComplete):
                        complete = event
            except RemoteAPIError as exc:
                failed_message = _response_message_item(
                    prepared["response_id"],
                    "".join(text_parts),
                )
                failed_output = [
                    failed_message if item["id"] == message_item["id"] else item
                    for item in output_items
                ]
                if message_output_index is not None:
                    failed_message["status"] = "incomplete"
                failed_response = _responses_base_payload(
                    response_id=prepared["response_id"],
                    model=prepared["response_model"],
                    previous_response_id=prepared["previous_response_id"],
                    conversation=prepared["conversation"],
                    store=prepared["should_store"],
                    status="failed",
                    completed_at=int(time.time()),
                    output=failed_output,
                    output_text="".join(text_parts),
                    usage=None,
                    instructions=prepared["instructions"] or None,
                    created_at=prepared["created_at"],
                    error={
                        "message": exc.detail,
                        "type": exc.error_type,
                        "code": exc.code,
                    },
                )
                yield encode_sse(
                    {
                        "type": "response.failed",
                        "response": failed_response,
                        "sequence_number": sequence_number,
                    },
                    event="response.failed",
                )
                return

            text = (
                complete.response_text
                if complete is not None and complete.response_text
                else "".join(text_parts)
            )
            usage = dict(complete.usage if complete is not None else {})
            messages = complete.messages if complete is not None else list(prepared["messages"])
            message_item = _response_message_item(prepared["response_id"], text)
            if message_output_index is None:
                message_output_index = next_output_index
                output_items.append(message_item)
                yield encode_sse(
                    {
                        "type": "response.output_item.added",
                        "output_index": message_output_index,
                        "item": {**message_item, "status": "in_progress", "content": []},
                        "sequence_number": sequence_number,
                    },
                    event="response.output_item.added",
                )
                sequence_number += 1
                yield encode_sse(
                    {
                        "type": "response.content_part.added",
                        "item_id": message_item["id"],
                        "output_index": message_output_index,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                        "sequence_number": sequence_number,
                    },
                    event="response.content_part.added",
                )
                sequence_number += 1
            output_items = [
                message_item if item["id"] == message_item["id"] else item for item in output_items
            ]
            result = RemoteRunResult(
                text=text,
                reason=complete.reason if complete is not None else "success",
                usage=usage,
                messages=messages,
                events=events,
            )
            response = _responses_payload(
                response_id=prepared["response_id"],
                model=prepared["response_model"],
                result=result,
                previous_response_id=prepared["previous_response_id"],
                conversation=prepared["conversation"],
                store=prepared["should_store"],
                instructions=prepared["instructions"] or None,
                output=output_items,
                created_at=prepared["created_at"],
            )
            if prepared["should_store"]:
                self._responses.put(
                    prepared["response_id"],
                    response,
                    messages,
                    prepared["input_items"],
                    conversation=prepared["conversation"],
                    session_id=prepared["session_id"],
                )

            yield encode_sse(
                {
                    "type": "response.output_text.done",
                    "item_id": message_item["id"],
                    "output_index": message_output_index,
                    "content_index": 0,
                    "text": result.text,
                    "sequence_number": sequence_number,
                },
                event="response.output_text.done",
            )
            sequence_number += 1
            yield encode_sse(
                {
                    "type": "response.content_part.done",
                    "item_id": message_item["id"],
                    "output_index": message_output_index,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": result.text,
                        "annotations": [],
                    },
                    "sequence_number": sequence_number,
                },
                event="response.content_part.done",
            )
            sequence_number += 1
            yield encode_sse(
                {
                    "type": "response.output_item.done",
                    "output_index": message_output_index,
                    "item": message_item,
                    "sequence_number": sequence_number,
                },
                event="response.output_item.done",
            )
            sequence_number += 1
            yield encode_sse(
                {
                    "type": "response.completed",
                    "response": response,
                    "sequence_number": sequence_number,
                },
                event="response.completed",
            )

    async def _response_output_item_frames(
        self,
        *,
        item: dict[str, Any],
        output_index: int,
        sequence_number: int,
    ) -> AsyncIterator[str]:
        """Emit SSE frames for one output item (added → … → done).

        For ``function_call`` items this includes the REQUIRED intermediate
        ``function_call_arguments.delta`` / ``function_call_arguments.done``
        events that the OpenAI Responses API expects.  Skipping those
        events causes clients (including Open WebUI) to lose track of the
        call and ignore its paired ``function_call_output``.
        """
        item_type = item.get("type", "")
        item_id = item["id"]

        yield encode_sse(
            {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": {**item, "status": "in_progress"},
                "sequence_number": sequence_number,
            },
            event="response.output_item.added",
        )

        if item_type == "function_call":
            arguments = item.get("arguments", "")
            yield encode_sse(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": item_id,
                    "output_index": output_index,
                    "delta": arguments,
                    "sequence_number": sequence_number + 1,
                },
                event="response.function_call_arguments.delta",
            )
            yield encode_sse(
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": item_id,
                    "output_index": output_index,
                    "arguments": arguments,
                    "sequence_number": sequence_number + 2,
                },
                event="response.function_call_arguments.done",
            )
            yield encode_sse(
                {
                    "type": "response.output_item.done",
                    "output_index": output_index,
                    "item": {**item, "status": "completed"},
                    "sequence_number": sequence_number + 3,
                },
                event="response.output_item.done",
            )
        else:
            yield encode_sse(
                {
                    "type": "response.output_item.done",
                    "output_index": output_index,
                    "item": {**item, "status": "completed"},
                    "sequence_number": sequence_number + 1,
                },
                event="response.output_item.done",
            )

    @asynccontextmanager
    async def _conversation_scope(self, conversation: str | None) -> AsyncIterator[None]:
        if not conversation:
            yield
            return
        entry = self._claim_conversation_lock(conversation)
        acquired = False
        try:
            while not acquired:
                acquired = entry.lock.acquire(blocking=False)
                if not acquired:
                    await asyncio.sleep(0.01)
            yield
        finally:
            if acquired:
                entry.lock.release()
            self._release_conversation_lock(conversation, entry)

    def _claim_conversation_lock(self, conversation: str) -> _ConversationLock:
        with self._conversation_locks_guard:
            entry = self._conversation_locks.get(conversation)
            if entry is None:
                entry = _ConversationLock()
                self._conversation_locks[conversation] = entry
            entry.refs += 1
            return entry

    def _release_conversation_lock(
        self,
        conversation: str,
        entry: _ConversationLock,
    ) -> None:
        with self._conversation_locks_guard:
            current = self._conversation_locks.get(conversation)
            if current is entry:
                entry.refs = max(0, entry.refs - 1)
            self._prune_conversation_locks_locked()

    def _prune_conversation_locks_locked(self) -> None:
        max_locks = max(16, self.config.state_limit * 2)
        if len(self._conversation_locks) <= max_locks:
            return
        for name, entry in list(self._conversation_locks.items()):
            if entry.refs == 0 and not entry.lock.locked():
                self._conversation_locks.pop(name, None)
                if len(self._conversation_locks) <= max_locks:
                    break

    def get_response(self, response_id: str) -> dict[str, Any]:
        stored = self._responses.get(response_id)
        if stored is None:
            raise RemoteAPIError(404, f"response not found: {response_id}")
        return stored.response

    def get_response_input_items(self, response_id: str) -> dict[str, Any]:
        stored = self._responses.get(response_id)
        if stored is None:
            raise RemoteAPIError(404, f"response not found: {response_id}")
        data = list(stored.input_items)
        return {
            "object": "list",
            "data": data,
            "first_id": data[0]["id"] if data else None,
            "last_id": data[-1]["id"] if data else None,
            "has_more": False,
        }

    def delete_response(self, response_id: str) -> dict[str, Any]:
        if not self._responses.delete(response_id):
            raise RemoteAPIError(404, f"response not found: {response_id}")
        return {
            "id": response_id,
            "object": "response.deleted",
            "deleted": True,
        }

    def _prepare_responses_run(self, body: dict[str, Any]) -> dict[str, Any]:
        reject_workspace_override(body)
        _validate_common_request_fields(body)
        previous_response_id = _optional_string_field(body, "previous_response_id")
        conversation = _optional_conversation_id(body.get("conversation"))
        if previous_response_id and conversation:
            raise RemoteAPIError(
                400,
                "previous_response_id and conversation cannot both be set",
            )
        instructions = _optional_string_field(body, "instructions") or ""
        response_model = str(body.get("model") or self.advertised_model())
        query_model = _resolve_query_model(body.get("model"), self.config.model)
        response_id = f"resp_{uuid.uuid4().hex}"
        created_at = int(time.time())

        base: StoredResponse | None = None
        if previous_response_id:
            base = self._responses.get(previous_response_id)
            if base is None:
                raise RemoteAPIError(404, f"response not found: {previous_response_id}")
        elif conversation:
            base = self._responses.latest_for_conversation(conversation)

        normalized = normalize_responses_input(body.get("input"))
        input_items = _response_input_items(response_id, normalized.messages)
        messages = [*(base.messages if base is not None else []), *normalized.messages]
        merged_instructions = merge_instructions(
            instructions,
            normalized.instructions,
        )
        should_store = body.get("store", True) is not False or bool(
            previous_response_id or conversation
        )
        return {
            "response_id": response_id,
            "created_at": created_at,
            "response_model": response_model,
            "query_model": query_model,
            "previous_response_id": previous_response_id,
            "conversation": conversation,
            "session_id": (
                base.session_id if base is not None and base.session_id else response_id
            ),
            "messages": messages,
            "input_items": input_items,
            "instructions": merged_instructions,
            "should_store": should_store,
        }

    async def _responses_impl(self, body: dict[str, Any]) -> tuple[dict[str, Any], RemoteRunResult]:
        prepared = self._prepare_responses_run(body)
        result = await self._run_agent(
            messages=prepared["messages"],
            instructions=prepared["instructions"],
            model=prepared["query_model"],
            run_id=prepared["response_id"],
            session_id=prepared["session_id"],
        )
        response = _responses_payload(
            response_id=prepared["response_id"],
            model=prepared["response_model"],
            result=result,
            previous_response_id=prepared["previous_response_id"],
            conversation=prepared["conversation"],
            store=prepared["should_store"],
            instructions=prepared["instructions"] or None,
            created_at=prepared["created_at"],
        )
        if prepared["should_store"]:
            self._responses.put(
                prepared["response_id"],
                response,
                result.messages,
                prepared["input_items"],
                conversation=prepared["conversation"],
                session_id=prepared["session_id"],
            )
        return response, result

    async def _run_agent(
        self,
        *,
        messages: list[Any],
        instructions: str,
        model: str | None,
        run_id: str,
        session_id: str | None = None,
    ) -> RemoteRunResult:
        with self._active_lock:
            self._active_runs += 1
        try:
            import asyncio

            runner = RemoteAgentRunner(
                RemoteRunConfig(
                    workspace=self.config.workspace,
                    provider=self.config.provider,
                    model=model,
                    max_turns=self.config.max_turns,
                    permission_mode=self.config.permission_mode,
                    session_id=session_id,
                ),
                messages=messages,
                instructions=instructions,
                run_id=run_id,
            )
            try:
                result = await asyncio.wait_for(
                    runner.run(),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError as exc:
                raise RemoteAPIError(504, "agent run timed out") from exc
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
                raise RemoteAPIError(500, f"agent run failed: exit_code={code}") from exc
            if result.reason != "success":
                raise RemoteAPIError(500, f"agent run failed: {result.reason}")
            return result
        finally:
            with self._active_lock:
                self._active_runs = max(0, self._active_runs - 1)

    async def _stream_agent(
        self,
        *,
        messages: list[Any],
        instructions: str,
        model: str | None,
        run_id: str,
        session_id: str | None = None,
    ) -> AsyncIterator[Any]:
        with self._active_lock:
            self._active_runs += 1
        try:
            runner = RemoteAgentRunner(
                RemoteRunConfig(
                    workspace=self.config.workspace,
                    provider=self.config.provider,
                    model=model,
                    max_turns=self.config.max_turns,
                    permission_mode=self.config.permission_mode,
                    session_id=session_id,
                ),
                messages=messages,
                instructions=instructions,
                run_id=run_id,
            )
            deadline = time.monotonic() + self.config.timeout_seconds
            stream = runner.stream()
            stream_iter = stream.__aiter__()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RemoteAPIError(504, "agent run timed out")
                try:
                    event = await asyncio.wait_for(stream_iter.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise RemoteAPIError(504, "agent run timed out") from exc
                if isinstance(event, RemoteRunComplete) and event.reason != "success":
                    raise RemoteAPIError(500, f"agent run failed: {event.reason}")
                yield event
        finally:
            if "stream" in locals():
                await stream.aclose()
            with self._active_lock:
                self._active_runs = max(0, self._active_runs - 1)


def _chat_completion_payload(
    run_id: str,
    model: str,
    result: RemoteRunResult,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": _openai_usage(result.usage),
    }


def _responses_payload(
    *,
    response_id: str,
    model: str,
    result: RemoteRunResult,
    previous_response_id: str | None,
    conversation: str | None,
    store: bool,
    instructions: str | None = None,
    output: list[dict[str, Any]] | None = None,
    created_at: int | None = None,
) -> dict[str, Any]:
    response_output = (
        output
        if output is not None
        else _response_output_items(response_id, result.text, result.events)
    )
    response_created_at = created_at or int(time.time())
    payload = _responses_base_payload(
        response_id=response_id,
        model=model,
        previous_response_id=previous_response_id,
        conversation=conversation,
        store=store,
        status="completed",
        completed_at=int(time.time()),
        output=response_output,
        output_text=result.text,
        usage=_responses_usage(result.usage),
        created_at=response_created_at,
        instructions=instructions,
    )
    return payload


def _responses_base_payload(
    *,
    response_id: str,
    model: str,
    previous_response_id: str | None,
    conversation: str | None,
    store: bool,
    status: str,
    completed_at: int | None,
    output: list[dict[str, Any]],
    output_text: str,
    usage: dict[str, Any] | None,
    created_at: int | None = None,
    instructions: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": response_id,
        "object": "response",
        "created_at": created_at or int(time.time()),
        "status": status,
        "completed_at": completed_at,
        "error": error,
        "incomplete_details": None,
        "instructions": instructions,
        "max_output_tokens": None,
        "model": model,
        "output": output,
        "output_text": output_text,
        "parallel_tool_calls": True,
        "previous_response_id": previous_response_id,
        "reasoning": {"effort": None, "summary": None},
        "store": store,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": {},
    }
    if conversation:
        payload["conversation"] = {"id": conversation}
    return payload


def _response_output_items(
    response_id: str,
    text: str,
    events: list[Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    pending_call_ids: dict[str, list[str]] = {}
    for event in events:
        if isinstance(event, RemoteToolCall):
            item = _response_tool_call_item(event, response_id, len(output))
            output.append(item)
            _remember_pending_call(pending_call_ids, event, item["call_id"])
        elif isinstance(event, RemoteToolResult):
            fallback_call_id = _take_pending_call(pending_call_ids, event)
            output.append(
                _response_tool_result_item(
                    event,
                    response_id,
                    len(output),
                    fallback_call_id=fallback_call_id,
                )
            )
    output.append(_response_message_item(response_id, text))
    return output


def _response_message_item(response_id: str, text: str) -> dict[str, Any]:
    return {
        "id": f"msg_{response_id.removeprefix('resp_')}",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": text,
                "annotations": [],
            }
        ],
    }


def _response_input_items(response_id: str, messages: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    suffix = response_id.removeprefix("resp_")
    for index, message in enumerate(messages):
        role = getattr(message, "role", "user")
        if role not in {"user", "assistant", "system"}:
            role = "user"
        items.append(
            {
                "id": f"msg_{suffix}_input_{index}",
                "type": "message",
                "role": role,
                "content": _response_input_content(getattr(message, "content", "")),
            }
        )
    return items


def _response_input_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        return [{"type": "input_text", "text": str(content)}]
    out: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, TextBlock):
            out.append({"type": "input_text", "text": block.text})
        elif isinstance(block, ImageBlock):
            source = block.source
            media_type = str(source.get("media_type", "image/png"))
            data = str(source.get("data", ""))
            out.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{media_type};base64,{data}",
                }
            )
        else:
            text = getattr(block, "text", None)
            out.append({"type": "input_text", "text": str(text if text is not None else block)})
    return out


def _response_tool_call_item(
    event: RemoteToolCall,
    response_id: str,
    output_index: int,
) -> dict[str, Any]:
    suffix = response_id.removeprefix("resp_")
    return {
        "id": f"fc_{suffix}_{output_index}",
        "type": "function_call",
        "status": "completed",
        "name": event.tool_name,
        "arguments": _json_or_string(event.params),
        "call_id": event.tool_use_id or f"call_{suffix}_{output_index}",
    }


def _remember_pending_call(
    pending_call_ids: dict[str, list[str]],
    event: RemoteToolCall,
    call_id: str,
) -> None:
    if event.tool_name:
        pending_call_ids.setdefault(event.tool_name, []).append(call_id)


def _take_pending_call(
    pending_call_ids: dict[str, list[str]],
    event: RemoteToolResult,
) -> str | None:
    """Consume a call pairing, preferring the event's exact tool-use ID."""
    call_ids = pending_call_ids.get(event.tool_name, [])
    if event.tool_use_id:
        try:
            call_ids.remove(event.tool_use_id)
        except ValueError:
            pass
        return None
    return call_ids.pop(0) if call_ids else None


def _response_tool_result_item(
    event: RemoteToolResult,
    response_id: str,
    output_index: int,
    *,
    fallback_call_id: str | None = None,
) -> dict[str, Any]:
    suffix = response_id.removeprefix("resp_")
    # event.result is a wrapper dict {"output": …, "is_error": …}.
    # Open WebUI consumes Responses tool output as an array of input content
    # parts and calls ``part.get(...)`` on every entry.  The Responses API
    # permits either a string or content-part array here; use the array form
    # so tool output renders in Open WebUI and remains safe on the next turn.
    actual_output = (
        event.result.get("output", "") if isinstance(event.result, dict) else event.result
    )
    return {
        "id": f"fco_{suffix}_{output_index}",
        "type": "function_call_output",
        "status": "completed",
        "call_id": event.tool_use_id or fallback_call_id or f"call_{suffix}_{output_index}",
        "output": [
            {
                "type": "input_text",
                "text": _json_or_string(actual_output),
            }
        ],
    }


def _json_or_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _openai_usage(usage: dict[str, Any]) -> dict[str, int]:
    input_tokens = _int_usage(usage, "input_tokens")
    output_tokens = _int_usage(usage, "output_tokens")
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _responses_usage(usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _int_usage(usage, "input_tokens")
    output_tokens = _int_usage(usage, "output_tokens")
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {
            "cached_tokens": _first_int_usage(
                usage,
                "cached_tokens",
                "cache_read_input_tokens",
            )
        },
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": _int_usage(usage, "reasoning_tokens")},
        "total_tokens": input_tokens + output_tokens,
    }


def _int_usage(usage: dict[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _first_int_usage(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key in usage:
            return _int_usage(usage, key)
    return 0


def _optional_string_field(body: dict[str, Any], field: str) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RemoteAPIError(400, f"{field} must be a string")
    return value or None


def _validate_common_request_fields(body: dict[str, Any]) -> None:
    model = body.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise RemoteAPIError(400, "model must be a non-empty string")
    for field in ("stream", "store"):
        value = body.get(field)
        if value is not None and not isinstance(value, bool):
            raise RemoteAPIError(400, f"{field} must be a boolean")


def _chat_include_usage(body: dict[str, Any]) -> bool:
    options = body.get("stream_options")
    if options is None:
        return False
    if not isinstance(options, dict):
        raise RemoteAPIError(400, "stream_options must be an object")
    include_usage = options.get("include_usage", False)
    if not isinstance(include_usage, bool):
        raise RemoteAPIError(400, "stream_options.include_usage must be a boolean")
    if body.get("stream") is not True:
        raise RemoteAPIError(400, "stream_options is only supported when stream is true")
    return include_usage


def _optional_conversation_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        raw_id = value.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            return raw_id.strip()
    raise RemoteAPIError(400, "conversation must be a string or object with an id")


def _stream_error_payload(exc: RemoteAPIError) -> dict[str, Any]:
    return {
        "error": {
            "message": exc.detail,
            "type": exc.error_type,
            "code": exc.code,
        }
    }


def _resolve_query_model(request_model: Any, service_model: str | None) -> str | None:
    if isinstance(request_model, str) and request_model and request_model != API_MODEL_NAME:
        return request_model
    if service_model and service_model != API_MODEL_NAME:
        return service_model
    return None


__all__ = [
    "API_MODEL_NAME",
    "RemoteAPIConfig",
    "RemoteAPIError",
    "RemoteAPIService",
]

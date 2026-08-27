from __future__ import annotations

import copy
import contextlib
import contextvars
import threading
from typing import Any, Iterator


_SUPPRESS_TOKEN_USAGE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "memory_token_usage_suppressed",
    default=False,
)


@contextlib.contextmanager
def suppress_token_usage() -> Iterator[None]:
    """Temporarily exclude OpenAI calls from the memory-write token stats."""
    token = _SUPPRESS_TOKEN_USAGE.set(True)
    try:
        yield
    finally:
        _SUPPRESS_TOKEN_USAGE.reset(token)


class TokenUsageTracker:
    """In-process token usage tracker for memory-write LLM calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._stats = self._empty_stats()
        self._patched = False

    @staticmethod
    def _empty_stats() -> dict[str, Any]:
        return {
            "enabled": False,
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "add_requests_total": 0,
            "add_requests_forwarded_to_mem0": 0,
            "add_requests_skipped": 0,
            "calls": [],
        }

    def reset(self, enabled: bool = True) -> dict[str, Any]:
        with self._lock:
            self._enabled = enabled
            self._stats = self._empty_stats()
            self._stats["enabled"] = enabled
        if enabled:
            self.patch_openai()
        return self.snapshot()

    def disable(self) -> dict[str, Any]:
        with self._lock:
            self._enabled = False
            self._stats["enabled"] = False
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = copy.deepcopy(self._stats)
            data["enabled"] = self._enabled
            return data

    def record_add_request(self, *, forwarded: bool) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._stats["add_requests_total"] += 1
            if forwarded:
                self._stats["add_requests_forwarded_to_mem0"] += 1
            else:
                self._stats["add_requests_skipped"] += 1

    def record_response(self, response: Any, *, provider: str = "openai") -> None:
        if not self._enabled:
            return
        if _SUPPRESS_TOKEN_USAGE.get():
            return

        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return

        prompt_tokens = self._get_usage_value(usage, "prompt_tokens")
        completion_tokens = self._get_usage_value(usage, "completion_tokens")
        total_tokens = self._get_usage_value(usage, "total_tokens")

        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return

        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        total = int(total_tokens if total_tokens is not None else prompt + completion)

        model = getattr(response, "model", None)
        if model is None and isinstance(response, dict):
            model = response.get("model")

        with self._lock:
            self._stats["llm_calls"] += 1
            self._stats["prompt_tokens"] += prompt
            self._stats["completion_tokens"] += completion
            self._stats["total_tokens"] += total
            self._stats["calls"].append(
                {
                    "provider": provider,
                    "model": model,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                }
            )

    @staticmethod
    def _get_usage_value(usage: Any, name: str) -> int | None:
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        return int(value) if value is not None else None

    def patch_openai(self) -> None:
        if self._patched:
            return
        try:
            from openai.resources.chat.completions import Completions
        except Exception:
            return

        original_create = Completions.create
        tracker = self

        def tracked_create(self_obj: Any, *args: Any, **kwargs: Any) -> Any:
            response = original_create(self_obj, *args, **kwargs)
            tracker.record_response(response, provider="openai")
            return response

        tracked_create._memory_token_usage_patched = True  # type: ignore[attr-defined]
        Completions.create = tracked_create  # type: ignore[method-assign]
        self._patched = True


token_usage_tracker = TokenUsageTracker()

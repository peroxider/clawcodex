"""LLM usage statistics helper functions for semantic crystallization."""

from __future__ import annotations

import threading
from typing import Any, Callable


class LLMStatsTracker:
    """Thread-safe counter for crystallizer LLM calls and token usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._llm_calls = 0
        self._llm_failures = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._token_tracked = False

    def wrap(
        self, llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    ) -> Callable[[str, str, dict[str, Any]], dict[str, Any]]:
        def wrapped(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
            with self._lock:
                self._llm_calls += 1
            try:
                result = llm_fn(system, user, schema)
            except Exception:
                with self._lock:
                    self._llm_failures += 1
                raise

            raw = result.pop("_raw_response", None) if isinstance(result, dict) else None
            if raw is not None:
                usage = getattr(raw, "usage", None)
                if usage is None and isinstance(raw, dict):
                    usage = raw.get("usage")
                prompt = self._usage_value(usage, "prompt_tokens")
                completion = self._usage_value(usage, "completion_tokens")
                total = self._usage_value(usage, "total_tokens")
                if total is None and (prompt is not None or completion is not None):
                    total = int(prompt or 0) + int(completion or 0)
                with self._lock:
                    self._token_tracked = True
                    self._prompt_tokens += int(prompt or 0)
                    self._completion_tokens += int(completion or 0)
                    self._total_tokens += int(total or 0)
            return result

        return wrapped

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "llm_calls": self._llm_calls,
                "llm_failures": self._llm_failures,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._total_tokens,
                "token_tracked": self._token_tracked,
            }

    def reset(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        with self._lock:
            self._llm_calls = 0
            self._llm_failures = 0
            self._prompt_tokens = 0
            self._completion_tokens = 0
            self._total_tokens = 0
            self._token_tracked = False
        return snapshot

    @staticmethod
    def _usage_value(usage: Any, name: str) -> int | None:
        if usage is None:
            return None
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        return int(value) if value is not None else None

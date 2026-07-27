"""Small deterministic helpers shared by the current Plan Graph tests."""

from __future__ import annotations

from typing import Any


class DeterministicClock:
    def __init__(self) -> None:
        self._seconds = 0

    def now(self) -> str:
        value = f"2026-01-01T00:00:{self._seconds:02d}.000Z"
        self._seconds += 1
        return value

    def advance(self, seconds: int) -> None:
        self._seconds += max(0, seconds)

    def peek(self) -> str:
        return f"2026-01-01T00:00:{self._seconds:02d}.000Z"

    __call__ = now


class DeterministicIdFactory:
    def __init__(self, width: int = 3) -> None:
        self._width = width
        self._counters: dict[str, int] = {}

    def __call__(self, prefix: str = "T") -> str:
        value = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = value
        return f"{prefix}-{value:0{self._width}d}"

    def reset(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._counters.clear()
        else:
            self._counters.pop(prefix, None)


class Failpoint:
    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}

    def register(self, name: str, handler: Any) -> None:
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        self._handlers.pop(name, None)

    def clear(self) -> None:
        self._handlers.clear()

    def hit(self, name: str) -> None:
        handler = self._handlers.get(name)
        if isinstance(handler, type) and issubclass(handler, BaseException):
            raise handler()
        if isinstance(handler, BaseException):
            raise handler
        if callable(handler):
            handler(name)

    def __contains__(self, name: str) -> bool:
        return name in self._handlers


__all__ = ["DeterministicClock", "DeterministicIdFactory", "Failpoint"]

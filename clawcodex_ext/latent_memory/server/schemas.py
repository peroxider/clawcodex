from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


def sanitize_request_strings(value: Any) -> Any:
    """Recursively remove orphaned UTF-16 surrogate code points from strings."""
    if isinstance(value, str):
        return "".join(char for char in value if not 0xD800 <= ord(char) <= 0xDFFF)
    if isinstance(value, dict):
        return {
            sanitize_request_strings(key): sanitize_request_strings(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_request_strings(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_request_strings(item) for item in value)
    if isinstance(value, set):
        return {sanitize_request_strings(item) for item in value}
    return value


class SanitizedRequest(BaseModel):
    """Base model that recursively sanitizes all inbound string values."""

    @model_validator(mode="before")
    @classmethod
    def sanitize_strings(cls, value: Any) -> Any:
        return sanitize_request_strings(value)


class AddRequest(SanitizedRequest):
    """Request body for writing a conversation, with a message list and optional scope/time params."""

    messages: list[dict[str, Any]]
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: int | None = None
    observation_date: str | None = None
    custom_instructions: str | None = None


class SearchRequest(SanitizedRequest):
    """Semantic search request body; query is required, scope and filters are optional."""

    query: str
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    filters: dict[str, Any] | None = None
    rerank: bool = False
    search_strategy: str | None = Field(
        default=None,
        pattern="^(layered|crystal_boost)$",
    )


class UpdateRequest(SanitizedRequest):
    """Request body for updating a single memory's content."""

    data: str

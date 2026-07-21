"""Tests for LinearAdapter.create_clarification_comment override (F-124-G)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from extensions.orchestrator.linear import LinearAdapter, LinearGraphQLClient
from extensions.orchestrator.tracker import Comment


def _make_adapter() -> LinearAdapter:
    return LinearAdapter(api_key="test-key", project_slug="proj")


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_with_mentions() -> None:
    """Mentions are joined as @login tokens and prepended to body."""
    adapter = _make_adapter()
    adapter.client = MagicMock(spec=LinearGraphQLClient)
    adapter.create_comment = AsyncMock(
        return_value=Comment(
            id="c-1",
            body="@alice\n\nNeed details",
            author_login="bot",
        )
    )

    result = await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Need details",
        mentions=["alice"],
    )

    assert result is not None
    assert result.id == "c-1"
    adapter.create_comment.assert_awaited_once_with(
        "issue-1", "@alice\n\nNeed details"
    )


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_multiple_mentions() -> None:
    """Multiple mentions are space-joined into the prefix."""
    adapter = _make_adapter()
    adapter.create_comment = AsyncMock(
        return_value=Comment(id="c-2", body="@alice @bob\n\nQ?")
    )

    await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Q?",
        mentions=["alice", "bob"],
    )

    adapter.create_comment.assert_awaited_once_with(
        "issue-1", "@alice @bob\n\nQ?"
    )


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_without_mentions() -> None:
    """No mentions → body is posted verbatim, no leading newline."""
    adapter = _make_adapter()
    adapter.create_comment = AsyncMock(
        return_value=Comment(id="c-3", body="Need details")
    )

    await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Need details",
        mentions=None,
    )

    adapter.create_comment.assert_awaited_once_with("issue-1", "Need details")


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_empty_mentions() -> None:
    """Empty mentions list is treated as no mentions (no stray @ prefix)."""
    adapter = _make_adapter()
    adapter.create_comment = AsyncMock(
        return_value=Comment(id="c-4", body="Need details")
    )

    await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Need details",
        mentions=[],
    )

    adapter.create_comment.assert_awaited_once_with("issue-1", "Need details")


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_blank_login_filtered() -> None:
    """Whitespace-only login tokens are filtered out to avoid '@\n\nbody' artefacts."""
    adapter = _make_adapter()
    adapter.create_comment = AsyncMock(
        return_value=Comment(id="c-5", body="@alice\n\nNeed details")
    )

    await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Need details",
        mentions=["", "  ", "alice"],
    )

    adapter.create_comment.assert_awaited_once_with(
        "issue-1", "@alice\n\nNeed details"
    )


@pytest.mark.asyncio
async def test_linear_adapter_create_clarification_comment_returns_none_on_failure() -> None:
    """create_comment returning None propagates as None (TrackerAdapter contract)."""
    adapter = _make_adapter()
    adapter.create_comment = AsyncMock(return_value=None)

    result = await adapter.create_clarification_comment(
        issue_id="issue-1",
        body="Need details",
        mentions=["alice"],
    )

    assert result is None

"""Contract tests for the model-facing SkillSearch tool wrapper."""

from __future__ import annotations

from clawcodex_ext.tool_system.tools.skill_search import _skill_search_call


def test_missing_search_query_returns_structured_tool_error() -> None:
    result = _skill_search_call({}, None)  # type: ignore[arg-type]

    assert result.name == "SkillSearch"
    assert result.is_error is True
    assert result.output == "query is required for search action"


def test_unknown_action_returns_structured_tool_error() -> None:
    result = _skill_search_call({"action": "unknown"}, None)  # type: ignore[arg-type]

    assert result.name == "SkillSearch"
    assert result.is_error is True
    assert "Unknown action: unknown" in result.output


def test_stats_when_search_is_disabled_returns_normal_result(monkeypatch) -> None:
    class _DisabledSearcher:
        async def ensure_index(self) -> None:
            raise RuntimeError("disabled")

    monkeypatch.setattr(
        "clawcodex_ext.tool_system.tools.skill_search._get_searcher",
        lambda: _DisabledSearcher(),
    )

    result = _skill_search_call({"action": "stats"}, None)  # type: ignore[arg-type]

    assert result.name == "SkillSearch"
    assert result.is_error is False
    assert result.output == "Index not loaded (feature flag may be off)."

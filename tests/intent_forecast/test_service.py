from __future__ import annotations

from clawcodex_ext.intent_forecast.context import ForecastContext
from clawcodex_ext.intent_forecast.messages import ForecastSuggestion
from clawcodex_ext.intent_forecast.prompt import build_forecast_messages
from clawcodex_ext.intent_forecast.service import (
    IntentForecastService,
    filter_suggestions_for_context,
    parse_forecast_response,
)


def test_parse_forecast_response_filters_low_confidence() -> None:
    raw = '{"suggestions":[{"title":"A","prompt":"do a","confidence":0.8},{"title":"B","prompt":"do b","confidence":0.1}]}'
    suggestions = parse_forecast_response(raw, min_confidence=0.45)
    assert [s.title for s in suggestions] == ["A"]


def test_service_uses_fallback_without_provider(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        current_messages=[{"role": "user", "content": "finish tests"}],
        workspace={"git_status": " M file.py"},
        fingerprint="abc",
    )
    result = IntentForecastService(
        conversation=None,
        provider=None,
        model=None,
        workspace_root=tmp_path,
        context=context,
    ).generate(trigger="test", force=True)
    assert result.generated is True
    assert result.suggestions[0].prompt
    assert result.fingerprint == "abc"


def test_prompt_carries_response_language(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        current_messages=[{"role": "user", "content": "\u7ee7\u7eed\u5b9e\u73b0\u529f\u80fd"}],
        response_language="Chinese",
    )

    messages = build_forecast_messages(context, max_input_tokens=4000)

    assert '"response_language": "Chinese"' in messages[0]["content"]
    assert "MUST use the context field `response_language`" in messages[0]["content"]
    assert "Do not suggest changing permission mode" in messages[0]["content"]
    assert "Treat `dontAsk` as permissive" in messages[0]["content"]


def test_fallback_uses_chinese_when_context_language_is_chinese(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        current_messages=[{"role": "user", "content": "\u7ee7\u7eed\u8865\u9f50\u6d4b\u8bd5"}],
        response_language="Chinese",
        fingerprint="abc",
    )

    result = IntentForecastService(
        conversation=None,
        provider=None,
        model=None,
        workspace_root=tmp_path,
        context=context,
    ).generate(trigger="test", force=True)

    assert result.suggestions[0].title == "\u7ee7\u7eed\u6700\u8fd1\u7684\u4efb\u52a1"
    assert result.suggestions[0].prompt.startswith("\u8bf7\u57fa\u4e8e\u6700\u65b0\u7528\u6237\u8bf7\u6c42")


def test_filter_drops_english_suggestions_when_chinese_required(tmp_path) -> None:
    context = ForecastContext(cwd=str(tmp_path), response_language="Chinese")
    suggestions = [
        ForecastSuggestion(
            id="s1",
            title="Run tests",
            prompt="Run the stability tests.",
            reason="Likely next step.",
            confidence=0.8,
        ),
        ForecastSuggestion(
            id="s2",
            title="\u8fd0\u884c\u6d4b\u8bd5",
            prompt="\u8bf7\u8fd0\u884c\u7a33\u5b9a\u6027\u6d4b\u8bd5\u3002",
            reason="\u8fd9\u662f\u5408\u7406\u7684\u4e0b\u4e00\u6b65\u3002",
            confidence=0.7,
        ),
    ]

    filtered = filter_suggestions_for_context(suggestions, context)

    assert [s.id for s in filtered] == ["s2"]


def test_filter_drops_permission_mode_suggestion_without_current_block(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        current_messages=[{"role": "user", "content": "continue forecast work"}],
        response_language="English",
    )
    suggestions = [
        ForecastSuggestion(
            id="s1",
            title="Verify Permission Mode Configuration",
            prompt="Switch permission mode to ask.",
            reason="Previous sessions mentioned dontAsk.",
            confidence=0.8,
        ),
        ForecastSuggestion(
            id="s2",
            title="Run focused tests",
            prompt="Run the intent forecast tests.",
            confidence=0.7,
        ),
    ]

    filtered = filter_suggestions_for_context(suggestions, context)

    assert [s.id for s in filtered] == ["s2"]


def test_filter_drops_unrelated_history_when_workspace_focus_is_intent_forecast(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        workspace={"changed_files": ["clawcodex_ext/intent_forecast/service.py"]},
        response_language="English",
    )
    suggestions = [
        ForecastSuggestion(
            id="s1",
            title="Run Orchestrator Unit Tests",
            prompt="Run orchestrator unit tests.",
            reason="Previous sessions mentioned orchestrator stability.",
            confidence=0.8,
        ),
        ForecastSuggestion(
            id="s2",
            title="Run Intent Forecast tests",
            prompt="Run tests/intent_forecast.",
            reason="The active changes are in intent_forecast.",
            confidence=0.7,
        ),
    ]

    filtered = filter_suggestions_for_context(suggestions, context)

    assert [s.id for s in filtered] == ["s2"]


def test_filter_allows_generic_current_changes_for_focused_workspace(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        workspace={"changed_files": ["clawcodex_ext/intent_forecast/service.py"]},
        response_language="English",
    )
    suggestions = [
        ForecastSuggestion(
            id="s1",
            title="Review current workspace changes",
            prompt="Review current changes and identify unfinished work.",
            confidence=0.7,
        )
    ]

    filtered = filter_suggestions_for_context(suggestions, context)

    assert [s.id for s in filtered] == ["s1"]


def test_filter_keeps_multiple_focuses_for_cross_module_changes(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        workspace={
            "changed_files": [
                "clawcodex_ext/intent_forecast/service.py",
                "clawcodex_ext/tui/app.py",
            ]
        },
        response_language="English",
    )
    suggestions = [
        ForecastSuggestion(
            id="s1",
            title="Verify Intent Forecast filtering",
            prompt="Run tests/intent_forecast.",
            confidence=0.8,
        ),
        ForecastSuggestion(
            id="s2",
            title="Check TUI forecast picker",
            prompt="Inspect TUI app wiring.",
            confidence=0.7,
        ),
        ForecastSuggestion(
            id="s3",
            title="Run Orchestrator Unit Tests",
            prompt="Run orchestrator unit tests.",
            confidence=0.6,
        ),
    ]

    filtered = filter_suggestions_for_context(suggestions, context)

    assert [s.id for s in filtered] == ["s1", "s2"]


def test_fallback_prioritizes_intent_forecast_workspace_focus(tmp_path) -> None:
    context = ForecastContext(
        cwd=str(tmp_path),
        workspace={
            "git_status": " M clawcodex_ext/intent_forecast/service.py",
            "changed_files": ["clawcodex_ext/intent_forecast/service.py"],
        },
        response_language="English",
    )

    result = IntentForecastService(
        conversation=None,
        provider=None,
        model=None,
        workspace_root=tmp_path,
        context=context,
    ).generate(trigger="test", force=True)

    assert result.suggestions[0].title == "Verify Intent Forecast fixes"
    assert [s.title for s in result.suggestions] == [
        "Verify Intent Forecast fixes",
        "Run Intent Forecast regression tests",
        "Inspect latest Forecast history",
    ]

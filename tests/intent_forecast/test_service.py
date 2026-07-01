from __future__ import annotations

from clawcodex_ext.intent_forecast.context import ForecastContext
from clawcodex_ext.intent_forecast.service import IntentForecastService, parse_forecast_response


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

from __future__ import annotations

from clawcodex_ext.intent_forecast.learning import read_recent_feedback, record_feedback
from clawcodex_ext.intent_forecast.messages import ForecastSuggestion


def test_feedback_roundtrip(tmp_path) -> None:
    suggestion = ForecastSuggestion(id="s1", title="Do it", prompt="do it", confidence=0.7)
    record_feedback("accepted", suggestion=suggestion, cwd=tmp_path, fingerprint="fp", base_dir=tmp_path)
    rows = read_recent_feedback(base_dir=tmp_path)
    assert rows[-1]["event"] == "accepted"
    assert rows[-1]["suggestion_id"] == "s1"

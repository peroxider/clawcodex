from __future__ import annotations

from eval.intent_forecast.runner import evaluate_cases, load_cases


def test_eval_runner_loads_30_cases() -> None:
    cases = load_cases()

    assert len(cases) >= 30


def test_eval_runner_reports_metrics() -> None:
    report = evaluate_cases(load_cases())

    assert report["cases"] >= 30
    assert "top1_match" in report
    assert "off_topic_rate" in report
    assert "actionability" in report

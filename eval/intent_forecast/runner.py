"""Offline evaluation runner for Intent Forecast quality checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.context import ForecastContext
from clawcodex_ext.intent_forecast.service import IntentForecastService


DATASET_PATH = Path(__file__).with_name("samples.jsonl")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    context: ForecastContext
    expected_kind: str
    expected_terms: list[str]
    should_suggest: bool = True


def load_cases(path: Path = DATASET_PATH) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        cases.append(
            EvalCase(
                case_id=str(data["case_id"]),
                context=ForecastContext(
                    cwd=str(data.get("cwd") or "repo"),
                    current_messages=list(data.get("current_messages") or []),
                    workspace=dict(data.get("workspace") or {}),
                    task_state=dict(data.get("task_state") or {}),
                    intent_stage=str(data.get("intent_stage") or "explore"),
                    response_language=str(data.get("response_language") or "English"),
                    sessions=list(data.get("sessions") or []),
                    fingerprint=str(data.get("case_id")),
                ),
                expected_kind=str(data.get("expected_kind") or ""),
                expected_terms=[str(item).lower() for item in data.get("expected_terms") or []],
                should_suggest=bool(data.get("should_suggest", True)),
            )
        )
    return cases


def evaluate_cases(cases: list[EvalCase]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        result = IntentForecastService(
            conversation=None,
            provider=None,
            model=None,
            workspace_root=Path(case.context.cwd),
            context=case.context,
            config=IntentForecastConfig(min_confidence=0.45),
        ).generate(trigger="test", force=True)
        suggestions = result.suggestions
        texts = [_suggestion_text(item) for item in suggestions]
        top1_match = bool(suggestions and _matches(texts[0], case.expected_terms))
        top3_match = any(_matches(text, case.expected_terms) for text in texts[:3])
        no_suggestion_ok = (not case.should_suggest and not result.generated) or (case.should_suggest and result.generated)
        rows.append(
            {
                "case_id": case.case_id,
                "generated": result.generated,
                "top1_match": top1_match,
                "top3_match": top3_match,
                "no_suggestion_ok": no_suggestion_ok,
                "off_topic": result.generated and case.should_suggest and not top3_match,
                "language_ok": _language_ok(case.context.response_language, texts),
                "actionable": all(bool(item.prompt.strip()) for item in suggestions),
            }
        )
    return _metrics(rows)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    return {
        "cases": len(rows),
        "top1_match": _rate(rows, "top1_match", total),
        "top3_match": _rate(rows, "top3_match", total),
        "off_topic_rate": _rate(rows, "off_topic", total),
        "no_suggestion_accuracy": _rate(rows, "no_suggestion_ok", total),
        "language_accuracy": _rate(rows, "language_ok", total),
        "actionability": _rate(rows, "actionable", total),
        "rows": rows,
    }


def _rate(rows: list[dict[str, Any]], key: str, total: int) -> float:
    return round(sum(1 for row in rows if row.get(key)) / total, 4)


def _suggestion_text(suggestion: Any) -> str:
    return " ".join([suggestion.title, suggestion.prompt, suggestion.reason, " ".join(suggestion.refs())]).lower()


def _matches(text: str, terms: list[str]) -> bool:
    if not terms:
        return False
    return any(term in text for term in terms)


def _language_ok(language: str, texts: list[str]) -> bool:
    if not texts:
        return True
    joined = "\n".join(texts)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in joined)
    if language.lower().startswith("chinese"):
        return has_cjk
    return True


def main() -> int:
    print(json.dumps(evaluate_cases(load_cases()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""``clawcodex forecast`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from clawcodex_ext.cli.subcommand_registry import register
from clawcodex_ext.intent_forecast.config import load_intent_forecast_config
from clawcodex_ext.intent_forecast.learning import record_feedback, read_recent_feedback
from clawcodex_ext.intent_forecast.messages import (
    ForecastResult,
    ForecastSuggestion,
    format_forecast_for_display,
    parse_selection,
    result_to_dict,
)
from clawcodex_ext.intent_forecast.service import IntentForecastService
from clawcodex_ext.session_intelligence.queue import enqueue_summary_job
from clawcodex_ext.session_intelligence.summarizer import summarize_session


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clawcodex forecast")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status", "accept", "dismiss", "summarize", "stats"],
    )
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--session", default="")
    parser.add_argument("--pending", action="store_true", help="process pending summary queue")
    return parser


@register("forecast")
def run_forecast_command(args: list[str]) -> int:
    parser = _build_parser()
    ns = parser.parse_args(args)
    cwd = Path.cwd()
    cfg = load_intent_forecast_config(cwd=cwd)

    if ns.command == "status":
        payload = {
            "enabled": cfg.enabled,
            "auto_display": cfg.auto_display,
            "idle_seconds": cfg.idle_seconds,
            "feedback_events": len(read_recent_feedback(limit=100)),
        }
        _print(payload, ns.json)
        return 0
    if ns.command == "stats":
        rows = read_recent_feedback(limit=200)
        counts: dict[str, int] = {}
        for row in rows:
            event = str(row.get("event") or "")
            counts[event] = counts.get(event, 0) + 1
        _print({"events": counts, "recent": rows[-10:]}, ns.json)
        return 0
    if ns.command == "accept":
        result = _load_last_cli_result()
        if result is None:
            print("No saved forecast suggestion is available to accept.", file=sys.stderr)
            return 1
        suggestion = parse_selection(ns.target or "1", result.suggestions)
        if suggestion is None:
            print(f"No forecast suggestion matches {ns.target!r}.", file=sys.stderr)
            return 1
        if ns.json:
            print(json.dumps({"prompt": suggestion.prompt, "suggestion_id": suggestion.id}, ensure_ascii=False, indent=2))
        else:
            print(suggestion.prompt)
        _last_cli_result_path().unlink(missing_ok=True)
        return 0
    if ns.command == "dismiss":
        _last_cli_result_path().unlink(missing_ok=True)
        print("Forecast dismissed.")
        return 0
    if ns.command == "summarize":
        if ns.pending:
            from clawcodex_ext.session_intelligence.queue import process_pending_summary_jobs

            _print(process_pending_summary_jobs(), ns.json)
            return 0
        if not ns.session:
            print("usage: clawcodex forecast summarize --session <session_id> [--pending]", file=sys.stderr)
            return 2
        result = summarize_session(ns.session)
        _print(result, ns.json)
        return 0

    result = IntentForecastService(
        conversation=None,
        provider=None,
        model=None,
        workspace_root=cwd,
        config=cfg,
    ).generate(trigger="cli", force=True)
    if cfg.summary_lazy_generate:
        for suggestion in result.suggestions[:1]:
            del suggestion
            try:
                enqueue_summary_job("latest", cwd=cwd)
            except Exception:
                pass
            break
    if ns.json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_forecast_for_display(result))
    if result.generated:
        _save_last_cli_result(result)
    if cfg.feedback_enabled and not result.generated:
        record_feedback("empty", cwd=cwd, fingerprint=result.fingerprint)
    return 0


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")


def _last_cli_result_path() -> Path:
    return Path.home() / ".clawcodex" / "intent_forecast" / "last_forecast.json"


def _save_last_cli_result(result: ForecastResult) -> None:
    path = _last_cli_result_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_last_cli_result() -> ForecastResult | None:
    path = _last_cli_result_path()
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_suggestions = data.get("suggestions")
    if not isinstance(raw_suggestions, list):
        return None
    suggestions: list[ForecastSuggestion] = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        suggestions.append(
            ForecastSuggestion(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                prompt=str(item.get("prompt") or ""),
                reason=str(item.get("reason") or ""),
                confidence=float(item.get("confidence") or 0.0),
                source_refs=[str(ref) for ref in item.get("source_refs") or []],
            )
        )
    return ForecastResult(
        generated=bool(data.get("generated", bool(suggestions))),
        suggestions=suggestions,
        reason=str(data.get("reason") or ""),
        fingerprint=str(data.get("fingerprint") or ""),
    )

"""Prompt construction for Intent Forecast."""

from __future__ import annotations

import json

from clawcodex_ext.intent_forecast.context import ForecastContext


FORECAST_INSTRUCTIONS = """You predict the user's likely next step in an interactive coding session.

Return strict JSON only, shaped as:
{"suggestions":[{"title":"...","prompt":"...","reason":"...","confidence":0.0,"source_refs":["..."]}]}

Rules:
- Suggest at most 3 concrete next actions.
- The prompt must be ready to submit to the coding agent.
- Do not start work yourself.
- Prefer the dominant language of recent user messages.
- Use confidence between 0 and 1.
- Avoid repeating suggestions that feedback says were dismissed."""


def build_forecast_messages(
    context: ForecastContext,
    *,
    max_input_tokens: int,
) -> list[dict[str, str]]:
    payload = json.dumps(context.to_prompt_dict(), ensure_ascii=False, default=str, indent=2)
    payload = _truncate(payload, max_input_tokens=max_input_tokens)
    return [
        {
            "role": "user",
            "content": f"{FORECAST_INSTRUCTIONS}\n\nContext:\n{payload}\n\nReturn JSON only.",
        }
    ]


def _truncate(text: str, *, max_input_tokens: int) -> str:
    budget = max_input_tokens * 4
    if len(text) <= budget:
        return text
    head = max(1000, budget // 4)
    tail = max(1000, budget - head - 120)
    return text[:head].rstrip() + "\n\n[... omitted for forecast budget ...]\n\n" + text[-tail:].lstrip()

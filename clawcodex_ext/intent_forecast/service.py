"""Intent Forecast generation service."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.context import ForecastContext, IntentForecastContextBuilder
from clawcodex_ext.intent_forecast.learning import feedback_weight
from clawcodex_ext.intent_forecast.messages import ForecastResult, ForecastSuggestion
from clawcodex_ext.intent_forecast.prompt import build_forecast_messages


class IntentForecastService:
    def __init__(
        self,
        *,
        conversation: Any | None,
        provider: Any | None,
        model: str | None,
        workspace_root: Path,
        config: IntentForecastConfig | None = None,
        context: ForecastContext | None = None,
    ) -> None:
        self.conversation = conversation
        self.provider = provider
        self.model = model
        self.workspace_root = Path(workspace_root)
        self.config = config or IntentForecastConfig()
        self.context = context

    def generate(self, *, trigger: str, force: bool = False) -> ForecastResult:
        del trigger
        if not force and not self.config.enabled:
            return ForecastResult(generated=False, suggestions=[], reason="Intent Forecast is disabled.")
        context = self.context or IntentForecastContextBuilder(
            conversation=self.conversation,
            workspace_root=self.workspace_root,
            config=self.config,
        ).build()
        suggestions: list[ForecastSuggestion] = []
        if self.provider is not None:
            messages = build_forecast_messages(context, max_input_tokens=self.config.max_input_tokens)
            try:
                response = self.provider.chat(
                    messages=messages,
                    tools=None,
                    model=self.model,
                    max_tokens=self.config.max_output_tokens,
                )
            except TypeError:
                response = self.provider.chat(messages=messages, tools=None, model=self.model)
            raw = str(getattr(response, "content", "") or "")
            suggestions = parse_forecast_response(raw, min_confidence=self.config.min_confidence)

        if not suggestions:
            suggestions = fallback_suggestions(context, min_confidence=self.config.min_confidence)

        if not suggestions:
            return ForecastResult(
                generated=False,
                suggestions=[],
                reason="No confident next-step suggestions are available.",
                fingerprint=context.fingerprint,
            )
        suggestions = rank_suggestions_with_feedback(
            suggestions,
            cwd=context.cwd,
            fingerprint=context.fingerprint,
        )
        return ForecastResult(generated=True, suggestions=suggestions[:3], fingerprint=context.fingerprint)


def parse_forecast_response(raw: str, *, min_confidence: float) -> list[ForecastSuggestion]:
    data = _loads_json(raw)
    if not isinstance(data, dict):
        return []
    raw_suggestions = data.get("suggestions")
    if not isinstance(raw_suggestions, list):
        return []
    suggestions: list[ForecastSuggestion] = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not title or not prompt:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < min_confidence:
            continue
        refs = item.get("source_refs")
        if not isinstance(refs, list):
            refs = []
        suggestions.append(
            ForecastSuggestion(
                id=str(item.get("id") or f"forecast-{uuid.uuid4().hex[:10]}"),
                title=title[:160],
                prompt=prompt,
                reason=str(item.get("reason") or "").strip()[:300],
                confidence=max(0.0, min(1.0, confidence)),
                source_refs=[str(ref)[:120] for ref in refs[:8]],
            )
        )
    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions


def fallback_suggestions(context: ForecastContext, *, min_confidence: float) -> list[ForecastSuggestion]:
    candidates: list[ForecastSuggestion] = []
    recent_user = ""
    for msg in reversed(context.current_messages):
        if msg.get("role") == "user":
            recent_user = str(msg.get("content") or "").strip()
            break
    if recent_user:
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="Continue the recent task",
                prompt=f"Continue from the latest user request and current workspace state:\n\n{recent_user}",
                reason="The most recent user message is the strongest local signal.",
                confidence=max(min_confidence, 0.55),
                source_refs=["conversation:recent-user"],
            )
        )
    status = str(context.workspace.get("git_status") or "").strip()
    if status:
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="Review current workspace changes",
                prompt="Review the current git changes, identify unfinished work, and propose the next implementation step.",
                reason="The workspace has uncommitted changes.",
                confidence=max(min_confidence, 0.5),
                source_refs=["git:status"],
            )
        )
    for session in context.sessions:
        summary = session.get("summary") if isinstance(session, dict) else None
        if isinstance(summary, dict):
            candidates_raw = summary.get("next_action_candidates")
            if isinstance(candidates_raw, list) and candidates_raw:
                title = str(candidates_raw[0])[:160]
                candidates.append(
                    ForecastSuggestion(
                        id=f"forecast-{uuid.uuid4().hex[:10]}",
                        title=title,
                        prompt=f"Continue this next action from the recent session: {title}",
                        reason="A recent session summary listed this as a next action.",
                        confidence=max(min_confidence, 0.48),
                        source_refs=[f"session:{session.get('session_id', '')}"],
                    )
                )
                break
    return candidates[:3]


def rank_suggestions_with_feedback(
    suggestions: list[ForecastSuggestion],
    *,
    cwd: str,
    fingerprint: str,
) -> list[ForecastSuggestion]:
    ranked: list[ForecastSuggestion] = []
    for suggestion in suggestions:
        adjusted = max(
            0.0,
            min(
                1.0,
                suggestion.confidence
                + feedback_weight(
                    suggestion.title,
                    cwd=cwd,
                    fingerprint=fingerprint,
                ),
            ),
        )
        ranked.append(
            ForecastSuggestion(
                id=suggestion.id,
                title=suggestion.title,
                prompt=suggestion.prompt,
                reason=suggestion.reason,
                confidence=adjusted,
                source_refs=suggestion.refs(),
            )
        )
    ranked.sort(key=lambda s: s.confidence, reverse=True)
    return ranked


def _loads_json(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

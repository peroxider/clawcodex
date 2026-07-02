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
            suggestions = filter_suggestions_for_context(suggestions, context)

        if not suggestions:
            suggestions = fallback_suggestions(context, min_confidence=self.config.min_confidence)

        suggestions = no_suggestion_gate(
            suggestions,
            context=context,
            trigger=trigger,
            min_confidence=self.config.min_confidence,
        )
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
    zh = context.response_language.lower().startswith("chinese")
    primary_focus = _primary_workspace_focus(context)
    task_state = context.task_state or {}
    intent_stage = str(context.intent_stage or "explore")
    blocked_reason = str(task_state.get("blocked_reason") or "")
    pending_tests = [str(item) for item in task_state.get("pending_tests") or [] if str(item)]
    open_questions = [str(item) for item in task_state.get("open_questions") or [] if str(item)]
    recent_user = ""
    for msg in reversed(context.current_messages):
        if msg.get("role") == "user":
            recent_user = str(msg.get("content") or "").strip()
            break
    if open_questions:
        question = open_questions[0]
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="先回答待确认问题" if zh else "Resolve the open question",
                prompt=(
                    f"请先围绕这个待确认问题继续：{question}"
                    if zh
                    else f"Continue by resolving this open question first: {question}"
                ),
                reason=(
                    "最近 assistant 刚提出澄清问题，继续实现前应先补齐决策信息。"
                    if zh
                    else "The latest assistant turn asked for clarification, so the next step should resolve that decision before implementation."
                ),
                confidence=max(min_confidence, 0.72),
                source_refs=["task_state:open_questions"],
            )
        )
        return candidates[:3]
    if blocked_reason:
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="修复最近失败" if zh else "Fix the recent failure",
                prompt=(
                    f"请优先定位并修复最近的失败：{blocked_reason}"
                    if zh
                    else f"Prioritize diagnosing and fixing the recent failure: {blocked_reason}"
                ),
                reason=("任务状态显示最近存在阻塞或测试失败。" if zh else "Task state shows a recent blocker or test failure."),
                confidence=max(min_confidence, 0.76),
                source_refs=["task_state:blocked_reason"],
            )
        )
        return candidates[:3]
    if pending_tests and intent_stage in {"test", "debug", "implement"}:
        tests_text = ", ".join(pending_tests[:3])
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="运行相关测试" if zh else "Run focused tests",
                prompt=(f"请运行相关测试并根据结果继续处理：{tests_text}" if zh else f"Run the focused tests and continue from the results: {tests_text}"),
                reason=(
                    "当前变更已经映射到可验证的测试范围。"
                    if zh
                    else "The current changes map to a focused verification set."
                ),
                confidence=max(min_confidence, 0.7),
                source_refs=["task_state:pending_tests"],
            )
        )
        if intent_stage == "test":
            return candidates[:3]
    if intent_stage == "document":
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="继续完善文档" if zh else "Continue documentation work",
                prompt=(
                    "请基于当前变更继续完善相关文档，并检查文档内容是否与已实现行为一致。"
                    if zh
                    else "Continue updating the relevant documentation from the current changes and check that it matches the implemented behavior."
                ),
                reason=("最近用户请求或变更指向文档阶段。" if zh else "The recent user request or changed files point to documentation work."),
                confidence=max(min_confidence, 0.66),
                source_refs=["intent_stage:document"],
            )
        )
    if intent_stage == "commit":
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="整理当前变更" if zh else "Prepare the current changes",
                prompt=(
                    "请查看当前 diff，整理变更摘要和剩余风险，并确认是否适合提交。"
                    if zh
                    else "Review the current diff, summarize the changes and remaining risks, and confirm whether it is ready to commit."
                ),
                reason=("当前意图阶段更接近提交前整理。" if zh else "The current intent stage is closest to pre-commit preparation."),
                confidence=max(min_confidence, 0.65),
                source_refs=["intent_stage:commit"],
            )
        )
    if primary_focus and primary_focus["id"] == "intent_forecast":
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="\u9a8c\u8bc1 Intent Forecast \u4fee\u590d" if zh else "Verify Intent Forecast fixes",
                prompt=(
                    "\u8bf7\u68c0\u67e5\u5f53\u524d Intent Forecast \u76f8\u5173\u53d8\u66f4\uff0c\u8fd0\u884c tests/intent_forecast \u56de\u5f52\u6d4b\u8bd5\uff0c\u5e76\u786e\u8ba4\u81ea\u52a8\u89e6\u53d1\u3001/forecast \u548c CLI \u7684\u63a8\u8350\u90fd\u4e0e\u5f53\u524d\u529f\u80fd\u76f8\u5173\u3002"
                    if zh
                    else "Review the current Intent Forecast changes, run the tests/intent_forecast regression suite, and confirm auto, /forecast, and CLI suggestions stay relevant to the active feature."
                ),
                reason=(
                    "\u5f53\u524d\u5de5\u4f5c\u533a\u53d8\u66f4\u96c6\u4e2d\u5728 intent_forecast \u529f\u80fd\u4e0a\u3002"
                    if zh
                    else "Current workspace changes are concentrated in the intent_forecast feature."
                ),
                confidence=max(min_confidence, 0.68),
                source_refs=["git:changed-files"],
            )
        )
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="\u8fd0\u884c Intent Forecast \u56de\u5f52\u6d4b\u8bd5" if zh else "Run Intent Forecast regression tests",
                prompt=(
                    "\u8bf7\u8fd0\u884c tests/intent_forecast \u4ee5\u53ca\u76f8\u5173 frontend wiring \u6d4b\u8bd5\uff0c\u786e\u8ba4 CLI\u3001/forecast \u548c\u81ea\u52a8\u89e6\u53d1\u7684\u8fc7\u6ee4\u4e0e\u4fdd\u5b58\u903b\u8f91\u6b63\u5e38\u3002"
                    if zh
                    else "Run tests/intent_forecast and the related frontend wiring tests to verify CLI, /forecast, and automatic forecast filtering and persistence."
                ),
                reason=(
                    "\u5f53\u524d\u4fee\u6539\u6d89\u53ca forecast \u751f\u6210\u3001\u8fc7\u6ee4\u548c\u6301\u4e45\u5316\uff0c\u9002\u5408\u5148\u505a\u9488\u5bf9\u6027\u56de\u5f52\u3002"
                    if zh
                    else "Current changes touch forecast generation, filtering, and persistence, so focused regression tests are the safest next step."
                ),
                confidence=max(min_confidence, 0.64),
                source_refs=["tests:intent_forecast"],
            )
        )
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="\u68c0\u67e5\u6700\u65b0 Forecast \u5386\u53f2\u8bb0\u5f55" if zh else "Inspect latest Forecast history",
                prompt=(
                    "\u8bf7\u67e5\u770b ~/.clawcodex/intent_forecast/history.jsonl \u7684\u6700\u65b0\u8bb0\u5f55\uff0c\u786e\u8ba4\u5efa\u8bae\u4e0d\u518d\u5305\u542b\u65e0\u5173 orchestrator \u6216\u6743\u9650\u6a21\u5f0f\u8bef\u5224\u3002"
                    if zh
                    else "Inspect the latest ~/.clawcodex/intent_forecast/history.jsonl records and confirm suggestions no longer include unrelated orchestrator or permission-mode claims."
                ),
                reason=(
                    "\u7edf\u4e00 history sidecar \u4f1a\u4fdd\u7559\u6bcf\u6b21 forecast \u7ed3\u679c\uff0c\u53ef\u76f4\u63a5\u9a8c\u8bc1\u8fc7\u6ee4\u6548\u679c\u3002"
                    if zh
                    else "The unified history sidecar keeps every forecast result, making it the direct evidence for filtering quality."
                ),
                confidence=max(min_confidence, 0.6),
                source_refs=["history:intent_forecast"],
            )
        )
        if not recent_user:
            return candidates[:3]
    if recent_user:
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="\u7ee7\u7eed\u6700\u8fd1\u7684\u4efb\u52a1" if zh else "Continue the recent task",
                prompt=(
                    f"\u8bf7\u57fa\u4e8e\u6700\u65b0\u7528\u6237\u8bf7\u6c42\u548c\u5f53\u524d\u5de5\u4f5c\u533a\u72b6\u6001\u7ee7\u7eed\u63a8\u8fdb\uff1a\n\n{recent_user}"
                    if zh
                    else f"Continue from the latest user request and current workspace state:\n\n{recent_user}"
                ),
                reason=(
                    "\u6700\u8fd1\u7684\u7528\u6237\u6d88\u606f\u662f\u5f53\u524d\u6700\u5f3a\u7684\u672c\u5730\u4fe1\u53f7\u3002"
                    if zh
                    else "The most recent user message is the strongest local signal."
                ),
                confidence=max(min_confidence, 0.55),
                source_refs=["conversation:recent-user"],
            )
        )
    status = str(context.workspace.get("git_status") or "").strip()
    if status:
        candidates.append(
            ForecastSuggestion(
                id=f"forecast-{uuid.uuid4().hex[:10]}",
                title="\u68c0\u67e5\u5f53\u524d\u5de5\u4f5c\u533a\u53d8\u66f4" if zh else "Review current workspace changes",
                prompt=(
                    "\u8bf7\u68c0\u67e5\u5f53\u524d git \u53d8\u66f4\uff0c\u8bc6\u522b\u672a\u5b8c\u6210\u7684\u5de5\u4f5c\uff0c\u5e76\u63d0\u51fa\u4e0b\u4e00\u6b65\u5b9e\u73b0\u8ba1\u5212\u3002"
                    if zh
                    else "Review the current git changes, identify unfinished work, and propose the next implementation step."
                ),
                reason="\u5de5\u4f5c\u533a\u5b58\u5728\u672a\u63d0\u4ea4\u53d8\u66f4\u3002" if zh else "The workspace has uncommitted changes.",
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
                        prompt=(
                            f"\u8bf7\u7ee7\u7eed\u63a8\u8fdb\u6700\u8fd1\u4f1a\u8bdd\u4e2d\u7684\u4e0b\u4e00\u6b65\u884c\u52a8\uff1a{title}"
                            if zh
                            else f"Continue this next action from the recent session: {title}"
                        ),
                        reason=(
                            "\u6700\u8fd1\u4f1a\u8bdd\u6458\u8981\u5c06\u5b83\u5217\u4e3a\u4e0b\u4e00\u6b65\u884c\u52a8\u3002"
                            if zh
                            else "A recent session summary listed this as a next action."
                        ),
                        confidence=max(min_confidence, 0.48),
                        source_refs=[f"session:{session.get('session_id', '')}"],
                    )
                )
                break
    return candidates[:3]


def no_suggestion_gate(
    suggestions: list[ForecastSuggestion],
    *,
    context: ForecastContext,
    trigger: str,
    min_confidence: float,
) -> list[ForecastSuggestion]:
    """Suppress weak automatic suggestions when local evidence is thin."""

    if not suggestions:
        return []
    manual = trigger in {"slash", "cli", "manual", "test"}
    task_state = context.task_state or {}
    if str(context.intent_stage or "") == "pause" and not manual:
        return []
    threshold = min_confidence if manual else min(0.95, max(min_confidence, min_confidence + 0.08))
    strong_signal = bool(
        context.current_messages
        or context.workspace.get("git_status")
        or task_state.get("blocked_reason")
        or task_state.get("pending_tests")
        or any(float(session.get("relevance_score") or 0) >= 0.5 for session in context.sessions[:3])
    )
    if not strong_signal and not manual:
        return []
    return [suggestion for suggestion in suggestions if suggestion.confidence >= threshold]


def filter_suggestions_for_context(
    suggestions: list[ForecastSuggestion],
    context: ForecastContext,
) -> list[ForecastSuggestion]:
    filtered: list[ForecastSuggestion] = []
    require_chinese = context.response_language.lower().startswith("chinese")
    permission_change_allowed = _permission_change_allowed(context)
    focuses = _workspace_focuses(context)
    for suggestion in suggestions:
        text = " ".join([suggestion.title, suggestion.prompt, suggestion.reason]).lower()
        if _is_permission_mode_suggestion(text) and not permission_change_allowed:
            continue
        if require_chinese and not _contains_cjk(text):
            continue
        if not _passes_workspace_focus(suggestion, text, focuses):
            continue
        filtered.append(suggestion)
    return filtered


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


def _is_permission_mode_suggestion(text: str) -> bool:
    return (
        "permission mode" in text
        or "bypasspermissions" in text
        or "dontask" in text
        or "switch permission" in text
        or "\u6743\u9650\u6a21\u5f0f" in text
    )


def _permission_change_allowed(context: ForecastContext) -> bool:
    texts: list[str] = []
    for msg in context.current_messages[-8:]:
        texts.append(str(msg.get("content") or ""))
    for session in context.sessions[:4]:
        tail = session.get("transcript_tail")
        if isinstance(tail, list):
            for item in tail[-4:]:
                if isinstance(item, dict):
                    texts.append(str(item.get("content") or ""))
    haystack = "\n".join(texts).lower()
    blocked_markers = (
        "permission denied",
        "blocked by permission",
        "permissions blocked",
        "not permitted",
        "user denied",
        "\u6743\u9650\u963b\u6b62",
        "\u6743\u9650\u62d2\u7edd",
        "\u88ab\u6743\u9650\u963b\u6b62",
    )
    return any(marker in haystack for marker in blocked_markers)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _primary_workspace_focus(context: ForecastContext) -> dict[str, Any] | None:
    focuses = _workspace_focuses(context)
    return focuses[0] if focuses else None


def _workspace_focuses(context: ForecastContext) -> list[dict[str, Any]]:
    changed = [str(path).lower() for path in context.workspace.get("changed_files") or []]
    recent = " ".join(str(msg.get("content") or "").lower() for msg in context.current_messages[-6:])
    if not changed and not recent:
        return []

    focus_defs = _focus_definitions()
    scores: dict[str, float] = {}
    evidence: dict[str, list[str]] = {}
    for path in changed:
        for focus_id, meta in focus_defs.items():
            aliases = meta["aliases"]
            if any(alias in path for alias in aliases):
                scores[focus_id] = scores.get(focus_id, 0.0) + 1.0
                evidence.setdefault(focus_id, []).append(path)
    for focus_id, meta in focus_defs.items():
        aliases = meta["aliases"]
        if any(alias in recent for alias in aliases):
            scores[focus_id] = scores.get(focus_id, 0.0) + 0.75
            evidence.setdefault(focus_id, []).append("conversation:recent-user")

    if not scores:
        return []
    total_changed = max(1, len(changed))
    focuses: list[dict[str, Any]] = []
    for focus_id, score in scores.items():
        confidence = min(1.0, score / total_changed)
        if "conversation:recent-user" in evidence.get(focus_id, []):
            confidence = min(1.0, confidence + 0.25)
        meta = focus_defs[focus_id]
        focuses.append(
            {
                "id": focus_id,
                "label": meta["label"],
                "aliases": meta["aliases"],
                "confidence": confidence,
                "evidence": evidence.get(focus_id, [])[:8],
            }
        )
    focuses.sort(key=lambda item: item["confidence"], reverse=True)
    top = focuses[0]["confidence"]
    return [item for item in focuses if item["confidence"] >= max(0.34, top - 0.2)]


def _passes_workspace_focus(
    suggestion: ForecastSuggestion,
    text: str,
    focuses: list[dict[str, Any]],
) -> bool:
    if not focuses:
        return True
    top_confidence = float(focuses[0].get("confidence") or 0.0)
    if top_confidence < 0.55 and len(focuses) < 2:
        return True
    refs_text = " ".join(suggestion.refs()).lower()
    combined = f"{text} {refs_text}"
    if any(_matches_focus_aliases(combined, focus) for focus in focuses):
        return True
    generic_current_work = (
        "current workspace" in combined
        or "current changes" in combined
        or "git changes" in combined
        or "changed files" in combined
        or "\u5f53\u524d\u5de5\u4f5c\u533a" in combined
        or "\u5f53\u524d\u53d8\u66f4" in combined
    )
    if generic_current_work:
        return True
    return False


def _matches_focus_aliases(text: str, focus: dict[str, Any]) -> bool:
    return any(str(alias) in text for alias in focus.get("aliases", []))


def _focus_definitions() -> dict[str, dict[str, Any]]:
    return {
        "intent_forecast": {
            "label": "Intent Forecast",
            "aliases": (
                "intent_forecast",
                "intent-forecast",
                "intent forecast",
                "tests/intent_forecast",
                "\u610f\u56fe\u9884\u6d4b",
            ),
        },
        "session_intelligence": {
            "label": "Session Intelligence",
            "aliases": ("session_intelligence", "summary", "summary.json", "session summary"),
        },
        "away_summary": {
            "label": "Away Summary",
            "aliases": ("away_summary", "away summary", "recap"),
        },
        "tui": {
            "label": "TUI",
            "aliases": ("tui/", "tui\\", "tui", "textual", "repl screen", "prompt_input"),
        },
        "repl": {
            "label": "REPL",
            "aliases": ("repl/", "repl\\", "frontend/repl", "slash command"),
        },
        "command_system": {
            "label": "Command System",
            "aliases": ("command_system", "commands", "slash command", "localcommand"),
        },
        "orchestrator": {
            "label": "Orchestrator",
            "aliases": ("orchestrator",),
        },
        "permissions": {
            "label": "Permissions",
            "aliases": ("permission", "permissions", "bypasspermissions", "dontask"),
        },
        "context": {
            "label": "Context",
            "aliases": ("context", "prompt_assembly", "system_prompt"),
        },
        "tests": {
            "label": "Tests",
            "aliases": ("tests/", "test_", "pytest"),
        },
    }


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

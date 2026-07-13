"""Summary service shared by automatic Away Summary and /recap."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from clawcodex_ext.away_summary.config import AwaySummaryConfig
from clawcodex_ext.away_summary.fingerprint import (
    conversation_fingerprint,
    last_away_summary_fingerprint,
    session_turn_count,
)
from clawcodex_ext.away_summary.messages import create_away_summary_message
from clawcodex_ext.away_summary.prompt import build_summary_messages, infer_response_language

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AwaySummaryResult:
    generated: bool
    summary: str = ""
    reason: str = ""
    fingerprint: str = ""
    message: Any | None = None


class AwaySummaryService:
    """Generate and optionally persist a recap for the current session."""

    def __init__(
        self,
        *,
        conversation: Any,
        provider: Any,
        model: str | None,
        session: Any | None = None,
        config: AwaySummaryConfig | None = None,
    ) -> None:
        self.conversation = conversation
        self.provider = provider
        self.model = model
        self.session = session
        self.config = config or AwaySummaryConfig()

    def generate(
        self,
        *,
        trigger: str,
        force: bool = False,
        persist: bool | None = None,
    ) -> AwaySummaryResult:
        turns = session_turn_count(self.conversation)
        if turns < self.config.min_turns:
            return AwaySummaryResult(
                generated=False,
                reason=f"Not enough conversation yet ({turns}/{self.config.min_turns} turns).",
            )

        fingerprint = conversation_fingerprint(self.conversation)
        if not force and fingerprint == last_away_summary_fingerprint(self.conversation):
            return AwaySummaryResult(
                generated=False,
                reason="No new session content since the last recap.",
                fingerprint=fingerprint,
            )

        messages = build_summary_messages(
            self.conversation,
            max_input_tokens=self.config.max_input_tokens,
            response_language=self.config.response_language,
        )
        # Transient TLS / network errors (e.g. SSL: UNEXPECTED_EOF_WHILE_READING)
        # are common when issuing an API call after a long idle period.  Retry
        # once after a short delay rather than failing the whole summary.
        _last_exc: Exception | None = None
        for attempt in range(2):
            if attempt > 0:
                logger.info("Retrying Away Summary API call (attempt %d/2)", attempt + 1)
                time.sleep(1.0)
            try:
                response = self.provider.chat(
                    messages=messages,
                    tools=None,
                    model=self.model,
                    max_tokens=self.config.max_output_tokens,
                )
            except TypeError:
                # Some providers reject max_tokens — fall back to no limit.
                try:
                    response = self.provider.chat(
                        messages=messages,
                        tools=None,
                        model=self.model,
                    )
                except Exception as exc:
                    _last_exc = exc
                    continue
            except Exception as exc:
                _last_exc = exc
                continue
            else:
                _last_exc = None
                break

        if _last_exc is not None:
            raise _last_exc  # type: ignore[misc] — re-raise so the controller logs it
        summary = _extract_summary(response)
        if not summary:
            reasoning = str(getattr(response, "reasoning_content", "") or "").strip()
            if reasoning:
                # ``reasoning_content`` is an internal chain-of-thought stream
                # and is treated as private context elsewhere in the system
                # (see ``clawcodex_ext/query/query.py``). Never leak it to the
                # user; log it for diagnostics and fall back to the
                # conversation-derived summary instead.
                logger.info(
                    "Away Summary: model returned empty content with reasoning; "
                    "using fallback recap. reasoning_len=%d", len(reasoning),
                )
            summary = _fallback_summary(self.conversation)

        summary_message = create_away_summary_message(
            summary,
            trigger=trigger,
            fingerprint=fingerprint,
            message_count=len(getattr(self.conversation, "messages", []) or []),
            model=self.model,
        )

        should_persist = self.config.persist_last_recap if persist is None else persist
        if should_persist:
            self.conversation.messages.append(summary_message)
            if self.session is not None:
                try:
                    self.session.save()
                except Exception:
                    logger.exception(
                        "Failed to save Away Summary: session_id=%s trigger=%s",
                        getattr(self.session, "session_id", ""),
                        trigger,
                    )
                try:
                    from clawcodex_ext.session_intelligence.summarizer import (
                        update_summary_from_away_summary,
                    )

                    sid = str(getattr(self.session, "session_id", "") or "")
                    if sid:
                        update_summary_from_away_summary(session_id=sid, recap=summary)
                except Exception:
                    logger.debug("Away Summary sidecar update failed", exc_info=True)

        return AwaySummaryResult(
            generated=True,
            summary=summary,
            fingerprint=fingerprint,
            message=summary_message,
        )


def _extract_summary(response: Any) -> str:
    """Pull the user-facing recap text out of a ChatResponse, stripping any
    internal chain-of-thought the model may have leaked into ``content``.

    Several providers (e.g. Sapiens AI / Agnes, Kimi thinking mode, Gemini
    thinking variants) emit a ``"Here's a thinking process"`` style draft
    block *inside* ``content`` even when asked to return only the recap.
    Treat that block as reasoning — never as recap.
    """
    raw = str(getattr(response, "content", "") or "").strip()
    return _clean_summary_text(raw)


# Pre-compiled regexes used by ``_clean_summary_text``. Each pattern matches a
# thinking/reasoning preamble that some models prepend to free-form text in
# ``content``. They are intentionally conservative: only strip when the leaked
# block is clearly demarcated (intro line + blank line, or explicit XML tags).
_THINKING_PREAMBLE_RE = re.compile(
    r"""
    ^\s*
    (?:
        here\s*['']?s?\s+a?\s+thinking\s+process\s*[:：]?    # "Here's a thinking process"
      | thinking\s+process\s*[:：]?                           # "Thinking process:"
      | 思考过程\s*[:：]                                       # Chinese: "思考过程:"
      | let\s+me\s+think\s+(?:about\s+this\s+)?[:：]?         # "Let me think"
      | my\s+thought\s+process\s*[:：]?                       # "My thought process:"
    )
    .*?(?=\n\s*\n|\Z)                                          # up to next blank line or EOF
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)
_THINKING_TAG_RE = re.compile(
    r"<(?P<tag>think(?:ing)?|reasoning|thought|reflection|analysis)>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)

# Hallmarks of a leaked chain-of-thought scaffold. When these appear in the
# ``content`` after the preamble has been stripped, the entire content is
# almost certainly the model's reasoning transcript rather than a real recap.
# In that case ``_clean_summary_text`` returns the empty string so the caller
# can fall back to the conversation-derived ``_fallback_summary`` instead of
# leaking thinking to the user.
_COT_HALLMARKS: tuple[str, ...] = (
    "no hidden reasoning",
    "no reasoning trace",
    "check constraints",
    "draft recap (mental refinement",
    "input transcript:",
    "5 writing style",
    "focus areas covered?",
    "language: natural simplified chinese?",
)

# A recap is, in the worst case, a numbered list (1. ... 2. ... 3. ...).
# When we see THREE OR MORE leading-numbered chapter headings inside the
# cleaned body, we treat the body as a CoT chain (1 Analyze, 2 Identify,
# 3 Draft, 4 Check, ...) and fall back. A genuine 1./2./3. bullet recap is
# very rare — and even if it occurs, the conversation-derived fallback
# still gives the user something sensible to read on return.
_COT_CHAPTER_RE = re.compile(
    r"(?:^|\n)\s*[1-9]\d*[\.\s]+[\u4e00-\u9fffA-Za-z][^\n]{0,80}:\s*\n",
)
_COT_CHAPTER_THRESHOLD = 2


def _looks_like_cot_transcript(text: str) -> bool:
    """Return True if ``text`` shows the hallmarks of leaked chain-of-thought.

    Two independent signals are checked:

    1. A hard-coded list of self-check phrases that would never appear in
       a user-facing recap (``No hidden reasoning`` etc.).
    2. Three or more numbered chapter headings on their own line. Real
       recaps don't read like ``1 Analyze`` / ``2 Identify`` / ``3 Draft``
       / ``4 Check`` — those are CoT scaffolding.

    The list is deliberately narrow so legitimate content (e.g. a recap
    that mentions these words in passing) still passes through.
    """
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _COT_HALLMARKS):
        return True
    chapters = _COT_CHAPTER_RE.findall(text)
    return len(chapters) >= _COT_CHAPTER_THRESHOLD


def _clean_summary_text(text: str) -> str:
    """Strip leaked thinking/reasoning blocks from a model's free-form text.

    Handles two leakage modes observed in the wild:

    1. The leading "Here's a thinking process: 1 Foo 2 Bar ...\n\n3 Draft
       Recap ..." template — strip everything before the blank line that
       precedes the actual recap.
    2. XML-style ``<think>...</think>`` envelopes around the recap — strip
       the envelopes but keep the recap body.

    If, after stripping, the remaining text still exhibits obvious
    chain-of-thought scaffolding (``Check Constraints``, ``No hidden
    reasoning`` etc.), return the empty string so the caller's
    ``_fallback_summary`` path takes over.

    The function is deliberately conservative: when in doubt, leave the text
    alone rather than risk eating the recap itself.
    """
    if not text:
        return text

    cleaned = text

    # 1. XML-style envelopes — strip while preserving the inner content.
    cleaned = _THINKING_TAG_RE.sub("", cleaned)

    # 2. Free-form preamble of the form "Here's a thinking process...\n\n…".
    cleaned = _THINKING_PREAMBLE_RE.sub("", cleaned)

    # Collapse any double blanks that the cuts may have introduced.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # 3. If the post-clean body still looks like reasoning scaffolding,
    #    surrender to the conversation-derived fallback.
    if _looks_like_cot_transcript(cleaned):
        return ""
    return cleaned


def _fallback_summary(conversation: Any) -> str:
    """Build a 1-2 sentence recap from conversation history without calling the LLM.

    Used when the model returned empty content or leaked chain-of-thought
    into ``content``. The output mirrors the LLM path's format — exactly
    1-2 plain sentences (no markdown, no bullets), with a goal + next-action
    shape — so users get a consistent reading experience whether the recap
    was LLM-generated or fell back to conversation-derived text.
    """
    messages = list(getattr(conversation, "messages", []) or [])
    is_zh = infer_response_language(conversation) == "Chinese"

    user_messages: list[str] = []
    assistant_messages: list[str] = []

    for msg in messages:
        role = getattr(msg, "role", "")
        content = getattr(msg, "content", "")
        if role == "user":
            text = _flatten_content(content).strip()
            if text:
                user_messages.append(text)
        elif role == "assistant":
            text = _flatten_content(content).strip()
            if text and not text.startswith("[tool:"):
                assistant_messages.append(text)

    if not user_messages and not assistant_messages:
        return (
            "会话刚开始，暂无内容。请直接告诉我你想做什么。" if is_zh
            else "The session just started; nothing to recap yet. Tell me what you'd like to do next."
        )

    last_user = user_messages[-1]
    user_point = _leading_point(last_user, limit=80)

    if not assistant_messages:
        if is_zh:
            return f"你正在进行：{user_point}。等待助手响应后继续。"
        return f"You're working on: {user_point}. Waiting for the assistant to respond."

    last_asst = assistant_messages[-1]
    asst_point = _leading_point(last_asst, limit=80)

    if is_zh:
        return f"你正在进行：{user_point}。助手已回复：{asst_point}。请从中断处继续。"
    return (
        f"You're working on: {user_point}. "
        f"Assistant last replied: {asst_point}. Continue from where you left off."
    )


def _leading_point(text: str, limit: int = 140) -> str:
    """Return the leading point of ``text`` for use in a recap.

    Prefers the first sentence (terminated by ``. ! ? 。 ！ ？``) when it
    fits in ``limit`` characters; otherwise truncates with an ellipsis.
    """
    if not text:
        return ""
    flat = " ".join(text.split())
    for sep in (". ", "! ", "? ", "。", "！", "？"):
        idx = flat.find(sep)
        if 0 < idx < limit:
            return flat[: idx + len(sep)].strip()
    if len(flat) > limit:
        return flat[:limit].rstrip() + "…"
    return flat


def _extract_actions_and_files(
    content: Any,
) -> tuple[list[str], set[str]]:
    """Return (action_labels, file_paths) from an assistant message content."""
    actions: list[str] = []
    files: set[str] = set()

    if isinstance(content, list):
        for block in content:
            kind = getattr(block, "type", None)
            if kind == "tool_use":
                name = str(getattr(block, "name", "") or "")
                inp = getattr(block, "input", {}) or {}
                file_path = _find_file_path(inp)
                label = name if not file_path else f"{name}({file_path})"
                actions.append(label)
                if file_path:
                    files.add(file_path)
            elif isinstance(block, dict):
                if block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    inp = block.get("input", {}) or {}
                    file_path = _find_file_path(inp)
                    label = name if not file_path else f"{name}({file_path})"
                    actions.append(label)
                    if file_path:
                        files.add(file_path)
    return actions, files


def _find_file_path(inp: dict[str, Any]) -> str:
    """Extract a file path from a tool call input dict."""
    for key in ("file_path", "path", "target", "file"):
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Some tool calls embed path in the first positional argument.
    for key in ("argument", "content", "text"):
        val = inp.get(key)
        if isinstance(val, str) and ("." in val or "/" in val):
            return val.strip()[:120]
    return ""


def _dedup_ordered(items: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _flatten_content_block(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(content).strip()


def _flatten_content_block(block: Any) -> str:
    if isinstance(block, str):
        return block.strip()
    if isinstance(block, dict):
        kind = block.get("type")
        if kind in (None, "text"):
            return str(block.get("text") or block.get("content") or "").strip()
        if kind == "tool_use":
            name = str(block.get("name") or "tool").strip()
            return f"[tool:{name}]"
        if kind == "tool_result":
            return str(block.get("content") or "").strip()
        if kind == "thinking":
            return str(block.get("thinking") or "").strip()
        if kind == "redacted_thinking":
            return "[redacted thinking]"
        if kind in {"image", "document"}:
            return f"[{kind}]"
        return ""

    kind = getattr(block, "type", None)
    if kind == "text" or hasattr(block, "text"):
        return str(getattr(block, "text", "") or "").strip()
    if kind == "tool_use":
        name = str(getattr(block, "name", "") or "tool").strip()
        return f"[tool:{name}]"
    if kind == "tool_result":
        return _flatten_content(getattr(block, "content", ""))
    if kind == "thinking":
        return str(getattr(block, "thinking", "") or "").strip()
    if kind == "redacted_thinking":
        return "[redacted thinking]"
    if kind in {"image", "document"}:
        return f"[{kind}]"
    return str(block).strip()

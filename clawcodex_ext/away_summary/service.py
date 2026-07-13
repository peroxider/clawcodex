"""Summary service shared by automatic Away Summary and /recap."""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Fork-path helpers
# ---------------------------------------------------------------------------


class _ForkUnavailable(Exception):
    """Raised when the fork path cannot be used; caller falls back to chat."""


def _generate_via_chat(
    provider: Any,
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    max_output_tokens: int,
) -> Any:
    """Synchronous provider.chat call with retry on transient TLS errors.

    Mirrors the legacy retry policy: up to two attempts with a 1-second
    sleep between them, since transient SSL EOFs are common when the
    recap fires right after a long idle period.
    """
    _last_exc: Exception | None = None
    for attempt in range(2):
        if attempt > 0:
            logger.info("Retrying Away Summary API call (attempt %d/2)", attempt + 1)
            time.sleep(1.0)
        try:
            return provider.chat(
                messages=messages,
                tools=None,
                model=model,
                max_tokens=max_output_tokens,
            )
        except TypeError:
            # Some providers reject max_tokens — fall back to no limit.
            try:
                return provider.chat(
                    messages=messages,
                    tools=None,
                    model=model,
                )
            except Exception as exc:
                _last_exc = exc
                continue
        except Exception as exc:
            _last_exc = exc
            continue
    if _last_exc is not None:
        raise _last_exc
    # Unreachable: the loop always either returns or sets _last_exc.
    raise RuntimeError("Away Summary: provider.chat loop exited without result")


def _generate_via_fork(
    cache_safe_params: Any,
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    max_output_tokens: int,
) -> Any:
    """Run the recap through ``run_forked_agent`` to reuse the cache prefix.

    Falls back to ``_ForkUnavailable`` (so the caller can drop down to a
    fresh ``provider.chat``) when:

    * an event loop is already running (``asyncio.run`` would raise),
    * the fork primitive or its dependencies can't be imported,
    * the tool_use_context is missing ``_active_provider`` (fork can't
      route the request),
    * the resulting fork returned no assistant messages.
    """
    try:
        asyncio.get_running_loop()
        # We're inside another loop — ``asyncio.run`` would crash.
        # Fall back rather than corrupt the host loop.
        raise _ForkUnavailable("running event loop detected")
    except RuntimeError as exc:
        # ``get_running_loop`` raises RuntimeError when there's no loop.
        # Re-raise as ForkUnavailable only when we actually got "no
        # current event loop" *and* we're not the caller of get_running_loop.
        # The structure of the try/except above guarantees we never
        # reach here on the "no loop" path, so any RuntimeError here is
        # genuinely the "running loop" branch.
        if "no running event loop" not in str(exc).lower() and \
                "no current event loop" not in str(exc).lower():
            raise _ForkUnavailable(str(exc))

    try:
        from clawcodex_ext.agent.forked_agent import (
            ForkedAgentParams,
            PermissionDecision,
            run_forked_agent,
        )
        from clawcodex_ext.types.content_blocks import TextBlock
        from clawcodex_ext.types.messages import create_user_message
    except Exception as exc:
        raise _ForkUnavailable(f"import failed: {exc}") from exc

    parent_context = getattr(cache_safe_params, "tool_use_context", None)
    if parent_context is None:
        raise _ForkUnavailable("cache_safe_params has no tool_use_context")
    if getattr(parent_context, "_active_provider", None) is None:
        raise _ForkUnavailable("parent tool_use_context has no _active_provider")

    user_text = _extract_user_text(messages)
    if not user_text:
        raise _ForkUnavailable("recap user message has no extractable text")

    prompt_messages = [
        create_user_message(content=[TextBlock(text=user_text)])
    ]

    async def _deny_all(_tool_use: Any) -> PermissionDecision:
        return PermissionDecision(behavior="deny", reason="away_summary")

    async def _run() -> Any:
        return await run_forked_agent(
            ForkedAgentParams(
                prompt_messages=prompt_messages,
                cache_safe_params=cache_safe_params,
                can_use_tool=_deny_all,
                query_source="away_summary",
                fork_label="away_summary",
                max_turns=1,
                skip_cache_write=True,
                skip_transcript=True,
            )
        )

    try:
        fork_result = asyncio.run(_run())
    except RuntimeError as exc:
        # ``asyncio.run`` inside a running loop is the most likely cause.
        if "running event loop" in str(exc).lower() or "asyncio.run()" in str(exc):
            raise _ForkUnavailable("nested event loop") from exc
        raise

    assistant_text = _extract_fork_assistant_text(fork_result)
    if not assistant_text:
        raise _ForkUnavailable("fork produced no assistant text")

    # Wrap into a ChatResponse-shaped object so the existing extraction
    # pipeline (``_extract_summary`` + CoT stripping) works unchanged.
    return _build_chat_response(assistant_text, model=model)


def _extract_user_text(messages: list[dict[str, Any]]) -> str:
    """Pick the last user-role message's text content from a chat pair."""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        parts.append(str(item.get("text") or ""))
                    else:
                        text = getattr(item, "text", None)
                        if text is not None:
                            parts.append(str(text))
                return "\n".join(p for p in parts if p)
    return ""


def _extract_fork_assistant_text(fork_result: Any) -> str:
    """Concatenate text from the first assistant message in the fork."""
    from clawcodex_ext.types.content_blocks import TextBlock
    from clawcodex_ext.types.messages import AssistantMessage

    messages = getattr(fork_result, "messages", []) or []
    for msg in messages:
        if not isinstance(msg, AssistantMessage):
            continue
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


def _build_chat_response(text: str, *, model: str | None) -> Any:
    """Wrap a raw assistant string into a ChatResponse-like object."""
    from clawcodex_ext.providers.base import ChatResponse

    return ChatResponse(
        content=text,
        model=model or "",
        usage={},
        finish_reason="stop",
    )


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
        memory: str | None = None,
    ) -> None:
        self.conversation = conversation
        self.provider = provider
        self.model = model
        self.session = session
        self.config = config or AwaySummaryConfig()
        # Optional broader session-memory block to inject into auto
        # recaps (matches the canonical upstream behaviour of prepending
        # ``getSessionMemoryContent()`` to the auto prompt). When None
        # the service falls back to the previous behaviour.
        self.memory = memory

    def generate(
        self,
        *,
        trigger: str,
        force: bool = False,
        persist: bool | None = None,
        cache_safe_params: Any | None = None,
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
            trigger=trigger,
            memory=self.memory,
        )

        # Decide the execution path. Cache-safe params (saved by the main
        # query loop after each turn) let the recap share the parent's
        # prompt-cache prefix via ``run_forked_agent`` — significantly
        # cheaper than an independent provider call. Disabled by config
        # or when no live cache-safe params are available; in either
        # case we fall back to a synchronous ``provider.chat`` call.
        used_fork = False
        if (
            self.config.enable_recap_cache
            and cache_safe_params is not None
            and trigger == "manual"
        ):
            try:
                response = _generate_via_fork(
                    cache_safe_params,
                    messages,
                    model=self.model,
                    max_output_tokens=self.config.max_output_tokens,
                )
                used_fork = True
            except _ForkUnavailable:
                logger.debug(
                    "Away Summary: fork path unavailable, falling back to provider.chat"
                )
                response = None
            except Exception as exc:
                logger.debug(
                    "Away Summary: fork path raised %s, falling back to provider.chat",
                    type(exc).__name__,
                )
                response = None
        else:
            response = None

        if response is None:
            response = _generate_via_chat(
                self.provider,
                messages,
                model=self.model,
                max_output_tokens=self.config.max_output_tokens,
            )

        if used_fork:
            logger.info(
                "Away Summary: served via forked agent (cache-safe prefix reused)"
            )
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
    """Build a natural, flexible recap from conversation history.

    Used when the model returned empty content or leaked chain-of-thought
    into ``content``. The output is a short handoff: one flowing sentence
    that captures the goal and current state, optionally followed by a few
    plain bullets that surface whatever context matters most (files touched,
    tools used, next step). When no files were touched and no tools were
    used, the bullets are skipped so a bare greeting doesn't end with a
    low-value "Continue with hello" bullet.
    """
    messages = list(getattr(conversation, "messages", []) or [])
    is_zh = infer_response_language(conversation) == "Chinese"

    user_messages: list[str] = []
    assistant_messages: list[str] = []
    files_touched: set[str] = set()
    tool_actions: list[str] = []

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
            actions, fnames = _extract_actions_and_files(content)
            tool_actions.extend(actions)
            files_touched.update(fnames)

    if not user_messages and not assistant_messages:
        return (
            "会话刚开始，暂无内容。请直接告诉我你想做什么。" if is_zh
            else "The session just started; nothing to recap yet. Tell me what you'd like to do next."
        )

    last_user = user_messages[-1]
    user_point = _leading_point(last_user, limit=80)

    if not assistant_messages:
        if is_zh:
            sentence = f"我们刚聊到 {user_point}，还没有收到助手回应。"
        else:
            sentence = f"We were talking about {user_point} and haven't heard back from the assistant yet."
    else:
        last_asst = assistant_messages[-1]
        asst_point = _leading_point(last_asst, limit=80)
        if is_zh:
            sentence = f"我们正在处理 {user_point}，助手回应了：{asst_point}"
        else:
            sentence = f"We're working on {user_point}. The assistant just replied: {asst_point}"

    bullets = _fallback_bullets(
        user_messages[-1] if user_messages else "",
        files_touched,
        tool_actions,
        is_zh=is_zh,
    )
    if bullets:
        intro = "后续计划" if is_zh else "Next steps"
        return sentence + "\n" + intro + "\n" + "\n".join(bullets)
    return sentence


def _fallback_bullets(
    last_user: str,
    files_touched: set[str],
    tool_actions: list[str],
    *,
    is_zh: bool,
) -> list[str]:
    """Build plain, label-free bullets for the fallback recap.

    Both English and Chinese sessions use the ASCII hyphen "-" as the
    bullet marker so the recap renders consistently as Markdown.

    When no files were touched and no tools were used, the only
    possible bullet would be "Continue with <last user message>". That
    is low-value for short greetings (e.g. "hello" → "Continue with
    hello"), so we omit the bullet list entirely in that case and let
    the leading sentence carry the recap.
    """
    marker = "-"
    bullets: list[str] = []

    if files_touched:
        shown = sorted(files_touched)[:4]
        extra = " …" if len(files_touched) > 4 else ""
        bullets.append(f"{marker} {', '.join(shown)}{extra}")

    if tool_actions:
        unique_actions = _dedup_ordered(tool_actions)[:4]
        extra = " …" if len(tool_actions) > 4 else ""
        bullets.append(f"{marker} {', '.join(unique_actions)}{extra}")

    if not bullets:
        # Nothing concrete to surface; skip the generic next-step bullet.
        return []

    # Only add a next-step bullet when there is already something
    # concrete (files or actions) to give it context.
    next_step = _leading_point(last_user, limit=60)
    if is_zh:
        bullets.append(f"{marker} 继续 {next_step}")
    else:
        bullets.append(f"{marker} Continue with {next_step}")

    return bullets


def _fallback_labels(
    files_touched: set[str],
    tool_actions: list[str],
    *,
    is_zh: bool,
) -> list[str]:
    """Build the optional structured-label section of the fallback recap.

    Returns an empty list when there is nothing meaningful to surface
    (i.e. no tool calls happened in the session) so the caller knows to
    skip the section entirely. When tool calls happened, returns the
    populated subsets of:

    * ``Files mentioned: a, b, c`` — distinct file paths touched by tool_use.
    * ``Actions taken: Edit(file.py), Bash(...)`` — deduped tool labels.

    Both lists are capped at 6 entries so the recap never balloons past
    the readable budget, with a trailing ``… and N more`` marker when the
    cap is hit.
    """
    if not tool_actions and not files_touched:
        return []

    lines: list[str] = []
    files_label = "涉及文件" if is_zh else "Files mentioned"
    actions_label = "执行操作" if is_zh else "Actions taken"

    if files_touched:
        sorted_files = sorted(files_touched)
        shown = sorted_files[:6]
        if len(sorted_files) > 6:
            shown_text = ", ".join(shown) + (
                f" … 等 {len(sorted_files)} 项" if is_zh else f" … and {len(sorted_files) - 6} more"
            )
        else:
            shown_text = ", ".join(shown)
        lines.append(f"{files_label}: {shown_text}")

    if tool_actions:
        unique_actions = _dedup_ordered(tool_actions)
        shown = unique_actions[:6]
        if len(unique_actions) > 6:
            shown_text = ", ".join(shown) + (
                f" … 等 {len(unique_actions)} 项" if is_zh else f" … and {len(unique_actions) - 6} more"
            )
        else:
            shown_text = ", ".join(shown)
        lines.append(f"{actions_label}: {shown_text}")

    return lines


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

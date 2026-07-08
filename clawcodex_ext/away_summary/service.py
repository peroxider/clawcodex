"""Summary service shared by automatic Away Summary and /recap."""

from __future__ import annotations

import logging
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
from clawcodex_ext.away_summary.prompt import build_summary_messages

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
        summary = str(getattr(response, "content", "") or "").strip()
        if not summary:
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


def _fallback_summary(conversation: Any) -> str:
    messages = list(getattr(conversation, "messages", []) or [])
    last_user = ""
    last_assistant = ""
    for msg in reversed(messages):
        role = getattr(msg, "role", "")
        content = _flatten_content(getattr(msg, "content", ""))
        if role == "user" and not last_user:
            last_user = content[:180]
        elif role == "assistant" and not last_assistant:
            last_assistant = content[:180]
        if last_user and last_assistant:
            break
    parts = [f"Conversation has {len(messages)} messages."]
    if last_user:
        parts.append(f"Last user request: {last_user}")
    if last_assistant:
        parts.append(f"Last assistant response: {last_assistant}")
    return "\n".join(parts)


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

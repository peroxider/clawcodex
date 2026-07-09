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
            reasoning = str(getattr(response, "reasoning_content", "") or "").strip()
            if reasoning:
                summary = reasoning
            else:
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
    """Build a readable summary from conversation history without calling the LLM.

    Scans messages to extract user intents, files touched, and key actions,
    producing a structured recap that does not look like raw internal metadata.
    """
    messages = list(getattr(conversation, "messages", []) or [])

    # Collect rich information from each turn.
    user_requests: list[str] = []
    files_touched: set[str] = set()
    tool_actions: list[str] = []
    last_msgs: list[str] = []

    for msg in messages:
        role = getattr(msg, "role", "")
        content = getattr(msg, "content", "")
        if role == "user":
            text = _flatten_content(content)
            text = text[:300].rstrip()
            if text:
                user_requests.append(text)
                last_msgs.append(f"User: {text}")
        elif role == "assistant":
            actions, fnames = _extract_actions_and_files(content)
            tool_actions.extend(actions)
            files_touched.update(fnames)
            text = _flatten_content(content)[:300].rstrip()
            if text and not text.startswith("[tool:"):
                last_msgs.append(f"Assistant: {text}")

    parts: list[str] = []

    # Summarise the conversation scope.
    if not user_requests:
        parts.append(f"This session has {len(messages)} messages.")
    else:
        first = user_requests[0][:200]
        parts.append(f"This session has {len(messages)} messages across {len(user_requests)} user requests.")
        parts.append(f"Started with: {first}")

    # What files were touched.
    if files_touched:
        file_list = sorted(files_touched, key=lambda p: (p.count("/"), p))[:12]
        if len(file_list) <= 6:
            parts.append("Files mentioned: " + ", ".join(file_list))
        else:
            parts.append("Files mentioned: " + ", ".join(sorted(files_touched)[:6]) + " … and more")

    # What tool actions were taken.
    if tool_actions:
        unique_actions = _dedup_ordered(tool_actions)
        parts.append("Actions taken: " + ", ".join(unique_actions[:6]))

    # Last user request (useful for context).
    if user_requests:
        last_req = user_requests[-1][:240]
        if last_req not in parts[-1]:
            parts.append(f"Latest task: {last_req}")

    return "\n".join(parts)


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

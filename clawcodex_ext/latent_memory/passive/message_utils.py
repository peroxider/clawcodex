from __future__ import annotations

import json
import re
from typing import Any

from clawcodex_ext.types.content_blocks import TextBlock, ToolResultBlock, ToolUseBlock
from clawcodex_ext.types.messages import AssistantMessage, Message, UserMessage
from clawcodex_ext.utils.token_estimation import count_tokens


_CONTINUATION_RE = re.compile(
    r"(?:上次|之前|继续|接着|刚才|前面|原来|还是|那个|此前|previous|continue|earlier|last time)",
    re.IGNORECASE,
)
_TRIVIAL_RE = re.compile(
    r"^(?:你好|您好|嗨|谢谢|多谢|好的|好|嗯|收到|明白|可以|ok|okay|thanks|thank you|hello|hi)[!！。.\s]*$",
    re.IGNORECASE,
)
_STRONG_MEMORY_RE = re.compile(
    r"(?:记住|以后|从现在起|偏好|约定|最终决定|确认采用|根因是|下次|remember|from now on|preference|decided)",
    re.IGNORECASE,
)
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|password|secret)\s*[:=]\s*([^\s,;]+)"
)


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(part.strip() for part in parts if part.strip()).strip()


def is_real_user_message(message: Message) -> bool:
    if not isinstance(message, UserMessage):
        return False
    if message.isMeta or message.isCompactSummary or message.toolUseResult is not None:
        return False
    if message.origin in {"tool_result", "system_injection", "compact_summary"}:
        return False
    if isinstance(message.content, list):
        for block in message.content:
            block_type = (
                block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            )
            if block_type == "tool_result":
                return False
    return bool(text_from_content(message.content))


def latest_user_prompt(messages: list[Message]) -> str:
    for message in reversed(messages):
        if is_real_user_message(message):
            return text_from_content(message.content)
    return ""


def is_trivial_prompt(prompt: str) -> bool:
    normalized = prompt.strip()
    return not normalized or bool(_TRIVIAL_RE.fullmatch(normalized))


def build_search_query(messages: list[Message]) -> str:
    user_indices = [
        index for index, message in enumerate(messages) if is_real_user_message(message)
    ]
    if not user_indices:
        return ""
    current_index = user_indices[-1]
    current = text_from_content(messages[current_index].content)
    if len(current) >= 80 and not _CONTINUATION_RE.search(current):
        return _truncate(current, 2000)
    if len(user_indices) < 2:
        return _truncate(current, 2000)

    previous_index = user_indices[-2]
    previous_user = text_from_content(messages[previous_index].content)
    return (
        f"Current request:\n{_truncate(current, 2000)}\n\n"
        f"Previous user request:\n{_truncate(previous_user, 1200)}"
    )[:3300]


def build_capture_messages(
    messages: list[Message],
    *,
    max_tokens: int,
) -> tuple[list[dict[str, str]], str]:
    start = _latest_real_user_index(messages)
    if start is None:
        return [], "none"
    segment = messages[start:]
    prompt = text_from_content(segment[0].content)
    if is_trivial_prompt(prompt):
        return [], "trivial"

    tool_names: dict[str, str] = {}
    assistant_texts: list[str] = []
    tool_evidence: list[str] = []
    for message in segment[1:]:
        if isinstance(message, AssistantMessage):
            text = text_from_content(message.content)
            if text:
                assistant_texts.append(text)
            for block in message.content if isinstance(message.content, list) else []:
                if isinstance(block, ToolUseBlock):
                    tool_names[block.id] = block.name
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_names[str(block.get("id", ""))] = str(block.get("name", "tool"))
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                evidence = _tool_evidence(block, tool_names)
                if evidence:
                    tool_evidence.append(evidence)

    if not assistant_texts:
        return [], "no_assistant"

    payload: list[dict[str, str]] = [{"role": "user", "content": _redact(_truncate(prompt, 8000))}]
    if len(assistant_texts) > 1:
        intermediate = "\n\n".join(assistant_texts[:-1])
        if intermediate.strip():
            payload.append(
                {
                    "role": "assistant",
                    "content": _redact(_truncate(intermediate, 4000)),
                }
            )
    if tool_evidence:
        payload.append(
            {
                "role": "system",
                "content": "Verified tool evidence:\n"
                + _redact(_truncate("\n".join(tool_evidence[:4]), 8000)),
            }
        )
    payload.append(
        {
            "role": "assistant",
            "content": _redact(_truncate(assistant_texts[-1], 12000)),
        }
    )
    payload = _fit_token_budget(payload, max_tokens)
    return payload, "strong" if _STRONG_MEMORY_RE.search(prompt) else "normal"


def _latest_real_user_index(messages: list[Message]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if is_real_user_message(messages[index]):
            return index
    return None


def _tool_evidence(block: Any, tool_names: dict[str, str]) -> str:
    if isinstance(block, ToolResultBlock):
        tool_use_id = block.tool_use_id
        content = block.content
        is_error = block.is_error
    elif isinstance(block, dict) and block.get("type") == "tool_result":
        tool_use_id = str(block.get("tool_use_id", ""))
        content = block.get("content", "")
        is_error = bool(block.get("is_error", False))
    else:
        return ""
    name = tool_names.get(tool_use_id, "tool")
    if isinstance(content, list):
        content_text = json.dumps(content, ensure_ascii=False, default=str)
    else:
        content_text = str(content)
    status = "error" if is_error else "success"
    return f"- {name}: {status}; output={_truncate(content_text, 2000)}"


def _fit_token_budget(payload: list[dict[str, str]], max_tokens: int) -> list[dict[str, str]]:
    total = sum(count_tokens(item["content"]) for item in payload)
    if total <= max_tokens:
        return payload
    max_chars = max_tokens * 4
    current_chars = sum(len(item["content"]) for item in payload) or 1
    ratio = max_chars / current_chars
    fitted: list[dict[str, str]] = []
    for item in payload:
        minimum = 500 if item["role"] in {"user", "assistant"} else 200
        limit = max(minimum, int(len(item["content"]) * ratio))
        fitted.append({**item, "content": _truncate(item["content"], limit)})
    return fitted


def _redact(text: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def _truncate(text: str, limit: int) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    if limit < 20:
        return value[:limit]
    head = int(limit * 0.7)
    tail = limit - head - 16
    return f"{value[:head]}\n...[truncated]...\n{value[-tail:]}"


__all__ = [
    "build_capture_messages",
    "build_search_query",
    "is_real_user_message",
    "is_trivial_prompt",
    "latest_user_prompt",
    "text_from_content",
]

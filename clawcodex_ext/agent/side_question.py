"""Side question execution wrapper.

Mirrors ``typescript/src/utils/sideQuestion.ts``.

Wraps ``run_forked_agent`` with the constraints specific to a /btw
side-question:

* max_turns = 1  (single-shot answer, no follow-up)
* can_use_tool = deny-all  (no tool execution)
* query_source = "side_question"
* skip_cache_write = True  (don't pollute the parent's prompt cache)
* Injects a <system-reminder> wrapped directive so the model knows it is
  an independent instance with no tools and no interruption semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from clawcodex_ext.agent.forked_agent import (
    CacheSafeParams,
    ForkedAgentParams,
    ForkedAgentResult,
    PermissionDecision,
    run_forked_agent,
)
from clawcodex_ext.types.content_blocks import TextBlock
from clawcodex_ext.types.messages import Message, AssistantMessage, create_user_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt template (Chinese, matching project interaction language)
# ---------------------------------------------------------------------------

_WRAPPED_TEMPLATE = """<system-reminder>这是一个侧边问题（side question），来自用户。

重要上下文:
- 你是一个独立的轻量 Agent，仅用于回答这一个问题
- 主 Agent 没有被中断——它正在后台独立继续工作
- 你共享对话上下文，但完全是一个独立实例
- 不要提及"被中断"或"之前正在做什么"——这种表述不正确

关键约束:
- 你没有任何工具可用——不能读文件、运行命令、搜索或执行任何操作
- 这是单次回答——没有后续轮次
- 你只能基于已有的知识回答
- 绝不要说"让我试试"、"我现在就"、"让我查一下"或承诺任何行动
- 如果你不知道答案，直接说不知道——不要提议去查

直接根据你已知的信息回答问题。</system-reminder>

{question}"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SideQuestionResult:
    """Result of a side question."""

    response: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core wrapper
# ---------------------------------------------------------------------------

async def run_side_question(
    question: str,
    cache_safe_params: CacheSafeParams,
) -> SideQuestionResult:
    """Run a side question in an isolated fork.

    Args:
        question: The user's question text (already stripped).
        cache_safe_params: Frozen snapshot of the parent's API prefix.

    Returns:
        SideQuestionResult with the text response and usage info.
    """
    wrapped_question = _WRAPPED_TEMPLATE.format(question=question)
    prompt_messages = [create_user_message(content=[TextBlock(text=wrapped_question)])]

    async def _deny_all(_tool_use: Any) -> PermissionDecision:
        return PermissionDecision(behavior="deny")

    fork_params = ForkedAgentParams(
        prompt_messages=prompt_messages,
        cache_safe_params=cache_safe_params,
        can_use_tool=_deny_all,
        query_source="side_question",
        max_turns=1,
        skip_cache_write=True,
        skip_transcript=True,
    )

    result: ForkedAgentResult = await run_forked_agent(fork_params)
    response = extract_side_question_response(result.messages)
    return SideQuestionResult(response=response, usage=result.total_usage)


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------

def extract_side_question_response(messages: list[Message]) -> str | None:
    """Extract the text response from the fork's message stream.

    Looks for the first AssistantMessage containing text blocks and
    concatenates their text content.
    """
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            content = msg.content
            if isinstance(content, str) and content:
                return content.strip() or None
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                text = "".join(parts).strip()
                return text or None
    return None

from src.agent.conversation import Conversation
from src.types.messages import Message

from clawcodex_ext.away_summary.prompt import build_summary_messages
from clawcodex_ext.types.content_blocks import TextBlock, ToolUseBlock


def test_summary_prompt_omits_no_content_placeholder_but_keeps_tool_call() -> None:
    conversation = Conversation()
    conversation.messages = [
        Message(role="user", content="修改文档"),
        Message(
            role="assistant",
            content=[
                TextBlock(text="[No content]"),
                ToolUseBlock(id="edit-1", name="Edit", input={"path": "report.md"}),
            ],
        ),
    ]

    messages = build_summary_messages(conversation, max_input_tokens=4_000)
    prompt = "\n".join(m["content"] for m in messages)

    assert "[No content]" not in prompt
    assert "tool_use Edit" in prompt
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

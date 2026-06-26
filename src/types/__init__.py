"""Typed message/content models for Claude Code parity work.

This module is a fork-side facade: it re-exports the type re-exports
from :mod:`clawcodex_ext.types` and adds a small fork delta — the
upstream archive placeholder metadata (SNAPSHOT_PATH, ARCHIVE_NAME,
MODULE_COUNT, SAMPLE_FILES, PORTING_NOTE) which depends on the file
location in src/. Existing ``from src.types import ...`` callers
keep working.
"""

from __future__ import annotations

import json
from pathlib import Path

# Re-export the upstream type re-exports from clawcodex_ext.types.
from clawcodex_ext.types import *  # noqa: F401,F403

# Fork delta: archive placeholder metadata.
SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / 'reference_data' / 'subsystems' / 'types.json'
)
_SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())

ARCHIVE_NAME = _SNAPSHOT['archive_name']
MODULE_COUNT = _SNAPSHOT['module_count']
SAMPLE_FILES = tuple(_SNAPSHOT['sample_files'])
PORTING_NOTE = f"Python placeholder package for '{ARCHIVE_NAME}' with {MODULE_COUNT} archived module references."

__all__ = [
    'ARCHIVE_NAME',
    'CANCEL_MESSAGE',
    'AssistantMessage',
    'AttachmentMessage',
    'ContentBlock',
    'ContentBlockDelta',
    'ContentBlockStart',
    'ContentBlockStop',
    'DocumentBlock',
    'INTERRUPT_MESSAGE',
    'INTERRUPT_MESSAGE_FOR_TOOL_USE',
    'ImageBlock',
    'MODULE_COUNT',
    'Message',
    'MessageContent',
    'MessageDelta',
    'MessageLike',
    'MessageOrigin',
    'MessageStart',
    'MessageStop',
    'MessageType',
    'NO_CONTENT_MESSAGE',
    'NO_RESPONSE_REQUESTED',
    'PORTING_NOTE',
    'ProgressMessage',
    'REJECT_MESSAGE',
    'REJECT_MESSAGE_WITH_REASON_PREFIX',
    'RedactedThinkingBlock',
    'SAMPLE_FILES',
    'StreamEvent',
    'SystemMessage',
    'TextBlock',
    'ThinkingBlock',
    'ToolResultBlock',
    'ToolUseBlock',
    'TypedMessage',
    'UserMessage',
    'content_block_from_dict',
    'content_block_to_dict',
    'create_assistant_api_error_message',
    'create_assistant_message',
    'create_message',
    'create_progress_message',
    'create_system_message',
    'create_user_message',
    'get_last_assistant_message',
    'get_tool_use_ids',
    'is_tool_use_request_message',
    'is_tool_use_result_message',
    'message_from_dict',
    'message_to_dict',
    'normalize_content_blocks',
    'normalize_message_for_api',
    'normalize_messages_for_api',
    'stream_event_from_dict',
    'stream_event_to_dict',
]

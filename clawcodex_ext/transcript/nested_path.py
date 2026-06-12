"""子 agent transcript 嵌套到主会话目录的路径解析器（扩展）。

将 18cf565 的硬编码嵌套逻辑从 ``src/agent/transcript.py`` 解耦到此处。
核心默认回退到 flat ``~/.clawcodex/transcripts/<id>.jsonl``，
通过 ``register_transcript_path_resolver`` 注册后启用嵌套。

路径格式::

    ~/.clawcodex/sessions/<parent_session_id>/subagents/agent-<agent_id>.jsonl

每行 JSONL 额外携带 ``"parent_session_id": "<uuid>"`` 字段
（由 ``TranscriptWriter`` 在 ``src/agent/transcript.py`` 中注入）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def nested_session_path_resolver(
    agent_id: str,
    parent_session_id: str | None = None,
) -> str | None:
    """当有 *parent_session_id* 时，嵌套到 sessions/<id>/subagents/ 下。

    返回绝对路径字符串，或 ``None`` 回退到核心默认 flat 目录。
    """
    if not parent_session_id:
        return None  # 回退到 flat ~/.clawcodex/transcripts/

    _safe_session = _sanitize_for_path(parent_session_id)
    root = Path.home() / ".clawcodex" / "sessions" / _safe_session / "subagents"
    root.mkdir(parents=True, exist_ok=True)
    return str(root / f"agent-{agent_id}.jsonl")


def _sanitize_for_path(name: str) -> str:
    """轻量 sanitize — 只允许字母数字、连字符、下划线。"""
    if not name or not all(c.isalnum() or c in "_-" for c in name):
        raise ValueError(
            f"invalid component for session path: {name!r} "
            "(allowed: alphanumeric + '_' + '-')"
        )
    if len(name) > 128:
        raise ValueError(f"session_id too long ({len(name)} > 128 chars)")
    return name


def init() -> None:
    """在扩展加载入口点注册嵌套路径解析器。

    调用方式（在 ``clawcodex_ext/__init__.py`` 或入口点中）：:

        from clawcodex_ext.transcript.nested_path import init
        init()
    """
    from src.agent.transcript import register_transcript_path_resolver

    register_transcript_path_resolver(nested_session_path_resolver)
    import logging

    logging.getLogger(__name__).info(
        "registered nested-session transcript path resolver"
    )


__all__ = [
    "nested_session_path_resolver",
    "init",
]

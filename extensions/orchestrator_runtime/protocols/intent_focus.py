"""Orchestrator Runtime — IntentFocus Protocol（Phase 1）。

声明"问题意图聚焦"的契约 —— 给定 issue + workspace 路径，返回
orchestrator 要重点编辑的文件/区域列表。Phase 2 落地默认实现
(从 ``clawcodex_ext.intent_forecast.focus.compute_workspace_focuses`` 复制)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class IssueLike(Protocol):
    """Structural type for an issue to compute focuses for. Attributes
    are compatible with ``extensions.orchestrator.issue.Issue``.
    """

    issue_id: str
    title: str
    body: str


@dataclass(slots=True)
class FocusArea:
    """One focus area in a workspace.

    Attributes:
        path: file path relative to workspace root
        rationale: human-readable reasoning
        confidence: 0.0..1.0
    """

    path: str
    rationale: str
    confidence: float = 1.0


@runtime_checkable
class IntentFocus(Protocol):
    """Workspace focus computation."""

    def compute_workspace_focuses(
        self,
        workspace: Path,
        issue: IssueLike,
    ) -> list[FocusArea]:
        ...


__all__ = ["FocusArea", "IntentFocus", "IssueLike"]

"""Orchestrator Runtime — WorkspaceTooling Protocol（Phase 1）。

声明 Workspace 元数据与工具上下文的契约。Phase 3 让 AgentRunner 调用
``WorkspaceTooling.build_tool_context`` 而非 ``ToolContext(...)``，把
上游 ToolContext 替换为最小结构性 ``ToolContextLike``。

完整契约见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §4.2。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


@runtime_checkable
class ToolContextLike(Protocol):
    """Minimal structural type — runtime doesn't introspect fields beyond
    :attr:`workspace_root` and :attr:`cwd`.

    Compatible with ``clawcodex_ext.tool_system.context.ToolContext`` and
    with Phase 2's wrapper in
    ``extensions.orchestrator_runtime.utils.git_backend_impl`` if it ever
    needs a tool context (it currently doesn't).

    Phase 3 adds optional fields (``plan_mode``, ``permission_context``)
    when AgentRunner starts building tool contexts.
    """

    workspace_root: Path | None
    cwd: Path | None


@runtime_checkable
class WorkspaceTooling(Protocol):
    """Informs the agent runtime about the workspace being orchestrated.

    The orchestrator's :class:`AgentRunner` calls into the tooling to
    * register custom progress-report tools
    * expose workspace metadata (branch, focus area, rules…)
    """

    def build_tool_context(
        self,
        workspace: Path,
        *,
        branch: str | None = None,
        focus_files: tuple[str, ...] = (),
        rule_hints: tuple[str, ...] = (),
    ) -> ToolContextLike:
        """Return an opaque tool context the runtime passes to tool registry."""
        ...

    def progress_report_callback(self) -> Callable[[str], Awaitable[None]] | None:
        """Hook the agent invokes via the internal ``progress_report`` tool.

        ``None`` if the workspace doesn't support progress reports.
        """
        ...

    def task_update_callback(self) -> Callable[[str, str], Awaitable[None]] | None:
        """Hook the agent invokes via the internal ``task_update`` tool.

        ``None`` if the workspace doesn't support task updates.
        """
        ...


__all__ = ["ToolContextLike", "WorkspaceTooling"]

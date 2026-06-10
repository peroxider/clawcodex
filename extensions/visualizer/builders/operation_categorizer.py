"""Operation categorizer (F-95 waterfall legend).

Maps a ``TimelineBar`` to one of five ``OperationCategory`` buckets that
match the reference visualization's top legend:

  读取  READ          🟢 Read / Glob / Grep / WebFetch / WebSearch
  执行  EXECUTE       🔵 Bash / Execute / TaskKill / BashOutput / KillShell
  写入  WRITE         🟡 Write / Edit / MultiEdit / NotebookEdit / TodoWrite
  编排  ORCHESTRATE   🟣 Agent / Task (subagent invocation)
  其他  OTHER         ⚪ anything else (LLM text, tool_result echoes, etc.)

Resolution order:
  1. Explicit ``isAgentInvocation`` / ``is_agent_invocation`` flag in detail  → ORCHESTRATE
  2. ``tool_name`` against per-category rule sets
  3. BarType-based fallback: PHASE/SESSION → ORCHESTRATE, others → OTHER

The categorizer is pure (no I/O), and is safe to invoke from any parser.
"""

from __future__ import annotations

from ..models.viz_models import BarType, OperationCategory, TimelineBar


class OperationCategorizer:
    """Rule-based mapper from TimelineBar to OperationCategory."""

    _TOOL_RULES: dict[OperationCategory, frozenset[str]] = {
        OperationCategory.READ: frozenset(
            {"Read", "Glob", "Grep", "WebFetch", "WebSearch", "LS"}
        ),
        OperationCategory.EXECUTE: frozenset(
            {"Bash", "Execute", "TaskKill", "BashOutput", "KillShell", "Shell"}
        ),
        OperationCategory.WRITE: frozenset(
            {"Write", "Edit", "MultiEdit", "NotebookEdit", "TodoWrite", "Patch"}
        ),
        OperationCategory.ORCHESTRATE: frozenset(
            {"Agent", "Task", "SendMessage", "TeamCreate"}
        ),
    }

    def categorize(self, bar: TimelineBar) -> OperationCategory:
        """Return the operation category for the given bar.

        Never returns ``None`` — falls back to ``OTHER`` for unclassifiable bars.
        """
        if bar.category is not None:
            return bar.category

        detail = bar.detail or {}
        # 1. Explicit orchestration flag wins.
        if detail.get("isAgentInvocation") or detail.get("is_agent_invocation"):
            return OperationCategory.ORCHESTRATE

        # 2. Tool name lookup.
        tool_name = (detail.get("tool_name") or detail.get("tool") or bar.label or "").strip()
        for cat, names in self._TOOL_RULES.items():
            if tool_name in names:
                return cat

        # 3. BarType fallback.
        if bar.type == BarType.PHASE:
            return OperationCategory.ORCHESTRATE
        if bar.type == BarType.SESSION:
            return OperationCategory.ORCHESTRATE
        return OperationCategory.OTHER


__all__ = ["OperationCategorizer"]

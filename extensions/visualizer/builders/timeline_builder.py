"""Timeline builder (F-91-C).

Aggregates TimelineBar objects from multiple parsers into a unified timeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import BarType, SessionVizData, TimelineBar
from ..parsers.session_parser import SessionMetadataParser
from ..parsers.transcript_parser import TranscriptParser
from ..parsers.tool_events_parser import ToolEventsParser
from ..parsers.multi_agent_parser import MultiAgentParser

logger = logging.getLogger(__name__)


class TimelineBuilder:
    """Build a unified timeline for a session by combining all data sources."""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        transcripts_dir: Path | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self.session_parser = SessionMetadataParser(
            sessions_dir=sessions_dir,
            transcripts_dir=transcripts_dir,
            reports_dir=reports_dir,
        )
        self.transcript_parser = TranscriptParser()
        self.tool_events_parser = ToolEventsParser()
        self.multi_agent_parser = MultiAgentParser()
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")
        self.transcripts_dir = transcripts_dir or (Path.home() / ".clawcodex" / "transcripts")

    def build(self, session_id: str) -> SessionVizData | None:
        """Build complete SessionVizData for a session."""
        # Parse base metadata
        viz = self.session_parser.parse(session_id)
        if viz is None:
            return None

        # Parse transcript bars
        if viz.transcript_path:
            transcript_bars = self.transcript_parser.parse_file(viz.transcript_path)
            viz.timeline.extend(transcript_bars)
            viz.parse_warnings.extend(self.transcript_parser.warnings)

        # Parse tool events bars
        if viz.tool_events_path:
            tool_bars = self.tool_events_parser.parse_file(viz.tool_events_path)
            viz.timeline.extend(tool_bars)

        # Parse agent tree — discover sub-agents from the new layout
        # (flat ``~/.clawcodex/transcripts/*.jsonl`` and nested
        # ``sessions/<sid>/subagents/agent-*.jsonl``). The legacy
        # ``.orchestrator_control/runs/<rid>/agent_meta.json`` tree has
        # been replaced.
        agent_tree = self.multi_agent_parser.parse_for_session(
            session_id,
            sessions_dir=self.sessions_dir,
            transcripts_dir=self.transcripts_dir,
        )
        viz.agent_tree = agent_tree

        # A discovered child is only useful when its real events are placed on
        # the shared timeline.  Parse every nested/flat transcript separately
        # and stamp the filename-derived agent id onto all emitted bars.
        for node in agent_tree:
            transcript_path = node.metadata.get("transcript_path")
            if not transcript_path:
                continue
            child_parser = TranscriptParser()
            child_bars = child_parser.parse_file(
                transcript_path,
                agent_id=node.agent_id,
                llm_duration_strategy="unrecorded",
            )
            viz.timeline.extend(child_bars)
            viz.parse_warnings.extend(child_parser.warnings)

        self._apply_spawn_metadata(viz)

        # Sort timeline by start time
        viz.timeline.sort(key=lambda b: b.start_time)
        viz.tool_count = sum(1 for bar in viz.timeline if bar.type == BarType.TOOL_CALL)
        viz.turn_count = sum(1 for bar in viz.timeline if bar.type == BarType.LLM_CALL)

        # Compute stats — pass the pre-enriched ``viz.stats`` as a base so
        # cost_usd / context_tokens populated by ``_enrich_from_transcript``
        # survive the recomputation. Without this, the enrichment is
        # silently wiped every time.
        from .stats_builder import StatsBuilder

        viz.stats = StatsBuilder().build(viz.timeline, base=viz.stats)

        # Detect anomalies
        from .anomaly_builder import AnomalyBuilder

        viz.anomalies = AnomalyBuilder().build(viz)

        # Compute multi-agent waterfall layout (spawn_x / join_x / depth_y).
        # Best-effort: never raises — if the timeline has no Agent calls,
        # the layout is a no-op and agent_layout_summary stays empty.
        from .agent_tree_layout import AgentTreeLayout

        try:
            AgentTreeLayout().layout(viz)
        except Exception as e:
            logger.debug("AgentTreeLayout failed for %s: %s", session_id, e)

        viz.parse_warnings = self._dedupe_warnings(viz.parse_warnings)
        return viz

    @staticmethod
    def _dedupe_warnings(warnings: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for warning in warnings:
            if warning in seen:
                continue
            seen.add(warning)
            deduped.append(warning)
        return deduped

    @staticmethod
    def _apply_spawn_metadata(viz: SessionVizData) -> None:
        """Match Agent/Task calls to transcript lanes and improve labels."""
        spawn_bars = [
            bar
            for bar in viz.timeline
            if bar.type == BarType.TOOL_CALL
            and (bar.detail or {}).get("is_agent_invocation")
            and not bar.agent_id
        ]
        unused = list(viz.agent_tree)
        for bar in spawn_bars:
            detail = bar.detail or {}
            explicit = next(
                (
                    detail.get(key)
                    for key in ("agent_id", "subagent_id", "agentId", "subagentId")
                    if detail.get(key)
                ),
                None,
            )
            node = next(
                (item for item in unused if explicit and item.agent_id == str(explicit)), None
            )
            if node is None and unused:
                node = unused[0]
            if node is None:
                continue
            unused.remove(node)
            subagent_type = detail.get("subagent_type") or detail.get("agent_type")
            description = detail.get("subagent_description") or detail.get("description")
            if isinstance(subagent_type, str) and subagent_type:
                node.name = subagent_type
                node.metadata["subagent_type"] = subagent_type
            elif isinstance(description, str) and description:
                node.name = description[:60]
            node.metadata["spawn_bar_id"] = bar.id

    def build_for_sessions(self, session_ids: list[str]) -> list[SessionVizData]:
        """Build viz data for multiple sessions."""
        results: list[SessionVizData] = []
        for sid in session_ids:
            viz = self.build(sid)
            if viz:
                results.append(viz)
        return results

"""Multi-agent tree parser for the new ClawCodeX session format.

Sub-agent transcripts in the new format live in two places:

- **Flat fallback**: ``~/.clawcodex/transcripts/<agent_id>.jsonl`` — the
  default when ``src.init.init()`` is bypassed. The TranscriptWriter
  emits a one-shot warning.
- **Nested**: ``~/.clawcodex/sessions/<parent_session_id>/subagents/
  agent-<agent_id>.jsonl`` — when the resolver in
  ``clawcodex_ext.agent.transcript.init()`` is called at startup
  (registers ``nested_session_path_resolver``).

Each sub-agent transcript entry carries a ``parent_session_id`` field
(``src.agent.transcript._serialize_message`` injects it for every entry
written by a sub-agent). The visualizer uses the *file* location to
discover sub-agents and the per-entry ``parent_session_id`` to confirm
parentage — both pieces of evidence must agree for a node to be emitted.

No ``.orchestrator_control/runs/<run_id>/agent_meta.json`` reading: the
old orchestrator control tree has been replaced by the sub-agent
transcript convention above.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.viz_models import AgentTreeNode, BarStatus

logger = logging.getLogger(__name__)

# ``agent-<id>.jsonl`` — the naming convention emitted by
# ``clawcodex_ext.transcript.nested_path``.
_SUBAGENT_RE = re.compile(r"^agent-(?P<agent_id>.+)\.jsonl$")


def _coerce_iso_ts(value: Any) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class MultiAgentParser:
    """Build an ``AgentTreeNode`` list for a session from the new sub-agent layout."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_for_session(
        self,
        session_id: str,
        *,
        sessions_dir: Path | str | None = None,
        transcripts_dir: Path | str | None = None,
    ) -> list[AgentTreeNode]:
        """Discover sub-agent nodes for the given session.

        Walks both:

        - ``<transcripts_dir>/*.jsonl`` (flat) — keeps only files whose
          first non-meta entry has ``parent_session_id == session_id``.
        - ``<sessions_dir>/<session_id>/subagents/agent-*.jsonl``
          (nested) — all files in the directory are sub-agents of this
          session.

        Returns a flat list. The root node is *not* included — the
        caller (MultiSessionViewBuilder) renders the root as a session
        row, not an agent row.
        """
        sessions_root = (
            Path(sessions_dir) if sessions_dir else (Path.home() / ".clawcodex" / "sessions")
        )
        transcripts_root = (
            Path(transcripts_dir)
            if transcripts_dir
            else (Path.home() / ".clawcodex" / "transcripts")
        )

        nodes: list[AgentTreeNode] = []

        # 1. Nested subagents — every file under
        #    sessions/<sid>/subagents/ is a child of this session.
        nested_dir = sessions_root / session_id / "subagents"
        if nested_dir.is_dir():
            for path in sorted(nested_dir.iterdir()):
                if not path.is_file() or path.suffix != ".jsonl":
                    continue
                m = _SUBAGENT_RE.match(path.name)
                if not m:
                    continue
                agent_id = m.group("agent_id")
                node = self._node_from_transcript(
                    path,
                    agent_id=agent_id,
                    parent_session_id=session_id,
                    source="nested",
                )
                if node is not None:
                    nodes.append(node)

        # 2. Flat subagents — filter the transcripts/ directory by
        #    parent_session_id on the first non-meta entry.
        if transcripts_root.is_dir():
            for path in sorted(transcripts_root.iterdir()):
                if not path.is_file() or path.suffix != ".jsonl":
                    continue
                # Skip the main session's own transcript (it would also
                # lack parent_session_id, but we don't want to include
                # it as a sub-agent).
                if path.stem == session_id:
                    continue
                parent_id = self._peek_parent_session_id(path)
                if parent_id != session_id:
                    continue
                node = self._node_from_transcript(
                    path,
                    agent_id=path.stem,
                    parent_session_id=session_id,
                    source="flat",
                )
                if node is not None:
                    # Don't double-count an agent that's already been
                    # discovered via the nested layout.
                    if not any(n.agent_id == node.agent_id for n in nodes):
                        nodes.append(node)

        return nodes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _peek_parent_session_id(path: Path) -> str:
        """Return the ``parent_session_id`` of the first parseable entry.

        Tolerant: a corrupt or empty file returns ``""`` (which never
        matches the queried session id). We do not need the full
        transcript content for the discovery step — just the parent
        marker — so a single-line read is enough.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                for _ in range(50):  # peek up to 50 lines
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("isMeta") or entry.get("isVirtual"):
                        continue
                    parent = entry.get("parent_session_id", "")
                    if isinstance(parent, str):
                        return parent
                    return ""
        except OSError:
            return ""
        return ""

    def _node_from_transcript(
        self,
        path: Path,
        *,
        agent_id: str,
        parent_session_id: str,
        source: str,
    ) -> AgentTreeNode | None:
        """Build an ``AgentTreeNode`` from a sub-agent transcript file.

        Pulls:

        - ``name`` — first non-empty assistant text block (truncated).
        - ``status`` — ``completed`` if the file is closed, ``running``
          if the most recent entry is within the recency window.
        - ``depth`` — always 1 (one level below the root in P0).
        - ``metadata`` — counts of tool_use / tool_result / text blocks
          and the parent_session_id for cross-reference.
        """
        tool_count = 0
        turn_count = 0
        first_text = ""
        last_ts: float = 0.0

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("isMeta") or entry.get("isVirtual"):
                        continue
                    if entry.get("isCompactSummary"):
                        continue
                    if entry.get("isApiErrorMessage"):
                        continue

                    ts = _coerce_iso_ts(entry.get("timestamp"))
                    if ts:
                        last_ts = ts

                    role = entry.get("role", "")
                    if role in ("user", "assistant"):
                        turn_count += 1

                    content = entry.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type", "")
                            if btype == "tool_use":
                                tool_count += 1
                            elif btype in ("text", "thinking") and not first_text:
                                text = block.get("text") or block.get("thinking") or ""
                                if text:
                                    first_text = text[:60]
        except OSError as e:
            logger.debug("Failed to read sub-agent transcript %s: %s", path, e)
            return None

        # Status inference: "running" if the file's mtime is within 5
        # minutes (same window the SessionMetadataParser uses).
        try:
            from time import time as _now

            mtime = path.stat().st_mtime
            status = BarStatus.RUNNING if (_now() - mtime < 300) else BarStatus.SUCCESS
        except OSError:
            status = BarStatus.SUCCESS

        return AgentTreeNode(
            agent_id=agent_id,
            name=first_text or f"agent-{agent_id[:8]}",
            parent_id=parent_session_id,
            children=[],
            session_ref=agent_id,
            status=status,
            depth=1,
            metadata={
                "source": source,
                "transcript_path": str(path),
                "tool_count": tool_count,
                "turn_count": turn_count,
                "last_ts": last_ts,
            },
        )

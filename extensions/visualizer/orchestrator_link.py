"""Orchestrator link generator (F-95-A).

Generates links to F-38 reports, F-45 tool events, and F-54 debug logs
from session data, using the new ClawCodeX on-disk layout:

- Tool events (F-45) live at ``~/.clawcodex/tool-events/<run_id>/events.ndjson``.
- Debug logs (F-54) live at ``~/.clawcodex/tool-events/<run_id>/debug.ndjson``.
- Reports (F-38) live alongside the session at ``<session_dir>/report.{md,json}``.

The old fallback path ``<session_dir>/.orchestrator_control/runs/<run_id>/``
is no longer consulted — that layout was retired when the orchestrator
moved to the F-45 canonical tool-events root.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Canonical tool-events root in the new format (F-45).
TOOL_EVENTS_ROOT = Path.home() / ".clawcodex" / "tool-events"


class OrchestratorLink:
    """Generate orchestrator-related links for a session."""

    def __init__(self, base_url: str = "http://localhost:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def generate_links(self, session_id: str, session_dir: Path | None = None) -> dict[str, Any]:
        """Generate all orchestrator links for a session."""
        links: dict[str, Any] = {
            "session_id": session_id,
            "api_base": f"{self.base_url}/api/viz",
            "frontend": f"{self.base_url}/session/{session_id}",
        }

        if session_dir is None:
            session_dir = Path.home() / ".clawcodex" / "sessions" / session_id

        if not session_dir.is_dir():
            links["available"] = False
            return links

        links["available"] = True

        # F-38: Verification report
        report_md = session_dir / "report.md"
        report_json = session_dir / "report.json"
        if report_md.exists() or report_json.exists():
            links["f38_report"] = {
                "type": "verification_report",
                "api_url": f"{self.base_url}/api/viz/sessions/{session_id}/report",
                "file_path": str(report_md if report_md.exists() else report_json),
                "available": True,
            }

        # F-45: Tool events audit log
        # Canonical path: ``~/.clawcodex/tool-events/<run_id>/events.ndjson``.
        # The session_id is the run_id (the new orchestrator key is the
        # session id from bootstrap, not a separate ``run_*``).
        events_file = TOOL_EVENTS_ROOT / session_id / "events.ndjson"
        if not events_file.exists():
            # Legacy fallback (transitional periods only) — same file
            # under the session directory. The old
            # ``.orchestrator_control/runs/<run_id>/`` layout is gone.
            fallback = session_dir / "events.ndjson"
            if fallback.exists():
                events_file = fallback

        if events_file.exists():
            links["f45_events"] = {
                "type": "tool_events",
                "api_url": f"{self.base_url}/api/viz/sessions/{session_id}/report",
                "file_path": str(events_file),
                "available": True,
                "event_count": self._count_ndjson_lines(events_file),
            }

        # F-54: Debug timeline log
        debug_file = TOOL_EVENTS_ROOT / session_id / "debug.ndjson"
        if not debug_file.exists():
            fallback = session_dir / "debug.ndjson"
            if fallback.exists():
                debug_file = fallback

        if debug_file.exists():
            links["f54_debug"] = {
                "type": "debug_timeline",
                "api_url": f"{self.base_url}/api/viz/sessions/{session_id}/report",
                "file_path": str(debug_file),
                "available": True,
                "entry_count": self._count_ndjson_lines(debug_file),
            }

        return links

    @staticmethod
    def _count_ndjson_lines(path: Path) -> int:
        """Count non-empty lines in an NDJSON file."""
        try:
            count = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        count += 1
            return count
        except Exception:
            return 0

    def generate_share_link(self, session_id: str, view_type: str = "session") -> dict[str, str]:
        """Generate a share link payload for the API."""
        return {
            "session_id": session_id,
            "view_type": view_type,
            "format": "json",
        }

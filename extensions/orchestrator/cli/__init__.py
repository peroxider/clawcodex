"""Orchestrator CLI subcommands — noun-verb structure.

Usage:
  clawcodex orchestrator server status|stop|start    # daemon-level ops
  clawcodex orchestrator issue list|show|tail|...    # issue-level ops
  clawcodex orchestrator workflow init|list-templates # scaffold workflow.md
  clawcodex orchestrator dashboard [--port PORT]     # standalone dashboard
"""

from __future__ import annotations

from .dashboard import run as run_dashboard
from .issue import run as run_issue
from .server import run as run_server
from .workflow import run as run_workflow

__all__ = [
    "run_server",
    "run_issue",
    "run_workflow",
    "run_dashboard",
]
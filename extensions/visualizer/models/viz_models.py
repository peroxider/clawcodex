"""Pydantic data models for the Multi-Session Visualizer (F-91-A).

Five core models that map 1:1 to frontend TypeScript types.
All datetime fields use Unix timestamps (float) for JSON compactness.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BarType(str, Enum):
    """Type of operation represented by a timeline bar."""

    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PHASE = "phase"
    TURN = "turn"
    SESSION = "session"
    WAIT = "wait"
    CUSTOM = "custom"


class BarStatus(str, Enum):
    """Execution status of a timeline bar."""

    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    RUNNING = "running"
    PENDING = "pending"
    SKIPPED = "skipped"


class AnomalyType(str, Enum):
    """Category of detected anomaly."""

    NO_OP = "no_op"
    STAGNATION = "stagnation"
    LOOP = "loop"
    READ_ONLY_SPIRAL = "read_only_spiral"
    RATE_LIMIT = "rate_limit"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_TURNS = "max_turns"
    LONG_TOOL = "long_tool"
    CUSTOM = "custom"


class AnomalySeverity(str, Enum):
    """Severity level of an anomaly."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TimeMode(str, Enum):
    """Time axis display mode for the gantt chart."""

    RELATIVE = "relative"  # start from 0
    ABSOLUTE = "absolute"  # wall-clock timestamps
    WINDOW = "window"  # configurable sliding window


class ExportFormat(str, Enum):
    """Supported export formats."""

    PNG = "png"
    SVG = "svg"
    JSON = "json"
    PDF = "pdf"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TimelineBar(BaseModel):
    """A single operation bar on the timeline.

    13 fields; rendered as one ECharts custom-series bar.
    """

    id: str = Field(description="Unique bar identifier")
    type: BarType = Field(description="Operation type")
    label: str = Field(description="Human-readable label")
    start_time: float = Field(description="Unix timestamp (seconds)")
    end_time: float = Field(description="Unix timestamp (seconds)")
    duration_ms: int = Field(description="Computed duration in milliseconds")
    agent_id: str | None = Field(default=None, description="Owning agent/runner")
    group_id: str | None = Field(default=None, description="Logical group (phase/turn)")
    parent_id: str | None = Field(default=None, description="Parent bar for nesting")
    status: BarStatus = Field(default=BarStatus.SUCCESS)
    depth: int = Field(default=0, description="Nesting depth for tree rendering")
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific payload (tool_name, params excerpt, etc.)",
    )
    color: str | None = Field(
        default=None,
        description="Optional override color (hex string)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "tc-001",
                "type": "tool_call",
                "label": "Read src/main.py",
                "start_time": 1717500000.0,
                "end_time": 1717500001.2,
                "duration_ms": 1200,
                "agent_id": "agent-1",
                "group_id": "turn-3",
                "parent_id": None,
                "status": "success",
                "depth": 0,
                "detail": {"tool_name": "Read", "path": "src/main.py"},
            }
        }
    }


class Anomaly(BaseModel):
    """Detected anomaly in a session.

    6 fields; surfaced in the anomaly panel.
    """

    type: AnomalyType
    severity: AnomalySeverity
    session_id: str
    description: str
    timestamp: float
    suggestion: str = ""
    bar_id: str | None = None  # link to triggering bar


class OperationStats(BaseModel):
    """Aggregated operation statistics for a session.

    7 fields; displayed in the stats bar.
    """

    total_ops: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    avg_duration_ms: float = 0.0
    max_concurrent: int = 0
    total_duration_ms: int = 0
    context_tokens: int = 0
    cost_usd: float = 0.0


class AgentTreeNode(BaseModel):
    """Node in the multi-agent tree.

    9 fields; P0 simplified version (flat list with parent refs).
    """

    agent_id: str
    name: str
    parent_id: str | None = None
    children: list[str] = Field(default_factory=list)
    session_ref: str  # session/run_id this node belongs to
    status: BarStatus = BarStatus.SUCCESS
    depth: int = 0
    stats: OperationStats = Field(default_factory=OperationStats)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionVizData(BaseModel):
    """Complete visualization data for one session.

    23 fields; the primary payload returned by /api/viz/sessions/{sid}.
    """

    session_id: str
    title: str = ""
    workspace: str = ""
    model: str = ""
    provider: str = ""
    start_time: float = 0.0
    end_time: float | None = None
    duration_ms: int = 0
    status: str = "unknown"  # running, completed, failed, etc.
    agent_name: str = ""
    tags: list[str] = Field(default_factory=list)

    # Aggregated stats
    stats: OperationStats = Field(default_factory=OperationStats)

    # Timeline bars (primary rendering data)
    timeline: list[TimelineBar] = Field(default_factory=list)

    # Anomalies
    anomalies: list[Anomaly] = Field(default_factory=list)

    # Multi-agent tree (P0: simplified flat list)
    agent_tree: list[AgentTreeNode] = Field(default_factory=list)

    # Linked reports (F-95)
    report_path: str | None = None  # F-38 markdown path
    tool_events_path: str | None = None  # F-45 events.ndjson path
    debug_log_path: str | None = None  # F-54 debug.ndjson path

    # Raw data pointers (not serialized in full; frontend fetches on demand)
    transcript_path: str | None = None
    snapshot_path: str | None = None

    # Computed fields
    turn_count: int = 0
    tool_count: int = 0
    phase_count: int = 0
    detected_mode: str = ""  # e.g. "headless", "interactive"
    config_summary: dict[str, Any] = Field(default_factory=dict)

    # Session end reason (F-09 / F-40)
    end_reason: str | None = None
    end_summary: str = ""

    model_config = {"populate_by_name": True}


class WorkspaceInfo(BaseModel):
    """Lightweight workspace descriptor for the workspace list endpoint."""

    id: str
    name: str
    path: str
    session_count: int = 0
    last_updated: float = 0.0


class ShareLink(BaseModel):
    """Share link record (F-92-D / F-95-B)."""

    id: str
    session_id: str
    created_at: float
    expires_at: float
    format: ExportFormat = ExportFormat.JSON
    view_type: str = "session"  # session | comparison
    payload: dict[str, Any] = Field(default_factory=dict)


class ComparisonResult(BaseModel):
    """Cross-session comparison payload."""

    sessions: list[str] = Field(default_factory=list)
    common_metrics: dict[str, Any] = Field(default_factory=dict)
    per_session: dict[str, OperationStats] = Field(default_factory=dict)
    delta: dict[str, Any] = Field(default_factory=dict)


class ImportStatus(BaseModel):
    """Async import job status."""

    task_id: str
    status: str  # pending, running, completed, failed
    progress: int = 0  # 0-100
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

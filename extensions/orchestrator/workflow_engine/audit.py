"""工作流审计事件写入 (F-116)。

将工作流级事件以 NDJSON 格式写入审计日志，
供 Visualizer 和审计系统消费。

与 tool_event_log.py 的 per-tool 审计互补：
- tool_event_log: 单次工具调用级审计
- audit: 工作流阶段级审计

输出路径: ~/.clawcodex/workflow-events/{workflow_name}/events.ndjson
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 审计事件 Schema ─────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkflowAuditEvent:
    """工作流级审计事件。

    Schema (固定顺序，保证 NDJSON 可 grep):
        ts:              float  — time.time()
        event_type:      str    — 事件类型
        workflow_name:   str    — 工作流名称
        stage_id:        int|None
        stage_name:      str|None
        outcome:         str|None
        cost_usd:        float
        duration_seconds: float
        error:           str|None
        metadata:        dict   — 扩展字段
    """

    event_type: str
    workflow_name: str
    ts: float = field(default_factory=time.time)
    stage_id: int | None = None
    stage_name: str | None = None
    phase: str | None = None
    outcome: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "event_type": self.event_type,
            "workflow_name": self.workflow_name,
            "stage_id": self.stage_id,
            "stage_name": self.stage_name,
            "phase": self.phase,
            "outcome": self.outcome,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ── 审计写入器 ──────────────────────────────────────────────────────


class WorkflowAuditWriter:
    """工作流审计事件写入器。

    以 NDJSON 格式追加写入审计事件。
    复用 ARC 原子写入模式（temp file + rename）仅在需要时使用；
    日常追加使用简单 append 模式（性能优先，审计日志允许最终一致性）。
    """

    def __init__(
        self,
        workflow_name: str,
        events_dir: str | Path | None = None,
    ) -> None:
        self._workflow_name = workflow_name

        if events_dir is None:
            events_dir = Path.home() / ".clawcodex" / "workflow-events" / workflow_name
        self._events_dir = Path(events_dir)
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._events_dir / "events.ndjson"

    def write_event(self, event: WorkflowAuditEvent) -> None:
        """追加一条审计事件（NDJSON 行）。"""
        line = event.to_json() + "\n"
        with open(self._events_path, "a", encoding="utf-8") as f:
            f.write(line)

    def write_stage_start(
        self,
        stage_id: int,
        stage_name: str,
        phase: str = "",
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="stage_start",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                stage_name=stage_name,
                phase=phase,
                metadata=kwargs,
            )
        )

    def write_stage_complete(
        self,
        stage_id: int,
        stage_name: str,
        cost: float = 0.0,
        duration: float = 0.0,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="stage_complete",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                stage_name=stage_name,
                outcome="success",
                cost_usd=cost,
                duration_seconds=duration,
                metadata=kwargs,
            )
        )

    def write_stage_failed(
        self,
        stage_id: int,
        stage_name: str,
        error: str = "",
        cost: float = 0.0,
        duration: float = 0.0,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="stage_failed",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                stage_name=stage_name,
                outcome="failed",
                error=error,
                cost_usd=cost,
                duration_seconds=duration,
                metadata=kwargs,
            )
        )

    def write_gate_result(
        self,
        stage_id: int,
        stage_name: str,
        approved: bool,
        reason: str = "",
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="gate_result",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                stage_name=stage_name,
                outcome="approved" if approved else "rejected",
                error=reason if not approved else None,
                metadata=kwargs,
            )
        )

    def write_decision(
        self,
        stage_id: int,
        outcome: str,
        next_stage: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="decision",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                outcome=outcome,
                metadata={"next_stage": next_stage, **kwargs},
            )
        )

    def write_rollback(
        self,
        stage_id: int,
        rollback_to: int,
        reason: str = "",
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="rollback",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                outcome="rollback",
                error=reason,
                metadata={"rollback_to": rollback_to, **kwargs},
            )
        )

    def write_workflow_complete(
        self,
        total_cost: float,
        total_duration: float,
        completed_stages: int,
        total_stages: int,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="workflow_complete",
                workflow_name=self._workflow_name,
                outcome="success",
                cost_usd=total_cost,
                duration_seconds=total_duration,
                metadata={
                    "completed_stages": completed_stages,
                    "total_stages": total_stages,
                    **kwargs,
                },
            )
        )

    def write_workflow_error(
        self,
        error: str,
        stage_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="workflow_error",
                workflow_name=self._workflow_name,
                stage_id=stage_id,
                outcome="error",
                error=error,
                metadata=kwargs,
            )
        )

    def write_cost_event(
        self,
        total_usd: float,
        stage_usd: float,
        budget_max: float,
        **kwargs: Any,
    ) -> None:
        self.write_event(
            WorkflowAuditEvent(
                event_type="cost_update",
                workflow_name=self._workflow_name,
                cost_usd=total_usd,
                metadata={
                    "stage_usd": stage_usd,
                    "budget_max": budget_max,
                    "usage_pct": round(total_usd / budget_max * 100, 1) if budget_max > 0 else 0,
                    **kwargs,
                },
            )
        )

    @property
    def events_path(self) -> Path:
        return self._events_path

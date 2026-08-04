"""Execution engine: orchestrates task execution via the configured agent."""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Any, Dict, Optional

from src.models import (
    ExecutionTrace,
    ExecutionMetrics,
    Task,
    TraceStep,
    StepType,
    ToolCall,
)
from src.utils import read_text, setup_logger

logger = setup_logger("execution_engine")


class ExecutionEngine:
    """Wraps execution of a task by the coding agent.

    In production, this would call the real agent system (e.g., Codex CLI).
    In the current implementation, it provides the framework for capturing
    traces, and supports a 'mock' mode for testing the self-evolution loop.
    """

    def __init__(self, config: Dict[str, Any], agent_callback=None) -> None:
        self.config = config
        self.agent_callback = agent_callback
        self.version_config: Optional[Dict[str, Any]] = None

    def set_version_config(self, config: Dict[str, Any]) -> None:
        """Use a specific version's config (prompts, skills) for execution."""
        self.version_config = config

    def _resolve_config(self) -> Dict[str, Any]:
        return self.version_config if self.version_config is not None else self.config

    def execute(self, task: Task) -> ExecutionTrace:
        """Execute a task and return the full trace.

        If an agent_callback is set, delegates to it.
        Otherwise, the caller should handle trace collection externally.
        """
        cfg = self._resolve_config()
        trace = ExecutionTrace(
            task_id=task.task_id,
            task_description=task.description,
            agent_version=cfg.get("_version", "unknown"),
            config_snapshot=cfg,
        )

        if self.agent_callback:
            trace = self.agent_callback(task, cfg)
        else:
            logger.info(
                "No agent_callback set; recording a minimal trace "
                "for task %s", task.task_id
            )
            trace.steps.append(
                TraceStep(
                    step_index=0,
                    step_type=StepType.TASK_UNDERSTANDING,
                    action=f"Received task: {task.description}",
                )
            )
            trace.execution_metrics = ExecutionMetrics(total_steps=1)

        return trace

"""F-118 dynamic decomposition backed by the existing coordinator runtime."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..git_sync import VerificationFailed
from ..task_decomposition import (
    TaskDecomposer,
    build_swarm_prompt,
    validate_task_execution,
    write_task_plan,
)
from .coordinator import CoordinatorModeRunner

if TYPE_CHECKING:
    from ..agent_runner import AgentRunner, AgentSession
    from ..config.schema import WorkflowConfig

logger = logging.getLogger(__name__)


class SwarmModeRunner:
    def __init__(
        self,
        agent_runner: "AgentRunner",
        *,
        max_subtasks: int = 8,
        max_parallel: int = 3,
        max_waves: int = 6,
    ) -> None:
        self._agent_runner = agent_runner
        self._coordinator = CoordinatorModeRunner(agent_runner)
        self._decomposer = TaskDecomposer(
            max_subtasks=max_subtasks,
            max_parallel=max_parallel,
            max_waves=max_waves,
        )

    async def run(
        self,
        session: "AgentSession",
        workflow: "WorkflowConfig",
        **hooks: Any,
    ) -> Any:
        plan = self._decomposer.decompose_issue(session.issue)
        plan_path = write_task_plan(plan, session.workspace.path)
        original_prompt = session.prompt_override
        original_kind = session.run_kind
        session.task_decomposition_path = str(plan_path)
        session.task_decomposition = plan.to_dict()
        session.prompt_override = build_swarm_prompt(session.issue, plan, plan_path)
        session.run_kind = "swarm"
        logger.info(
            "F-118 swarm plan issue=%s tasks=%d waves=%d max_parallel=%d path=%s",
            session.issue.id,
            len(plan.subtasks),
            len(plan.waves),
            plan.max_parallel,
            plan_path,
        )
        try:
            result = await self._coordinator.run(session, workflow, **hooks)
            if getattr(session, "status", None) == "completed":
                try:
                    validate_task_execution(plan_path, plan)
                except ValueError as exc:
                    raise VerificationFailed(
                        "Swarm execution evidence validation failed",
                        output=str(exc),
                    ) from exc
            return result
        finally:
            session.prompt_override = original_prompt
            session.run_kind = original_kind


__all__ = ["SwarmModeRunner"]

"""工作流编排器 (F-110 集成)。

将 DeclarativeWorkflowEngine 接入 Orchestrator 体系，
提供 workflow.yaml 加载、执行、可观测性集成。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .config.schema import WorkflowConfig
from .workflow_engine.engine import (
    DeclarativeWorkflowEngine,
    EngineConfig,
    WorkflowResult,
    WorkflowSchema,
)
from .workflow_engine.stage_runner import StageRunner
from .workflow_engine.cost import CostBudget
from .workflow_engine.checkpoint import CheckpointManager
from .workflow_engine.observability import WorkflowProgressSink
from .workflow_engine.audit import WorkflowAuditWriter

if TYPE_CHECKING:
    from .agent_runner import AgentRunner
    from .issue import Issue

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """声明式工作流编排器。

    读取 workflow.yaml，注入 AgentRunner，执行 DAG 工作流，
    并通过 WorkflowProgressSink 上报进度。

    与 Orchestrator 集成：当 Orchestrator 收到 issue 时，
    通过 WorkflowOrchestrator 按 workflow.yaml 定义的阶段执行。
    """

    def __init__(
        self,
        workflow_config: WorkflowConfig,
        workflow_yaml_path: str,
        agent_runner: "AgentRunner | None" = None,
        checkpoint_dir: str | None = None,
        tracker: Any = None,
        status_dashboard: Any = None,
        clarification_resolver: Any = None,
        llm_client: Any = None,
    ) -> None:
        self._workflow_config = workflow_config
        self._yaml_path = Path(workflow_yaml_path)
        self._checkpoint_dir = checkpoint_dir

        # 加载 workflow.yaml
        self._schema = WorkflowSchema.from_yaml(self._yaml_path)

        # 构建引擎配置
        workspace_root = workflow_config.workspace.root
        agent_timeout_s = int(getattr(workflow_config.agent, "run_timeout_ms", 1_800_000) / 1000)
        engine_config = EngineConfig(
            cost_budget=CostBudget(
                max_total_usd=getattr(workflow_config.agent, "cost_budget_usd", 50.0) or 50.0,
            ),
            default_timeout_seconds=agent_timeout_s,
            workspace_dir=str(workspace_root),
            enable_snapshots=True,
            llm_client=llm_client,
        )
        self._engine = DeclarativeWorkflowEngine(
            workflow=self._schema,
            config=engine_config,
        )

        bundle_dir = self._yaml_path.parent.resolve()
        self._stage_runner = StageRunner(
            agent_runner=agent_runner,
            workflow_config=workflow_config,
            agent_config=workflow_config.agent,
            sandbox_config=workflow_config.sandbox,
            workspace_dir=str(workspace_root),
            tracker=tracker,
            status_dashboard=status_dashboard,
            clarification_resolver=clarification_resolver,
            llm_client=llm_client,
        )
        self._stage_runner.set_bundle_path(bundle_dir)
        self._engine.set_stage_runner(self._stage_runner)

        # 进度上报
        self._progress_sink = WorkflowProgressSink(
            workflow_name=self._schema.name,
            total_stages=len(self._schema.stages),
        )

        # 审计日志
        self._audit = WorkflowAuditWriter(
            workflow_name=self._schema.name,
        )

        # 检查点
        if self._checkpoint_dir:
            self._checkpoint_mgr = CheckpointManager(
                run_dir=self._checkpoint_dir,
            )
        else:
            self._checkpoint_mgr = None

        # 事件订阅
        self._setup_event_subscriptions()

    def _setup_event_subscriptions(self) -> None:
        """订阅引擎事件，转发到进度上报。"""
        self._engine.event_bus.on("workflow_start", self._on_workflow_start)
        self._engine.event_bus.on("stage_start", self._on_stage_start)
        self._engine.event_bus.on("stage_complete", self._on_stage_complete)
        self._engine.event_bus.on("stage_failed", self._on_stage_failed)
        self._engine.event_bus.on("workflow_complete", self._on_workflow_complete)
        self._engine.event_bus.on("workflow_error", self._on_workflow_error)
        self._engine.event_bus.on("gate_request", self._on_gate_request)
        self._engine.event_bus.on("gate_approved", self._on_gate_approved)
        self._engine.event_bus.on("gate_rejected", self._on_gate_rejected)
        self._engine.event_bus.on("cost_warning", self._on_cost_warning)

    # ── 公开接口 ──────────────────────────────────────────────────

    async def run(self, from_stage: int | None = None) -> WorkflowResult:
        """执行工作流。

        Args:
            from_stage: 从指定阶段恢复执行（检查点恢复）。

        Returns:
            WorkflowResult
        """
        start_time = time.time()

        # 尝试从检查点恢复
        if (
            from_stage is None
            and self._checkpoint_mgr is not None
            and self._checkpoint_mgr.exists()
        ):
            checkpoint = self._checkpoint_mgr.load()
            if checkpoint and checkpoint.completed_stages:
                last_completed = max(checkpoint.completed_stages)
                logger.info(
                    "Resuming from checkpoint: stage %s",
                    last_completed,
                )
                from_stage = last_completed + 1

                # 使用 CheckpointManager.restore_state 完整恢复 WorkflowState
                restored_state = self._checkpoint_mgr.restore_state(checkpoint)
                self._engine.state = restored_state
                self._engine.cost_tracker.load_state(
                    total_usd=checkpoint.cost_accumulated_usd,
                    stage_usd=0.0,
                )
                # 回填决策历史
                if restored_state.decision_history is not None:
                    self._engine._decision_handler._history = restored_state.decision_history

        result = await self._engine.execute(from_stage=from_stage)

        # 检查点管理：成功则清理，失败则保存
        if self._checkpoint_mgr is not None:
            if result.success:
                self._checkpoint_mgr.delete()
            else:
                self._checkpoint_mgr.save(self._engine.state)

        elapsed = time.time() - start_time
        logger.info(
            "Workflow %s: %s, %d/%d stages, %.1fs",
            self._schema.name,
            "SUCCESS" if result.success else "FAILED",
            result.completed_stages,
            result.total_stages,
            elapsed,
        )

        return result

    async def run_for_issue(
        self,
        issue: "Issue",
        workspace_path: str = "",
        from_stage: int | None = None,
    ) -> WorkflowResult:
        """为指定 Issue 执行工作流 (Orchestrator 集成入口)。

        将 issue 的标题和描述注入为首阶段上下文，
        然后按 workflow.yaml 定义的 DAG 阶段顺序执行。

        Args:
            issue: 来自 tracker 的 Issue 对象。
            workspace_path: 工作区路径（用于 StageRunner 的共享目录）。
            from_stage: 从指定阶段恢复执行。

        Returns:
            WorkflowResult
        """
        # 更新 StageRunner 的工作区目录
        if workspace_path:
            self._stage_runner._workspace_dir = workspace_path

        # 设置 per-issue 检查点目录（F-115: 重试时从检查点恢复）
        issue_checkpoint_dir = None
        if workspace_path:
            issue_checkpoint_dir = str(
                Path(workspace_path) / ".orchestrator_workspace" / "checkpoints"
            )
        self._checkpoint_dir = issue_checkpoint_dir
        if issue_checkpoint_dir:
            self._checkpoint_mgr = CheckpointManager(run_dir=issue_checkpoint_dir)
            self._engine.set_checkpoint_manager(self._checkpoint_mgr)
        else:
            self._checkpoint_mgr = None

        # 重置引擎状态（防止单例跨 issue 状态污染）
        # 如果存在检查点，run() 会自动从检查点恢复
        self._reset_engine_state()

        # 将 issue 上下文注入到工作流状态中
        # _issue 保留原始对象引用，供 StageRunner 调用 PromptBuilder.render()
        self._engine.state.issue_context = {
            "id": issue.id,
            "identifier": issue.identifier,
            "title": issue.title,
            "description": issue.description,
            "labels": issue.labels,
            "_issue": issue,
        }

        logger.info(
            "WorkflowOrchestrator: running for issue %s (%s)",
            issue.identifier,
            issue.title,
        )

        return await self.run(from_stage=from_stage)

    def _reset_engine_state(self) -> None:
        """重置引擎运行时状态，防止单例跨 issue 状态污染。"""
        from .workflow_engine.workflow_state import WorkflowState

        self._engine.state = WorkflowState(
            workflow_name=self._schema.name,
            workflow_version=self._schema.version,
        )
        self._engine._dag_order = []
        self._engine._decision_handler.reset()
        self._engine.cost_tracker.load_state(total_usd=0.0, stage_usd=0.0)

    async def shutdown(self) -> None:
        """优雅关闭。"""
        if self._checkpoint_mgr is not None:
            self._checkpoint_mgr.save(self._engine.state)
        logger.info("WorkflowOrchestrator shutdown complete")

    # ── 事件处理 ──────────────────────────────────────────────────

    def _on_workflow_start(self, event_type: str, event: dict[str, Any]) -> None:
        logger.info(
            "Workflow started: %s (%d stages)",
            event.get("workflow_name"),
            event.get("total_stages"),
        )

    def _on_stage_start(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        phase = event.get("phase", "")
        logger.info("Stage %s [%s/%s] started", stage_id, stage_name, phase)
        self._progress_sink.on_stage_start(stage_id, stage_name, phase)
        self._audit.write_stage_start(stage_id, stage_name, phase)

    def _on_stage_complete(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        cost = event.get("cost", 0.0)
        duration = event.get("duration", 0.0)
        logger.info("Stage %s completed (cost=%.4f, duration=%.1fs)", stage_id, cost, duration)
        self._progress_sink.on_stage_complete(stage_id, stage_name, cost, duration)
        self._audit.write_stage_complete(stage_id, stage_name, cost, duration)

    def _on_stage_failed(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        error = event.get("error", "")
        logger.error("Stage %s failed: %s", stage_id, error)
        self._progress_sink.on_stage_failed(stage_id, error)
        self._audit.write_stage_failed(stage_id, stage_name, error)

    def _on_workflow_complete(self, event_type: str, event: dict[str, Any]) -> None:
        total_cost = event.get("total_cost", 0.0)
        total_duration = event.get("total_duration", 0.0)
        completed = self._engine.state.completed_count
        total = self._engine.state.total_stages
        logger.info(
            "Workflow completed: cost=%.4f, duration=%.1fs",
            total_cost,
            total_duration,
        )
        self._progress_sink.on_workflow_complete(total_cost, total_duration)
        self._audit.write_workflow_complete(total_cost, total_duration, completed, total)

    def _on_workflow_error(self, event_type: str, event: dict[str, Any]) -> None:
        error = event.get("error", "")
        stage_id = event.get("stage_id")
        logger.error("Workflow error: %s", error)
        self._audit.write_workflow_error(error, stage_id)

    def _on_gate_request(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        mode = event.get("mode", "")
        logger.info("GATE request: stage=%s mode=%s", stage_id, mode)

    def _on_gate_approved(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        reason = event.get("reason", "")
        logger.info("GATE approved: stage=%s reason=%s", stage_id, reason)
        self._audit.write_gate_result(stage_id, stage_name, approved=True, reason=reason)

    def _on_gate_rejected(self, event_type: str, event: dict[str, Any]) -> None:
        stage_id = event.get("stage_id")
        stage_name = event.get("stage_name", "")
        reason = event.get("reason", "")
        logger.info("GATE rejected: stage=%s reason=%s", stage_id, reason)
        self._audit.write_gate_result(stage_id, stage_name, approved=False, reason=reason)

    def _on_cost_warning(self, event_type: str, event: dict[str, Any]) -> None:
        message = event.get("message", "")
        total_usd = self._engine.cost_tracker.total_usd
        stage_usd = self._engine.cost_tracker.stage_usd
        budget_max = self._engine.cost_tracker.budget.max_total_usd
        logger.warning("Cost warning: %s", message)
        self._audit.write_cost_event(total_usd, stage_usd, budget_max, message=message)

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def engine(self) -> DeclarativeWorkflowEngine:
        return self._engine

    @property
    def schema(self) -> WorkflowSchema:
        return self._schema

    def set_progress_sink(self, sink: Any) -> None:
        """注入外部进度接收器 (F-116: 编排器 Dashboard 集成)。

        WorkflowProgressSink 会将阶段进度事件转发给此 sink，
        使编排器的 StatusDashboard 能实时展示工作流阶段进度。
        """
        self._progress_sink.add_sink(sink)

    @property
    def progress(self) -> dict[str, Any]:
        """获取当前进度快照。"""
        return self._progress_sink.snapshot()

    @property
    def state(self):
        return self._engine.state

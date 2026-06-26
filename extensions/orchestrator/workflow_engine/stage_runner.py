"""StageRunner 适配器 (F-111)。

桥接 DeclarativeWorkflowEngine 与 AgentRunner，
将阶段执行适配为 AgentRunner 可消费的合成 Issue 工作单元。

设计决策 DD-5: 方案 A（合成 Issue 适配器）优先，
保留 AgentRunner 的全部稳健机制（停滞检测、进度上报、验证管线等）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .workflow_state import StageNode, WorkflowState

if TYPE_CHECKING:
    from ..agent_runner import AgentRunner, AgentSession
    from ..config.schema import AgentConfig, SandboxConfig, WorkflowConfig
    from ..issue import Issue
    from ..workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class StageRunResult:
    """StageRunner 执行结果。"""

    stage_id: int
    success: bool
    outputs: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    cost_usd: float = 0.0
    error: str | None = None
    message: str = ""


@dataclass
class GateRunResult:
    """GATE 阶段执行结果。"""

    stage_id: int
    approved: bool
    reason: str = ""
    cost_usd: float = 0.0


@dataclass
class DecisionRunResult:
    """DECISION 阶段执行结果。"""

    stage_id: int
    outcome: str  # proceed | pivot | refine | rollback
    next_stage: int | None = None
    cost_usd: float = 0.0


class StageRunner:
    """阶段执行适配器 (F-111 DD-5)。

    通过合成 Issue 调用 AgentRunner，复用其全部生命周期管理能力：
    - 停滞检测 (stagnation detection)
    - 进度上报 (ProgressSink)
    - 验证管线 (Verification Pipeline)
    - 澄清队列 (ClarificationQueue)
    - 成本追踪
    """

    MAX_RETRIES = 2

    def __init__(
        self,
        agent_runner: "AgentRunner",
        workflow_config: "WorkflowConfig",
        agent_config: "AgentConfig | None" = None,
        sandbox_config: "SandboxConfig | None" = None,
        workspace_dir: str = "",
        run_dir: str = "",
    ) -> None:
        self._agent_runner = agent_runner
        self._workflow_config = workflow_config
        self._agent_config = agent_config
        self._sandbox_config = sandbox_config
        self._workspace_dir = workspace_dir
        self._run_dir = run_dir

    # ── 公开接口 ──────────────────────────────────────────────────

    async def run(self, stage_node: StageNode, state: WorkflowState) -> StageRunResult:
        """执行 Agent 阶段。

        构建合成 Issue，通过 AgentRunner 执行，支持自动重试。
        """
        last_error: str | None = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return await self._execute_agent_stage(stage_node, state)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Stage %s attempt %d/%d failed: %s",
                    stage_node.id, attempt + 1, self.MAX_RETRIES + 1, exc,
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)

        return StageRunResult(
            stage_id=stage_node.id,
            success=False,
            error=last_error,
        )

    async def run_gate(self, stage_node: StageNode, state: WorkflowState) -> GateRunResult:
        """执行 GATE 阶段 (F-112)。"""
        mode = stage_node.gate_mode

        if mode == "auto":
            return await self._run_auto_gate(stage_node, state)
        elif mode == "threshold":
            return await self._run_threshold_gate(stage_node, state)
        else:
            return GateRunResult(
                stage_id=stage_node.id,
                approved=False,
                reason=f"GATE stage {stage_node.id} requires manual approval",
            )

    async def run_decision(self, stage_node: StageNode, state: WorkflowState) -> DecisionRunResult:
        """执行 DECISION 阶段 (F-113)。"""
        try:
            session = await self._run_synthetic_issue(
                prompt=self._build_decision_prompt(stage_node, state),
                stage_node=stage_node,
            )
            output_text = session.output_text if session else ""
            outcome = self._parse_decision_outcome(output_text, stage_node)
            next_stage = self._resolve_next_stage(outcome, stage_node)

            return DecisionRunResult(
                stage_id=stage_node.id,
                outcome=outcome,
                next_stage=next_stage,
            )
        except Exception as exc:
            logger.exception("Decision stage failed for stage %s", stage_node.id)
            return DecisionRunResult(stage_id=stage_node.id, outcome="proceed")

    # ── Agent 阶段执行 (DD-5: 合成 Issue 适配器) ─────────────────

    async def _execute_agent_stage(
        self, stage_node: StageNode, state: WorkflowState,
    ) -> StageRunResult:
        """通过合成 Issue + AgentRunner 执行 Agent 阶段。"""
        prompt = self._build_stage_prompt(stage_node, state)
        session = await self._run_synthetic_issue(prompt=prompt, stage_node=stage_node)

        if session is None:
            return StageRunResult(
                stage_id=stage_node.id,
                success=False,
                error="AgentRunner returned no session",
            )

        output_text = session.output_text if hasattr(session, "output_text") else ""
        status = session.status if hasattr(session, "status") else "unknown"

        return StageRunResult(
            stage_id=stage_node.id,
            success=status == "completed",
            outputs=[output_text] if output_text else [],
            message=output_text,
            error=None if status == "completed" else f"Session status: {status}",
        )

    async def _run_synthetic_issue(
        self, prompt: str, stage_node: StageNode,
    ) -> "AgentSession | None":
        """构建合成 Issue 并调用 AgentRunner (DD-5)。"""
        from ..issue import Issue
        from ..workspace import Workspace
        from ..agent_runner import AgentSession

        # 构建合成 Issue
        synthetic_issue = Issue(
            id=f"stage-{stage_node.id:02d}",
            identifier=f"stage-{stage_node.id:02d}",
            title=f"[{stage_node.phase}] {stage_node.name}",
            description=prompt,
            labels=[f"workflow-stage", f"workflow-{stage_node.phase}"],
        )

        # 构建 Workspace（共享目录，DD-6）
        workspace_path = Path(self._workspace_dir) if self._workspace_dir else Path(".")
        workspace = Workspace(
            path=workspace_path,
            issue_identifier=f"stage-{stage_node.id:02d}",
            issue_id=f"stage-{stage_node.id:02d}",
        )

        # 构建 AgentSession
        session = AgentSession(
            issue=synthetic_issue,
            workspace=workspace,
            run_kind=f"workflow-stage-{stage_node.phase}",
            run_id=f"stage-{stage_node.id:02d}",
        )

        # 调用 AgentRunner
        try:
            await self._agent_runner.run(
                session=session,
                workflow=self._workflow_config,
            )
        except Exception as exc:
            logger.exception("AgentRunner.run failed for stage %s", stage_node.id)
            session.status = "failed"
            session.output_text = str(exc)

        return session

    # ── GATE 处理 ─────────────────────────────────────────────────

    async def _run_auto_gate(self, stage_node: StageNode, state: WorkflowState) -> GateRunResult:
        """自动 GATE：基于 validator 结果判定。"""
        if not stage_node.validators:
            return GateRunResult(stage_id=stage_node.id, approved=True, reason="no validators, auto-approved")

        from .validators import ContractValidator

        validator = ContractValidator()
        results = validator.validate_all(stage_node.validators)
        all_passed = all(r.passed for r in results)

        return GateRunResult(
            stage_id=stage_node.id,
            approved=all_passed,
            reason="All validators passed" if all_passed
            else f"Validators failed: {[r.message for r in results if not r.passed]}",
        )

    async def _run_threshold_gate(self, stage_node: StageNode, state: WorkflowState) -> GateRunResult:
        """阈值 GATE：通过合成 Issue + LLM 评分判定。"""
        try:
            prompt = (
                f"Evaluate the following work output and assign a score from 0.0 to 1.0.\n"
                f"Respond with ONLY: score: <number>\n\n"
                f"Stage: {stage_node.name}\n"
                f"Prompt: {stage_node.prompt}\n"
            )
            session = await self._run_synthetic_issue(prompt=prompt, stage_node=stage_node)
            output_text = session.output_text if session else ""
            score = self._extract_score(output_text)
            approved = score >= stage_node.gate_threshold

            return GateRunResult(
                stage_id=stage_node.id,
                approved=approved,
                reason=f"Score {score:.2f} >= threshold {stage_node.gate_threshold}" if approved
                else f"Score {score:.2f} < threshold {stage_node.gate_threshold}",
            )
        except Exception as exc:
            return GateRunResult(stage_id=stage_node.id, approved=False, reason=f"Threshold gate error: {exc}")

    # ── DECISION 处理 ─────────────────────────────────────────────

    def _build_decision_prompt(self, stage_node: StageNode, state: WorkflowState) -> str:
        """构建决策阶段提示词。"""
        outcomes = list(stage_node.decision_outcomes.keys())
        return (
            f"Based on the completed stages, decide the next action.\n"
            f"Available outcomes: {', '.join(outcomes)}\n"
            f"Respond with ONE word: the chosen outcome.\n\n"
            f"Stage: {stage_node.name}\n"
            f"Context: {stage_node.prompt}\n"
        )

    def _parse_decision_outcome(self, output_text: str, stage_node: StageNode) -> str:
        """从 LLM 输出中解析决策结果。"""
        text_lower = output_text.strip().lower()
        outcomes = list(stage_node.decision_outcomes.keys())
        for outcome in outcomes:
            if outcome.lower() in text_lower:
                return outcome
        return "proceed"

    def _resolve_next_stage(self, outcome: str, stage_node: StageNode) -> int | None:
        """根据决策结果解析下一个阶段。"""
        decision_spec = stage_node.decision_outcomes.get(outcome, {})
        return decision_spec.get("next")

    # ── 提示词构建 ────────────────────────────────────────────────

    def _build_stage_prompt(self, stage_node: StageNode, state: WorkflowState) -> str:
        """构建阶段提示词（含 issue 上下文和前序阶段输出）。"""
        parts = []

        # 注入 issue 上下文（来自 Orchestrator 集成）
        if state.issue_context:
            parts.append("## Issue Context")
            parts.append(f"Title: {state.issue_context.get('title', 'N/A')}")
            desc = state.issue_context.get('description', '')
            if desc:
                parts.append(f"Description: {desc}")
            labels = state.issue_context.get('labels', [])
            if labels:
                parts.append(f"Labels: {', '.join(labels)}")
            parts.append("")

        parts.append(stage_node.prompt or f"Execute stage: {stage_node.name}")

        if state.completed_stages:
            parts.append("\n## Completed Stages")
            for sid in state.completed_stages:
                sresult = state.get_stage_result(sid)
                if sresult:
                    parts.append(f"- Stage {sid}: {sresult.status.value}")
                    if sresult.outputs:
                        parts.append(f"  Output: {sresult.outputs[0][:500]}")

        if stage_node.validators:
            parts.append("\n## Output Requirements")
            for v in stage_node.validators:
                parts.append(f"- {v.get('type', 'unknown')}: {v}")

        return "\n".join(parts)

    # ── 工具方法 ──────────────────────────────────────────────────

    @staticmethod
    def _extract_score(text: str) -> float:
        """从 LLM 输出中提取评分 (0.0-1.0)。"""
        import re
        match = re.search(r"(?:score|评分)[:\s]*([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.0
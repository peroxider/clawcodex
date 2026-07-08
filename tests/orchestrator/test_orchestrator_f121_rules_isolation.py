"""F-121 问题 1 验收：apply() 异常隔离。

验证 _apply_review_rules 在 RuleEngine.apply 抛错（OSError / YAMLError /
ValueError 等）时仅 log warning，不冒泡阻塞 session 流程。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from extensions.orchestrator.agent_runner import AgentSession
from extensions.orchestrator.config.schema import RulesConfig, WorkflowConfig
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.orchestrator import Orchestrator


def _make_orchestrator(workflow: WorkflowConfig, workflow_path: str) -> Orchestrator:
    """绕过 __init__ 构造轻量 orchestrator，仅 wire F-121 所需字段。"""
    orch = Orchestrator.__new__(Orchestrator)
    orch.workflow = workflow
    orch._workflow_path = workflow_path
    return orch


def _make_session() -> AgentSession:
    issue = Issue(id="42", identifier="ISSUE-42", title="t", branch_name="b")
    session = AgentSession.__new__(AgentSession)
    session.issue = issue
    session.output_text = "## Extracted Rules\n- [naming] Use snake_case for functions\n"
    return session


class TestApplyReviewRulesIsolation(unittest.IsolatedAsyncioTestCase):
    """F-121 问题 1：规则提取失败不阻塞 session。"""

    async def test_apply_failure_does_not_block_session(self) -> None:
        """RuleEngine.apply 抛 OSError 时，_apply_review_rules 不重抛。"""
        with tempfile.TemporaryDirectory() as tmp:
            workflow = WorkflowConfig(
                rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
            )
            orch = _make_orchestrator(workflow, str(Path(tmp) / "WORKFLOW.md"))
            session = _make_session()

            with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
                MockEngine.get_rules_path.return_value = str(Path(tmp) / "workflow.rules.yaml")
                MockEngine.return_value.apply = AsyncMock(side_effect=OSError("disk full"))
                # 不应抛出异常
                await orch._apply_review_rules(session)
                MockEngine.return_value.apply.assert_awaited_once()

    async def test_apply_failure_logs_warning(self) -> None:
        """apply 抛错时记录 warning 日志，含 issue id。"""
        with tempfile.TemporaryDirectory() as tmp:
            workflow = WorkflowConfig(
                rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
            )
            orch = _make_orchestrator(workflow, str(Path(tmp) / "WORKFLOW.md"))
            session = _make_session()

            with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
                MockEngine.get_rules_path.return_value = str(Path(tmp) / "workflow.rules.yaml")
                MockEngine.return_value.apply = AsyncMock(side_effect=ValueError("bad yaml"))
                with self.assertLogs("extensions.orchestrator.orchestrator", level="WARNING") as cm:
                    await orch._apply_review_rules(session)
                self.assertTrue(
                    any("F-121" in msg and "42" in msg for msg in cm.output),
                    f"warning log should mention F-121 and issue id, got: {cm.output}",
                )

    async def test_disabled_rules_skips_apply(self) -> None:
        """rules.enabled=False 时不调用 apply。"""
        with tempfile.TemporaryDirectory() as tmp:
            workflow = WorkflowConfig(rules=RulesConfig(enabled=False))
            orch = _make_orchestrator(workflow, str(Path(tmp) / "WORKFLOW.md"))
            session = _make_session()

            with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
                await orch._apply_review_rules(session)
                MockEngine.get_rules_path.assert_not_called()
                MockEngine.return_value.apply.assert_not_called()

    async def test_no_rules_path_skips_apply(self) -> None:
        """get_rules_path 返回 None（如无 _workflow_path）时不调用 apply。"""
        workflow = WorkflowConfig(
            rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
        )
        orch = _make_orchestrator(workflow, "/tmp/WORKFLOW.md")
        orch._workflow_path = None  # 触发 get_rules_path 返回 None
        session = _make_session()

        with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
            MockEngine.get_rules_path.return_value = None
            await orch._apply_review_rules(session)
            MockEngine.return_value.apply.assert_not_called()

    async def test_yaml_error_is_isolated(self) -> None:
        """yaml.YAMLError 同样被隔离（设计 §2.10 边界）。"""
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            workflow = WorkflowConfig(
                rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
            )
            orch = _make_orchestrator(workflow, str(Path(tmp) / "WORKFLOW.md"))
            session = _make_session()

            with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
                MockEngine.get_rules_path.return_value = str(Path(tmp) / "workflow.rules.yaml")
                MockEngine.return_value.apply = AsyncMock(side_effect=yaml.YAMLError("malformed"))
                # 不应抛出
                await orch._apply_review_rules(session)


if __name__ == "__main__":
    unittest.main(verbosity=2)

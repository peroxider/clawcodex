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
    """F-121: _apply_review_rules 已简化为无操作（规则提取改为 CLI 触发）。"""

    async def test_apply_review_rules_is_noop(self) -> None:
        """_apply_review_rules 不再调用 RuleEngine.apply，只是空返回。"""
        with tempfile.TemporaryDirectory() as tmp:
            workflow = WorkflowConfig(
                rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
            )
            orch = _make_orchestrator(workflow, str(Path(tmp) / "WORKFLOW.md"))
            session = _make_session()

            with patch("extensions.orchestrator.orchestrator.RuleEngine") as MockEngine:
                await orch._apply_review_rules(session)
                # 不应调用 apply（规则提取已改为 CLI 触发）
                MockEngine.return_value.apply.assert_not_called()
                MockEngine.get_rules_path.assert_not_called()

    async def test_apply_review_rules_never_throws(self) -> None:
        """_apply_review_rules 即使传入任意 session 也不会抛出。"""
        workflow = WorkflowConfig(
            rules=RulesConfig(enabled=True, path="workflow.rules.yaml"),
        )
        orch = _make_orchestrator(workflow, "/tmp/WORKFLOW.md")
        session = _make_session()
        # 不应抛出任何异常
        await orch._apply_review_rules(session)


if __name__ == "__main__":
    unittest.main(verbosity=2)

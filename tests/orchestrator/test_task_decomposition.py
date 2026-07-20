from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from clawcodex_ext.cli.parser import build_parser
from extensions.orchestrator import modes as mode_registry
from extensions.orchestrator.config.schema import WorkflowConfig
from extensions.orchestrator.git_sync import VerificationFailed
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.mode_router import HeuristicRouter
from extensions.orchestrator.mode_selector import ModeSelector
from extensions.orchestrator.modes.swarm import SwarmModeRunner
from extensions.orchestrator.task_decomposition import (
    TaskDecomposer,
    validate_task_execution,
    write_task_plan,
)
from extensions.orchestrator.task_decomposition.models import Subtask, TaskPlan


class FakeAgentRunner:
    def __init__(self) -> None:
        self.agent_config = SimpleNamespace(coordinator_mode=False)
        self.calls = []

    async def run(self, session, workflow, **hooks):
        self.calls.append(
            {
                "coordinator": self.agent_config.coordinator_mode,
                "session_coordinator": getattr(session, "coordinator_mode", None),
                "prompt": session.prompt_override,
                "run_kind": session.run_kind,
            }
        )
        return "done"


def test_fallback_plan_is_investigate_implement_verify() -> None:
    plan = TaskDecomposer().decompose_issue(
        Issue(id="1", title="Fix race", description="The operation races in production")
    )
    assert [task.id for task in plan.subtasks] == ["task-1", "task-2", "task-3"]
    assert plan.waves == (("task-1",), ("task-2",), ("task-3",))


def test_explicit_independent_tasks_share_waves() -> None:
    issue = Issue(
        id="1",
        title="Migration",
        description="- Update API\n- Update CLI\n- Update docs\n- Then run integration tests",
    )
    plan = TaskDecomposer(max_parallel=2).decompose_issue(issue)
    assert len(plan.subtasks) == 4
    assert all(len(wave) <= 2 for wave in plan.waves)
    assert plan.subtasks[-1].depends_on == ("task-1", "task-2", "task-3")


def test_explicit_plan_infers_discovery_implementation_and_verification_dependencies() -> None:
    issue = Issue(
        id="1",
        title="Provider refactor",
        description=(
            "- 梳理 Provider 调用关系\n"
            "- 重构公共接口\n"
            "- 保持现有 provider 兼容\n"
            "- 补充回归测试\n"
            "- 执行验证并整理结果"
        ),
    )
    plan = TaskDecomposer(max_parallel=3).decompose_issue(issue)
    assert plan.subtasks[0].depends_on == ()
    assert plan.subtasks[1].depends_on == ("task-1",)
    assert plan.subtasks[2].depends_on == ("task-1",)
    assert plan.subtasks[3].depends_on == ("task-1", "task-2", "task-3")
    assert plan.subtasks[4].depends_on == ("task-1", "task-2", "task-3", "task-4")
    assert plan.waves == (
        ("task-1",),
        ("task-2", "task-3"),
        ("task-4",),
        ("task-5",),
    )


def test_plan_validation_rejects_dependency_in_same_or_later_wave() -> None:
    plan = TaskPlan(
        goal="bad",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(
                id="task-2",
                title="two",
                description="two",
                depends_on=("task-1",),
            ),
        ),
        waves=(("task-1", "task-2"),),
        max_parallel=2,
    )
    with pytest.raises(ValueError, match="must run after"):
        plan.validate(max_subtasks=4, max_waves=4)


def test_long_sequential_plan_falls_back_within_wave_budget() -> None:
    issue = Issue(
        id="1",
        title="Long validation",
        description="\n".join(f"- Then verify step {index}" for index in range(1, 9)),
    )
    plan = TaskDecomposer(max_subtasks=8, max_waves=2).decompose_issue(issue)
    assert len(plan.waves) == 2
    assert [task.id for task in plan.subtasks] == ["task-1", "task-2"]


def test_single_wave_fallback_still_requires_end_to_end_verification() -> None:
    plan = TaskDecomposer(max_subtasks=8, max_waves=1).decompose_issue(
        Issue(id="1", title="Bounded", description="Do a complex migration")
    )
    assert plan.waves == (("task-1",),)
    assert "implement" in plan.subtasks[0].title.lower()
    assert "verify" in plan.subtasks[0].title.lower()


def test_plan_is_written_as_structured_json(tmp_path) -> None:
    plan = TaskDecomposer().decompose_issue(Issue(id="1", title="Fix", description="Fix it"))
    path = write_task_plan(plan, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "task_decomposition.json"
    assert payload["goal"] == "Fix"
    assert payload["waves"] == [["task-1"], ["task-2"], ["task-3"]]
    assert all(row["status"] == "pending" for row in payload["subtasks"])
    assert all(row["evidence"] == "" for row in payload["subtasks"])
    assert all(row["started_at"] is None for row in payload["subtasks"])
    assert all(row["completed_at"] is None for row in payload["subtasks"])


def _write_execution_evidence(tmp_path, plan, evidence_rows):
    payload = plan.to_dict()
    for row in payload["subtasks"]:
        row.update(evidence_rows[row["id"]])
    path = tmp_path / "task_decomposition.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_execution_evidence_accepts_completed_dependency_order(tmp_path) -> None:
    plan = TaskPlan(
        goal="ordered",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(
                id="task-2",
                title="two",
                description="two",
                depends_on=("task-1",),
            ),
        ),
        waves=(("task-1",), ("task-2",)),
        max_parallel=1,
    )
    path = _write_execution_evidence(
        tmp_path,
        plan,
        {
            "task-1": {
                "status": "completed",
                "evidence": "pytest task one",
                "started_at": 1,
                "completed_at": 2,
            },
            "task-2": {
                "status": "completed",
                "evidence": ["pytest task two"],
                "started_at": 2,
                "completed_at": 3,
            },
        },
    )

    validate_task_execution(path, plan)


def test_execution_evidence_accepts_per_task_worker_files(tmp_path) -> None:
    plan = TaskPlan(
        goal="parallel",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(id="task-2", title="two", description="two"),
        ),
        waves=(("task-1", "task-2"),),
        max_parallel=2,
    )
    path = tmp_path / "task_decomposition.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    evidence_dir = tmp_path / "task_evidence"
    evidence_dir.mkdir()
    for task_id in ("task-1", "task-2"):
        (evidence_dir / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "id": task_id,
                    "status": "completed",
                    "evidence": f"pytest {task_id}: passed",
                    "started_at": "2099-01-01T00:00:00Z",
                    "completed_at": "2099-01-01T00:00:01Z",
                }
            ),
            encoding="utf-8",
        )

    validate_task_execution(path, plan)


def test_per_task_evidence_uses_host_mtime_for_dependency_order(tmp_path) -> None:
    plan = TaskPlan(
        goal="ordered",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(
                id="task-2",
                title="two",
                description="two",
                depends_on=("task-1",),
            ),
        ),
        waves=(("task-1",), ("task-2",)),
        max_parallel=1,
    )
    path = tmp_path / "task_decomposition.json"
    path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    evidence_dir = tmp_path / "task_evidence"
    evidence_dir.mkdir()
    for index, task_id in enumerate(("task-1", "task-2"), start=1):
        evidence_path = evidence_dir / f"{task_id}.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "id": task_id,
                    "status": "completed",
                    "evidence": "passed",
                    "started_at": 9999999999,
                    "completed_at": 1,
                }
            ),
            encoding="utf-8",
        )
        os.utime(evidence_path, (index, index))

    validate_task_execution(path, plan)


@pytest.mark.parametrize(
    ("row_updates", "error"),
    [
        ({"evidence": ""}, "has no completion evidence"),
        ({"evidence": ["  "]}, "has no completion evidence"),
        ({"started_at": "not-a-time"}, "invalid started_at"),
    ],
)
def test_execution_evidence_rejects_missing_or_invalid_fields(
    tmp_path,
    row_updates,
    error,
) -> None:
    plan = TaskPlan(
        goal="one",
        subtasks=(Subtask(id="task-1", title="one", description="one"),),
        waves=(("task-1",),),
        max_parallel=1,
    )
    row = {
        "status": "completed",
        "evidence": "verified",
        "started_at": 1,
        "completed_at": 2,
    }
    row.update(row_updates)
    path = _write_execution_evidence(tmp_path, plan, {"task-1": row})

    with pytest.raises(ValueError, match=error):
        validate_task_execution(path, plan)


def test_execution_evidence_rejects_duplicate_task_rows(tmp_path) -> None:
    plan = TaskPlan(
        goal="one",
        subtasks=(Subtask(id="task-1", title="one", description="one"),),
        waves=(("task-1",),),
        max_parallel=1,
    )
    payload = plan.to_dict()
    payload["subtasks"] = [payload["subtasks"][0], payload["subtasks"][0]]
    path = tmp_path / "task_decomposition.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly the seed task ids"):
        validate_task_execution(path, plan)


def test_execution_evidence_rejects_dependency_overlap(tmp_path) -> None:
    plan = TaskPlan(
        goal="ordered",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(
                id="task-2",
                title="two",
                description="two",
                depends_on=("task-1",),
            ),
        ),
        waves=(("task-1",), ("task-2",)),
        max_parallel=2,
    )
    path = _write_execution_evidence(
        tmp_path,
        plan,
        {
            "task-1": {
                "status": "completed",
                "evidence": "one",
                "started_at": 1,
                "completed_at": 4,
            },
            "task-2": {
                "status": "completed",
                "evidence": "two",
                "started_at": 2,
                "completed_at": 3,
            },
        },
    )

    with pytest.raises(ValueError, match="before dependency task-1 completed"):
        validate_task_execution(path, plan)


def test_execution_evidence_rejects_parallelism_above_limit(tmp_path) -> None:
    plan = TaskPlan(
        goal="bounded",
        subtasks=(
            Subtask(id="task-1", title="one", description="one"),
            Subtask(id="task-2", title="two", description="two"),
        ),
        waves=(("task-1",), ("task-2",)),
        max_parallel=1,
    )
    path = _write_execution_evidence(
        tmp_path,
        plan,
        {
            "task-1": {
                "status": "completed",
                "evidence": "one",
                "started_at": 1,
                "completed_at": 4,
            },
            "task-2": {
                "status": "completed",
                "evidence": "two",
                "started_at": 2,
                "completed_at": 3,
            },
        },
    )

    with pytest.raises(ValueError, match="peak parallelism 2 exceeds limit 1"):
        validate_task_execution(path, plan)


def test_swarm_runner_persists_plan_and_uses_coordinator(tmp_path) -> None:
    agent = FakeAgentRunner()
    runner = SwarmModeRunner(agent, max_subtasks=5, max_parallel=2)
    session = SimpleNamespace(
        issue=Issue(id="1", title="Complex change", description="Do several things"),
        workspace=SimpleNamespace(path=tmp_path),
        prompt_override=None,
        run_kind="issue",
    )

    result = asyncio.run(runner.run(session, WorkflowConfig()))

    assert result == "done"
    assert agent.calls[0]["session_coordinator"] is True
    assert agent.calls[0]["run_kind"] == "swarm"
    assert "Execution rules" in agent.calls[0]["prompt"]
    assert "write-capable worker" in agent.calls[0]["prompt"]
    assert "exact task id" in agent.calls[0]["prompt"]
    assert "task_evidence" in agent.calls[0]["prompt"]
    assert "Never edit task_decomposition.json" in agent.calls[0]["prompt"]
    assert "Do not commit files under .orchestrator_control" in agent.calls[0]["prompt"]
    assert (tmp_path / ".orchestrator_control" / "task_decomposition.json").exists()
    assert session.prompt_override is None
    assert session.run_kind == "issue"
    assert agent.agent_config.coordinator_mode is False


def test_swarm_runner_rejects_completed_session_without_execution_evidence(tmp_path) -> None:
    agent = FakeAgentRunner()
    runner = SwarmModeRunner(agent, max_subtasks=5, max_parallel=2)
    session = SimpleNamespace(
        issue=Issue(id="1", title="Complex change", description="Do several things"),
        workspace=SimpleNamespace(path=tmp_path),
        prompt_override=None,
        run_kind="issue",
        status="completed",
    )

    with pytest.raises(VerificationFailed, match="execution evidence validation"):
        asyncio.run(runner.run(session, WorkflowConfig()))


def test_orchestrator_rejects_explicit_unregistered_issue_mode() -> None:
    from extensions.orchestrator.orchestrator import Orchestrator

    instance = object.__new__(Orchestrator)
    instance.stage_runners = {}
    instance.agent_runner = FakeAgentRunner()
    session = SimpleNamespace(
        issue=Issue(id="42", title="Complex"),
        collaboration_mode="swarm",
        run_kind="issue",
    )

    with patch.dict(mode_registry._registry, {}, clear=True):
        with pytest.raises(RuntimeError, match="mode 'swarm'.*not enabled"):
            instance._resolve_session_runner(session)


def test_workflow_config_parses_swarm_limits() -> None:
    workflow = WorkflowConfig.from_dict(
        {
            "modes": {
                "enabled": ["single", "swarm"],
                "swarm": {"max_subtasks": 6, "max_parallel": 2, "max_waves": 4},
            }
        }
    )
    assert workflow.modes.swarm_max_subtasks == 6
    assert workflow.modes.swarm_max_parallel == 2
    assert workflow.modes.swarm_max_waves == 4


def test_mode_selector_accepts_swarm_label() -> None:
    decision = ModeSelector().choose(Issue(id="1", labels=["mode:swarm"]))
    assert decision.mode == "swarm"
    assert decision.source == "label"


def test_heuristic_router_detects_complex_bug() -> None:
    result = HeuristicRouter().choose(
        Issue(id="1", title="Complex bug", description="Needs multi-step reproduction")
    )
    assert result.mode == "swarm"
    assert result.confidence >= 0.5


def test_orchestrator_registers_swarm_runner() -> None:
    from extensions.orchestrator.orchestrator import Orchestrator

    instance = MagicMock(spec=["_register_collaboration_modes"])
    workflow = WorkflowConfig.from_dict({"modes": {"enabled": ["single", "swarm"]}})
    Orchestrator._register_collaboration_modes(instance, workflow, FakeAgentRunner())
    assert isinstance(mode_registry.get("swarm"), SwarmModeRunner)


def test_cli_parser_supports_swarm_aliases() -> None:
    args = build_parser().parse_args(["--swarm", "do work"])
    assert args.swarm is True
    assert args.prompt == "do work"
    alias = build_parser().parse_args(["--decompose", "do work"])
    assert alias.swarm is True
    effort = build_parser().parse_args(["--effort", "swarm", "do work"])
    assert effort.effort == "swarm"

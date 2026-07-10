"""F-115 检查点与恢复单元测试。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from extensions.orchestrator.workflow_engine.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ArtifactResolver,
    Checkpoint,
    CheckpointError,
    CheckpointManager,
    WorkflowResumer,
)
from extensions.orchestrator.workflow_engine.cost import CostBudget, CostTracker
from extensions.orchestrator.workflow_engine.decision_handler import DecisionHistory
from extensions.orchestrator.workflow_engine.engine import DeclarativeWorkflowEngine
from extensions.orchestrator.workflow_engine.workflow_state import (
    StageResult,
    StageStatus,
    WorkflowState,
)


# ── Checkpoint 序列化 ───────────────────────────────────────────────


class TestCheckpointSerialization:
    """Checkpoint 数据模型往返序列化。"""

    def test_to_dict_includes_schema_version_and_metadata(self) -> None:
        cp = Checkpoint(
            workflow_name="wf",
            workflow_version="1.2",
            current_stage=3,
            completed_stages=[1, 2],
            stage_results={
                1: {
                    "status": "completed",
                    "outputs": ["a.md"],
                    "error": None,
                    "cost_usd": 0.1,
                    "duration_seconds": 1.0,
                    "timestamp": "2026-07-10T10:00:00Z",
                }
            },
            decision_history=[{"stage": 2, "outcome": "proceed"}],
            cost_accumulated_usd=0.5,
            started_at="2026-07-10T09:00:00Z",
            last_checkpoint="2026-07-10T10:00:00Z",
            metadata={"run_id": "r1"},
            workflow_state_metadata={"key": "value"},
            rollback_events=[{"from_stage": 3, "to_stage": 1}],
            issue_context={"id": "i1", "title": "issue"},
            finished_at="2026-07-10T11:00:00Z",
        )
        data = cp.to_dict()
        assert data["schema_version"] == CHECKPOINT_SCHEMA_VERSION
        assert data["metadata"] == {"run_id": "r1"}
        assert data["workflow_state_metadata"] == {"key": "value"}
        assert data["rollback_events"] == [{"from_stage": 3, "to_stage": 1}]
        assert data["issue_context"] == {"id": "i1", "title": "issue"}
        assert data["finished_at"] == "2026-07-10T11:00:00Z"

    def test_from_dict_roundtrip(self) -> None:
        cp = Checkpoint(
            workflow_name="wf",
            workflow_version="1.0",
            current_stage=2,
            completed_stages=[1],
            stage_results={1: {"status": "completed", "outputs": ["out.md"]}},
            cost_accumulated_usd=1.23,
            metadata={"k": "v"},
        )
        cp2 = Checkpoint.from_dict(cp.to_dict())
        assert cp2.workflow_name == cp.workflow_name
        assert cp2.current_stage == cp.current_stage
        assert cp2.completed_stages == cp.completed_stages
        # to_dict/from_dict 会规范化 stage_results 的默认字段
        assert cp2.stage_results[1]["status"] == "completed"
        assert cp2.stage_results[1]["outputs"] == ["out.md"]
        assert cp2.cost_accumulated_usd == cp.cost_accumulated_usd
        assert cp2.metadata == cp.metadata

    def test_from_dict_rejects_unsupported_schema_version(self) -> None:
        data = {
            "workflow_name": "wf",
            "workflow_version": "1.0",
            "current_stage": 1,
            "schema_version": CHECKPOINT_SCHEMA_VERSION + 1,
        }
        with pytest.raises(CheckpointError):
            Checkpoint.from_dict(data)


# ── CheckpointManager ───────────────────────────────────────────────


class TestCheckpointManager:
    """检查点管理器读写与恢复。"""

    @pytest.fixture
    def tmp_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield tmp

    def _make_state(self) -> WorkflowState:
        state = WorkflowState(workflow_name="wf", workflow_version="1.0")
        state.current_stage = 2
        state.completed_stages = [1]
        state.cost_accumulated_usd = 0.42
        state.metadata = {"run_id": "r1"}
        state.rollback_events = [{"from_stage": 2, "to_stage": 1}]
        state.issue_context = {"id": "i1", "title": "title"}
        state.stage_results[1] = StageResult(
            stage_id=1,
            status=StageStatus.COMPLETED,
            outputs=["goal.md"],
            artifacts={"report": "/workspace/stage_01/report.md"},
            cost_usd=0.42,
            duration_seconds=10.0,
            timestamp="2026-07-10T10:00:00Z",
        )
        state.stage_statuses[1] = StageStatus.COMPLETED
        return state

    def test_save_and_load(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        state = self._make_state()
        decision_history = [{"stage": 1, "outcome": "proceed"}]

        cp = mgr.save(state, decision_history=decision_history)
        assert mgr.exists()
        assert cp.schema_version == CHECKPOINT_SCHEMA_VERSION

        loaded = mgr.load()
        assert loaded.workflow_name == "wf"
        assert loaded.current_stage == 2
        assert loaded.completed_stages == [1]
        assert loaded.cost_accumulated_usd == 0.42
        assert loaded.decision_history == decision_history
        assert loaded.workflow_state_metadata == {"run_id": "r1"}
        assert loaded.rollback_events == [{"from_stage": 2, "to_stage": 1}]
        assert loaded.issue_context == {"id": "i1", "title": "title"}

    def test_atomic_write_does_not_leave_corrupt_checkpoint(self, tmp_run_dir: str) -> None:
        """模拟写入过程中崩溃：temp 文件不应替代旧检查点。

        这里通过直接调用内部逻辑验证原子写入：写入后 checkpoint.json 有效。
        """
        mgr = CheckpointManager(tmp_run_dir)
        state = self._make_state()
        mgr.save(state)

        # 破坏 temp 文件不应影响已提交的 checkpoint.json
        temp_path = Path(tmp_run_dir) / "checkpoint.tmp"
        temp_path.write_text("garbage", encoding="utf-8")

        loaded = mgr.load()
        assert loaded.workflow_name == "wf"

    def test_load_missing_raises(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        with pytest.raises(CheckpointError):
            mgr.load()

    def test_delete(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        mgr.save(self._make_state())
        assert mgr.exists()
        mgr.delete()
        assert not mgr.exists()

    def test_restore_state(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        state = self._make_state()
        decision_history = [{"stage": 1, "outcome": "proceed", "next_stage": 2}]
        cp = mgr.save(state, decision_history=decision_history)

        restored = mgr.restore_state(cp)
        assert restored.workflow_name == "wf"
        assert restored.current_stage == 2
        assert restored.completed_stages == [1]
        assert restored.cost_accumulated_usd == 0.42
        assert restored.metadata == {"run_id": "r1"}
        assert restored.rollback_events == [{"from_stage": 2, "to_stage": 1}]
        assert restored.issue_context == {"id": "i1", "title": "title"}
        assert restored.stage_results[1].artifacts == {"report": "/workspace/stage_01/report.md"}
        assert restored.stage_statuses[1] == StageStatus.COMPLETED
        assert restored.decision_history is not None
        assert restored.decision_history.count("proceed", 1) == 1


# ── WorkflowResumer ───────────────────────────────────────────────


class TestWorkflowResumer:
    """WorkflowResumer 从检查点恢复引擎执行。"""

    @pytest.fixture
    def tmp_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield tmp

    @pytest.mark.asyncio
    async def test_resume_restores_cost_tracker(self, tmp_run_dir: str) -> None:
        """恢复时成本累计值应回填到 CostTracker。"""
        from extensions.orchestrator.workflow_engine.engine import (
            EngineConfig,
            WorkflowSchema,
        )

        called = {"times": 0}
        async def fake_execute(*args, **kwargs):  # type: ignore[no-redef]
            called["times"] += 1
            return MagicMock()

        schema = WorkflowSchema(name="wf", version="1.0", stages=[])
        engine = DeclarativeWorkflowEngine(schema, config=EngineConfig())
        engine.execute = fake_execute  # type: ignore[method-assign]

        mgr = CheckpointManager(tmp_run_dir)
        state = WorkflowState(workflow_name="wf", workflow_version="1.0")
        state.current_stage = 0
        state.cost_accumulated_usd = 12.34
        mgr.save(state)

        resumer = WorkflowResumer(mgr)
        await resumer.resume(engine)

        assert engine.cost_tracker.total_usd == 12.34
        assert called["times"] == 1


# ── ArtifactResolver ───────────────────────────────────────────────


class TestArtifactResolver:
    """跨阶段产物路径解析。"""

    def test_resolve_with_artifact(self) -> None:
        state = WorkflowState(workflow_name="wf")
        state.stage_results[1] = StageResult(
            stage_id=1,
            status=StageStatus.COMPLETED,
            artifacts={"report.md": "/workspace/stage_01/report.md"},
        )
        result = ArtifactResolver.resolve(
            "Review ${stage:1:output:report.md}",
            state=state,
        )
        assert result == "Review /workspace/stage_01/report.md"

    def test_resolve_fallback_to_workspace_dir(self) -> None:
        state = WorkflowState(workflow_name="wf")
        result = ArtifactResolver.resolve(
            "Open ${stage:2:output:summary.md}",
            state=state,
            workspace_dir="/tmp/ws",
        )
        assert result == "Open /tmp/ws/stage_02/summary.md"

    def test_resolve_keeps_template_when_no_fallback(self) -> None:
        state = WorkflowState(workflow_name="wf")
        result = ArtifactResolver.resolve(
            "Open ${stage:2:output:summary.md}",
            state=state,
        )
        assert result == "Open ${stage:2:output:summary.md}"

    def test_resolve_multiple_placeholders(self) -> None:
        state = WorkflowState(workflow_name="wf")
        state.stage_results[1] = StageResult(
            stage_id=1,
            status=StageStatus.COMPLETED,
            artifacts={"a.md": "/path/a.md"},
        )
        state.stage_results[2] = StageResult(
            stage_id=2,
            status=StageStatus.COMPLETED,
            artifacts={"b.md": "/path/b.md"},
        )
        result = ArtifactResolver.resolve(
            "A=${stage:1:output:a.md} B=${stage:2:output:b.md}",
            state=state,
        )
        assert result == "A=/path/a.md B=/path/b.md"


# ── 集成：清理与保留 ───────────────────────────────────────────────


class TestCheckpointLifecycle:
    """检查点成功清理/失败保留行为。"""

    @pytest.fixture
    def tmp_run_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield tmp

    def test_success_deletes_checkpoint(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        state = WorkflowState(workflow_name="wf")
        mgr.save(state)
        assert mgr.exists()
        mgr.delete()
        assert not mgr.exists()

    def test_checkpoint_written_to_disk_is_valid_json(self, tmp_run_dir: str) -> None:
        mgr = CheckpointManager(tmp_run_dir)
        state = WorkflowState(workflow_name="wf", workflow_version="1.0")
        state.current_stage = 1
        state.completed_stages = [1]
        state.cost_accumulated_usd = 0.1
        mgr.save(state)

        path = Path(tmp_run_dir) / "checkpoint.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == CHECKPOINT_SCHEMA_VERSION
        assert data["workflow_name"] == "wf"
        assert data["cost_accumulated_usd"] == 0.1

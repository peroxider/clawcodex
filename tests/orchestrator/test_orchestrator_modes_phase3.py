"""Phase-3 unit tests: CoordinatorModeRunner + DebateModeRunner.

These cover the two final mode runners. Phase-1 / Phase-2 stayed green
because the new modes are only registered when ``modes.enabled`` lists
them — workflows that don't opt in keep their byte-identical
``single``-only behavior.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from extensions.orchestrator import modes as mode_registry
from extensions.orchestrator.config.schema import (
    ModesConfig,
    WorkflowConfig,
    _parse_modes_config,
)
from extensions.orchestrator.modes.coordinator import CoordinatorModeRunner
from extensions.orchestrator.modes.debate import DebateModeRunner
from extensions.orchestrator.modes.pipeline import PipelineModeRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _StubAgentConfig:
    """Mutable stand-in for the real ``AgentConfig``."""

    coordinator_mode: bool = False


class _StubAgentRunner:
    """Records calls and (optionally) raises mid-run."""

    def __init__(self, *, raise_on_call: int | None = None) -> None:
        self.agent_config = _StubAgentConfig()
        self.calls: list[dict[str, Any]] = []
        self._raise_on_call = raise_on_call

    async def run(self, session: Any, workflow: Any, **hooks: Any) -> str:
        self.calls.append(
            {
                "coordinator_mode_at_entry": self.agent_config.coordinator_mode,
                "prompt": session.prompt_override,
                "run_kind": session.run_kind,
                "run_id": session.run_id,
                "turn_count_at_entry": session.turn_count,
            }
        )
        if (
            self._raise_on_call is not None
            and len(self.calls) == self._raise_on_call
        ):
            raise RuntimeError("simulated agent crash")
        # Mimic AgentRunner.run's side effects.
        session.turn_count = 5
        session.status = "completed"
        session.output_text = f"output of {session.run_kind}"
        if session.run_id is None:
            session.run_id = f"run-{len(self.calls)}"
        return "ok"


def _make_session() -> Any:
    s = MagicMock(name="AgentSession")
    s.issue = MagicMock()
    s.issue.id = "ISSUE-1"
    s.issue.title = "Test"
    s.issue.description = "Hello"
    s.run_kind = "issue"
    s.run_id = None
    s.turn_count = 0
    s.status = "running"
    s.output_text = ""
    s.session_end_reason = None
    s.session_end_summary = ""
    s.consecutive_429_count = 0
    s.rate_limit_pending_turn = None
    s.prompt_override = None
    return s


# ---------------------------------------------------------------------------
# CoordinatorModeRunner
# ---------------------------------------------------------------------------


class TestCoordinatorModeRunner(unittest.TestCase):
    def test_enables_coordinator_mode_during_run(self) -> None:
        agent = _StubAgentRunner()
        agent.agent_config.coordinator_mode = False
        runner = CoordinatorModeRunner(agent)
        asyncio.run(runner.run(_make_session(), MagicMock()))
        self.assertEqual(
            agent.calls[0]["coordinator_mode_at_entry"], True
        )

    def test_restores_original_value_after_run(self) -> None:
        agent = _StubAgentRunner()
        agent.agent_config.coordinator_mode = False
        runner = CoordinatorModeRunner(agent)
        asyncio.run(runner.run(_make_session(), MagicMock()))
        self.assertFalse(agent.agent_config.coordinator_mode)

    def test_preserves_true_original_value(self) -> None:
        agent = _StubAgentRunner()
        agent.agent_config.coordinator_mode = True
        runner = CoordinatorModeRunner(agent)
        asyncio.run(runner.run(_make_session(), MagicMock()))
        self.assertTrue(agent.agent_config.coordinator_mode)
        self.assertEqual(
            agent.calls[0]["coordinator_mode_at_entry"], True
        )

    def test_restores_value_even_if_run_raises(self) -> None:
        agent = _StubAgentRunner(raise_on_call=1)
        agent.agent_config.coordinator_mode = False
        runner = CoordinatorModeRunner(agent)
        with self.assertRaises(RuntimeError):
            asyncio.run(runner.run(_make_session(), MagicMock()))
        # Critical: leaked coordinator_mode=True would silently flip
        # every subsequent issue into coordinator mode. The finally
        # clause must restore the original False.
        self.assertFalse(agent.agent_config.coordinator_mode)


# ---------------------------------------------------------------------------
# DebateModeRunner
# ---------------------------------------------------------------------------


class TestDebateModeRunner(unittest.TestCase):
    def test_runs_proposers_then_judge(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        stages = [r.stage for r in results]
        self.assertEqual(stages, ["proposer_a", "proposer_b", "judge"])

    def test_proposer_prompts_omit_other_proposers(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Proposer A's prompt must NOT mention Proposer B (and vice versa).
        prompt_a = agent.calls[0]["prompt"]
        prompt_b = agent.calls[1]["prompt"]
        self.assertNotIn("proposer_b", prompt_a)
        self.assertNotIn("Output of pipeline:", prompt_a)
        self.assertNotIn("proposer_a", prompt_b)
        # Each proposer prompt must include the issue block.
        self.assertIn("## Issue", prompt_a)
        self.assertIn("## Issue", prompt_b)

    def test_judge_prompt_includes_all_proposals(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        judge_prompt = agent.calls[2]["prompt"]
        self.assertIn("Proposal from proposer_a", judge_prompt)
        self.assertIn("Proposal from proposer_b", judge_prompt)
        self.assertIn("output of debate:proposer_a", judge_prompt)
        self.assertIn("output of debate:proposer_b", judge_prompt)

    def test_run_kinds_per_stage(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        self.assertEqual(
            [c["run_kind"] for c in agent.calls],
            ["debate:proposer_a", "debate:proposer_b", "debate:judge"],
        )

    def test_resets_session_between_stages(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        for call in agent.calls:
            self.assertEqual(call["turn_count_at_entry"], 0)
            self.assertIsNone(call["run_id"])  # forced fresh per stage

    def test_aborts_before_judge_on_proposer_failure(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent)
        session = _make_session()
        # Patch the stub so proposer_b leaves session in a terminal state.
        original_run = agent.run

        async def _patched_run(s: Any, w: Any, **h: Any) -> str:
            await original_run(s, w, **h)
            if s.run_kind == "debate:proposer_b":
                s.status = "stagnation"
            return "ok"

        agent.run = _patched_run  # type: ignore[assignment]
        results = asyncio.run(runner.run(session, MagicMock()))
        # Only the two proposers — no judge call.
        self.assertEqual(len(results), 2)
        self.assertEqual(len(agent.calls), 2)
        self.assertEqual(results[-1].status, "stagnation")

    def test_empty_proposers_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DebateModeRunner(_StubAgentRunner(), proposers=())

    def test_custom_proposer_names(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("alice", "bob", "carol")
        )
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        self.assertEqual(
            [r.stage for r in results],
            ["alice", "bob", "carol", "judge"],
        )
        # Proposer count interpolated into the prompt.
        self.assertIn(
            "one of 3 independent proposers", agent.calls[0]["prompt"]
        )

    def test_proposer_done_sentinel_uses_uppercase_name(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent, proposers=("alice",))
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Sentinel: "[ALICE DONE]"
        self.assertIn("[ALICE DONE]", agent.calls[0]["prompt"])


# ---------------------------------------------------------------------------
# ModesConfig debate_proposers parsing
# ---------------------------------------------------------------------------


class TestModesConfigDebate(unittest.TestCase):
    def test_default_proposers(self) -> None:
        cfg = _parse_modes_config({})
        self.assertEqual(cfg.debate_proposers, ["proposer_a", "proposer_b"])

    def test_custom_proposers(self) -> None:
        cfg = _parse_modes_config(
            {"debate": {"proposers": ["alice", "bob", "carol"]}}
        )
        self.assertEqual(cfg.debate_proposers, ["alice", "bob", "carol"])


# ---------------------------------------------------------------------------
# Orchestrator-level registration of Phase-3 modes
# ---------------------------------------------------------------------------


class TestOrchestratorPhase3Registration(unittest.TestCase):
    def setUp(self) -> None:
        mode_registry._registry.clear()

    def test_register_coordinator_when_enabled(self) -> None:
        from extensions.orchestrator.orchestrator import Orchestrator

        instance = MagicMock(spec=["_register_collaboration_modes"])
        Orchestrator._register_collaboration_modes(
            instance,
            workflow=WorkflowConfig.from_dict(
                {"modes": {"enabled": ["single", "coordinator"]}}
            ),
            agent_runner=_StubAgentRunner(),
        )
        self.assertIn("coordinator", mode_registry.available())
        self.assertIsInstance(
            mode_registry.get("coordinator"), CoordinatorModeRunner
        )

    def test_register_debate_when_enabled(self) -> None:
        from extensions.orchestrator.orchestrator import Orchestrator

        instance = MagicMock(spec=["_register_collaboration_modes"])
        Orchestrator._register_collaboration_modes(
            instance,
            workflow=WorkflowConfig.from_dict(
                {
                    "modes": {
                        "enabled": ["single", "debate"],
                        "debate": {"proposers": ["alice", "bob"]},
                    }
                }
            ),
            agent_runner=_StubAgentRunner(),
        )
        self.assertIn("debate", mode_registry.available())
        runner = mode_registry.get("debate")
        self.assertIsInstance(runner, DebateModeRunner)
        self.assertEqual(runner.proposers, ("alice", "bob"))

    def test_register_all_modes(self) -> None:
        from extensions.orchestrator.orchestrator import Orchestrator

        instance = MagicMock(spec=["_register_collaboration_modes"])
        Orchestrator._register_collaboration_modes(
            instance,
            workflow=WorkflowConfig.from_dict(
                {
                    "modes": {
                        "enabled": [
                            "single",
                            "pipeline",
                            "coordinator",
                            "debate",
                        ]
                    }
                }
            ),
            agent_runner=_StubAgentRunner(),
        )
        self.assertEqual(
            sorted(mode_registry.available()),
            ["coordinator", "debate", "pipeline", "single"],
        )


# ---------------------------------------------------------------------------
# Debate hardening (lens diversity + workspace isolation)
# ---------------------------------------------------------------------------


class TestDebateProposerLensDiversity(unittest.TestCase):
    """Each proposer must get a DIFFERENT lens so the judge sees real
    contrasts, not near-identical proposals from a 0-temperature model."""

    def test_first_two_proposers_get_distinct_lenses(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent, proposers=("alpha", "beta"))
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # First two proposer prompts contain different lens names.
        prompt_a = agent.calls[0]["prompt"]
        prompt_b = agent.calls[1]["prompt"]
        self.assertIn("simplicity-first", prompt_a)
        self.assertIn("robustness-first", prompt_b)
        self.assertNotIn("robustness-first", prompt_a)
        self.assertNotIn("simplicity-first", prompt_b)

    def test_lenses_cycle_when_more_proposers_than_lenses(self) -> None:
        # 5 proposers, only 4 default lenses → 5th cycles back to first.
        agent = _StubAgentRunner()
        names = tuple(f"p{i}" for i in range(5))
        runner = DebateModeRunner(agent, proposers=names)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Lens-name appearances per proposer prompt.
        first_lens = "simplicity-first"
        self.assertIn(first_lens, agent.calls[0]["prompt"])
        # 5th proposer (index 4) cycles back to index 0 → first lens again.
        self.assertIn(first_lens, agent.calls[4]["prompt"])

    def test_lens_instruction_present_in_prompt(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent, proposers=("solo",))
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # The full lens instruction (not just name) is in the prompt.
        self.assertIn(
            "Prefer the simplest possible approach", agent.calls[0]["prompt"]
        )


class TestDebateWorkspaceIsolation(unittest.TestCase):
    """Each proposer + judge starts from the same git baseline so a
    misbehaving proposer can't contaminate the next stage's view."""

    def test_snapshot_is_none_for_non_git_workspace(self) -> None:
        # Workspace path that exists but is NOT a git repo → graceful None.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            sha = DebateModeRunner._snapshot_workspace_head(session)
            self.assertIsNone(sha)

    def test_reset_is_noop_for_none_baseline(self) -> None:
        # Reset must NOT raise / crash when given baseline=None.
        session = _make_session()
        DebateModeRunner._reset_workspace_to(session, None)  # no exception

    def test_isolation_invoked_for_every_proposer_and_judge(self) -> None:
        # Patch the two isolation helpers to verify the call pattern.
        from unittest.mock import patch

        agent = _StubAgentRunner()
        runner = DebateModeRunner(agent, proposers=("alpha", "beta"))
        session = _make_session()

        with patch.object(
            DebateModeRunner, "_snapshot_workspace_head", return_value="abc123"
        ) as snap, patch.object(
            DebateModeRunner, "_reset_workspace_to"
        ) as reset:
            asyncio.run(runner.run(session, MagicMock()))

        # Snapshot once at start.
        self.assertEqual(snap.call_count, 1)
        # Reset 3 times: 2 proposers + 1 judge.
        self.assertEqual(reset.call_count, 3)
        # Every reset call uses the same baseline sha.
        for call_args in reset.call_args_list:
            self.assertEqual(call_args[0][1], "abc123")


# ---------------------------------------------------------------------------
# Pipeline structured handoff via plan file
# ---------------------------------------------------------------------------


class TestPipelineStructuredHandoff(unittest.TestCase):
    """ANALYZER writes a plan file; later stages reference it explicitly."""

    def test_analyzer_prompt_instructs_write_plan_file(self) -> None:
        from extensions.orchestrator.modes.pipeline import PipelineModeRunner

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        analyzer_prompt = agent.calls[0]["prompt"]
        self.assertIn(".clawcodex/pipeline-plan.md", analyzer_prompt)
        self.assertIn("Files to change", analyzer_prompt)
        self.assertIn("## Validation", analyzer_prompt)

    def test_implementer_prompt_references_plan_file(self) -> None:
        from extensions.orchestrator.modes.pipeline import PipelineModeRunner

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        implementer_prompt = agent.calls[1]["prompt"]
        self.assertIn(".clawcodex/pipeline-plan.md", implementer_prompt)
        self.assertIn("Read it first", implementer_prompt)

    def test_tester_prompt_references_plan_validation_section(self) -> None:
        from extensions.orchestrator.modes.pipeline import PipelineModeRunner

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        tester_prompt = agent.calls[2]["prompt"]
        self.assertIn("## Validation", tester_prompt)

    def test_analyzer_warning_logged_when_plan_file_missing(self) -> None:
        # The plan-file status logger emits a warning if analyzer didn't
        # write the file. Use a tmp workspace where no plan exists.
        import tempfile
        import logging
        from extensions.orchestrator.modes.pipeline import PipelineModeRunner

        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            session.issue.id = "ISSUE-X"
            with self.assertLogs(
                "extensions.orchestrator.modes.pipeline", level="WARNING"
            ) as cm:
                PipelineModeRunner._log_plan_file_status(session, "analyzer")
            joined = "\n".join(cm.output)
            self.assertIn("did NOT write", joined)


# ---------------------------------------------------------------------------
# Debate: judge model override
# ---------------------------------------------------------------------------


class _StubWorkflow:
    """Just enough surface for the judge model override to read/write."""

    def __init__(self, model: str = "deepseek-v4-flash") -> None:
        self.agent = MagicMock()
        self.agent.model = model


class TestDebateJudgeModelOverride(unittest.TestCase):
    def test_no_override_when_judge_model_none(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("alpha",), judge_model=None
        )
        wf = _StubWorkflow(model="deepseek-v4-flash")
        session = _make_session()
        asyncio.run(runner.run(session, wf))
        # judge_model=None → workflow.agent.model unchanged throughout.
        self.assertEqual(wf.agent.model, "deepseek-v4-flash")

    def test_judge_model_set_during_judge_stage_only(self) -> None:
        # Patch agent_runner.run to record workflow.agent.model at each call.
        agent = _StubAgentRunner()
        observed_models: list[str] = []
        orig_run = agent.run

        async def _patched_run(s: Any, w: Any, **h: Any) -> None:
            observed_models.append(w.agent.model)
            await orig_run(s, w, **h)

        agent.run = _patched_run  # type: ignore[assignment]

        runner = DebateModeRunner(
            agent,
            proposers=("alpha",),
            judge_model="deepseek-v4-strong",
        )
        wf = _StubWorkflow(model="deepseek-v4-flash")
        session = _make_session()
        asyncio.run(runner.run(session, wf))
        # 2 calls: proposer (default model) + judge (override).
        self.assertEqual(
            observed_models, ["deepseek-v4-flash", "deepseek-v4-strong"]
        )
        # After the runner returns, model is restored.
        self.assertEqual(wf.agent.model, "deepseek-v4-flash")

    def test_judge_model_restored_even_on_exception(self) -> None:
        # Patch agent_runner.run to raise during judge stage.
        agent = _StubAgentRunner()
        orig_run = agent.run

        async def _patched_run(s: Any, w: Any, **h: Any) -> None:
            await orig_run(s, w, **h)
            if s.run_kind.endswith(":judge"):
                raise RuntimeError("judge crashed")

        agent.run = _patched_run  # type: ignore[assignment]

        runner = DebateModeRunner(
            agent,
            proposers=("alpha",),
            judge_model="deepseek-v4-strong",
        )
        wf = _StubWorkflow(model="deepseek-v4-flash")
        session = _make_session()
        with self.assertRaises(RuntimeError):
            asyncio.run(runner.run(session, wf))
        # Critical: model restored to original even when judge raised.
        self.assertEqual(wf.agent.model, "deepseek-v4-flash")


# ---------------------------------------------------------------------------
# Debate: worktree isolation
# ---------------------------------------------------------------------------


class TestDebateWorktreeIsolation(unittest.TestCase):
    def test_invalid_isolation_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DebateModeRunner(
                _StubAgentRunner(),
                proposers=("a",),
                isolation="quantum-entanglement",
            )

    def test_isolation_none_skips_all_workspace_ops(self) -> None:
        from unittest.mock import patch

        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("a", "b"), isolation="none"
        )
        session = _make_session()
        with patch.object(
            DebateModeRunner, "_reset_workspace_to"
        ) as reset, patch.object(
            DebateModeRunner, "_create_worktree_and_swap"
        ) as create_wt:
            asyncio.run(runner.run(session, MagicMock()))
        # With isolation=none, neither reset nor worktree-create runs.
        self.assertEqual(reset.call_count, 0)
        self.assertEqual(create_wt.call_count, 0)

    def test_isolation_worktree_creates_per_proposer(self) -> None:
        from unittest.mock import patch
        from pathlib import Path

        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("a", "b"), isolation="worktree"
        )
        session = _make_session()
        session.workspace.path = "/tmp/fake-workspace"
        fake_wt_paths = [Path("/tmp/wt-a"), Path("/tmp/wt-b")]

        with patch.object(
            DebateModeRunner,
            "_snapshot_workspace_head",
            return_value="abc123",
        ), patch.object(
            DebateModeRunner,
            "_create_worktree_and_swap",
            side_effect=fake_wt_paths,
        ) as create_wt, patch.object(
            DebateModeRunner, "_remove_worktree"
        ) as remove_wt, patch.object(
            DebateModeRunner, "_reset_workspace_to"
        ) as reset:
            asyncio.run(runner.run(session, MagicMock()))

        # Per proposer: one worktree created + torn down.
        self.assertEqual(create_wt.call_count, 2)
        self.assertEqual(remove_wt.call_count, 2)
        # Judge runs in the ORIGINAL workspace (its commit needs to land
        # on the real branch). In worktree mode, the original workspace
        # was never touched by proposers, so judge doesn't need a reset
        # — the dir IS already at baseline.
        self.assertEqual(reset.call_count, 0)


# ---------------------------------------------------------------------------
# ModesConfig: new Phase-3 hardening fields parsing
# ---------------------------------------------------------------------------


class TestModesConfigPhase3Hardening(unittest.TestCase):
    def test_pipeline_max_retries_default(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config({})
        self.assertEqual(cfg.pipeline_max_retries_per_stage, 1)

    def test_pipeline_max_retries_negative_clamped(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config(
            {"pipeline": {"max_retries_per_stage": -3}}
        )
        self.assertEqual(cfg.pipeline_max_retries_per_stage, 0)

    def test_debate_judge_model_parsed(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config(
            {"debate": {"judge_model": "deepseek-v4-strong"}}
        )
        self.assertEqual(cfg.debate_judge_model, "deepseek-v4-strong")

    def test_debate_judge_model_empty_string_treated_as_none(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config({"debate": {"judge_model": ""}})
        self.assertIsNone(cfg.debate_judge_model)

    def test_debate_isolation_default_is_reset(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config({})
        self.assertEqual(cfg.debate_isolation, "reset")

    def test_debate_isolation_worktree_parsed(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config({"debate": {"isolation": "worktree"}})
        self.assertEqual(cfg.debate_isolation, "worktree")

    def test_debate_isolation_unknown_coerced_to_reset(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        cfg = _parse_modes_config({"debate": {"isolation": "yolo"}})
        self.assertEqual(cfg.debate_isolation, "reset")


# ---------------------------------------------------------------------------
# Real-multi-agent upgrades (Round 4):
#   · Pipeline per-stage model override
#   · Pipeline mailbox handoff (team.json auto-create + SendMessage prompt)
#   · Debate per-proposer model override (sequential mode)
#   · Debate parallel proposers (asyncio.gather)
# ---------------------------------------------------------------------------


class TestPipelineStageModelOverride(unittest.TestCase):
    """Per-stage model = different LLM brain per role. Sequential, no race."""

    def test_no_override_when_stage_models_empty(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent, stage_models={})
        wf = _StubWorkflow(model="default-model")
        session = _make_session()
        asyncio.run(runner.run(session, wf))
        # Model never touched.
        self.assertEqual(wf.agent.model, "default-model")

    def test_per_stage_model_swap_observed_at_each_stage(self) -> None:
        agent = _StubAgentRunner()
        observed: list[tuple[str, str]] = []
        orig_run = agent.run

        async def _patched(s: Any, w: Any, **h: Any) -> None:
            observed.append((s.run_kind, w.agent.model))
            await orig_run(s, w, **h)

        agent.run = _patched  # type: ignore[assignment]

        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer", "tester"),
            stage_models={"analyzer": "model-a", "tester": "model-b"},
        )
        wf = _StubWorkflow(model="default-flash")
        session = _make_session()
        asyncio.run(runner.run(session, wf))

        # analyzer → model-a; implementer → default (not overridden); tester → model-b.
        self.assertEqual(observed[0], ("pipeline:analyzer", "model-a"))
        self.assertEqual(observed[1], ("pipeline:implementer", "default-flash"))
        self.assertEqual(observed[2], ("pipeline:tester", "model-b"))
        # Restored after the runner returns.
        self.assertEqual(wf.agent.model, "default-flash")

    def test_model_restored_even_on_exception(self) -> None:
        agent = _StubAgentRunner()
        orig_run = agent.run

        async def _patched(s: Any, w: Any, **h: Any) -> None:
            await orig_run(s, w, **h)
            if s.run_kind == "pipeline:analyzer":
                raise RuntimeError("analyzer crashed")

        agent.run = _patched  # type: ignore[assignment]

        runner = PipelineModeRunner(
            agent, stage_models={"analyzer": "model-a"}
        )
        wf = _StubWorkflow(model="default-flash")
        session = _make_session()
        try:
            asyncio.run(runner.run(session, wf))
        except RuntimeError:
            pass
        # Critical: model restored even when stage threw.
        self.assertEqual(wf.agent.model, "default-flash")


class TestPipelineMailboxHandoff(unittest.TestCase):
    """handoff='mailbox' auto-writes team.json + adds SendMessage prompt."""

    def test_invalid_handoff_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PipelineModeRunner(_StubAgentRunner(), handoff="quantum")

    def test_default_handoff_is_prompt(self) -> None:
        runner = PipelineModeRunner(_StubAgentRunner())
        self.assertEqual(runner.handoff, "prompt")

    def test_mailbox_handoff_writes_team_json(self) -> None:
        import tempfile
        from pathlib import Path

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer"),
            handoff="mailbox",
        )
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            asyncio.run(runner.run(session, MagicMock()))
            team_path = Path(tmp) / ".clawcodex/team.json"
            self.assertTrue(team_path.exists(), "team.json must be written")
            import json
            data = json.loads(team_path.read_text())
            self.assertEqual(data["team_name"], "pipeline-team")
            self.assertEqual([m["name"] for m in data["members"]], ["analyzer", "implementer"])

    def test_mailbox_handoff_appends_sendmessage_instructions(self) -> None:
        import tempfile

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer", "tester"),
            handoff="mailbox",
        )
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            asyncio.run(runner.run(session, MagicMock()))
        # analyzer prompt: tells it to SendMessage to implementer.
        self.assertIn("Mailbox handoff", agent.calls[0]["prompt"])
        self.assertIn('SendMessage(to="implementer"', agent.calls[0]["prompt"])
        # implementer prompt: tells it to Read its inbox; SendMessage to tester.
        self.assertIn("Read it first", agent.calls[1]["prompt"])
        self.assertIn('SendMessage(to="tester"', agent.calls[1]["prompt"])
        # tester prompt: no SendMessage (last stage).
        self.assertIn("no SendMessage needed", agent.calls[2]["prompt"])

    def test_prompt_handoff_omits_mailbox_section(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent, handoff="prompt")
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # No mailbox section in any prompt.
        for call in agent.calls:
            self.assertNotIn("Mailbox handoff", call["prompt"])


class TestDebateProposerModelOverride(unittest.TestCase):
    """Sequential mode honors per-proposer model. Parallel ignores it (race-prone)."""

    def test_sequential_per_proposer_model_observed(self) -> None:
        agent = _StubAgentRunner()
        observed: list[tuple[str, str]] = []
        orig_run = agent.run

        async def _patched(s: Any, w: Any, **h: Any) -> None:
            observed.append((s.run_kind, w.agent.model))
            await orig_run(s, w, **h)

        agent.run = _patched  # type: ignore[assignment]

        runner = DebateModeRunner(
            agent,
            proposers=("a", "b"),
            proposer_models={"a": "model-b", "b": "model-c"},
            parallel=False,
        )
        wf = _StubWorkflow(model="default-model")
        session = _make_session()
        asyncio.run(runner.run(session, wf))
        # Filter to proposer rounds only (judge is last with default model).
        proposer_rows = [row for row in observed if "judge" not in row[0]]
        self.assertEqual(proposer_rows[0], ("debate:a", "model-b"))
        self.assertEqual(proposer_rows[1], ("debate:b", "model-c"))

    def test_parallel_with_proposer_models_warns_and_ignores(self) -> None:
        # parallel + proposer_models → logged warning + models NOT applied.
        with self.assertLogs(
            "extensions.orchestrator.modes.debate", level="WARNING"
        ) as cm:
            DebateModeRunner(
                _StubAgentRunner(),
                proposers=("a", "b"),
                proposer_models={"a": "model-b"},
                parallel=True,
                isolation="worktree",
            )
        self.assertTrue(any("IGNORED" in m for m in cm.output))


class TestDebateParallelProposers(unittest.TestCase):
    def test_parallel_requires_worktree_isolation(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            DebateModeRunner(
                _StubAgentRunner(),
                proposers=("a", "b"),
                parallel=True,
                isolation="reset",
            )
        self.assertIn("worktree", str(ctx.exception))

    def test_parallel_runs_proposers_concurrently_via_gather(self) -> None:
        from unittest.mock import patch
        from pathlib import Path

        # Track concurrency: each call increments active_count, sleeps a
        # tick, decrements. If parallel works, active_count peaks at >1.
        active = {"count": 0, "peak": 0}

        class _CountingAgent:
            def __init__(self) -> None:
                self.agent_config = _StubAgentConfig()
                self.calls: list[str] = []

            async def run(self, s: Any, w: Any, **h: Any) -> None:
                active["count"] += 1
                active["peak"] = max(active["peak"], active["count"])
                await asyncio.sleep(0.05)  # let the other coroutine in
                s.turn_count = 1
                s.output_text = f"out:{s.run_kind}"
                s.status = "completed"
                if s.run_id is None:
                    s.run_id = f"r-{len(self.calls)}"
                self.calls.append(s.run_kind)
                active["count"] -= 1

        agent = _CountingAgent()
        runner = DebateModeRunner(
            agent, proposers=("a", "b"), parallel=True, isolation="worktree"
        )
        session = _make_session()
        session.workspace.path = "/tmp/whatever"

        with patch.object(
            DebateModeRunner,
            "_snapshot_workspace_head",
            return_value="abc123",
        ), patch.object(
            DebateModeRunner,
            "_create_worktree_and_swap",
            side_effect=[Path("/tmp/wt-a"), Path("/tmp/wt-b")],
        ), patch.object(
            DebateModeRunner, "_remove_worktree"
        ):
            asyncio.run(runner.run(session, MagicMock()))

        # Concurrent peak should be 2 (both proposers running at once).
        self.assertEqual(active["peak"], 2)
        # Plus the judge ran serially after (1 more call).
        self.assertIn("debate:judge", agent.calls)


class TestPhase4ModesConfigParsing(unittest.TestCase):
    def setUp(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        self._parse = _parse_modes_config

    def test_pipeline_stage_models_parsed(self) -> None:
        cfg = self._parse({
            "pipeline": {
                "stage_models": {
                    "analyzer": "model-strong",
                    "tester": "deepseek-chat",
                }
            }
        })
        self.assertEqual(
            cfg.pipeline_stage_models,
            {"analyzer": "model-strong", "tester": "deepseek-chat"},
        )

    def test_pipeline_stage_models_default_empty(self) -> None:
        cfg = self._parse({})
        self.assertEqual(cfg.pipeline_stage_models, {})

    def test_pipeline_handoff_default_is_prompt(self) -> None:
        cfg = self._parse({})
        self.assertEqual(cfg.pipeline_handoff, "prompt")

    def test_pipeline_handoff_mailbox_parsed(self) -> None:
        cfg = self._parse({"pipeline": {"handoff": "mailbox"}})
        self.assertEqual(cfg.pipeline_handoff, "mailbox")

    def test_pipeline_handoff_unknown_coerced_to_prompt(self) -> None:
        cfg = self._parse({"pipeline": {"handoff": "magic"}})
        self.assertEqual(cfg.pipeline_handoff, "prompt")

    def test_debate_proposer_models_parsed(self) -> None:
        cfg = self._parse({
            "debate": {
                "proposer_models": {"a": "model-b", "b": "model-c"}
            }
        })
        self.assertEqual(
            cfg.debate_proposer_models, {"a": "model-b", "b": "model-c"}
        )

    def test_debate_parallel_parsed(self) -> None:
        cfg = self._parse({"debate": {"parallel": True}})
        self.assertTrue(cfg.debate_parallel)


# ---------------------------------------------------------------------------
# Bug regression tests (Round 4 code review)
# ---------------------------------------------------------------------------


class TestBugFixEmptyStageModel(unittest.TestCase):
    """Empty-string model IDs must be filtered at constructor level."""

    def test_empty_model_filtered_from_stage_models(self) -> None:
        runner = PipelineModeRunner(
            _StubAgentRunner(),
            stage_models={"analyzer": "model-a", "implementer": "", "tester": "  "},
        )
        self.assertEqual(runner.stage_models, {"analyzer": "model-a"})

    def test_empty_model_filtered_from_proposer_models(self) -> None:
        runner = DebateModeRunner(
            _StubAgentRunner(),
            proposers=("a", "b"),
            proposer_models={"a": "", "b": "model-c"},
        )
        self.assertEqual(runner.proposer_models, {"b": "model-c"})

    def test_none_stage_models_handled(self) -> None:
        runner = PipelineModeRunner(_StubAgentRunner(), stage_models=None)
        self.assertEqual(runner.stage_models, {})


class TestBugFixAgentNameEnvOnlyForMailbox(unittest.TestCase):
    """CLAUDE_CODE_AGENT_NAME env must NOT be set when handoff=prompt."""

    def setUp(self) -> None:
        self._orig = os.environ.get("CLAUDE_CODE_AGENT_NAME")
        os.environ.pop("CLAUDE_CODE_AGENT_NAME", None)

    def tearDown(self) -> None:
        if self._orig is not None:
            os.environ["CLAUDE_CODE_AGENT_NAME"] = self._orig
        else:
            os.environ.pop("CLAUDE_CODE_AGENT_NAME", None)

    def test_prompt_handoff_does_not_set_agent_name_env(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent, handoff="prompt")
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        self.assertNotIn("CLAUDE_CODE_AGENT_NAME", os.environ)

    def test_mailbox_handoff_does_set_agent_name_env(self) -> None:
        import tempfile
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer"),
            handoff="mailbox",
        )
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            # Snapshot env before the run to see it change.
            os.environ.pop("CLAUDE_CODE_AGENT_NAME", None)
            asyncio.run(runner.run(session, MagicMock()))
        # After run, env should be restored (agent name popped for mailbox,
        # then restored to None in __exit__).
        self.assertNotIn("CLAUDE_CODE_AGENT_NAME", os.environ)


class TestBugFixForkSessionDeepCopy(unittest.TestCase):
    """Parallel branches must NOT share mutable containers."""

    def test_forked_branch_has_independent_lists(self) -> None:
        session = _make_session()
        # Set up fake transcript state on the parent.
        session._transcript_tool_uses = ["tool_a"]
        session._transcript_pending_results = {"id1": "result1"}
        session._transcript_result_order = ["id1"]
        session.event_queue = object()
        session.pause_resume_event = object()
        session.state_cache = object()
        session._transcript_storage = object()

        branch = DebateModeRunner._fork_session_for_branch(session, "alpha")

        # Branch must have its own empty copies, not share the parent's.
        self.assertEqual(branch._transcript_tool_uses, [])
        self.assertIsNot(branch._transcript_tool_uses, session._transcript_tool_uses)
        self.assertEqual(branch._transcript_pending_results, {})
        self.assertIsNot(branch._transcript_pending_results, session._transcript_pending_results)
        self.assertEqual(branch._transcript_result_order, [])
        self.assertIsNot(branch._transcript_result_order, session._transcript_result_order)
        # Async primitives reset to None so AgentRunner re-creates them.
        self.assertIsNone(branch.event_queue)
        self.assertIsNone(branch.pause_resume_event)
        self.assertIsNone(branch.state_cache)
        self.assertIsNone(branch._transcript_storage)


# ---------------------------------------------------------------------------
# Bug audit fixes (Round 5): parallel exception isolation + unknown-key warns
# ---------------------------------------------------------------------------


class TestDebateParallelExceptionIsolation(unittest.TestCase):
    """One proposer crashing in parallel mode must NOT cancel the sibling
    and must NOT propagate as an unhandled exception. It should be
    surfaced as a _StageResult(status='failed'), matching sequential mode."""

    def test_parallel_one_proposer_raises_other_finishes(self) -> None:
        from unittest.mock import patch
        from pathlib import Path

        class _MixedAgent:
            def __init__(self) -> None:
                self.agent_config = _StubAgentConfig()
                self.calls: list[str] = []

            async def run(self, s: Any, w: Any, **h: Any) -> None:
                self.calls.append(s.run_kind)
                await asyncio.sleep(0.02)
                if s.run_kind == "debate:proposer_a":
                    raise RuntimeError("proposer_a intentionally crashed")
                s.turn_count = 1
                s.status = "completed"
                s.output_text = "clean b output"
                if s.run_id is None:
                    s.run_id = "r-b"

        agent = _MixedAgent()
        runner = DebateModeRunner(
            agent,
            proposers=("proposer_a", "proposer_b"),
            parallel=True,
            isolation="worktree",
        )
        session = _make_session()
        session.workspace.path = "/tmp/whatever"

        with patch.object(
            DebateModeRunner, "_snapshot_workspace_head", return_value="abc123"
        ), patch.object(
            DebateModeRunner,
            "_create_worktree_and_swap",
            side_effect=[Path("/tmp/wt-a"), Path("/tmp/wt-b")],
        ), patch.object(DebateModeRunner, "_remove_worktree"):
            # Must NOT raise — parallel isolation catches per-branch
            # exception + surfaces it as a failed _StageResult upstream.
            results = asyncio.run(runner.run(session, MagicMock()))

        # Both proposers were dispatched (gather with return_exceptions=True
        # keeps sibling running even after a's failure).
        proposer_calls = [c for c in agent.calls if c.startswith("debate:proposer_")]
        self.assertEqual(sorted(proposer_calls), ["debate:proposer_a", "debate:proposer_b"])
        # Judge should NOT run (any-proposer-failed check aborts before judge).
        self.assertNotIn("debate:judge", agent.calls)
        # Results: 2 stage results, one failed one completed.
        self.assertEqual(len(results), 2)
        by_stage = {r.stage: r for r in results}
        self.assertEqual(by_stage["proposer_a"].status, "failed")
        self.assertIn("RuntimeError", by_stage["proposer_a"].output)
        self.assertEqual(by_stage["proposer_b"].status, "completed")


class TestUnknownKeyWarnings(unittest.TestCase):
    """Passing stage_models / proposer_models with typo'd keys must emit
    a WARNING so operators don't silently wonder why their override was
    ignored. Regression: silent no-op is the classic 'why isn't my
    config working' trap."""

    def test_pipeline_stage_models_unknown_key_warns(self) -> None:
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="WARNING"
        ) as cm:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer", "implementer", "tester"),
                stage_models={"analzer": "model-a"},  # typo
            )
        joined = "\n".join(cm.output)
        self.assertIn("unknown keys", joined)
        self.assertIn("analzer", joined)

    def test_debate_proposer_models_unknown_key_warns(self) -> None:
        with self.assertLogs(
            "extensions.orchestrator.modes.debate", level="WARNING"
        ) as cm:
            DebateModeRunner(
                _StubAgentRunner(),
                proposers=("proposer_a", "proposer_b"),
                proposer_models={"proposr_a": "model-b"},  # typo
            )
        joined = "\n".join(cm.output)
        self.assertIn("unknown keys", joined)
        self.assertIn("proposr_a", joined)


class TestPipelineTeamJsonReWrittenPerStage(unittest.TestCase):
    """Regression: live e2e on h144 caught that .clawcodex/team.json
    written once at pipeline start could be silently clobbered by git
    operations between stages (a stale team.json from a previous test
    was committed to the repo history). Fix: re-write per stage."""

    def test_ensure_team_file_called_per_stage_in_mailbox_mode(self) -> None:
        from unittest.mock import patch
        import tempfile
        from pathlib import Path

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer", "tester"),
            handoff="mailbox",
            max_retries_per_stage=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            session = _make_session()
            session.workspace.path = tmp
            with patch.object(
                PipelineModeRunner, "_ensure_team_file", wraps=runner._ensure_team_file
            ) as spy:
                asyncio.run(runner.run(session, MagicMock()))
            # 1 call at run() start + 3 calls (one per stage) = 4 total.
            self.assertEqual(spy.call_count, 4)

    def test_ensure_team_file_NOT_called_in_prompt_mode(self) -> None:
        from unittest.mock import patch

        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer"),
            handoff="prompt",  # default
        )
        session = _make_session()
        with patch.object(
            PipelineModeRunner, "_ensure_team_file"
        ) as spy:
            asyncio.run(runner.run(session, MagicMock()))
        # prompt mode → team.json auto-write is completely skipped.
        self.assertEqual(spy.call_count, 0)


# ---------------------------------------------------------------------------
# Product-level improvements (Round 6):
#   · Debate judge_mode = "synthesize" (hybrid winner instead of single pick)
#   · Pipeline per-stage model over-log fix (no "overriding X → X" no-op)
#   · Pipeline per-stage max_turns override
# ---------------------------------------------------------------------------


class TestDebateJudgeMode(unittest.TestCase):
    def test_invalid_judge_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DebateModeRunner(
                _StubAgentRunner(),
                proposers=("a",),
                judge_mode="magic-8-ball",
            )

    def test_pick_mode_is_default(self) -> None:
        runner = DebateModeRunner(_StubAgentRunner())
        self.assertEqual(runner.judge_mode, "pick")

    def test_pick_mode_uses_pick_prompt(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("a", "b"), judge_mode="pick"
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        judge_prompt = agent.calls[-1]["prompt"]  # last call = judge
        self.assertIn("PICK mode", judge_prompt)
        self.assertIn("Pick ONE proposer", judge_prompt)
        self.assertNotIn("SYNTHESIZE mode", judge_prompt)

    def test_synthesize_mode_uses_synthesize_prompt(self) -> None:
        agent = _StubAgentRunner()
        runner = DebateModeRunner(
            agent, proposers=("a", "b"), judge_mode="synthesize"
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        judge_prompt = agent.calls[-1]["prompt"]
        self.assertIn("SYNTHESIZE mode", judge_prompt)
        # Synthesize-specific instructions.
        self.assertIn("KEEP", judge_prompt)
        self.assertIn("MERGE", judge_prompt)
        self.assertIn("CITE which proposer", judge_prompt)
        # Must NOT use the pick-only language.
        self.assertNotIn("Pick ONE proposer", judge_prompt)


class TestPipelineStageOverLogFix(unittest.TestCase):
    """When stage_model equals the current workflow.agent.model, we must
    NOT emit the noisy 'overriding X → X' log line (and must not do the
    no-op swap either). Regression: cluttered logs were burying real
    signal in e2e runs."""

    def test_no_swap_no_log_when_stage_model_equals_current(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer",),
            stage_models={"analyzer": "same-model"},
        )
        wf = _StubWorkflow(model="same-model")  # same as stage model
        session = _make_session()
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="INFO"
        ) as cm:
            asyncio.run(runner.run(session, wf))
        joined = "\n".join(cm.output)
        # No noisy "overriding X → X" line.
        self.assertNotIn("temporarily overriding workflow.agent.model", joined)

    def test_swap_and_log_when_stage_model_differs(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer",),
            stage_models={"analyzer": "different-model"},
        )
        wf = _StubWorkflow(model="workflow-default")
        session = _make_session()
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="INFO"
        ) as cm:
            asyncio.run(runner.run(session, wf))
        joined = "\n".join(cm.output)
        self.assertIn("temporarily overriding workflow.agent.model", joined)
        self.assertIn("workflow-default", joined)
        self.assertIn("different-model", joined)
        # Restored after.
        self.assertEqual(wf.agent.model, "workflow-default")


class TestPipelineStageMaxTurns(unittest.TestCase):
    def test_no_override_when_stage_max_turns_empty(self) -> None:
        # Constructor tolerates None (default) and empty dict — no error.
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent, stage_max_turns=None)
        self.assertEqual(runner.stage_max_turns, {})
        runner2 = PipelineModeRunner(agent, stage_max_turns={})
        self.assertEqual(runner2.stage_max_turns, {})

    def test_per_stage_max_turns_swap_observed_on_agent_runner(self) -> None:
        # Verify agent_runner.max_turns is mutated per stage + restored.
        class _MaxTurnsAgent:
            def __init__(self) -> None:
                self.agent_config = _StubAgentConfig()
                self.max_turns = 10        # base
                self.observed: list[tuple[str, int]] = []

            async def run(self, s: Any, w: Any, **h: Any) -> None:
                self.observed.append((s.run_kind, self.max_turns))
                s.turn_count = 1
                s.status = "completed"
                s.output_text = "ok"
                if s.run_id is None:
                    s.run_id = "r-x"

        agent = _MaxTurnsAgent()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer", "tester"),
            stage_max_turns={"analyzer": 20, "tester": 3},  # implementer not overridden
        )
        session = _make_session()
        asyncio.run(runner.run(session, _StubWorkflow(model="m")))

        # analyzer → 20; implementer → base (10); tester → 3.
        self.assertEqual(agent.observed[0], ("pipeline:analyzer", 20))
        self.assertEqual(agent.observed[1], ("pipeline:implementer", 10))
        self.assertEqual(agent.observed[2], ("pipeline:tester", 3))
        # Fully restored after runner returns.
        self.assertEqual(agent.max_turns, 10)

    def test_invalid_max_turns_dropped(self) -> None:
        # Non-int / zero / negative values are silently filtered by the
        # constructor. (Schema _normalize_int_map also filters at the
        # YAML level; this is defense-in-depth for direct construction.)
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer"),
            stage_max_turns={"analyzer": 0, "implementer": -1},
        )
        self.assertEqual(runner.stage_max_turns, {})

    def test_stage_max_turns_unknown_key_warns(self) -> None:
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="WARNING"
        ) as cm:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer",),
                stage_max_turns={"analzer": 20},  # typo
            )
        joined = "\n".join(cm.output)
        self.assertIn("stage_max_turns", joined)
        self.assertIn("analzer", joined)


class TestSchemaRound6Parsing(unittest.TestCase):
    def setUp(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        self._parse = _parse_modes_config

    def test_pipeline_stage_max_turns_parsed(self) -> None:
        cfg = self._parse({
            "pipeline": {"stage_max_turns": {"analyzer": 20, "tester": 3}}
        })
        self.assertEqual(
            cfg.pipeline_stage_max_turns, {"analyzer": 20, "tester": 3}
        )

    def test_pipeline_stage_max_turns_filters_bad_values(self) -> None:
        cfg = self._parse({
            "pipeline": {
                "stage_max_turns": {
                    "analyzer": 20,
                    "implementer": 0,
                    "tester": "not-a-number",
                    "": 5,
                    "bogus": -3,
                }
            }
        })
        # Only analyzer:20 survives — 0 is < min_value=1, "not-a-number"
        # can't be int-coerced, "" is empty key, -3 is < min.
        self.assertEqual(cfg.pipeline_stage_max_turns, {"analyzer": 20})

    def test_debate_judge_mode_default(self) -> None:
        cfg = self._parse({})
        self.assertEqual(cfg.debate_judge_mode, "pick")

    def test_debate_judge_mode_synthesize_parsed(self) -> None:
        cfg = self._parse({"debate": {"judge_mode": "synthesize"}})
        self.assertEqual(cfg.debate_judge_mode, "synthesize")

    def test_debate_judge_mode_unknown_coerced_to_pick(self) -> None:
        cfg = self._parse({"debate": {"judge_mode": "vibes"}})
        self.assertEqual(cfg.debate_judge_mode, "pick")


# ---------------------------------------------------------------------------
# Hierarchical agents (Round 7): Pipeline stages can nest Debate / Coordinator
# ---------------------------------------------------------------------------


class TestPipelineNestedStageSpec(unittest.TestCase):
    def test_default_stage_spec_empty(self) -> None:
        runner = PipelineModeRunner(_StubAgentRunner())
        self.assertEqual(runner.stage_specs, {})

    def test_agent_kind_stage_uses_agent_runner_path(self) -> None:
        # Explicit kind='agent' behaves the same as no spec at all.
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer",),
            stage_specs={"analyzer": {"kind": "agent"}},
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # 1 agent call, no nested runner.
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(agent.calls[0]["run_kind"], "pipeline:analyzer")

    def test_debate_kind_stage_dispatches_to_debate_runner(self) -> None:
        # A pipeline stage with kind=debate delegates to DebateModeRunner.
        # StubAgentRunner is called MORE than once for this stage
        # (2 proposers + 1 judge = 3 sub-runs), instead of the usual 1.
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "implementer", "tester"),
            stage_specs={
                "implementer": {
                    "kind": "debate",
                    "config": {"proposers": ("prop_x", "prop_y")},
                }
            },
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        run_kinds = [c["run_kind"] for c in agent.calls]
        # analyzer: 1 call (agent kind).
        # implementer: nested debate = 3 calls (prop_x, prop_y, judge).
        # tester: 1 call (agent kind).
        # Total: 5 calls.
        self.assertEqual(len(agent.calls), 5)
        self.assertEqual(run_kinds[0], "pipeline:analyzer")
        # The nested Debate sub-runner writes its own run_kind format
        # (debate:proposer / debate:judge), NOT prefixed with pipeline:*.
        # That's intentional so nested-mode transcripts read cleanly.
        self.assertIn("debate:prop_x", run_kinds)
        self.assertIn("debate:prop_y", run_kinds)
        self.assertIn("debate:judge", run_kinds)
        self.assertEqual(run_kinds[-1], "pipeline:tester")

    def test_coordinator_kind_stage_toggles_coordinator_mode(self) -> None:
        # coordinator kind wraps AgentRunner.run in a coordinator_mode
        # try/finally toggle (via CoordinatorModeRunner).
        agent = _StubAgentRunner()
        agent.agent_config.coordinator_mode = False
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "impl_coord"),
            stage_specs={"impl_coord": {"kind": "coordinator"}},
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # 2 calls total (1 agent + 1 coordinator wrapping AgentRunner).
        self.assertEqual(len(agent.calls), 2)
        # analyzer sees coordinator_mode=False (not set for it).
        self.assertFalse(agent.calls[0]["coordinator_mode_at_entry"])
        # impl_coord sees coordinator_mode=True (Coordinator runner set it).
        self.assertTrue(agent.calls[1]["coordinator_mode_at_entry"])
        # Restored after runner returns.
        self.assertFalse(agent.agent_config.coordinator_mode)

    def test_nested_pipeline_rejected_at_construction(self) -> None:
        # Guarding against the infinite-recursion trap.
        with self.assertRaises(ValueError) as ctx:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer",),
                stage_specs={"analyzer": {"kind": "pipeline"}},
            )
        self.assertIn("pipeline", str(ctx.exception).lower())

    def test_unknown_kind_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer",),
                stage_specs={"analyzer": {"kind": "magic-orchestration"}},
            )

    def test_stage_specs_unknown_stage_warns(self) -> None:
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="WARNING"
        ) as cm:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer",),
                stage_specs={"nonexistent_stage": {"kind": "debate"}},
            )
        joined = "\n".join(cm.output)
        self.assertIn("stage_specs has unknown keys", joined)
        self.assertIn("nonexistent_stage", joined)

    def test_debate_config_forwarded_to_sub_runner(self) -> None:
        # judge_mode=synthesize should reach the nested Debate.
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("implementer",),
            stage_specs={
                "implementer": {
                    "kind": "debate",
                    "config": {
                        "proposers": ("p1", "p2"),
                        "judge_mode": "synthesize",
                    },
                }
            },
        )
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Judge should have been called with the synthesize-mode prompt.
        judge_prompt = agent.calls[-1]["prompt"]
        self.assertIn("SYNTHESIZE mode", judge_prompt)


class TestSchemaRound7Parsing(unittest.TestCase):
    def setUp(self) -> None:
        from extensions.orchestrator.config.schema import _parse_modes_config

        self._parse = _parse_modes_config

    def test_stage_specs_default_empty(self) -> None:
        cfg = self._parse({})
        self.assertEqual(cfg.pipeline_stage_specs, {})

    def test_stage_specs_parsed(self) -> None:
        cfg = self._parse({
            "pipeline": {
                "stage_specs": {
                    "implementer": {
                        "kind": "debate",
                        "config": {"proposers": ["a", "b"]},
                    }
                }
            }
        })
        self.assertEqual(
            cfg.pipeline_stage_specs,
            {
                "implementer": {
                    "kind": "debate",
                    "config": {"proposers": ["a", "b"]},
                }
            },
        )

    def test_stage_specs_unknown_kind_dropped_with_warn(self) -> None:
        with self.assertLogs(
            "extensions.orchestrator.config.schema", level="WARNING"
        ) as cm:
            cfg = self._parse({
                "pipeline": {
                    "stage_specs": {"implementer": {"kind": "quantum"}}
                }
            })
        joined = "\n".join(cm.output)
        self.assertIn("quantum", joined)
        # Bad entry is dropped, not silently kept.
        self.assertEqual(cfg.pipeline_stage_specs, {})

    def test_stage_specs_pipeline_kind_dropped_at_config_layer(self) -> None:
        # Config layer allows only agent/debate/coordinator. pipeline
        # would let the loader through but PipelineModeRunner would
        # then reject at construction. Belt-and-braces.
        cfg = self._parse({
            "pipeline": {
                "stage_specs": {"x": {"kind": "pipeline"}}
            }
        })
        self.assertEqual(cfg.pipeline_stage_specs, {})


class TestPipelineNestedEagerValidation(unittest.TestCase):
    """Sub-runners must be built at PipelineModeRunner __init__ so bad
    configs fail fast at daemon startup — NOT partway through an
    issue run when the nested stage is finally reached."""

    def test_bad_debate_config_raises_at_pipeline_construction(self) -> None:
        # Debate with parallel=True requires isolation=worktree. Setting
        # both parallel=True + isolation=reset is a valid-looking config
        # that DebateModeRunner rejects. This error MUST surface at
        # Pipeline __init__ time, not at run() time.
        with self.assertRaises(ValueError) as ctx:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer", "impl"),
                stage_specs={
                    "impl": {
                        "kind": "debate",
                        "config": {
                            "parallel": True,
                            "isolation": "reset",
                        },
                    }
                },
            )
        msg = str(ctx.exception).lower()
        self.assertIn("impl", msg)
        self.assertIn("debate", msg)
        # The original Debate error message about worktree requirement
        # must be preserved in the chain.
        self.assertIn("worktree", msg)

    def test_sub_runner_cached_and_reused_across_retries(self) -> None:
        # A stage that fails + retries should NOT re-construct the
        # sub-runner (would be wasteful + repeat any constructor warnings).
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer",),
            stage_specs={
                "analyzer": {
                    "kind": "debate",
                    "config": {"proposers": ("a",)},
                }
            },
            max_retries_per_stage=1,
        )
        # There should be exactly ONE cached sub-runner for analyzer.
        self.assertIn("analyzer", runner._nested_runner_cache)
        cached_before = runner._nested_runner_cache["analyzer"]
        # Trigger a run — the cache should hand out the same instance.
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        cached_after = runner._nested_runner_cache["analyzer"]
        self.assertIs(cached_before, cached_after)

    def test_agent_kind_with_config_warns_silent_no_op(self) -> None:
        # kind=agent + non-empty config = wired-something-that-never-fires.
        # Warn loudly at construction so the operator doesn't debug
        # phantom problems for 30 minutes.
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="WARNING"
        ) as cm:
            PipelineModeRunner(
                _StubAgentRunner(),
                stages=("analyzer",),
                stage_specs={
                    "analyzer": {
                        "kind": "agent",
                        "config": {"proposers": ("x", "y")},
                    }
                },
            )
        joined = "\n".join(cm.output)
        self.assertIn("kind=agent", joined)
        self.assertIn("IGNORED", joined)

    def test_handoff_label_reflects_delegation_in_log(self) -> None:
        # When a stage is nested (kind=debate), the log should NOT
        # display the Pipeline's handoff mode as if it applied — sub-runner
        # doesn't use it. Show "(delegated to debate)" instead.
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(
            agent,
            stages=("analyzer", "impl"),
            stage_specs={
                "impl": {
                    "kind": "debate",
                    "config": {"proposers": ("a",)},
                }
            },
            handoff="mailbox",  # Pipeline uses mailbox for its own stages
        )
        session = _make_session()
        session.workspace.path = "/tmp/whatever"
        with self.assertLogs(
            "extensions.orchestrator.modes.pipeline", level="INFO"
        ) as cm:
            asyncio.run(runner.run(session, MagicMock()))
        joined = "\n".join(cm.output)
        # Plain agent stage shows the actual handoff mode:
        self.assertIn("stage=analyzer", joined)
        self.assertIn("handoff=mailbox", joined)
        # Nested stage shows the delegation label instead:
        self.assertIn("handoff=(delegated to debate)", joined)

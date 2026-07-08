"""Phase-2 unit tests: HeuristicRouter, LLMRouter stub, PipelineModeRunner,
ModeSelector router integration, and ModesConfig YAML parsing.

These tests verify the new abstractions without spinning up a full
Orchestrator. The 270+ existing orchestrator integration tests keep
passing because Phase 2 defaults preserve byte-identical behavior
(``modes.enabled=["single"]``, ``router_kind="none"``).
"""

from __future__ import annotations

import asyncio
import os
import unittest
from typing import Any
from unittest.mock import MagicMock

from extensions.orchestrator import modes as mode_registry
from extensions.orchestrator.config.schema import (
    ModesConfig,
    WorkflowConfig,
    _parse_modes_config,
)
from extensions.orchestrator.mode_router import (
    HeuristicRouter,
    LLMRouter,
    Router,
    RouterResult,
)
from extensions.orchestrator.mode_selector import (
    KNOWN_MODES,
    ModeSelector,
)
from extensions.orchestrator.modes.base import DEFAULT_MODE, ModeDecision
from extensions.orchestrator.modes.pipeline import PipelineModeRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeIssue:
    """Minimal Issue stand-in — Router / selector only read these fields."""

    def __init__(
        self,
        *,
        labels: list[str] | None = None,
        title: str = "",
        description: str = "",
        id: str = "ISSUE-1",
    ) -> None:
        self.labels = labels or []
        self.title = title
        self.description = description
        self.id = id


# ---------------------------------------------------------------------------
# HeuristicRouter
# ---------------------------------------------------------------------------


class TestHeuristicRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.router = HeuristicRouter()

    def test_debate_keyword_in_title(self) -> None:
        result = self.router.choose(_FakeIssue(title="Design new caching layer", description=""))
        self.assertEqual(result.mode, "debate")
        self.assertGreaterEqual(result.confidence, 0.5)
        self.assertIn("design", result.reason)

    def test_coordinator_keyword_in_title(self) -> None:
        result = self.router.choose(_FakeIssue(title="Refactor auth module", description=""))
        self.assertEqual(result.mode, "coordinator")

    def test_pipeline_keyword_in_title(self) -> None:
        result = self.router.choose(_FakeIssue(title="Implement OAuth login flow", description=""))
        self.assertEqual(result.mode, "pipeline")

    def test_fallback_when_no_keywords(self) -> None:
        result = self.router.choose(_FakeIssue(title="Fix typo in README", description=""))
        self.assertEqual(result.mode, "single")
        # Low confidence so ModeSelector falls back.
        self.assertLess(result.confidence, 0.5)

    def test_keyword_in_description(self) -> None:
        # No keyword in title; only in body.
        result = self.router.choose(
            _FakeIssue(
                title="Task",
                description="We need to investigate and decide between A and B.",
            )
        )
        self.assertEqual(result.mode, "debate")

    def test_first_category_wins_when_multiple_match(self) -> None:
        # Description has both a debate keyword AND a pipeline keyword.
        # The order in HeuristicRouter is: debate → coordinator → pipeline.
        result = self.router.choose(
            _FakeIssue(
                title="Implement",
                description="We need to design this carefully",
            )
        )
        self.assertEqual(result.mode, "debate")

    def test_satisfies_router_protocol(self) -> None:
        self.assertIsInstance(self.router, Router)


# ---------------------------------------------------------------------------
# LLMRouter — real HTTP call (mocked) to OpenAI-compatible endpoint
# ---------------------------------------------------------------------------


class _StubHttpResponse:
    def __init__(self, *, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._body


class _StubHttpClient:
    """Mock httpx.Client matching the surface LLMRouter._post uses."""

    def __init__(self, *, response: Any = None, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, headers: dict) -> _StubHttpResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.raise_exc:
            raise self.raise_exc
        return self.response


def _make_openai_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class TestLLMRouter(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure API key is present so the env-var guard passes.
        self._old_key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "test-key"

    def tearDown(self) -> None:
        if self._old_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key

    def test_satisfies_router_protocol(self) -> None:
        self.assertIsInstance(LLMRouter(), Router)

    def test_picks_mode_from_json_response(self) -> None:
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response(
                    '{"mode": "pipeline", "reason": "needs design then impl", "confidence": 0.85}'
                )
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="Implement OAuth", description=""))
        self.assertEqual(result.mode, "pipeline")
        self.assertEqual(result.confidence, 0.85)
        self.assertIn("needs design", result.reason)
        # Verify the call shape (one POST, Authorization header, model name).
        self.assertEqual(len(stub.calls), 1)
        call = stub.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call["json"]["temperature"], 0.0)
        self.assertEqual(len(call["json"]["messages"]), 2)
        # User message must contain the issue title.
        self.assertIn("Implement OAuth", call["json"]["messages"][1]["content"])

    def test_strips_code_fences_around_json(self) -> None:
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response(
                    "```json\n"
                    '{"mode": "debate", "reason": "design question", "confidence": 0.7}\n'
                    "```"
                )
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "debate")

    def test_missing_api_key_falls_back(self) -> None:
        del os.environ["DEEPSEEK_API_KEY"]
        # No http_client passed — guaranteed no network call because the
        # env-var guard fires before any HTTP code runs.
        router = LLMRouter()
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "single")
        self.assertLess(result.confidence, 0.5)
        self.assertIn("DEEPSEEK_API_KEY", result.reason)

    def test_http_error_falls_back(self) -> None:
        stub = _StubHttpClient(raise_exc=RuntimeError("connection refused"))
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "single")
        self.assertLess(result.confidence, 0.5)
        self.assertIn("RuntimeError", result.reason)

    def test_non_json_response_falls_back(self) -> None:
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response("Sure! I think pipeline is best.")
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "single")
        self.assertLess(result.confidence, 0.5)
        self.assertIn("non-JSON", result.reason)

    def test_unknown_mode_in_json_falls_back(self) -> None:
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response(
                    '{"mode": "magic", "reason": "vibes", "confidence": 0.99}'
                )
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "single")
        self.assertIn("unknown mode", result.reason)

    def test_confidence_clamped_to_unit_interval(self) -> None:
        # Model claims 1.5 confidence; LLMRouter clamps to 1.0.
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response(
                    '{"mode": "coordinator", "reason": "ok", "confidence": 1.5}'
                )
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.confidence, 1.0)

    def test_malformed_confidence_uses_default(self) -> None:
        stub = _StubHttpClient(
            response=_StubHttpResponse(
                body=_make_openai_response(
                    '{"mode": "single", "reason": "trivial", "confidence": "high"}'
                )
            )
        )
        router = LLMRouter(http_client=stub)
        result = router.choose(_FakeIssue(title="anything"))
        self.assertEqual(result.mode, "single")
        self.assertEqual(result.confidence, 0.5)

    def test_default_model_is_deepseek(self) -> None:
        # The default is what workflow.md falls back to when modes.router.model
        # is unset. Keeping this in lockstep with ModesConfig is load-bearing.
        router = LLMRouter()
        self.assertEqual(router._model, "deepseek-v4-flash")
        self.assertIn("deepseek", router._endpoint)
        self.assertEqual(router._api_key_env_var, "DEEPSEEK_API_KEY")


# ---------------------------------------------------------------------------
# ModeSelector + Router integration
# ---------------------------------------------------------------------------


class _StubRouter:
    """A fully-controllable Router for testing ModeSelector wiring."""

    def __init__(self, result: RouterResult | None = None, raise_exc: bool = False) -> None:
        self.result = result
        self.raise_exc = raise_exc
        self.choose_calls: list[Any] = []

    def choose(self, issue: Any) -> RouterResult:
        self.choose_calls.append(issue)
        if self.raise_exc:
            raise RuntimeError("router boom")
        assert self.result is not None
        return self.result


class TestModeSelectorWithRouter(unittest.TestCase):
    def test_router_consulted_when_no_label(self) -> None:
        router = _StubRouter(RouterResult(mode="pipeline", reason="kw match", confidence=0.8))
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, "pipeline")
        self.assertEqual(decision.source, "router")
        self.assertEqual(decision.reason, "kw match")
        self.assertEqual(decision.confidence, 0.8)
        self.assertEqual(len(router.choose_calls), 1)

    def test_router_consulted_for_auto_label(self) -> None:
        router = _StubRouter(
            RouterResult(mode="coordinator", reason="multi-module", confidence=0.7)
        )
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue(labels=["mode:auto"]))
        self.assertEqual(decision.mode, "coordinator")
        self.assertEqual(decision.source, "router")
        self.assertEqual(len(router.choose_calls), 1)

    def test_explicit_label_skips_router(self) -> None:
        router = _StubRouter(RouterResult(mode="pipeline", reason="kw", confidence=0.9))
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue(labels=["mode:debate"]))
        self.assertEqual(decision.mode, "debate")
        self.assertEqual(decision.source, "label")
        # Router NOT consulted — explicit label wins.
        self.assertEqual(len(router.choose_calls), 0)

    def test_router_raising_falls_back(self) -> None:
        router = _StubRouter(raise_exc=True)
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, DEFAULT_MODE)
        self.assertEqual(decision.source, "fallback")
        self.assertIn("router raised", decision.reason)

    def test_router_low_confidence_falls_back(self) -> None:
        router = _StubRouter(RouterResult(mode="pipeline", reason="weak hit", confidence=0.2))
        selector = ModeSelector(router=router, min_confidence=0.5)
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, DEFAULT_MODE)
        self.assertEqual(decision.source, "fallback")
        self.assertIn("confidence", decision.reason)

    def test_router_returns_unknown_mode_falls_back(self) -> None:
        router = _StubRouter(RouterResult(mode="wizardry", reason="?", confidence=0.99))
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, DEFAULT_MODE)
        self.assertEqual(decision.source, "fallback")

    def test_router_returns_auto_treated_as_unknown(self) -> None:
        router = _StubRouter(RouterResult(mode="auto", reason="recursing!", confidence=0.99))
        selector = ModeSelector(router=router)
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, DEFAULT_MODE)

    def test_no_router_no_label_returns_default(self) -> None:
        selector = ModeSelector()  # no router
        decision = selector.choose(_FakeIssue())
        self.assertEqual(decision.mode, DEFAULT_MODE)
        self.assertEqual(decision.source, "fallback")
        self.assertIn("no router", decision.reason.lower())

    def test_invalid_min_confidence_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ModeSelector(min_confidence=1.5)
        with self.assertRaises(ValueError):
            ModeSelector(min_confidence=-0.1)


# ---------------------------------------------------------------------------
# PipelineModeRunner
# ---------------------------------------------------------------------------


class _StubAgentRunner:
    """Records calls and simulates AgentRunner.run side effects on the session."""

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail_after = fail_after

    async def run(self, session: Any, workflow: Any, **hooks: Any) -> None:
        self.calls.append(
            {
                "prompt": session.prompt_override,
                "run_kind": session.run_kind,
                "run_id": session.run_id,
                "turn_count_at_entry": session.turn_count,
            }
        )
        # Simulate the agent running a few turns and producing output.
        session.turn_count = 4
        session.output_text = f"Output of {session.run_kind}"
        # Pretend each stage assigned itself a run_id (AgentRunner.run does this in production).
        if session.run_id is None:
            session.run_id = f"run-{len(self.calls)}"

        if self._fail_after is not None and len(self.calls) > self._fail_after:
            session.status = "stagnation"
        else:
            session.status = "completed"


def _make_session() -> Any:
    """Build a minimal session-shaped object PipelineModeRunner expects."""
    session = MagicMock(name="AgentSession")
    session.issue = MagicMock()
    session.issue.id = "ISSUE-1"
    session.issue.title = "Test"
    session.issue.description = "Hello"
    session.run_kind = "issue"
    session.run_id = None
    session.turn_count = 0
    session.status = "running"
    session.output_text = ""
    session.session_end_reason = None
    session.session_end_summary = ""
    session.consecutive_429_count = 0
    session.rate_limit_pending_turn = None
    session.prompt_override = None
    return session


class TestPipelineModeRunner(unittest.TestCase):
    def test_runs_all_stages_in_order(self) -> None:
        runner = PipelineModeRunner(_StubAgentRunner())
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        self.assertEqual([r.stage for r in results], list(runner.stages))
        self.assertEqual([r.status for r in results], ["completed"] * 3)

    def test_resets_session_state_between_stages(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Each call must have observed turn_count==0 at entry (we reset
        # it before invoking the runner each time).
        self.assertEqual(
            [c["turn_count_at_entry"] for c in agent.calls],
            [0, 0, 0],
        )

    def test_forces_new_run_id_per_stage(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Each call must have observed run_id==None at entry — we
        # explicitly clear it so AgentRunner.run generates a fresh one.
        self.assertEqual([c["run_id"] for c in agent.calls], [None, None, None])

    def test_run_kind_per_stage(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        self.assertEqual(
            [c["run_kind"] for c in agent.calls],
            ["pipeline:analyzer", "pipeline:implementer", "pipeline:tester"],
        )

    def test_prior_output_injected_into_next_stage_prompt(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Stage 1 is the analyzer — its hard-coded template doesn't
        # interpolate ``{prior}`` because the analyzer is always first
        # in the default pipeline. That's intentional: prompt clarity
        # beats a useless "(no prior stages)" line.
        self.assertNotIn("Output of pipeline:", agent.calls[0]["prompt"])
        # Stage 2's prompt references stage 1's stage name and output.
        self.assertIn("analyzer", agent.calls[1]["prompt"])
        self.assertIn("Output of pipeline:analyzer", agent.calls[1]["prompt"])
        # Stage 3's prompt references both prior stages.
        self.assertIn("analyzer", agent.calls[2]["prompt"])
        self.assertIn("implementer", agent.calls[2]["prompt"])

    def test_stage_prompt_includes_issue_block(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        for call in agent.calls:
            self.assertIn("## Issue", call["prompt"])
            self.assertIn("Title: Test", call["prompt"])

    def test_aborts_on_terminal_failure_no_retry(self) -> None:
        # ``fail_after=1`` → first call succeeds, every later call fails.
        # max_retries_per_stage=0 disables the retry path so the legacy
        # "fail-once-and-abort" behavior is what we assert here.
        agent = _StubAgentRunner(fail_after=1)
        runner = PipelineModeRunner(agent, max_retries_per_stage=0)
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        # Stage 1 completed, stage 2 failed → pipeline aborts. Stage 3 never runs.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, "completed")
        self.assertEqual(results[1].status, "stagnation")
        self.assertEqual(len(agent.calls), 2)

    def test_retries_failed_stage_then_aborts_if_still_failing(self) -> None:
        # Default max_retries_per_stage=1. Stage 2 fails on first attempt,
        # gets retried once, fails again → abort. Stage 3 never runs.
        # Expected call count: stage1(1) + stage2(1) + stage2_retry(1) = 3.
        agent = _StubAgentRunner(fail_after=1)
        runner = PipelineModeRunner(agent)  # default max_retries_per_stage=1
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, "completed")
        self.assertEqual(results[1].status, "stagnation")
        self.assertEqual(len(agent.calls), 3)
        # Retry call must carry the retry note in its prompt.
        retry_prompt = agent.calls[2]["prompt"]
        self.assertIn("Retry context", retry_prompt)
        self.assertIn("Attempt 1", retry_prompt)
        self.assertIn("stagnation", retry_prompt)
        # Retry call's run_kind should be tagged.
        self.assertEqual(agent.calls[2]["run_kind"], "pipeline:implementer:retry1")

    def test_retry_success_continues_pipeline(self) -> None:
        # First attempt of stage 2 fails, retry succeeds → stage 3 runs.
        class _RetryAgent:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def run(self, session: Any, workflow: Any, **hooks: Any) -> None:
                self.calls.append({"run_kind": session.run_kind, "prompt": session.prompt_override})
                session.turn_count = 4
                session.output_text = f"out:{session.run_kind}"
                if session.run_id is None:
                    session.run_id = f"run-{len(self.calls)}"
                # Fail ONLY first attempt of stage 2.
                if session.run_kind == "pipeline:implementer":
                    session.status = "stagnation"
                else:
                    session.status = "completed"

        agent = _RetryAgent()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        # All 3 stages eventually succeed. Total agent calls: stage1 + stage2 fail + stage2 retry success + stage3 = 4.
        self.assertEqual(len(results), 3)
        self.assertEqual([r.stage for r in results], ["analyzer", "implementer", "tester"])
        self.assertEqual(len(agent.calls), 4)
        # Final result for stage 2 must be the SUCCESS, not the failure.
        self.assertEqual(results[1].status, "completed")

    def test_invalid_max_retries_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PipelineModeRunner(_StubAgentRunner(), max_retries_per_stage=-1)

    def test_empty_stages_list_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PipelineModeRunner(_StubAgentRunner(), stages=())

    def test_read_only_loop_does_not_abort_pipeline(self) -> None:
        """An analyzer-style stage that exits with ``read_only_loop``
        (it read files and produced a plan but never edited) must NOT
        abort the pipeline — the next stage still gets to act on the plan.
        Regression: live e2e run on h144 showed analyzer hitting this
        status with default max_turns and the pipeline aborted before
        implementer ran. Fix in modes/pipeline.py:_stage_succeeded.
        """

        class _ReadOnlyAgent:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def run(self, session: Any, workflow: Any, **hooks: Any) -> None:
                self.calls.append(session.run_kind)
                session.turn_count = 4
                session.output_text = f"out:{session.run_kind}"
                # First stage exits with read_only_loop (analyzer
                # finished planning without edits); later stages run normal.
                if session.run_kind == "pipeline:analyzer":
                    session.status = "read_only_loop"
                else:
                    session.status = "completed"
                if session.run_id is None:
                    session.run_id = f"run-{len(self.calls)}"

        agent = _ReadOnlyAgent()
        runner = PipelineModeRunner(agent)
        session = _make_session()
        results = asyncio.run(runner.run(session, MagicMock()))
        # All 3 stages must run despite stage 1's read_only_loop exit.
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].status, "read_only_loop")
        self.assertEqual(results[1].status, "completed")
        self.assertEqual(results[2].status, "completed")
        self.assertEqual(
            [c for c in agent.calls],
            ["pipeline:analyzer", "pipeline:implementer", "pipeline:tester"],
        )

    def test_custom_stage_names_use_generic_template(self) -> None:
        agent = _StubAgentRunner()
        runner = PipelineModeRunner(agent, stages=("scout", "builder"))
        session = _make_session()
        asyncio.run(runner.run(session, MagicMock()))
        # Generic template uppercases the stage name and uses "[STAGE DONE]" sentinel.
        self.assertIn("SCOUT", agent.calls[0]["prompt"])
        self.assertIn("BUILDER", agent.calls[1]["prompt"])


# ---------------------------------------------------------------------------
# ModesConfig YAML parsing
# ---------------------------------------------------------------------------


class TestModesConfigParsing(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = _parse_modes_config({})
        self.assertEqual(cfg.enabled, ["single"])
        self.assertEqual(cfg.default, "single")
        self.assertEqual(cfg.router_kind, "none")
        self.assertEqual(cfg.router_min_confidence, 0.5)
        self.assertEqual(cfg.pipeline_stages, ["analyzer", "implementer", "tester"])

    def test_full_config(self) -> None:
        cfg = _parse_modes_config(
            {
                "enabled": ["single", "pipeline"],
                "default": "pipeline",
                "router": {
                    "kind": "heuristic",
                    "model": "model-b",
                    "min_confidence": 0.7,
                },
                "pipeline": {"stages": ["a", "b"]},
            }
        )
        self.assertEqual(cfg.enabled, ["single", "pipeline"])
        self.assertEqual(cfg.default, "pipeline")
        self.assertEqual(cfg.router_kind, "heuristic")
        self.assertEqual(cfg.router_min_confidence, 0.7)
        self.assertEqual(cfg.pipeline_stages, ["a", "b"])

    def test_unknown_router_kind_coerced_to_none(self) -> None:
        cfg = _parse_modes_config({"router": {"kind": "magic"}})
        self.assertEqual(cfg.router_kind, "none")

    def test_min_confidence_clamped(self) -> None:
        cfg = _parse_modes_config({"router": {"min_confidence": 5.0}})
        self.assertEqual(cfg.router_min_confidence, 1.0)
        cfg = _parse_modes_config({"router": {"min_confidence": -0.5}})
        self.assertEqual(cfg.router_min_confidence, 0.0)

    def test_garbage_min_confidence_uses_default(self) -> None:
        cfg = _parse_modes_config({"router": {"min_confidence": "not a float"}})
        self.assertEqual(cfg.router_min_confidence, 0.5)

    def test_workflow_config_has_default_modes(self) -> None:
        wf = WorkflowConfig.from_dict({})
        self.assertIsInstance(wf.modes, ModesConfig)
        self.assertEqual(wf.modes.enabled, ["single"])

    def test_workflow_config_parses_modes_section(self) -> None:
        wf = WorkflowConfig.from_dict(
            {
                "modes": {
                    "enabled": ["single", "pipeline"],
                    "router": {"kind": "heuristic"},
                }
            }
        )
        self.assertEqual(wf.modes.enabled, ["single", "pipeline"])
        self.assertEqual(wf.modes.router_kind, "heuristic")


# ---------------------------------------------------------------------------
# Orchestrator-level wiring (registration + selector build)
# ---------------------------------------------------------------------------


class TestOrchestratorModeWiring(unittest.TestCase):
    """We don't spin up a full Orchestrator (heavy deps); we test the
    two new helpers in isolation by attaching them to a stub object."""

    def setUp(self) -> None:
        mode_registry._registry.clear()

    def _stub_orchestrator(self) -> Any:
        # The two helpers use `self` only for ``logger`` (module-level)
        # — we don't need a real Orchestrator instance.
        from extensions.orchestrator.orchestrator import Orchestrator

        return Orchestrator

    def test_register_default_only(self) -> None:
        Orch = self._stub_orchestrator()
        # Construct a minimal stub with just the methods we need.
        instance = MagicMock(spec=["_register_collaboration_modes"])
        Orch._register_collaboration_modes(
            instance,
            workflow=WorkflowConfig.from_dict({}),
            agent_runner=MagicMock(),
        )
        self.assertIn("single", mode_registry.available())
        self.assertNotIn("pipeline", mode_registry.available())

    def test_register_pipeline_when_enabled(self) -> None:
        Orch = self._stub_orchestrator()
        instance = MagicMock(spec=["_register_collaboration_modes"])
        Orch._register_collaboration_modes(
            instance,
            workflow=WorkflowConfig.from_dict({"modes": {"enabled": ["single", "pipeline"]}}),
            agent_runner=MagicMock(),
        )
        self.assertEqual(sorted(mode_registry.available()), ["pipeline", "single"])

    def test_build_selector_with_heuristic_router(self) -> None:
        Orch = self._stub_orchestrator()
        instance = MagicMock(spec=["_build_mode_selector"])
        selector = Orch._build_mode_selector(
            instance,
            workflow=WorkflowConfig.from_dict({"modes": {"router": {"kind": "heuristic"}}}),
        )
        self.assertIsInstance(selector, ModeSelector)
        # Smoke: router does its thing.
        decision = selector.choose(_FakeIssue(title="Refactor auth module"))
        self.assertEqual(decision.mode, "coordinator")
        self.assertEqual(decision.source, "router")

    def test_build_selector_with_no_router(self) -> None:
        Orch = self._stub_orchestrator()
        instance = MagicMock(spec=["_build_mode_selector"])
        selector = Orch._build_mode_selector(instance, workflow=WorkflowConfig.from_dict({}))
        decision = selector.choose(_FakeIssue(title="Refactor auth"))
        # No router → never selects "coordinator" even though the title would match.
        self.assertEqual(decision.mode, "single")


if __name__ == "__main__":
    unittest.main()

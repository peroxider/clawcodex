"""Tests for the repro-first gate (reproduce before fixing)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from extensions.orchestrator.config.schema import (
    AgentConfig,
    ReproFirstConfig,
    _parse_repro_first_config,
)
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.orchestrator.repro_gate import (
    NOT_REPRODUCIBLE_FILE,
    REPRO_COMMAND_FILE,
    ReproGateResult,
    append_repro_hint,
    build_repro_prompt,
    evaluate_repro_gate,
    format_repro_gate_comment,
)


class _Issue:
    def __init__(self, labels: list[str] | None = None) -> None:
        self.id = "19"
        self.identifier = "PROBE-19"
        self.title = "Crash in retry backoff"
        self.description = "timeout=0 causes ZeroDivisionError"
        self.labels = labels or []


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _exit_script(root: Path, code: int) -> str:
    _write(root, ".orchestrator_control/repro/check.py", f"import sys\nsys.exit({code})\n")
    return f'"{sys.executable}" .orchestrator_control/repro/check.py'


class TestBuildReproPrompt(unittest.TestCase):
    def test_prompt_states_the_contract(self) -> None:
        prompt = build_repro_prompt(_Issue())
        self.assertIn("PROBE-19", prompt)
        self.assertIn(REPRO_COMMAND_FILE, prompt)
        self.assertIn(NOT_REPRODUCIBLE_FILE, prompt)
        self.assertIn("NON-ZERO", prompt)
        self.assertIn("Do NOT fix anything", prompt)


class TestEvaluateReproGate(unittest.IsolatedAsyncioTestCase):
    async def test_no_artifacts_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "missing")
            self.assertFalse(result.proceed)

    async def test_not_reproducible_report_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                NOT_REPRODUCIBLE_FILE,
                json.dumps({"reason": "file does not exist", "attempts": ["grep", "git log"]}),
            )
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "not_reproducible")
            assert result.payload is not None
            self.assertEqual(result.payload["reason"], "file does not exist")

    async def test_malformed_report_still_closes_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), NOT_REPRODUCIBLE_FILE, "not json at all")
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "not_reproducible")

    async def test_failing_command_opens_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = _exit_script(root, 1)
            _write(root, REPRO_COMMAND_FILE, command + "\n")
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "reproduced")
            self.assertTrue(result.proceed)
            self.assertEqual(result.command, command)

    async def test_green_command_is_not_a_demonstration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = _exit_script(root, 0)
            _write(root, REPRO_COMMAND_FILE, command + "\n")
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "not_demonstrated")
            self.assertFalse(result.proceed)

    async def test_comment_only_command_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), REPRO_COMMAND_FILE, "# TODO figure it out\n\n")
            result = await evaluate_repro_gate(tmp)
            self.assertEqual(result.verdict, "missing")


class TestReproHint(unittest.TestCase):
    def test_hint_created_and_appended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_repro_hint(root, "pytest tests/test_probe.py -q")
            hints = (root / ".operator_hints.md").read_text(encoding="utf-8")
            self.assertIn("Reproduction established", hints)
            self.assertIn("pytest tests/test_probe.py -q", hints)

            (root / ".operator_hints.md").write_text("existing operator note\n", encoding="utf-8")
            append_repro_hint(root, "make repro")
            hints = (root / ".operator_hints.md").read_text(encoding="utf-8")
            self.assertTrue(hints.startswith("existing operator note"))
            self.assertIn("make repro", hints)


class TestGateComment(unittest.TestCase):
    def test_not_reproducible_comment_lists_attempts(self) -> None:
        comment = format_repro_gate_comment(
            _Issue(),
            ReproGateResult(
                verdict="not_reproducible",
                payload={"reason": "no such file", "attempts": ["grep -r", "read docs"]},
            ),
        )
        self.assertIn("PROBE-19", comment)
        self.assertIn("no such file", comment)
        self.assertIn("- grep -r", comment)
        self.assertIn("No fix was attempted", comment)

    def test_not_demonstrated_comment_shows_command(self) -> None:
        comment = format_repro_gate_comment(
            _Issue(),
            ReproGateResult(verdict="not_demonstrated", command="pytest -q", output="all green"),
        )
        self.assertIn("exits 0", comment)
        self.assertIn("pytest -q", comment)


class TestConfigParsing(unittest.TestCase):
    def test_defaults_disabled(self) -> None:
        config = _parse_repro_first_config({})
        self.assertFalse(config.enabled)
        self.assertEqual(AgentConfig().repro_first.enabled, False)

    def test_full_section(self) -> None:
        config = _parse_repro_first_config(
            {
                "enabled": True,
                "timeout_ms": 60_000,
                "command_timeout_ms": 5_000,
                "labels": ["bug", "Regression"],
            }
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.timeout_ms, 60_000)
        self.assertEqual(config.command_timeout_ms, 5_000)
        self.assertEqual(config.labels, ["bug", "Regression"])

    def test_malformed_section_falls_back(self) -> None:
        config = _parse_repro_first_config("yes please")
        self.assertFalse(config.enabled)
        config = _parse_repro_first_config({"timeout_ms": "soon"})
        self.assertEqual(config.timeout_ms, 900_000)


class _GateSelf:
    """Minimal stand-in for Orchestrator in _repro_gate_applies."""

    class _Agent:
        pass

    class _Workflow:
        pass

    def __init__(self, config: ReproFirstConfig) -> None:
        self.workflow = self._Workflow()
        self.workflow.agent = self._Agent()
        self.workflow.agent.repro_first = config


class _GateSession:
    def __init__(self, run_kind: str = "issue", labels: list[str] | None = None) -> None:
        self.run_kind = run_kind
        self.issue = _Issue(labels=labels)


class TestGateApplies(unittest.TestCase):
    def test_disabled_never_applies(self) -> None:
        self_stub = _GateSelf(ReproFirstConfig(enabled=False))
        self.assertFalse(Orchestrator._repro_gate_applies(self_stub, _GateSession()))

    def test_enabled_applies_to_issue_runs_only(self) -> None:
        self_stub = _GateSelf(ReproFirstConfig(enabled=True))
        self.assertTrue(Orchestrator._repro_gate_applies(self_stub, _GateSession()))
        self.assertFalse(
            Orchestrator._repro_gate_applies(
                self_stub, _GateSession(run_kind="agent_followup")
            )
        )

    def test_label_filter(self) -> None:
        self_stub = _GateSelf(ReproFirstConfig(enabled=True, labels=["bug"]))
        self.assertTrue(
            Orchestrator._repro_gate_applies(self_stub, _GateSession(labels=["Bug", "ui"]))
        )
        self.assertFalse(
            Orchestrator._repro_gate_applies(self_stub, _GateSession(labels=["feature"]))
        )


class TestReproGateRunner(unittest.IsolatedAsyncioTestCase):
    async def test_repro_stage_uses_gate_contract_instead_of_tracker_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = _exit_script(root, 1)
            _write(root, REPRO_COMMAND_FILE, command + "\n")

            tracker = object()
            agent_runner = SimpleNamespace(run=AsyncMock())
            workflow = SimpleNamespace(
                agent=SimpleNamespace(repro_first=ReproFirstConfig(enabled=True))
            )
            self_stub = SimpleNamespace(
                workflow=workflow,
                agent_runner=agent_runner,
                tracker=tracker,
                status_dashboard=MagicMock(),
                _clarification_resolver=object(),
                _update_run_diagnostics=MagicMock(),
            )
            session = SimpleNamespace(
                issue=_Issue(),
                workspace=SimpleNamespace(path=root),
                run_kind="issue",
                prompt_override=None,
                timeout_deadline_at=None,
                turn_count=0,
                status="running",
                output_text="",
                session_end_reason=None,
                session_end_summary="",
                run_id="run-repro",
                consecutive_429_count=0,
                rate_limit_pending_turn=None,
            )

            proceed = await Orchestrator._run_repro_gate(self_stub, session, None)

            self.assertTrue(proceed)
            call = agent_runner.run.await_args
            self.assertIsNone(call.kwargs["tracker"])
            self.assertIs(call.kwargs["comment_tracker"], tracker)
            self.assertEqual(session.repro_command, command)
            self.assertEqual(session.run_kind, "issue")


class TestGitSyncReproRecheck(unittest.IsolatedAsyncioTestCase):
    async def test_green_repro_command_passes_and_reports(self) -> None:
        from extensions.orchestrator.git_sync import GitSyncService

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = _exit_script(root, 0)

            class _Session:
                repro_command = command
                verification_status = None
                verification_output = None

            service = GitSyncService(_NullTracker())
            session = _Session()
            await service._run_pre_push_verification(str(root), session)
            self.assertEqual(session.verification_status, "skipped_no_tests")
            assert session.verification_output is not None
            self.assertIn("## repro", session.verification_output)

    async def test_red_repro_command_blocks_push(self) -> None:
        from extensions.orchestrator.git_sync import GitSyncService, VerificationFailed

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = _exit_script(root, 1)

            class _Session:
                repro_command = command
                verification_status = None
                verification_output = None

            service = GitSyncService(_NullTracker())
            with self.assertRaises(VerificationFailed) as ctx:
                await service._run_pre_push_verification(str(root), _Session())
            self.assertIn("still exits non-zero", str(ctx.exception))


class _NullTracker:
    """Duck-typed tracker stub (GitSyncService only stores it here)."""


if __name__ == "__main__":
    unittest.main()

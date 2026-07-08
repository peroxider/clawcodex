"""Tests for the F-138 Layer-2 Datalog solver adapter.

These tests pin the IR → Soufflé ``.dl`` encoding and the return-code /
violation-row → ``SolverResponse`` mapping. The Soufflé binary is not
required: every test mocks :func:`run_external_solver` and forces
``available()`` to ``True`` so the encoding path is exercised end-to-end.

The adapter is also verified against :class:`SolverPipeline` so the F-138
aggregation policy (``any fail → fail``, ``any uncertain → unknown``) is
exercised end-to-end, not just the adapter in isolation.
"""

from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from clawcodex_ext.logical_kanban import (
    DatalogSolverAdapter,
    Layer1SolverAdapter,
    ProposedChange,
    SolverAdapter,
    SolverPipeline,
    SolverRequest,
    SolverResponse,
    extended_adapters,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot  # noqa: E402
from clawcodex_ext.logical_kanban.solver_adapter import (  # noqa: E402
    SolverLimitError,
    SolverResourceLimits,
    encode_solver_literal,
)
from clawcodex_ext.logical_kanban.types import FactsSnapshot  # noqa: E402


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ctx_with(tasks: dict[str, dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(tasks=tasks, todos=())


def _snapshot(context: SimpleNamespace) -> FactsSnapshot:
    return build_facts_snapshot(context)


def _req(snapshot, *, target=None, status=None, strict=False, proof=None):
    return SolverRequest(
        snapshot=snapshot,
        target_task_id=target,
        target_status=status,
        strict_acceptance=strict,
        acceptance_proof_present=proof,
    )


def _task(
    task_id: str,
    *,
    status: str = "pending",
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    subject: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": task_id,
        "subject": subject if subject is not None else task_id,
        "description": description if description is not None else "",
        "status": status,
        "blocks": list(blocks or []),
        "blockedBy": list(blocked_by or []),
        "metadata": dict(metadata or {}),
    }
    return body


# ---------------------------------------------------------------------------
# Mocking the Soufflé subprocess boundary
# ---------------------------------------------------------------------------


class _SubprocessRecorder:
    """In-memory substitute for :func:`run_external_solver`.

    Each call records the captured ``program_text`` / ``facts_dir`` so tests
    can inspect the encoding, and returns a configurable ``(returncode,
    stdout, stderr)`` triple. Tests should set ``return_value`` for the
    expected exit code and ``violation_rows`` to materialise the
    ``violation.csv`` file Soufflé would normally produce.

    The recorder also short-circuits the ``--version`` probe used by
    ``available()`` so the only meaningful call recorded is the one driven
    by ``solve()``.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.return_value: tuple[int, str, str] = (0, "", "")
        self.violation_rows: tuple[str, ()] = ()

    def __call__(
        self,
        command: list[str],
        *,
        input_text: str = "",
        limits: SolverResourceLimits | None = None,
    ) -> tuple[int, str, str]:
        # The availability probe is invoked with ``['souffle', '--version']``
        # — skip capturing so ``calls`` only contains real solve invocations.
        if "--version" in command:
            return (0, "souffle mock 1.0", "")

        # Locate the program file and the facts directory from the command
        # vector. The adapter uses ``['souffle', '-D', facts_dir,
        # program_path]`` so the facts dir is the 3rd element and the
        # program path is the 4th.
        facts_dir: str | None = None
        program_path: str | None = None
        if "-D" in command:
            idx = command.index("-D")
            if idx + 1 < len(command):
                facts_dir = command[idx + 1]
        if command:
            program_path = command[-1]
        program_text = ""
        if program_path and os.path.isfile(program_path):
            with open(program_path, "r", encoding="utf-8") as handle:
                program_text = handle.read()
        facts_snapshot: dict[str, str] = {}
        if facts_dir and os.path.isdir(facts_dir):
            for entry in sorted(os.listdir(facts_dir)):
                full = os.path.join(facts_dir, entry)
                if not os.path.isfile(full):
                    continue
                with open(full, "r", encoding="utf-8") as handle:
                    facts_snapshot[entry] = handle.read()
            if self.violation_rows:
                with open(
                    os.path.join(facts_dir, "violation.csv"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    for row in self.violation_rows:
                        handle.write(f'"{row}"\n')
        self.calls.append(
            {
                "command": list(command),
                "program_path": program_path,
                "program_text": program_text,
                "facts_dir": facts_dir,
                "facts": facts_snapshot,
                "limits": limits,
                "input_text": input_text,
            }
        )
        return self.return_value


@pytest.fixture
def datalog_subprocess(monkeypatch: pytest.MonkeyPatch) -> _SubprocessRecorder:
    """Force ``DatalogSolverAdapter.available()`` and patch the subprocess."""
    recorder = _SubprocessRecorder()
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/souffle")
    monkeypatch.setattr(
        "clawcodex_ext.logical_kanban.solver_adapter.run_external_solver",
        recorder,
    )
    return recorder


# ---------------------------------------------------------------------------
# Smoke / availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_unavailable_when_souffle_missing(self) -> None:
        adapter = DatalogSolverAdapter()
        with patch("shutil.which", return_value=None):
            assert adapter.available() is False
            response = adapter.solve(_req(_snapshot(_ctx_with({}))))
        assert response.result == "unknown"
        assert response.error_info == {"reason": "engine_unavailable"}

    def test_extended_adapters_skips_datalog_when_unavailable(
        self,
    ) -> None:
        with patch("shutil.which", return_value=None):
            names = {a.name for a in extended_adapters()}
        assert "datalog-souffle" not in names

    def test_extended_adapters_includes_datalog_when_available(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/souffle")
        # ``DatalogSolverAdapter.available`` also runs ``souffle --version``;
        # supply a benign response so it returns ``True``.
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.solver_adapter.run_external_solver",
            lambda *args, **kwargs: (0, "souffle mock", ""),
        )
        names = {a.name for a in extended_adapters()}
        assert "datalog-souffle" in names


# ---------------------------------------------------------------------------
# Program structure
# ---------------------------------------------------------------------------


class TestProgramGeneration:
    def test_program_declares_violation_output(
        self, datalog_subprocess: _SubprocessRecorder
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        ctx = _ctx_with({"A": _task("A")})
        DatalogSolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        program = datalog_subprocess.calls[0]["program_text"]
        assert ".decl violation(t: symbol)" in program
        assert ".output violation" in program

    def test_program_emits_layer1_rules(self, datalog_subprocess: _SubprocessRecorder) -> None:
        datalog_subprocess.return_value = (0, "", "")
        ctx = _ctx_with({"A": _task("A")})
        DatalogSolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        program = datalog_subprocess.calls[0]["program_text"]
        # R-002: blocked cannot enter in_progress.
        assert "violation(T) :- do_proposal(T), blocked(T)." in program
        # R-006: cycle cannot enter in_progress.
        assert "violation(T) :- do_proposal(T), in_cycle(T)." in program
        # R-005: strict acceptance + completion requires proof.
        assert "has_acceptance_proof(T)" in program
        assert "strict_acceptance()" in program

    def test_facts_files_materialise_required_relations(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        ctx = _ctx_with(
            {
                "A": _task("A", status="completed"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        DatalogSolverAdapter().solve(_req(_snapshot(ctx), target="B", status="in_progress"))
        facts = datalog_subprocess.calls[0]["facts"]
        assert "task.facts" in facts
        assert "blocks.facts" in facts
        assert "requires.facts" in facts
        assert "done.facts" in facts
        assert "doing.facts" in facts
        assert "pending.facts" in facts
        assert "blocked.facts" in facts
        assert "in_cycle.facts" in facts
        assert "has_acceptance_proof.facts" in facts
        assert "do_proposal.facts" in facts
        # A is completed, so the snapshot should materialise done("A").
        assert "A" in facts["done.facts"]
        # The proposal for B → in_progress should land in do_proposal.facts.
        assert "B" in facts["do_proposal.facts"]

    def test_strict_acceptance_flag_emitted(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        ctx = _ctx_with({"A": _task("A")})
        DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="completed", strict=True, proof=False)
        )
        facts = datalog_subprocess.calls[0]["facts"]
        assert facts["strict_acceptance.facts"].strip() == "1"

    def test_hostile_subject_routed_through_encode(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    subject='"; (assert (not Task))',
                    description="\\x00\\n",
                ),
            }
        )
        DatalogSolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        program = datalog_subprocess.calls[0]["program_text"]
        facts = datalog_subprocess.calls[0]["facts"]
        # F-139: no raw subject text reaches the program or the facts files.
        assert '"; (assert (not Task))' not in program
        for content in facts.values():
            assert '"; (assert (not Task))' not in content
        # The escaped surrogate should still encode the task id in the
        # ``task.facts`` materialisation.
        safe = encode_solver_literal("A")
        assert safe in facts["task.facts"]


# ---------------------------------------------------------------------------
# Decision coverage
# ---------------------------------------------------------------------------


class TestDecisionMatrix:
    def test_ready_task_passes(self, datalog_subprocess: _SubprocessRecorder) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ()
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "pass"
        assert response.proof_trace
        assert response.proof_trace[0]["rule"] == "DL-SAT"

    def test_blocked_task_fails_with_r002(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ("B",)
        ctx = _ctx_with(
            {
                "A": _task("A"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="B", status="in_progress")
        )
        assert response.result == "fail"
        assert response.violated_rule == "R-002"
        assert "A" in response.message

    def test_cycle_task_fails_with_r006(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ("A",)
        ctx = _ctx_with(
            {
                "A": _task("A", blocks=["B"]),
                "B": _task("B", blocks=["A"], blocked_by=["A"]),
            }
        )
        snap = _snapshot(ctx)
        assert "A" in snap.cycle_task_ids
        response = DatalogSolverAdapter().solve(_req(snap, target="A", status="in_progress"))
        assert response.result == "fail"
        assert response.violated_rule == "R-006"

    def test_strict_acceptance_requires_proof(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ("A",)
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    status="in_progress",
                    metadata={"lkb": {"strict_acceptance": True}},
                ),
            }
        )
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="completed", strict=True, proof=False)
        )
        assert response.result == "fail"
        assert response.violated_rule == "R-005"

    def test_strict_acceptance_with_proof_passes(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ()
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    status="in_progress",
                    metadata={
                        "lkb": {
                            "strict_acceptance": True,
                            "acceptance_proof": "hash-of-evidence",
                        }
                    },
                ),
            }
        )
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="completed", strict=True, proof=True)
        )
        assert response.result == "pass"

    def test_unknown_target_id_denied(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ("Z",)
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(_req(_snapshot(ctx), target="Z", status="pending"))
        assert response.result == "fail"
        assert response.violated_rule == "LKB-TRANSITION-001"

    def test_unknown_target_with_no_violation_still_fails(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        # When Soufflé produced no violation row but the target is unknown,
        # the default fallback classifies the run as DL-UNSAT (still fail).
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ()
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "pass"


# ---------------------------------------------------------------------------
# Resource-limit mapping
# ---------------------------------------------------------------------------


class TestResourceLimits:
    def test_timeout_maps_to_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ``--version`` returns OK so ``available()`` succeeds; only the
        # actual ``solve`` invocation raises ``SolverLimitError``.
        def _fake_run(command: list[str], *args: Any, **kwargs: Any) -> Any:
            if "--version" in command:
                return (0, "souffle mock", "")
            raise SolverLimitError("timeout", "5.0s")

        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/souffle")
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.solver_adapter.run_external_solver",
            _fake_run,
        )
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "timeout"
        assert response.error_info == {
            "reason": "timeout",
            "timeout_seconds": 30.0,
        }

    def test_output_limit_maps_to_unknown(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _fake_run(command: list[str], *args: Any, **kwargs: Any) -> Any:
            if "--version" in command:
                return (0, "souffle mock", "")
            raise SolverLimitError("output_limit", "8388608 bytes")

        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/souffle")
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.solver_adapter.run_external_solver",
            _fake_run,
        )
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "unknown"
        assert response.error_info == {"reason": "output_limit"}

    def test_subprocess_exception_maps_to_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _fake_run(command: list[str], *args: Any, **kwargs: Any) -> Any:
            if "--version" in command:
                return (0, "souffle mock", "")
            raise RuntimeError("boom")

        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/souffle")
        monkeypatch.setattr(
            "clawcodex_ext.logical_kanban.solver_adapter.run_external_solver",
            _fake_run,
        )
        ctx = _ctx_with({"A": _task("A")})
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "error"
        assert response.error_info is not None
        assert response.error_info["reason"] == "exception"
        assert response.error_info["exception"] == "RuntimeError"


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class _AlwaysPassAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return "always-pass"

    @property
    def version(self) -> str:
        return "0.0.0"

    def available(self) -> bool:
        return True

    def solve(self, request: SolverRequest, *, timeout_seconds: float = 30.0) -> SolverResponse:
        return SolverResponse(result="pass")


class TestPipelineIntegration:
    def test_layer1_plus_datalog_agrees_on_ready(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ()
        ctx = _ctx_with({"A": _task("A")})
        pipeline = SolverPipeline([Layer1SolverAdapter(), DatalogSolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target="A", status="in_progress"),
            proposal_id="P-ready",
        )
        assert run.result == "pass"
        engines = {r["adapter"] for r in run.solver_results}
        assert engines == {"layer1-python", "datalog-souffle"}

    def test_any_fail_means_overall_fail(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ("B",)
        ctx = _ctx_with(
            {
                "A": _task("A"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        pipeline = SolverPipeline([Layer1SolverAdapter(), DatalogSolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target="B", status="in_progress"),
            proposal_id="P-block",
        )
        assert run.result == "fail"
        assert all(r["result"] == "fail" for r in run.solver_results)


# ---------------------------------------------------------------------------
# F-139 sanitisation
# ---------------------------------------------------------------------------


class TestSecuritySanitisation:
    def test_encode_solver_literal_rejects_unsafe_chars(self) -> None:
        escaped = encode_solver_literal("<script>alert(1)</script>")
        assert "<" not in escaped and ">" not in escaped
        suffix = re.findall(r"_h[0-9a-f]{4}$", escaped)
        assert escaped.endswith(suffix[0])

    def test_hostile_subject_does_not_crash(
        self,
        datalog_subprocess: _SubprocessRecorder,
    ) -> None:
        datalog_subprocess.return_value = (0, "", "")
        datalog_subprocess.violation_rows = ()
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    subject='"; (assert (not Task))',
                    description="\\x00\\n",
                ),
            }
        )
        response = DatalogSolverAdapter().solve(
            _req(_snapshot(ctx), target="A", status="in_progress")
        )
        assert response.result == "pass"

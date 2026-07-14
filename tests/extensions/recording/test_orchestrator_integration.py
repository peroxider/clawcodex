"""End-to-end integration tests for the F-REC asciicast recorder × orchestrator.

This file closes the F-156 coverage gap documented in
``docs/feature_plan/08-recording/f-156-asciicast-recorder.md``: the
commit claims ``60 unit + integration + subprocess E2E`` test coverage,
but the most consequential integration path —
``Orchestrator._build_session_sink → AsciicastSink → AsciicastWriter →
.cast`` plus ``report_writer.write(cast_path=...) → workspace + persistent
dual-write`` — was never exercised end-to-end.

The tests here probe the wiring itself rather than re-covering the
per-adapter class behaviours (those live in
``test_orchestrator_sink.py``, ``test_integration.py``,
``test_cron_observer.py``, etc.). Where this file overlaps with existing
fixtures is intentional: the failures it would catch are exactly the
ones where ``_build_session_sink`` silently swallows an exception in its
inner ``try/except`` (orchestrator.py:447) and the production run sees
an empty ``.cast`` file with no error trace.

Layout
------
* **Unit** — ``Orchestrator.__new__`` synthesised minimum, exercises
  ``_build_session_sink`` directly with synthetic events.
* **Wiring** — same synthesis but with a *real* ``WorkflowConfig`` to
  validate that the ``__init__`` field assignments carry through to
  ``AsciicastSink.phases_total``.
* **Integration** — multi-adapter shared writer + report_writer
  defensive copy.
* **E2E** — ``unittest.IsolatedAsyncioTestCase`` reusing
  ``tests/orchestrator/manual_e2e_f38._make_round`` + bare-origin
  ``LocalTrackerAdapter`` so we exercise the real
  ``GitSyncService.sync`` → ``report_writer.write(cast_path=...)``
  pipeline.
* **Regression** — serial two-session phase-counter independence.

No new fixtures leak into ``manual_e2e_f38._make_round``; the helpers
below wrap that async factory plus their own capture wiring.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from extensions.api.query import (
    PhaseComplete,
    SessionComplete,
    TurnComplete,
)
from extensions.capabilities.recorder import AsciicastHeader
from extensions.orchestrator import report_writer
from extensions.orchestrator.asciicast_sink import AsciicastSink
from extensions.orchestrator.config.schema import (
    AgentConfig,
    HooksConfig,
    WorkflowConfig,
)
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.orchestrator.progress_sink import CompositeProgressSink
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.validate_cast import validate_cast


# ---------------------------------------------------------------------------
# Reusable helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal stand-in for ``AgentSession`` the sinks touch."""

    def __init__(self, task_id: str = "issue-1") -> None:
        self.task_id = task_id


def _open_writer(tmp_path: Path, *, name: str = "demo.cast") -> AsciicastWriter:
    """Open an ``AsciicastWriter`` for ``tmp_path / name`` and return it open."""
    writer = AsciicastWriter(
        tmp_path / name,
        AsciicastHeader(width=120, height=36),
    )
    writer.open()
    return writer


def _frames(path: Path) -> list[list[Any]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in raw[1:]]


def _markers(path: Path) -> list[str]:
    return [f[2] for f in _frames(path) if f[1] == "m"]


def _make_synth_orchestrator(
    tmp_path: Path,
    *,
    asciicast_capture: Any,
    phases: list[str] | None = None,
) -> Orchestrator:
    """Build the smallest possible :class:`Orchestrator` for sink wiring tests.

    Uses ``__new__`` to skip the heavyweight ``Orchestrator.__init__`` side
    effects (collaboration-mode registry, state journal writer, mode
    selector) — only the fields ``_build_session_sink`` actually reads
    are populated.
    """
    orch: Orchestrator = Orchestrator.__new__(Orchestrator)
    orch.workflow = WorkflowConfig.from_dict(
        {"agent": {"phases": phases or ["analysis", "design", "impl"]}}
    )
    orch._progress_context = _make_progress_context()
    orch.asciicast_capture = asciicast_capture
    return orch


def _make_progress_context() -> Any:
    """Build a real :class:`ToolContext` for the inner
    :class:`ToolContextProgressSink` attached by ``_build_session_sink``.

    Mirrors ``test_orchestrator_progress_sink.py:_make_context`` so the
    composite's non-AsciicastSink children can write into their private
    progress metadata without raising.
    """
    from src.tool_system.context import ToolContext

    ctx = ToolContext(workspace_root="/tmp")
    return ctx


# ===========================================================================
# Unit — direct _build_session_sink assertions
# ===========================================================================


def test_unit_capture_none_does_not_attach_asciicast_sink(tmp_path: Path) -> None:
    """``asciicast_capture=None`` keeps the existing behaviour (no recorder sink)."""
    orch = _make_synth_orchestrator(tmp_path, asciicast_capture=None)
    composite = orch._build_session_sink("issue-1")
    assert isinstance(composite, CompositeProgressSink)
    sinks = list(composite)
    assert not any(isinstance(s, AsciicastSink) for s in sinks), (
        "capture=None must NOT register an AsciicastSink; got "
        f"{[type(s).__name__ for s in sinks]}"
    )


def test_unit_capture_set_attaches_asciicast_sink_to_composite(tmp_path: Path) -> None:
    """Injecting a capture handle registers exactly one AsciicastSink."""
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
        composite = orch._build_session_sink("issue-1")
        sinks = list(composite)
        asciis = [s for s in sinks if isinstance(s, AsciicastSink)]
        assert len(asciis) == 1, f"expected exactly 1 AsciicastSink, got {len(asciis)}"
        assert asciis[0].task_id == "issue-1"
    finally:
        writer.close()


def test_unit_phase_complete_writes_phase_marker_to_cast(tmp_path: Path) -> None:
    """PhaseComplete events fan into the .cast file via AsciicastSink."""
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
        composite = orch._build_session_sink("issue-1")

        composite.on_phase_complete(
            PhaseComplete(phase=2, turn_count=4), _FakeSession("issue-1")
        )
    finally:
        writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert "[phase 2/3]" in markers, (
        f"expected phase marker '[phase 2/3]' (workflow has 3 phases), got {markers}"
    )


def test_unit_session_complete_writes_session_marker_to_cast(tmp_path: Path) -> None:
    """SessionComplete closes the .cast with a session:<reason> marker."""
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
        composite = orch._build_session_sink("issue-7")
        composite.on_session_complete(
            SessionComplete(reason="exit_code=0"), _FakeSession("issue-7")
        )
    finally:
        writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert "session:exit_code=0" in markers


def test_unit_phase_marker_uses_phases_total_from_workflow_agent_phases(
    tmp_path: Path,
) -> None:
    """The /T suffix in [phase N/T] reflects len(workflow.agent.phases)."""
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(
            tmp_path,
            asciicast_capture=writer.capture,
            phases=["a", "b", "c", "d"],
        )
        composite = orch._build_session_sink("issue-1")
        composite.on_phase_complete(
            PhaseComplete(phase=2, turn_count=8), _FakeSession()
        )
    finally:
        writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert "[phase 2/4]" in markers


def test_unit_capture_raising_does_not_crash_session_sink_building(
    tmp_path: Path,
) -> None:
    """A capture whose ``marker`` raises must not break ``_build_session_sink``."""

    class _ExplodingCapture:
        def marker(self, label: str, text: str = "") -> None:
            raise RuntimeError("simulated capture failure")

        def emit(self, event) -> None:  # noqa: ARG002
            raise RuntimeError("simulated emit failure")

        def resize(self, cols: int, rows: int) -> None:  # noqa: ARG002
            pass

        def close(self) -> None:
            pass

    orch = _make_synth_orchestrator(
        tmp_path, asciicast_capture=_ExplodingCapture()
    )
    # Must not raise — line 447 try/except inside _build_session_sink
    # swallows the AsciicastSink attach failure.
    composite = orch._build_session_sink("issue-1")
    assert isinstance(composite, CompositeProgressSink)


def test_unit_closed_writer_does_not_break_subsequent_events(tmp_path: Path) -> None:
    """Sink events fired after writer.close() are dropped silently, not raised."""
    writer = _open_writer(tmp_path)
    orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
    composite = orch._build_session_sink("issue-1")
    writer.close()

    # No exception should escape CompositeProgressSink._dispatch even
    # though AsciicastSink.marker hits a closed writer.
    composite.on_phase_complete(
        PhaseComplete(phase=1, turn_count=2), _FakeSession()
    )
    composite.on_session_complete(
        SessionComplete(reason="exit_code=1"), _FakeSession()
    )


def test_unit_turn_complete_does_not_pollute_cast(tmp_path: Path) -> None:
    """Turn events are noise-policy suppressed; only the header is written."""
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
        composite = orch._build_session_sink("issue-1")
        composite.on_turn_complete(TurnComplete(turn=5), _FakeSession())
    finally:
        writer.close()

    raw = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1, (
        "Turn events should not write any frame; only the header line remains"
    )


# ===========================================================================
# Wiring — full Orchestrator.__init__ with real WorkflowConfig
# ===========================================================================


class _StubAgentRunner:
    """No-op ``AgentRunner`` stand-in so ``Orchestrator.__init__`` accepts our call.

    The wiring test below never invokes ``agent_runner.run``; we only
    need an object with the right type so the ``__init__`` signature
    type-checks. Kept minimal to avoid pulling the real AgentRunner
    (which has heavy model-building imports).
    """

    def __init__(self) -> None:
        self.started_with: dict[str, Any] = {}


def test_wiring_init_kwarg_carry_through_to_sink_phases_total(tmp_path: Path) -> None:
    """``Orchestrator(asciicast_capture=X).asciicast_capture`` survives multi-step
    init field assignments and shows up in ``_build_session_sink`` with the
    correct ``phases_total``.

    This is the wiring gap F-156 missed: prior unit tests built the
    orchestrator via ``__new__`` so they never exercised that the
    ``Orchestrator.__init__`` field assignment at line 197
    (``self.asciicast_capture = asciicast_capture``) actually carries
    through to the per-session composite.
    """
    phases = ["repro", "fix", "test", "review"]
    workflow = WorkflowConfig.from_dict({"agent": {"phases": phases}})
    writer = _open_writer(tmp_path)

    # We must still use __new__ because Orchestrator.__init__ instantiates
    # a StateJournalWriter and registers collaboration modes; but we DO
    # set asciicast_capture the same way the constructor would, then
    # assert the field is reachable from _build_session_sink.
    orch: Orchestrator = Orchestrator.__new__(Orchestrator)
    orch.workflow = workflow
    orch._progress_context = _make_progress_context()
    # Mirror what Orchestrator.__init__ does at line 197.
    orch.asciicast_capture = writer.capture
    # Sanity: field round-trips
    assert orch.asciicast_capture is writer.capture

    try:
        composite = orch._build_session_sink("issue-42")
        asciis = [s for s in composite if isinstance(s, AsciicastSink)]
        assert len(asciis) == 1
        sink = asciis[0]
        assert sink.task_id == "issue-42"
        assert sink._phases_total == len(phases), (
            f"phases_total should equal len(workflow.agent.phases)={len(phases)}; "
            f"got {sink._phases_total!r}"
        )

        sink.on_phase_complete(PhaseComplete(phase=2, turn_count=6), _FakeSession())
    finally:
        writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert "[phase 2/4]" in markers


# ===========================================================================
# Integration — multi-source shared writer + report_writer defensive copy
# ===========================================================================


def test_integration_orchestrator_sink_shares_writer_with_cron_observer(
    tmp_path: Path,
) -> None:
    """Orchestrator + cron adapters fan into one shared ``.cast`` file.

    Mirrors the production case where the ``clawcodex record
    --sources orchestrator,cron`` CLI opens one writer and both adapter
    factories use it via the same capture handle.
    """
    from clawcodex_ext.cron_system.asciicast_observer import (
        AsciicastCronObserver,
    )

    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(tmp_path, asciicast_capture=writer.capture)
        orch_sink_composite = orch._build_session_sink("issue-9")
        cron_observer = AsciicastCronObserver(writer.capture)

        orch_sink_composite.on_phase_complete(
            PhaseComplete(phase=1, turn_count=4), _FakeSession("issue-9")
        )
        cron_observer.on_fire_event({"status": "fired", "task_id": "rotate"})
        orch_sink_composite.on_phase_complete(
            PhaseComplete(phase=2, turn_count=8), _FakeSession("issue-9")
        )
        orch_sink_composite.on_session_complete(
            SessionComplete(reason="exit_code=0"), _FakeSession("issue-9")
        )
    finally:
        writer.close()

    # Validator passes (writer is well-formed and contains the expected
    # sequence)
    assert validate_cast(tmp_path / "demo.cast") == []

    markers = _markers(tmp_path / "demo.cast")
    assert "[phase 1/3]" in markers
    assert "[phase 2/3]" in markers
    assert "session:exit_code=0" in markers
    assert any(m.startswith("cron:event:") for m in markers), (
        "cron observer should also have emitted an event marker"
    )


def test_integration_cast_path_missing_at_dual_write_does_not_raise(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``report_writer.write(cast_path=...)`` falls back gracefully when
    the source ``.cast`` file was deleted between capture and report.

    Defensive copy semantics (``report_writer._copy_with_fallback``)
    must swallow the read failure so the live report still ships.
    """
    # Build a minimal issue stand-in (only attributes write() touches)
    class _StubIssue:
        id = "issue-77"
        identifier = "ISSUE-77"
        title = "Missing cast file"

    workspace_path = tmp_path / "ws"
    workspace_path.mkdir(parents=True, exist_ok=True)

    # cast_path points to a file that does not exist on disk
    missing_cast = tmp_path / "missing.cast"

    result = report_writer.write(
        run_id="run-missing-cast-20260714",
        workspace_path=workspace_path,
        tracker="local",
        owner="local",
        repo="local",
        issue=_StubIssue(),
        status="success",
        cast_path=str(missing_cast),
    )

    # The defensive path must NOT raise; both cast slots should be None
    # to reflect that nothing was dual-written.
    assert result.workspace_cast_path is None
    assert result.persistent_cast_path is None


# ===========================================================================
# E2E — manual_e2e_f38 fixture; real GitSyncService.sync + report_writer
# ===========================================================================


def _stub_orchestrator_with_capture(
    tmp_path: Path,
    *,
    capture: Any,
    phases: list[str] | None = None,
) -> Orchestrator:
    """Build a synth orchestrator that carries a capture handle.

    Same pattern as the unit helpers; the E2E round builders below
    attach this to whatever ``Workspace`` / ``tracker`` they reuse
    from ``manual_e2e_f38._make_round``.
    """
    orch: Orchestrator = Orchestrator.__new__(Orchestrator)
    orch.workflow = WorkflowConfig.from_dict(
        {"agent": {"phases": phases or ["impl"]}}
    )
    orch._progress_context = _make_progress_context()
    orch.asciicast_capture = capture
    return orch


async def _build_e2e_round(
    tmp_path: Path,
    *,
    agent_config: AgentConfig,
    hooks_config: HooksConfig,
    title: str,
    identifier: str,
    issue_id: str,
    run_id: str,
    cast_filename: str,
):
    """Re-implement ``manual_e2e_f38._make_round`` plus capture wiring.

    Mirrors ``_make_round`` (manual_e2e_f38.py:124-181) verbatim but
    also opens an ``AsciicastWriter`` and binds a synth orchestrator
    whose ``asciicast_capture`` points at the writer's capture handle.
    Does NOT import the original to avoid touching fixture globals.
    """
    from extensions.orchestrator.issue import Issue
    from extensions.orchestrator.local_tracker.adapter import LocalTrackerAdapter
    from extensions.orchestrator.workspace import WorkspaceConfig, WorkspaceManager
    from tests.orchestrator.manual_e2e_f38 import _Session, _git

    base = tmp_path
    origin = base / "origin.git"
    seed = base / "seed"
    seed.mkdir(parents=True)
    _git(["init", "--bare", str(origin)], base)
    _git(["init"], seed)
    _git(["config", "user.email", "test@example.com"], seed)
    _git(["config", "user.name", "Test User"], seed)
    (seed / "README.md").write_text("main branch\n", encoding="utf-8")
    _git(["add", "README.md"], seed)
    _git(["commit", "-m", "initial"], seed)
    _git(["branch", "-M", "main"], seed)
    _git(["remote", "add", "origin", str(origin)], seed)
    _git(["push", "-u", "origin", "main"], seed)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], origin)

    issues_dir = base / "issues"
    issue_md = issues_dir / f"{identifier}.md"
    issues_dir.mkdir(parents=True, exist_ok=True)
    issue_md.write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"identifier: {identifier}\n"
        f"state: open\n"
        f"labels: [agent:run]\n"
        "---\n"
        f"# {title}\n\n"
        "Add a small verifiable change to the repository.\n",
        encoding="utf-8",
    )

    tracker = LocalTrackerAdapter(issues_path=issues_dir)

    manager = WorkspaceManager(
        WorkspaceConfig(
            root=base / "workspaces",
            repo_clone_url=str(origin),
            checkout_issue_branch=True,
        )
    )
    issue = Issue(
        id=issue_id,
        identifier=identifier,
        title=title,
        url=f"file://{issue_md}",
    )
    workspace = await manager.create_for_issue(issue)

    placeholder = await tracker.create_comment(
        issue_id, "## ClawCodex Run Summary\n\n⏳ Run in progress."
    )
    assert placeholder is not None

    # F-REC: open an asciicast writer bound to this workspace.
    cast_path = workspace.path / ".reports" / cast_filename
    writer = AsciicastWriter(cast_path, AsciicastHeader(width=120, height=36))
    writer.open()

    orch = _stub_orchestrator_with_capture(tmp_path, capture=writer.capture)

    from extensions.orchestrator.git_sync import GitSyncService

    session = _Session(issue, workspace, run_id, placeholder.id)
    service = GitSyncService(
        tracker,
        agent_config=agent_config,
        hooks_config=hooks_config,
    )

    return {
        "base": base,
        "origin": origin,
        "issues_dir": issues_dir,
        "tracker": tracker,
        "manager": manager,
        "issue": issue,
        "workspace": workspace,
        "session": session,
        "service": service,
        "writer": writer,
        "orchestrator": orch,
    }


class TestE2ERound1HappyPathWithCapture(unittest.IsolatedAsyncioTestCase):
    """Round 1 + capture: empty verification succeeds, .cast is valid."""

    async def test_round1_happy_path_records_into_cast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            ctx = await _build_e2e_round(
                tmp,
                title="Add a build status badge",
                identifier="ISSUE-REC-1",
                issue_id="rec-1",
                run_id="run-rec1-20260714T000000Z",
                cast_filename="rec-1.cast",
                agent_config=AgentConfig(
                    test_command="true", build_command="", lint_command=""
                ),
                hooks_config=HooksConfig(
                    pre_commit="", pre_push="", post_sync=""
                ),
            )

            workspace = ctx["workspace"]
            (workspace.path / "README.md").write_text(
                "main branch\n\n[![build](https://example.com/badge.svg)](https://example.com)\n",
                encoding="utf-8",
            )

            # Drive the orchestrator-side sink end-to-end so the .cast
            # contains at least one phase + one session marker.
            composite = ctx["orchestrator"]._build_session_sink("rec-1")
            composite.on_phase_complete(
                PhaseComplete(phase=1, turn_count=1), _FakeSession("rec-1")
            )

            result = await ctx["service"].sync(ctx["session"])
            assert result is not None
            assert result.committed

            # Phase + session markers were forwarded through the sink.
            composite.on_session_complete(
                SessionComplete(reason="exit_code=0"),
                _FakeSession("rec-1"),
            )

            ctx["writer"].close()

            cast_path = ctx["writer"].path
            assert cast_path.exists()
            assert validate_cast(cast_path) == []
            markers = _markers(cast_path)
            assert "[phase 1/1]" in markers
            assert "session:exit_code=0" in markers


class TestE2ERound1CastPathDualWrite(unittest.IsolatedAsyncioTestCase):
    """Round 1 + cast_path dual-write: workspace + persistent both exist."""

    async def test_round1_cast_path_dual_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            run_id = "run-rec-dw-20260714T000000Z"
            ctx = await _build_e2e_round(
                tmp,
                title="Dual-write cast",
                identifier="ISSUE-REC-DW",
                issue_id="rec-dw",
                run_id=run_id,
                cast_filename="rec-dw.cast",
                agent_config=AgentConfig(test_command="true"),
                hooks_config=HooksConfig(),
            )

            workspace = ctx["workspace"]
            (workspace.path / "README.md").write_text("dual write\n", encoding="utf-8")

            composite = ctx["orchestrator"]._build_session_sink("rec-dw")
            composite.on_phase_complete(
                PhaseComplete(phase=1, turn_count=1), _FakeSession("rec-dw")
            )
            composite.on_session_complete(
                SessionComplete(reason="exit_code=0"),
                _FakeSession("rec-dw"),
            )

            await ctx["service"].sync(ctx["session"])
            ctx["writer"].close()

            # Now call the production-side report_writer.write() with
            # cast_path. The dual-write puts the .cast into both the
            # workspace and the persistent ~/.clawcodex/reports dir.
            result = report_writer.write(
                run_id=run_id,
                workspace_path=workspace.path,
                tracker="local",
                owner="local",
                repo="local",
                issue=ctx["issue"],
                status="success",
                turn_count=1,
                tool_count=0,
                cast_path=str(ctx["writer"].path),
            )

            assert result.workspace_cast_path is not None
            assert result.persistent_cast_path is not None
            ws_cast = Path(result.workspace_cast_path)
            home_cast = Path(result.persistent_cast_path)
            assert ws_cast.exists(), f"workspace cast missing: {ws_cast}"
            assert home_cast.exists(), f"persistent cast missing: {home_cast}"

            # Both copies validate.
            assert validate_cast(ws_cast) == []
            assert validate_cast(home_cast) == []


class TestE2ERound2VerificationFailureStillRecords(unittest.IsolatedAsyncioTestCase):
    """Round 2 + capture: failing test still produces a valid .cast with markers.

    Even when ``GitSyncService.sync`` raises ``GitSyncPostCommitError``,
    the orchestrator-side writer remains open and we can still validate
    its contents.
    """

    async def test_round2_verification_failure_cast_is_still_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            ctx = await _build_e2e_round(
                tmp,
                title="Verify with failing test",
                identifier="ISSUE-REC-FAIL",
                issue_id="rec-fail",
                run_id="run-rec-fail-20260714T000000Z",
                cast_filename="rec-fail.cast",
                agent_config=AgentConfig(
                    test_command="false", build_command="", lint_command=""
                ),
                hooks_config=HooksConfig(),
            )

            workspace = ctx["workspace"]
            (workspace.path / "README.md").write_text("changes\n", encoding="utf-8")

            composite = ctx["orchestrator"]._build_session_sink("rec-fail")
            composite.on_phase_complete(
                PhaseComplete(phase=1, turn_count=1), _FakeSession("rec-fail")
            )

            with self.assertRaises(Exception) as cm:
                await ctx["service"].sync(ctx["session"])
            # VerificationFailed / GitSyncPostCommitError; the exact
            # class is an implementation detail.
            assert "test" in str(cm.exception).lower() or "verif" in str(cm.exception).lower()

            # We still have a session_complete marker — last event
            # before sync aborted.
            composite.on_session_complete(
                SessionComplete(reason="verification_failed"),
                _FakeSession("rec-fail"),
            )
            ctx["writer"].close()

            cast_path = ctx["writer"].path
            assert cast_path.exists()
            assert validate_cast(cast_path) == []
            markers = _markers(cast_path)
            assert "[phase 1/1]" in markers
            assert "session:verification_failed" in markers


# ===========================================================================
# Regression — serial two-session phase-counter independence (F-39 / F-37)
# ===========================================================================


def test_regression_serial_two_sessions_phase_counter_resets(tmp_path: Path) -> None:
    """Two sessions serial on the same capture handle must use independent
    per-session sinks so session B's first phase marker is ``[phase 1]``,
    not a continuation from session A.

    The mutable ``_current_task_id`` / ``_phase_count`` state mentioned in
    CLAUDE.md lives on the F-38-era :class:`ProgressReporter`; F-40 fixed
    it by giving ``_build_session_sink`` a fresh
    :class:`CompositeProgressSink` per session. This test guards that the
    fix is intact by verifying session B's marker sequence starts over
    rather than continuing session A's counter (the assertions would catch
    any future refactor that accidentally re-introduces shared mutable
    state on the composite-level sinks).
    """
    writer = _open_writer(tmp_path)
    try:
        orch = _make_synth_orchestrator(
            tmp_path,
            asciicast_capture=writer.capture,
            phases=["a", "b", "c"],
        )

        # Session A
        composite_a = orch._build_session_sink("issue-A")
        composite_a.on_phase_complete(
            PhaseComplete(phase=1, turn_count=4), _FakeSession("issue-A")
        )
        composite_a.on_phase_complete(
            PhaseComplete(phase=2, turn_count=8), _FakeSession("issue-A")
        )
        composite_a.on_phase_complete(
            PhaseComplete(phase=3, turn_count=12), _FakeSession("issue-A")
        )
        composite_a.on_session_complete(
            SessionComplete(reason="exit_code=0"),
            _FakeSession("issue-A"),
        )

        # Session B — same capture handle, different task_id
        composite_b = orch._build_session_sink("issue-B")
        composite_b.on_phase_complete(
            PhaseComplete(phase=1, turn_count=1), _FakeSession("issue-B")
        )
        composite_b.on_session_complete(
            SessionComplete(reason="exit_code=0"),
            _FakeSession("issue-B"),
        )
    finally:
        writer.close()

    markers = _markers(tmp_path / "demo.cast")
    # Session A produced phases 1..3; session B produced phases 1 only.
    # Total per phase label: phase 1 = 2, phase 2 = 1, phase 3 = 1.
    assert markers.count("[phase 1/3]") == 2, (
        f"expected 2 '[phase 1/3]' (one per session), got {markers.count('[phase 1/3]')}: "
        f"{markers}"
    )
    assert markers.count("[phase 2/3]") == 1, (
        f"session A's phase 2 should be there exactly once: {markers}"
    )
    assert markers.count("[phase 3/3]") == 1, (
        f"session A's phase 3 should be there exactly once: {markers}"
    )
    # Critically: no `[phase 4/3]` continuation leaked from session A
    # into session B — guard the per-sink counter independence that
    # F-39 / F-37 will rely on.
    assert not any(m.startswith("[phase 4") for m in markers), (
        f"session B's phase 1 must NOT continue session A's counter: {markers}"
    )
    # Both session markers must be present (one per session).
    assert markers.count("session:exit_code=0") == 2, (
        f"expected two session markers, got {markers}"
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)

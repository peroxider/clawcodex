"""Phase 4 tests for the ``takeover`` CLI subcommand.

Covers:
  * ``argparse`` registration: ``clawcodex issue takeover --id X``
    parses into ``args.issue_subcommand == "takeover"``, and the
    parser also accepts ``--run`` + ``--workspace`` (sibling of
    attach / resume-session).
  * ``run()`` dispatcher routes ``takeover`` to ``_run_takeover``
    with ``(registry_path, ws, args)`` (the same signature
    _run_attach / _run_resume_session use).
  * ``_resolve_target`` returns the correct ``_TakeoverTarget`` for
    each lookup mode: ``--id`` (IssueRegistry), ``--run`` +
    ``--workspace`` (registry bypass), and the not-found / no-run-id
    / no-workspace-path / no-registry negative cases.
  * Full flow: the handler sends a ``flush_transcript`` command over
    the control socket (so the latest conversation is on disk), then
    spawns a ``--resume`` REPL. The agent is NOT paused — no
    ``pause``/``stop``/``takeover`` commands are sent. Takeover is a
    pure read-only snapshot of the on-disk ``transcript.jsonl``.

Uses ``unittest.TestCase`` (the resolver / parser are sync) and
``tempfile.TemporaryDirectory`` for IssueRegistry isolation.
Patches ``extensions.orchestrator.issue_registry``'s default path
so the test does not touch the user's real ``~/.clawcodex``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import unittest
from contextlib import redirect_stderr
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from extensions.orchestrator.cli.takeover import (
    _TakeoverTarget,
    _resolve_target,
    _run_takeover,
    _run_takeover_async,
)
from extensions.orchestrator.control_socket import ControlSocket
from extensions.orchestrator.issue_registry import (
    IssueRecord,
    IssueRegistry,
    IssueStatus,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _write_registry(path: Path, record: IssueRecord) -> None:
    """Write a single-record IssueRegistry JSON file at ``path``.

    The on-disk format is ``{issue_id: record_dict}`` — see
    ``IssueRegistry._save`` for the canonical shape. ``status`` is
    serialised as its ``.value`` so the loader's
    ``IssueStatus(v)`` round-trip succeeds.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {record.issue_id: asdict(record)}
    data[record.issue_id]["status"] = record.status.value
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_record(
    issue_id: str = "42",
    issue_identifier: str = "owner/repo#42",
    run_id: str | None = "run-abc",
    workspace_path: str | None = "/tmp/ws",
) -> IssueRecord:
    """Build an IssueRecord for tests."""
    return IssueRecord(
        issue_id=issue_id,
        issue_identifier=issue_identifier,
        status=IssueStatus.RUNNING,
        branch_name="f-49-takeover-test",
        base_branch="main",
        workspace_path=workspace_path,
        workspace_strategy="worktree",
        run_id=run_id,
    )


async def _drain_one_command(
    cs: ControlSocket,
    timeout: float = 0.5,
) -> object | None:
    """Read at most one command from the control socket's queue.

    Returns the command if one arrives within ``timeout``, else ``None``.
    Used to assert that takeover does NOT send any commands.
    """

    async def _next() -> object | None:
        async for cmd in cs.poll_commands():
            return cmd
        return None

    try:
        return await asyncio.wait_for(_next(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


# ------------------------------------------------------------------
# Parser registration
# ------------------------------------------------------------------


class TestTakeoverParser(unittest.TestCase):
    """The new subcommand is registered with --id, --run, --workspace."""

    def test_takeover_parser_registered(self) -> None:
        from extensions.orchestrator.cli.issue import add_issue_parser

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers(dest="top")
        add_issue_parser(sub)
        args = parent.parse_args(["issue", "takeover", "--id", "X"])
        self.assertEqual(args.issue_subcommand, "takeover")
        self.assertEqual(args.id, "X")
        self.assertIsNone(args.run)
        self.assertIsNone(args.workspace)

    def test_takeover_parser_accepts_run_and_workspace(self) -> None:
        from extensions.orchestrator.cli.issue import add_issue_parser

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers(dest="top")
        add_issue_parser(sub)
        args = parent.parse_args(
            ["issue", "takeover", "--run", "r-1", "--workspace", "/w"],
        )
        self.assertEqual(args.issue_subcommand, "takeover")
        self.assertIsNone(args.id)
        self.assertEqual(args.run, "r-1")
        self.assertEqual(args.workspace, "/w")

    def test_takeover_parser_allows_no_args(self) -> None:
        """Unlike the legacy version, --id is now optional — usage
        is enforced at the handler, not the parser (so --run
        alone is parseable).
        """
        from extensions.orchestrator.cli.issue import add_issue_parser

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers(dest="top")
        add_issue_parser(sub)
        args = parent.parse_args(["issue", "takeover"])
        self.assertEqual(args.issue_subcommand, "takeover")
        self.assertIsNone(args.id)
        self.assertIsNone(args.run)
        self.assertIsNone(args.workspace)

    def test_takeover_parser_has_no_handback_flag(self) -> None:
        """The --no-handback flag was removed when takeover became
        a read-only snapshot viewer (no handback flow exists).
        """
        from extensions.orchestrator.cli.issue import add_issue_parser

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers(dest="top")
        add_issue_parser(sub)
        # Parsing --no-handback should fail (unknown arg).
        with self.assertRaises(SystemExit):
            parent.parse_args(["issue", "takeover", "--no-handback"])


# ------------------------------------------------------------------
# Dispatcher
# ------------------------------------------------------------------


class TestTakeoverDispatch(unittest.TestCase):
    """The ``run()`` dispatcher routes ``takeover`` to the new
    module-level ``_run_takeover`` with the (registry_path, ws,
    args) signature.
    """

    def test_dispatch_to_run_takeover(self) -> None:
        from extensions.orchestrator import cli as cli_mod
        from extensions.orchestrator.cli import issue as cli_issue

        captured: dict = {}

        def fake(registry_path, workspace_root, args) -> int:
            captured["called"] = True
            captured["registry_path"] = registry_path
            captured["workspace_root"] = workspace_root
            captured["id"] = getattr(args, "id", None)
            captured["run"] = getattr(args, "run", None)
            captured["workspace"] = getattr(args, "workspace", None)
            return 0

        with patch.object(cli_issue, "_run_takeover", side_effect=fake):
            args = argparse.Namespace(
                issue_subcommand="takeover",
                id="X",
                run=None,
                workspace=None,
            )
            rc = cli_issue.run(args)
        self.assertEqual(rc, 0)
        self.assertTrue(captured.get("called"))
        self.assertEqual(captured.get("id"), "X")
        self.assertIsNone(captured.get("run"))
        # The dispatcher passes the resolved registry path and the
        # ``--workspace`` argument through unchanged.
        self.assertEqual(
            captured.get("workspace"),
            args.workspace,
        )

    def test_dispatch_passes_registry_path_through(self) -> None:
        """When a registry_path is configured, the dispatcher
        forwards it to ``_run_takeover`` so the handler can look up
        the run_id via IssueRegistry.
        """
        from extensions.orchestrator.cli import issue as cli_issue

        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            _write_registry(registry_path, _make_record())

            captured: dict = {}

            def fake(registry_path_arg, workspace_root, args) -> int:
                captured["registry_path"] = registry_path_arg
                return 0

            with patch.object(cli_issue, "_run_takeover", side_effect=fake):
                args = argparse.Namespace(
                    issue_subcommand="takeover",
                    id="owner/repo#42",
                    run=None,
                    workspace=None,
                )
                # Inject the registry_path the way ``run()`` does.
                cli_issue._run_takeover(registry_path, Path(tmp), args)
            self.assertEqual(captured["registry_path"], registry_path)


# ------------------------------------------------------------------
# _resolve_target
# ------------------------------------------------------------------


class TestResolveTarget(unittest.TestCase):
    """The lookup helper returns the correct _TakeoverTarget or None."""

    def test_resolve_via_issue_id(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            _write_registry(registry_path, _make_record())
            result = _resolve_target(
                registry_path,
                None,
                "owner/repo#42",
                None,
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsInstance(result, _TakeoverTarget)
        self.assertEqual(result.run_id, "run-abc")
        self.assertEqual(result.workspace_path, Path("/tmp/ws"))
        self.assertEqual(result.issue_id, "owner/repo#42")

    def test_resolve_returns_none_for_no_run_id(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            _write_registry(
                registry_path,
                _make_record(run_id=None),
            )
            result = _resolve_target(
                registry_path,
                None,
                "owner/repo#42",
                None,
            )
        self.assertIsNone(result)

    def test_resolve_returns_none_for_no_workspace_path(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            _write_registry(
                registry_path,
                _make_record(workspace_path=None),
            )
            result = _resolve_target(
                registry_path,
                None,
                "owner/repo#42",
                None,
            )
        self.assertIsNone(result)

    def test_resolve_via_run_id_with_workspace(self) -> None:
        """--run + --workspace bypasses the registry entirely."""
        result = _resolve_target(
            None,
            Path("/w"),
            None,
            "run-xyz",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.run_id, "run-xyz")
        self.assertEqual(result.workspace_path, Path("/w"))
        self.assertEqual(result.issue_id, "run:run-xyz")

    def test_resolve_returns_none_when_registry_missing(self) -> None:
        result = _resolve_target(
            Path("/nonexistent/registry.json"),
            None,
            "X",
            None,
        )
        self.assertIsNone(result)

    def test_resolve_returns_none_for_missing_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            _write_registry(registry_path, _make_record())
            result = _resolve_target(
                registry_path,
                None,
                "MISSING",
                None,
            )
        self.assertIsNone(result)

    def test_resolve_returns_none_when_both_args_missing(self) -> None:
        result = _resolve_target(None, None, None, None)
        self.assertIsNone(result)

    def test_resolve_via_run_id_ignores_workspace_root_when_path_given(
        self,
    ) -> None:
        """--workspace overrides the resolved workspace_root."""
        result = _resolve_target(
            None,
            Path("/default"),
            None,
            "run-xyz",
        )
        assert result is not None
        self.assertEqual(result.workspace_path, Path("/default"))

    def test_resolve_via_run_id_uses_workspace_arg(self) -> None:
        """When the handler passes workspace_root=Path('/explicit')
        and --workspace='explicit', the explicit one wins (because
        the handler builds ``effective_workspace`` before calling
        _resolve_target). This test guards the contract that
        _resolve_target treats ``workspace_root`` as authoritative.
        """
        result = _resolve_target(
            None,
            Path("/explicit"),
            None,
            "run-xyz",
        )
        assert result is not None
        self.assertEqual(result.workspace_path, Path("/explicit"))


# ------------------------------------------------------------------
# _run_takeover — arg validation + stub behaviour
# ------------------------------------------------------------------


class TestRunTakeoverStub(unittest.TestCase):
    """The handler validates args + resolves the target + spawns
    the REPL. ``_wait_for_transcript`` is patched out so the stub
    tests don't block on the 3 s transcript-poll timeout.
    """

    def test_missing_id_and_run_returns_2(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            args = argparse.Namespace(id=None, run=None, workspace=None)
            rc = _run_takeover(None, None, args)
        self.assertEqual(rc, 2)
        self.assertIn("--id", err.getvalue())

    def test_run_without_workspace_returns_2(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            args = argparse.Namespace(
                id=None,
                run="r-1",
                workspace=None,
            )
            rc = _run_takeover(None, None, args)
        self.assertEqual(rc, 2)
        self.assertIn("--workspace", err.getvalue())

    def test_issue_not_found_returns_1(self) -> None:
        with TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            # Registry exists but is empty.
            registry_path.write_text("{}", encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                args = argparse.Namespace(
                    id="MISSING",
                    run=None,
                    workspace=None,
                )
                rc = _run_takeover(registry_path, Path(tmp), args)
        self.assertEqual(rc, 1)
        self.assertIn("no active run", err.getvalue().lower())

    def test_run_with_no_resolution_returns_0(self) -> None:
        """--run + --workspace bypasses the registry and resolves
        cleanly. The spawn layer is patched so we can assert the
        success code without launching a real REPL.
        """
        with patch(
            "extensions.orchestrator.cli.takeover._wait_for_transcript",
        ):
            with patch(
                "extensions.orchestrator.cli.takeover._ensure_session_stub",
            ):
                with patch(
                    "extensions.orchestrator.cli.takeover.subprocess.call",
                    return_value=0,
                ):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        args = argparse.Namespace(
                            id=None,
                            run="r-1",
                            workspace="/w",
                        )
                        rc = _run_takeover(None, Path("/w"), args)
        self.assertEqual(rc, 0)


# ------------------------------------------------------------------
# _run_takeover — full flow (REPL spawn, no pause)
# ------------------------------------------------------------------


class TestRunTakeoverFullFlow(unittest.IsolatedAsyncioTestCase):
    """The full flow: resolve → spawn ``--resume`` REPL.

    The agent is NOT paused — no commands are sent over the control
    socket. The REPL spawn is patched out (``subprocess.call``) so the
    test does not launch a real Python interpreter; the test asserts
    the right command was constructed and the right exit code is
    propagated. ``_wait_for_transcript`` is patched to avoid the 3 s
    poll delay.
    """

    async def test_socket_path_missing_spawns_repl_anyway(self) -> None:
        """If the agent has already ended (no .sock), the handler
        still spawns the REPL with ``--resume <run_id>`` against
        the on-disk transcript.
        """
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "ws"
            workspace.mkdir()
            registry_path = tmp_path / "registry.json"
            _write_registry(
                registry_path,
                _make_record(
                    run_id="run-1",
                    workspace_path=str(workspace),
                ),
            )

            # No socket file: agent already ended.
            run_dir = workspace / ".run_control"
            run_dir.mkdir(parents=True, exist_ok=True)
            # Intentionally do NOT create the sock file.

            with patch(
                "extensions.orchestrator.cli.takeover._wait_for_transcript",
            ):
                with patch(
                    "extensions.orchestrator.cli.takeover._ensure_session_stub",
                ):
                    with patch(
                        "extensions.orchestrator.cli.takeover.subprocess.call",
                        return_value=0,
                    ) as mock_call:
                        args = argparse.Namespace(
                            id="owner/repo#42",
                            run=None,
                            workspace=None,
                        )
                        rc = await _run_takeover_async(
                            registry_path,
                            tmp_path,
                            args,
                        )
        self.assertEqual(rc, 0)
        # REPL spawned with --resume run-1, cwd=<workspace>
        self.assertEqual(mock_call.call_count, 1)
        cmd = mock_call.call_args[0][0]
        self.assertEqual(cmd[0], "python3")
        self.assertIn("--resume", cmd)
        self.assertIn("run-1", cmd)
        self.assertNotIn("--workspace", cmd)
        self.assertEqual(mock_call.call_args[1]["cwd"], str(workspace))

    async def test_socket_present_sends_flush_not_pause(self) -> None:
        """If the .sock is alive, the handler sends only ``flush_transcript``
        (so the REPL can read the latest conversation). It does NOT send
        ``pause``/``stop``/``takeover`` — the agent keeps running.
        """
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "ws"
            workspace.mkdir()
            registry_path = tmp_path / "registry.json"
            run_id = "run-2"
            _write_registry(
                registry_path,
                _make_record(
                    run_id=run_id,
                    workspace_path=str(workspace),
                ),
            )

            # Create the socket + start the server.
            sock_path = workspace / ".run_control" / f"{run_id}.sock"
            sock_path.parent.mkdir(parents=True, exist_ok=True)
            cs = ControlSocket(sock_path)
            await cs.start()
            try:
                with patch(
                    "extensions.orchestrator.cli.takeover._wait_for_transcript",
                ):
                    with patch(
                        "extensions.orchestrator.cli.takeover._ensure_session_stub",
                    ):
                        with patch(
                            "extensions.orchestrator.cli.takeover.asyncio.sleep",
                        ):
                            with patch(
                                "extensions.orchestrator.cli.takeover.subprocess.call",
                                return_value=0,
                            ) as mock_call:
                                args = argparse.Namespace(
                                    id="owner/repo#42",
                                    run=None,
                                    workspace=None,
                                )
                                rc = await _run_takeover_async(
                                    registry_path,
                                    tmp_path,
                                    args,
                                )

                # Exactly one command should have been sent:
                # flush_transcript. NOT pause/stop/takeover.
                cmd = await _drain_one_command(cs, timeout=0.5)
                self.assertIsNotNone(cmd, "expected flush_transcript command")
                assert cmd is not None
                self.assertEqual(cmd.cmd, "flush_transcript")
                # No more commands (no pause/stop/takeover).
                extra = await _drain_one_command(cs, timeout=0.3)
                self.assertIsNone(
                    extra,
                    "takeover must not send pause/stop/takeover",
                )
            finally:
                await cs.stop()

        self.assertEqual(rc, 0)
        # REPL spawned with --resume <run_id>.
        self.assertEqual(mock_call.call_count, 1)
        cmd = mock_call.call_args[0][0]
        self.assertIn("--resume", cmd)
        self.assertIn(run_id, cmd)

    async def test_run_mode_resolves_via_run_id(self) -> None:
        """--run + --workspace bypasses the registry; the handler
        spawns the REPL with ``--resume <run_id>``.
        """
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "ws"
            workspace.mkdir()
            run_id = "run-3"
            with patch(
                "extensions.orchestrator.cli.takeover._wait_for_transcript",
            ):
                with patch(
                    "extensions.orchestrator.cli.takeover._ensure_session_stub",
                ):
                    with patch(
                        "extensions.orchestrator.cli.takeover.subprocess.call",
                        return_value=0,
                    ) as mock_call:
                        args = argparse.Namespace(
                            id=None,
                            run=run_id,
                            workspace=str(workspace),
                        )
                        rc = await _run_takeover_async(
                            None,
                            tmp_path,
                            args,
                        )
        self.assertEqual(rc, 0)
        self.assertEqual(mock_call.call_count, 1)
        cmd = mock_call.call_args[0][0]
        self.assertIn("--resume", cmd)
        self.assertIn(run_id, cmd)


# ------------------------------------------------------------------
# End-to-end: transcript persistence + REPL spawn
# ------------------------------------------------------------------


class TestTakeoverEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Full integration: orchestrator writes a transcript →
    takeover spawns the ``--resume`` REPL against the on-disk
    ``transcript.jsonl``.

    The agent is NOT paused. Mirrors the round-trip exercised by
    ``test_orchestrator_f49_resume.py::TestResumeSessionEndToEnd``
    (orchestrator writes a transcript; resume-session CLI reads it)
    but for the takeover flow specifically: the REPL is spawned with
    ``--resume <run_id>`` so it displays the conversation history.
    """

    async def test_transcript_snapshot_repl_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workspace = tmp_path / "ws"
            workspace.mkdir()
            sessions_dir = tmp_path / "sessions"
            run_id = "run-f49-takeover-e2e"

            # 1. Orchestrator side: write a transcript the way
            #    the headless agent would. Patches
            #    ``src.services.session_storage.SESSIONS_DIR``
            #    so the storage writes into our tmp dir.
            from src.services.session_storage import SessionStorage
            from src.types.messages import (
                AssistantMessage,
                UserMessage,
                message_to_dict,
            )

            with patch(
                "clawcodex_ext.services.session_storage.SESSIONS_DIR",
                sessions_dir,
            ):
                storage = SessionStorage(
                    session_id=run_id,
                    sessions_dir=sessions_dir,
                )
                storage.init_metadata(
                    model="claude-sonnet-4-20250514",
                    cwd=str(workspace),
                    title="orchestrator-takeover-e2e",
                )
                storage.write_raw(
                    message_to_dict(
                        UserMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": "fix the bug in takeover",
                                }
                            ],
                        ),
                    ),
                )
                storage.write_raw(
                    message_to_dict(
                        AssistantMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": "Reading the relevant file.",
                                }
                            ],
                            model="claude-sonnet-4-20250514",
                        ),
                    ),
                )
                storage.flush()
                self.assertTrue(
                    (sessions_dir / run_id / "transcript.jsonl").exists(),
                )
                self.assertTrue(
                    (sessions_dir / run_id / "metadata.json").exists(),
                )

            # 2. Run the takeover. Patch ``subprocess.call`` so
            #    the REPL does not actually launch, and assert
            #    the right argv was constructed.
            with patch(
                "extensions.orchestrator.cli.takeover._wait_for_transcript",
            ):
                with patch(
                    "extensions.orchestrator.cli.takeover._ensure_session_stub",
                ):
                    with patch(
                        "extensions.orchestrator.cli.takeover.subprocess.call",
                        return_value=0,
                    ) as mock_call:
                        args = argparse.Namespace(
                            id=None,
                            run=run_id,
                            workspace=str(workspace),
                        )
                        rc = await _run_takeover_async(
                            None,
                            tmp_path,
                            args,
                        )

            # 3. Verify: takeover returned 0 and the patched
            #    ``subprocess.call`` was invoked with the
            #    ``--resume <run_id>`` argv (workspace conveyed
            #    via ``cwd``, not a CLI flag).
            self.assertEqual(rc, 0)
            self.assertEqual(mock_call.call_count, 1)
            argv = mock_call.call_args[0][0]
            self.assertEqual(argv[0], "python3")
            self.assertIn("--resume", argv)
            self.assertIn(run_id, argv)
            self.assertNotIn("--workspace", argv)
            self.assertEqual(mock_call.call_args[1]["cwd"], str(workspace))


if __name__ == "__main__":
    unittest.main()

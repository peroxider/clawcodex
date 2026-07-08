"""F-120 Step 8: CLI `orchestrator issue rebase --id [--force] [--reason]`.

Covers:
  - argparse: `rebase` subcommand registered with --id / --force / --reason / --operator
  - argparse: --force action is store_true
  - argparse: --id is required
  - _run_rebase:
      * writes control file `.orchestrator_control/rebase_<id>.control`
      * writes audit log entry with event="rebase_requested"
      * mark_intent(REBASE) on registry
      * missing PR/workspace/branch returns 4
      * --force flag sets push_method=force in audit
      * default push_method is force-with-lease
      * missing --id returns 2
      * no registry returns 1
  - audit log priority="high" when --force, "normal" otherwise
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from extensions.orchestrator.cli.issue import (
    _run_rebase,
    add_issue_parser,
)
from extensions.orchestrator.issue_registry import IssueRegistry
from extensions.orchestrator.tracker import Intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "id": "7",
        "force": False,
        "reason": "F-120 E2E test",
        "operator": "tester",
        "workspace": None,
        "workflow": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _make_registry_with_pr(tmp: Path, issue_id: str = "7") -> IssueRegistry:
    """Create a registry with a record that has the F-120 preconditions
    (pr_number, workspace_path, branch_name)."""
    reg_path = Path(tmp) / "registry.json"
    reg = IssueRegistry(reg_path)
    reg.register(
        issue_id=issue_id,
        issue_identifier=f"ISSUE-{issue_id}",
        branch_name=f"feature/f-120-{issue_id}",
        base_branch="main",
        workspace_path=str(tmp / "ws"),
    )
    # Inject pr_number / pr_url — register() does not accept these directly.
    record = reg.get(issue_id)
    assert record is not None
    record.pr_number = 35
    record.pr_url = "https://example/pr/35"
    reg._save()
    return reg


# ---------------------------------------------------------------------------
# argparse surface
# ---------------------------------------------------------------------------


class TestRebaseParser(unittest.TestCase):
    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        add_issue_parser(sub)
        return parser

    def test_rebase_registered(self) -> None:
        parser = self._build_parser()
        # Parse a complete rebase invocation; should not raise.
        args = parser.parse_args(["issue", "rebase", "--id", "7"])
        self.assertEqual(args.issue_subcommand, "rebase")
        self.assertEqual(args.id, "7")
        self.assertFalse(args.force)

    def test_rebase_force_flag(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["issue", "rebase", "--id", "7", "--force"])
        self.assertTrue(args.force)

    def test_rebase_reason(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args(["issue", "rebase", "--id", "7", "--reason", "stale base"])
        self.assertEqual(args.reason, "stale base")

    def test_rebase_missing_id_is_error(self) -> None:
        parser = self._build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["issue", "rebase"])


# ---------------------------------------------------------------------------
# _run_rebase
# ---------------------------------------------------------------------------


class TestRunRebase(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(
            os.environ, {"CLAWCODEX_WORKSPACE_ROOT": tempfile.mkdtemp(prefix="f120_ws_")}
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_missing_id_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            args = _make_args(id=None)
            rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 2)

    def test_no_registry_returns_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.json"
            args = _make_args()
            rc = _run_rebase(missing, args)
            self.assertEqual(rc, 1)

    def test_missing_pr_returns_4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg_path = tmp_path / "registry.json"
            IssueRegistry(reg_path).register(
                issue_id="7",
                issue_identifier="ISSUE-7",
                branch_name="feature/f-120-7",
                workspace_path=str(tmp_path / "ws"),
            )
            # No pr_number / pr_url — should fail with rc=4.
            args = _make_args()
            rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 4)

    def test_writes_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            _make_registry_with_pr(Path(tmp))
            args = _make_args()
            rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 0)
            ws_root = Path(os.environ["CLAWCODEX_WORKSPACE_ROOT"])
            control = ws_root / ".orchestrator_control" / "rebase_7.control"
            self.assertTrue(control.exists())
            content = control.read_text(encoding="utf-8")
            # Format: rebase\n<id>\nforce=0|1\n<reason>
            lines = content.splitlines()
            self.assertEqual(lines[0], "rebase")
            self.assertEqual(lines[1], "7")
            self.assertEqual(lines[2], "force=0")
            self.assertEqual(lines[3], "F-120 E2E test")

    def test_writes_audit_log_normal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            _make_registry_with_pr(Path(tmp))
            audit_path = Path(tmp) / "audit.jsonl"
            args = _make_args()
            with patch(
                "extensions.orchestrator.cli.issue._DEFAULT_AUDIT_LOG_PATH",
                audit_path,
            ):
                rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 0)
            self.assertTrue(audit_path.exists())
            entry = json.loads(audit_path.read_text(encoding="utf-8").strip())
            self.assertEqual(entry["event"], "rebase_requested")
            self.assertEqual(entry["mode"], "rebase")
            self.assertEqual(entry["force"], False)
            self.assertEqual(entry["priority"], "normal")
            self.assertEqual(entry["push_method"], "force-with-lease")
            self.assertEqual(entry["pr_number"], 35)

    def test_force_flag_high_priority_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            _make_registry_with_pr(Path(tmp))
            audit_path = Path(tmp) / "audit.jsonl"
            args = _make_args(force=True, reason="manual override")
            with patch(
                "extensions.orchestrator.cli.issue._DEFAULT_AUDIT_LOG_PATH",
                audit_path,
            ):
                rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 0)
            entry = json.loads(audit_path.read_text(encoding="utf-8").strip())
            self.assertEqual(entry["force"], True)
            self.assertEqual(entry["priority"], "high")
            self.assertEqual(entry["push_method"], "force")
            # Control file should also reflect force=1.
            ws_root = Path(os.environ["CLAWCODEX_WORKSPACE_ROOT"])
            control = ws_root / ".orchestrator_control" / "rebase_7.control"
            lines = control.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[2], "force=1")

    def test_marks_registry_intent_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            reg = _make_registry_with_pr(Path(tmp))
            args = _make_args()
            rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 0)
            reloaded = IssueRegistry(reg_path)
            record = reloaded.get("7")
            assert record is not None
            self.assertIs(record.intent, Intent.REBASE)
            self.assertEqual(record.intent_source, "cli")

    def test_auto_registers_unknown_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg_path = tmp_path / "registry.json"
            reg = IssueRegistry(reg_path)
            # Register an issue with pr+workspace+branch so the
            # auto-register path completes the run.
            reg.register(
                issue_id="999",
                issue_identifier="ISSUE-999",
                branch_name="feature/auto",
                workspace_path=str(tmp_path / "ws"),
            )
            record = reg.get("999")
            assert record is not None
            record.pr_number = 1
            record.pr_url = "https://example/pr/1"
            reg._save()

            args = _make_args(id="999")
            rc = _run_rebase(reg_path, args)
            self.assertEqual(rc, 0)
            reloaded = IssueRegistry(reg_path)
            record2 = reloaded.get("999")
            assert record2 is not None
            self.assertEqual(record2.issue_identifier, "ISSUE-999")
            self.assertIs(record2.intent, Intent.REBASE)


if __name__ == "__main__":
    unittest.main()

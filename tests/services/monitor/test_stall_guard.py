"""Tests for stall-watchdog exemption predicate."""

from __future__ import annotations

from clawcodex_ext.services.monitor.stall_guard import StallWatchdogExemptor
from src.tasks.local_shell import LocalShellTaskState


class TestStallWatchdogExemptor:
    def test_monitor_kind_skipped(self):
        state = LocalShellTaskState(
            id="b12345678",
            type="local_bash",
            status="running",
            description="x",
            start_time=0.0,
            output_file="/tmp/x",
            kind="monitor",
        )
        assert StallWatchdogExemptor.should_skip_stall_check(state) is True

    def test_shell_kind_not_skipped(self):
        state = LocalShellTaskState(
            id="b12345678",
            type="local_bash",
            status="running",
            description="x",
            start_time=0.0,
            output_file="/tmp/x",
            kind="shell",
        )
        assert StallWatchdogExemptor.should_skip_stall_check(state) is False

    def test_missing_kind_defaults_to_shell(self):
        # Simulate a legacy object without a ``kind`` field.
        class Legacy:
            pass

        assert StallWatchdogExemptor.should_skip_stall_check(Legacy()) is False

    def test_arbitrary_object_no_kind(self):
        assert StallWatchdogExemptor.should_skip_stall_check(None) is False
        assert StallWatchdogExemptor.should_skip_stall_check({"kind": "monitor"}) is True

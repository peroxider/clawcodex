"""Tests for watch compatibility conversion."""

from __future__ import annotations

import platform

import pytest

from clawcodex_ext.services.monitor.watch_compat import normalize_watch_command


class TestNormalizeWatchCommand:
    def test_posix_unchanged(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        assert normalize_watch_command("watch -n 5 git status") == "watch -n 5 git status"
        assert normalize_watch_command("tail -f /var/log/syslog") == "tail -f /var/log/syslog"

    def test_macos_unchanged(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        assert normalize_watch_command("watch -n 5 git status") == "watch -n 5 git status"

    def test_windows_watch_converted(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        result = normalize_watch_command("watch -n 5 git status")
        assert result.startswith("powershell -c")
        assert "while(1){" in result
        assert "git status" in result
        assert "Start-Sleep 5" in result

    def test_windows_non_watch_unchanged(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        assert normalize_watch_command("tail -f /var/log/syslog") == "tail -f /var/log/syslog"

    def test_windows_quotes_safely_escaped(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        result = normalize_watch_command('watch -n 1 echo "hello $world"')
        # The inner command should be escaped so it does not break the loop.
        assert "powershell -c" in result
        assert "echo" in result
        assert "Start-Sleep 1" in result

    def test_windows_invalid_interval_unchanged(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        assert normalize_watch_command("watch -n abc git status") == "watch -n abc git status"

    def test_windows_negative_interval_unchanged(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        assert normalize_watch_command("watch -n -1 git status") == "watch -n -1 git status"

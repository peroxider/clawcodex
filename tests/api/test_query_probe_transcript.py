"""``QueryRunner.probe_transcript`` static method.

The orchestrator's clawcodex backend calls this static method during
``probe_resume`` to decide whether a resume target is reachable. The
probe must mirror the validation the CLI's ``--resume`` flag performs
(direct directory hit at ``resolve_sessions_dir() / <session_id>``,
then a tag-prefix fallback via ``SessionStorage.list_sessions``) and
never raise — failures are reported as ``False`` so the caller can map
to ``ResumeStatus.REJECTED`` / ``UNDETECTABLE``.

These tests pin both paths plus the swallow-on-exception contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from extensions.api.query import QueryRunner
from clawcodex_ext.services import session_storage as storage_mod


def _seed_session(sessions_dir: Path, session_id: str, *, tags: list[str] | None = None) -> Path:
    """Create a session directory with metadata.json so list_sessions picks it up."""
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "session_id": session_id,
        "start_time": 1700000000.0,
        "model": "test-model",
        "title": "",
        "message_count": 0,
        "last_updated": 1700000001.0,
        "tags": list(tags or []),
    }
    (session_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return session_dir


# ----------------------------------------------------------------------
# Direct directory hit — same check the CLI's --resume performs
# ----------------------------------------------------------------------


def test_probe_transcript_returns_true_for_direct_directory_hit() -> None:
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)
        _seed_session(sessions_dir, "abc-123")

        with patch.object(storage_mod, "resolve_sessions_dir", return_value=sessions_dir):
            assert QueryRunner.probe_transcript("abc-123") is True


def test_probe_transcript_returns_false_when_directory_missing() -> None:
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)

        with patch.object(storage_mod, "resolve_sessions_dir", return_value=sessions_dir):
            assert QueryRunner.probe_transcript("does-not-exist") is False


# ----------------------------------------------------------------------
# Tag-prefix fallback — matches CLI --resume semantics
# ----------------------------------------------------------------------


def test_probe_transcript_falls_back_to_tag_prefix() -> None:
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)
        _seed_session(sessions_dir, "real-session-id", tags=["cron:task:build"])

        with patch.object(storage_mod, "resolve_sessions_dir", return_value=sessions_dir):
            assert QueryRunner.probe_transcript("cron:task:build") is True


def test_probe_transcript_returns_false_when_tag_prefix_has_no_match() -> None:
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)
        _seed_session(sessions_dir, "real-session-id", tags=["other:tag"])

        with patch.object(storage_mod, "resolve_sessions_dir", return_value=sessions_dir):
            assert QueryRunner.probe_transcript("cron:task:build") is False


# ----------------------------------------------------------------------
# Empty / whitespace session_id short-circuit
# ----------------------------------------------------------------------


@pytest.mark.parametrize("empty", ["", "   ", "\t\n"])
def test_probe_transcript_returns_false_for_empty_session_id(empty: str) -> None:
    """An empty/blank session id has no transcript to probe — short-circuit
    to False without touching the filesystem."""
    # Should not even attempt to resolve sessions dir.
    assert QueryRunner.probe_transcript(empty) is False


# ----------------------------------------------------------------------
# workspace kwarg is accepted but advisory (clawcodex storage is global)
# ----------------------------------------------------------------------


def test_probe_transcript_accepts_workspace_kwarg() -> None:
    """The orchestrator passes ``workspace=self._spec.cwd``. Clawcodex's
    session storage is global (single ``resolve_sessions_dir()``), so
    ``workspace`` is currently advisory — the probe still uses the
    env-resolved sessions dir. This test pins that contract so a future
    change to per-workspace storage surfaces here.
    """
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)
        _seed_session(sessions_dir, "abc-123")

        with patch.object(storage_mod, "resolve_sessions_dir", return_value=sessions_dir):
            assert (
                QueryRunner.probe_transcript(
                    "abc-123", workspace="/some/other/workspace"
                )
                is True
            )


# ----------------------------------------------------------------------
# Swallow-on-exception contract — the probe must never raise
# ----------------------------------------------------------------------


def test_probe_transcript_returns_false_when_resolve_sessions_dir_raises() -> None:
    def _boom() -> Path:
        raise OSError("disk on fire")

    with patch.object(storage_mod, "resolve_sessions_dir", side_effect=_boom):
        assert QueryRunner.probe_transcript("abc-123") is False


def test_probe_transcript_returns_false_when_list_sessions_raises() -> None:
    """The tag-prefix fallback (``SessionStorage.list_sessions``) can
    fail on a corrupted metadata.json or a permission error. The probe
    must swallow it and return False — never raise."""
    with TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp)

        def _boom_list(**_kwargs):  # noqa: ANN001
            raise OSError("metadata.json unreadable")

        with patch.object(
            storage_mod, "resolve_sessions_dir", return_value=sessions_dir
        ), patch.object(
            storage_mod.SessionStorage,
            "list_sessions",
            staticmethod(_boom_list),
        ):
            assert QueryRunner.probe_transcript("abc-123") is False


# ----------------------------------------------------------------------
# Static method — must be callable without an instance
# ----------------------------------------------------------------------


def test_probe_transcript_is_callable_on_class_directly() -> None:
    """The orchestrator calls ``QueryRunner.probe_transcript(...)`` —
    i.e. on the class, not on an instance. Pin that the method is
    static so a future refactor to ``classmethod``/instance method
    doesn't silently break the call site without a test failure."""
    assert isinstance(
        QueryRunner.__dict__["probe_transcript"], staticmethod
    )

"""Tests for clawcodex_ext.services.lodestone.resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawcodex_ext.services.lodestone.config import default_config
from clawcodex_ext.services.lodestone.models import (
    AnchorContext,
    AnchorTarget,
    LodestoneAnchor,
    LodestoneConfig,
)
from clawcodex_ext.services.lodestone.resolver import (
    AnchorResolver,
    _guard_path,
    probe_editor_from_env,
)
from clawcodex_ext.services.lodestone.targets import build_default_registry


# ---------------------------------------------------------------------------
# path-traversal guard
# ---------------------------------------------------------------------------


def test_guard_path_rejects_traversal(tmp_path: Path):
    cfg = LodestoneConfig()
    ctx = AnchorContext(workspace_root=tmp_path, session_id=None, config=cfg)
    bad = LodestoneAnchor(kind="file_path", raw="", file_path="../../etc/passwd")
    ok, reason = _guard_path(bad, ctx)
    assert not ok
    assert "workspace_root" in (reason or "")


def test_guard_path_allows_inside(tmp_path: Path):
    cfg = LodestoneConfig()
    ctx = AnchorContext(workspace_root=tmp_path, session_id=None, config=cfg)
    good = LodestoneAnchor(kind="file_path", raw="", file_path="src/foo.py")
    ok, _ = _guard_path(good, ctx)
    assert ok


def test_guard_path_no_workspace_root():
    cfg = LodestoneConfig()
    ctx = AnchorContext(workspace_root=None, session_id=None, config=cfg)
    a = LodestoneAnchor(kind="file_path", raw="", file_path="src/foo.py")
    ok, reason = _guard_path(a, ctx)
    assert ok
    # Reason is advisory; caller may surface it.
    assert reason == "no workspace_root; path not verified"

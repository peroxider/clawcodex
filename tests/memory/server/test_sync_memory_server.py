from __future__ import annotations

from pathlib import Path

import pytest

from scripts import sync_memory_server as sync


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_render_source_rewrites_namespace_and_excludes_tests(tmp_path: Path) -> None:
    source = tmp_path / "improved_memory_server"
    _write(source / "__init__.py", "")
    _write(
        source / "feature.py",
        "from improved_memory_server import helper\nVALUE = 'improved_memory_server'\n",
    )
    _write(source / "tests" / "test_feature.py", "raise RuntimeError('must not copy')\n")
    _write(source / "lib" / "tests" / "test_nested.py", "raise RuntimeError('must not copy')\n")

    rendered = sync.render_source(source)

    assert set(rendered) == {"__init__.py", "feature.py"}
    feature = rendered["feature.py"].content.decode("utf-8")
    assert "from clawcodex_ext.latent_memory.server import helper" in feature
    assert "improved_memory_server" not in feature


def test_validate_tree_rejects_missing_internal_export(tmp_path: Path) -> None:
    _write(tmp_path / "__init__.py", "")
    _write(
        tmp_path / "consumer.py",
        "from clawcodex_ext.latent_memory.server.provider import missing\n",
    )
    _write(tmp_path / "provider.py", "present = 1\n")

    with pytest.raises(sync.SyncError, match="has no exported name missing"):
        sync.validate_tree(tmp_path)


def test_make_plan_preserves_target_only_files(tmp_path: Path) -> None:
    _write(tmp_path / "same.py", "same\n")
    _write(tmp_path / "changed.py", "old\n")
    _write(tmp_path / "daemon.py", "claw-only\n")
    _write(tmp_path / "lib" / "solidification" / "migrate.py", "obsolete\n")
    rendered = {
        "same.py": sync.RenderedFile("same.py", (tmp_path / "same.py").read_bytes()),
        "changed.py": sync.RenderedFile("changed.py", b"new\n"),
        "new.py": sync.RenderedFile("new.py", b"new\n"),
    }

    plan = sync.make_plan(rendered, tmp_path)

    assert plan.new == ("new.py",)
    assert plan.changed == ("changed.py",)
    assert plan.unchanged == ("same.py",)
    assert plan.target_only == ("daemon.py",)
    assert plan.removed == ("lib/solidification/migrate.py",)


@pytest.mark.skipif(
    not sync.DEFAULT_SOURCE.is_dir(),
    reason="the sibling memory-benchmarks checkout is not available",
)
def test_current_source_renders_with_clawcodex_adaptations(tmp_path: Path) -> None:
    """Guard the exact adapter contract against changes in the development checkout."""
    rendered = sync.render_source(sync.DEFAULT_SOURCE)

    assert "lib/validity/store.py" in rendered
    assert not any("/tests/" in f"/{path}/" for path in rendered)
    config = rendered["config.py"].content.decode("utf-8")
    mcp_server = rendered["mcp_server.py"].content.decode("utf-8")
    projection = rendered["lib/solidification/projection.py"].content.decode("utf-8")
    assert "def load_validity_config" in config
    assert "CLAWCODEX_MEMORY_STATE_DIR" in config
    assert "if path is not None and path.exists():" in config
    assert 'DEFAULT_MEM0_HOST = "http://127.0.0.1:8888"' in mcp_server
    assert "clawcodex-dev memory enable" in mcp_server
    assert '/ "solidification"' in projection

    target = tmp_path / "server"
    _write(target / "daemon.py", "")
    with sync.tempfile.TemporaryDirectory(prefix="sync-test-") as temporary:
        staged = sync.stage_tree(rendered, target, Path(temporary))
        sync.validate_tree(staged)

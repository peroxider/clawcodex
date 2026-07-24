"""Tests for :mod:`upstream_sync.core.vendor`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from upstream_sync.config import UpstreamConfig
from upstream_sync.core.vendor import VendorManager, short_commit_id


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repositories(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create independent canonical-source and downstream repositories."""

    source = tmp_path / "canonical-source"
    downstream = tmp_path / "downstream"
    source.mkdir()
    downstream.mkdir()

    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "upstream-sync@example.test")
    _git(source, "config", "user.name", "upstream-sync tests")
    (source / "src").mkdir()
    (source / "src" / "feature.py").write_text("VALUE = 'canonical'\n", encoding="utf-8")
    (source / "README.md").write_text("outside source subtree\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "canonical source")
    source_commit = _git(source, "rev-parse", "HEAD")

    _git(downstream, "init", "-b", "main")
    _git(downstream, "config", "user.email", "downstream@example.test")
    _git(downstream, "config", "user.name", "downstream tests")
    (downstream / "src").mkdir()
    (downstream / "src" / "feature.py").write_text("VALUE = 'downstream'\n", encoding="utf-8")
    _git(downstream, "add", ".")
    _git(downstream, "commit", "-m", "downstream source")
    return source, downstream, source_commit


def _config(source: Path, *, remote_name: str = "source-upstream") -> UpstreamConfig:
    return UpstreamConfig(
        remote_url=str(source),
        remote_name=remote_name,
        main_branch="main",
        vendor_branch="upstream/vendor",
        version_tag_format="upstream/v{YYYY}_{MM}",
    )


class TestShortCommitId:
    def test_shortens_full_sha_to_project_convention(self) -> None:
        assert short_commit_id("0573f4c6a6663a60eaada4decf5915da7c5c60b2") == "0573f4c"

    def test_leaves_symbolic_ref_untouched(self) -> None:
        assert short_commit_id("release/main") == "release/main"


class TestVendorManager:
    def test_ensure_remote_adds_configured_remote(
        self, git_repositories: tuple[Path, Path, str]
    ) -> None:
        source, downstream, _ = git_repositories
        vendor = VendorManager(downstream, _config(source))

        vendor.ensure_remote()

        assert _git(downstream, "remote", "get-url", "source-upstream") == str(source)

    def test_ensure_remote_rejects_url_mismatch(
        self, git_repositories: tuple[Path, Path, str], tmp_path: Path
    ) -> None:
        source, downstream, _ = git_repositories
        wrong_source = tmp_path / "wrong-source"
        wrong_source.mkdir()
        _git(downstream, "remote", "add", "source-upstream", str(wrong_source))
        vendor = VendorManager(downstream, _config(source))

        with pytest.raises(RuntimeError, match="points to"):
            vendor.ensure_remote()

    def test_fetch_and_fetch_ref_return_exact_commit(
        self, git_repositories: tuple[Path, Path, str]
    ) -> None:
        source, downstream, source_commit = git_repositories
        vendor = VendorManager(downstream, _config(source))
        vendor.ensure_remote()

        assert vendor.fetch() == source_commit
        # A raw SHA is represented by FETCH_HEAD, not source-upstream/<sha>.
        assert vendor.fetch_ref(source_commit) == source_commit

    def test_extract_prefers_canonical_remote_branch_over_local_branch(
        self, git_repositories: tuple[Path, Path, str]
    ) -> None:
        source, downstream, _ = git_repositories
        vendor = VendorManager(downstream, _config(source))
        vendor.ensure_remote()
        vendor.fetch()
        target = downstream / "snapshot"

        vendor.extract_to_path("main", "src", target)

        assert (target / "feature.py").read_text(encoding="utf-8") == "VALUE = 'canonical'\n"
        assert not (target / "README.md").exists()

    @pytest.mark.parametrize("use_archive", [True, False])
    def test_extract_replaces_snapshot_without_leaving_stale_files(
        self,
        git_repositories: tuple[Path, Path, str],
        use_archive: bool,
    ) -> None:
        source, downstream, _ = git_repositories
        vendor = VendorManager(downstream, _config(source))
        vendor.ensure_remote()
        vendor.fetch()
        target = downstream / "snapshot"
        target.mkdir()
        (target / "stale.py").write_text("stale = True\n", encoding="utf-8")

        vendor.extract_to_path("main", "src", target, use_archive=use_archive)

        assert (target / "feature.py").read_text(encoding="utf-8") == "VALUE = 'canonical'\n"
        assert not (target / "stale.py").exists()

    def test_extract_failure_keeps_previous_snapshot(
        self, git_repositories: tuple[Path, Path, str]
    ) -> None:
        source, downstream, _ = git_repositories
        vendor = VendorManager(downstream, _config(source))
        vendor.ensure_remote()
        vendor.fetch()
        target = downstream / "snapshot"
        target.mkdir()
        sentinel = target / "keep.py"
        sentinel.write_text("keep = True\n", encoding="utf-8")

        with pytest.raises(subprocess.CalledProcessError):
            vendor.extract_to_path("main", "missing-subpath", target)

        assert sentinel.read_text(encoding="utf-8") == "keep = True\n"

    def test_detect_sync_refs_uses_configured_remote(
        self, git_repositories: tuple[Path, Path, str]
    ) -> None:
        source, downstream, _ = git_repositories
        vendor = VendorManager(downstream, _config(source))
        vendor.ensure_remote()
        vendor.fetch()

        previous, latest = vendor.detect_sync_refs()

        assert previous == "source-upstream/main"
        assert latest == "source-upstream/main"

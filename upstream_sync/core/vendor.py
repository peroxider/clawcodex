# upstream_sync/core/vendor.py
"""Vendor branch management.

Mirrors upstream code into a local, read-only vendor branch and maintains
version-lock tags.  Zero business awareness — purely mechanical Git ops.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final

from upstream_sync.config import UpstreamConfig


HEX_COMMIT_LENGTH: Final[int] = 7


def short_commit_id(commit: str, length: int = HEX_COMMIT_LENGTH) -> str:
    """Return the stable directory key used for an upstream commit.

    Snapshot and patch directories intentionally use seven hexadecimal
    characters (``src/upstream/0573f4c``), regardless of whether callers pass
    a full SHA or an already-short SHA.  Symbolic refs are left untouched so
    the helper remains safe for generic CLI inputs.
    """

    value = commit.strip()
    if len(value) >= length and all(ch in "0123456789abcdefABCDEF" for ch in value):
        return value[:length].lower()
    return value


def _is_hex_commit(value: str) -> bool:
    return len(value) >= HEX_COMMIT_LENGTH and all(ch in "0123456789abcdefABCDEF" for ch in value)


class VendorManager:
    """Manages upstream remote, fetch, tags, and the vendor branch."""

    def __init__(self, repo_root: Path, upstream: UpstreamConfig) -> None:
        self.repo_root = repo_root
        self.cfg = upstream

    @property
    def remote_name(self) -> str:
        """Configured local remote name (kept in one place for all git ops)."""

        return self.cfg.remote_name

    def _remote_ref(self, ref: str) -> str:
        """Return a remote-tracking ref for a branch-like input."""

        if ref.startswith(f"{self.remote_name}/") or ref.startswith("refs/"):
            return ref
        return f"{self.remote_name}/{ref}"

    def _rev_parse(self, ref: str) -> str | None:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _resolve_fetched_ref(self, ref: str, *, prefer_fetch_head: bool = False) -> str:
        """Resolve a ref to a full commit SHA after a fetch.

        ``git fetch <remote> <40-char-sha>`` records the object in
        ``FETCH_HEAD`` but does not create ``<remote>/<sha>``.  The old
        implementation assumed the latter and therefore failed for the exact
        commit IDs used by the snapshot workflow.
        """

        candidates: list[str] = []
        if prefer_fetch_head:
            candidates.append("FETCH_HEAD")
        # A bare branch such as ``main`` may also exist in the downstream
        # repository.  Prefer the canonical remote-tracking branch in that
        # case; exact hexadecimal commits can be resolved directly.
        if _is_hex_commit(ref) or ref.startswith("refs/"):
            candidates.extend([ref, self._remote_ref(ref)])
        else:
            candidates.extend([self._remote_ref(ref), ref])
        if not prefer_fetch_head:
            candidates.append("FETCH_HEAD")
        for candidate in candidates:
            resolved = self._rev_parse(candidate)
            if resolved:
                return resolved
        raise RuntimeError(
            f"Could not resolve fetched ref {ref!r} using remote {self.remote_name!r}."
        )

    # ------------------------------------------------------------------
    # Remote lifecycle
    # ------------------------------------------------------------------

    def ensure_remote(self) -> None:
        """Ensure the configured remote exists and points at the right URL.

        Existing remotes are never silently repointed: a typo here can make a
        sync appear successful while importing a completely different code
        base.  Configure a distinct ``remote_name`` when a repository already
        has an ``upstream`` remote for another purpose.
        """

        result = subprocess.run(
            ["git", "remote", "get-url", self.remote_name],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "remote", "add", self.remote_name, self.cfg.remote_url],
                cwd=self.repo_root,
                check=True,
            )
            return

        configured = result.stdout.strip()

        # Git accepts harmless spelling variants (trailing slash and .git),
        # so compare a normalised form while retaining the user's URL in the
        # error message.
        def normalise(url: str) -> str:
            return url.rstrip("/").removesuffix(".git").lower()

        if normalise(configured) != normalise(self.cfg.remote_url):
            raise RuntimeError(
                f"Git remote {self.remote_name!r} points to {configured!r}, "
                f"but upstream-sync.yaml specifies {self.cfg.remote_url!r}. "
                f"Choose another remote_name or fix the remote explicitly."
            )

    def fetch(self) -> str:
        """Fetch upstream main and return the latest commit hash."""
        subprocess.run(
            ["git", "fetch", self.remote_name, self.cfg.main_branch],
            cwd=self.repo_root,
            check=True,
        )
        return self._resolve_fetched_ref(self.cfg.main_branch)

    def fetch_ref(self, ref: str) -> str:
        """Fetch a specific ref (commit, tag, or branch) from upstream.

        Args:
            ref: Specific git ref (commit hash, tag, or branch name).

        Returns:
            The full commit hash that was fetched.
        """
        result = subprocess.run(
            ["git", "fetch", self.remote_name, ref],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # A commit that is already present locally can still be used (for
            # example after a shallow/partial clone); otherwise surface the
            # original fetch failure with its stderr.
            local = self._rev_parse(ref)
            if local:
                return local
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return self._resolve_fetched_ref(ref, prefer_fetch_head=True)

    def extract_to_path(
        self,
        ref: str,
        subpath: str,
        target_path: Path,
        use_archive: bool = True,
    ) -> None:
        """Extract a sub-path from a fetched upstream ref to a target directory.

        Args:
            ref: The upstream ref (commit hash, tag, or branch).
            subpath: Sub-directory within the upstream repo to extract (e.g. "src").
                     The extracted contents are placed DIRECTLY into target_path,
                     NOT into target_path/subpath/. This means target_path should
                     be the destination for the subpath contents themselves.
            target_path: Local directory to extract the sub-path contents into.
                         For example, extract_to_path("abc123", "src", Path("src/upstream/abc123"))
                         extracts upstream/src/* -> src/upstream/abc123/* (NOT src/upstream/abc123/src/*).
            use_archive: If True, use git archive for efficient extraction.
                         If False, use git checkout.
        """
        import io
        import shutil
        import tarfile
        import tempfile

        upstream_ref = self._resolve_fetched_ref(ref)
        target_path = target_path.resolve()
        repo_root = self.repo_root.resolve()
        if target_path == repo_root or target_path == repo_root / ".git":
            raise ValueError(f"Refusing to replace unsafe snapshot target: {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the complete snapshot away from the destination.  Only after
        # archive creation and extraction succeed do we replace the previous
        # directory.  This prevents both stale files and half-written
        # snapshots when a fetch/archive operation fails.
        with tempfile.TemporaryDirectory(
            dir=target_path.parent, prefix=f".{target_path.name}-extract-"
        ) as tmpdir:
            temporary_root = Path(tmpdir)
            staged = temporary_root / "snapshot"
            staged.mkdir()
            archive_args = ["git", "archive", "--format=tar", upstream_ref, subpath]

            if use_archive:
                proc = subprocess.run(
                    archive_args,
                    cwd=self.repo_root,
                    capture_output=True,
                    check=True,
                )
                archive = tarfile.open(fileobj=io.BytesIO(proc.stdout))
            else:
                archive_path = temporary_root / "snapshot.tar"
                with archive_path.open("wb") as archive_file:
                    subprocess.run(
                        archive_args,
                        cwd=self.repo_root,
                        stdout=archive_file,
                        check=True,
                    )
                archive = tarfile.open(archive_path)

            with archive:
                members = [m for m in archive.getmembers() if m.name.startswith(f"{subpath}/")]
                for member in members:
                    # Strip the subpath/ prefix so contents go directly into
                    # the snapshot root.
                    member.name = member.name[len(subpath) + 1 :]
                    if member.name:
                        archive.extract(member, staged)

            previous = temporary_root / "previous"
            if target_path.exists():
                target_path.replace(previous)
            try:
                staged.replace(target_path)
            except Exception:
                if previous.exists() and not target_path.exists():
                    previous.replace(target_path)
                raise
            if previous.exists():
                shutil.rmtree(previous)

    # ------------------------------------------------------------------
    # Version tags
    # ------------------------------------------------------------------

    def create_version_tag(self, version: str, commit: str) -> None:
        """Create a version lock tag (e.g. upstream/v2025_06)."""
        dt = datetime.strptime(version, "%Y.%m.%d")
        tag = self.cfg.version_tag_format.format(YYYY=dt.year, MM=f"{dt.month:02d}")
        subprocess.run(
            ["git", "tag", tag, commit],
            cwd=self.repo_root,
            check=True,
        )

    def list_version_tags(self) -> list[str]:
        """Return all locally-created upstream version tags."""
        result = subprocess.run(
            ["git", "tag", "--list", "upstream/*"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
        return tags

    # ------------------------------------------------------------------
    # Vendor branch
    # ------------------------------------------------------------------

    def checkout_vendor(self) -> None:
        """Switch to the vendor branch, creating it if necessary."""
        result = subprocess.run(
            ["git", "branch", "--list", self.cfg.vendor_branch],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            subprocess.run(
                ["git", "checkout", "-b", self.cfg.vendor_branch],
                cwd=self.repo_root,
                check=True,
            )
        else:
            subprocess.run(
                ["git", "checkout", self.cfg.vendor_branch],
                cwd=self.repo_root,
                check=True,
            )

    def reset_vendor_to_upstream(self, commit: str | None = None) -> None:
        """Hard-reset vendor branch to the given upstream commit (default: FETCH_HEAD)."""
        ref = commit or self._remote_ref(self.cfg.main_branch)
        subprocess.run(
            ["git", "checkout", self.cfg.vendor_branch],
            cwd=self.repo_root,
            check=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", ref],
            cwd=self.repo_root,
            check=True,
        )

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def detect_sync_refs(self) -> tuple[str, str]:
        """Detect the previous and latest upstream refs for sync.

        Returns:
            A tuple ``(previous_ref, latest_ref)`` where:
            - *previous_ref* is the newest local ``upstream/v*`` tag,
              or ``upstream/vendor`` branch tip if no tags exist.
            - *latest_ref* is ``upstream/<main_branch>`` (the current upstream head).

        Raises:
            RuntimeError: If the upstream remote has never been fetched.
        """
        # Ensure we have something to compare against
        upstream_ref = self._remote_ref(self.cfg.main_branch)
        result = subprocess.run(
            ["git", "rev-parse", upstream_ref],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Upstream remote '{upstream_ref}' not found. Run 'upstream-sync fetch' first."
            )
        latest_ref = upstream_ref

        # Find the newest local upstream/* tag
        tags = self.list_version_tags()
        if tags:
            # Sort tags lexicographically (tags follow upstream/vYYYY_MM format)
            latest_tag = sorted(tags)[-1]
            previous_ref = latest_tag
        else:
            # Fall back to vendor branch
            vb = self.cfg.vendor_branch
            result = subprocess.run(
                ["git", "rev-parse", vb],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                previous_ref = vb
            else:
                # No tags and no vendor branch — use upstream main as both
                # (first sync will show all files as new)
                previous_ref = latest_ref

        return previous_ref, latest_ref

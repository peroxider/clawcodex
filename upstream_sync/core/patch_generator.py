# upstream_sync/core/patch_generator.py
"""Generate new patches by analyzing upstream diff and old patches.

This module provides the logic to generate new patches for an upstream commit
(456def) by understanding the transformation patterns from old patches (123abc).

Path Convention
==============
All patches are generated with paths relative to the upstream source_subpath
(e.g. "src"). The patch diff header uses paths like:
    diff --git a/bridge/__init__.py b/bridge/__init__.py
NOT:
    diff --git a/src/bridge/__init__.py b/src/bridge/__init__.py

This means patches are applied directly to the extracted upstream source
at src/upstream/{commit_id}/, where the extracted directory already contains
the source_subpath contents (e.g., src/upstream/68dc3c5/bridge/__init__.py).

When comparing two upstream commits (old vs new), the source_subpath prefix
is stripped from all paths so patches use consistent, subpath-relative paths.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from upstream_sync.config import ProjectConfig, PatchConfig


@dataclass
class PatchDiff:
    """Represents the diff between two versions of a file."""

    path: str
    old_version: str
    new_version: str
    is_new: bool = False
    is_deleted: bool = False


@dataclass
class GeneratedPatch:
    """A generated patch with metadata."""

    filename: str
    content: str
    source_file: str
    patch_type: str  # 'modify' | 'add' | 'delete'


# ---------------------------------------------------------------------------
# Regeneration (strict reconstruction) types
# ---------------------------------------------------------------------------


@dataclass
class RegeneratePatch:
    """An individual patch entry during regeneration."""

    filename: str
    relative_path: str
    patch_type: str  # 'modified' | 'new' | 'deleted'


@dataclass
class RegenerateResult:
    """Result of a patch regeneration run (strict reconstruction).

    Models the invariant::

        src/upstream/{commit} + patches/upstream/{commit}/series == src/
    """

    patch_entries: list[RegeneratePatch] = field(default_factory=list)
    modified_count: int = 0
    new_count: int = 0
    deleted_count: int = 0
    preserved_count: int = 0
    preserved_files: set[str] = field(default_factory=set)
    patch_dir: Path | None = None
    series_file: Path | None = None
    compatibility_series_file: Path | None = None
    total_size: int = 0


# Default skip rules for file collection
REGENERATE_SKIP_DIRS: set[str] = {"__pycache__"}
REGENERATE_SKIP_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")
REGENERATE_SKIP_PREFIXES: tuple[str, ...] = ("upstream/", "orchestrator/")


class PatchGenerator:
    """Generates patches for new upstream commits based on old patch patterns."""

    def __init__(self, repo_root: Path, config: ProjectConfig) -> None:
        self.repo_root = repo_root
        self.cfg = config

    def generate_patches(
        self,
        new_commit: str,
        old_commit: str,
        patch_subdir: Path,
    ) -> list[GeneratedPatch]:
        """Generate patches for new_commit based on old_commit patches.

        Args:
            new_commit: The new upstream commit hash.
            old_commit: The old upstream commit hash to reference.
            patch_subdir: Directory to write generated patches to.

        Returns:
            List of GeneratedPatch objects.
        """
        # 1. Get diff between old and new upstream commits
        upstream_diff = self._get_upstream_diff(old_commit, new_commit)
        if not upstream_diff:
            return []

        # 2. Analyze old patches to understand transformation patterns
        old_patches_dir = self._resolve_patch_dir(old_commit)
        old_patch_patterns = self._analyze_old_patches(old_patches_dir)

        # 3. Generate new patches
        generated = []
        patch_subdir.mkdir(parents=True, exist_ok=True)

        for diff in upstream_diff:
            if diff.is_deleted:
                continue

            # Check if this file was modified in old patches
            if diff.path in old_patch_patterns:
                pattern = old_patch_patterns[diff.path]
                new_patch_content = self._transform_patch(diff, pattern, old_commit, new_commit)
            else:
                # For new files, create a simple patch
                new_patch_content = self._create_simple_patch(diff, new_commit)

            if new_patch_content:
                filename = self._generate_patch_filename(diff, new_commit)
                patch_path = patch_subdir / filename
                patch_path.write_text(new_patch_content, encoding="utf-8")
                generated.append(
                    GeneratedPatch(
                        filename=filename,
                        content=new_patch_content,
                        source_file=diff.path,
                        patch_type="add" if diff.is_new else "modify",
                    )
                )

        return generated

    def _get_upstream_diff(self, old_commit: str, new_commit: str) -> list[PatchDiff]:
        """Get file diffs between two upstream commits.

        All returned paths are relative to source_subpath (e.g. "src").
        The source_subpath prefix is stripped from paths, so a file like
        "src/bridge/__init__.py" becomes "bridge/__init__.py" in the diff.
        """
        result = subprocess.run(
            ["git", "diff", f"{old_commit}..{new_commit}", "--", self.cfg.upstream.source_subpath],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return []

        diffs = []
        current_file = None
        old_lines = []
        new_lines = []
        is_new = False
        is_deleted = False

        for line in result.stdout.splitlines():
            if line.startswith("diff --git"):
                # Save previous file diff
                if current_file:
                    diffs.append(
                        PatchDiff(
                            path=current_file,
                            old_version="\n".join(old_lines),
                            new_version="\n".join(new_lines),
                            is_new=is_new,
                            is_deleted=is_deleted,
                        )
                    )
                # Parse new file path from "b/<path>" part
                # e.g., "diff --git a/src/bridge/__init__.py b/src/bridge/__init__.py"
                parts = line.split(" b/")
                if len(parts) == 2:
                    raw_path = parts[1].split(" ")[0] if " " in parts[1] else parts[1]
                    # Strip source_subpath prefix so paths are relative to extracted upstream root
                    # e.g., "src/bridge/__init__.py" -> "bridge/__init__.py"
                    subpath = self.cfg.upstream.source_subpath
                    if raw_path.startswith(f"{subpath}/"):
                        current_file = raw_path[len(subpath) + 1 :]
                    else:
                        current_file = raw_path
                old_lines = []
                new_lines = []
                is_new = "new file mode" in line
                is_deleted = "deleted file mode" in line
            elif line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                old_lines.append(line[1:])
            elif line.startswith("@@"):
                # Reset for hunk header
                old_lines = []
                new_lines = []

        # Save last file
        if current_file:
            diffs.append(
                PatchDiff(
                    path=current_file,
                    old_version="\n".join(old_lines),
                    new_version="\n".join(new_lines),
                    is_new=is_new,
                    is_deleted=is_deleted,
                )
            )

        return diffs

    def _analyze_old_patches(self, old_patches_dir: Path) -> dict[str, str]:
        """Analyze old patches to understand transformation patterns.

        Returns a dict mapping file paths (relative to source_subpath) to their
        patch content. Paths in patches have source_subpath prefix stripped, so
        a patch for "src/bridge/__init__.py" is stored under key "bridge/__init__.py".
        """
        patterns = {}
        if not old_patches_dir.exists():
            return patterns

        subpath = self.cfg.upstream.source_subpath
        for patch_file in old_patches_dir.glob("*.patch"):
            content = patch_file.read_text(encoding="utf-8")
            # Extract the source file from patch header
            # Format: "diff --git a/bridge/__init__.py b/bridge/__init__.py"
            # or: "--- a/src/bridge/__init__.py"
            for line in content.splitlines():
                if line.startswith("diff --git"):
                    # Extract "b/<path>" or "a/<path>"
                    if " b/" in line:
                        src = line.split(" b/")[1].split(" ")[0]
                    elif " a/" in line:
                        src = line.split(" a/")[1].split(" ")[0]
                    else:
                        continue
                    # Strip source_subpath prefix if present
                    if src.startswith(f"{subpath}/"):
                        src = src[len(subpath) + 1 :]
                    patterns[src] = content
                    break
                elif line.startswith("--- a/") or line.startswith("+++ b/"):
                    # Extract path after a/ or b/
                    prefix = "--- a/" if line.startswith("--- a/") else "+++ b/"
                    src = line[len(prefix) :].split(" ")[0]
                    # Strip source_subpath prefix if present
                    if src.startswith(f"{subpath}/"):
                        src = src[len(subpath) + 1 :]
                    patterns[src] = content
                    break

        return patterns

    def _transform_patch(
        self,
        diff: PatchDiff,
        pattern: str,
        old_commit: str,
        new_commit: str,
    ) -> str | None:
        """Transform an old patch pattern to match new upstream changes."""
        if not pattern:
            return None

        # Paths in patches are already relative to source_subpath root,
        # so we generate new patches with simple a/<path> b/<path> format.
        return self._create_unified_patch(diff, new_commit)

    def _create_simple_patch(self, diff: PatchDiff, commit: str) -> str:
        """Create a simple patch for a file change."""
        return self._create_unified_patch(diff, commit)

    def _create_unified_patch(self, diff: PatchDiff, commit: str) -> str:
        """Create a unified diff patch with source_subpath-relative paths.

        Paths in the patch header use the format:
            diff --git a/bridge/__init__.py b/bridge/__init__.py
        NOT:
            diff --git a/src/bridge/__init__.py b/src/bridge/__init__.py

        This convention allows the patch to be applied directly to the
        extracted upstream source at src/upstream/{commit_id}/, where the
        directory already contains the source_subpath contents.
        """
        old_path = f"a/{diff.path}"
        new_path = f"b/{diff.path}"

        # Generate diff using git diff for proper format
        if not diff.is_new and not diff.is_deleted:
            # For modifications, use git diff
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    f"upstream/{self.cfg.upstream.main_branch}~1",
                    f"upstream/{self.cfg.upstream.main_branch}",
                    "--",
                    diff.path,
                ],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                # Normalize paths: strip source_subpath prefix from the diff output
                output = result.stdout
                subpath = self.cfg.upstream.source_subpath
                output = output.replace(f"a/{subpath}/", "a/")
                output = output.replace(f"b/{subpath}/", "b/")
                return output

        # Fallback: create manual unified diff
        lines = []
        lines.append(f"diff --git {old_path} {new_path}")
        if diff.is_new:
            lines.append(f"new file mode 100644")
        lines.append(f"--- {old_path}")
        lines.append(f"+++ {new_path}")
        lines.append(f"@@ -0,0 +1,{len(diff.new_version.splitlines())} @@")

        for line in diff.new_version.splitlines():
            lines.append(f"+{line}")

        return "\n".join(lines)

    def _generate_patch_filename(self, diff: PatchDiff, commit: str) -> str:
        """Generate a patch filename based on the file path and commit."""
        # Format: XXXX.{path}.{ext}.patch
        path_parts = diff.path.replace("/", ".").replace("_", ".")
        return f"0001.{path_parts}.patch"

    def _resolve_patch_dir(self, commit: str) -> Path:
        """Resolve the patch directory for a given commit."""
        if self.cfg.patches.patch_subdir:
            return Path(str(self.cfg.patches.patch_subdir).format(commit=commit))
        return self.cfg.patches.directory

    def create_series_file(self, patches: list[GeneratedPatch], output_path: Path) -> None:
        """Create a series file for the generated patches."""
        with open(output_path, "w", encoding="utf-8") as f:
            for i, patch in enumerate(patches, 1):
                f.write(f"{patch.filename}\n")

    # ------------------------------------------------------------------
    # Regeneration (strict reconstruction) — regenerate overlay patches
    # from an upstream snapshot and current src/ tree.
    #
    # Invariant:
    #     src/upstream/{commit} + patches/upstream/{commit}/series == src/
    # ------------------------------------------------------------------

    @staticmethod
    def read_normalised(path: Path) -> bytes:
        """Read file bytes with normalised line endings."""
        raw = path.read_bytes()
        return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    @staticmethod
    def files_differ_norm(upstream_path: Path, src_path: Path) -> bool:
        """Compare two files with normalised line endings."""
        return PatchGenerator.read_normalised(upstream_path) != PatchGenerator.read_normalised(
            src_path
        )

    @staticmethod
    def normalize_patch_path(path: str) -> str:
        """Convert a relative file path to a patch filename component."""
        name = path.replace("/", "_")
        dot_idx = name.rfind(".")
        if dot_idx >= 0:
            name = name[:dot_idx] + "_" + name[dot_idx + 1 :]
        return name

    @staticmethod
    def is_skipped(
        relative_path: str,
        skip_prefixes: tuple[str, ...] = REGENERATE_SKIP_PREFIXES,
        skip_dirs: set[str] | None = None,
        skip_suffixes: tuple[str, ...] = REGENERATE_SKIP_SUFFIXES,
    ) -> bool:
        """Check whether a file should be skipped from patch generation."""
        if skip_dirs is None:
            skip_dirs = REGENERATE_SKIP_DIRS
        if relative_path.startswith(skip_prefixes):
            return True
        if relative_path.endswith(skip_suffixes):
            return True
        return any(part in skip_dirs for part in relative_path.split("/"))

    @staticmethod
    def collect_files(
        root: Path,
        skip_prefixes: tuple[str, ...] = REGENERATE_SKIP_PREFIXES,
        skip_dirs: set[str] | None = None,
        skip_suffixes: tuple[str, ...] = REGENERATE_SKIP_SUFFIXES,
    ) -> set[str]:
        """Collect all non-skipped files under a root, returning relative paths."""
        files: set[str] = set()
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative_path = str(path.relative_to(root))
            if not PatchGenerator.is_skipped(
                relative_path, skip_prefixes, skip_dirs, skip_suffixes
            ):
                files.add(relative_path)
        return files

    @staticmethod
    def _timestamp(path: Path | None) -> str:
        """Format modification timestamp for patch headers."""
        if path is None:
            return "1970-01-01 00:00:00.000000000 +0000"
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f %z"
        )

    @staticmethod
    def run_diff_raw(upstream_path: Path, src_path: Path) -> str:
        """Run ``diff -u`` between two files and return the output."""
        result = subprocess.run(
            ["diff", "-u", str(upstream_path), str(src_path)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _added_lines_from_raw(raw: bytes) -> str | None:
        """Generate unified-diff body for a new (fork-only) file."""
        ends_with_newline = raw.endswith(b"\n")
        has_crlf = b"\r\n" in raw
        content = raw.decode("utf-8")

        if has_crlf:
            lines = content.split("\r\n")
            if content.endswith("\r\n"):
                lines.pop()
            newline_marker = "\r"
        else:
            lines = content.split("\n")
            if content.endswith("\n"):
                lines.pop()
            newline_marker = ""

        if not lines:
            return None

        diff_lines = [f"@@ -0,0 +1,{len(lines)} @@"]
        for index, line in enumerate(lines):
            if has_crlf and (index < len(lines) - 1 or ends_with_newline):
                diff_lines.append(f"+{line}{newline_marker}")
            else:
                diff_lines.append(f"+{line}")

        body = "\n".join(diff_lines) + "\n"
        if not ends_with_newline:
            body += "\\ No newline at end of file\n"
        return body

    @staticmethod
    def _deleted_lines_from_raw(raw: bytes) -> str | None:
        """Generate unified-diff body for a deleted file."""
        content = raw.decode("utf-8")
        ends_with_newline = raw.endswith(b"\n")
        lines = content.splitlines()
        if not lines:
            return None

        diff_lines = [f"@@ -1,{len(lines)} +0,0 @@"]
        diff_lines.extend(f"-{line}" for line in lines)
        body = "\n".join(diff_lines) + "\n"
        if not ends_with_newline:
            body += "\\ No newline at end of file\n"
        return body

    @staticmethod
    def generate_modified_patch(
        relative_path: str, upstream_path: Path, src_path: Path
    ) -> str | None:
        """Generate a full patch for a modified file."""
        diff_output = PatchGenerator.run_diff_raw(upstream_path, src_path)
        if not diff_output:
            return None

        diff_lines = diff_output.split("\n")
        body = "\n".join(diff_lines[2:])
        if not body.strip():
            return None

        return (
            f"diff --git a/{relative_path} b/{relative_path}\n"
            f"--- a/{relative_path}\t{PatchGenerator._timestamp(upstream_path)}\n"
            f"+++ b/{relative_path}\t{PatchGenerator._timestamp(src_path)}\n"
            f"{body}"
        )

    @staticmethod
    def generate_new_patch(relative_path: str, src_path: Path) -> str | None:
        """Generate a full patch for a new (fork-only) file."""
        body = PatchGenerator._added_lines_from_raw(src_path.read_bytes())
        if body is None:
            return None

        return (
            f"diff --git a/{relative_path} b/{relative_path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{relative_path}\t{PatchGenerator._timestamp(src_path)}\n"
            f"{body}"
        )

    @staticmethod
    def generate_delete_patch(relative_path: str, upstream_path: Path) -> str | None:
        """Generate a full patch for a deleted file."""
        body = PatchGenerator._deleted_lines_from_raw(upstream_path.read_bytes())
        if body is None:
            return None

        return (
            f"diff --git a/{relative_path} b/{relative_path}\n"
            "deleted file mode 100644\n"
            f"--- a/{relative_path}\t{PatchGenerator._timestamp(upstream_path)}\n"
            "+++ /dev/null\n"
            f"{body}"
        )

    @staticmethod
    def _write_patch(path: Path, content: str) -> None:
        """Write a patch file to disk."""
        path.write_bytes(content.encode("utf-8"))

    @staticmethod
    def _backup_existing_patches(patch_dir: Path, backup_dir: Path) -> None:
        """Back up existing patches before overwriting."""
        if not patch_dir.exists():
            return

        existing = list(patch_dir.glob("*.patch"))
        if not existing:
            return

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / timestamp
        target.mkdir(parents=True, exist_ok=True)
        for patch in existing:
            shutil.move(str(patch), target / patch.name)

    @staticmethod
    def collect_preserve(
        preserve_args: list[str] | None = None,
        preserve_file_path: Path | None = None,
    ) -> set[str]:
        """Collect the set of files to preserve from the upstream base.

        Args:
            preserve_args: List of relative paths from CLI ``--preserve``.
            preserve_file_path: Path to a file with one relative path per line.

        Returns:
            Set of relative paths to preserve.
        """
        preserve: set[str] = set()
        for rel in preserve_args or []:
            rel = rel.strip()
            if rel:
                preserve.add(rel)
        if preserve_file_path and preserve_file_path.exists():
            for line in preserve_file_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    preserve.add(line)
        return preserve

    @staticmethod
    def _write_series(
        series_file: Path,
        compatibility_series_file: Path,
        commit: str,
        patch_entries: list[tuple[str, str]],
        modified_count: int,
        new_count: int,
        deleted_count: int,
        preserved_count: int,
    ) -> None:
        """Write the quilt series file (and a compatibility variant)."""
        lines = [
            f"# Quilt series file — {commit} (regenerated downstream overlay patches)",
            "#",
            "# Generated by upstream_sync.core.patch_generator.PatchGenerator",
            f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "#",
            f"# Modified files: {modified_count}",
            f"# New files (fork-only, not in upstream): {new_count}",
            f"# Deleted files (removed from upstream base by fork): {deleted_count}",
            f"# Preserved files (new in upstream, kept in base): {preserved_count}",
            f"# Total patches: {len(patch_entries)}",
            "",
            "# === Phase 1: Modified files (diffs from upstream) ===",
        ]

        phase = "modified"
        for patch_filename, patch_type in patch_entries:
            if patch_type != phase:
                phase = patch_type
                if phase == "new":
                    lines.extend(["", "# === Phase 2: New files (fork-only, not in upstream) ==="])
                elif phase == "deleted":
                    lines.extend(
                        ["", "# === Phase 3: Deleted files (removed from upstream base) ==="]
                    )
            lines.append(patch_filename)

        lines.append("")
        series_file.write_text("\n".join(lines), encoding="utf-8")

        # Compatibility series: patch names prefixed with "merged/"
        compatibility_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                compatibility_lines.append(f"merged/{stripped}")
            else:
                compatibility_lines.append(line)
        compatibility_series_file.write_text("\n".join(compatibility_lines), encoding="utf-8")

    def regenerate(
        self,
        commit: str,
        src_dir: Path,
        upstream_dir: Path,
        patch_root: Path,
        allow_deletes: bool = False,
        preserve: set[str] | None = None,
        skip_prefixes: tuple[str, ...] = REGENERATE_SKIP_PREFIXES,
        skip_dirs: set[str] | None = None,
        skip_suffixes: tuple[str, ...] = REGENERATE_SKIP_SUFFIXES,
    ) -> RegenerateResult:
        """Regenerate all overlay patches from an upstream snapshot.

        This is the "strict reconstruction" entry point.  It compares
        ``src_dir`` against ``upstream_dir`` and generates patches for
        every difference (modified, new fork-only files, and optionally
        deleted files).

        Args:
            commit: Short commit hash used for directory naming.
            src_dir: The downstream source tree (e.g. ``PROJECT / "src"``).
            upstream_dir: The upstream snapshot directory
                (e.g. ``PROJECT / "src" / "upstream" / commit``).
            patch_root: The per-commit patch base directory
                (e.g. ``PROJECT / "patches" / "upstream" / commit``).
            allow_deletes: Emit delete patches for upstream files absent from src.
            preserve: Set of relative paths to preserve from upstream base
                (no patch generated).
            skip_prefixes: File path prefixes to skip.
            skip_dirs: Directory names to skip.
            skip_suffixes: File extensions to skip.

        Returns:
            ``RegenerateResult`` with summary and file paths.

        Raises:
            FileNotFoundError: If ``src_dir`` or ``upstream_dir`` does not exist.
            ValueError: If a preserve entry is not in the upstream base.
            RuntimeError: If deleted files exist without ``allow_deletes``.
        """
        if preserve is None:
            preserve = set()
        if skip_dirs is None:
            skip_dirs = REGENERATE_SKIP_DIRS

        src = src_dir.resolve()
        upstream = upstream_dir.resolve()
        patch_base = patch_root.resolve()
        patch_dir = patch_base / "merged"
        backup_dir = patch_base / "backup"
        series_file = patch_base / "series"
        compatibility_series_file = patch_base / f"{commit}_series"

        if not src.exists():
            raise FileNotFoundError(f"Source tree does not exist: {src}")
        if not upstream.exists():
            raise FileNotFoundError(f"Upstream snapshot does not exist: {upstream}")

        upstream_files = self.collect_files(upstream, skip_prefixes, skip_dirs, skip_suffixes)
        src_files = self.collect_files(src, skip_prefixes, skip_dirs, skip_suffixes)

        # Cross-check preserve entries
        for relative_path in sorted(preserve):
            if relative_path not in upstream_files:
                raise ValueError(f"--preserve entry not in upstream base: {relative_path}")

        # Classify files
        upstream_only = sorted(upstream_files - src_files)
        preserved_new = sorted(p for p in upstream_only if p in preserve)
        deleted_files = sorted(p for p in upstream_only if p not in preserve)

        both = sorted(src_files & upstream_files)
        preserved_existing = sorted(p for p in both if p in preserve)
        preserved_files = sorted(set(preserved_new) | set(preserved_existing))
        modified_files = sorted(
            relative_path
            for relative_path in both
            if relative_path not in preserve
            and self.files_differ_norm(upstream / relative_path, src / relative_path)
        )
        new_files = sorted(src_files - upstream_files)

        if deleted_files and not allow_deletes:
            msg_parts = [f"{len(deleted_files)} upstream files are absent from {src}:"]
            for relative_path in deleted_files:
                msg_parts.append(f"  - {relative_path}")
            msg_parts.append("Re-run with --allow-deletes to generate delete patches after review.")
            raise RuntimeError("\n".join(msg_parts))

        # Backup existing patches
        self._backup_existing_patches(patch_dir, backup_dir)
        patch_dir.mkdir(parents=True, exist_ok=True)
        patch_base.mkdir(parents=True, exist_ok=True)

        patch_entries: list[tuple[str, str]] = []
        index = 1

        for relative_path in modified_files:
            content = self.generate_modified_patch(
                relative_path, upstream / relative_path, src / relative_path
            )
            if content is None:
                continue
            patch_filename = f"{index:04d}.{self.normalize_patch_path(relative_path)}.patch"
            self._write_patch(patch_dir / patch_filename, content)
            patch_entries.append((patch_filename, "modified"))
            index += 1

        for relative_path in new_files:
            content = self.generate_new_patch(relative_path, src / relative_path)
            if content is None:
                continue
            patch_filename = f"{index:04d}.{self.normalize_patch_path(relative_path)}.patch"
            self._write_patch(patch_dir / patch_filename, content)
            patch_entries.append((patch_filename, "new"))
            index += 1

        if allow_deletes:
            for relative_path in deleted_files:
                content = self.generate_delete_patch(relative_path, upstream / relative_path)
                if content is None:
                    continue
                patch_filename = (
                    f"{index:04d}.{self.normalize_patch_path(relative_path)}.delete.patch"
                )
                self._write_patch(patch_dir / patch_filename, content)
                patch_entries.append((patch_filename, "deleted"))
                index += 1

        self._write_series(
            series_file,
            compatibility_series_file,
            commit,
            patch_entries,
            len(modified_files),
            len(new_files),
            len(deleted_files),
            len(preserved_files),
        )

        total_size = sum(
            (patch_dir / patch_filename).stat().st_size for patch_filename, _ in patch_entries
        )

        # Build result
        result = RegenerateResult(
            modified_count=len(modified_files),
            new_count=len(new_files),
            deleted_count=len(deleted_files),
            preserved_count=len(preserved_files),
            preserved_files=set(preserved_files),
            patch_dir=patch_dir,
            series_file=series_file,
            compatibility_series_file=compatibility_series_file,
            total_size=total_size,
        )
        for patch_filename, patch_type in patch_entries:
            result.patch_entries.append(
                RegeneratePatch(
                    filename=patch_filename,
                    relative_path="",
                    patch_type=patch_type,
                )
            )

        return result

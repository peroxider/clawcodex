#!/usr/bin/env python3
"""Three-way merge an extracted upstream source snapshot into a fork.

The project keeps a source-only upstream snapshot and a patch queue, but the
runtime also contains migrated implementations under ``clawcodex_ext``.  A
plain directory copy cannot distinguish an upstream change from a downstream
change and would either lose二开代码 or silently pin old upstream behavior.
This helper performs a deterministic file-level three-way merge:

    base   = old extracted upstream snapshot
    ours   = current downstream tree (or an extension mirror)
    theirs = new extracted upstream snapshot

Files that changed on only one side are taken automatically.  Files changed on
both sides are passed through ``git merge-file``; unresolved hunks default to
the downstream version (the safe runtime choice) and are recorded in a JSON
report for explicit follow-up.  Facades and the legacy Python TUI/REPL are
always retained while their ``clawcodex_ext`` mirrors are merged separately.

The command writes a reviewable output tree first.  Pass ``--apply`` only
after inspecting the report to overlay it onto ``src`` and
``clawcodex_ext``.  Snapshot directories are never touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


LEGACY_PRESERVE = {
    "entrypoints/repl.py",
    "entrypoints/tui.py",
    "context_system/claude_md.py",  # renamed upstream -> clawcodex_md.py
    "repl/task_notifications.py",  # renamed upstream -> server/task_notifications.py
    "tui/theme.py",  # renamed upstream -> utils/theme.py
}
LEGACY_PREFIXES = ("repl/", "tui/")


@dataclass
class MergeReport:
    base: str
    ours: str
    theirs: str
    trees: dict[str, dict[str, int]] = field(default_factory=dict)
    statuses: list[dict[str, str]] = field(default_factory=list)

    def add(self, tree: str, path: str, status: str) -> None:
        counts = self.trees.setdefault(tree, {})
        counts[status] = counts.get(status, 0) + 1
        self.statuses.append({"tree": tree, "path": path, "status": status})


def rel_files(root: Path, excluded: tuple[str, ...] = ()) -> set[str]:
    """Return regular files below *root* as POSIX relative paths."""

    if not root.exists():
        return set()
    result: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel.split("/") or path.suffix in {".pyc", ".pyo"}:
            continue
        if any(rel == prefix or rel.startswith(prefix.rstrip("/") + "/") for prefix in excluded):
            continue
        result.add(rel)
    return result


def read_bytes(root: Path, rel: str) -> bytes | None:
    path = root / Path(rel)
    return path.read_bytes() if path.is_file() else None


def copy_one(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def is_binary(data: bytes) -> bool:
    return b"\x00" in data


def is_facade(data: bytes | None) -> bool:
    if not data or is_binary(data):
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return "clawcodex_ext" in text and (
        "__getattr__" in text or "facade" in text.lower() or "globals().update" in text
    )


def merge_text(repo_root: Path, ours: bytes, base: bytes, theirs: bytes) -> tuple[bytes, bool]:
    """Run git's diff3 merger on three byte strings."""

    with tempfile.TemporaryDirectory(prefix="clawcodex-merge-") as tmp:
        tmp_root = Path(tmp)
        current = tmp_root / "ours"
        ancestor = tmp_root / "base"
        incoming = tmp_root / "theirs"
        current.write_bytes(ours)
        ancestor.write_bytes(base)
        incoming.write_bytes(theirs)
        result = subprocess.run(
            [
                "git",
                "merge-file",
                "--stdout",
                "--diff3",
                str(current),
                str(ancestor),
                str(incoming),
            ],
            cwd=repo_root,
            capture_output=True,
        )
        # ``git merge-file`` returns the number of unresolved conflict hunks
        # (capped at 127), not a boolean 0/1 status.  Treating 2+ as a command
        # failure used to discard the marker output for exactly the complex
        # files that most needed review.
        if result.returncode > 127:
            detail = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git merge-file failed ({result.returncode}): {detail}")
        return result.stdout, result.returncode != 0


def prefer_ours(tree: str, rel: str, ours: bytes | None) -> bool:
    if rel in LEGACY_PRESERVE or rel.startswith(LEGACY_PREFIXES):
        return True
    # A source facade is deliberately only a routing shim.  Upstream changes
    # belong in the extension mirror, not in the shim itself.
    return tree == "src" and is_facade(ours)


def merge_tree(
    *,
    repo_root: Path,
    tree: str,
    base_root: Path,
    ours_root: Path,
    theirs_root: Path,
    output_root: Path,
    conflict_root: Path,
    excluded: tuple[str, ...],
    adopt_upstream_new: bool,
    report: MergeReport,
) -> None:
    """Merge one logical tree into *output_root*."""

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    base_files = rel_files(base_root)
    ours_files = rel_files(ours_root, excluded)
    theirs_files = rel_files(theirs_root)
    # The primary source tree adopts every incoming file.  The extension tree
    # is a selective mirror, so only paths already present downstream are
    # eligible; otherwise this would duplicate the entire upstream package
    # under ``clawcodex_ext``.
    all_files = (
        sorted(base_files | ours_files | theirs_files) if adopt_upstream_new else sorted(ours_files)
    )

    for rel in all_files:
        base = read_bytes(base_root, rel)
        ours = read_bytes(ours_root, rel)
        theirs = read_bytes(theirs_root, rel)
        destination = output_root / Path(rel)

        # Files introduced only by the downstream fork are retained verbatim.
        if base is None and theirs is None:
            if ours is not None:
                copy_one(ours_root / Path(rel), destination)
                report.add(tree, rel, "downstream-only")
            continue

        # New upstream files are adopted unless the fork independently added
        # a file at the same path; the latter is kept and reported.
        if base is None:
            if ours is None:
                copy_one(theirs_root / Path(rel), destination)
                report.add(tree, rel, "upstream-new")
            elif ours == theirs:
                copy_one(ours_root / Path(rel), destination)
                report.add(tree, rel, "identical-new")
            else:
                copy_one(ours_root / Path(rel), destination)
                report.add(tree, rel, "both-new-downstream-kept")
            continue

        # Restore upstream files that are absent from the materialised fork.
        # The historical patch queue used ``preserve.list`` for these paths,
        # so absence from ``src`` did not mean an intentional delete.
        if ours is None:
            if theirs is not None:
                copy_one(theirs_root / Path(rel), destination)
                report.add(tree, rel, "upstream-restored-local-delete")
            continue

        # Upstream deletion: retain a changed compatibility implementation;
        # otherwise honour the upstream deletion.  Legacy paths are retained
        # even when they are byte-identical to the old baseline.
        if theirs is None:
            if tree == "clawcodex_ext" or prefer_ours(tree, rel, ours) or ours != base:
                copy_one(ours_root / Path(rel), destination)
                report.add(tree, rel, "upstream-deleted-downstream-kept")
            else:
                report.add(tree, rel, "upstream-deleted")
            continue

        if ours == base:
            copy_one(theirs_root / Path(rel), destination)
            report.add(tree, rel, "upstream-only")
        elif theirs == base or ours == theirs:
            copy_one(ours_root / Path(rel), destination)
            report.add(tree, rel, "downstream-only" if theirs == base else "identical")
        elif prefer_ours(tree, rel, ours):
            copy_one(ours_root / Path(rel), destination)
            report.add(tree, rel, "facade-or-legacy-preserved")
        elif is_binary(ours) or is_binary(base) or is_binary(theirs):
            copy_one(ours_root / Path(rel), destination)
            report.add(tree, rel, "binary-conflict-downstream-kept")
        else:
            merged, conflicted = merge_text(repo_root, ours, base, theirs)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(merged if not conflicted else ours)
            if conflicted:
                marker_file = conflict_root / tree / Path(rel)
                marker_file.parent.mkdir(parents=True, exist_ok=True)
                marker_file.write_bytes(merged)
            report.add(
                tree, rel, "three-way-merged" if not conflicted else "text-conflict-downstream-kept"
            )


def tracked_files(repo_root: Path, target: Path) -> set[str]:
    target_rel = target.resolve().relative_to(repo_root.resolve()).as_posix()
    result = subprocess.run(
        ["git", "ls-files", "--", target_rel],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    prefix = target_rel.rstrip("/") + "/"
    return {
        line.strip()[len(prefix) :]
        for line in result.stdout.splitlines()
        if line.strip().startswith(prefix)
    }


def apply_tree(
    repo_root: Path, output_root: Path, target_root: Path, excluded: tuple[str, ...]
) -> None:
    """Overlay a generated tree and remove only tracked stale files."""

    generated = rel_files(output_root)
    for rel in tracked_files(repo_root, target_root) - generated:
        if any(rel == prefix or rel.startswith(prefix.rstrip("/") + "/") for prefix in excluded):
            continue
        stale = target_root / Path(rel)
        if stale.exists():
            stale.unlink()
    for rel in generated:
        copy_one(output_root / Path(rel), target_root / Path(rel))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--base", type=Path, required=True, help="Old extracted upstream snapshot")
    parser.add_argument(
        "--theirs", type=Path, required=True, help="New extracted upstream snapshot"
    )
    parser.add_argument("--ours", type=Path, default=Path("src"))
    parser.add_argument("--mirror-ours", type=Path, default=Path("clawcodex_ext"))
    parser.add_argument(
        "--target",
        type=Path,
        help="Apply the generated src tree here (defaults to --ours)",
    )
    parser.add_argument(
        "--mirror-target",
        type=Path,
        help="Apply the generated extension tree here (defaults to --mirror-ours)",
    )
    parser.add_argument("--output", type=Path, required=True, help="Generated merge output root")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Apply output trees after generation")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    base = (repo_root / args.base).resolve()
    theirs = (repo_root / args.theirs).resolve()
    ours = (repo_root / args.ours).resolve()
    mirror_ours = (repo_root / args.mirror_ours).resolve()
    target = (repo_root / (args.target or args.ours)).resolve()
    mirror_target = (repo_root / (args.mirror_target or args.mirror_ours)).resolve()
    output = (repo_root / args.output).resolve()
    report_path = (repo_root / args.report).resolve()

    for path in (base, theirs, ours, mirror_ours):
        if not path.exists():
            raise SystemExit(f"Required merge path does not exist: {path}")
    if output == repo_root or output in (
        base,
        theirs,
        ours,
        mirror_ours,
        target,
        mirror_target,
    ):
        raise SystemExit("Refusing to use a source tree as merge output")

    output.mkdir(parents=True, exist_ok=True)
    conflict_root = output.parent / f"{output.name}-conflicts"
    if conflict_root.exists():
        shutil.rmtree(conflict_root)
    report = MergeReport(base=str(args.base), ours=str(args.ours), theirs=str(args.theirs))
    merge_tree(
        repo_root=repo_root,
        tree="src",
        base_root=base,
        ours_root=ours,
        theirs_root=theirs,
        output_root=output / "src",
        conflict_root=conflict_root,
        excluded=("upstream",),
        adopt_upstream_new=True,
        report=report,
    )
    merge_tree(
        repo_root=repo_root,
        tree="clawcodex_ext",
        base_root=base,
        ours_root=mirror_ours,
        theirs_root=theirs,
        output_root=output / "clawcodex_ext",
        conflict_root=conflict_root,
        excluded=(),
        adopt_upstream_new=False,
        report=report,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if args.apply:
        apply_tree(repo_root, output / "src", target, ("upstream",))
        apply_tree(repo_root, output / "clawcodex_ext", mirror_target, ())
    print(json.dumps(report.trees, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

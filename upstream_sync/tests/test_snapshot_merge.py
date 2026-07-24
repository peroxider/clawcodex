"""Focused tests for the source-snapshot three-way merge helper."""

from pathlib import Path

from scripts.merge_upstream_snapshot import MergeReport, merge_text, merge_tree


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_merge_tree_preserves_both_one_sided_changes(tmp_path: Path) -> None:
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    output = tmp_path / "output"
    conflicts = tmp_path / "conflicts"
    for root in (base, ours, theirs):
        root.mkdir()

    _write(base, "upstream.py", "old\n")
    _write(ours, "upstream.py", "old\n")
    _write(theirs, "upstream.py", "new\n")
    _write(base, "fork.py", "old\n")
    _write(ours, "fork.py", "fork\n")
    _write(theirs, "fork.py", "old\n")
    _write(ours, "fork_only.py", "fork only\n")
    _write(theirs, "upstream_new.py", "upstream only\n")

    report = MergeReport("base", "ours", "theirs")
    merge_tree(
        repo_root=tmp_path,
        tree="src",
        base_root=base,
        ours_root=ours,
        theirs_root=theirs,
        output_root=output,
        conflict_root=conflicts,
        excluded=(),
        adopt_upstream_new=True,
        report=report,
    )

    assert (output / "upstream.py").read_text(encoding="utf-8") == "new\n"
    assert (output / "fork.py").read_text(encoding="utf-8") == "fork\n"
    assert (output / "fork_only.py").exists()
    assert (output / "upstream_new.py").exists()


def test_conflict_keeps_downstream_and_writes_review_artifact(tmp_path: Path) -> None:
    base = tmp_path / "base"
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    output = tmp_path / "output"
    conflicts = tmp_path / "conflicts"
    for root in (base, ours, theirs):
        root.mkdir()
    _write(base, "conflict.py", "value = 'base'\n")
    _write(ours, "conflict.py", "value = 'fork'\n")
    _write(theirs, "conflict.py", "value = 'upstream'\n")

    report = MergeReport("base", "ours", "theirs")
    merge_tree(
        repo_root=tmp_path,
        tree="src",
        base_root=base,
        ours_root=ours,
        theirs_root=theirs,
        output_root=output,
        conflict_root=conflicts,
        excluded=(),
        adopt_upstream_new=True,
        report=report,
    )

    assert (output / "conflict.py").read_text(encoding="utf-8") == "value = 'fork'\n"
    marker_text = (conflicts / "src" / "conflict.py").read_text(encoding="utf-8")
    assert "<<<<<<<" in marker_text
    assert report.trees["src"]["text-conflict-downstream-kept"] == 1


def test_merge_text_keeps_markers_for_multiple_conflict_hunks(tmp_path: Path) -> None:
    separators = [f"unchanged_{index}\n" for index in range(20)]
    base = "value_a = 'base'\n" + "".join(separators) + "value_b = 'base'\n"
    ours = "value_a = 'ours'\n" + "".join(separators) + "value_b = 'ours'\n"
    theirs = "value_a = 'theirs'\n" + "".join(separators) + "value_b = 'theirs'\n"

    merged, conflicted = merge_text(
        tmp_path,
        ours.encode(),
        base.encode(),
        theirs.encode(),
    )

    assert conflicted is True
    assert merged.count(b"<<<<<<<") == 2
    assert merged.count(b">>>>>>>") == 2


def test_mirror_does_not_duplicate_new_upstream_modules(tmp_path: Path) -> None:
    base = tmp_path / "base"
    ours = tmp_path / "mirror"
    theirs = tmp_path / "theirs"
    output = tmp_path / "output"
    for root in (base, ours, theirs):
        root.mkdir()
    _write(ours, "fork_extension.py", "extension = True\n")
    _write(theirs, "new_upstream.py", "feature = True\n")

    report = MergeReport("base", "mirror", "theirs")
    merge_tree(
        repo_root=tmp_path,
        tree="clawcodex_ext",
        base_root=base,
        ours_root=ours,
        theirs_root=theirs,
        output_root=output,
        conflict_root=tmp_path / "conflicts",
        excluded=(),
        adopt_upstream_new=False,
        report=report,
    )

    assert (output / "fork_extension.py").exists()
    assert not (output / "new_upstream.py").exists()

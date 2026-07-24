from __future__ import annotations

from pathlib import Path

from upstream_sync.core.patch_generator import PatchGenerator


def test_run_diff_raw_falls_back_when_posix_diff_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    upstream = tmp_path / "upstream.py"
    downstream = tmp_path / "downstream.py"
    upstream.write_text("value = 1\n", encoding="utf-8")
    downstream.write_text("value = 2\n", encoding="utf-8")

    def missing_diff(*_args, **_kwargs):
        raise FileNotFoundError("diff")

    monkeypatch.setattr("upstream_sync.core.patch_generator.subprocess.run", missing_diff)

    patch = PatchGenerator.run_diff_raw(upstream, downstream)

    assert patch.startswith(f"--- {upstream}")
    assert f"+++ {downstream}" in patch
    assert "-value = 1" in patch
    assert "+value = 2" in patch


def test_run_diff_raw_git_fallback_preserves_missing_newline_marker(
    tmp_path: Path, monkeypatch
) -> None:
    upstream = tmp_path / "upstream.py"
    downstream = tmp_path / "downstream.py"
    upstream.write_text("value = 1\n", encoding="utf-8")
    downstream.write_text("value = 2", encoding="utf-8")

    real_run = __import__("subprocess").run

    def no_posix_diff(args, **kwargs):
        if args[0] == "diff":
            raise FileNotFoundError("diff")
        return real_run(args, **kwargs)

    monkeypatch.setattr("upstream_sync.core.patch_generator.subprocess.run", no_posix_diff)

    patch = PatchGenerator.run_diff_raw(upstream, downstream)

    assert "+value = 2\n\\ No newline at end of file\n" in patch


def test_collect_files_uses_patch_portable_relative_paths(tmp_path: Path) -> None:
    nested = tmp_path / "pkg" / "module.py"
    nested.parent.mkdir()
    nested.write_text("pass\n", encoding="utf-8")

    assert PatchGenerator.collect_files(tmp_path) == {"pkg/module.py"}

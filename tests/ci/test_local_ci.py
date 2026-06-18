from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_module(monkeypatch):
    monkeypatch.syspath_prepend("scripts/ci")
    return importlib.import_module("local_ci")


def _load_preflight(monkeypatch):
    monkeypatch.syspath_prepend("scripts/ci")
    return importlib.import_module("preflight")


class _FakeStdout:
    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_env_bool_accepts_only_true(monkeypatch):
    local_ci = _load_module(monkeypatch)

    assert local_ci._env_bool({"CI_RUN_DOCS": "true"}, "CI_RUN_DOCS") is True
    assert local_ci._env_bool({"CI_RUN_DOCS": "True"}, "CI_RUN_DOCS") is True
    assert local_ci._env_bool({"CI_RUN_DOCS": "false"}, "CI_RUN_DOCS") is False
    assert local_ci._env_bool({}, "CI_RUN_DOCS") is False


def test_auto_ui_enables_rich_for_powershell_wrapped_stdout(monkeypatch):
    local_ci = _load_module(monkeypatch)
    if not local_ci.RICH_AVAILABLE:
        pytest.skip("rich is not available")

    ui_mode, reason = local_ci._resolve_ui(
        "auto",
        {"PSModulePath": "C:\\Program Files\\PowerShell\\Modules"},
        _FakeStdout(is_tty=False),
    )

    assert ui_mode == "static"
    assert "PowerShell" in reason


def test_auto_ui_stays_plain_in_ci(monkeypatch):
    local_ci = _load_module(monkeypatch)

    ui_mode, reason = local_ci._resolve_ui(
        "auto",
        {"CI": "true", "PSModulePath": "C:\\Program Files\\PowerShell\\Modules"},
        _FakeStdout(is_tty=False),
    )

    assert ui_mode == "plain"
    assert reason == "CI=true"


def test_build_steps_marks_remote_only_items_as_skipped(tmp_path, monkeypatch):
    local_ci = _load_module(monkeypatch)
    monkeypatch.setattr(local_ci, "PYTHON_FILES", tmp_path / "ci_python_files.txt")
    monkeypatch.setattr(local_ci, "DOC_FILES", tmp_path / "ci_doc_files.txt")
    local_ci.PYTHON_FILES.write_text("", encoding="utf-8")
    local_ci.DOC_FILES.write_text("", encoding="utf-8")

    steps = local_ci._build_steps(
        {
            "CI_RUN_DOCS": "false",
            "CI_RUN_PYTHON": "false",
            "CI_RUN_ORCHESTRATOR": "false",
            "CI_RUN_PACKAGE": "false",
            "CI_DOCS_ONLY": "true",
        },
        all_files=False,
        base="origin/main",
    )

    skipped = {step.name: step.skip_reason for step in steps if step.skip_reason}
    assert skipped["security / CodeCheck"].startswith("remote-only")
    assert skipped["publish / TestPyPI-GitCode-Release"].startswith("destructive")
    assert skipped["agent-smoke / agent-replay-smoke"] == "docs-only change"
    assert skipped["ci / package-smoke"] == "docs-only change"


def test_build_steps_skips_lint_when_package_scope_has_no_python_files(tmp_path, monkeypatch):
    local_ci = _load_module(monkeypatch)
    monkeypatch.setattr(local_ci, "PYTHON_FILES", tmp_path / "ci_python_files.txt")
    monkeypatch.setattr(local_ci, "DOC_FILES", tmp_path / "ci_doc_files.txt")
    local_ci.PYTHON_FILES.write_text("", encoding="utf-8")
    local_ci.DOC_FILES.write_text("", encoding="utf-8")

    steps = local_ci._build_steps(
        {
            "CI_RUN_DOCS": "false",
            "CI_RUN_PYTHON": "true",
            "CI_RUN_ORCHESTRATOR": "true",
            "CI_RUN_PACKAGE": "true",
            "CI_DOCS_ONLY": "false",
        },
        all_files=False,
        base="HEAD~1",
    )

    lint_step = next(step for step in steps if step.name == "ci / lint")
    assert lint_step.commands == []
    assert lint_step.skip_reason == "no changed Python files"


def test_chunked_commands_split_long_file_lists(monkeypatch):
    local_ci = _load_module(monkeypatch)

    commands = local_ci._chunked_commands(
        ["python", "-m", "ruff", "check"],
        ["a.py", "b" * 20 + ".py", "c.py"],
        max_command_chars=32,
    )

    assert commands == [
        ["python", "-m", "ruff", "check", "a.py"],
        ["python", "-m", "ruff", "check", "b" * 20 + ".py"],
        ["python", "-m", "ruff", "check", "c.py"],
    ]


def test_preflight_runs_package_smoke_for_non_docs_only_changes(monkeypatch):
    preflight = _load_preflight(monkeypatch)

    assert preflight.build_env(["README.md"])["CI_RUN_PACKAGE"] == "false"
    assert preflight.build_env(["README.md", "src/agent/foo.py"])["CI_RUN_PACKAGE"] == "true"
    assert preflight.build_env([".gitignore"])["CI_RUN_PACKAGE"] == "true"


def test_gitcode_ci_package_smoke_is_skipped_for_docs_only_changes():
    workflow = Path(".gitcode/workflows/ci.yml").read_text(encoding="utf-8")

    assert "No non-docs changes; skipping package smoke." in workflow
    assert '[ "$CI_RUN_PACKAGE" != "true" ]' in workflow


def test_write_preflight_uses_committed_scope_only(tmp_path, monkeypatch, capsys):
    local_ci = _load_module(monkeypatch)
    state_dir = tmp_path / ".local-ci"
    preflight_env = state_dir / "ci_preflight.env"
    python_files = state_dir / "ci_python_files.txt"
    doc_files = state_dir / "ci_doc_files.txt"
    (tmp_path / "untracked.py").write_text("print('ignore me')\n", encoding="utf-8")

    monkeypatch.setattr(local_ci, "ROOT", tmp_path)
    monkeypatch.setattr(local_ci, "PREFLIGHT_ENV", preflight_env)
    monkeypatch.setattr(local_ci, "PYTHON_FILES", python_files)
    monkeypatch.setattr(local_ci, "DOC_FILES", doc_files)
    monkeypatch.setattr(
        local_ci.preflight,
        "_changed_files",
        lambda base, all_files: ["committed.py"],
    )

    local_ci._write_preflight("HEAD~1", False, scope_label="current commit (HEAD~1..HEAD)")

    assert python_files.read_text(encoding="utf-8") == "committed.py\n"
    assert "untracked.py" not in preflight_env.read_text(encoding="utf-8")
    assert "changed files: 1" in capsys.readouterr().out


def test_package_smoke_cleanup_removes_sdist_staging_dir(tmp_path, monkeypatch):
    local_ci = _load_module(monkeypatch)
    monkeypatch.setattr(local_ci, "ROOT", tmp_path)

    for name in ("dist", "build", ".package-smoke", "clawcodex_dev_mind-0.5.0"):
        path = tmp_path / name
        path.mkdir()
        (path / "sentinel.txt").write_text("temporary\n", encoding="utf-8")

    local_ci._prepare_step(local_ci.Step(name="ci / package-smoke", description="build"))

    assert not (tmp_path / "dist").exists()
    assert not (tmp_path / "build").exists()
    assert not (tmp_path / ".package-smoke").exists()
    assert not (tmp_path / "clawcodex_dev_mind-0.5.0").exists()


def test_local_ci_reports_package_artifact_locations(monkeypatch):
    local_ci = _load_module(monkeypatch)

    paths = {path for path, _description in local_ci._artifact_locations()}

    assert ".package-smoke/" in paths
    assert "dist/" in paths
    assert local_ci.SDIST_STAGING_DIR_GLOB in paths


class _FakeLive:
    def __init__(self) -> None:
        self.updates = []

    def update(self, renderable, *, refresh: bool = False) -> None:
        self.updates.append((renderable, refresh))


def test_rich_live_failure_detail_is_bounded(tmp_path, monkeypatch):
    local_ci = _load_module(monkeypatch)
    if not local_ci.RICH_AVAILABLE:
        pytest.skip("rich is not available")

    monkeypatch.setattr(local_ci, "ROOT", tmp_path)
    step = local_ci.Step(
        name="ci / sample",
        description="sample rich live failure",
        commands=[
            [
                sys.executable,
                "-c",
                "import sys; [print(f'line {i}') for i in range(30)]; sys.exit(7)",
            ]
        ],
    )
    state = local_ci.DisplayState(
        steps=[step],
        statuses=["pending"],
        scope_label="current commit (HEAD~1..HEAD)",
        changed_count=1,
        python_count=1,
        docs_count=0,
        env_file=".local-ci/ci_preflight.env",
    )
    live = _FakeLive()

    ok = local_ci._run_step_live(
        step,
        index=0,
        state=state,
        live=live,
        failure_lines=30,
        show_output=False,
    )

    assert ok is False
    assert state.statuses == ["fail"]
    assert len(state.detail_lines) <= local_ci.LIVE_DETAIL_MAX_LINES
    assert any("output truncated in dashboard" in line for line in state.detail_lines)
    assert any("line 29" in line for line in state.post_run_lines)
    assert live.updates


def test_rich_live_prints_failure_summary_after_stopping(tmp_path, monkeypatch, capsys):
    local_ci = _load_module(monkeypatch)
    if not local_ci.RICH_AVAILABLE:
        pytest.skip("rich is not available")

    state_dir = tmp_path / ".local-ci"
    state_dir.mkdir()
    preflight_env = state_dir / "ci_preflight.env"
    python_files = state_dir / "ci_python_files.txt"
    doc_files = state_dir / "ci_doc_files.txt"
    preflight_env.write_text("CI_CHANGED_FILES=sample.py\n", encoding="utf-8")
    python_files.write_text("sample.py\n", encoding="utf-8")
    doc_files.write_text("", encoding="utf-8")

    monkeypatch.setattr(local_ci, "ROOT", tmp_path)
    monkeypatch.setattr(local_ci, "PREFLIGHT_ENV", preflight_env)
    monkeypatch.setattr(local_ci, "PYTHON_FILES", python_files)
    monkeypatch.setattr(local_ci, "DOC_FILES", doc_files)

    step = local_ci.Step(
        name="ci / sample",
        description="sample rich live failure",
        commands=[[sys.executable, "-c", "import sys; print('boom'); sys.exit(7)"]],
    )

    assert (
        local_ci._run_steps_live(
            [step],
            scope_label="current commit (HEAD~1..HEAD)",
            continue_on_error=False,
            failure_lines=5,
            show_output=False,
            force_terminal=False,
        )
        == 1
    )

    output = capsys.readouterr().out
    assert "[FAIL] ci / sample exited 7" in output
    assert "boom" in output
    assert "[FAIL] local CI finished with 1 blocking failure(s)." in output


def test_rich_static_prints_single_total_flow_on_failure(tmp_path, monkeypatch, capsys):
    local_ci = _load_module(monkeypatch)
    if not local_ci.RICH_AVAILABLE:
        pytest.skip("rich is not available")

    state_dir = tmp_path / ".local-ci"
    state_dir.mkdir()
    preflight_env = state_dir / "ci_preflight.env"
    python_files = state_dir / "ci_python_files.txt"
    doc_files = state_dir / "ci_doc_files.txt"
    preflight_env.write_text("CI_CHANGED_FILES=bad.md\n", encoding="utf-8")
    python_files.write_text("", encoding="utf-8")
    doc_files.write_text("bad.md\n", encoding="utf-8")

    monkeypatch.setattr(local_ci, "ROOT", tmp_path)
    monkeypatch.setattr(local_ci, "PREFLIGHT_ENV", preflight_env)
    monkeypatch.setattr(local_ci, "PYTHON_FILES", python_files)
    monkeypatch.setattr(local_ci, "DOC_FILES", doc_files)

    step = local_ci.Step(
        name="ci / docs",
        description="sample static failure",
        commands=[[sys.executable, "-c", "import sys; print('bad'); sys.exit(2)"]],
    )

    assert (
        local_ci._run_steps_rich_static(
            [step],
            scope_label="current commit (HEAD~1..HEAD)",
            continue_on_error=False,
            failure_lines=5,
            show_output=False,
        )
        == 1
    )

    output = capsys.readouterr().out
    assert output.count("Total Flow") == 1
    assert "[FAIL] ci / docs exited 2" in output
    assert "[FAIL] local CI finished with 1 blocking failure(s)." in output

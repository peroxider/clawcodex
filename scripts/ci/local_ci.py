"""Run the GitCode CI gate shape locally.

This is the one-command fallback for repositories where GitCode Pipeline is not
available yet. It uses the same helper scripts as the workflows, prints the
planned steps, and expands command output when a blocking step fails.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import preflight

try:
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - rich is a runtime dependency.
    box = None
    Console = Group = Live = Panel = Table = Text = None
    RICH_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / ".local-ci"
PREFLIGHT_ENV = STATE_DIR / "ci_preflight.env"
PYTHON_FILES = STATE_DIR / "ci_python_files.txt"
DOC_FILES = STATE_DIR / "ci_doc_files.txt"

PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GLM_API_KEY", "ZHIPUAI_API_KEY")

CORE_PYTEST = [
    "tests/fast",
    "tests/config/test_config.py",
    "tests/config/test_config_system.py",
    "tests/config/test_effort.py",
    "tests/model",
    "tests/utils/test_combined_abort_signal.py",
    "tests/input/test_format.py",
    "tests/input/test_frontmatter_adapter.py",
    "tests/permissions/test_permission_modes.py",
    "tests/hooks/test_hook_config.py",
    "tests/skills/test_skills_frontmatter_yaml.py",
    "tests/bridge/test_jwt_utils.py",
    "tests/ci/test_gitcode_release.py",
]

ORCHESTRATOR_PYTEST = [
    "tests/orchestrator/test_local_tracker_parser.py",
    "tests/orchestrator/test_orchestrator_f39_intent.py",
    "tests/test_visualizer/test_orchestrator_link.py",
]

AGENT_SMOKE_PYTEST = [
    "tests/agent/test_agent_smoke_no_live_key.py",
    "tests/orchestrator/test_orchestrator_f49_transcript.py",
    "tests/orchestrator/test_orchestrator_f49_resume.py",
    "tests/orchestrator/test_orchestrator_workspace_hooks.py",
]

CI_HELPER_FILES = [
    "scripts/ci/dev_setup.py",
    "scripts/ci/docs_check.py",
    "scripts/ci/env_loader.py",
    "scripts/ci/gitcode_release.py",
    "scripts/ci/local_ci.py",
    "scripts/ci/local_publish.py",
    "scripts/ci/preflight.py",
    "scripts/ci/supply_chain_audit.py",
]
SDIST_STAGING_DIR_GLOB = "clawcodex_dev_mind-*"
LIVE_DETAIL_MAX_LINES = 18


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    output: str
    duration: float


@dataclass
class Step:
    name: str
    description: str
    commands: list[list[str]] = field(default_factory=list)
    skip_reason: str | None = None
    blocking: bool = True
    advisory: bool = False
    env: dict[str, str] | None = None


@dataclass
class DisplayState:
    steps: list[Step]
    statuses: list[str]
    scope_label: str
    changed_count: int
    python_count: int
    docs_count: int
    env_file: str
    detail_lines: list[str] = field(default_factory=list)
    post_run_lines: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)


def _display_command(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def _env_bool(env: dict[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() == "true"


def _env_truthy(env: dict[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_rich_reason(env: dict[str, str], stdout) -> str | None:
    if not RICH_AVAILABLE:
        return None
    if "NO_COLOR" in env or _env_truthy(env, "CI"):
        return None
    if stdout.isatty():
        return "stdout is interactive"
    if any(env.get(key) for key in ("WT_SESSION", "TERM_PROGRAM", "ANSICON", "ConEmuANSI")):
        return "terminal host detected"
    if "PSModulePath" in env:
        return "PowerShell environment detected"
    return None


def _rich_ui_mode(env: dict[str, str], stdout, *, forced: bool) -> tuple[str, str]:
    if "PSModulePath" in env:
        return "static", "PowerShell environment detected; live dashboard disabled"
    if not stdout.isatty():
        return "static", "stdout is not interactive; live dashboard disabled"
    reason = "forced rich output" if forced else "stdout is interactive"
    return "live", reason


def _resolve_ui(ui: str, env: dict[str, str], stdout) -> tuple[str, str]:
    if ui == "plain":
        return "plain", "forced plain output"
    if ui == "rich":
        if RICH_AVAILABLE:
            return _rich_ui_mode(env, stdout, forced=True)
        return "plain", "Rich is not installed"

    reason = _auto_rich_reason(env, stdout)
    if reason:
        return _rich_ui_mode(env, stdout, forced=False)
    if not RICH_AVAILABLE:
        return "plain", "Rich is not installed"
    if "NO_COLOR" in env:
        return "plain", "NO_COLOR is set"
    if _env_truthy(env, "CI"):
        return "plain", "CI=true"
    return "plain", "stdout is not interactive"


def _read_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _print_output_tail(output: str, *, lines: int) -> None:
    if not output:
        print("  <no command output>")
        return
    chunks = output.splitlines()
    if len(chunks) > lines:
        print(f"  ... output truncated to last {lines} lines ...")
        chunks = chunks[-lines:]
    for line in chunks:
        print(f"  {line}")


def _artifact_locations() -> list[tuple[str, str]]:
    return [
        (".local-ci/", "preflight env and changed-file lists"),
        ("dist/", "wheel and sdist produced by ci / package-smoke"),
        ("build/", "PEP 517 build scratch directory"),
        (".package-smoke/", "temporary venv used to install the built wheel"),
        (SDIST_STAGING_DIR_GLOB, "sdist staging directories cleaned before package smoke"),
    ]


def _print_artifact_locations() -> None:
    print("  local artifacts:")
    for path, description in _artifact_locations():
        print(f"    {path}: {description}")


def _clean_provider_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in PROVIDER_KEYS:
        env[key] = ""
    return env


def _default_base() -> str:
    return "HEAD~1"


def _run_command(args: list[str], *, env: dict[str, str] | None = None) -> CommandResult:
    started = time.perf_counter()
    proc = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return CommandResult(
        args=args,
        returncode=proc.returncode,
        output=proc.stdout,
        duration=time.perf_counter() - started,
    )


def _write_preflight(base: str, all_files: bool, *, scope_label: str) -> dict[str, str]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    files = preflight._changed_files(base, all_files)
    env = preflight.build_env(files)
    env["CI_PYTHON_FILE_LIST"] = str(PYTHON_FILES.relative_to(ROOT)).replace("\\", "/")
    env["CI_DOC_FILE_LIST"] = str(DOC_FILES.relative_to(ROOT)).replace("\\", "/")
    preflight.write_env(env, PREFLIGHT_ENV)
    preflight.write_file_list(preflight._python_files(files), PYTHON_FILES)
    preflight.write_file_list(preflight._doc_files(files), DOC_FILES)

    print("[PASS] preflight scope")
    print(f"  mode: {scope_label}")
    print(f"  changed files: {len(files)}")
    print(f"  python files: {len(_read_list(PYTHON_FILES))}")
    print(f"  docs files: {len(_read_list(DOC_FILES))}")
    print(f"  env file: {PREFLIGHT_ENV.relative_to(ROOT)}")
    _print_artifact_locations()
    return env


def _preflight_counts() -> tuple[int, int, int]:
    changed = _read_list(PREFLIGHT_ENV)
    changed_count = 0
    for line in changed:
        if line.startswith("CI_CHANGED_FILES="):
            encoded = line.split("=", 1)[1].strip()
            try:
                raw = shlex.split(encoded)[0] if encoded else ""
                changed_count = len(shlex.split(raw))
            except ValueError:
                changed_count = 0
            break
    return changed_count, len(_read_list(PYTHON_FILES)), len(_read_list(DOC_FILES))


def _build_steps(env: dict[str, str], *, all_files: bool, base: str) -> list[Step]:
    python_files = _read_list(PYTHON_FILES)
    docs_command = [sys.executable, "scripts/ci/docs_check.py", "--files-from", str(DOC_FILES)]
    supply_command = [sys.executable, "scripts/ci/supply_chain_audit.py"]
    supply_command.extend(["--all"] if all_files else ["--base", base])

    lint_commands = []
    if python_files:
        lint_commands = [
            [sys.executable, "-m", "ruff", "check", *python_files],
            [sys.executable, "-m", "ruff", "format", "--check", *python_files],
        ]

    if not _env_bool(env, "CI_RUN_PYTHON"):
        lint_skip_reason = "no Python/package/CI changes"
    elif not python_files:
        lint_skip_reason = "no changed Python files"
    else:
        lint_skip_reason = None

    smoke_dir = ROOT / ".package-smoke"
    smoke_python = smoke_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    smoke_cli = smoke_dir / (
        "Scripts/clawcodex-dev.exe" if os.name == "nt" else "bin/clawcodex-dev"
    )

    return [
        Step(
            name="ci / docs",
            description="UTF-8, trailing whitespace, final newline, merge markers, local links",
            commands=[docs_command],
            skip_reason=None if _env_bool(env, "CI_RUN_DOCS") else "no changed documentation files",
        ),
        Step(
            name="ci / lint",
            description="ruff check and ruff format --check",
            commands=lint_commands,
            skip_reason=lint_skip_reason,
        ),
        Step(
            name="ci / typecheck",
            description="mypy advisory baseline exposure",
            commands=[[sys.executable, "-m", "mypy", "src", "clawcodex_ext", "extensions"]],
            blocking=False,
            advisory=True,
        ),
        Step(
            name="ci / pytest-core",
            description="stable core pytest smoke without live provider keys",
            commands=[[sys.executable, "-m", "pytest", *CORE_PYTEST, "-q"]],
            skip_reason=None if _env_bool(env, "CI_RUN_PYTHON") else "no Python/package/CI changes",
            env=_clean_provider_env(),
        ),
        Step(
            name="ci / pytest-orchestrator",
            description="orchestrator smoke with report-only coverage",
            commands=[
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *ORCHESTRATOR_PYTEST,
                    "-q",
                    "--cov=extensions.orchestrator",
                    "--cov=clawcodex_ext",
                    "--cov=src",
                    "--cov-report=term-missing",
                    "--cov-report=xml",
                    "--cov-fail-under=0",
                ]
            ],
            skip_reason=(
                None
                if _env_bool(env, "CI_RUN_ORCHESTRATOR")
                else "no orchestrator/package/CI changes"
            ),
            env=_clean_provider_env(),
        ),
        Step(
            name="ci / package-smoke",
            description="build, twine check, install wheel, run clawcodex-dev --help",
            commands=[
                [sys.executable, "-m", "build"],
                [sys.executable, "-m", "twine", "check", "dist/*"],
                [sys.executable, "-m", "venv", str(smoke_dir)],
                [str(smoke_python), "-m", "pip", "install", "--upgrade", "pip"],
                [str(smoke_python), "-m", "pip", "install", "dist/*.whl"],
                [str(smoke_cli), "--help"],
            ],
            skip_reason=None if _env_bool(env, "CI_RUN_PACKAGE") else "docs-only change",
        ),
        Step(
            name="agent-smoke / agent-replay-smoke",
            description="mock LLM text/tool loop, transcript, resume, workspace hooks",
            commands=[[sys.executable, "-m", "pytest", *AGENT_SMOKE_PYTEST, "-q"]],
            skip_reason=None if not _env_bool(env, "CI_DOCS_ONLY") else "docs-only change",
            env=_clean_provider_env(),
        ),
        Step(
            name="security / supply-chain",
            description="secret and suspicious payload scan",
            commands=[supply_command],
            env=_clean_provider_env(),
        ),
        Step(
            name="security / CodeCheck",
            description="GitCode remote CodeCheck action",
            skip_reason="remote-only: requires GitCode Pipeline and GITCODE_TOKEN",
        ),
        Step(
            name="publish / TestPyPI-GitCode-Release",
            description="tag publish, TestPyPI/PyPI upload, GitCode Release assets",
            skip_reason="destructive external publish; use local_publish.py explicitly",
        ),
    ]


def _prepare_step(step: Step) -> None:
    if step.name == "ci / package-smoke":
        paths = [ROOT / "dist", ROOT / "build", ROOT / ".package-smoke"]
        paths.extend(path for path in ROOT.glob(SDIST_STAGING_DIR_GLOB) if path.is_dir())
        for path in paths:
            if path.exists():
                shutil.rmtree(path)


def _expand_globs(command: list[str]) -> list[str]:
    expanded: list[str] = []
    for item in command:
        if "*" not in item:
            expanded.append(item)
            continue
        matches = sorted(str(path) for path in ROOT.glob(item))
        expanded.extend(matches or [item])
    return expanded


def _print_plan(steps: list[Step]) -> None:
    print("\nPlanned local CI steps:")
    for index, step in enumerate(steps, start=1):
        status = "SKIP" if step.skip_reason else "PENDING"
        suffix = f" ({step.skip_reason})" if step.skip_reason else ""
        print(f"  {index:02d}. [{status}] {step.name}: {step.description}{suffix}")


def _append_detail(state: DisplayState, line: str, *, max_lines: int = 18) -> None:
    state.detail_lines.append(line)
    if len(state.detail_lines) > max_lines:
        state.detail_lines = state.detail_lines[-max_lines:]


def _status_text(status: str):
    if status == "pass":
        return Text("[OK] pass", style="bold green") if Text else "PASS"
    if status == "running":
        return Text("[RUN]", style="bold cyan") if Text else "RUN"
    if status == "skip":
        return Text("[SKIP]", style="yellow") if Text else "SKIP"
    if status == "fail":
        return Text("[FAIL]", style="bold red") if Text else "FAIL"
    if status == "advisory":
        return Text("[WARN]", style="bold magenta") if Text else "ADVISORY"
    return Text("[WAIT]", style="dim") if Text else "PENDING"


def _render_dashboard(state: DisplayState):
    elapsed = time.perf_counter() - state.started_at
    header = Table.grid(expand=True)
    header.add_column(ratio=1)
    header.add_column(justify="right")
    header.add_row(
        "[bold cyan]ClawCodex Local CI[/bold cyan]",
        f"[dim]elapsed {elapsed:.1f}s[/dim]",
    )
    header.add_row(
        f"[white]{state.scope_label}[/white]",
        (
            f"[green]{state.changed_count}[/green] files | "
            f"[cyan]{state.python_count}[/cyan] py | "
            f"[magenta]{state.docs_count}[/magenta] docs"
        ),
    )
    header.add_row("[dim]remote-only and destructive publish steps are shown but not run[/dim]", "")

    flow = Table(
        title="Total Flow",
        box=box.ROUNDED,
        expand=True,
        show_lines=False,
        border_style="blue",
    )
    flow.add_column("#", justify="right", style="dim", width=3)
    flow.add_column("Status", width=12)
    flow.add_column("Step", style="bold")
    flow.add_column("Checks")
    for index, step in enumerate(state.steps, start=1):
        flow.add_row(
            f"{index:02d}",
            _status_text(state.statuses[index - 1]),
            step.name,
            step.skip_reason or step.description,
        )

    detail = "\n".join(state.detail_lines) if state.detail_lines else "Waiting to start..."
    return Group(
        Panel(header, box=box.ROUNDED, border_style="cyan"),
        flow,
        Panel(detail, title="Step Detail", box=box.ROUNDED, border_style="green"),
    )


def _run_command_live(
    args: list[str],
    *,
    env: dict[str, str] | None,
    state: DisplayState,
    live,
    show_output: bool,
) -> CommandResult:
    started = time.perf_counter()
    output: list[str] = []
    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        clean = line.rstrip()
        output.append(clean)
        if show_output:
            _append_detail(state, f"  {clean}")
            live.update(_render_dashboard(state), refresh=True)
    returncode = proc.wait()
    return CommandResult(
        args=args,
        returncode=returncode,
        output="\n".join(output),
        duration=time.perf_counter() - started,
    )


def _run_step(step: Step, *, failure_lines: int, show_output: bool) -> bool:
    if step.skip_reason:
        print(f"\n[SKIP] {step.name}: {step.skip_reason}")
        return True

    _prepare_step(step)
    print(f"\n[RUN] {step.name}")
    print(f"  {step.description}")
    for command in step.commands:
        expanded = _expand_globs(command)
        print(f"  $ {_display_command(expanded)}")
        result = _run_command(expanded, env=step.env)
        if show_output and result.output:
            _print_output_tail(result.output, lines=10_000)
        if result.returncode == 0:
            print(f"  -> passed in {result.duration:.1f}s")
            continue

        status = "ADVISORY-FAIL" if step.advisory else "FAIL"
        print(f"[{status}] {step.name} exited {result.returncode} after {result.duration:.1f}s")
        print("  failure detail:")
        print(f"  command: {_display_command(expanded)}")
        _print_output_tail(result.output, lines=failure_lines)
        return not step.blocking

    print(f"[PASS] {step.name}")
    return True


def _run_step_live(
    step: Step,
    *,
    index: int,
    state: DisplayState,
    live,
    failure_lines: int,
    show_output: bool,
) -> bool:
    if step.skip_reason:
        state.statuses[index] = "skip"
        state.detail_lines = [f"[skip] {step.name}", step.skip_reason]
        live.update(_render_dashboard(state), refresh=True)
        return True

    _prepare_step(step)
    state.statuses[index] = "running"
    state.detail_lines = [f"[run] {step.name}", step.description]
    live.update(_render_dashboard(state), refresh=True)

    for command in step.commands:
        expanded = _expand_globs(command)
        _append_detail(state, f"$ {_display_command(expanded)}")
        live.update(_render_dashboard(state), refresh=True)
        result = _run_command_live(
            expanded,
            env=step.env,
            state=state,
            live=live,
            show_output=show_output,
        )
        if result.returncode == 0:
            _append_detail(state, f"-> passed in {result.duration:.1f}s")
            live.update(_render_dashboard(state), refresh=True)
            continue

        state.statuses[index] = "advisory" if step.advisory else "fail"
        status = "ADVISORY-FAIL" if step.advisory else "FAIL"
        post_lines = [
            f"[{status}] {step.name} exited {result.returncode} after {result.duration:.1f}s",
            "  failure detail:",
            f"  command: {_display_command(expanded)}",
        ]
        full_tail = (
            result.output.splitlines()[-failure_lines:]
            if result.output
            else ["<no command output>"]
        )
        post_lines.extend(f"  {line}" for line in full_tail)
        state.post_run_lines.extend(post_lines)

        detail_tail_budget = max(1, LIVE_DETAIL_MAX_LINES - 5)
        detail_tail = full_tail[-detail_tail_budget:]
        if len(full_tail) > detail_tail_budget:
            detail_tail = ["... output truncated in dashboard ...", *detail_tail]
        state.detail_lines = [
            f"[{'advisory' if step.advisory else 'fail'}] {step.name}",
            f"command: {_display_command(expanded)}",
            f"exit: {result.returncode} after {result.duration:.1f}s",
            "failure detail:",
        ]
        for line in detail_tail:
            _append_detail(state, f"  {line}", max_lines=LIVE_DETAIL_MAX_LINES)
        live.update(_render_dashboard(state), refresh=True)
        return not step.blocking

    state.statuses[index] = "pass"
    _append_detail(state, f"[pass] {step.name}")
    live.update(_render_dashboard(state), refresh=True)
    return True


def _run_steps_live(
    steps: list[Step],
    *,
    scope_label: str,
    continue_on_error: bool,
    failure_lines: int,
    show_output: bool,
    force_terminal: bool,
) -> int:
    changed_count, python_count, docs_count = _preflight_counts()
    console = Console(force_terminal=force_terminal, highlight=False, color_system="auto")
    state = DisplayState(
        steps=steps,
        statuses=["skip" if step.skip_reason else "pending" for step in steps],
        scope_label=scope_label,
        changed_count=changed_count,
        python_count=python_count,
        docs_count=docs_count,
        env_file=str(PREFLIGHT_ENV.relative_to(ROOT)),
        detail_lines=[f"preflight env: {PREFLIGHT_ENV.relative_to(ROOT)}"],
    )

    failures = 0
    with Live(
        _render_dashboard(state),
        console=console,
        refresh_per_second=8,
        transient=False,
        redirect_stdout=False,
        redirect_stderr=False,
        vertical_overflow="ellipsis",
    ) as live:
        for index, step in enumerate(steps):
            ok = _run_step_live(
                step,
                index=index,
                state=state,
                live=live,
                failure_lines=failure_lines,
                show_output=show_output,
            )
            if not ok:
                failures += 1
                if not continue_on_error:
                    break

        _append_detail(
            state,
            (
                f"[fail] local CI finished with {failures} blocking failure(s)."
                if failures
                else "[pass] local CI finished without blocking failures."
            ),
        )
        live.update(_render_dashboard(state), refresh=True)

    if state.post_run_lines:
        console.print("\n".join(state.post_run_lines), highlight=False, markup=False)
    final_message = (
        f"\n[FAIL] local CI finished with {failures} blocking failure(s)."
        if failures
        else "\n[PASS] local CI finished without blocking failures."
    )
    if Text:
        console.print(Text(final_message, style="bold red" if failures else "bold green"))
    else:
        console.print(final_message, highlight=False, markup=False)

    return 1 if failures else 0


def _console_print_lines(console, lines: list[str], *, style: str | None = None) -> None:
    text = "\n".join(lines)
    if Text and style:
        console.print(Text(text, style=style), highlight=False)
    else:
        console.print(text, highlight=False, markup=False)


def _run_steps_rich_static(
    steps: list[Step],
    *,
    scope_label: str,
    continue_on_error: bool,
    failure_lines: int,
    show_output: bool,
) -> int:
    changed_count, python_count, docs_count = _preflight_counts()
    console = Console(force_terminal=True, highlight=False, color_system="auto")
    state = DisplayState(
        steps=steps,
        statuses=["skip" if step.skip_reason else "pending" for step in steps],
        scope_label=scope_label,
        changed_count=changed_count,
        python_count=python_count,
        docs_count=docs_count,
        env_file=str(PREFLIGHT_ENV.relative_to(ROOT)),
        detail_lines=[f"preflight env: {PREFLIGHT_ENV.relative_to(ROOT)}"],
    )

    console.print(
        Panel(
            (
                f"[white]{scope_label}[/white]\n"
                f"[green]{changed_count}[/green] files | "
                f"[cyan]{python_count}[/cyan] py | "
                f"[magenta]{docs_count}[/magenta] docs\n"
                "[dim]static Rich output avoids overlapping live frames in this terminal[/dim]"
            ),
            title="ClawCodex Local CI",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    failures = 0
    for index, step in enumerate(steps):
        if step.skip_reason:
            state.statuses[index] = "skip"
            state.detail_lines = [f"[skip] {step.name}", step.skip_reason]
            _console_print_lines(
                console,
                [f"\n[SKIP] {step.name}: {step.skip_reason}"],
                style="yellow",
            )
            continue

        _prepare_step(step)
        state.statuses[index] = "running"
        state.detail_lines = [f"[run] {step.name}", step.description]
        _console_print_lines(
            console, [f"\n[RUN] {step.name}", f"  {step.description}"], style="cyan"
        )

        step_ok = True
        for command in step.commands:
            expanded = _expand_globs(command)
            command_text = _display_command(expanded)
            _append_detail(state, f"$ {command_text}")
            console.print(f"  $ {command_text}", highlight=False, markup=False)
            result = _run_command(expanded, env=step.env)
            if show_output and result.output:
                _console_print_lines(console, result.output.splitlines())

            if result.returncode == 0:
                _append_detail(state, f"-> passed in {result.duration:.1f}s")
                _console_print_lines(
                    console,
                    [f"  -> passed in {result.duration:.1f}s"],
                    style="green",
                )
                continue

            state.statuses[index] = "advisory" if step.advisory else "fail"
            status = "ADVISORY-FAIL" if step.advisory else "FAIL"
            tail = (
                result.output.splitlines()[-failure_lines:]
                if result.output
                else ["<no command output>"]
            )
            failure_detail = [
                f"[{status}] {step.name} exited {result.returncode} after {result.duration:.1f}s",
                "  failure detail:",
                f"  command: {command_text}",
                *[f"  {line}" for line in tail],
            ]
            state.detail_lines = failure_detail[:4] + [f"  {line}" for line in tail[-10:]]
            _console_print_lines(
                console,
                failure_detail,
                style="magenta" if step.advisory else "red",
            )
            step_ok = not step.blocking
            break

        if step_ok and state.statuses[index] == "running":
            state.statuses[index] = "pass"
            _append_detail(state, f"[pass] {step.name}")
            _console_print_lines(console, [f"[PASS] {step.name}"], style="green")
            continue

        if not step_ok:
            failures += 1
            if not continue_on_error:
                break

    _append_detail(
        state,
        (
            f"[fail] local CI finished with {failures} blocking failure(s)."
            if failures
            else "[pass] local CI finished without blocking failures."
        ),
    )
    console.print(_render_dashboard(state))
    final_message = (
        f"\n[FAIL] local CI finished with {failures} blocking failure(s)."
        if failures
        else "\n[PASS] local CI finished without blocking failures."
    )
    _console_print_lines(console, [final_message], style="red" if failures else "green")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        help="Run changed-file mode against this base ref. Defaults to current commit (HEAD~1).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tracked-file gates. This may expose historical documentation debt.",
    )
    parser.add_argument("--list", action="store_true", help="Print the computed plan only.")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--show-output", action="store_true", help="Print passing command output too."
    )
    parser.add_argument("--failure-lines", type=int, default=120)
    parser.add_argument(
        "--ui",
        choices=["auto", "rich", "plain"],
        default="auto",
        help="Use the live Rich dashboard in terminals, or force plain output.",
    )
    args = parser.parse_args(argv)

    base = args.base or _default_base()
    all_files = args.all
    scope_label = (
        "all tracked files"
        if all_files
        else f"changed files vs {args.base}"
        if args.base
        else "current commit (HEAD~1..HEAD)"
    )

    env = _write_preflight(base, all_files, scope_label=scope_label)
    steps = _build_steps(env, all_files=all_files, base=base)
    _print_plan(steps)
    if args.list:
        return 0

    ui_mode, ui_reason = _resolve_ui(args.ui, os.environ, sys.stdout)
    ui_label = {
        "live": "rich live dashboard",
        "static": "rich static output",
        "plain": "plain output",
    }[ui_mode]
    print(f"\n[INFO] UI: {ui_label} ({ui_reason})")
    if ui_mode == "live" and RICH_AVAILABLE:
        return _run_steps_live(
            steps,
            scope_label=scope_label,
            continue_on_error=args.continue_on_error,
            failure_lines=args.failure_lines,
            show_output=args.show_output,
            force_terminal=True,
        )
    if ui_mode == "static" and RICH_AVAILABLE:
        return _run_steps_rich_static(
            steps,
            scope_label=scope_label,
            continue_on_error=args.continue_on_error,
            failure_lines=args.failure_lines,
            show_output=args.show_output,
        )

    failures = 0
    for step in steps:
        ok = _run_step(step, failure_lines=args.failure_lines, show_output=args.show_output)
        if not ok:
            failures += 1
            if not args.continue_on_error:
                break

    if failures:
        print(f"\n[FAIL] local CI finished with {failures} blocking failure(s).")
        return 1

    print("\n[PASS] local CI finished without blocking failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

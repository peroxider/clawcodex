"""Run the F-73 release path locally.

This is the fallback path for GitCode projects that do not have Pipeline or
repository secret support enabled. Tokens are loaded from environment variables
first, then from the repository's ignored ``.env`` file.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from env_loader import ROOT, ensure_dotenv, load_dotenv

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - rich is optional for this helper.
    box = None
    Console = Live = Table = Text = None
    RICH_AVAILABLE = False


PYTEST_SMOKE = [
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
    "tests/agent/test_agent_smoke_no_live_key.py",
    "tests/orchestrator/test_local_tracker_parser.py",
    "tests/orchestrator/test_orchestrator_f39_intent.py",
    "tests/orchestrator/test_orchestrator_f49_transcript.py",
    "tests/orchestrator/test_orchestrator_f49_resume.py",
    "tests/orchestrator/test_orchestrator_workspace_hooks.py",
    "tests/test_visualizer/test_orchestrator_link.py",
]
RELEASE_RUFF_FILES = [
    "scripts/ci/dev_setup.py",
    "scripts/ci/docs_check.py",
    "scripts/ci/env_loader.py",
    "scripts/ci/gitcode_release.py",
    "scripts/ci/local_publish.py",
    "scripts/ci/preflight.py",
    "scripts/ci/supply_chain_audit.py",
]
PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GLM_API_KEY", "ZHIPUAI_API_KEY")
RELEASE_SMOKE_DIR = ROOT / ".release-smoke"
SDIST_STAGING_DIR_GLOB = "clawcodex_dev_mind-*"


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    output: str
    duration: float


@dataclass
class FlowStep:
    name: str
    description: str
    skip_reason: str | None = None
    advisory: bool = False
    status: str = "WAIT"
    result: str = ""


@dataclass
class ReleaseContext:
    env_path: Path | None = None
    env_created: bool = False
    tag: str | None = None
    target_sha: str | None = None


class StepFailure(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(f"command exited {result.returncode}")


class StepSkipped(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _display_command(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


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


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _artifact_locations() -> list[tuple[str, str]]:
    return [
        (".env", "ignored token file created from .env.example when missing"),
        ("dist/", "wheel and sdist produced by package smoke and uploaded by publish"),
        ("build/", "PEP 517 build scratch directory"),
        (".release-smoke/", "temporary venv used to install the built wheel"),
        (SDIST_STAGING_DIR_GLOB, "sdist staging directories cleaned before package smoke"),
    ]


def _print_artifact_locations() -> None:
    print("\nLocal release artifact paths:")
    print(f"  repository root: {ROOT}")
    for path, description in _artifact_locations():
        print(f"  {path}: {description}")


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


def _run_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    show_output: bool = False,
) -> CommandResult:
    print(f"  $ {_display_command(args)}")
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
    result = CommandResult(
        args=args,
        returncode=proc.returncode,
        output=proc.stdout,
        duration=time.perf_counter() - started,
    )
    if show_output and result.output:
        _print_output_tail(result.output, lines=10_000)
    if result.returncode != 0:
        raise StepFailure(result)
    print(f"  -> passed in {result.duration:.1f}s")
    return result


def _git(args: list[str], *, show_output: bool = False) -> str:
    return _run_command(["git", *args], show_output=show_output).output.strip()


def _token(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required; put it in .env or export it in your shell")
    return value


def _optional_token(name: str) -> str | None:
    return os.environ.get(name) or None


def _effective_release_target(release_target: str | None) -> str:
    return release_target or "testpypi"


def _required_tokens(
    release_target: str | None,
    skip_gitcode_release: bool,
    *,
    require_publish_token: bool = True,
) -> list[str]:
    tokens: list[str] = []
    if require_publish_token and release_target:
        tokens.append("PYPI_TOKEN" if release_target == "pypi" else "TEST_PYPI_TOKEN")
    if not skip_gitcode_release:
        tokens.append("GITCODE_TOKEN")
    return tokens


def _load_environment(ctx: ReleaseContext) -> None:
    env_path, created = ensure_dotenv()
    load_dotenv(env_path)
    ctx.env_path = env_path
    ctx.env_created = created
    if created:
        print(f"  created local release environment template: {_relative(env_path)}")
    else:
        print(f"  local release environment template exists: {_relative(env_path)}")
    print(f"  loaded local release environment from: {_relative(env_path)}")


def _check_credentials(
    release_target: str | None,
    skip_gitcode_release: bool,
    *,
    require_publish_token: bool,
) -> None:
    for name in _required_tokens(
        release_target,
        skip_gitcode_release,
        require_publish_token=require_publish_token,
    ):
        value = _token(name)
        print(f"  {name}: set ({len(value)} chars)")


def _ensure_clean_tracked_tree() -> None:
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False)
    unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT, check=False)
    if staged.returncode == 0 and unstaged.returncode == 0:
        print("  tracked working tree is clean")
        return

    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        encoding="utf-8",
        errors="replace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout.strip()
    detail = f"\n{status}" if status else ""
    raise RuntimeError(
        "Tracked working tree changes exist; commit or stash them before publishing" + detail
    )


def _resolve_tag(
    tag: str | None,
    *,
    show_output: bool = False,
    create_missing: bool = False,
    dry_run: bool = False,
) -> tuple[str, str]:
    if tag is None:
        described = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=ROOT,
            encoding="utf-8",
            errors="replace",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if described.returncode != 0 or not described.stdout.strip():
            raise RuntimeError(
                "Release tag is required; pass --tag or run from an exact tag checkout"
            )
        tag = described.stdout.strip()

    _run_command(["git", "fetch", "--tags", "--force"], show_output=show_output)
    head_sha = _git(["rev-parse", "HEAD"], show_output=show_output)
    exists = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode != 0:
        if not create_missing:
            raise RuntimeError(f"Release tag {tag} does not exist; pass --tag to create it at HEAD")
        if dry_run:
            print(f"  dry-run: would create release tag: {tag} -> {head_sha}")
            print(f"  release tag: {tag}")
            print(f"  release target sha: {head_sha}")
            return tag, head_sha

        _run_command(["git", "tag", tag, head_sha], show_output=show_output)
        print(f"  created local release tag: {tag} -> {head_sha}")

    tag_sha = _git(["rev-list", "-n", "1", tag], show_output=show_output)
    if tag_sha != head_sha:
        raise RuntimeError(
            f"Release tag {tag} points to {tag_sha}, but HEAD is {head_sha}; "
            "check out the tag commit before publishing locally"
        )
    print(f"  release tag: {tag}")
    print(f"  release target sha: {tag_sha}")
    return tag, tag_sha


def _clean_provider_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in PROVIDER_KEYS:
        env[key] = ""
    return env


def _clean_artifacts() -> None:
    removed: list[str] = []
    for path in (ROOT / "dist", ROOT / "build", RELEASE_SMOKE_DIR):
        if path.exists():
            shutil.rmtree(path)
            removed.append(_relative(path))
    for path in ROOT.glob(SDIST_STAGING_DIR_GLOB):
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(_relative(path))

    if removed:
        print("  removed:")
        for path in removed:
            print(f"    - {path}")
    else:
        print("  no local release artifacts needed cleanup")


def _dist_files() -> list[Path]:
    dist = ROOT / "dist"
    if not dist.exists():
        raise RuntimeError("No distribution files found in dist")
    files = sorted(path for path in dist.iterdir() if path.is_file())
    if not files:
        raise RuntimeError("No distribution files found in dist")
    return files


def _wheel_file() -> Path:
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    if not wheels:
        raise RuntimeError("No wheel file found in dist")
    return wheels[0]


def _run_release_lint(*, show_output: bool) -> None:
    _run_command(
        [sys.executable, "-m", "ruff", "check", *RELEASE_RUFF_FILES], show_output=show_output
    )
    _run_command(
        [sys.executable, "-m", "ruff", "format", "--check", *RELEASE_RUFF_FILES],
        show_output=show_output,
    )


def _run_typecheck(*, show_output: bool) -> None:
    _run_command(
        [sys.executable, "-m", "mypy", "src", "clawcodex_ext", "extensions"],
        show_output=show_output,
    )


def _run_tests(*, show_output: bool) -> None:
    _run_command(
        [sys.executable, "-m", "pytest", *PYTEST_SMOKE, "-q"],
        env=_clean_provider_env(),
        show_output=show_output,
    )


def _run_package_smoke(*, show_output: bool) -> None:
    smoke_python = RELEASE_SMOKE_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    smoke_cli = RELEASE_SMOKE_DIR / (
        "Scripts/clawcodex-dev.exe" if os.name == "nt" else "bin/clawcodex-dev"
    )

    _run_command([sys.executable, "-m", "build"], show_output=show_output)
    dist_files = [str(path) for path in _dist_files()]
    _run_command([sys.executable, "-m", "twine", "check", *dist_files], show_output=show_output)
    _run_command([sys.executable, "-m", "venv", str(RELEASE_SMOKE_DIR)], show_output=show_output)
    _run_command(
        [str(smoke_python), "-m", "pip", "install", "--upgrade", "pip"],
        show_output=show_output,
    )
    _run_command(
        [str(smoke_python), "-m", "pip", "install", str(_wheel_file())],
        show_output=show_output,
    )
    _run_command([str(smoke_cli), "--help"], show_output=show_output)
    print(f"  smoke venv: {_relative(RELEASE_SMOKE_DIR)}")


def _publish_package(release_target: str, dry_run: bool, *, show_output: bool) -> None:
    dist_files = [str(path) for path in _dist_files()]
    if dry_run:
        print(f"  dry-run: would upload {len(dist_files)} dist files to {release_target}")
        for path in dist_files:
            print(f"    - {_relative(Path(path))}")
        return

    env = os.environ.copy()
    env["TWINE_USERNAME"] = "__token__"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    if release_target == "pypi":
        token_name = "PYPI_TOKEN"
        token = _optional_token(token_name)
        if token is None:
            raise StepSkipped(f"{token_name} is not set; skipping package upload")
        env["TWINE_PASSWORD"] = token
        command = [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--disable-progress-bar",
            *dist_files,
        ]
    else:
        token_name = "TEST_PYPI_TOKEN"
        token = _optional_token(token_name)
        if token is None:
            raise StepSkipped(f"{token_name} is not set; skipping package upload")
        env["TWINE_PASSWORD"] = token
        command = [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--disable-progress-bar",
            "--repository-url",
            "https://test.pypi.org/legacy/",
            *dist_files,
        ]
    _run_command(command, env=env, show_output=show_output)


def _publish_gitcode_release(
    *,
    release_target: str,
    tag: str,
    target_sha: str,
    dry_run: bool,
    show_output: bool,
) -> None:
    if dry_run:
        print("  dry-run: would create/update GitCode Release and upload dist assets")
        print(f"  tag: {tag}")
        print(f"  target: {target_sha}")
        print("  assets: dist/")
        return
    _token("GITCODE_TOKEN")
    command = [
        sys.executable,
        "scripts/ci/gitcode_release.py",
        "--owner",
        os.environ.get("GITCODE_OWNER", ""),
        "--repo",
        os.environ.get("GITCODE_REPO", ""),
        "--tag",
        tag,
        "--target",
        target_sha,
        "--dist",
        "dist",
        "--body",
        "Automated ClawCodex package release",
    ]
    if release_target != "pypi":
        command.append("--prerelease")
    _run_command(command, show_output=show_output)


def _build_step_plan(args: argparse.Namespace) -> list[FlowStep]:
    credential_skip = None
    if args.dry_run and not args.check_credentials:
        credential_skip = "dry-run does not require publish tokens"
    mode_skip = "credential check mode" if args.check_credentials else None
    return [
        FlowStep("release / environment", "create/load ignored .env release config"),
        FlowStep(
            "release / credentials",
            "verify PyPI/TestPyPI token and GitCode token names",
            skip_reason=credential_skip,
        ),
        FlowStep(
            "release / clean-tree",
            "require no tracked working-tree changes before publish",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "release / tag",
            "fetch tags and require HEAD to match the release tag",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "release / clean-artifacts",
            "remove dist, build, .release-smoke, and sdist staging dirs",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "ci / release-lint",
            "ruff check and ruff format --check for CI helper files",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "ci / typecheck-advisory",
            "mypy baseline exposure; recorded but not release-blocking",
            skip_reason=mode_skip,
            advisory=True,
        ),
        FlowStep(
            "ci / release-tests",
            "core, agent, orchestrator, and GitCode release smoke pytest set",
            skip_reason=mode_skip or ("--skip-tests was requested" if args.skip_tests else None),
        ),
        FlowStep(
            "ci / package-smoke",
            "build, twine check, install wheel in .release-smoke, run CLI help",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "publish / package",
            "upload dist assets to TestPyPI or PyPI, or list them in dry-run mode",
            skip_reason=mode_skip,
        ),
        FlowStep(
            "publish / GitCode Release",
            "create/update GitCode Release and upload dist assets",
            skip_reason=mode_skip
            or ("--skip-gitcode-release was requested" if args.skip_gitcode_release else None),
        ),
    ]


def _status_label(status: str) -> str:
    return {
        "WAIT": "[WAIT]",
        "RUN": "[RUN]",
        "PASS": "[PASS]",
        "SKIP": "[SKIP]",
        "FAIL": "[FAIL]",
        "WARN": "[WARN]",
    }[status]


def _print_plan(steps: list[FlowStep]) -> None:
    print("\nPlanned local publish steps:")
    for index, step in enumerate(steps, start=1):
        status = "SKIP" if step.skip_reason else "PENDING"
        suffix = f" ({step.skip_reason})" if step.skip_reason else ""
        print(f"  {index:02d}. [{status}] {step.name}: {step.description}{suffix}")


def _render_flow_table(steps: list[FlowStep], *, title: str):
    table = Table(title=title, box=box.ROUNDED, expand=True, border_style="blue")
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Status", width=10)
    table.add_column("Step", style="bold")
    table.add_column("Result")
    styles = {
        "WAIT": "dim",
        "RUN": "bold cyan",
        "PASS": "bold green",
        "SKIP": "yellow",
        "FAIL": "bold red",
        "WARN": "bold magenta",
    }
    for index, step in enumerate(steps, start=1):
        status = "SKIP" if step.skip_reason and step.status == "WAIT" else step.status
        result = step.result or step.skip_reason or step.description
        table.add_row(
            f"{index:02d}",
            Text(_status_label(status), style=styles[status]),
            step.name,
            result,
        )
    return table


def _print_flow_table(
    steps: list[FlowStep],
    *,
    title: str,
    rich: bool | None = None,
    console=None,
) -> None:
    use_rich = RICH_AVAILABLE if rich is None else rich
    if use_rich and RICH_AVAILABLE:
        active_console = console or Console(
            force_terminal=True,
            highlight=False,
            color_system="auto",
        )
        active_console.print(_render_flow_table(steps, title=title))
        return

    print(f"\n{title}")
    print("+----+----------+---------------------------+----------------------------------------+")
    print("| #  | Status   | Step                      | Result                                 |")
    print("+----+----------+---------------------------+----------------------------------------+")
    for index, step in enumerate(steps, start=1):
        status = "SKIP" if step.skip_reason and step.status == "WAIT" else step.status
        result = step.result or step.skip_reason or step.description
        print(
            f"| {index:02d} | {_status_label(status):8} | {step.name[:25]:25} | {result[:38]:38} |"
        )
    print("+----+----------+---------------------------+----------------------------------------+")


def _print_failure_detail(error: BaseException, *, failure_lines: int) -> None:
    print("  failure detail:")
    if isinstance(error, StepFailure):
        result = error.result
        print(f"  command: {_display_command(result.args)}")
        print(f"  exit code: {result.returncode}")
        _print_output_tail(result.output, lines=failure_lines)
        return
    for line in str(error).splitlines() or ["<no error message>"]:
        print(f"  {line}")


class FlowRunner:
    def __init__(
        self,
        steps: list[FlowStep],
        *,
        failure_lines: int,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.steps = steps
        self.failure_lines = failure_lines
        self.on_update = on_update

    def _notify_update(self) -> None:
        if self.on_update is not None:
            self.on_update()

    def run(self, step: FlowStep, action: Callable[[], None]) -> bool:
        if step.skip_reason:
            step.status = "SKIP"
            step.result = step.skip_reason
            print(f"\n[SKIP] {step.name}: {step.skip_reason}")
            self._notify_update()
            return True

        step.status = "RUN"
        print(f"\n[RUN] {step.name}")
        print(f"  {step.description}")
        self._notify_update()
        started = time.perf_counter()
        try:
            action()
        except StepSkipped as skipped:
            step.status = "SKIP"
            step.result = skipped.reason
            print(f"[SKIP] {step.name}: {skipped.reason}")
            self._notify_update()
            return True
        except (RuntimeError, StepFailure) as error:
            elapsed = time.perf_counter() - started
            if step.advisory:
                step.status = "WARN"
                step.result = f"advisory failed after {elapsed:.1f}s"
                print(f"[WARN] {step.name} advisory failed after {elapsed:.1f}s")
                _print_failure_detail(error, failure_lines=self.failure_lines)
                self._notify_update()
                return True
            step.status = "FAIL"
            step.result = f"failed after {elapsed:.1f}s"
            print(f"[FAIL] {step.name} failed after {elapsed:.1f}s")
            _print_failure_detail(error, failure_lines=self.failure_lines)
            self._notify_update()
            return False

        elapsed = time.perf_counter() - started
        step.status = "PASS"
        step.result = f"passed in {elapsed:.1f}s"
        print(f"[PASS] {step.name} passed in {elapsed:.1f}s")
        self._notify_update()
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-target", choices=["testpypi", "pypi"])
    parser.add_argument("--tag", help="Existing release tag, for example v0.5.0")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-gitcode-release", action="store_true")
    parser.add_argument(
        "--check-credentials",
        action="store_true",
        help=(
            "Load .env and verify required token names without building or uploading; "
            "PyPI/TestPyPI tokens are checked only when --release-target is set"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true", help="Print the computed release flow only.")
    parser.add_argument(
        "--show-output",
        action="store_true",
        help="Print passing command output too.",
    )
    parser.add_argument("--failure-lines", type=int, default=120)
    parser.add_argument(
        "--ui",
        choices=["auto", "rich", "plain"],
        default="auto",
        help="Use the live Rich dashboard in terminals, or force plain output.",
    )
    args = parser.parse_args(argv)
    effective_release_target = _effective_release_target(args.release_target)
    require_publish_token = bool(args.release_target)

    ctx = ReleaseContext()
    steps = _build_step_plan(args)
    print("ClawCodex Local Publish")
    print(f"  target: {effective_release_target}")
    print(
        f"  mode: {'credential-check' if args.check_credentials else 'dry-run' if args.dry_run else 'publish'}"
    )
    _print_artifact_locations()
    _print_plan(steps)

    ui_mode, ui_reason = _resolve_ui(args.ui, os.environ, sys.stdout)
    ui_label = {
        "live": "rich live dashboard",
        "static": "rich static output",
        "plain": "plain output",
    }[ui_mode]
    if args.list:
        _print_flow_table(steps, title="Total Publish Flow", rich=ui_mode != "plain")
        return 0
    print(f"\n[INFO] UI: {ui_label} ({ui_reason})")

    actions: dict[str, Callable[[], None]] = {
        "release / environment": lambda: _load_environment(ctx),
        "release / credentials": lambda: _check_credentials(
            args.release_target,
            args.skip_gitcode_release,
            require_publish_token=require_publish_token,
        ),
        "release / clean-tree": _ensure_clean_tracked_tree,
        "release / tag": lambda: _set_release_tag(
            ctx,
            args.tag,
            show_output=args.show_output,
            dry_run=args.dry_run,
        ),
        "release / clean-artifacts": _clean_artifacts,
        "ci / release-lint": lambda: _run_release_lint(show_output=args.show_output),
        "ci / typecheck-advisory": lambda: _run_typecheck(show_output=args.show_output),
        "ci / release-tests": lambda: _run_tests(show_output=args.show_output),
        "ci / package-smoke": lambda: _run_package_smoke(show_output=args.show_output),
        "publish / package": lambda: _publish_package(
            effective_release_target,
            args.dry_run,
            show_output=args.show_output,
        ),
        "publish / GitCode Release": lambda: _publish_gitcode_release(
            release_target=effective_release_target,
            tag=_require_context_value(ctx.tag, "release tag"),
            target_sha=_require_context_value(ctx.target_sha, "release target sha"),
            dry_run=args.dry_run,
            show_output=args.show_output,
        ),
    }

    console = None
    if ui_mode in {"live", "static"} and RICH_AVAILABLE:
        console = Console(force_terminal=True, highlight=False, color_system="auto")

    if ui_mode == "live" and RICH_AVAILABLE:
        runner = FlowRunner(steps, failure_lines=args.failure_lines)
        failed = False
        with Live(
            _render_flow_table(steps, title="Total Publish Flow"),
            console=console,
            refresh_per_second=8,
            transient=False,
            redirect_stdout=True,
            redirect_stderr=True,
            vertical_overflow="ellipsis",
        ) as live:

            def refresh_live_flow_table() -> None:
                live.update(_render_flow_table(steps, title="Total Publish Flow"), refresh=True)

            runner.on_update = refresh_live_flow_table
            for step in steps:
                if not runner.run(step, actions[step.name]):
                    failed = True
                    break

        if failed:
            print("\n[FAIL] local publish finished with a blocking failure.")
            return 1
        print("\n[PASS] local publish finished without blocking failures.")
        return 0

    runner = FlowRunner(steps, failure_lines=args.failure_lines)
    _print_flow_table(
        steps,
        title="Total Publish Flow",
        rich=ui_mode != "plain",
        console=console,
    )
    for step in steps:
        if not runner.run(step, actions[step.name]):
            _print_flow_table(
                steps,
                title="Total Publish Flow",
                rich=ui_mode != "plain",
                console=console,
            )
            print("\n[FAIL] local publish finished with a blocking failure.")
            return 1

    _print_flow_table(
        steps,
        title="Total Publish Flow",
        rich=ui_mode != "plain",
        console=console,
    )
    print("\n[PASS] local publish finished without blocking failures.")
    return 0


def _set_release_tag(
    ctx: ReleaseContext,
    tag: str | None,
    *,
    show_output: bool,
    dry_run: bool,
) -> None:
    ctx.tag, ctx.target_sha = _resolve_tag(
        tag,
        show_output=show_output,
        create_missing=tag is not None,
        dry_run=dry_run,
    )


def _require_context_value(value: str | None, label: str) -> str:
    if value is None:
        raise RuntimeError(f"{label} is unavailable because an earlier release step did not run")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

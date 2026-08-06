"""REPL showcase: real orchestrator batch + REPL ``/dashboard`` → one ``.cast``.

This example composes the auto-demo path (real ``GitSyncService.sync``) with
REPL-style prompt markers and the live ``/dashboard``
formatter from ``clawcodex_ext.command_system.dashboard_command`` so
that a single ``.cast`` file shows a developer running
``clawcodex-dev --record`` while a real orchestrator batch executes in
the background and the REPL ``/dashboard`` command snapshots the
progress every couple of seconds.

What the script writes into the ``.cast``:

* Every per-session ``PhaseComplete`` / ``SessionComplete`` event
  emitted by ``AsciicastSink`` → ``m`` markers ``[phase N/T]`` and
  ``session:<reason>``
* Every 2 s a simulated "user typed /dashboard" sequence:
  - marker ``repl:prompt:start``
  - marker ``repl:command:/dashboard``
  - marker ``repl:prompt:submit``
  - one ``o`` frame per section of the real ``/dashboard`` snapshot
    (rendered via ``_format_snapshot`` — the same Rich markup the
    interactive REPL produces when a user runs the command, so the
    .cast content matches what the user actually sees)
* Frames are flushed per-frame so ``tail -f`` reads incrementally.

Note: the prompt_toolkit prompt bar itself (``❯`` glyph, line edit,
status row) is rendered by prompt_toolkit and not captured by
``install_repl_capture`` — see ``repl_source.py`` for that REPL
capture limitation. The markers + the rendered snapshot together reconstruct
the user-perceived ``/dashboard`` event flow in playback.

Layer rule (CLAUDE.md): this file lives in Layer 2 alongside the
recorder package and is independent from ``src/`` /
``clawcodex_ext/``. It is a runnable example, not a public CLI
subcommand.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

# Allow ``python extensions/recording/examples/repl_orchestrator_showcase.py``
# from a fresh checkout without requiring the package to be installed.
_PKG_PARENT = Path(__file__).resolve().parents[3]
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from extensions.agent_dashboard.sources.orchestrator_source import (  # noqa: E402
    OrchestratorDashboardSource,
)
from extensions.agent_dashboard.source_registry import (  # noqa: E402
    get_default_registry,
    unregister_dashboard_source,
)
from extensions.api.query import PhaseComplete, SessionComplete  # noqa: E402
from extensions.capabilities.dashboard_entry import (  # noqa: E402
    DASHBOARD_STATUS_COMPLETED,
    DASHBOARD_STATUS_FAILED,
    DASHBOARD_STATUS_IN_PROGRESS,
    DASHBOARD_STATUS_PENDING,
    DashboardEntry,
)
from extensions.capabilities.recorder import AsciicastEvent, AsciicastHeader  # noqa: E402
from extensions.orchestrator.config.schema import (  # noqa: E402
    AgentConfig,
    HooksConfig,
)
from extensions.orchestrator.git_sync import GitSyncService  # noqa: E402
from extensions.orchestrator.issue import Issue  # noqa: E402
from extensions.orchestrator.local_tracker.adapter import LocalTrackerAdapter  # noqa: E402
from extensions.orchestrator.orchestrator import Orchestrator  # noqa: E402
from extensions.orchestrator.workspace import (  # noqa: E402
    WorkspaceConfig,
    WorkspaceManager,
)
from extensions.recording.asciicast_writer import AsciicastWriter  # noqa: E402
from extensions.recording.validate_cast import validate_cast  # noqa: E402

# Reuse the real ``/dashboard`` renderer so the .cast content matches
# what a user sees when typing ``/dashboard`` in the interactive REPL.
# The previous version called ``AsciicastDashboardSource.record_snapshot``
# (a home-grown ASCII panel) and looked nothing like the real dashboard
# in the rendered MP4 — see that insight in the demo commit history.
from clawcodex_ext.command_system.dashboard_command import (  # noqa: E402
    _format_snapshot,
)

logger = logging.getLogger(__name__)

__all__ = ["build_parser", "main", "run"]


# ---------------------------------------------------------------------------
# Reused scaffolding (mirrors extensions/recording/auto_demo.py)
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _build_origin(base: Path) -> Path:
    origin = base / "origin.git"
    seed = base / "seed"
    seed.mkdir(parents=True)
    _git(["init", "--bare", str(origin)], base)
    _git(["init"], seed)
    _git(["config", "user.email", "demo@example.com"], seed)
    _git(["config", "user.name", "Auto Demo"], seed)
    (seed / "README.md").write_text("main branch\n", encoding="utf-8")
    _git(["add", "README.md"], seed)
    _git(["commit", "-m", "initial"], seed)
    _git(["branch", "-M", "main"], seed)
    _git(["remote", "add", "origin", str(origin)], seed)
    _git(["push", "-u", "origin", "main"], seed)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], origin)
    return origin


def _write_issue(issues_dir: Path, issue_id: str, identifier: str, title: str) -> Path:
    issues_dir.mkdir(parents=True, exist_ok=True)
    path = issues_dir / f"{identifier}.md"
    path.write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"identifier: {identifier}\n"
        f"state: open\n"
        f"labels: [agent:run]\n"
        "---\n"
        f"# {title}\n\n"
        "Add a small verifiable change to the repository.\n",
        encoding="utf-8",
    )
    return path


def _issues_for_showcase() -> list[dict[str, str]]:
    return [
        {"id": "repl-1", "identifier": "REPL-1", "title": "Add login form validation"},
        {"id": "repl-2", "identifier": "REPL-2", "title": "Refactor retry loop"},
        {"id": "repl-3", "identifier": "REPL-3", "title": "Migrate DB schema v3"},
    ]


def _agent_hook_configs_for(issue_index: int) -> tuple[AgentConfig, HooksConfig]:
    if issue_index == 0:
        return (
            AgentConfig(test_command="true"),
            HooksConfig(),
        )
    if issue_index == 1:
        return (
            AgentConfig(test_command="false"),
            HooksConfig(),
        )
    return (
        AgentConfig(test_command="true"),
        HooksConfig(),
    )


# ---------------------------------------------------------------------------
# Dashboard projection (synthetic + live)
# ---------------------------------------------------------------------------


def _issue_to_entry(
    issue_id: str,
    identifier: str,
    title: str,
    status: str,
    progress_pct: float | None = None,
    detail: str = "",
) -> DashboardEntry:
    return DashboardEntry(
        id=f"local:{issue_id}",
        source="local",
        title=identifier,
        status=status,
        detail=detail,
        progress_pct=progress_pct,
        owner="repl_showcase",
    )


def _seed_entries(issues: list[dict[str, str]]) -> list[DashboardEntry]:
    return [
        _issue_to_entry(
            i["id"], i["identifier"], i["title"], status=DASHBOARD_STATUS_PENDING
        )
        for i in issues
    ]


def _update_entry(
    entries: list[DashboardEntry],
    issue_id: str,
    *,
    status: str | None = None,
    progress_pct: float | None = None,
    detail: str | None = None,
) -> list[DashboardEntry]:
    for idx, entry in enumerate(entries):
        if entry.id.endswith(issue_id):
            updated = entry
            if status is not None:
                updated = replace(updated, status=status)
            if progress_pct is not None:
                updated = replace(updated, progress_pct=progress_pct)
            if detail is not None:
                updated = replace(updated, detail=detail)
            entries[idx] = updated
            return entries
    return entries


# ---------------------------------------------------------------------------
# REPL `/dashboard` echo + real snapshot — uses the *same* renderer the
# interactive REPL calls into when the user submits the slash command.
# ---------------------------------------------------------------------------


def _emit_repl_prompt_echo(capture: Any, tick: int) -> None:
    """Emit the prompt boundary markers for a simulated ``/dashboard`` submit."""
    capture.marker("repl:prompt:start", text=f"prompt {tick}")
    capture.marker("repl:command:/dashboard", text="user typed /dashboard")
    capture.marker("repl:prompt:submit", text=f"submit {tick}")


def _emit_dashboard_snapshot(
    capture: Any, entries: list[DashboardEntry], tick: int
) -> None:
    """Render the dashboard via the *real* ``/dashboard`` formatter.

    Calls ``extensions.recording.repl_source``'s pipeline-equivalent path:
    the same ``_format_snapshot`` function the live ``DashboardCommand``
    uses, so the .cast output is character-for-character identical to
    what an interactive REPL user sees when they type ``/dashboard``.
    """
    snapshot = _format_snapshot(entries)
    # Per-section split so the eventual MP4 shows one block at a time
    # rather than landing the whole render in a single instant.
    blocks = snapshot.split("\n\n")
    capture.marker(
        "dashboard:snapshot", text=f"REPL /dashboard snapshot tick {tick}"
    )
    for block in blocks:
        capture.emit(AsciicastEvent(t=0.0, kind="o", data=block.rstrip() + "\n"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run(
    out_path: Path,
    *,
    duration_s: float = 12.0,
    issue_count: int = 3,
    frame_delay_s: float = 2.0,
) -> int:
    """Drive the REPL showcase end-to-end. Returns the process exit code.

    Parameters mirror :func:`extensions.recording.auto_demo.run` so the
    two demos share a familiar CLI surface.
    """
    out_path = Path(out_path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Defensive input validation (same rules as the auto-demo path).
    import math

    if not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError(
            f"duration_s must be non-negative finite; got {duration_s!r}"
        )
    if not math.isfinite(frame_delay_s) or frame_delay_s <= 0:
        raise ValueError(
            f"frame_delay_s must be positive finite; got {frame_delay_s!r}"
        )
    if int(issue_count) < 1:
        raise ValueError(f"issue_count must be >= 1; got {issue_count!r}")

    from extensions.capabilities.recorder import AsciicastEvent

    issues = _issues_for_showcase()[: max(1, int(issue_count))]
    run_dir = Path(tempfile.mkdtemp(prefix=f".repl-showcase-{out_path.stem}-"))

    base = run_dir
    origin = _build_origin(base)
    issues_dir = base / "issues"
    for issue in issues:
        _write_issue(issues_dir, issue["id"], issue["identifier"], issue["title"])

    tracker = LocalTrackerAdapter(issues_path=issues_dir)
    workspace_root = base / "workspaces"
    manager = WorkspaceManager(
        WorkspaceConfig(
            root=workspace_root,
            repo_clone_url=str(origin),
            checkout_issue_branch=True,
        )
    )

    header = AsciicastHeader(
        width=120,
        height=36,
        timestamp=int(time.time()),
        command="clawcodex-dev --record <path> (REPL /dashboard showcase)",
        title=f"REPL /dashboard showcase — {len(issues)} issue(s) in {duration_s:.0f}s",
    )
    writer = AsciicastWriter(out_path, header)
    writer.open()
    capture = writer.capture

    # Wire OrchestratorDashboardSource as in the auto-demo path so the registry
    # also exposes a live source for any other in-process puller; the
    # REPL showcase itself reads entries from a synthetic mirror to
    # avoid coupling the demo to a real orchestrator_provider.
    orch_holder: dict[str, Orchestrator | None] = {"orch": None}
    orch_source = OrchestratorDashboardSource(
        orchestrator_provider=lambda: orch_holder["orch"]
    )
    registry = get_default_registry()
    registry.register(orch_source)

    from tests.orchestrator.manual_e2e_f38 import _Session

    synth_entries = _seed_entries(issues)

    try:
        # Build a minimal orchestrator with a capture handle.
        orch = Orchestrator.__new__(Orchestrator)
        orch.workflow = _stub_workflow(issues_dir)
        orch._progress_context = _stub_progress_context()
        orch.asciicast_capture = capture
        orch_holder["orch"] = orch

        async def sync_one(issue_spec: dict[str, str], index: int) -> str:
            """Run a real GitSyncService.sync; mark the dashboard entry."""
            agent_cfg, hook_cfg = _agent_hook_configs_for(index)
            issue_obj = Issue(
                id=issue_spec["id"],
                identifier=issue_spec["identifier"],
                title=issue_spec["title"],
                url=f"file://{issues_dir / (issue_spec['identifier'] + '.md')}",
            )
            workspace = await manager.create_for_issue(issue_obj)
            placeholder = await tracker.create_comment(
                issue_spec["id"],
                "## ClawCodex Run Summary\n\nRun in progress.",
            )
            assert placeholder is not None
            composite = orch._build_session_sink(issue_spec["id"])
            composite.on_phase_complete(PhaseComplete(phase=1, turn_count=1), None)

            _update_entry(
                synth_entries,
                issue_spec["id"],
                status=DASHBOARD_STATUS_IN_PROGRESS,
                progress_pct=0.5,
            )
            (workspace.path / "README.md").write_text(
                f"changes for {issue_spec['identifier']}\n", encoding="utf-8"
            )
            try:
                service = GitSyncService(
                    tracker, agent_config=agent_cfg, hooks_config=hook_cfg
                )
                run_id = f"repl-{issue_spec['identifier']}-{int(time.time())}"
                session = _Session(issue_obj, workspace, run_id, placeholder.id)
                reason = "exit_code=0"
                try:
                    await service.sync(session)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("sync raised for %s: %s", issue_spec["id"], exc)
                    reason = f"sync_error={exc.__class__.__name__}"
                composite.on_session_complete(SessionComplete(reason=reason), None)

                final_status = (
                    DASHBOARD_STATUS_COMPLETED
                    if reason == "exit_code=0"
                    else DASHBOARD_STATUS_FAILED
                )
                _update_entry(
                    synth_entries,
                    issue_spec["id"],
                    status=final_status,
                    progress_pct=1.0 if final_status == DASHBOARD_STATUS_COMPLETED else None,
                    detail=reason,
                )
                return reason
            except Exception as exc:  # noqa: BLE001
                logger.debug("sync_one outer error for %s: %s", issue_spec["id"], exc)
                return f"sync_error={exc.__class__.__name__}"

        async def tick_loop(stop_event: asyncio.Event, n_issues: int) -> int:
            """Simulate REPL ``/dashboard`` snapshots at ``frame_delay_s`` cadence.

            Each iteration emits the prompt markers + a *real* dashboard
            snapshot rendered through ``_format_snapshot`` (the same path
            the live ``/dashboard`` slash command uses) so the .cast
            content matches what a user would see in the interactive
            REPL.
            """
            tick = 0
            while not stop_event.is_set():
                _emit_repl_prompt_echo(capture, tick)
                _emit_dashboard_snapshot(capture, list(synth_entries), tick)
                tick += 1
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=frame_delay_s)
                except asyncio.TimeoutError:
                    continue
            return tick

        async def drive() -> tuple[int, list[str]]:
            stop_event = asyncio.Event()
            tick_task = asyncio.create_task(tick_loop(stop_event, len(issues)))
            sync_tasks = [
                asyncio.create_task(sync_one(spec, idx))
                for idx, spec in enumerate(issues)
            ]
            # Honour the duration deadline naturally.
            await asyncio.sleep(max(0.0, float(duration_s)))
            stop_event.set()
            await tick_task
            results = await asyncio.gather(*sync_tasks, return_exceptions=True)
            return (
                tick_task.result() if isinstance(tick_task.result(), int) else 0,
                [r if isinstance(r, str) else "sync_error" for r in results],
            )

        tick_count, results = await drive()

    finally:
        try:
            unregister_dashboard_source("orchestrator")
        except Exception:
            pass
        writer.close()

    errors = validate_cast(out_path)
    if errors:
        print(f"[repl-showcase] validation FAILED for {out_path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"[repl-showcase] {out_path} — {writer.frame_count} frame(s), "
        f"{tick_count} dashboard tick(s), "
        f"results={results}; validation: OK"
    )
    return 0


def _stub_workflow(issues_dir: Path) -> Any:
    from extensions.orchestrator.config.schema import WorkflowConfig

    return WorkflowConfig.from_dict(
        {
            "tracker": {"kind": "local", "issues_path": str(issues_dir)},
            "agent": {
                "max_concurrent_agents": 1,
                "phases": ["analysis", "design", "impl", "test", "review"],
            },
        }
    )


def _stub_progress_context() -> Any:
    try:
        from src.tool_system.context import ToolContext

        return ToolContext(workspace_root="/tmp")
    except Exception:
        return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repl-orchestrator-showcase",
        description=(
            "Record a real orchestrator batch + REPL /dashboard ticks into "
            "one asciicast v2 .cast — a developer's-eye view of the REPL "
            "monitoring an in-flight orchestrator run."
        ),
    )
    p.add_argument("--out", type=Path, default=Path("repl-showcase.cast"))
    p.add_argument(
        "--duration-s", type=float, default=12.0,
        help="Total wall-clock budget (default: %(default)s)",
    )
    p.add_argument(
        "--issue-count", type=int, default=3,
        help="Number of issues (1..3, default: %(default)s)",
    )
    p.add_argument(
        "--frame-delay-s", type=float, default=2.0,
        help="Seconds between simulated /dashboard submissions (default: %(default)s)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(
        run(
            args.out,
            duration_s=args.duration_s,
            issue_count=args.issue_count,
            frame_delay_s=args.frame_delay_s,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from src.deferred_init import DeferredPrefetchHandle, start_deferred_prefetches
from src.prefetch import (
    PrefetchResult,
    get_or_start_keychain_prefetch,
    get_or_start_mdm_raw_read,
    start_project_scan,
)


@dataclass(frozen=True)
class WorkspaceSetup:
    python_version: str
    implementation: str
    platform_name: str
    test_command: str = "python3 -m unittest discover -s tests -v"

    def startup_steps(self) -> tuple[str, ...]:
        return (
            "start top-level prefetch side effects",
            "build workspace context",
            "load mirrored command snapshot",
            "load mirrored tool snapshot",
            "prepare parity audit hooks",
            "apply trust-gated deferred init",
        )


@dataclass(frozen=True)
class SetupReport:
    setup: WorkspaceSetup
    prefetches: tuple[PrefetchResult, ...]
    deferred_init: DeferredPrefetchHandle
    trusted: bool
    cwd: Path

    def as_markdown(self) -> str:
        lines = [
            "# Setup Report",
            "",
            f"- Python: {self.setup.python_version} ({self.setup.implementation})",
            f"- Platform: {self.setup.platform_name}",
            f"- Trusted mode: {self.trusted}",
            f"- CWD: {self.cwd}",
            "",
            "Prefetches:",
            *(f"- {prefetch.name}: {prefetch.detail}" for prefetch in self.prefetches),
            "",
            "Deferred init:",
            f"- mode: {self.deferred_init.mode}",
            # These audit-only flags predate the concrete deferred-prefetch
            # handle.  Keep their report contract while the runtime uses the
            # current implementation above.
            f"- plugin_init={bool(self.trusted)}",
            f"- skill_init={bool(self.trusted)}",
            f"- mcp_prefetch={bool(self.trusted)}",
            f"- session_hooks={bool(self.trusted)}",
        ]
        return "\n".join(lines)


def build_workspace_setup() -> WorkspaceSetup:
    return WorkspaceSetup(
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        implementation=platform.python_implementation(),
        platform_name=platform.platform(),
    )


def run_setup(cwd: Path | None = None, trusted: bool = True) -> SetupReport:
    root = cwd or Path(__file__).resolve().parents[2]
    # WI-4.1: singleton getters. ``cli.py`` may have already fired these
    # at module import time; we reuse those handles instead of re-spawning.
    prefetches = [
        get_or_start_mdm_raw_read(),
        get_or_start_keychain_prefetch(),
        start_project_scan(root),
    ]
    return SetupReport(
        setup=build_workspace_setup(),
        prefetches=tuple(prefetches),
        deferred_init=start_deferred_prefetches(
            cwd=str(root),
            include_system_context=trusted,
        ),
        trusted=trusted,
        cwd=root,
    )

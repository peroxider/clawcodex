"""F-REC: ``clawcodex record`` CLI subcommand.

Standalone entry point that opens an asciicast v2 ``.cast`` file and
plumbs it into one or more subsystem adapters via the
:class:`RecordableSourceRegistry`. The CLI itself is intentionally
minimal — it does *not* try to drive the subsystems. Each registered
source is given the capture handle and is expected to wire itself into
whatever event stream that subsystem exposes (ProgressSink, cron
observers, HeadlessSessionOptions.on_event, DashboardSource, SOP
TeeWriter). Sources tick on their own clock; the CLI just keeps the
writer alive until either a duration elapses or the user hits Ctrl-C.

Layer rule (CLAUDE.md): this module lives under ``extensions/`` (Layer 2)
because it composes per-subsystem adapters that already live there. The
:class:`subcommand_registry` decorator makes the ``record`` subcommand
discoverable without hard-coding an import in ``clawcodex_ext/cli/``;
the registry only needs to import this module for the decorator to
fire.

Usage::

    clawcodex record --sources visualizer,cron --out demo.cast --duration 30s
    clawcodex record --sources orchestrator --out run.cast
    clawcodex record --list-sources
"""

from __future__ import annotations

import argparse
import re
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Sequence

from clawcodex_ext.cli.subcommand_registry import register

from extensions.capabilities.recorder import (
    AsciicastCapture,
    AsciicastHeader,
    RecordableSource,
)
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.config import RecordingConfig
from extensions.recording.registry import (
    get_default_registry,
    reset_default_registry,
)
from extensions.recording.validate_cast import validate_cast

__all__ = ["build_record_parser", "run_record_command"]

# `_factories` is imported lazily so that simply running ``clawcodex
# record`` populates the default registry with the well-known source
# factories (orchestrator, sop, visualizer, cron, query).
_FACTORIES_LOADED = False


def _ensure_factories_loaded() -> None:
    """Populate the default registry with built-in source factories.

    Idempotent. Importing :mod:`extensions.recording._factories` is
    what registers the built-in ``orchestrator``, ``sop``,
    ``visualizer``, ``cron``, and ``query`` source factories — but
    only if the parent :mod:`extensions.recording` package was loaded
    in the first place. Tests that build a private registry should
    call :func:`reset_default_registry` first.
    """
    global _FACTORIES_LOADED
    if _FACTORIES_LOADED:
        return
    _FACTORIES_LOADED = True
    # Importing this side-effect module triggers the
    # ``register_source(...)`` calls at module load.
    from extensions.recording import _factories  # noqa: F401


# ---------------------------------------------------------------------------
# Duration parser
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.IGNORECASE)
_DURATION_UNITS = {
    "": 1,
    "s": 1,
    "m": 60,
    "h": 3600,
}


def parse_duration(value: str) -> float:
    """Parse a human duration (``"30s"`` / ``"5m"`` / ``"1h"`` / ``"0"``).

    Returns the number of seconds. ``"0"`` or empty string means *no
    duration limit* — the CLI then runs until SIGINT.
    """
    if value is None:
        return 0.0
    raw = str(value).strip()
    if not raw or raw == "0":
        return 0.0
    match = _DURATION_RE.match(raw)
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid duration {value!r}; expected e.g. 30s, 5m, 1h, 0"
        )
    n = float(match.group(1))
    unit = match.group(2).lower()
    return n * _DURATION_UNITS[unit]


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def build_record_parser() -> argparse.ArgumentParser:
    """Build the argument parser for ``clawcodex record``."""
    p = argparse.ArgumentParser(
        prog="clawcodex record",
        description=(
            "Record one or more ClawCodex subsystems into an asciicast "
            "v2 .cast file. Runs until --duration elapses or Ctrl-C."
        ),
    )
    p.add_argument(
        "--sources",
        type=str,
        default=None,
        help=(
            "Comma-separated list of source IDs to record "
            "(e.g. orchestrator,sop,visualizer,cron,query). "
            "Defaults to all registered sources when omitted."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output .cast file path. Required unless --list-sources is set.",
    )
    p.add_argument(
        "--duration",
        type=parse_duration,
        default=0.0,
        help=(
            "Auto-stop after N seconds. Accepts suffixes: 30s, 5m, 1h. "
            "0 or empty runs until Ctrl-C. Default: 0."
        ),
    )
    p.add_argument(
        "--width",
        type=int,
        default=120,
        help="Terminal width recorded in the .cast header (default: 120).",
    )
    p.add_argument(
        "--height",
        type=int,
        default=36,
        help="Terminal height recorded in the .cast header (default: 36).",
    )
    p.add_argument(
        "--title",
        type=str,
        default=None,
        help="Optional title written to the .cast header.",
    )
    p.add_argument(
        "--reset-registry",
        action="store_true",
        help=(
            "Drop the default source registry before recording. Test-only "
            "escape hatch; production runs should leave the registry alone."
        ),
    )
    p.add_argument(
        "--list-sources",
        action="store_true",
        help="Print registered source IDs and exit.",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help=(
            "After recording, run the self-contained validator on the "
            "output file and print any errors."
        ),
    )
    return p


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _resolve_sources(
    spec: str | None,
    registry_names: Sequence[str],
) -> list[str]:
    """Resolve the ``--sources`` string into a concrete list of IDs.

    ``None`` means *use all registered sources*. Empty string is an
    explicit user choice of *no sources* (we let it through so
    ``--list-sources`` style smoke checks stay deterministic).

    Unknown IDs are preserved in the output (in user-supplied order)
    so the caller can emit a precise ``unknown source(s): ...`` error
    rather than silently dropping the user's typo.
    """
    if spec is None:
        return list(registry_names)
    parts = [s.strip().lower() for s in spec.split(",")]
    parts = [s for s in parts if s]
    if not parts:
        return []
    # Preserve user order, deduplicate. ``registered`` is kept in
    # registry order for cases where the user passed ``None`` so the
    # .cast header ``command`` field stays predictable across runs.
    seen: set[str] = set()
    deduped: list[str] = []
    for name in parts:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


def _install_sigint_handler(stop_event: threading.Event) -> None:
    """Wire SIGINT into ``stop_event`` so the main loop can break out."""
    previous = signal.getsignal(signal.SIGINT)

    def _handler(signum: int, frame: object) -> None:  # noqa: ARG001
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        # SIGINT is unavailable on Windows / non-main threads; the
        # duration timer still gets us out cleanly.
        pass
    stop_event._previous_sigint = previous  # type: ignore[attr-defined]


def _restore_sigint_handler(stop_event: threading.Event) -> None:
    previous = getattr(stop_event, "_previous_sigint", None)
    if previous is None:
        return
    try:
        signal.signal(signal.SIGINT, previous)
    except (ValueError, OSError):
        pass


def run_record_command(args: list[str] | None = None) -> int:
    """Entry point invoked by ``subcommand_registry``."""
    parser = build_record_parser()
    parsed = parser.parse_args(args)

    if parsed.reset_registry:
        reset_default_registry()
    _ensure_factories_loaded()

    registry = get_default_registry()
    available = registry.names()

    if parsed.list_sources:
        print("registered sources:")
        if not available:
            print("  (none)")
        else:
            for name in available:
                print(f"  - {name}")
        return 0

    if parsed.out is None:
        parser.error("--out is required (or pass --list-sources)")

    out_path = Path(parsed.out).expanduser().resolve()
    sources = _resolve_sources(parsed.sources, available)

    if not sources:
        print(
            "error: no sources selected. Use --sources or --list-sources.",
            file=sys.stderr,
        )
        return 2

    unknown = [s for s in sources if not registry.has(s)]
    if unknown:
        print(
            f"error: unknown source(s): {', '.join(unknown)}. "
            f"Available: {', '.join(available) or '(none)'}",
            file=sys.stderr,
        )
        return 2

    if parsed.width <= 0 or parsed.height <= 0:
        parser.error("--width and --height must be positive integers")

    header = AsciicastHeader(
        width=parsed.width,
        height=parsed.height,
        timestamp=int(time.time()),
        command=f"clawcodex record --sources {','.join(sources)}",
        title=parsed.title,
    )

    writer = AsciicastWriter(out_path, header)
    capture = writer.open()

    opened: list[tuple[str, RecordableSource]] = []
    failures: list[tuple[str, BaseException]] = []
    for source_id in sources:
        factory = registry.get(source_id)
        assert factory is not None
        try:
            source = factory(capture)
        except Exception as exc:  # pragma: no cover - adapter failure
            failures.append((source_id, exc))
            continue
        try:
            source.open(capture)
        except Exception as exc:  # pragma: no cover - adapter failure
            failures.append((source_id, exc))
            try:
                source.close()
            except Exception:
                pass
            continue
        opened.append((source_id, source))

    if not opened:
        writer.close()
        print(
            "error: no source could be opened. "
            + "; ".join(f"{name}: {exc}" for name, exc in failures),
            file=sys.stderr,
        )
        return 1

    stop_event = threading.Event()
    deadline = time.monotonic() + parsed.duration if parsed.duration > 0 else None
    _install_sigint_handler(stop_event)

    print(
        f"[record] writing {out_path} ({len(opened)} source(s): "
        f"{', '.join(name for name, _ in opened)})",
        file=sys.stderr,
    )
    if deadline is not None:
        print(
            f"[record] auto-stop in {parsed.duration:.1f}s (Ctrl-C to end early)",
            file=sys.stderr,
        )

    try:
        while not stop_event.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            # Sources tick on their own clock — the CLI is just the
            # lifetime owner of the writer. Sleep is short so Ctrl-C
            # latency stays low.
            stop_event.wait(timeout=0.25)
    finally:
        for _source_id, source in reversed(opened):
            try:
                source.close()
            except Exception:
                # Cleanup must not raise; one misbehaving adapter
                # should not stop the others from unwinding.
                pass
        writer.close()
        _restore_sigint_handler(stop_event)

    if failures:
        for name, exc in failures:
            print(f"[record] source {name!r} failed: {exc}", file=sys.stderr)

    print(
        f"[record] done — {writer.frame_count} frame(s) written to {out_path}",
        file=sys.stderr,
    )

    if parsed.validate:
        errors = validate_cast(out_path)
        if errors:
            print(f"[record] validation errors:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print("[record] validation: OK", file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# subcommand_registry hook
# ---------------------------------------------------------------------------


@register("record")
def _record_subcommand(args: list[str]) -> int:
    """``clawcodex record ...`` handler registered with ``subcommand_registry``."""
    return run_record_command(args)


# Re-export the default config so callers building custom CLIs (tests,
# docs examples) can read the knob set without instantiating RecordingConfig.
DEFAULT_CONFIG = RecordingConfig()
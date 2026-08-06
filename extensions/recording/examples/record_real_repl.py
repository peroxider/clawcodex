"""Example: record the real interactive REPL and convert to MP4.

This script demonstrates full-PTY capture mode end-to-end:

1. Fork ``clawcodex-dev`` into a pseudo-terminal.
2. Wait for the splash screen, type ``/dashboard`` and ``/quit``.
3. Convert the resulting ``.cast`` to an MP4 that renders ANSI escape
   sequences so the output looks like the reference screenshot.

Run from the repo root::

    python3 -m extensions.recording.examples.record_real_repl \
        --out /tmp/repl-demo.mp4

Requirements:

* ffmpeg (for MP4 encoding)
* Pillow (PNG rendering)
* pyte (ANSI terminal emulation for cast→mp4)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record the real ClawCodex REPL and convert to MP4."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/repl-demo.mp4"),
        help="Output MP4 path (default: /tmp/repl-demo.mp4)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=120,
        help="Terminal width in columns (default: 120)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=36,
        help="Terminal height in rows (default: 36)",
    )
    parser.add_argument(
        "--input-delay-s",
        type=float,
        default=10.0,
        help="Seconds to wait for the REPL splash before typing (default: 10)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=2,
        help="MP4 frame rate (default: 2)",
    )
    args = parser.parse_args()

    cast_path = args.out.with_suffix(".cast")

    env = os.environ.copy()
    env["CLAWCODEX_DISABLE_TELEMETRY"] = "1"
    env.setdefault("ANTHROPIC_API_KEY", "")
    env.setdefault("OPENAI_API_KEY", "")

    from extensions.recording.pty_recorder import run_pty_recording

    print(f"[record-real-repl] PTY recording → {cast_path}", file=sys.stderr)
    rc = run_pty_recording(
        cmd=["clawcodex-dev"],
        out_path=cast_path,
        width=args.width,
        height=args.height,
        title="Real ClawCodex REPL",
        input_script=b"/dashboard\n/quit\n",
        capture_input=True,
        input_delay_s=args.input_delay_s,
        env=env,
    )
    if rc != 0:
        print(f"[record-real-repl] REPL exited with rc={rc}", file=sys.stderr)
        return rc

    from extensions.recording.tools.cast_to_mp4 import convert_cast_to_mp4

    print(f"[record-real-repl] converting → {args.out}", file=sys.stderr)
    convert_cast_to_mp4(
        cast_path,
        args.out,
        fps=args.fps,
        width_px=1440,
        height_px=540,
    )

    print(f"[record-real-repl] done: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
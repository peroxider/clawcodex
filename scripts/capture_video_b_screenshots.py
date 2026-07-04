#!/usr/bin/env python3
"""
Capture chapter cover screenshots from assets/video-b/presentation/dist/index.html.

The single-file React SPA built by vite-plugin-singlefile is fully self-contained
(all JS/CSS inlined), so we can load it via ``file://`` without an HTTP server.

For each chapter we:
  1. Open the page (coldopen is the default cursor in localStorage).
  2. Wait for React mount + a short animation settle.
  3. For chapters 2/3/4 — press the numeric hotkey (``1``-``9`` jumps to that
     chapter's first step; wired in ``useStepper.ts``).
  4. Wait again for the chapter scene to settle, then ``page.screenshot``.

Why keyboard hotkeys instead of ``onJumpChapter`` via DOM querying:
  - The chapter jump controls live inside ``<ProgressBar>`` and are not
    tagged with ``data-testid`` / accessible names — keyboard shortcuts are
    the only stable, framework-agnostic trigger.
  - ``useStepper`` (L139-160) maps ``1``-``9`` to chapter index 0-8.

Usage::

    python scripts/capture_video_b_screenshots.py
    python scripts/capture_video_b_screenshots.py --out docs/showcase-screens
    python scripts/capture_video_b_screenshots.py --viewport 1600x900

Outputs (default):
    assets/video-b/screenshots/01-coldopen.png
    assets/video-b/screenshots/02-orchestrator.png
    assets/video-b/screenshots/03-sop-compiler.png
    assets/video-b/screenshots/04-install.png

Each image is full-viewport (the React app renders to ``#root`` at 100vw/100vh).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# Repo root: scripts/ is one level under clawcodex/.
REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "assets" / "video-b" / "presentation" / "dist" / "index.html"
DEFAULT_OUT = REPO_ROOT / "assets" / "video-b" / "screenshots"

CHAPTERS = [
    ("coldopen", 1),  # default cursor on a fresh localStorage
    ("orchestrator", 2),
    ("sop-compiler", 3),
    ("install", 4),
]

# Time spent waiting for React mount + first-paint before pressing a hotkey.
# Must accommodate Google Fonts CSS @import latency — see fonts.css.
INITIAL_SETTLE_MS = 5000
# Time spent waiting for a chapter switch to fully settle (scene fade-in
# transitions + AutoStartGate unmount). Tuned on a Linux x86_64 host; bump
# if any chapter looks half-rendered.
CHAPTER_SETTLE_MS = 2200


def parse_viewport(spec: str) -> dict[str, int]:
    try:
        w, h = spec.lower().split("x", 1)
        return {"width": int(w), "height": int(h)}
    except ValueError as exc:
        raise SystemExit(f"--viewport expects WxH (e.g. 1920x1080); got {spec!r}") from exc


def capture(out_dir: Path, viewport: dict[str, int]) -> list[Path]:
    if not HTML_PATH.is_file():
        raise SystemExit(
            f"SPA bundle not found: {HTML_PATH}\n"
            f"Build it first: cd assets/video-b/presentation && node scripts/build.cjs"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    file_url = HTML_PATH.resolve().as_uri()

    written: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport=viewport,
                device_scale_factor=1,  # 1x for README-friendly PNG sizes
                reduced_motion="reduce",  # minimize motion jitter between runs
            )
            # Wipe any persisted cursor from earlier runs.
            context.add_init_script(
                """
                try {
                    localStorage.removeItem('presentation-cursor-v4');
                } catch (e) {}
                """
            )
            page = context.new_page()
            console_errors: list[str] = []
            page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
            page.on(
                "console",
                lambda msg: (
                    console_errors.append(f"console.{msg.type}: {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            )

            page.goto(file_url, wait_until="domcontentloaded", timeout=15_000)
            # React mount signal: scene container appears in App.tsx (L57).
            page.wait_for_selector(".scene", timeout=10_000)
            # Web fonts (Noto Sans SC, Inter, JetBrains Mono …) are imported
            # from Google Fonts via fonts.css. Without explicit wait, CJK
            # glyphs render as tofu boxes. We block on document.fonts.ready
            # to guarantee the family list is resolved before painting.
            page.evaluate(
                "async () => { if (document.fonts && document.fonts.ready) "
                "{ await document.fonts.ready; } }"
            )
            page.wait_for_timeout(INITIAL_SETTLE_MS)

            for idx, (chapter_id, hotkey) in enumerate(CHAPTERS, start=1):
                if idx > 1:
                    page.keyboard.press(str(hotkey))
                    page.wait_for_timeout(CHAPTER_SETTLE_MS)

                target = out_dir / f"{idx:02d}-{chapter_id}.png"
                page.screenshot(path=str(target), full_page=False)
                print(f"  wrote {target.relative_to(REPO_ROOT)}  ({target.stat().st_size} bytes)")
                written.append(target)

            if console_errors:
                print("⚠ browser reported errors:", file=sys.stderr)
                for err in console_errors[:8]:
                    print(f"   {err}", file=sys.stderr)
        finally:
            browser.close()

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--viewport",
        default="1280x720",
        help="playwright viewport WxH (default 1280x720 — README-friendly)",
    )
    args = parser.parse_args()

    started = time.monotonic()
    viewport = parse_viewport(args.viewport)
    print(
        f"Capturing {len(CHAPTERS)} chapter screenshots "
        f"({viewport['width']}x{viewport['height']}) → {args.out}"
    )
    written = capture(args.out, viewport)
    elapsed = time.monotonic() - started
    print(f"Done: {len(written)} files in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

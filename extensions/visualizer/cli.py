"""``clawcodex viz`` CLI subcommand (F-94-A).

Usage::

    clawcodex viz                       # Start visualizer server (port 8765)
    clawcodex viz --port 9000           # Custom port
    clawcodex viz --allow-import        # Enable session import endpoint
    clawcodex viz --sessions-dir /path  # Custom sessions directory
    clawcodex viz --no-open             # Don't open browser
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)


def register_viz_subcommand() -> None:
    """Register the ``viz`` subcommand with the CLI registry."""
    from clawcodex_ext.cli.subcommand_registry import register

    @register("viz")
    def _viz_handler(args: list[str]) -> int:
        return run_viz(args)


def run_viz(args: list[str] | None = None) -> int:
    """Entry point for the ``clawcodex viz`` subcommand."""
    parser = argparse.ArgumentParser(
        prog="clawcodex viz",
        description="Start the Multi-Session Visualizer web server",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help="Path to sessions directory (default: ~/.clawcodex/sessions)",
    )
    parser.add_argument(
        "--workspaces-file",
        type=Path,
        default=None,
        help="Path to workspaces.json (default: ~/.clawcodex/workspaces.json)",
    )
    parser.add_argument(
        "--allow-import",
        action="store_true",
        default=False,
        help="Enable the session import endpoint (SSRF-protected)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        default=False,
        help="Don't open the browser automatically",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable uvicorn auto-reload (dev mode)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level",
    )

    parsed = parser.parse_args(args)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, parsed.log_level.upper()),
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
    )

    # Lazy import to avoid pulling in FastAPI on every CLI invocation
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is required for the visualizer. "
            "Install it with: pip install uvicorn[standard]",
            file=sys.stderr,
        )
        return 1

    from .server import create_app

    app = create_app(
        sessions_dir=parsed.sessions_dir,
        workspaces_file=parsed.workspaces_file,
        allow_import=parsed.allow_import,
        host=parsed.host,
        port=parsed.port,
    )

    url = f"http://localhost:{parsed.port}"

    if not parsed.no_open:
        # Open browser after a short delay
        import threading

        def _open_browser() -> None:
            import time
            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    print(f"🖥  ClawCodex Visualizer starting at {url}")
    print(f"   Sessions dir: {parsed.sessions_dir or '~/.clawcodex/sessions'}")
    print(f"   Import: {'enabled' if parsed.allow_import else 'disabled'}")
    print(f"   Press Ctrl+C to stop\n")

    try:
        uvicorn.run(
            app,
            host=parsed.host,
            port=parsed.port,
            log_level=parsed.log_level,
            reload=parsed.reload,
        )
    except KeyboardInterrupt:
        print("\nVisualizer stopped.")
    except Exception as e:
        print(f"Error starting visualizer: {e}", file=sys.stderr)
        return 1

    return 0

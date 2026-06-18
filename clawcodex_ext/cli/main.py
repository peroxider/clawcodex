"""Downstream CLI entrypoint."""

from __future__ import annotations

import sys


def main():
    """Delegate to the downstream CLI dispatch.

    Triggers the lazy ``ensure_nested_transcript_initialized()`` from
    ``clawcodex_ext.__init__`` so the nested-session transcript path
    resolver is registered before any code that writes transcripts
    runs. See that function's docstring for the circular-import
    reason this lives here, not in the package ``__init__``.
    """
    from clawcodex_ext import ensure_nested_transcript_initialized

    ensure_nested_transcript_initialized()
    from clawcodex_ext.cli.dispatch import run_cli

    return run_cli()


if __name__ == "__main__":
    sys.exit(main())

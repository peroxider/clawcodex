"""CLI entrypoint discovery helpers for generated workflow bridges."""

from __future__ import annotations

import shlex
from pathlib import Path


def split_cli_prefix(cli_prefix: str | None) -> list[str]:
    """Split a configured CLI prefix into argv tokens."""

    if not cli_prefix:
        return []
    return shlex.split(cli_prefix)


def discover_cli_prefix(
    source_dir: Path,
    project_name: str,
    *,
    override: str | None = None,
) -> str | None:
    """Return a CLI prefix override when one is explicitly configured.

    The bridge generator falls back to executing the source file directly
    when this returns ``None``.
    """

    if override and override.strip():
        return override.strip()
    return None

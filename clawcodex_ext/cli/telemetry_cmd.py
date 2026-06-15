"""Fast-path telemetry CLI command."""

from __future__ import annotations

from clawcodex_ext.cli.subcommand_registry import register


@register("telemetry")
def run_telemetry_command(args: list[str]) -> int:
    from clawcodex.telemetry.cli import main

    return main(args)

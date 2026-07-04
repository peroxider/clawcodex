"""Bash call handler — executes whitelisted shell commands safely."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any

_DEFAULT_TIMEOUT_SEC = 300.0


class BashCallError(Exception):
    """Raised when a bash command fails or times out."""

    pass


def resolve_agent_tool_bash_timeout_sec() -> float:
    """Return subprocess timeout for agent-tool bash handlers.

    ``AGENT_TOOL_BASH_TIMEOUT_SEC`` overrides the default (300s).
    """
    raw = os.environ.get("AGENT_TOOL_BASH_TIMEOUT_SEC", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return _DEFAULT_TIMEOUT_SEC


def execute_bash(
    command_template: str,
    params: dict[str, Any],
    *,
    timeout_sec: float | None = None,
) -> str:
    """Execute a bash command from a validated template.

    Args:
        command_template: A format-string command, e.g. ``"glab project view {project_id}"``.
        params: Mapping of placeholder names to resolved values.

    Returns:
        stdout from the subprocess.

    Raises:
        BashCallError: If the command exits non-zero or exceeds the timeout.
    """
    try:
        command = command_template.format(**params)
    except KeyError as exc:
        raise BashCallError(f"Missing parameter in template: {exc}") from exc
    except Exception as exc:
        raise BashCallError(f"Failed to format command template: {exc}") from exc

    if timeout_sec is None:
        timeout_sec = resolve_agent_tool_bash_timeout_sec()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise BashCallError(
            f"Command timed out after {int(timeout_sec)}s: {command[:80]}"
        ) from exc
    except OSError as exc:
        raise BashCallError(f"Failed to execute: {exc}") from exc

    if result.returncode != 0:
        raise BashCallError(
            f"Command exited with {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )

    return result.stdout


def parse_sop_wrapper_stdout(raw: str) -> Any:
    """Extract the JSON payload printed by a sop-converter wrapper script.

    Wrapper subprocesses may emit SDK init logs on stdout before the final
    ``json.dumps(...)`` line.  Walk lines bottom-up and return the last line
    that parses as JSON; fall back to the trimmed raw text when none match.
    """
    text = raw.strip()
    if not text:
        return text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    return text

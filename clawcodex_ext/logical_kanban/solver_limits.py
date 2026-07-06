"""Resource limits for external solver processes (F-139).

External solver adapters must run inside bounded time, memory, and output
budgets.  This module provides a portable helper that subprocess-based
adapters can use; when a limit is breached the process is killed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SolverResourceLimits:
    """Bounds for a single external solver invocation."""

    timeout_seconds: float = 30.0
    max_memory_mb: int = 512
    max_output_bytes: int = 10 * 1024 * 1024  # 10 MiB


class SolverLimitError(Exception):
    """Raised when a solver process violates a resource limit."""

    def __init__(self, reason: str, limit: str) -> None:
        super().__init__(f"Solver {reason}: {limit}")
        self.reason = reason
        self.limit = limit


def _set_memory_limit(max_memory_mb: int) -> None:
    """Preexec helper: set the address-space limit for the child process."""
    try:
        import resource

        # RLIMIT_AS is the maximum virtual-memory size in bytes.
        limit_bytes = max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ImportError, AttributeError, OSError):
        # Platforms without the resource module (e.g. Windows) or without
        # RLIMIT_AS (e.g. WSL) silently skip.
        pass


def _kill_process_group(proc: subprocess.Popen[Any]) -> None:
    """Best-effort kill of the process group spawned by the solver."""
    try:
        if os.name != 'nt':
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_external_solver(
    command: list[str],
    *,
    input_text: str = '',
    limits: SolverResourceLimits | None = None,
) -> tuple[int, str, str]:
    """Run ``command`` as an external solver with enforced resource limits.

    Parameters
    ----------
    command:
        Argument vector for the subprocess.  The caller is responsible for
        making sure the executable path and any arguments are trusted.
    input_text:
        Data to write to the solver's stdin.  Must already be encoded/escaped
        by the caller; this helper does not sanitize content.
    limits:
        Resource bounds.  Defaults to ``SolverResourceLimits()``.

    Returns
    -------
    ``(returncode, stdout, stderr)``.

    Raises
    ------
    SolverLimitError:
        If the process exceeds the timeout, memory limit, or output-size limit.
    """
    if limits is None:
        limits = SolverResourceLimits()

    start = time.perf_counter()
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=(lambda: _set_memory_limit(limits.max_memory_mb)) if os.name != 'nt' else None,
        start_new_session=True,
    )

    limit_exceeded = threading.Event()
    limit_reason: list[str] = []

    try:
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def _reader(stream, parts, limit_bytes, label):  # type: ignore[no-untyped-def]
            """Read from a stream until EOF or the per-stream byte limit."""
            total = 0
            while True:
                try:
                    chunk = stream.read(4096)
                except Exception:
                    break
                if not chunk:
                    break
                encoded_chunk = chunk.encode('utf-8', errors='replace')
                total += len(encoded_chunk)
                if total > limit_bytes:
                    parts.append(f"\n[{label} truncated after {limit_bytes} bytes]\n")
                    limit_reason.append('output_limit')
                    limit_exceeded.set()
                    # Drain the rest so the process can exit without filling the pipe.
                    try:
                        while stream.read(4096):
                            pass
                    except Exception:
                        pass
                    break
                parts.append(chunk)

        stdout_thread = threading.Thread(
            target=_reader,
            args=(proc.stdout, stdout_parts, limits.max_output_bytes, 'stdout'),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_reader,
            args=(proc.stderr, stderr_parts, limits.max_output_bytes, 'stderr'),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            if input_text:
                proc.stdin.write(input_text)
            proc.stdin.close()
        except Exception:
            pass

        try:
            returncode = proc.wait(timeout=limits.timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            try:
                returncode = proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                returncode = -1
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            raise SolverLimitError('timeout', f'{limits.timeout_seconds}s')

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

        stdout = ''.join(stdout_parts)
        stderr = ''.join(stderr_parts)

        if limit_exceeded.is_set():
            _kill_process_group(proc)
            reason = limit_reason[0] if limit_reason else 'output_limit'
            raise SolverLimitError(reason, f'{limits.max_output_bytes} bytes')

        elapsed = time.perf_counter() - start
        if elapsed > limits.timeout_seconds:
            raise SolverLimitError('timeout', f'{limits.timeout_seconds}s')

        return returncode, stdout, stderr
    except SolverLimitError:
        _kill_process_group(proc)
        raise
    except Exception as exc:
        _kill_process_group(proc)
        raise SolverLimitError('error', str(exc)) from exc


__all__ = [
    'SolverLimitError',
    'SolverResourceLimits',
    'run_external_solver',
]

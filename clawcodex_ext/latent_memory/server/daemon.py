"""Lifecycle management for the bundled ClawCodex memory service."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from clawcodex_ext.latent_memory.environment import (
    load_memory_server_environment as load_memory_environment,
)


@dataclass(frozen=True)
class MemoryServerPaths:
    state_dir: Path
    pid_file: Path
    log_file: Path
    qdrant_path: Path
    history_db: Path
    mem0_dir: Path
    crystallize_state: Path
    crystallize_audit: Path
    solidification_db: Path
    crystal_docs: Path

    @classmethod
    def for_state_dir(cls, state_dir: str | Path | None = None) -> "MemoryServerPaths":
        if state_dir is None:
            state_dir = os.getenv("CLAWCODEX_MEMORY_STATE_DIR") or None
        if state_dir is None:
            config_root = Path(
                os.getenv("CLAWCODEX_CONFIG_DIR", str(Path.home() / ".clawcodex"))
            ).expanduser()
            state_path = config_root / "memory"
        else:
            state_path = Path(state_dir).expanduser()
        state_path = state_path.resolve()
        return cls(
            state_dir=state_path,
            pid_file=state_path / "server.pid",
            log_file=state_path / "server.log",
            qdrant_path=state_path / "qdrant",
            history_db=state_path / "history.db",
            mem0_dir=state_path / ".mem0",
            crystallize_state=state_path / "crystallize_state.json",
            crystallize_audit=state_path / "crystallize_audit.jsonl",
            solidification_db=state_path / "solidification.db",
            crystal_docs=state_path / "crystal_docs",
        )

    def ensure_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.mem0_dir.mkdir(parents=True, exist_ok=True)


def apply_runtime_defaults(
    paths: MemoryServerPaths,
    environ: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    target = os.environ if environ is None else environ
    target.setdefault("CLAWCODEX_MEMORY_STATE_DIR", str(paths.state_dir))
    target.setdefault("HISTORY_DB_PATH", str(paths.history_db))
    target.setdefault("MEM0_DIR", str(paths.mem0_dir))
    target.setdefault("MEM0_TELEMETRY", "False")
    if not target.get("QDRANT_HOST") and not target.get("QDRANT_URL"):
        target.setdefault("QDRANT_PATH", str(paths.qdrant_path))
    target.setdefault("CRYSTALLIZE_STATE_PATH", str(paths.crystallize_state))
    target.setdefault("CRYSTALLIZE_AUDIT_PATH", str(paths.crystallize_audit))
    target.setdefault("SOLIDIFY_DB_PATH", str(paths.solidification_db))
    target.setdefault("SOLIDIFY_DOC_REPO_PATH", str(paths.crystal_docs))
    target.setdefault("SALIENCE_GATE_OLLAMA_MODEL", "none")
    target.setdefault("MEMORY_SERVER_HOST", "127.0.0.1")
    target.setdefault("MEMORY_SERVER_PORT", "8888")
    host = _health_host(target["MEMORY_SERVER_HOST"])
    target.setdefault("MEM0_HOST", f"http://{host}:{target['MEMORY_SERVER_PORT']}")
    return target


def check_runtime_requirements(environ: Mapping[str, str] | None = None) -> str | None:
    target = os.environ if environ is None else environ
    missing = [name for name in ("mem0", "qdrant_client") if importlib.util.find_spec(name) is None]
    if missing:
        return (
            f"missing optional memory dependencies: {', '.join(missing)}; "
            "run `uv sync --extra memory`"
        )
    config_path = target.get("MEM0_CONFIG_PATH", "").strip()
    if config_path:
        if not Path(config_path).expanduser().is_file():
            return f"MEM0_CONFIG_PATH does not exist: {config_path}"
        return None
    providers = {
        target.get("LLM_PROVIDER", "openai").strip().lower(),
        target.get("EMBEDDER_PROVIDER", "openai").strip().lower(),
    }
    if "openai" in providers and not target.get("OPENAI_API_KEY"):
        return (
            "OPENAI_API_KEY is required by the default memory LLM/embedder; "
            "set it, choose Ollama providers, or provide MEM0_CONFIG_PATH"
        )
    return None


def memory_server_address(environ: Mapping[str, str] | None = None) -> tuple[str, int]:
    target = os.environ if environ is None else environ
    host = target.get("MEMORY_SERVER_HOST", "127.0.0.1")
    try:
        port = int(target.get("MEMORY_SERVER_PORT", "8888"))
    except ValueError as exc:
        raise ValueError("MEMORY_SERVER_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("MEMORY_SERVER_PORT must be between 1 and 65535")
    return host, port


def memory_server_url(environ: Mapping[str, str] | None = None) -> str:
    host, port = memory_server_address(environ)
    return f"http://{_health_host(host)}:{port}"


def read_health(
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = 1.0,
) -> dict[str, Any] | None:
    request = urllib.request.Request(f"{memory_server_url(environ)}/health")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if isinstance(payload, dict) and payload.get("status") == "ok":
        return payload
    return None


def port_is_open(host: str, port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((_health_host(host), port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid(paths: MemoryServerPaths) -> int | None:
    try:
        value = int(paths.pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    On Windows, os.kill(pid, 0) can raise OSError/WinError for various
    reasons unrelated to process existence. Use ctypes for reliability.
    """
    import sys

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        process = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
        if process == 0:
            return False
        kernel32.CloseHandle(process)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _health_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host


class MemoryServerDaemon:
    def __init__(self, paths: MemoryServerPaths):
        self.paths = paths

    def start(self, *, env_file: str | Path | None = None, timeout: float = 60.0) -> int:
        try:
            load_memory_environment(env_file, state_dir=self.paths.state_dir)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        apply_runtime_defaults(self.paths)
        self.paths.ensure_directories()
        health = read_health(timeout=1.5)
        if health is not None:
            pid = read_pid(self.paths)
            suffix = f" (pid {pid})" if pid and is_pid_alive(pid) else ""
            print(f"Memory server is already running at {memory_server_url()}{suffix}")
            return 0
        requirement_error = check_runtime_requirements()
        if requirement_error:
            print(f"error: {requirement_error}", file=sys.stderr)
            return 2
        host, port = memory_server_address()
        if port_is_open(host, port):
            print(
                f"error: {host}:{port} is in use but is not a healthy memory server",
                file=sys.stderr,
            )
            return 1
        existing_pid = read_pid(self.paths)
        if existing_pid and is_pid_alive(existing_pid):
            print(
                f"error: memory server pid {existing_pid} is alive but health check failed; "
                f"see {self.paths.log_file}",
                file=sys.stderr,
            )
            return 1
        self._cleanup_pid()
        command = [
            sys.executable,
            "-m",
            "clawcodex_ext.latent_memory.server.daemon",
            "serve",
            "--state-dir",
            str(self.paths.state_dir),
        ]
        process_options: dict[str, Any] = {
            "cwd": str(Path.cwd()),
            "env": dict(os.environ),
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            process_options["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            process_options["start_new_session"] = True
        with self.paths.log_file.open("ab", buffering=0) as log_handle:
            process_options["stdout"] = log_handle
            process_options["stderr"] = subprocess.STDOUT
            process = subprocess.Popen(command, **process_options)
        self.paths.pid_file.write_text(str(process.pid), encoding="utf-8")
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._cleanup_pid()
                print(
                    f"error: memory server exited with code {process.returncode}; "
                    f"see {self.paths.log_file}",
                    file=sys.stderr,
                )
                return 1
            if read_health(timeout=1.0) is not None:
                print(f"Memory server started at {memory_server_url()} (pid {process.pid})")
                print(f"Data: {self.paths.state_dir}")
                print(f"Log:  {self.paths.log_file}")
                return 0
            time.sleep(0.25)
        print(
            f"error: memory server did not become healthy within {timeout:g}s; "
            f"see {self.paths.log_file}",
            file=sys.stderr,
        )
        try:
            process.terminate()
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
        except OSError:
            pass
        self._cleanup_pid()
        return 1

    def stop(self, *, timeout: float = 10.0) -> int:
        apply_runtime_defaults(self.paths)
        pid = read_pid(self.paths)
        if pid is None or not is_pid_alive(pid):
            self._cleanup_pid()
            if read_health(timeout=0.5) is not None:
                print(
                    "Memory server is healthy but is not managed by this state directory; "
                    "leave it running or stop it manually."
                )
                return 1
            print("Memory server is already stopped.")
            return 0
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._cleanup_pid()
            print("Memory server is already stopped.")
            return 0
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline and is_pid_alive(pid):
            time.sleep(0.1)
        if is_pid_alive(pid):
            kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, kill_signal)
        self._cleanup_pid()
        print("Memory server stopped.")
        return 0

    def restart(
        self,
        *,
        env_file: str | Path | None = None,
        timeout: float = 60.0,
    ) -> int:
        stop_result = self.stop()
        if stop_result != 0:
            return stop_result
        return self.start(env_file=env_file, timeout=timeout)

    def status(self) -> int:
        apply_runtime_defaults(self.paths)
        health = read_health(timeout=1.5)
        pid = read_pid(self.paths)
        if health is None:
            if pid and not is_pid_alive(pid):
                self._cleanup_pid()
                pid = None
            suffix = f"; pid {pid} exists but health check failed" if pid else ""
            print(f"Memory server: stopped{suffix}")
            print(f"Expected URL: {memory_server_url()}")
            print(f"Log: {self.paths.log_file}")
            return 1
        pid_text = str(pid) if pid and is_pid_alive(pid) else "external"
        print(f"Memory server: running (pid {pid_text})")
        print(f"URL: {memory_server_url()}")
        print(f"Backend: llm={health.get('llm', '?')} embedder={health.get('embedder', '?')}")
        print(f"Data: {self.paths.state_dir}")
        return 0

    def logs(self, *, lines: int = 200, follow: bool = False) -> int:
        if not self.paths.log_file.is_file():
            print(f"No memory server log found at {self.paths.log_file}", file=sys.stderr)
            return 1
        lines = max(1, lines)
        content = self.paths.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in content[-lines:]:
            print(line)
        if not follow:
            return 0
        position = self.paths.log_file.stat().st_size
        try:
            while True:
                time.sleep(0.25)
                size = self.paths.log_file.stat().st_size
                if size < position:
                    position = 0
                if size == position:
                    continue
                with self.paths.log_file.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(position)
                    sys.stdout.write(handle.read())
                    sys.stdout.flush()
                    position = handle.tell()
        except KeyboardInterrupt:
            return 0

    def _cleanup_pid(self) -> None:
        try:
            self.paths.pid_file.unlink()
        except FileNotFoundError:
            pass


def serve_foreground(state_dir: str | Path | None = None) -> int:
    paths = MemoryServerPaths.for_state_dir(state_dir)
    apply_runtime_defaults(paths)
    paths.ensure_directories()
    requirement_error = check_runtime_requirements()
    if requirement_error:
        print(f"error: {requirement_error}", file=sys.stderr)
        return 2
    host, port = memory_server_address()
    paths.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        import uvicorn

        uvicorn.run(
            "clawcodex_ext.latent_memory.server.app:app",
            host=host,
            port=port,
            workers=1,
            log_level=os.getenv("CLAWCODEX_MEMORY_LOG_LEVEL", "info").lower(),
        )
    finally:
        if read_pid(paths) == os.getpid():
            try:
                paths.pid_file.unlink()
            except FileNotFoundError:
                pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clawcodex_ext.latent_memory.server.daemon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--state-dir")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve_foreground(args.state_dir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

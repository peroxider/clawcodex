from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawcodex_ext.latent_memory.server import config
from clawcodex_ext.latent_memory.server import daemon as daemon_module
from clawcodex_ext.latent_memory.environment import load_passive_memory_environment
from clawcodex_ext.latent_memory.server.daemon import (
    MemoryServerDaemon,
    MemoryServerPaths,
    apply_runtime_defaults,
    load_memory_environment,
)


MEMORY_ENV_NAMES = {
    "CLAWCODEX_CONFIG_DIR",
    "CLAWCODEX_MEMORY_ENV_FILE",
    "CLAWCODEX_MEMORY_STATE_DIR",
    "COLLECTION_NAME",
    "CRYSTALLIZE_AUDIT_PATH",
    "CRYSTALLIZE_STATE_PATH",
    "EMBEDDING_DIMS",
    "EMBEDDER_MODEL",
    "EMBEDDER_PROVIDER",
    "HISTORY_DB_PATH",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "MEM0_CONFIG_PATH",
    "MEM0_DIR",
    "MEM0_HOST",
    "MEMORY_SERVER_HOST",
    "MEMORY_SERVER_PORT",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OLLAMA_BASE_URL",
    "QDRANT_API_KEY",
    "QDRANT_HOST",
    "QDRANT_PATH",
    "QDRANT_PORT",
    "QDRANT_URL",
    "SALIENCE_GATE_OLLAMA_MODEL",
    "SOLIDIFY_DB_PATH",
    "SOLIDIFY_DOC_REPO_PATH",
}


@pytest.fixture(autouse=True)
def clean_memory_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in MEMORY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_default_vector_store_is_embedded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAWCODEX_MEMORY_STATE_DIR", str(tmp_path))

    result = config.build_vector_store_config({})

    assert result == {
        "provider": "qdrant",
        "config": {
            "collection_name": "memories",
            "path": str(tmp_path / "qdrant"),
            "on_disk": True,
        },
    }


def test_external_qdrant_host_overrides_embedded_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAWCODEX_MEMORY_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("QDRANT_HOST", "memory-qdrant.internal")
    monkeypatch.setenv("QDRANT_PORT", "7444")

    result = config.build_vector_store_config({})["config"]

    assert result["host"] == "memory-qdrant.internal"
    assert result["port"] == 7444
    assert "path" not in result


def test_external_qdrant_url_with_api_key_has_highest_runtime_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    monkeypatch.setenv("QDRANT_HOST", "ignored-host")

    result = config.build_vector_store_config({})["config"]

    assert result["url"] == "https://example.qdrant.io"
    assert result["api_key"] == "secret"
    assert "host" not in result


def test_external_qdrant_url_without_api_key_preserves_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io:7443/prefix")

    result = config.build_vector_store_config({})["config"]

    assert result["url"] == "https://example.qdrant.io:7443/prefix"
    assert "api_key" not in result
    assert "host" not in result


def test_environment_only_ollama_config_includes_url_and_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAWCODEX_MEMORY_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:1.5b")
    monkeypatch.setenv("EMBEDDER_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDER_MODEL", "snowflake-arctic-embed2:568m")
    monkeypatch.setenv("EMBEDDING_DIMS", "1024")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    result = config.load_config()

    assert result["llm"]["config"]["ollama_base_url"] == "http://127.0.0.1:11434"
    assert result["embedder"]["config"]["embedding_dims"] == 1024
    assert result["vector_store"]["config"]["embedding_model_dims"] == 1024


def test_config_file_vector_store_is_preserved(tmp_path: Path) -> None:
    config_file = tmp_path / "memory.yaml"
    config_file.write_text(
        """
version: v1.1
llm:
  provider: openai
  config:
    model: test-llm
embedder:
  provider: openai
  config:
    model: test-embedder
vector_store:
  provider: qdrant
  config:
    host: explicit-host
    port: 6333
    collection_name: explicit
""".strip(),
        encoding="utf-8",
    )

    result = config.load_config(config_file)

    assert result["vector_store"]["config"]["host"] == "explicit-host"
    assert result["vector_store"]["config"]["collection_name"] == "explicit"


def test_runtime_defaults_keep_all_state_under_one_directory(tmp_path: Path) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    environment: dict[str, str] = {}

    apply_runtime_defaults(paths, environment)

    assert environment["QDRANT_PATH"] == str(tmp_path / "qdrant")
    assert environment["HISTORY_DB_PATH"] == str(tmp_path / "history.db")
    assert environment["CRYSTALLIZE_STATE_PATH"] == str(tmp_path / "crystallize_state.json")
    assert environment["SOLIDIFY_DB_PATH"] == str(tmp_path / "solidification.db")
    assert environment["SALIENCE_GATE_OLLAMA_MODEL"] == "none"


def test_explicit_env_file_overrides_project_file_but_not_process_environment(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text(
        "MEMORY_SERVER_PORT=7001\nLLM_PROVIDER=project\n",
        encoding="utf-8",
    )
    explicit = tmp_path / "memory.env"
    explicit.write_text(
        "MEMORY_SERVER_PORT=7002\nLLM_PROVIDER=explicit\n",
        encoding="utf-8",
    )
    environment = {"LLM_PROVIDER": "process"}

    load_memory_environment(explicit, cwd=project, environ=environment)

    assert environment["MEMORY_SERVER_PORT"] == "7002"
    assert environment["LLM_PROVIDER"] == "process"


def test_default_state_memory_env_loads_without_cli_argument(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("LLM_MODEL=project-model\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "memory.env").write_text(
        "LLM_MODEL=memory-model\nCLAWCODEX_PASSIVE_MEMORY=1\n",
        encoding="utf-8",
    )
    environment = {"LLM_PROVIDER": "process-provider"}

    load_memory_environment(cwd=project, state_dir=state_dir, environ=environment)

    assert environment["LLM_PROVIDER"] == "process-provider"
    assert environment["LLM_MODEL"] == "memory-model"
    assert environment["CLAWCODEX_PASSIVE_MEMORY"] == "1"


def test_passive_loader_does_not_import_server_secrets(tmp_path: Path) -> None:
    state_dir = tmp_path / "memory"
    state_dir.mkdir()
    env_file = state_dir / "memory.env"
    env_file.write_text(
        "CLAWCODEX_PASSIVE_MEMORY=1\n"
        "CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID=test-user\n"
        "OPENAI_API_KEY=server-secret\n",
        encoding="utf-8",
    )
    environment = {
        "CLAWCODEX_MEMORY_STATE_DIR": str(state_dir),
        "CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID": "process-user",
    }

    loaded = load_passive_memory_environment(cwd=tmp_path, environ=environment)

    assert loaded == env_file
    assert environment["CLAWCODEX_PASSIVE_MEMORY"] == "1"
    assert environment["CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID"] == "process-user"
    assert "OPENAI_API_KEY" not in environment


def test_start_is_idempotent_when_health_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    daemon = MemoryServerDaemon(paths)
    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: {"status": "ok"})

    result = daemon.start()

    assert result == 0
    assert "already running" in capsys.readouterr().out


def test_start_reports_missing_optional_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    daemon = MemoryServerDaemon(paths)
    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: None)
    monkeypatch.setattr(
        daemon_module,
        "check_runtime_requirements",
        lambda: "missing optional memory dependencies: mem0; run `uv sync --extra memory`",
    )

    result = daemon.start()

    assert result == 2
    assert "uv sync --extra memory" in capsys.readouterr().err


def test_start_reports_port_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    daemon = MemoryServerDaemon(MemoryServerPaths.for_state_dir(tmp_path))
    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: None)
    monkeypatch.setattr(daemon_module, "check_runtime_requirements", lambda: None)
    monkeypatch.setattr(daemon_module, "port_is_open", lambda *args, **kwargs: True)

    result = daemon.start()

    assert result == 1
    assert "is in use" in capsys.readouterr().err


def test_start_spawns_current_python_and_waits_for_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    daemon = MemoryServerDaemon(paths)
    health_results = iter([None, {"status": "ok"}])
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 4321
        returncode = None

        @staticmethod
        def poll() -> None:
            return None

    def fake_popen(command: list[str], **options: object) -> FakeProcess:
        captured["command"] = command
        captured["options"] = options
        return FakeProcess()

    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: next(health_results))
    monkeypatch.setattr(daemon_module, "check_runtime_requirements", lambda: None)
    monkeypatch.setattr(daemon_module, "port_is_open", lambda *args, **kwargs: False)
    monkeypatch.setattr(daemon_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(daemon_module.time, "sleep", lambda seconds: None)

    result = daemon.start(timeout=2)

    assert result == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[0] == os.sys.executable
    assert command[1:4] == ["-m", "clawcodex_ext.latent_memory.server.daemon", "serve"]
    assert paths.pid_file.read_text(encoding="utf-8") == "4321"


def test_start_timeout_terminates_process_and_removes_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    daemon = MemoryServerDaemon(paths)

    class FakeProcess:
        pid = 4321
        returncode = None
        terminated = False

        @staticmethod
        def poll() -> None:
            return None

        def terminate(self) -> None:
            self.terminated = True

        @staticmethod
        def wait(timeout: float) -> int:
            return 0

    process = FakeProcess()
    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: None)
    monkeypatch.setattr(daemon_module, "check_runtime_requirements", lambda: None)
    monkeypatch.setattr(daemon_module, "port_is_open", lambda *args, **kwargs: False)
    monkeypatch.setattr(daemon_module.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(daemon_module.time, "monotonic", lambda: next(monotonic_values))

    result = daemon.start(timeout=0.1)

    assert result == 1
    assert process.terminated is True
    assert not paths.pid_file.exists()


def test_stop_removes_managed_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    paths.ensure_directories()
    paths.pid_file.write_text("1234", encoding="utf-8")
    daemon = MemoryServerDaemon(paths)
    alive_states = iter([True, False, False])
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_module, "is_pid_alive", lambda pid: next(alive_states))
    monkeypatch.setattr(daemon_module.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    result = daemon.stop(timeout=0.1)

    assert result == 0
    assert signals[0][0] == 1234
    assert not paths.pid_file.exists()


def test_restart_stops_before_starting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = MemoryServerDaemon(MemoryServerPaths.for_state_dir(tmp_path))
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        daemon,
        "stop",
        lambda **kwargs: calls.append(("stop", kwargs)) or 0,
    )
    monkeypatch.setattr(
        daemon,
        "start",
        lambda **kwargs: calls.append(("start", kwargs)) or 0,
    )

    result = daemon.restart(env_file="memory.env", timeout=12.0)

    assert result == 0
    assert calls == [
        ("stop", {}),
        ("start", {"env_file": "memory.env", "timeout": 12.0}),
    ]


def test_status_cleans_stale_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)
    paths.ensure_directories()
    paths.pid_file.write_text("9999", encoding="utf-8")
    daemon = MemoryServerDaemon(paths)
    monkeypatch.setattr(daemon_module, "read_health", lambda **kwargs: None)
    monkeypatch.setattr(daemon_module, "is_pid_alive", lambda pid: False)

    result = daemon.status()

    assert result == 1
    assert "stopped" in capsys.readouterr().out
    assert not paths.pid_file.exists()


def test_logs_reports_expected_log_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = MemoryServerPaths.for_state_dir(tmp_path)

    result = MemoryServerDaemon(paths).logs()

    assert result == 1
    assert str(paths.log_file) in capsys.readouterr().err


def test_memory_subcommand_is_registered() -> None:
    from clawcodex_ext.cli.subcommand_registry import get_subcommand

    assert get_subcommand("memory") is not None

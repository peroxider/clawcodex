from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


RecallScope = Literal["user", "agent", "run"]
DEFAULT_MEMORY_SERVER_NAME = "latent-memory"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class PassiveMemoryConfig:
    enabled: bool = False
    server_name: str = DEFAULT_MEMORY_SERVER_NAME
    human_id: str | None = None
    agent_id: str = "ccx:primary"
    recall_scope: RecallScope = "user"
    search_limit: int = 16
    inject_limit: int = 10
    minimum_score: float = 0.25
    score_margin: float = 0.4
    max_crystallized: int = 1
    inject_max_chars: int = 4000
    present_chronologically: bool = False
    include_observation_dates: bool = False
    search_timeout_ms: int = 5000
    capture_max_tokens: int = 8000
    write_queue_size: int = 32

    @classmethod
    def from_env(cls) -> "PassiveMemoryConfig":
        raw_scope = os.getenv("CLAWCODEX_PASSIVE_MEMORY_RECALL_SCOPE", "user").strip().lower()
        scope: RecallScope = raw_scope if raw_scope in {"user", "agent", "run"} else "user"  # type: ignore[assignment]
        server_name = (
            os.getenv("CLAWCODEX_PASSIVE_MEMORY_SERVER", DEFAULT_MEMORY_SERVER_NAME).strip()
            or DEFAULT_MEMORY_SERVER_NAME
        )
        return cls(
            enabled=_env_bool("CLAWCODEX_PASSIVE_MEMORY", False),
            server_name=server_name,
            human_id=(
                os.getenv("CLAWCODEX_PASSIVE_MEMORY_HUMAN_ID")
                or os.getenv("CLAWCODEX_PASSIVE_MEMORY_USER_ID")
                or None
            ),
            agent_id=os.getenv("CLAWCODEX_PASSIVE_MEMORY_AGENT_ID", "ccx:primary").strip()
            or "ccx:primary",
            recall_scope=scope,
            search_limit=_env_int("CLAWCODEX_PASSIVE_MEMORY_SEARCH_LIMIT", 16, 1, 50),
            inject_limit=_env_int("CLAWCODEX_PASSIVE_MEMORY_INJECT_LIMIT", 3, 1, 20),
            minimum_score=_env_float("CLAWCODEX_PASSIVE_MEMORY_MINIMUM_SCORE", 0.50, 0.0, 1.0),
            score_margin=_env_float("CLAWCODEX_PASSIVE_MEMORY_SCORE_MARGIN", 0.15, 0.0, 1.0),
            max_crystallized=_env_int("CLAWCODEX_PASSIVE_MEMORY_MAX_CRYSTALLIZED", 1, 0, 20),
            inject_max_chars=_env_int(
                "CLAWCODEX_PASSIVE_MEMORY_INJECT_MAX_CHARS", 4000, 500, 20000
            ),
            present_chronologically=_env_bool(
                "CLAWCODEX_PASSIVE_MEMORY_PRESENT_CHRONOLOGICALLY", False
            ),
            include_observation_dates=_env_bool(
                "CLAWCODEX_PASSIVE_MEMORY_INCLUDE_OBSERVATION_DATES", False
            ),
            search_timeout_ms=_env_int(
                "CLAWCODEX_PASSIVE_MEMORY_SEARCH_TIMEOUT_MS", 5000, 100, 30000
            ),
            capture_max_tokens=_env_int(
                "CLAWCODEX_PASSIVE_MEMORY_CAPTURE_MAX_TOKENS", 8000, 1000, 32000
            ),
            write_queue_size=_env_int("CLAWCODEX_PASSIVE_MEMORY_WRITE_QUEUE_SIZE", 32, 1, 256),
        )


__all__ = ["DEFAULT_MEMORY_SERVER_NAME", "PassiveMemoryConfig", "RecallScope"]

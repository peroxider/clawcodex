"""TelemetryConfig — the F-97 configuration surface.

The default is fully disabled; users opt in by writing a ``telemetry``
section into their merged config (see
``docs/FEATURE_PLAN.md`` §9.3 for the TOML shape — the JSON config
mirrors it field-for-field).

Environment variables override the on-disk config for the current
process only:

* ``CLAW_TELEMETRY_ENABLED=1``     — enable local collection
* ``CLAW_TELEMETRY_REPORTING_ENABLED=1`` — enable reporter emission
* ``CLAW_TELEMETRY_STORAGE_DIR``    — override the storage root
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .redaction import RedactionConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportingConfig:
    """Reporter configuration.

    ``kind`` selects the reporter implementation. Remote issue reporting
    remains opt-in via ``reporting_enabled`` and ``kind=\"issue\"``.
    """

    reporting_enabled: bool = False
    kind: str = "local_file"
    platform: str = "github"
    owner: str = ""
    repo: str = ""
    endpoint: str | None = None
    issue_title: str = "ClawCodex Telemetry Inbox"
    mode: str = "update_or_create"
    interval_hours: int = 24
    api_key: str = ""
    token_env: str = ""


@dataclass(frozen=True)
class TelemetryConfig:
    """F-97 configuration.

    All toggles default to off. ``storage_dir`` is expanded at load
    time and rejected if it is empty.
    """

    enabled: bool = False
    storage_dir: Path = field(default_factory=lambda: Path("~/.clawcodex/telemetry"))
    retention_days: int = 30
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)


_ENV_OVERRIDES: Final[tuple[tuple[str, str], ...]] = (
    ("CLAW_TELEMETRY_ENABLED", "enabled"),
    ("CLAW_TELEMETRY_REPORTING_ENABLED", "reporting_enabled"),
    ("CLAW_TELEMETRY_STORAGE_DIR", "storage_dir"),
)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return default


def _section(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def load_config(cwd: str | os.PathLike[str] | None = None) -> TelemetryConfig:
    """Resolve :class:`TelemetryConfig` from config + env overrides.

    Order (lowest → highest precedence):

    1. :class:`TelemetryConfig` dataclass defaults.
    2. ``telemetry`` section of the merged config (loaded via
       :func:`src.config.load_config`); unknown keys are dropped.
    3. Process environment overrides.
    """
    base = TelemetryConfig()

    on_disk_section: dict[str, Any] = {}
    try:
        from src.config import load_config as _load  # type: ignore[import-not-found]

        merged = _load()
        if isinstance(merged, dict):
            on_disk_section = _section(merged, "telemetry")
    except Exception as exc:  # noqa: BLE001
        logger.debug("telemetry: failed to load src.config: %s", exc)

    enabled = _coerce_bool(
        on_disk_section.get("enabled", base.enabled),
        base.enabled,
    )
    storage_raw = on_disk_section.get("storage_dir", str(base.storage_dir))
    storage_dir = Path(os.path.expanduser(str(storage_raw or base.storage_dir)))

    retention_raw = on_disk_section.get("retention_days", base.retention_days)
    try:
        retention_days = max(1, int(retention_raw))
    except (TypeError, ValueError):
        retention_days = base.retention_days

    reporting_section = _section(on_disk_section, "reporting")
    reporting_enabled_raw = reporting_section.get(
        "reporting_enabled",
        reporting_section.get("enabled", base.reporting.reporting_enabled),
    )
    reporting_enabled = _coerce_bool(
        reporting_enabled_raw,
        base.reporting.reporting_enabled,
    )
    reporting_kind = str(
        reporting_section.get("kind", base.reporting.kind) or base.reporting.kind
    )
    reporting_platform = str(
        reporting_section.get("platform", base.reporting.platform) or base.reporting.platform
    )
    reporting_owner = str(reporting_section.get("owner", base.reporting.owner) or "")
    reporting_repo = str(reporting_section.get("repo", base.reporting.repo) or "")
    endpoint_raw = reporting_section.get("endpoint", base.reporting.endpoint)
    reporting_endpoint = str(endpoint_raw).rstrip("/") if endpoint_raw else None
    reporting_issue_title = str(
        reporting_section.get("issue_title", base.reporting.issue_title)
        or base.reporting.issue_title
    )
    reporting_mode = str(
        reporting_section.get("mode", base.reporting.mode) or base.reporting.mode
    )
    interval_raw = reporting_section.get("interval_hours", base.reporting.interval_hours)
    try:
        reporting_interval_hours = max(1, int(interval_raw))
    except (TypeError, ValueError):
        reporting_interval_hours = base.reporting.interval_hours
    reporting_token_env = str(reporting_section.get("token_env", base.reporting.token_env) or "")
    reporting_api_key = str(reporting_section.get("api_key", base.reporting.api_key) or "")
    if reporting_token_env and not reporting_api_key:
        reporting_api_key = os.environ.get(reporting_token_env, "")

    redaction_section = _section(on_disk_section, "redaction")
    redaction_cfg = base.redaction
    if redaction_section:
        try:
            redaction_cfg = RedactionConfig(
                include_command_name=_coerce_bool(
                    redaction_section.get("include_command_name", base.redaction.include_command_name),
                    base.redaction.include_command_name,
                ),
                include_command_args=_coerce_bool(
                    redaction_section.get("include_command_args", base.redaction.include_command_args),
                    base.redaction.include_command_args,
                ),
                include_absolute_paths=_coerce_bool(
                    redaction_section.get("include_absolute_paths", base.redaction.include_absolute_paths),
                    base.redaction.include_absolute_paths,
                ),
                include_stacktrace=_coerce_bool(
                    redaction_section.get("include_stacktrace", base.redaction.include_stacktrace),
                    base.redaction.include_stacktrace,
                ),
                include_prompts=_coerce_bool(
                    redaction_section.get("include_prompts", base.redaction.include_prompts),
                    base.redaction.include_prompts,
                ),
                include_outputs=_coerce_bool(
                    redaction_section.get("include_outputs", base.redaction.include_outputs),
                    base.redaction.include_outputs,
                ),
                stacktrace_max_lines=int(
                    redaction_section.get("stacktrace_max_lines", base.redaction.stacktrace_max_lines)
                ),
                secret_hash_salt=str(
                    redaction_section.get("secret_hash_salt", base.redaction.secret_hash_salt)
                ),
            )
        except (TypeError, ValueError) as exc:
            logger.debug("telemetry: redaction section invalid: %s", exc)
            redaction_cfg = base.redaction

    cfg = TelemetryConfig(
        enabled=enabled,
        storage_dir=storage_dir,
        retention_days=retention_days,
        redaction=redaction_cfg,
        reporting=ReportingConfig(
            reporting_enabled=reporting_enabled,
            kind=reporting_kind,
            platform=reporting_platform,
            owner=reporting_owner,
            repo=reporting_repo,
            endpoint=reporting_endpoint,
            issue_title=reporting_issue_title,
            mode=reporting_mode,
            interval_hours=reporting_interval_hours,
            api_key=reporting_api_key,
            token_env=reporting_token_env,
        ),
    )

    return _apply_env_overrides(cfg)


def _apply_env_overrides(cfg: TelemetryConfig) -> TelemetryConfig:
    enabled = cfg.enabled
    reporting_enabled = cfg.reporting.reporting_enabled
    storage_dir = cfg.storage_dir
    for env_name, field_name in _ENV_OVERRIDES:
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        if field_name == "enabled":
            enabled = _coerce_bool(raw, enabled)
        elif field_name == "reporting_enabled":
            reporting_enabled = _coerce_bool(raw, reporting_enabled)
        elif field_name == "storage_dir":
            storage_dir = Path(os.path.expanduser(raw))
    return TelemetryConfig(
        enabled=enabled,
        storage_dir=storage_dir,
        retention_days=cfg.retention_days,
        redaction=cfg.redaction,
        reporting=ReportingConfig(
            reporting_enabled=reporting_enabled,
            kind=cfg.reporting.kind,
            platform=cfg.reporting.platform,
            owner=cfg.reporting.owner,
            repo=cfg.reporting.repo,
            endpoint=cfg.reporting.endpoint,
            issue_title=cfg.reporting.issue_title,
            mode=cfg.reporting.mode,
            interval_hours=cfg.reporting.interval_hours,
            api_key=cfg.reporting.api_key,
            token_env=cfg.reporting.token_env,
        ),
    )

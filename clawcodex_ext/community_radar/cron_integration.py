"""Cron integration helpers for SR-5.1.

FEATURE_PLAN.md §10.1.8 calls for wiring the radar into the existing
F-22 Cron system. The actual scheduling is done by the F-22 scheduler
(``clawcodex_ext.cron_system``) calling
:func:`clawcodex_ext.community_radar.run_community_scan`. This module
provides the thin adapter so a user (or the bootstrap script) can:

* Register a durable Cron task that fires ``run_community_scan`` on a
  schedule (``install_cron_task``).
* Disable a previously installed task by ID (``uninstall_cron_task``).
* Inspect whether the radar is currently scheduled
  (``get_cron_task_status``).

The helpers use the existing ``CronTask`` + ``CronScheduler`` APIs and
fall back to a no-op when the F-22 module is unavailable (e.g. on a
slim CI image) so importing this module never crashes the radar.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RadarConfig, default_config_path
from .registry import SourceRegistry, default_registry_path

_log = logging.getLogger(__name__)


DEFAULT_CRON_TASK_ID = "community-radar-weekly"
DEFAULT_CRON_PROMPT = (
    "Run the SR-5.1 community radar scan "
    "via run_community_scan(); persist the digest to "
    "~/.clawcodex/reports/community-radar."
)


@dataclass
class CronTaskSummary:
    """Result of :func:`install_cron_task` / :func:`get_cron_task_status`."""

    task_id: str
    installed: bool
    schedule: str
    message: str = ""


# ---------------------------------------------------------------------------
# Cron helpers — F-22 integration. Imports are lazy so the radar can
# run on systems where the Cron subsystem is disabled (e.g. headless CI).
# ---------------------------------------------------------------------------


def _load_cron_models():
    try:
        from clawcodex_ext.cron_system.models import CronTask
    except Exception as exc:  # noqa: BLE001
        _log.debug("CronTask unavailable: %s", exc)
        return None
    return CronTask


def _load_cron_tasks_path() -> Path | None:
    """Resolve ``.claude/scheduled_tasks.json`` for the current workspace.

    Honours ``CLAWCODEX_HOME`` so tests / CI can redirect without
    touching the user home directory.
    """
    try:
        from clawcodex_ext.cron_system.models import (
            SCHEDULED_TASKS_RELATIVE_PATH,
        )
    except Exception:  # noqa: BLE001
        return None
    base = os.environ.get("CLAWCODEX_HOME") or os.environ.get(
        "CLAWCODEX_WORKSPACE_ROOT"
    )
    root = Path(base) if base else Path.cwd()
    return root / SCHEDULED_TASKS_RELATIVE_PATH


def install_cron_task(
    *,
    schedule: str | None = None,
    task_id: str = DEFAULT_CRON_TASK_ID,
    prompt: str = DEFAULT_CRON_PROMPT,
    durable: bool = True,
) -> CronTaskSummary:
    """Install (or replace) the radar's Cron task.

    Returns a :class:`CronTaskSummary`. When the F-22 Cron module is not
    importable the helper degrades to a no-op and returns
    ``installed=False``; this keeps callers' code paths uniform.
    """
    CronTask = _load_cron_models()
    if CronTask is None:
        return CronTaskSummary(
            task_id=task_id,
            installed=False,
            schedule=schedule or "",
            message="F-22 cron system unavailable; nothing installed.",
        )

    config = _load_config_safely()
    cron_expr = schedule or config.cron_schedule

    task = CronTask(
        id=task_id,
        cron=cron_expr,
        prompt=prompt,
        recurring=True,
        durable=bool(durable),
    )

    path = _load_cron_tasks_path()
    if path is None:
        return CronTaskSummary(
            task_id=task_id,
            installed=False,
            schedule=cron_expr,
            message="could not resolve scheduled_tasks.json path",
        )

    try:
        import json

        existing: list[dict[str, Any]] = []
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = raw
            except (OSError, ValueError) as exc:
                _log.warning("failed to read %s: %s; starting fresh", path, exc)
        # Replace any prior entry with the same id.
        remaining = [item for item in existing if item.get("id") != task_id]
        remaining.append(task.to_dict())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(remaining, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — IO is best-effort
        _log.exception("install_cron_task failed: %s", exc)
        return CronTaskSummary(
            task_id=task_id,
            installed=False,
            schedule=cron_expr,
            message=f"failed to write {path}: {exc}",
        )

    _log.info("installed Cron task %s (%s)", task_id, cron_expr)
    return CronTaskSummary(
        task_id=task_id, installed=True, schedule=cron_expr,
        message=f"registered in {path}",
    )


def uninstall_cron_task(
    *, task_id: str = DEFAULT_CRON_TASK_ID
) -> CronTaskSummary:
    """Remove a previously installed radar Cron task."""
    path = _load_cron_tasks_path()
    if path is None or not path.exists():
        return CronTaskSummary(
            task_id=task_id, installed=False, schedule="",
            message="no scheduled_tasks.json found",
        )
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return CronTaskSummary(
                task_id=task_id, installed=False, schedule="",
                message="malformed scheduled_tasks.json",
            )
        remaining = [item for item in raw if item.get("id") != task_id]
        path.write_text(
            json.dumps(remaining, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        return CronTaskSummary(
            task_id=task_id, installed=False, schedule="",
            message=f"failed to mutate {path}: {exc}",
        )
    return CronTaskSummary(
        task_id=task_id, installed=True, schedule="",
        message=f"removed from {path}",
    )


def get_cron_task_status(
    *, task_id: str = DEFAULT_CRON_TASK_ID
) -> CronTaskSummary:
    """Return whether the task is currently registered."""
    path = _load_cron_tasks_path()
    if path is None or not path.exists():
        return CronTaskSummary(
            task_id=task_id, installed=False, schedule="",
            message="no scheduled_tasks.json",
        )
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return CronTaskSummary(
            task_id=task_id, installed=False, schedule="",
            message="unreadable scheduled_tasks.json",
        )
    if not isinstance(raw, list):
        return CronTaskSummary(
            task_id=task_id, installed=False, schedule="",
            message="malformed scheduled_tasks.json",
        )
    for item in raw:
        if isinstance(item, dict) and item.get("id") == task_id:
            return CronTaskSummary(
                task_id=task_id, installed=True,
                schedule=str(item.get("cron", "")),
                message=f"found in {path}",
            )
    return CronTaskSummary(
        task_id=task_id, installed=False, schedule="",
        message=f"no entry in {path}",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_cron_installed(
    *, task_id: str = DEFAULT_CRON_TASK_ID, force: bool = False
) -> CronTaskSummary:
    """Install the Cron task if it is not already registered.

    Phase 3 default: ``RadarConfig.enabled`` is ``True`` so the first
    call to :func:`run_community_scan` registers the durable task. This
    helper is idempotent: when the task already exists it returns a
    ``CronTaskSummary(installed=True)`` without rewriting the file unless
    ``force=True`` is passed.

    When ``RadarConfig.enabled`` is False the helper is a no-op (returns
    ``installed=False``) so users who explicitly disabled the radar do
    not get a surprise schedule.
    """
    config = _load_config_safely()
    if not config.enabled:
        return CronTaskSummary(
            task_id=task_id,
            installed=False,
            schedule=config.cron_schedule,
            message="RadarConfig.enabled=False; not installing Cron task",
        )
    existing = get_cron_task_status(task_id=task_id)
    if existing.installed and not force:
        return existing
    return install_cron_task(schedule=config.cron_schedule, task_id=task_id)


def _load_config_safely() -> RadarConfig:
    """Load RadarConfig from disk without crashing on bad input."""
    path = default_config_path()
    if not path.exists():
        return RadarConfig()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return RadarConfig()
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        else:
            import json
            data = json.loads(text)
    except Exception:  # noqa: BLE001
        return RadarConfig()
    if isinstance(data, dict):
        inner = data.get("community_radar") or data.get("radar") or data
        if isinstance(inner, dict):
            return RadarConfig.from_dict(inner)
    return RadarConfig()


def load_registry_safely() -> SourceRegistry:
    """Best-effort registry loader used by the Cron entry point."""
    path = default_registry_path()
    registry = SourceRegistry(path)
    if not path.exists():
        # Seed the defaults so the very first cron fire still produces
        # a useful digest.
        defaults = SourceRegistry.with_defaults(path)
        try:
            defaults.save()
        except Exception as exc:  # noqa: BLE001
            _log.debug("default seed save failed: %s", exc)
        return defaults
    registry.load()
    return registry


__all__ = [
    "DEFAULT_CRON_PROMPT",
    "DEFAULT_CRON_TASK_ID",
    "CronTaskSummary",
    "install_cron_task",
    "uninstall_cron_task",
    "get_cron_task_status",
    "load_registry_safely",
    "ensure_cron_installed",
]
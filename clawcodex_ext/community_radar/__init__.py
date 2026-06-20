"""SR-5.1 Community Feature Radar.

Public surface for the community radar package. Most consumers should
import from the submodules (e.g. ``from clawcodex_ext.community_radar
import run_community_scan``); this file re-exports the high-level
helpers so external modules can grab everything in one import.

This package implements FEATURE_PLAN.md §10.1 (SR-5.1) entirely inside
``clawcodex_ext/*`` so it never touches ``src/*`` and stays clear of
the upstream-sync audit. The Cron integration in §10.1.8 is provided
by :func:`run_community_scan`, which the F-22 durable task scheduler
calls as ``run_community_scan``.
"""

from __future__ import annotations

from .config import (
    DEFAULT_CRON_SCHEDULE,
    DEFAULT_MAX_FEATURES,
    DEFAULT_OUTPUT_DIR,
    RadarConfig,
    apply_env_overrides,
    default_config_path,
)
from .models import (
    CommunityDigest,
    DigestStats,
    FeatureCategory,
    FeatureRecord,
    FeatureScore,
    FeatureType,
    FetchResult,
    PullRequest,
    Release,
    ScoredFeature,
    WatchSource,
)
from .pipeline import CommunityRadarPipeline, ScanResult, run_community_scan
from .registry import DEFAULT_SOURCES, SourceRegistry, default_registry_path
from .cron_integration import (
    DEFAULT_CRON_PROMPT,
    DEFAULT_CRON_TASK_ID,
    CronTaskSummary,
    install_cron_task,
    uninstall_cron_task,
    get_cron_task_status,
    load_registry_safely,
)

__all__ = [
    # config
    "RadarConfig",
    "apply_env_overrides",
    "default_config_path",
    "DEFAULT_CRON_SCHEDULE",
    "DEFAULT_MAX_FEATURES",
    "DEFAULT_OUTPUT_DIR",
    # models
    "CommunityDigest",
    "DigestStats",
    "FeatureCategory",
    "FeatureRecord",
    "FeatureScore",
    "FeatureType",
    "FetchResult",
    "PullRequest",
    "Release",
    "ScoredFeature",
    "WatchSource",
    # pipeline
    "CommunityRadarPipeline",
    "ScanResult",
    "run_community_scan",
    # registry
    "DEFAULT_SOURCES",
    "SourceRegistry",
    "default_registry_path",
    # cron integration
    "DEFAULT_CRON_PROMPT",
    "DEFAULT_CRON_TASK_ID",
    "CronTaskSummary",
    "install_cron_task",
    "uninstall_cron_task",
    "get_cron_task_status",
    "load_registry_safely",
]
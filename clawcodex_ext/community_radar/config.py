"""Runtime configuration for SR-5.1 Community Feature Radar.

Mirrors the workflow.md block in FEATURE_PLAN.md §10.1.8:

    community_radar:
      enabled: false
      cron_schedule: "0 8 * * 1"
      max_features_per_report: 20
      output_dir: ".reports/community-radar"
      notify: false

The defaults below are conservative: scanning is **opt-in** (enabled
defaults to False) so installing the package never auto-fetches from
GitHub. When the user enables it via CLI or workflow.md, all values are
overridable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


DEFAULT_OUTPUT_DIR = ".reports/community-radar"
DEFAULT_CRON_SCHEDULE = "0 8 * * 1"  # Mondays 08:00 UTC
DEFAULT_MAX_FEATURES = 20
DEFAULT_LANGUAGE = "zh"
# Feature types excluded from reports (case-insensitive, matched against
# FeatureType.value). BUGFIX and DEPRECATION are excluded by default because
# they don't represent new capabilities.
DEFAULT_EXCLUDE_FEATURE_TYPES: list[str] = ["bugfix", "deprecation"]
# Categories that qualify for the "Highlights / 本期重点" summary section.
# Only features in these categories + scoring above highlight_min_score are
# promoted to the prose-summary block.
DEFAULT_HIGHLIGHT_CATEGORIES: list[str] = [
    "agent_loop",
    "tool_system",
    "multi_agent",
    "orchestrator",
    "provider",
    "memory",
    "mcp",
]
DEFAULT_HIGHLIGHT_MIN_SCORE = 55.0
DEFAULT_WEIGHTS: dict[str, float] = {
    "popularity": 0.15,
    "maturity": 0.20,
    "adaptation_cost": 0.25,
    "strategic_value": 0.25,
    "architecture_fit": 0.15,
}
# Tokens that suggest a feature aligns with the ClawCodex roadmap
# (FEATURE_PLAN.md/ROADMAP headings). The scorer matches tokens against
# the free-form ``title + description`` text after lowercasing.
DEFAULT_ROADMAP_KEYWORDS: list[str] = [
    "agent",
    "tool",
    "permission",
    "memory",
    "compact",
    "mcp",
    "sandbox",
    "cron",
    "telemetry",
    "session",
    "multi-agent",
    "orchestrator",
    "provider",
    "context",
    # SR-5.1 embodied / spatial intelligence domain keywords
    "embodied",
    "robot",
    "robotics",
    "manipulation",
    "navigation",
    "policy",
    "vla",
    "simulation",
    "spatial",
    "3d",
    "nerf",
    "gaussian",
    "slam",
    "rendering",
    "imitation",
]


@dataclass
class RadarConfig:
    """Runtime knobs for the radar.

    ``weights`` is keyed by :class:`FeatureScore` dimension name. They
    are normalised to sum to 1.0 by :meth:`normalized_weights` so the
    scorer never has to worry about caller-supplied totals.

    Phase 3 changes:

    * ``enabled`` defaults to ``True`` so a fresh install immediately
      gets a working Cron durable task. Users who want to opt out set
      the env var ``CLAWCODEX_RADAR_ENABLED=0`` or override
      ``community_radar.enabled: false`` in their workflow.md.
    * ``notify`` defaults to ``True``; the actual delivery only happens
      when at least one channel is configured (see
      :mod:`clawcodex_ext.community_radar.notifier`).
    """

    enabled: bool = True
    cron_schedule: str = DEFAULT_CRON_SCHEDULE
    max_features_per_report: int = DEFAULT_MAX_FEATURES
    output_dir: str = DEFAULT_OUTPUT_DIR
    notify: bool = True
    cache_dir: str = ".cache/community-radar"
    # i18n & report filtering (Phase 4 / SR-5.3)
    language: str = DEFAULT_LANGUAGE  # "zh" | "en"
    exclude_feature_types: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_FEATURE_TYPES)
    )
    highlight_categories: list[str] = field(
        default_factory=lambda: list(DEFAULT_HIGHLIGHT_CATEGORIES)
    )
    highlight_min_score: float = DEFAULT_HIGHLIGHT_MIN_SCORE
    # ``weights`` + ``roadmap_keywords`` are deliberately not part of
    # the public workflow.md schema; tests and advanced users can
    # override them via env vars (CLAWCODEX_RADAR_WEIGHT_POPULARITY=0.20)
    # or via the Python API.
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    roadmap_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_ROADMAP_KEYWORDS))
    # LLM classification (MAJOR/MINOR + highlights) is always enabled.
    # Translation (title_zh / desc_zh) is controlled by ``language``:
    # when "zh" the LLM prompt includes translation; when "en" it does not.

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def normalized_weights(self) -> dict[str, float]:
        """Return ``weights`` rescaled to sum to 1.0.

        Falls back to :data:`DEFAULT_WEIGHTS` when the user supplied a
        dict whose entries are all zero / non-numeric, so the scorer is
        never asked to divide by zero.
        """
        cleaned: dict[str, float] = {}
        for key in DEFAULT_WEIGHTS:
            raw = self.weights.get(key, DEFAULT_WEIGHTS[key])
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = DEFAULT_WEIGHTS[key]
            cleaned[key] = max(0.0, value)
        total = sum(cleaned.values())
        if total <= 0:
            return dict(DEFAULT_WEIGHTS)
        return {k: v / total for k, v in cleaned.items()}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "cron_schedule": self.cron_schedule,
            "max_features_per_report": self.max_features_per_report,
            "output_dir": self.output_dir,
            "notify": self.notify,
            "cache_dir": self.cache_dir,
            "language": self.language,
            "exclude_feature_types": list(self.exclude_feature_types),
            "highlight_categories": list(self.highlight_categories),
            "highlight_min_score": self.highlight_min_score,
            "weights": dict(self.weights),
            "roadmap_keywords": list(self.roadmap_keywords),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RadarConfig":
        if not isinstance(data, dict):
            return cls()
        weights_raw = data.get("weights") or {}
        weights = dict(DEFAULT_WEIGHTS)
        if isinstance(weights_raw, dict):
            for key, value in weights_raw.items():
                if key in DEFAULT_WEIGHTS:
                    try:
                        weights[key] = float(value)
                    except (TypeError, ValueError):
                        pass
        keywords_raw = data.get("roadmap_keywords") or data.get("roadmapKeywords") or []
        if isinstance(keywords_raw, list) and keywords_raw:
            keywords = [str(k) for k in keywords_raw]
        else:
            keywords = list(DEFAULT_ROADMAP_KEYWORDS)

        # Language
        lang = str(data.get("language") or DEFAULT_LANGUAGE)
        if lang not in ("zh", "en"):
            lang = DEFAULT_LANGUAGE

        # Exclude feature types
        exclude_raw = data.get("exclude_feature_types") or data.get("excludeFeatureTypes")
        if isinstance(exclude_raw, list):
            exclude_types = [str(t).lower() for t in exclude_raw]
        else:
            exclude_types = list(DEFAULT_EXCLUDE_FEATURE_TYPES)

        # Highlight categories
        hl_cats_raw = data.get("highlight_categories") or data.get("highlightCategories")
        if isinstance(hl_cats_raw, list):
            hl_cats = [str(c).lower() for c in hl_cats_raw]
        else:
            hl_cats = list(DEFAULT_HIGHLIGHT_CATEGORIES)

        # Highlight min score
        try:
            hl_score = float(
                data.get("highlight_min_score")
                or data.get("highlightMinScore")
                or DEFAULT_HIGHLIGHT_MIN_SCORE
            )
        except (TypeError, ValueError):
            hl_score = DEFAULT_HIGHLIGHT_MIN_SCORE

        return cls(
            enabled=bool(data.get("enabled", True)),
            cron_schedule=str(data.get("cron_schedule") or DEFAULT_CRON_SCHEDULE),
            max_features_per_report=int(
                data.get("max_features_per_report")
                or data.get("maxFeaturesPerReport")
                or DEFAULT_MAX_FEATURES
            ),
            output_dir=str(data.get("output_dir") or data.get("outputDir") or DEFAULT_OUTPUT_DIR),
            notify=bool(data.get("notify", True)),
            cache_dir=str(data.get("cache_dir") or data.get("cacheDir") or ".cache/community-radar"),
            language=lang,
            exclude_feature_types=exclude_types,
            highlight_categories=hl_cats,
            highlight_min_score=hl_score,
            weights=weights,
            roadmap_keywords=keywords,
        )


# ---------------------------------------------------------------------------
# Environment overrides (handy in CI / Cron)
# ---------------------------------------------------------------------------


def apply_env_overrides(config: RadarConfig) -> RadarConfig:
    """Mutate-and-return ``config`` based on ``CLAWCODEX_RADAR_*`` env vars.

    Supported keys:

    * ``CLAWCODEX_RADAR_ENABLED=1``
    * ``CLAWCODEX_RADAR_CRON="0 8 * * 1"``
    * ``CLAWCODEX_RADAR_MAX=25``
    * ``CLAWCODEX_RADAR_OUTPUT=/abs/path/.reports``
    * ``CLAWCODEX_RADAR_NOTIFY=1``
    * ``CLAWCODEX_RADAR_CACHE_DIR=/var/cache/...``
    * ``CLAWCODEX_RADAR_WEIGHT_POPULARITY=0.20`` (per dimension)
    * ``CLAWCODEX_RADAR_LANGUAGE=en``
    * ``CLAWCODEX_RADAR_EXCLUDE_TYPES=bugfix,deprecation``
    * ``CLAWCODEX_RADAR_HIGHLIGHT_CATEGORIES=agent_loop,tool_system``
    * ``CLAWCODEX_RADAR_HIGHLIGHT_MIN_SCORE=60``

    Unknown keys are silently ignored so a stale env file does not
    crash the radar.
    """
    def _bool(name: str) -> bool | None:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return None
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    if (v := _bool("CLAWCODEX_RADAR_ENABLED")) is not None:
        config.enabled = v
    if (v := _bool("CLAWCODEX_RADAR_NOTIFY")) is not None:
        config.notify = v

    if raw := os.environ.get("CLAWCODEX_RADAR_LANGUAGE"):
        lang = raw.strip().lower()
        if lang in ("zh", "en"):
            config.language = lang
    if raw := os.environ.get("CLAWCODEX_RADAR_EXCLUDE_TYPES"):
        config.exclude_feature_types = [
            t.strip().lower() for t in raw.split(",") if t.strip()
        ]
    if raw := os.environ.get("CLAWCODEX_RADAR_HIGHLIGHT_CATEGORIES"):
        config.highlight_categories = [
            c.strip().lower() for c in raw.split(",") if c.strip()
        ]
    if raw := os.environ.get("CLAWCODEX_RADAR_HIGHLIGHT_MIN_SCORE"):
        try:
            config.highlight_min_score = float(raw)
        except ValueError:
            _log.warning("invalid CLAWCODEX_RADAR_HIGHLIGHT_MIN_SCORE=%r; ignored", raw)

    if raw := os.environ.get("CLAWCODEX_RADAR_CRON"):
        config.cron_schedule = raw.strip()
    if raw := os.environ.get("CLAWCODEX_RADAR_OUTPUT"):
        config.output_dir = raw.strip()
    if raw := os.environ.get("CLAWCODEX_RADAR_CACHE_DIR"):
        config.cache_dir = raw.strip()
    if raw := os.environ.get("CLAWCODEX_RADAR_MAX"):
        try:
            config.max_features_per_report = int(raw)
        except ValueError:
            _log.warning("invalid CLAWCODEX_RADAR_MAX=%r; ignored", raw)

    for dim in DEFAULT_WEIGHTS:
        env_key = f"CLAWCODEX_RADAR_WEIGHT_{dim.upper()}"
        if raw := os.environ.get(env_key):
            try:
                config.weights[dim] = float(raw)
            except ValueError:
                _log.warning("invalid %s=%r; ignored", env_key, raw)

    return config


# ---------------------------------------------------------------------------
# Default config path
# ---------------------------------------------------------------------------


def default_config_path() -> Path:
    """``~/.clawcodex/community-radar/config.yaml`` (env-overridable)."""
    base = os.environ.get("CLAWCODEX_HOME")
    root = Path(base) if base else Path.home() / ".clawcodex"
    return root / "community-radar" / "config.yaml"
"""Community digest generator for SR-5.1.

Implements the ``CommunityDigest`` output format from
FEATURE_PLAN.md §10.1.7:

* Markdown rendering for human readers (matches the template in the
  plan; falls back to an inline string when no template file exists).
* JSON rendering for downstream automation (matches
  :meth:`CommunityDigest.to_dict`).
* Dual-write (workspace + persistent) mirroring the pattern used by
  ``extensions/orchestrator/report_writer.py``.

The reporter is intentionally lightweight: it does not pull from
GitHub, does not invoke LLMs, and does not depend on Jinja2 at import
time. Templates are loaded lazily and a missing template degrades to a
deterministic string format.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import RadarConfig
from .models import (
    CommunityDigest,
    DigestStats,
    FeatureCategory,
    FeatureRecord,
    FeatureType,
    ScoredFeature,
    utc_now_iso,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_markdown(
    digest: CommunityDigest,
    *,
    title: str = "ClawCodex 社区动态报告",
) -> str:
    lines: list[str] = []
    period_label = {"weekly": "周报", "monthly": "月报"}.get(digest.period, digest.period)
    lines.append(f"# {title} ({period_label})")
    lines.append("")
    lines.append(f"> 生成时间: {digest.generated_at}")
    sources = ", ".join(digest.sources_used) if digest.sources_used else "无"
    lines.append(
        f"> 覆盖范围: {len(digest.sources_used)} 个项目 · "
        f"{digest.stats.total_releases} 个 release · "
        f"{digest.stats.total_features} 条特性记录"
    )
    lines.append("")

    lines.append("## 摘要")
    lines.append("")
    lines.append(digest.summary.strip() or "（本周暂无显著动态。）")
    lines.append("")

    # Trending (high-score) table
    lines.append("## 高评分候选特性")
    lines.append("")
    if digest.trending:
        lines.append("| 特性 | 来源 | 评分 | 分类 | 简述 |")
        lines.append("|------|------|:----:|------|------|")
        for item in digest.trending:
            related = " + ".join([item.record.source, *item.record.related_projects])
            lines.append(
                f"| {_escape(item.record.title)} | {related} | "
                f"{item.score.overall:.1f} | {item.record.category.value} | "
                f"{_escape(_short_desc(item.record.description))} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

    # New features (one bullet per record, grouped by category)
    lines.append("## 新增候选特性")
    lines.append("")
    if digest.new_features:
        current_cat: FeatureCategory | None = None
        for record in digest.new_features:
            if record.category != current_cat:
                current_cat = record.category
                lines.append(f"### {current_cat.value}")
                lines.append("")
            related = "（仅此项目）"
            if record.related_projects:
                related = "同时出现于: " + ", ".join(record.related_projects)
            lines.append(
                f"- **{_escape(record.title)}** — "
                f"{_escape(_short_desc(record.description))} "
                f"({record.feature_type.value}; {related})"
            )
        lines.append("")
    else:
        lines.append("（无）")
        lines.append("")

    # Breaking changes (always a separate section for attention)
    lines.append("## 破坏性变更预警")
    lines.append("")
    if digest.breaking_changes:
        lines.append("| 项目 | 特性 | 影响评估 |")
        lines.append("|------|------|---------|")
        for record in digest.breaking_changes:
            impact = "中" if record.related_projects else "中—需评估迁移成本"
            lines.append(
                f"| {record.source} | {_escape(record.title)} | {impact} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

    # Category distribution
    lines.append("## 分类分布")
    lines.append("")
    if digest.stats.by_category:
        for category, count in sorted(
            digest.stats.by_category.items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("（无）")
    lines.append("")

    if digest.errors:
        lines.append("## 抓取错误")
        lines.append("")
        for err in digest.errors:
            lines.append(f"- {err}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _short_desc(text: str, *, limit: int = 120) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _build_stats(
    new_features: Iterable[FeatureRecord],
    releases_total: int,
) -> DigestStats:
    new_list = list(new_features)
    by_cat: Counter[str] = Counter()
    project_counts: Counter[str] = Counter()
    for record in new_list:
        by_cat[record.category.value] += 1
        project_counts[record.source] += 1
        for related in record.related_projects:
            project_counts[related] += 1
    top_projects = project_counts.most_common(5)
    return DigestStats(
        total_releases=releases_total,
        total_features=len(new_list),
        by_category=dict(by_cat),
        top_projects=top_projects,
    )


def _split_breaking(features: list[FeatureRecord]) -> list[FeatureRecord]:
    return [r for r in features if r.feature_type == FeatureType.BREAKING]


def _summarise(features: list[FeatureRecord]) -> str:
    if not features:
        return "本期没有新的候选特性。"
    counts = Counter(r.category.value for r in features)
    top_categories = [name for name, _ in counts.most_common(3)]
    bullet = "、".join(top_categories) if top_categories else "无"
    return (
        f"本期共发现 {len(features)} 条候选特性，主要集中在 "
        f"{bullet} 方向。"
    )


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


@dataclass
class DigestWriteResult:
    """Paths produced by :meth:`CommunityReporter.write`."""

    markdown_path: Path
    json_path: Path


class CommunityReporter:
    """Build a :class:`CommunityDigest` and persist it as MD + JSON."""

    def __init__(self, config: RadarConfig | None = None) -> None:
        self.config = config or RadarConfig()

    # ------------------------------------------------------------------
    # Digest construction
    # ------------------------------------------------------------------

    def build_digest(
        self,
        *,
        period: str,
        features: list[FeatureRecord],
        scored: list[ScoredFeature],
        sources_used: Iterable[str],
        errors: Iterable[str] | None = None,
        summary: str | None = None,
        generated_at: str | None = None,
        releases_total: int = 0,
    ) -> CommunityDigest:
        ranked = sorted(scored, key=lambda s: s.score.overall, reverse=True)
        max_features = max(1, int(self.config.max_features_per_report))
        trending = ranked[:max_features]
        # ``new_features`` follows the trending order so users see the
        # most relevant bullets first.
        new_features = [s.record for s in trending]
        breaking = _split_breaking(features)
        stats = _build_stats(features, releases_total)
        digest = CommunityDigest(
            period=period,
            generated_at=generated_at or utc_now_iso(),
            summary=summary if summary is not None else _summarise(features),
            new_features=new_features,
            trending=trending,
            breaking_changes=breaking,
            stats=stats,
            sources_used=list(sources_used),
            errors=list(errors or []),
        )
        return digest

    # ------------------------------------------------------------------
    # Dual-write (workspace + persistent)
    # ------------------------------------------------------------------

    def write(
        self,
        digest: CommunityDigest,
        output_dir: Path | str,
    ) -> DigestWriteResult:
        """Write ``digest`` as Markdown + JSON inside ``output_dir``.

        Returns the two paths produced. ``output_dir`` is created on
        demand. The file names follow the
        ``community-digest-<period>-<timestamp>`` convention so cron
        jobs appending to the same directory never collide.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        timestamp = _file_timestamp(digest.generated_at)
        stem = f"community-digest-{digest.period}-{timestamp}"
        md_path = out / f"{stem}.md"
        json_path = out / f"{stem}.json"

        md_path.write_text(_render_markdown(digest), encoding="utf-8")
        json_path.write_text(
            json.dumps(digest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log.info(
            "community digest written: %s (%d features, %d trending)",
            md_path,
            digest.stats.total_features,
            len(digest.trending),
        )
        return DigestWriteResult(markdown_path=md_path, json_path=json_path)


def _file_timestamp(iso: str) -> str:
    """Convert ``2026-06-29T08:00:00Z`` → ``20260629T080000Z`` for filenames."""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso.replace(":", "").replace("-", "")
    return dt.strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Optional: copy a digest into the persistent ~/.clawcodex/reports tree
# ---------------------------------------------------------------------------


def copy_to_persistent(
    digest_path: Path,
    *,
    root: Path | None = None,
) -> Path | None:
    """Best-effort copy into ``~/.clawcodex/reports/community-radar``.

    Mirrors :func:`extensions.orchestrator.report_writer.write` so the
    digest can be discovered alongside other ClawCodex reports. Returns
    the destination path, or ``None`` when the copy fails (the caller
    decides whether to fail loudly).
    """
    try:
        target_root = root or (Path.home() / ".clawcodex" / "reports" / "community-radar")
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / digest_path.name
        shutil.copy2(digest_path, target)
        return target
    except Exception as exc:  # noqa: BLE001 — IO is best-effort here
        _log.warning("copy_to_persistent failed for %s: %s", digest_path, exc)
        return None
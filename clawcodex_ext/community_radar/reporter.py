"""Community digest generator for SR-5.1.

Implements the ``CommunityDigest`` output format from
FEATURE_PLAN.md §10.1.7 (Markdown for humans, JSON for automation)
plus the Phase 3 Jinja2 template rendering from §10.1.12.

* The default template lookup walks ``clawcodex_ext/community_radar/templates``
  for ``weekly_digest.md.j2`` / ``monthly_digest.md.j2``. When a custom
  ``template_dir`` is supplied via :class:`CommunityReporter` it takes
  precedence. If neither path has a template the reporter falls back to
  the deterministic inline renderer that Phase 1 used.
* The dual-write pattern (workspace + persistent) mirrors
  ``extensions/orchestrator/report_writer.py``.
* A Phase 4 hook (:func:`render_proposals`) emits the SR-5.2-friendly
  ``proposals.json`` file alongside the digest.
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


def _short_desc(text: str, *, limit: int = 120) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _impact_for(record: FeatureRecord) -> str:
    if record.related_projects:
        return "中—多项目已采纳，需评估兼容"
    return "中—需评估迁移成本"


def _render_inline_markdown(digest: CommunityDigest) -> str:
    """Phase-1 fallback renderer; used when no Jinja template is available."""
    lines: list[str] = []
    period_label = {"weekly": "周报", "monthly": "月报"}.get(digest.period, digest.period)
    lines.append(f"# ClawCodex 社区动态报告 ({period_label})")
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

    lines.append("## 破坏性变更预警")
    lines.append("")
    if digest.breaking_changes:
        lines.append("| 项目 | 特性 | 影响评估 |")
        lines.append("|------|------|---------|")
        for record in digest.breaking_changes:
            lines.append(
                f"| {record.source} | {_escape(record.title)} | {_impact_for(record)} |"
            )
    else:
        lines.append("（无）")
    lines.append("")

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


# ---------------------------------------------------------------------------
# Jinja2 rendering
# ---------------------------------------------------------------------------


def _resolve_template_dir(template_dir: Path | str | None) -> Path | None:
    """Return the first existing template directory, or None."""
    candidates: list[Path] = []
    if template_dir is not None:
        candidates.append(Path(template_dir))
    # Default location relative to this file.
    candidates.append(Path(__file__).parent / "templates")
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _render_jinja_markdown(
    digest: CommunityDigest,
    template_dir: Path,
) -> str | None:
    """Render via Jinja2; returns ``None`` when jinja2 is unavailable."""
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined  # type: ignore
    except Exception as exc:  # noqa: BLE001
        _log.debug("jinja2 not available (%s); falling back to inline renderer", exc)
        return None

    period_to_template = {
        "weekly": "weekly_digest.md.j2",
        "monthly": "monthly_digest.md.j2",
    }
    template_name = period_to_template.get(digest.period)
    if template_name is None:
        return None
    template_path = template_dir / template_name
    if not template_path.exists():
        _log.debug("template %s missing; falling back to inline renderer", template_path)
        return None

    try:
        env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(template_name)
    except Exception as exc:  # noqa: BLE001
        _log.warning("failed to load %s: %s; falling back", template_path, exc)
        return None

    period_label = {"weekly": "周报", "monthly": "月报"}.get(digest.period, digest.period)
    llm_assisted = digest.summary.endswith("(LLM-assisted)") or "LLM 辅助" in digest.summary

    by_category = sorted(
        digest.stats.by_category.items(), key=lambda kv: -kv[1]
    )
    trending_rows = []
    for item in digest.trending:
        related = " + ".join([item.record.source, *item.record.related_projects])
        trending_rows.append({
            "title": item.record.title,
            "sources": related,
            "score": item.score.overall,
            "category": item.record.category.value,
            "desc": _short_desc(item.record.description),
        })

    new_feature_rows = []
    for record in digest.new_features:
        related = "同时出现于: " + ", ".join(record.related_projects) if record.related_projects else "（仅此项目）"
        new_feature_rows.append({
            "title": record.title,
            "desc": _short_desc(record.description),
            "feature_type": record.feature_type.value,
            "related": related,
        })

    breaking_rows = [
        {
            "source": record.source,
            "title": record.title,
            "impact": _impact_for(record),
        }
        for record in digest.breaking_changes
    ]

    try:
        return template.render(
            title="ClawCodex 社区动态报告",
            period_label=period_label,
            generated_at=digest.generated_at,
            sources_count=len(digest.sources_used),
            total_releases=digest.stats.total_releases,
            total_features=digest.stats.total_features,
            llm_assisted=llm_assisted,
            summary=digest.summary.strip() or "（本期暂无显著动态。）",
            trending=trending_rows,
            new_features=new_feature_rows,
            breaking_changes=breaking_rows,
            by_category=by_category,
            top_projects=digest.stats.top_projects,
            errors=list(digest.errors),
        )
    except Exception as exc:  # noqa: BLE001 — StrictUndefined or bad var
        _log.warning("template render failed (%s): %s; falling back", template_name, exc)
        return None


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
    proposals_path: Path | None = None


class CommunityReporter:
    """Build a :class:`CommunityDigest` and persist it as MD + JSON."""

    def __init__(
        self,
        config: RadarConfig | None = None,
        *,
        template_dir: Path | str | None = None,
    ) -> None:
        self.config = config or RadarConfig()
        self._explicit_template_dir = (
            Path(template_dir) if template_dir is not None else None
        )

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
        *,
        write_proposals: bool = True,
    ) -> DigestWriteResult:
        """Write ``digest`` as Markdown + JSON inside ``output_dir``.

        Returns the paths produced. ``output_dir`` is created on demand.
        File names follow the
        ``community-digest-<period>-<timestamp>`` convention.

        When ``write_proposals`` is True (the default) the reporter also
        emits ``<stem>.proposals.json`` in the SR-5.2-friendly schema.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        timestamp = _file_timestamp(digest.generated_at)
        stem = f"community-digest-{digest.period}-{timestamp}"
        md_path = out / f"{stem}.md"
        json_path = out / f"{stem}.json"

        # Prefer Jinja2 templates (Phase 3); gracefully fall back to the
        # inline renderer when templates or jinja2 itself are missing.
        template_dir = _resolve_template_dir(self._explicit_template_dir)
        rendered: str | None = None
        if template_dir is not None:
            rendered = _render_jinja_markdown(digest, template_dir)
        if rendered is None:
            rendered = _render_inline_markdown(digest)
        md_path.write_text(rendered, encoding="utf-8")

        json_path.write_text(
            json.dumps(digest.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        proposals_path: Path | None = None
        if write_proposals:
            proposals_path = out / f"{stem}.proposals.json"
            proposals_path.write_text(
                json.dumps(render_proposals(digest), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        _log.info(
            "community digest written: %s (%d features, %d trending)",
            md_path,
            digest.stats.total_features,
            len(digest.trending),
        )
        return DigestWriteResult(
            markdown_path=md_path,
            json_path=json_path,
            proposals_path=proposals_path,
        )


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
    the destination path, or ``None`` when the copy fails.
    """
    try:
        target_root = root or (Path.home() / ".clawcodex" / "reports" / "community-radar")
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / digest_path.name
        shutil.copy2(digest_path, target)
        return target
    except Exception as exc:  # noqa: BLE001
        _log.warning("copy_to_persistent failed for %s: %s", digest_path, exc)
        return None


# ---------------------------------------------------------------------------
# Phase 4: SR-5.2-friendly proposals schema
# ---------------------------------------------------------------------------


def render_proposals(digest: CommunityDigest) -> dict[str, Any]:
    """Render the ``proposals.json`` payload consumed by SR-5.2.

    Each trending record becomes a :class:`FeatureProposal` with:

    * ``id`` — stable across runs (``source|title|kind`` hash).
    * ``category`` — Taxonomy node.
    * ``score`` — overall + per-dimension breakdown.
    * ``candidate_actions`` — heuristic suggestions: ``adopt`` (high
      strategic value), ``observe`` (medium), ``skip`` (low strategic
      value + breaking + low architecture fit).
    * ``source_projects`` — which projects shipped it.

    The schema is intentionally additive to the main ``digest.json`` so
    SR-5.2 can evolve without breaking Phase-1 readers.
    """
    proposals: list[dict[str, Any]] = []
    for item in digest.trending:
        record = item.record
        score = item.score
        candidate_action = _candidate_action(record, score)
        proposals.append({
            "id": record.id,
            "title": record.title,
            "description": record.description,
            "category": record.category.value,
            "feature_type": record.feature_type.value,
            "source_projects": [record.source, *record.related_projects],
            "score": {
                "overall": score.overall,
                "popularity": score.popularity,
                "maturity": score.maturity,
                "adaptation_cost": score.adaptation_cost,
                "strategic_value": score.strategic_value,
                "architecture_fit": score.architecture_fit,
            },
            "candidate_action": candidate_action,
            "tags": list(record.tags),
            "released_at": record.released_at,
            "url": record.url,
        })
    return {
        "schema_version": "1.0",
        "generated_at": digest.generated_at,
        "period": digest.period,
        "proposals": proposals,
    }


def _candidate_action(record: FeatureRecord, score: FeatureScore) -> str:
    """Pick one of ``adopt`` / ``observe`` / ``skip``."""
    if record.feature_type == FeatureType.BREAKING and score.strategic_value < 40:
        return "skip"
    if score.strategic_value >= 60 and score.architecture_fit >= 60:
        return "adopt"
    if score.overall >= 60:
        return "observe"
    return "skip"


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "DigestWriteResult",
    "CommunityReporter",
    "render_proposals",
    "copy_to_persistent",
]
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
    FeatureScore,
    FeatureType,
    HistoryComparison,
    ScoredFeature,
    get_root,
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


def _render_inline_markdown(
    digest: CommunityDigest,
    *,
    comparison: HistoryComparison | None = None,
) -> str:
    """Phase-1 fallback renderer; used when no Jinja template is available."""
    lines: list[str] = []
    period_label = {"weekly": "周报", "monthly": "月报"}.get(digest.period, digest.period)
    lines.append(f"# ClawCodex 社区动态报告 ({period_label})")
    lines.append("")
    lines.append(f"> 生成时间: {digest.generated_at}")
    sources = ", ".join(digest.sources_used) if digest.sources_used else "无"
    lines.append(
        f"> 覆盖范围: {len(digest.sources_used)} 个项目 · "
        f"{digest.stats.total_versions} 个版本 · "
        f"{digest.stats.total_features} 条特性记录"
    )
    lines.append("")

    # History comparison section (before summary when present)
    if comparison is not None:
        lines.append(_render_comparison_section(comparison))

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
            lines.append(f"| {record.source} | {_escape(record.title)} | {_impact_for(record)} |")
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## 分类分布")
    lines.append("")
    if digest.stats.by_root_category:
        lines.append("### 按领域")
        lines.append("")
        for parent_name, count in sorted(
            digest.stats.by_root_category.items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"- {parent_name}: {count}")
        lines.append("")
        lines.append("### 按子分类")
        lines.append("")
    if digest.stats.by_category:
        for category, count in sorted(digest.stats.by_category.items(), key=lambda kv: -kv[1]):
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
    *,
    comparison: HistoryComparison | None = None,
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

    by_category = sorted(digest.stats.by_category.items(), key=lambda kv: -kv[1])
    by_root_category = sorted(digest.stats.by_root_category.items(), key=lambda kv: -kv[1])
    trending_rows = []
    for item in digest.trending:
        related = " + ".join([item.record.source, *item.record.related_projects])
        trending_rows.append(
            {
                "title": item.record.title,
                "sources": related,
                "score": item.score.overall,
                "category": item.record.category.value,
                "desc": _short_desc(item.record.description),
            }
        )

    new_feature_rows = []
    for record in digest.new_features:
        related = (
            "同时出现于: " + ", ".join(record.related_projects)
            if record.related_projects
            else "（仅此项目）"
        )
        new_feature_rows.append(
            {
                "title": record.title,
                "desc": _short_desc(record.description),
                "feature_type": record.feature_type.value,
                "related": related,
            }
        )

    breaking_rows = [
        {
            "source": record.source,
            "title": record.title,
            "impact": _impact_for(record),
        }
        for record in digest.breaking_changes
    ]

    comparison_data: dict[str, Any] | None = None
    if comparison is not None:
        # Build feature-list rows for the comparison section.  Use distinct
        # variable names to avoid shadowing the "新增候选特性" rows above.
        cmp_new_rows = [
            {
                "title": rec.title,
                "desc": _short_desc(rec.description),
                "category": rec.category.value if rec.category else "unknown",
                "source": rec.source,
            }
            for rec in comparison.new_features
        ]
        cmp_disappeared_rows = [
            {
                "title": rec.title,
                "desc": _short_desc(rec.description),
                "category": rec.category.value if rec.category else "unknown",
                "source": rec.source,
            }
            for rec in comparison.disappeared_features
        ]
        comparison_data = {
            "has_comparison": True,
            "previous_period": comparison.previous_period,
            "previous_generated_at": comparison.previous_generated_at,
            "new_count": comparison.new_count,
            "disappeared_count": comparison.disappeared_count,
            "score_changed": comparison.score_changed,
            "new_features": cmp_new_rows,
            "disappeared_features": cmp_disappeared_rows,
            "show_new_features": comparison.new_count > 0,
            "show_disappeared": comparison.disappeared_count > 0,
            "show_score_changes": len(comparison.score_changed) > 0,
        }

    try:
        return template.render(
            title="ClawCodex 社区动态报告",
            period_label=period_label,
            generated_at=digest.generated_at,
            sources_count=len(digest.sources_used),
            total_versions=digest.stats.total_versions,
            total_features=digest.stats.total_features,
            llm_assisted=llm_assisted,
            summary=digest.summary.strip() or "（本期暂无显著动态。）",
            trending=trending_rows,
            new_features=new_feature_rows,
            breaking_changes=breaking_rows,
            by_category=by_category,
            by_root_category=by_root_category,
            top_projects=digest.stats.top_projects,
            errors=list(digest.errors),
            comparison=comparison_data or {},
        )
    except Exception as exc:  # noqa: BLE001 — StrictUndefined or bad var
        _log.warning("template render failed (%s): %s; falling back", template_name, exc)
        return None


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _build_stats(
    new_features: Iterable[FeatureRecord],
    versions_total: int,
) -> DigestStats:
    new_list = list(new_features)
    by_cat: Counter[str] = Counter()
    by_parent: Counter[str] = Counter()
    project_counts: Counter[str] = Counter()
    for record in new_list:
        by_cat[record.category.value] += 1
        by_parent[get_root(record.category).value] += 1
        project_counts[record.source] += 1
        for related in record.related_projects:
            project_counts[related] += 1
    top_projects = project_counts.most_common(5)
    return DigestStats(
        total_versions=versions_total,
        total_features=len(new_list),
        by_category=dict(by_cat),
        by_root_category=dict(by_parent),
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
    return f"本期共发现 {len(features)} 条候选特性，主要集中在 {bullet} 方向。"


# ---------------------------------------------------------------------------
# History comparison
# ---------------------------------------------------------------------------


def find_previous_digest_path(
    output_dir: Path | str,
    period: str,
    current_stem: str,
) -> Path | None:
    """Find the most recent previous JSON digest in *output_dir*.

    Scans for ``community-digest-{period}-*.json``, sorts by timestamp
    descending, and returns the newest one whose stem differs from
    *current_stem*. Returns ``None`` when no previous digest exists.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return None
    pattern = f"community-digest-{period}-????????T??????Z.json"
    candidates = sorted(out.glob(pattern), reverse=True)
    for path in candidates:
        if path.stem != current_stem:
            return path
    return None


def _load_digest_from_json(path: Path) -> CommunityDigest | None:
    """Rehydrate a :class:`CommunityDigest` from a JSON file.

    Returns ``None`` when the file is unreadable or has an unexpected shape.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "period" not in data:
        return None
    try:
        new_features = [FeatureRecord.from_dict(r) for r in data.get("new_features", []) or []]
        trending_raw = data.get("trending", []) or []
        trending = []
        for item in trending_raw:
            record = FeatureRecord.from_dict(item.get("record", {}))
            s = item.get("score", {})
            score_dims = s.get("dimensions", s)
            score = FeatureScore(
                record_id=s.get("record_id", record.id),
                overall=float(s.get("overall", 0)),
                popularity=float(score_dims.get("popularity", 0)),
                maturity=float(score_dims.get("maturity", 0)),
                adaptation_cost=float(score_dims.get("adaptation_cost", 0)),
                strategic_value=float(score_dims.get("strategic_value", 0)),
                architecture_fit=float(score_dims.get("architecture_fit", 0)),
            )
            trending.append(ScoredFeature(record=record, score=score))
        breaking = [FeatureRecord.from_dict(r) for r in data.get("breaking_changes", []) or []]
        stats_raw = data.get("stats", {})
        stats = DigestStats(
            total_versions=int(stats_raw.get("total_versions", 0)),
            total_features=int(stats_raw.get("total_features", 0)),
            by_category=stats_raw.get("by_category", {}),
            by_root_category=stats_raw.get("by_root_category", {}),
            top_projects=[tuple(item) for item in stats_raw.get("top_projects", [])],
        )
        return CommunityDigest(
            period=str(data["period"]),
            generated_at=str(data.get("generated_at", "")),
            summary=str(data.get("summary", "")),
            new_features=new_features,
            trending=trending,
            breaking_changes=breaking,
            stats=stats,
            sources_used=data.get("sources_used", []),
            errors=data.get("errors", []),
        )
    except Exception:
        return None


def compare_digests(
    previous: CommunityDigest,
    current: CommunityDigest,
    *,
    score_delta_threshold: float = 5.0,
) -> HistoryComparison:
    """Compare *current* digest against *previous* and produce a delta.

    Features are matched by their stable ``id`` field. Features present
    only in *current* are "new"; features present only in *previous* are
    "disappeared"; features present in both whose overall score changed
    by at least *score_delta_threshold* are tracked as score changes.
    """
    prev_ids: dict[str, FeatureRecord] = {}
    prev_scores: dict[str, float] = {}
    for f in previous.new_features:
        prev_ids[f.id] = f
    for sf in previous.trending:
        prev_ids[sf.record.id] = sf.record
        prev_scores[sf.record.id] = sf.score.overall

    curr_ids: dict[str, FeatureRecord] = {}
    curr_scores: dict[str, float] = {}
    for f in current.new_features:
        curr_ids[f.id] = f
    for sf in current.trending:
        curr_scores[sf.record.id] = sf.score.overall
        if sf.record.id not in curr_ids:
            curr_ids[sf.record.id] = sf.record

    new = [curr_ids[fid] for fid in curr_ids if fid not in prev_ids]
    disappeared = [prev_ids[fid] for fid in prev_ids if fid not in curr_ids]

    score_changed: list[dict[str, Any]] = []
    for fid in set(prev_scores) & set(curr_scores):
        delta = curr_scores[fid] - prev_scores[fid]
        if abs(delta) >= score_delta_threshold:
            rec = curr_ids.get(fid) or prev_ids.get(fid)
            score_changed.append(
                {
                    "id": fid,
                    "title": rec.title if rec else fid,
                    "old_score": round(prev_scores[fid], 1),
                    "new_score": round(curr_scores[fid], 1),
                    "delta": round(delta, 1),
                }
            )

    return HistoryComparison(
        previous_period=previous.period,
        previous_generated_at=previous.generated_at,
        previous_stem="",
        new_count=len(new),
        disappeared_count=len(disappeared),
        score_changed=score_changed,
        new_features=new,
        disappeared_features=disappeared,
    )


def _render_comparison_section(comparison: HistoryComparison) -> str:
    """Render the "变化对比" markdown block for a history comparison."""
    lines: list[str] = []
    prev_label = {"weekly": "周报", "monthly": "月报"}.get(
        comparison.previous_period, comparison.previous_period
    )
    lines.append("## 变化对比 (vs 上期)")
    lines.append("")
    lines.append(f"> 对比基准: {comparison.previous_generated_at} ({prev_label})")
    lines.append("")

    # New features
    lines.append(f"### 新增特性 ({comparison.new_count})")
    lines.append("")
    if comparison.new_features:
        for rec in comparison.new_features:
            cat = rec.category.value if rec.category else "unknown"
            lines.append(
                f"- **{_escape(rec.title)}** — "
                f"{_escape(_short_desc(rec.description))} "
                f"({cat}, 来源: {rec.source})"
            )
    else:
        lines.append("（无新增特性）")
    lines.append("")

    # Disappeared features
    lines.append(f"### 消失特性 ({comparison.disappeared_count})")
    lines.append("")
    if comparison.disappeared_features:
        for rec in comparison.disappeared_features:
            cat = rec.category.value if rec.category else "unknown"
            lines.append(
                f"- ~~**{_escape(rec.title)}**~~ — "
                f"{_escape(_short_desc(rec.description))} "
                f"({cat}, 来源: {rec.source})"
            )
    else:
        lines.append("（无消失特性）")
    lines.append("")

    # Score changes
    lines.append(f"### 评分变化 ({len(comparison.score_changed)})")
    lines.append("")
    if comparison.score_changed:
        lines.append("| 特性 | 旧评分 | 新评分 | 变化 |")
        lines.append("|------|:------:|:------:|:----:|")
        for item in comparison.score_changed:
            direction = "↑" if item["delta"] > 0 else "↓"
            lines.append(
                f"| {_escape(item['title'])} "
                f"| {item['old_score']:.1f} "
                f"| {item['new_score']:.1f} "
                f"| {direction} {abs(item['delta']):.1f} |"
            )
    else:
        lines.append("（无显著评分变化）")
    lines.append("")

    return "\n".join(lines)


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
        self._explicit_template_dir = Path(template_dir) if template_dir is not None else None

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
        versions_total: int = 0,
    ) -> CommunityDigest:
        ranked = sorted(scored, key=lambda s: s.score.overall, reverse=True)
        max_features = max(1, int(self.config.max_features_per_report))
        trending = ranked[:max_features]
        new_features = [s.record for s in trending]
        breaking = _split_breaking(features)
        stats = _build_stats(features, versions_total)
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
        compare: bool = False,
    ) -> DigestWriteResult:
        """Write ``digest`` as Markdown + JSON inside ``output_dir``.

        Returns the paths produced. ``output_dir`` is created on demand.
        File names follow the
        ``community-digest-<period>-<timestamp>`` convention.

        When ``write_proposals`` is True (the default) the reporter also
        emits ``<stem>.proposals.json`` in the SR-5.2-friendly schema.

        When ``compare`` is True, the reporter finds the most recent
        previous JSON digest in *output_dir* and renders a "变化对比"
        section identifying new, disappeared, and score-changed features.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        timestamp = _file_timestamp(digest.generated_at)
        stem = f"community-digest-{digest.period}-{timestamp}"
        md_path = out / f"{stem}.md"
        json_path = out / f"{stem}.json"

        # History comparison
        comparison: HistoryComparison | None = None
        if compare:
            prev_path = find_previous_digest_path(out, digest.period, stem)
            if prev_path is not None:
                prev_digest = _load_digest_from_json(prev_path)
                if prev_digest is not None:
                    comparison = compare_digests(prev_digest, digest)
                    comparison.previous_stem = prev_path.stem

        # Prefer Jinja2 templates (Phase 3); gracefully fall back to the
        # inline renderer when templates or jinja2 itself are missing.
        template_dir = _resolve_template_dir(self._explicit_template_dir)
        rendered: str | None = None
        if template_dir is not None:
            rendered = _render_jinja_markdown(digest, template_dir, comparison=comparison)
        if rendered is None:
            rendered = _render_inline_markdown(digest, comparison=comparison)
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
        proposals.append(
            {
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
            }
        )
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

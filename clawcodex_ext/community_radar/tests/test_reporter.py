"""Tests for clawcodex_ext.community_radar.reporter."""

from __future__ import annotations

import json
from pathlib import Path

from clawcodex_ext.community_radar.config import RadarConfig
from clawcodex_ext.community_radar.models import (
    CommunityDigest,
    DigestStats,
    FeatureCategory,
    FeatureRecord,
    FeatureScore,
    FeatureType,
    ScoredFeature,
    utc_now_iso,
)
from clawcodex_ext.community_radar.reporter import (
    CommunityReporter,
    _render_markdown,
)


def _record(
    *,
    title: str = "Sample",
    description: str = "A description",
    source: str = "aider",
    category: FeatureCategory = FeatureCategory.TOOL_SYSTEM,
    feature_type: FeatureType = FeatureType.NEW,
    related: list[str] | None = None,
) -> FeatureRecord:
    return FeatureRecord(
        id="r1",
        source=source,
        title=title,
        description=description,
        category=category,
        feature_type=feature_type,
        related_projects=list(related or []),
        released_at="2026-06-15T00:00:00Z",
    )


def test_render_markdown_includes_table() -> None:
    record = _record()
    score = FeatureScore(
        record_id=record.id, overall=72.0, popularity=80.0,
        maturity=70.0, adaptation_cost=65.0, strategic_value=75.0,
        architecture_fit=70.0,
    )
    digest = CommunityDigest(
        period="weekly",
        generated_at=utc_now_iso(),
        summary="本期内容。",
        new_features=[record],
        trending=[ScoredFeature(record=record, score=score)],
        breaking_changes=[],
        stats=DigestStats(total_releases=1, total_features=1, by_category={"tool_system": 1}),
        sources_used=["aider"],
    )
    md = _render_markdown(digest)
    assert "# ClawCodex 社区动态报告" in md
    assert "| Sample" in md
    assert "tool_system" in md
    assert "本期内容。" in md


def test_reporter_write_produces_md_and_json(tmp_path: Path) -> None:
    record = _record(title="Write me", description="writes")
    score = FeatureScore(
        record_id=record.id, overall=72.0, popularity=80.0,
        maturity=70.0, adaptation_cost=65.0, strategic_value=75.0,
        architecture_fit=70.0,
    )
    reporter = CommunityReporter(RadarConfig(max_features_per_report=5))
    digest = reporter.build_digest(
        period="weekly",
        features=[record],
        scored=[ScoredFeature(record=record, score=score)],
        sources_used=["aider"],
        releases_total=1,
        summary="hello",
    )
    write_result = reporter.write(digest, tmp_path)
    assert write_result.markdown_path.exists()
    assert write_result.json_path.exists()

    payload = json.loads(write_result.json_path.read_text(encoding="utf-8"))
    assert payload["period"] == "weekly"
    assert payload["stats"]["total_features"] == 1
    assert payload["trending"][0]["record"]["title"] == "Write me"


def test_reporter_handles_empty_input(tmp_path: Path) -> None:
    reporter = CommunityReporter(RadarConfig())
    digest = reporter.build_digest(
        period="monthly",
        features=[],
        scored=[],
        sources_used=[],
        releases_total=0,
    )
    assert digest.stats.total_features == 0
    md = _render_markdown(digest)
    assert "（无）" in md


def test_breaking_changes_surface_in_digest(tmp_path: Path) -> None:
    breaking = _record(
        title="StateGraph refactor",
        description="API refactor",
        feature_type=FeatureType.BREAKING,
        source="langgraph",
    )
    digest = CommunityDigest(
        period="weekly",
        generated_at=utc_now_iso(),
        summary="breaking",
        new_features=[breaking],
        trending=[ScoredFeature(
            record=breaking,
            score=FeatureScore(
                record_id=breaking.id, overall=50.0, popularity=50.0,
                maturity=30.0, adaptation_cost=40.0, strategic_value=50.0,
                architecture_fit=50.0,
            ),
        )],
        breaking_changes=[breaking],
        stats=DigestStats(total_releases=1, total_features=1),
        sources_used=["langgraph"],
    )
    md = _render_markdown(digest)
    assert "## 破坏性变更预警" in md
    assert "StateGraph refactor" in md
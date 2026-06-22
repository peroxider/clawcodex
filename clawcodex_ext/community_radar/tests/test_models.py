"""Tests for clawcodex_ext.community_radar.models."""

from __future__ import annotations

from clawcodex_ext.community_radar.models import (
    FeatureCategory,
    FeatureRecord,
    FeatureScore,
    FeatureType,
    Release,
    WatchSource,
    make_feature_id,
)


def test_watch_source_roundtrip() -> None:
    raw = {
        "name": "aider",
        "repo": "paul-gauthier/aider",
        "track_releases": True,
        "track_commits": True,
        "track_prs": False,
        "release_tag_filter": r"\d+\.\d+\.\d+",
        "changelog_path": "aider/CHANGELOG.md",
        "notes": "Python 生态最活跃的编码 Agent",
        "roadmap_keywords": ["lint", "edit"],
    }
    src = WatchSource.from_dict(raw)
    assert src.name == "aider"
    assert src.track_commits is True
    assert src.roadmap_keywords == ["lint", "edit"]
    again = WatchSource.from_dict(src.to_dict())
    assert again.repo == src.repo
    assert again.notes == src.notes


def test_watch_source_validation() -> None:
    import pytest

    with pytest.raises(ValueError):
        WatchSource.from_dict({"name": "", "repo": "x/y"})
    with pytest.raises(ValueError):
        WatchSource.from_dict({"name": "ok", "repo": "missing-slash"})


def test_make_feature_id_stable() -> None:
    a = make_feature_id("aider", "Add lint auto-fix", "new")
    b = make_feature_id("aider", "Add lint auto-fix", "new")
    assert a == b
    c = make_feature_id("aider", "add lint auto-fix", "new")
    assert c == a  # case-insensitive on title
    d = make_feature_id("aider", "Add lint auto-fix", "enhancement")
    assert d != a


def test_feature_record_roundtrip() -> None:
    record = FeatureRecord(
        id="abc123",
        source="aider",
        title="Lint auto-fix",
        description="Aider now auto-fixes lint errors",
        category=FeatureCategory.TOOL_SYSTEM,
        feature_type=FeatureType.NEW,
        released_at="2026-06-15T00:00:00Z",
        url="https://example.com/aider/v1.2.3",
        related_projects=["claude-code"],
        tags=["lint"],
    )
    again = FeatureRecord.from_dict(record.to_dict())
    assert again.category == FeatureCategory.TOOL_SYSTEM
    assert again.feature_type == FeatureType.NEW
    assert again.related_projects == ["claude-code"]


def test_release_to_dict_roundtrip() -> None:
    rel = Release(
        tag="v1.2.3",
        name="Release v1.2.3",
        body="## Added\n- new feature\n",
        published_at="2026-06-15T00:00:00Z",
        url="https://example.com/release/v1.2.3",
        is_prerelease=False,
    )
    again = Release.from_dict(rel.to_dict())
    assert again.tag == "v1.2.3"
    assert again.body.startswith("## Added")
    assert again.is_prerelease is False


def test_feature_score_to_dict() -> None:
    score = FeatureScore(
        record_id="abc",
        overall=72.5,
        popularity=80.0,
        maturity=70.0,
        adaptation_cost=65.0,
        strategic_value=75.0,
        architecture_fit=70.0,
    )
    payload = score.to_dict()
    assert payload["overall"] == 72.5
    assert payload["dimensions"]["popularity"] == 80.0
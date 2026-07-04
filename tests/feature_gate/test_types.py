"""Tests for ``clawcodex_ext.feature_gate.types``."""

import pytest

from clawcodex_ext.feature_gate.types import FeatureFlag


class TestFeatureFlag:
    """Test the FeatureFlag dataclass."""

    def test_basic_creation(self):
        flag = FeatureFlag(name="test_feature")
        assert flag.name == "test_feature"
        assert flag.default is False
        assert flag.deps == []
        assert flag.mutex_with == []
        assert flag.description == ""

    def test_full_creation(self):
        flag = FeatureFlag(
            name="agentic_mode",
            default=True,
            deps=["experimental_tools"],
            mutex_with=["plain_chat"],
            description="Enable agentic multi-step planning",
        )
        assert flag.name == "agentic_mode"
        assert flag.default is True
        assert flag.deps == ["experimental_tools"]
        assert flag.mutex_with == ["plain_chat"]
        assert flag.description == "Enable agentic multi-step planning"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            FeatureFlag(name="")

    def test_duplicate_deps_deduplicated(self):
        flag = FeatureFlag(
            name="test",
            deps=["a", "b", "a", "c", "b"],
        )
        assert flag.deps == ["a", "b", "c"]

    def test_duplicate_mutex_deduplicated(self):
        flag = FeatureFlag(
            name="test",
            mutex_with=["x", "y", "x"],
        )
        assert flag.mutex_with == ["x", "y"]

    def test_invalid_dep_type_raises(self):
        with pytest.raises(TypeError):
            FeatureFlag(name="test", deps=[1, 2])  # type: ignore[list-item]

    def test_invalid_mutex_type_raises(self):
        with pytest.raises(TypeError):
            FeatureFlag(name="test", mutex_with=[None])  # type: ignore[list-item]

    def test_default_false(self):
        flag = FeatureFlag(name="no_default")
        assert flag.default is False

    def test_default_true(self):
        flag = FeatureFlag(name="yes_default", default=True)
        assert flag.default is True

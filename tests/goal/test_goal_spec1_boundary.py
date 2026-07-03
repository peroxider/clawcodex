"""Spec-1 package boundary tests for the goal subsystem."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "clawcodex_ext.goal.controller",
        "clawcodex_ext.goal.registry",
        "clawcodex_ext.goal.state_machine",
        "clawcodex_ext.goal.storage",
        "clawcodex_ext.goal.tool",
        "clawcodex_ext.goal.types",
    ],
)
def test_legacy_goal_v1_modules_are_removed(module_name: str):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


def test_goal_package_only_exposes_spec1_skeleton():
    goal_pkg = importlib.import_module("clawcodex_ext.goal")

    assert hasattr(goal_pkg, "GOAL_COMMAND")
    assert hasattr(goal_pkg, "goal_enabled")
    assert not hasattr(goal_pkg, "GoalTool")
    assert not hasattr(goal_pkg, "GoalStateRegistry")

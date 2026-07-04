from __future__ import annotations

import importlib


def _load_module(monkeypatch):
    monkeypatch.syspath_prepend("scripts/ci")
    return importlib.import_module("pytest_targets")


def test_changed_pytest_files_filter_and_normalize(monkeypatch):
    pytest_targets = _load_module(monkeypatch)

    selected = pytest_targets.changed_pytest_files(
        [
            "src/query/engine.py",
            "\ufefftests/api/test_api_retry.py",
            "tests/api/helpers.py",
            r"tests\bridge\test_bridge_api.py",
            "tests/agent/test_agent_loop.py",
            "tests/misc/example_test.py",
        ],
        exclude_prefixes=("tests/agent/",),
    )

    assert selected == [
        "tests/api/test_api_retry.py",
        "tests/bridge/test_bridge_api.py",
        "tests/misc/example_test.py",
    ]


def test_targets_for_preset_preserves_smoke_and_appends_unique_changed_tests(monkeypatch):
    pytest_targets = _load_module(monkeypatch)

    targets = pytest_targets.targets_for_preset(
        "core",
        [
            "tests/fast/test_fast_mode.py",
            "tests/api/test_api_retry.py",
            "tests/api/test_api_retry.py",
            "tests/orchestrator/test_orchestrator_dashboard.py",
        ],
        exclude_prefixes=("tests/orchestrator/",),
    )

    assert targets[: len(pytest_targets.CORE_PYTEST)] == list(pytest_targets.CORE_PYTEST)
    assert "tests/fast/test_fast_mode.py" not in targets
    assert "tests/api/test_api_retry.py" in targets
    assert "tests/orchestrator/test_orchestrator_dashboard.py" not in targets


def test_stability_gate_preset_covers_directory_without_duplicate_changed_files(monkeypatch):
    pytest_targets = _load_module(monkeypatch)

    targets = pytest_targets.targets_for_preset(
        "stability-gate",
        [
            "tests/stability_gate/test_stage1_imports.py",
            "tests/api/test_api_retry.py",
        ],
        include_prefixes=("tests/stability_gate/",),
    )

    assert targets == ["tests/stability_gate"]

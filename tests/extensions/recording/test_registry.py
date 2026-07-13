"""Tests for the RecordableSource registry (F-REC)."""

from __future__ import annotations

from extensions.capabilities.recorder import AsciicastCapture, RecordableSource
from extensions.recording.registry import (
    RecordableSourceRegistry,
    get_default_registry,
    register_source,
    reset_default_registry,
)


class _StubCapture:
    def emit(self, event) -> None:  # noqa: ARG002 - stub
        pass

    def marker(self, label, text=""):  # noqa: ARG002 - stub
        pass

    def resize(self, cols, rows):  # noqa: ARG002 - stub
        pass

    def close(self) -> None:
        pass


class _StubSource:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def open(self, capture: AsciicastCapture) -> None:  # noqa: ARG002 - stub
        pass

    def close(self) -> None:
        pass


def _factory(name: str):
    def _make(capture: AsciicastCapture) -> RecordableSource:  # noqa: ARG001
        return _StubSource(name)
    return _make


def test_registry_register_and_get() -> None:
    reg = RecordableSourceRegistry()
    reg.register("foo", _factory("foo"))
    assert reg.has("foo")
    assert reg.get("foo") is not None
    # Get with leading/trailing whitespace + case mismatch — registry
    # must normalize on lookup.
    assert reg.has(" FOO ")


def test_registry_rejects_empty_source_id() -> None:
    reg = RecordableSourceRegistry()
    try:
        reg.register("", _factory(""))
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty source_id")


def test_registry_unregister_returns_true_on_hit_false_on_miss() -> None:
    reg = RecordableSourceRegistry()
    reg.register("a", _factory("a"))
    assert reg.unregister("a") is True
    assert reg.unregister("a") is False


def test_registry_names_returns_sorted_list() -> None:
    reg = RecordableSourceRegistry()
    reg.register("zeta", _factory("zeta"))
    reg.register("alpha", _factory("alpha"))
    reg.register("mu", _factory("mu"))
    assert reg.names() == ["alpha", "mu", "zeta"]


def test_registry_clear_removes_all() -> None:
    reg = RecordableSourceRegistry()
    reg.register("a", _factory("a"))
    reg.register("b", _factory("b"))
    reg.clear()
    assert len(reg) == 0
    assert not reg.has("a")


def test_registry_iter_yields_pairs_safely() -> None:
    reg = RecordableSourceRegistry()
    reg.register("a", _factory("a"))
    reg.register("b", _factory("b"))
    pairs = list(reg)
    assert {name for name, _ in pairs} == {"a", "b"}


def test_default_registry_loads_builtin_sources() -> None:
    """Importing the package should register the 5 built-in factories.

    Note: ``_factories`` runs its ``register_source(...)`` calls at module
    import time and only once per process. So this test must NOT reset
    the default registry first — that would drop the cached registry
    without re-running the factories' registration code. To validate
    the registration side-effect in a clean process, run this test
    alone (``pytest tests/extensions/recording/test_registry.py``).
    """
    import extensions.recording  # noqa: F401

    reg = get_default_registry()
    expected = {"orchestrator", "sop", "visualizer", "cron", "query"}
    assert expected.issubset(set(reg.names()))


def test_register_source_default_registry_helper() -> None:
    reset_default_registry()
    register_source("custom", _factory("custom"))
    assert get_default_registry().has("custom")


def test_default_registry_is_singleton_per_process() -> None:
    reset_default_registry()
    a = get_default_registry()
    b = get_default_registry()
    assert a is b


def test_reset_default_registry_drops_cache() -> None:
    register_source("temp", _factory("temp"))
    assert get_default_registry().has("temp")
    reset_default_registry()
    assert not get_default_registry().has("temp")
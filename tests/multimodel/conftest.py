from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def enable_multimodel_feature():
    from clawcodex_ext.feature_gate import get_registry

    registry = get_registry()
    registry.set_override("MULTIMODEL", True)
    yield
    registry.clear_override("MULTIMODEL")

"""The single LKB feature flag with a host-optional fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PLAN_GRAPH_FEATURE_NAME = "LKB_PLAN_GRAPH"


# LKB 内置简化版 FeatureRegistry — 仅支持 env 变量 + 默认值。
# 不支持 deps/mutex/config persistence（lkb 用不到），保持最小实现。
@dataclass
class _LkbFeatureFlag:
    name: str
    default: bool = False


@dataclass
class _LkbRegistry:
    _flags: dict[str, _LkbFeatureFlag] = field(default_factory=dict)

    def register(self, flag: _LkbFeatureFlag) -> None:
        self._flags[flag.name] = flag

    def is_enabled(self, name: str) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        env_val = os.environ.get(f"LKB_FEATURE_{name}")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return flag.default


_LKB_REGISTRY = _LkbRegistry()
for _flag in (_LkbFeatureFlag(PLAN_GRAPH_FEATURE_NAME, default=False),):
    _LKB_REGISTRY.register(_flag)


def _try_clawcodex_feature_gate():
    """可选注入 clawcodex_ext.feature_gate（如在 clawcodex 环境内运行）。"""
    try:
        from clawcodex_ext.feature_gate import get_registry, register_defaults

        register_defaults()
        return get_registry()
    except ImportError:
        return None


def is_plan_graph_enabled() -> bool:
    """Return whether the persistent Plan Graph owns Task-v2 state."""
    claw_reg = _try_clawcodex_feature_gate()
    if claw_reg is not None:
        return claw_reg.is_enabled(PLAN_GRAPH_FEATURE_NAME)
    return _LKB_REGISTRY.is_enabled(PLAN_GRAPH_FEATURE_NAME)


__all__ = ["PLAN_GRAPH_FEATURE_NAME", "is_plan_graph_enabled"]

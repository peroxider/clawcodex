"""Compatibility shim — delegate to lkb.flags with clawcodex_ext.feature_gate registration."""

from lkb.flags import (  # noqa: F401
    CAUSAL_FEATURE_NAME,
    FEATURE_NAME,
    LLM_FACTS_FEATURE_NAME,
    is_causal_verification_enabled,
    is_llm_facts_enabled,
    is_logical_kanban_enabled,
)

# 在 clawcodex 环境内，向 clawcodex_ext.feature_gate 注册 lkb 的 flags，
# 这样 clawcodex 的 `--enable LKB_CAUSAL` 也能控制 lkb 行为。
def _register_with_clawcodex() -> None:
    try:
        from clawcodex_ext.feature_gate import FeatureFlag, get_registry, register_defaults

        register_defaults()
        reg = get_registry()
        # Idempotent registration: skip if already registered by register_defaults
        for name, default in [
            (FEATURE_NAME, True),
            (CAUSAL_FEATURE_NAME, False),
            (LLM_FACTS_FEATURE_NAME, False),
        ]:
            try:
                reg.register(FeatureFlag(name=name, default=default))
            except ValueError:
                pass  # already registered — that's fine
    except ImportError:
        pass


_register_with_clawcodex()
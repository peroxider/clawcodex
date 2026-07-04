"""src/services/feature_gate/__init__.py — re-export from canonical Layer 1.

Per the decoupling mandate, the canonical Feature Gate implementation lives
in ``clawcodex_ext/feature_gate/`` (Layer 1).  This module re-exports the
public API so that upstream ``src/`` code can import from the expected
``src.services.feature_gate`` namespace without duplicating code.

# TODO: upstream-fixable — once upstream adopts the feature-gate system
natively, this shim can be removed and ``src/`` can import directly.
"""

from __future__ import annotations

from clawcodex_ext.services.feature_gate import (  # noqa: F401
    ConfigStore,
    FeatureConfigStore,
    FeatureFlag,
    FeatureRegistry,
    add_feature_gate_args,
    apply_feature_gate_args,
    conditional_register,
    feature_gated,
    feature_gated_class,
    feature_gated_function,
    get_registry,
    guarded_call,
    guarded_is_enabled,
    handle_list_features,
    register_defaults,
    reset_registry,
    run_feature_command,
)

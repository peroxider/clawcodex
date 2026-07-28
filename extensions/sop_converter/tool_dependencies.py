# Backward-compatibility stub — re-exports from core/tool_dependencies.py
from extensions.sop_converter.core.tool_dependencies import *  # noqa: F401, F403

# ``import *`` omits leading-underscore names. Compat callers (package-root
# ``tool_registry_bridge``, tests) still import these privately — re-export
# them explicitly so ``from .tool_dependencies import _PRIMITIVE_TYPES`` works.
from extensions.sop_converter.core.tool_dependencies import (  # noqa: F401
    _PRIMITIVE_TYPES,
    _is_chain_builder_producer,
)

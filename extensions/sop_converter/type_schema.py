# Backward-compatibility stub — re-exports from core/type_schema.py
from extensions.sop_converter.core.type_schema import *  # noqa: F401, F403

# ``import *`` omits leading-underscore names. Tests still import this helper
# via the package-root path — re-export it explicitly.
from extensions.sop_converter.core.type_schema import (  # noqa: F401
    _import_resolved_type,
)

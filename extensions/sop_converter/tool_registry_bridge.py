# Backward-compatibility stub — alias runtime/tool_registry_bridge.py
#
# The former package-root implementation imported ``.heuristics`` / ``.dependency``
# after those packages moved under ``core/``, so convert skipped all wrapper
# registration (``ImportError: cannot import name '_PRIMITIVE_TYPES'`` was the
# first failure from the star-import stub chain). Replace this module with the
# runtime implementation so CLI/tests keep working under the old import path.
from extensions.sop_converter.runtime import tool_registry_bridge as _impl
import sys

sys.modules[__name__] = _impl

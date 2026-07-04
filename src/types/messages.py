"""Facade — types/messages.py moved to clawcodex_ext/types/.

The full typed message hierarchy now lives in
:mod:`clawcodex_ext.types.messages`. This module re-exports
it verbatim so existing ``from src.types.messages import ...``
callers keep working.
"""

import clawcodex_ext.types.messages as _mod

# Use globals().update() instead of star-import so underscore-prefixed
# names (notably _get_field, referenced by src.utils.messages) are also
# available.  Star import (from ... import *) skips names that start
# with '_', and the source module's __all__ deliberately excludes them.
_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('__')}
globals().update(_globals)

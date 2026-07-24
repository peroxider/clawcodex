"""Module-identity bridge to :mod:`clawcodex_ext.permissions.modes`.

Using the implementation module itself preserves private compatibility
helpers such as ``_settings_perms`` that a star-import facade drops.
"""

import sys

from clawcodex_ext.permissions import modes as _implementation

sys.modules[__name__] = _implementation

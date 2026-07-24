"""Compatibility facade — see :mod:`clawcodex_ext.buddy.companion`."""

from clawcodex_ext.buddy.companion import *  # noqa: F401,F403

import sys

from clawcodex_ext.buddy import companion as _implementation

sys.modules[__name__] = _implementation

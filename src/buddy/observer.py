"""Compatibility facade — see :mod:`clawcodex_ext.buddy.observer`."""

from clawcodex_ext.buddy.observer import *  # noqa: F401,F403

import sys

from clawcodex_ext.buddy import observer as _implementation

sys.modules[__name__] = _implementation

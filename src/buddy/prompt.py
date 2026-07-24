"""Compatibility facade — see :mod:`clawcodex_ext.buddy.prompt`."""

from clawcodex_ext.buddy.prompt import *  # noqa: F401,F403

import sys

from clawcodex_ext.buddy import prompt as _implementation

sys.modules[__name__] = _implementation

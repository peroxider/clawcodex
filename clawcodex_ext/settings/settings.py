"""Module-identity bridge to the canonical settings implementation."""

import sys

from src.settings import settings as _implementation

sys.modules[__name__] = _implementation

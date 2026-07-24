"""Module-identity bridge to the canonical configuration module."""

import sys

from src import config as _implementation

sys.modules[__name__] = _implementation

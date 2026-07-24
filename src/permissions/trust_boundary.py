"""Module-identity facade for the downstream trust-boundary implementation."""

from __future__ import annotations

import sys

from clawcodex_ext.permissions import trust_boundary as _module

sys.modules[__name__] = _module

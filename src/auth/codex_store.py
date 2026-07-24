"""Module-identity facade for the downstream Codex credential store."""

from __future__ import annotations

import sys

from clawcodex_ext.auth import codex_store as _module

sys.modules[__name__] = _module

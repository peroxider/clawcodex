"""Module-identity facade for downstream team-memory path handling."""

from __future__ import annotations

import sys

from clawcodex_ext.memdir import team_mem_paths as _module

sys.modules[__name__] = _module

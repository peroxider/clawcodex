"""Compatibility shim — re-export from lkb standalone package.

This module is kept for backward compatibility. All logical_kanban functionality
now lives in the ``lkb`` package at ``extensions/lkb/src/lkb/``.

New code should import directly from ``lkb``:
    from lkb import TaskDecomposer, LogicalKanbanService, ...

Feature flags are registered by ``clawcodex_ext/logical_kanban/flags.py`` shim
(which delegates to ``lkb.flags`` with ``clawcodex_ext.feature_gate`` registration).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _make_local_lkb_importable() -> None:
    """Expose checked-out LKB only when an installed package is unavailable.

    LKB remains independently installable.  This fallback supports source
    checkouts launched through an existing editable ClawCodex entry point,
    whose environment may predate the LKB extraction into ``extensions/lkb``.
    """
    if importlib.util.find_spec("lkb") is not None:
        return

    source_root = Path(__file__).resolve().parents[2] / "extensions" / "lkb" / "src"
    if (source_root / "lkb" / "__init__.py").is_file():
        sys.path.insert(0, str(source_root))


_make_local_lkb_importable()

from lkb import *  # noqa: E402, F401, F403

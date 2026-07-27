"""Public module for the real v0 -> v1 migration (spec §7.13).

The implementation and registry live in :mod:`lkb.migrations`; this module
keeps the version-addressable import path used by store orchestration.
"""

from __future__ import annotations

from lkb.migrations import v0_to_v1

__all__ = ["v0_to_v1"]

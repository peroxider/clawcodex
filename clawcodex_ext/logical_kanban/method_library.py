"""Compatibility shim — delegate to lkb.method_library."""
from lkb.method_library import *  # noqa: F401, F403
from lkb.method_library import _parse_semver  # noqa: F401 — private name used by tests
"""Compatibility shim — delegate to lkb.method_governance."""
from lkb.method_governance import *  # noqa: F401, F403
from lkb.method_governance import _transition  # noqa: F401 — private name used by tests